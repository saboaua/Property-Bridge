"""Connection management for a remote Home Assistant instance."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    ATTR_CONNECTED,
    ATTR_ENTITY_COUNT,
    ATTR_LAST_SEEN,
    ATTR_REMOTE_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_ENTITY_PREFIX,
    CONF_FRIENDLY_NAME_PREFIX,
    CONF_HOST,
    CONF_PORT,
    CONF_PROPERTY_NAME,
    CONF_SECURE,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DOMAIN,
    SIGNAL_CONNECTION_UPDATE,
)

_LOGGER = logging.getLogger(__name__)


class BridgeConnection:
    """Manages a WebSocket connection to a single remote Home Assistant instance.

    This is the core of the integration. In a full implementation it will:
    - Open a WebSocket to the remote HA
    - Subscribe to state_changed and other relevant events
    - Mirror remote entities into the local state machine (with optional prefix)
    - Forward service calls made on mirrored entities back to the remote instance
    - Clean up entities when the connection drops

    The skeleton below provides the public API and lifecycle hooks so the rest
    of the integration (config flow, sensors, unload) works while the real
    WebSocket logic is developed.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the connection object."""
        self.hass = hass
        self.entry = entry
        self._connected = False
        self._last_seen: datetime | None = None
        self._entity_count = 0
        self._remote_version: str | None = None
        self._ws_task: asyncio.Task | None = None
        self._entities: dict[str, Any] = {}

        self.property_name: str = entry.data.get(
            CONF_PROPERTY_NAME, entry.title or "Unknown Property"
        )
        self.host: str = entry.data[CONF_HOST]
        self.port: int = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self.secure: bool = entry.data.get(CONF_SECURE, True)
        self.verify_ssl: bool = entry.data.get(CONF_VERIFY_SSL, True)
        self.access_token: str = entry.data[CONF_ACCESS_TOKEN]
        self.entity_prefix: str = entry.data.get(CONF_ENTITY_PREFIX, "")
        self.friendly_name_prefix: str = entry.data.get(CONF_FRIENDLY_NAME_PREFIX, "")

    @property
    def connected(self) -> bool:
        """Return True if currently connected to the remote instance."""
        return self._connected

    @property
    def last_seen(self) -> datetime | None:
        """Return the last successful communication timestamp."""
        return self._last_seen

    @property
    def entity_count(self) -> int:
        """Return the number of mirrored entities."""
        return self._entity_count

    @property
    def remote_version(self) -> str | None:
        """Return the Home Assistant version reported by the remote instance."""
        return self._remote_version

    async def async_connect(self) -> None:
        """Establish the connection to the remote Home Assistant.

        Raises on permanent failure so config entry setup can mark NotReady.
        """
        _LOGGER.debug(
            "Connecting to remote HA at %s:%s (property: %s)",
            self.host,
            self.port,
            self.property_name,
        )

        # ------------------------------------------------------------------
        # TODO: Real implementation
        # 1. Build WebSocket URL (ws/wss)
        # 2. Authenticate with long-lived access token
        # 3. Subscribe to state_changed (and optionally other events)
        # 4. Fetch initial states and create local entities
        # 5. Start a background task that keeps the connection alive
        # ------------------------------------------------------------------

        # Skeleton: simulate a successful connection for development
        self._connected = True
        self._last_seen = datetime.now()
        self._remote_version = "skeleton"
        self._entity_count = 0

        self._notify_update()

        self._ws_task = self.hass.async_create_background_task(
            self._connection_loop(),
            name=f"property_bridge_{self.property_name}",
        )

        _LOGGER.info(
            "Property Bridge connected to '%s' (%s:%s)",
            self.property_name,
            self.host,
            self.port,
        )

    async def async_disconnect(self) -> None:
        """Cleanly disconnect and remove all mirrored entities."""
        _LOGGER.debug("Disconnecting from '%s'", self.property_name)

        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        # TODO: Remove all entities that were created for this connection

        self._connected = False
        self._entity_count = 0
        self._notify_update()

        _LOGGER.info("Property Bridge disconnected from '%s'", self.property_name)

    async def _connection_loop(self) -> None:
        """Background task that maintains the WebSocket connection."""
        try:
            while True:
                await asyncio.sleep(30)
                if self._connected:
                    self._last_seen = datetime.now()
                    self._notify_update()
        except asyncio.CancelledError:
            _LOGGER.debug(
                "Connection loop for '%s' cancelled", self.property_name
            )
            raise

    @callback
    def _notify_update(self) -> None:
        """Notify listeners (sensors) that connection state changed."""
        async_dispatcher_send(
            self.hass,
            f"{SIGNAL_CONNECTION_UPDATE}_{self.entry.entry_id}",
        )

    def get_status_data(self) -> dict[str, Any]:
        """Return a dict of status attributes for sensors."""
        return {
            ATTR_CONNECTED: self._connected,
            ATTR_LAST_SEEN: self._last_seen.isoformat() if self._last_seen else None,
            ATTR_ENTITY_COUNT: self._entity_count,
            ATTR_REMOTE_VERSION: self._remote_version,
            "property_name": self.property_name,
            "host": self.host,
            "port": self.port,
        }
