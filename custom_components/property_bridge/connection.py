"""Connection management for a remote Home Assistant instance."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_AREA_ID,
    ATTR_CONNECTED,
    ATTR_ENTITY_COUNT,
    ATTR_LABEL_ID,
    ATTR_LAST_SEEN,
    ATTR_MAINTENANCE_ALLOWED,
    ATTR_MAINTENANCE_UNTIL,
    ATTR_REMOTE_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_AREA_ID,
    CONF_CREATE_AREA,
    CONF_CREATE_LABEL,
    CONF_ENTITY_PREFIX,
    CONF_FRIENDLY_NAME_PREFIX,
    CONF_HOST,
    CONF_LABEL_ID,
    CONF_MAINTENANCE_ALLOWED_UNTIL,
    CONF_PORT,
    CONF_PROPERTY_NAME,
    CONF_SECURE,
    CONF_VERIFY_SSL,
    DEFAULT_CREATE_AREA,
    DEFAULT_CREATE_LABEL,
    DEFAULT_PORT,
    DOMAIN,
    SIGNAL_CONNECTION_UPDATE,
)
from .helpers import async_ensure_area, async_ensure_label

_LOGGER = logging.getLogger(__name__)


class BridgeConnection:
    """Manages a WebSocket connection to a single remote Home Assistant instance.

    Also owns property-level metadata: area, label, maintenance window state.
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

        # Area / label
        self.area_id: str | None = entry.options.get(CONF_AREA_ID) or entry.data.get(
            CONF_AREA_ID
        )
        self.label_id: str | None = entry.options.get(CONF_LABEL_ID) or entry.data.get(
            CONF_LABEL_ID
        )

        # Maintenance / consent state
        self.maintenance_requested: bool = False
        self.consent_granted: bool = False
        self.maintenance_allowed_until: datetime | None = None
        until_raw = entry.options.get(CONF_MAINTENANCE_ALLOWED_UNTIL)
        if until_raw:
            try:
                self.maintenance_allowed_until = dt_util.parse_datetime(until_raw)
                if self.maintenance_allowed_until and (
                    self.maintenance_allowed_until > dt_util.utcnow()
                ):
                    self.consent_granted = True
                    self.maintenance_requested = True
            except (TypeError, ValueError):
                self.maintenance_allowed_until = None

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

    @property
    def maintenance_allowed(self) -> bool:
        """Return True if a valid maintenance window is currently open."""
        if not self.maintenance_allowed_until:
            return False
        return self.maintenance_allowed_until > dt_util.utcnow()

    async def async_connect(self) -> None:
        """Establish the connection and ensure area/label exist."""
        _LOGGER.debug(
            "Connecting to remote HA at %s:%s (property: %s)",
            self.host,
            self.port,
            self.property_name,
        )

        # --- Automatic area / label assignment ---
        options = {**self.entry.data, **self.entry.options}
        create_area = options.get(CONF_CREATE_AREA, DEFAULT_CREATE_AREA)
        create_label = options.get(CONF_CREATE_LABEL, DEFAULT_CREATE_LABEL)

        if create_area:
            self.area_id = await async_ensure_area(
                self.hass, self.property_name, self.area_id
            )
        if create_label:
            self.label_id = await async_ensure_label(
                self.hass, self.property_name, self.label_id
            )

        # Persist area/label ids back into options
        if self.area_id or self.label_id:
            new_options = dict(self.entry.options)
            if self.area_id:
                new_options[CONF_AREA_ID] = self.area_id
            if self.label_id:
                new_options[CONF_LABEL_ID] = self.label_id
            self.hass.config_entries.async_update_entry(
                self.entry, options=new_options
            )

        # ------------------------------------------------------------------
        # TODO: Real WebSocket implementation
        # ------------------------------------------------------------------

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
            "Property Bridge connected to '%s' (%s:%s) area=%s label=%s",
            self.property_name,
            self.host,
            self.port,
            self.area_id,
            self.label_id,
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
                    # Expire maintenance window automatically
                    if (
                        self.maintenance_allowed_until
                        and self.maintenance_allowed_until <= dt_util.utcnow()
                    ):
                        self.maintenance_allowed_until = None
                        self.maintenance_requested = False
                        self.consent_granted = False
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
            ATTR_AREA_ID: self.area_id,
            ATTR_LABEL_ID: self.label_id,
            ATTR_MAINTENANCE_ALLOWED: self.maintenance_allowed,
            ATTR_MAINTENANCE_UNTIL: (
                self.maintenance_allowed_until.isoformat()
                if self.maintenance_allowed_until
                else None
            ),
            "property_name": self.property_name,
            "host": self.host,
            "port": self.port,
            "consent_granted": self.consent_granted,
            "maintenance_requested": self.maintenance_requested,
        }
