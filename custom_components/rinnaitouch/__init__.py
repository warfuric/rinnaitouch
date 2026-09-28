"""Set up the Rinnai Touch integration."""

# pylint: disable=duplicate-code
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from pyrinnaitouch import RinnaiCapabilities, RinnaiSystem

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
]

# Discovery waits up to 30 s for the unit's broadcast before trying TCP directly,
# then the connect can take 5 s and the first status about a second more.
SETUP_TIMEOUT = 40

# Entities that only make sense when the unit has the capability, keyed by the
# lower-cased class name that starts their unique_id.
_CAPABILITY_ENTITY_PREFIXES = {
    RinnaiCapabilities.COOLER: (
        "rinnaicoolingmodeswitch",
        "rinnaicallingcoolbinarysensorentity",
        "rinnaicompressorbinarysensorentity",
        "rinnaizonecallingcoolbinarysensorentity",
        "rinnaizonecompressorbinarysensorentity",
    ),
    RinnaiCapabilities.HEATER: (
        "rinnaiheatermodeswitch",
        "rinnaicallingheatbinarysensorentity",
        "rinnaigasvalvebinarysensorentity",
        "rinnaipreheatbinarysensorentity",
        "rinnaizonecallingheatbinarysensorentity",
        "rinnaizonegasvalvebinarysensorentity",
        "rinnaizonepreheatbinarysensorentity",
    ),
    RinnaiCapabilities.EVAP: (
        "rinnaievapmodeswitch",
        "rinnaievapfanswitch",
        "rinnaiwaterpumpswitch",
        "rinnaicoolerbusybinarysensorentity",
        "rinnaipumpoperatingbinarysensorentity",
        "rinnaiprewetbinarysensorentity",
    ),
}

type RinnaiConfigEntry = ConfigEntry[RinnaiSystem]


async def async_setup_entry(hass: HomeAssistant, entry: RinnaiConfigEntry):
    """Set up the rinnaitouch integration from a config entry."""

    ip_address = entry.data.get(CONF_HOST)
    _LOGGER.debug("Get controller with IP: %s", ip_address)
    system = RinnaiSystem.get_instance(ip_address)
    entry.runtime_data = system

    await system.async_start()
    if not await system.async_wait_ready(SETUP_TIMEOUT):
        await RinnaiSystem.async_remove_instance(ip_address)
        raise ConfigEntryNotReady(
            f"No status from the Rinnai unit at {ip_address} within {SETUP_TIMEOUT} s"
        )

    async def _async_stop(_event: Event) -> None:
        await system.async_stop()

    # Unsubscribed on unload, otherwise a reload would leave a stale listener behind
    # that points at the previous library instance.
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_prune_unsupported_entities(hass, entry, system.get_stored_status().capabilities)
    return True


@callback
def _async_prune_unsupported_entities(
    hass: HomeAssistant, entry: ConfigEntry, capabilities: RinnaiCapabilities
) -> None:
    """Remove entities for heating/cooling/evap modules this unit does not have.

    Runs after every platform has registered its entities and with a real status
    in hand, so it cannot race setup or act on an empty capability set.
    """
    if capabilities == RinnaiCapabilities.NONE:
        return
    unsupported = tuple(
        prefix
        for capability, prefixes in _CAPABILITY_ENTITY_PREFIXES.items()
        if capability not in capabilities
        for prefix in prefixes
    )
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id.startswith(unsupported):
            _LOGGER.debug("Removing entity for absent module: %s", reg_entry.entity_id)
            registry.async_remove(reg_entry.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: RinnaiConfigEntry):
    """Unload a config entry."""
    ip_address = entry.data.get(CONF_HOST)
    _LOGGER.debug("Removing controller with IP: %s", ip_address)

    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Entities are still live, so the connection has to stay up for them.
        return False

    await RinnaiSystem.async_remove_instance(ip_address)
    _LOGGER.debug("Controller with IP: %s removed", ip_address)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    # pylint: disable=unused-argument
    return True
