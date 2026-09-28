"""Config-entry lifecycle against a simulated unit: setup, updates, link loss, reload, stop."""
import asyncio
import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from pyrinnaitouch.connection import RinnaiConnection
from pyrinnaitouch.system import RinnaiSystem

from custom_components import rinnaitouch as integration
from custom_components.rinnaitouch.const import DOMAIN

HOST = "127.0.0.1"
ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_NAME: "Rinnai",
    "Zone A": True,
    "Zone B": False,
    "Zone C": False,
    "Zone D": False,
    "Common Zone": False,
}


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="rinnaitouch_127_0_0_1")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


def _entity_ids(hass, domain, needle):
    registry = er.async_get(hass)
    return [
        e.entity_id for e in registry.entities.values()
        if e.platform == DOMAIN and e.domain == domain and needle in e.unique_id
    ]


async def test_setup_connects_and_entities_reflect_the_unit(hass: HomeAssistant, unit, caplog):
    caplog.set_level(logging.WARNING)
    await _setup(hass)
    assert HOST in RinnaiSystem.instances
    assert RinnaiSystem.instances[HOST].is_connected
    state = hass.states.get("climate.rinnai")
    assert state is not None and state.state == "heat"  # simulator: heater on, 22 °C target
    assert state.attributes["temperature"] == 22
    assert state.attributes["hvac_modes"] == ["off", "cool", "heat", "fan_only"]
    assert hass.states.get("binary_sensor.rinnai_connected_sensor").state == "on"
    assert hass.states.get("sensor.rinnai_connection_state").state == "CONNECTED"
    bad = [r for r in caplog.records if r.name.startswith(("custom_components.rinnaitouch", "pyrinnaitouch"))]
    assert not bad, [r.getMessage() for r in bad]


async def test_entities_for_absent_modules_are_pruned_once_after_setup(hass: HomeAssistant, unit):
    await _setup(hass)
    # Simulator: heater + refrigerated cooling present, evaporative absent.
    assert _entity_ids(hass, "switch", "rinnaievapmodeswitch") == []
    assert _entity_ids(hass, "binary_sensor", "rinnaicoolerbusy") == []
    assert _entity_ids(hass, "switch", "rinnaiheatermodeswitch")
    assert _entity_ids(hass, "switch", "rinnaicoolingmodeswitch")


async def test_entities_go_unavailable_while_the_link_is_down(hass: HomeAssistant, unit):
    await _setup(hass)
    assert hass.states.get("climate.rinnai").state == "heat"
    connected_history = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: connected_history.append(event.data["new_state"].state)
        if event.data["entity_id"] == "binary_sensor.rinnai_connected_sensor"
        else None,
    )
    unit.hello = False
    unit.send_status = False  # the TCP session comes straight back, but no status does
    await unit.disconnect_clients()
    await _wait_for(lambda: hass.states.get("climate.rinnai").state == "unavailable")
    assert hass.states.get("switch.rinnai_heater_mode_switch").state == "unavailable"
    assert "off" in connected_history  # the link was reported down while it was down
    unit.send_status = True
    await _wait_for(lambda: hass.states.get("climate.rinnai").state == "heat")
    assert hass.states.get("binary_sensor.rinnai_connected_sensor").state == "on"


async def test_commands_reach_the_unit(hass: HomeAssistant, unit):
    await _setup(hass)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": "climate.rinnai", "temperature": 19}, blocking=True
    )
    await _wait_for(lambda: any('"SP": "19"' in payload for _, payload in unit.commands))


async def test_unreachable_unit_retries_setup(hass: HomeAssistant, no_unit, monkeypatch):
    monkeypatch.setattr(integration, "SETUP_TIMEOUT", 0.5)
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="rinnaitouch_127_0_0_1")
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert HOST not in RinnaiSystem.instances  # nothing left running between retries
    assert not RinnaiConnection._active  # pylint: disable=protected-access


async def test_reload_releases_and_reacquires_the_unit(hass: HomeAssistant, unit):
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert HOST not in RinnaiSystem.instances
    await _wait_for(lambda: not unit._clients)  # pylint: disable=protected-access
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert unit.connections == 2


async def test_unload_unsubscribes_every_entity(hass: HomeAssistant, unit):
    entry = await _setup(hass)
    system = RinnaiSystem.instances[HOST]
    handlers = system._on_updated._Event__eventhandlers  # pylint: disable=protected-access
    state_handlers = system._connection._state_handlers  # pylint: disable=protected-access
    assert len(handlers) > 10 and len(state_handlers) == 3  # 2 entities + the system itself
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert handlers == [] and len(state_handlers) == 1


async def test_home_assistant_stop_disconnects_cleanly(hass: HomeAssistant, unit, caplog):
    caplog.set_level(logging.ERROR)
    await _setup(hass)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    await _wait_for(lambda: not RinnaiSystem.instances[HOST].is_connected)
    await _wait_for(lambda: not unit._clients)  # pylint: disable=protected-access
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_stop_listener_is_removed_on_unload(hass: HomeAssistant, unit):
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    system = RinnaiSystem.instances[HOST]
    stopped = []
    original = system.async_stop

    async def counting_stop():
        stopped.append(1)
        await original()

    system.async_stop = counting_stop
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert stopped == [1]  # exactly the live listener, no stale one from before the reload
