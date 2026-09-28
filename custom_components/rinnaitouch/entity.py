"""Shared lifecycle for entities fed by the pyrinnaitouch worker thread.

The library calls back from its own thread, never from the event loop, so these
mixins only use thread-safe Home Assistant calls: ``schedule_update_ha_state``
hands the state write to the loop. Entities subscribe once they are registered
with Home Assistant and unsubscribe when removed, so a callback can never arrive
for an entity that has no ``hass`` yet or has already gone.
"""
from __future__ import annotations

from pyrinnaitouch import RinnaiSystem
from pyrinnaitouch.pollconnection import RinnaiConnectionState


class RinnaiPushMixin:
    """Refresh state on every status the library receives from the unit.

    Requires ``self._system`` to be set by the entity's ``__init__``.
    """

    _system: RinnaiSystem
    _attr_should_poll = False

    async def async_added_to_hass(self) -> None:
        """Start receiving status updates."""
        await super().async_added_to_hass()
        self._system.subscribe_updates(self._handle_system_update)

    async def async_will_remove_from_hass(self) -> None:
        """Stop receiving status updates."""
        self._system.unsubscribe_updates(self._handle_system_update)
        await super().async_will_remove_from_hass()

    def _handle_system_update(self) -> None:
        """Called from the library's worker thread on every status."""
        if self.hass is None:
            return
        self._on_system_update()
        self.schedule_update_ha_state()

    def _on_system_update(self) -> None:
        """Hook for entities that derive extra data before the state write."""


class RinnaiConnectionStateMixin:
    """Refresh state whenever the connection to the unit changes state.

    Requires ``self._system`` to be set by the entity's ``__init__``. The handler is
    called once on registration with the current state.
    """

    _system: RinnaiSystem
    _attr_should_poll = False

    async def async_added_to_hass(self) -> None:
        """Start receiving connection state changes."""
        await super().async_added_to_hass()
        self._system.register_socket_state_handler(self._handle_connection_state)

    async def async_will_remove_from_hass(self) -> None:
        """Stop receiving connection state changes."""
        self._system.unregister_socket_state_handler(self._handle_connection_state)
        await super().async_will_remove_from_hass()

    def _handle_connection_state(self, state: RinnaiConnectionState) -> None:
        """Called from the library's worker thread on every state change."""
        self._on_connection_state(state)
        if self.hass is not None:
            self.schedule_update_ha_state()

    def _on_connection_state(self, state: RinnaiConnectionState) -> None:
        """Record the new connection state on the entity."""
        raise NotImplementedError
