"""Config flow: probes the unit without starting the library, reports failures."""
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pyrinnaitouch.system import RinnaiSystem

from custom_components.rinnaitouch import config_flow
from custom_components.rinnaitouch.const import DOMAIN
from tests.conftest import closed_tcp_port

USER_INPUT = {
    CONF_HOST: "127.0.0.1",
    CONF_NAME: "Rinnai",
    "Zone A": True,
    "Zone B": False,
    "Zone C": False,
    "Zone D": False,
    "Common Zone": False,
}


async def _submit(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)


async def test_unreachable_host_shows_error_and_starts_nothing(hass, monkeypatch):
    monkeypatch.setattr(config_flow, "RINNAI_TCP_PORT", closed_tcp_port())
    monkeypatch.setattr(config_flow, "CONNECT_TIMEOUT_SECONDS", 1)
    result = await _submit(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert not RinnaiSystem.instances


async def test_reachable_host_creates_entry_then_rejects_duplicate(hass, unit, monkeypatch):
    monkeypatch.setattr(config_flow, "RINNAI_TCP_PORT", unit.tcp_port)
    result = await _submit(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "127.0.0.1"
    await hass.async_block_till_done()
    assert unit.connections >= 1  # the probe, then the real connection from setup

    result = await _submit(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
