"""Config flow: probes the unit without starting the library, reports failures."""
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pyrinnaitouch.system import RinnaiSystem

from custom_components.rinnaitouch.const import DOMAIN

USER_INPUT = {
    CONF_HOST: "192.0.2.10",
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
    def refuse(_host):
        raise OSError("connection refused")

    monkeypatch.setattr("custom_components.rinnaitouch.config_flow._probe_unit", refuse)
    result = await _submit(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert not RinnaiSystem.instances


async def test_reachable_host_creates_entry_then_rejects_duplicate(hass, monkeypatch):
    probes = []
    monkeypatch.setattr(
        "custom_components.rinnaitouch.config_flow._probe_unit", probes.append
    )
    result = await _submit(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.0.2.10"
    assert probes == ["192.0.2.10"]
    await hass.async_block_till_done()

    result = await _submit(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert probes == ["192.0.2.10"]  # not probed again once known
