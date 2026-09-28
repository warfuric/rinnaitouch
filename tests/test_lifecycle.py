"""Config-entry lifecycle: setup, push updates, reload and Home Assistant stop."""
import asyncio
import json
import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from pyrinnaitouch.pollconnection import RinnaiPollConnection
from pyrinnaitouch.system import RinnaiSystem

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

# Captured from a real unit: heater + refrigerated cooling installed, evap absent,
# currently in cooling mode, switched off.
STATUS_JSON = json.loads(
    '[{"SYST": {"CFG": {"MTSP": "N", "NC": "00", "DF": "N", "TU": "C", "CF": "1", "VR": "0183", "CV": "0010", "CC": "043", "ZA": " ", "ZB": " ", "ZC": " ", "ZD": " " }, "AVM": {"HG": "Y", "EC": "N", "CG": "Y", "RA": "N", "RH": "N", "RC": "N" }, "OSS": {"DY": "TUE", "TM": "16:45", "BP": "Y", "RG": "Y", "ST": "N", "MD": "C", "DE": "N", "DU": "N", "AT": "999", "LO": "N" }, "FLT": {"AV": "N", "C3": "000" } } },{"CGOM": {"CFG": {"ZUIS": "N", "ZAIS": "Y", "ZBIS": "Y", "ZCIS": "N", "ZDIS": "N", "CF": "N", "PS": "Y", "DG": "W" }, "OOP": {"ST": "F", "CF": "N", "FL": "00", "SN": "Y" }, "GSS": {"CC": "N", "FS": "N", "CP": "N" }, "APS": {"AV": "N" }, "ZUS": {"AE": "N", "MT": "999" }, "ZAS": {"AE": "N", "MT": "999" }, "ZBS": {"AE": "N", "MT": "999" }, "ZCS": {"AE": "N", "MT": "999" }, "ZDS": {"AE": "N", "MT": "999" } } }]'
)


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id="rinnaitouch_127_0_0_1"
    )
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


async def test_setup_starts_library_once(hass: HomeAssistant, no_network):
    await _setup(hass)
    assert len(no_network) == 1
    assert HOST in RinnaiSystem.instances
    assert hass.states.get("climate.rinnai") is not None
    assert hass.states.get("climate.rinnai").state == "unavailable"


async def test_push_update_from_library_thread_reaches_entities(
    hass: HomeAssistant, caplog
):
    caplog.set_level(logging.WARNING)
    await _setup(hass)
    registry = er.async_get(hass)
    evap_switch = next(
        e.entity_id for e in registry.entities.values()
        if e.platform == DOMAIN and e.domain == "switch" and "evap_mode" in e.entity_id
    )
    assert hass.states.get(evap_switch) is not None

    system = RinnaiSystem.instances[HOST]
    # Exactly what the socket thread does: hand the decoded status to the consumer
    # thread, which then calls every entity back from that thread.
    system._receiverqueue.put(STATUS_JSON)  # pylint: disable=protected-access

    await _wait_for(lambda: hass.states.get("climate.rinnai").state != "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get("climate.rinnai").state == "off"
    assert hass.states.get("climate.rinnai").attributes["hvac_modes"] == [
        "off", "cool", "heat", "fan_only"
    ]
    # First update prunes entities for capabilities the unit lacks (no evap here),
    # via the registry on the event loop.
    await _wait_for(lambda: registry.async_get(evap_switch) is None)
    heater_switch = next(
        e for e in registry.entities.values()
        if e.platform == DOMAIN and e.domain == "switch" and "heater_mode" in e.entity_id
    )
    assert heater_switch is not None

    bad = [r for r in caplog.records if r.name.startswith(("custom_components.rinnaitouch", "pyrinnaitouch"))]
    assert not bad, [r.getMessage() for r in bad]


async def test_reload_releases_and_reacquires_the_unit(hass: HomeAssistant, no_network):
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert HOST not in RinnaiSystem.instances
    assert RinnaiPollConnection.clients[HOST] == 0

    # Previously this second setup raised "Cannot have two connections".
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert len(no_network) == 2


async def test_home_assistant_stop_shuts_the_library_down(hass: HomeAssistant, caplog):
    caplog.set_level(logging.ERROR)
    await _setup(hass)
    assert RinnaiPollConnection.clients[HOST] == 1
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert RinnaiPollConnection.clients[HOST] == 0
    assert "TypeError" not in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_stop_listener_is_removed_on_unload(hass: HomeAssistant):
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert RinnaiPollConnection.clients[HOST] == 0
    # A stale listener would decrement the counter a second time here.
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert RinnaiPollConnection.clients[HOST] == 0
