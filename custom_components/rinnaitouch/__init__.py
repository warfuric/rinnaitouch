"""Set up main entity."""

# pylint: disable=duplicate-code
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers.device_registry import DeviceEntry

from pyrinnaitouch import RinnaiSystem

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
]

type RinnaiConfigEntry = ConfigEntry[RinnaiSystem]


async def async_setup_entry(hass: HomeAssistant, entry: RinnaiConfigEntry):
    """Set up the rinnaitouch integration from a config entry."""

    ip_address = entry.data.get(CONF_HOST)
    _LOGGER.debug("Get controller with IP: %s", ip_address)
    try:
        system: RinnaiSystem = RinnaiSystem.get_instance(ip_address)
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error("Get controller error: %s", err)
        raise ConfigEntryNotReady from err
    entry.runtime_data = system

    async def _async_shutdown(_event: Event) -> None:
        # Joins the socket thread, so keep it off the event loop.
        await hass.async_add_executor_job(system.shutdown)

    # Unsubscribe on unload, otherwise a reload leaves a stale listener behind that
    # points at the previous RinnaiSystem instance.
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_shutdown)
    )

    # Register every entity before the first status can arrive: the main climate
    # entity prunes entities for absent capabilities on its first update.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await hass.async_add_executor_job(system.get_status)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RinnaiConfigEntry):
    """Unload a config entry."""
    ip_address = entry.data.get(CONF_HOST)
    _LOGGER.debug("Removing controller with IP: %s", ip_address)

    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Entities are still live, so the connection has to stay up for them.
        return False

    # remove_instance joins the socket thread (up to 15 s): never on the event loop.
    await hass.async_add_executor_job(RinnaiSystem.remove_instance, ip_address)
    _LOGGER.debug("Controller with IP: %s removed", ip_address)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    # pylint: disable=unused-argument
    return True
