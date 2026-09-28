"""Config flow for rinnai-brivis-wifi."""
import logging
import socket

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .const import (
    DOMAIN,
    CONF_ZONE_A,
    CONF_ZONE_B,
    CONF_ZONE_C,
    CONF_ZONE_D,
    CONF_ZONE_COMMON,
    CONF_TEMP_SENSOR,
    CONF_TEMP_SENSOR_A,
    CONF_TEMP_SENSOR_B,
    CONF_TEMP_SENSOR_C,
    CONF_TEMP_SENSOR_D,
    CONF_TEMP_SENSOR_COMMON,
    DEFAULT_NAME,
)

_LOGGER = logging.getLogger(__name__)

RINNAI_TCP_PORT = 27847
CONNECT_TIMEOUT_SECONDS = 5

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_ZONE_A): bool,
        vol.Optional(CONF_TEMP_SENSOR_A): str,
        vol.Required(CONF_ZONE_B): bool,
        vol.Optional(CONF_TEMP_SENSOR_B): str,
        vol.Required(CONF_ZONE_C): bool,
        vol.Optional(CONF_TEMP_SENSOR_C): str,
        vol.Required(CONF_ZONE_D): bool,
        vol.Optional(CONF_TEMP_SENSOR_D): str,
        vol.Required(CONF_ZONE_COMMON): bool,
        vol.Optional(CONF_TEMP_SENSOR_COMMON): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Optional(CONF_TEMP_SENSOR): str,
    }
)


def _probe_unit(host: str) -> None:
    """Open and immediately close a TCP connection to the unit.

    Raises OSError when the host is unreachable. Deliberately does not start the
    library's threads: the unit only tolerates one client, and a flow that is
    abandoned must not leave a live connection behind.
    """
    with socket.create_connection((host, RINNAI_TCP_PORT), CONNECT_TIMEOUT_SECONDS):
        pass


class RinnaiTouchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rinnai Touch."""

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            user_input[CONF_HOST] = host
            device_id = "rinnaitouch_" + str.replace(host, ".", "_")
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()
            try:
                await self.hass.async_add_executor_job(_probe_unit, host)
            except OSError as err:
                _LOGGER.warning("Could not connect to Rinnai unit at %s: %s", host, err)
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
