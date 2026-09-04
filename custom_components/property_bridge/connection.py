"""Connection management for a remote Home Assistant instance.

Implements real WebSocket entity mirroring:
  - Authenticate with long-lived access token
  - Fetch all states (get_states)
  - Subscribe to state_changed events
  - Mirror entities locally with optional prefix
  - Clean up on disconnect / reconnect with backoff
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
    CONF_EXCLUDE_DOMAINS,
    CONF_FRIENDLY_NAME_PREFIX,
    CONF_HOST,
    CONF_INCLUDE_DOMAINS,
    CONF_LABEL_ID,
    CONF_MAINTENANCE_ALLOWED_UNTIL,
    CONF_PORT,
    CONF_PROPERTY_NAME,
    CONF_SECURE,
    CONF_VERIFY_SSL,
    DEFAULT_CREATE_AREA,
    DEFAULT_CREATE_LABEL,
    DEFAULT_EXCLUDE_DOMAINS,
    DEFAULT_PORT,
    DOMAIN,
    RECONNECT_MAX_DELAY,
    RECONNECT_MIN_DELAY,
    SIGNAL_CONNECTION_UPDATE,
)
from .helpers import async_ensure_area, async_ensure_label

_LOGGER = logging.getLogger(__name__)

_CLOUD_SUFFIXES = (
    ".ui.nabu.casa",
    ".nabu.casa",
    ".duckdns.org",
    ".homeassistant.io",
)


class BridgeConnection:
    """Manages a WebSocket connection to a single remote Home Assistant instance."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._connected = False
        self._last_seen: datetime | None = None
        self._entity_count = 0
        self._remote_version: str | None = None
        self._ws_task: asyncio.Task | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._msg_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._mirrored_entities: set[str] = set()
        self._stop = False
        self._last_error: str | None = None

        self.property_name: str = entry.data.get(
            CONF_PROPERTY_NAME, entry.title or "Unknown Property"
        )
        self.host: str = entry.data[CONF_HOST]
        self.port: int = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self.secure: bool = entry.data.get(CONF_SECURE, True)
        self.verify_ssl: bool = entry.data.get(CONF_VERIFY_SSL, True)
        self.access_token: str = entry.data[CONF_ACCESS_TOKEN]
        self.entity_prefix: str = entry.data.get(CONF_ENTITY_PREFIX, "") or ""
        self.friendly_name_prefix: str = (
            entry.data.get(CONF_FRIENDLY_NAME_PREFIX, "") or ""
        )

        # In-memory only normalization (never write back during WS session)
        self.host, self.secure, self.port = self._normalize_endpoint(
            self.host, self.secure, self.port
        )

        options = {**entry.data, **entry.options}
        include = options.get(CONF_INCLUDE_DOMAINS)
        exclude = options.get(CONF_EXCLUDE_DOMAINS)
        self._include_domains: set[str] | None = set(include) if include else None
        self._exclude_domains: set[str] = (
            set(exclude) if exclude else set(DEFAULT_EXCLUDE_DOMAINS)
        )

        self.area_id: str | None = entry.options.get(CONF_AREA_ID) or entry.data.get(
            CONF_AREA_ID
        )
        self.label_id: str | None = entry.options.get(CONF_LABEL_ID) or entry.data.get(
            CONF_LABEL_ID
        )

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
        return self._connected

    @property
    def last_seen(self) -> datetime | None:
        return self._last_seen

    @property
    def entity_count(self) -> int:
        return self._entity_count

    @property
    def remote_version(self) -> str | None:
        return self._remote_version

    @property
    def maintenance_allowed(self) -> bool:
        if not self.maintenance_allowed_until:
            return False
        return self.maintenance_allowed_until > dt_util.utcnow()

    @staticmethod
    def _normalize_endpoint(
        host: str, secure: bool, port: int | None
    ) -> tuple[str, bool, int]:
        host = (host or "").strip()
        if host.startswith(("http://", "https://")):
            parsed = urlparse(host)
            host = parsed.hostname or host
            if parsed.scheme == "https":
                secure = True
            elif parsed.scheme == "http":
                secure = False
            if parsed.port:
                port = parsed.port
        host = host.split("/")[0].split("?")[0].rstrip("/")

        host_l = host.lower()
        if host_l.endswith(".ui.nabu.casa") or host_l.endswith(".nabu.casa"):
            secure = True
            port = 443
        elif host_l.endswith(".duckdns.org") and secure and port in (
            None, 8123, DEFAULT_PORT
        ):
            port = 443

        if port is None:
            port = 443 if secure else DEFAULT_PORT
        return host, secure, int(port)

    async def async_connect(self) -> None:
        _LOGGER.debug(
            "Connecting to remote HA at %s:%s (property: %s)",
            self.host, self.port, self.property_name,
        )

        options = {**self.entry.data, **self.entry.options}
        if options.get(CONF_CREATE_AREA, DEFAULT_CREATE_AREA):
            self.area_id = await async_ensure_area(
                self.hass, self.property_name, self.area_id
            )
        if options.get(CONF_CREATE_LABEL, DEFAULT_CREATE_LABEL):
            self.label_id = await async_ensure_label(
                self.hass, self.property_name, self.label_id
            )

        if self.area_id or self.label_id:
            new_options = dict(self.entry.options)
            changed = False
            if self.area_id and new_options.get(CONF_AREA_ID) != self.area_id:
                new_options[CONF_AREA_ID] = self.area_id
                changed = True
            if self.label_id and new_options.get(CONF_LABEL_ID) != self.label_id:
                new_options[CONF_LABEL_ID] = self.label_id
                changed = True
            if changed:
                self.hass.config_entries.async_update_entry(
                    self.entry, options=new_options
                )

        self._stop = False
        self._ws_task = self.hass.async_create_background_task(
            self._connection_loop(),
            name=f"property_bridge_{self.property_name}",
        )
        self.entry.async_on_unload(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._on_hass_stop
            )
        )
        _LOGGER.info(
            "Property Bridge starting connection to '%s' (%s:%s secure=%s)",
            self.property_name, self.host, self.port, self.secure,
        )

    async def async_disconnect(self) -> None:
        self._stop = True
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        await self._clear_mirrored_entities()
        self._connected = False
        self._entity_count = 0
        self._notify_update()
        _LOGGER.info("Property Bridge disconnected from '%s'", self.property_name)

    async def _on_hass_stop(self, _event) -> None:
        await self.async_disconnect()

    def _ws_url(self) -> str:
        """Build WebSocket URL (omit standard ports for better proxy compatibility)."""
        scheme = "wss" if self.secure else "ws"
        if self.secure and self.port == 443:
            return f"{scheme}://{self.host}/api/websocket"
        if not self.secure and self.port == 80:
            return f"{scheme}://{self.host}/api/websocket"
        return f"{scheme}://{self.host}:{self.port}/api/websocket"

    async def _connection_loop(self) -> None:
        delay = RECONNECT_MIN_DELAY
        try:
            while not self._stop:
                try:
                    await self._run_session()
                    delay = RECONNECT_MIN_DELAY
                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    self._last_error = f"{type(err).__name__}: {err}"
                    _LOGGER.warning(
                        "WebSocket session for '%s' ended: %s – reconnecting in %ss",
                        self.property_name, self._last_error, delay,
                        exc_info=True,
                    )
                    self._connected = False
                    self._notify_update()
                    await self._clear_mirrored_entities()
                if self._stop:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
        except asyncio.CancelledError:
            raise
        finally:
            await self._clear_mirrored_entities()
            self._connected = False
            self._notify_update()

    async def _run_session(self) -> None:
        # Do NOT call async_update_entry here — it triggers a reload loop.
        session = async_get_clientsession(self.hass)
        url = self._ws_url()
        if not self.secure:
            ssl_param = None
        elif self.verify_ssl:
            ssl_param = True
        else:
            ssl_param = False

        _LOGGER.info(
            "Opening WebSocket to %s for property '%s' (ssl=%s)",
            url, self.property_name, ssl_param,
        )

        async with session.ws_connect(
            url, heartbeat=30, ssl=ssl_param, timeout=aiohttp.ClientTimeout(total=30)
        ) as ws:
            self._ws = ws
            self._msg_id = 1
            self._pending.clear()

            msg = await ws.receive_json()
            if msg.get("type") != "auth_required":
                raise RuntimeError(f"Expected auth_required, got: {msg}")

            await ws.send_json({"type": "auth", "access_token": self.access_token})
            msg = await ws.receive_json()
            if msg.get("type") != "auth_ok":
                raise RuntimeError(f"Auth failed: {msg.get('message', msg)}")

            self._remote_version = msg.get("ha_version", "unknown")
            self._last_seen = dt_util.utcnow()
            _LOGGER.info(
                "Authenticated to '%s' (HA %s) – fetching states…",
                self.property_name, self._remote_version,
            )

            states = await self._send_command(ws, "get_states")
            if isinstance(states, list):
                for state in states:
                    self._apply_remote_state(state)
                self._entity_count = len(self._mirrored_entities)
                _LOGGER.info(
                    "Mirrored %s / %s entities from '%s'",
                    self._entity_count, len(states), self.property_name,
                )
            else:
                _LOGGER.warning(
                    "get_states unexpected payload for '%s': %s",
                    self.property_name, type(states),
                )

            self._connected = True
            self._last_error = None
            self._notify_update()

            await self._send_command(ws, "subscribe_events", event_type="state_changed")
            _LOGGER.info("Subscribed to state_changed for '%s'", self.property_name)

            async for raw in ws:
                if self._stop:
                    break
                if raw.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
                if raw.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    data = raw.json()
                except Exception:
                    continue
                self._last_seen = dt_util.utcnow()
                await self._handle_message(data)
                if (
                    self.maintenance_allowed_until
                    and self.maintenance_allowed_until <= dt_util.utcnow()
                ):
                    self.maintenance_allowed_until = None
                    self.maintenance_requested = False
                    self.consent_granted = False
                    self._notify_update()

    async def _send_command(
        self, ws: aiohttp.ClientWebSocketResponse, cmd_type: str, **kwargs: Any
    ) -> Any:
        msg_id = self._msg_id
        self._msg_id += 1
        fut: asyncio.Future = self.hass.loop.create_future()
        self._pending[msg_id] = fut
        await ws.send_json({"id": msg_id, "type": cmd_type, **kwargs})
        try:
            return await asyncio.wait_for(fut, timeout=30)
        finally:
            self._pending.pop(msg_id, None)

    async def _handle_message(self, data: dict[str, Any]) -> None:
        msg_type = data.get("type")
        if msg_type == "result":
            fut = self._pending.get(data.get("id"))
            if fut and not fut.done():
                if data.get("success"):
                    fut.set_result(data.get("result"))
                else:
                    fut.set_exception(
                        RuntimeError(str(data.get("error", "unknown error")))
                    )
            return
        if msg_type == "event":
            event = data.get("event") or {}
            if event.get("event_type") == "state_changed":
                event_data = event.get("data") or {}
                new_state = event_data.get("new_state")
                entity_id = event_data.get("entity_id")
                if new_state is None and entity_id:
                    self._remove_local_entity(entity_id)
                elif new_state:
                    self._apply_remote_state(new_state)
                    self._entity_count = len(self._mirrored_entities)

    def _should_mirror(self, entity_id: str) -> bool:
        if not entity_id or "." not in entity_id:
            return False
        domain = entity_id.split(".", 1)[0]
        if domain in self._exclude_domains or domain == DOMAIN:
            return False
        if self._include_domains is not None and domain not in self._include_domains:
            return False
        return True

    def _local_entity_id(self, remote_entity_id: str) -> str:
        domain, object_id = remote_entity_id.split(".", 1)
        if self.entity_prefix:
            object_id = f"{self.entity_prefix}{object_id}"
        return f"{domain}.{object_id}"

    def _apply_remote_state(self, state: dict[str, Any]) -> None:
        remote_eid = state.get("entity_id")
        if not remote_eid or not self._should_mirror(remote_eid):
            return
        local_eid = self._local_entity_id(remote_eid)
        attrs = dict(state.get("attributes") or {})
        if self.friendly_name_prefix:
            original = attrs.get("friendly_name") or remote_eid
            attrs["friendly_name"] = f"{self.friendly_name_prefix}{original}"
        attrs["property_bridge_remote"] = self.property_name
        attrs["property_bridge_remote_entity_id"] = remote_eid
        try:
            self.hass.states.async_set(local_eid, state.get("state"), attrs)
            self._mirrored_entities.add(local_eid)
            self._entity_count = len(self._mirrored_entities)
        except Exception as err:
            _LOGGER.debug("Failed to set state for %s: %s", local_eid, err)

    def _remove_local_entity(self, remote_entity_id: str) -> None:
        local_eid = self._local_entity_id(remote_entity_id)
        if local_eid in self._mirrored_entities:
            self.hass.states.async_remove(local_eid)
            self._mirrored_entities.discard(local_eid)
            self._entity_count = len(self._mirrored_entities)
            self._notify_update()

    async def _clear_mirrored_entities(self) -> None:
        for eid in list(self._mirrored_entities):
            try:
                self.hass.states.async_remove(eid)
            except Exception:
                pass
        self._mirrored_entities.clear()
        self._entity_count = 0

    @callback
    def _notify_update(self) -> None:
        async_dispatcher_send(
            self.hass, f"{SIGNAL_CONNECTION_UPDATE}_{self.entry.entry_id}"
        )

    def get_status_data(self) -> dict[str, Any]:
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
            "secure": self.secure,
            "ws_url": self._ws_url(),
            "last_error": self._last_error,
            "consent_granted": self.consent_granted,
            "maintenance_requested": self.maintenance_requested,
        }
