"""Services for Property Bridge – rental presets and maintenance windows."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CALENDAR_ENTITY,
    CONF_CHECKIN_SCENE,
    CONF_CHECKIN_SCRIPT,
    CONF_CHECKOUT_SCENE,
    CONF_CHECKOUT_SCRIPT,
    CONF_MAINTENANCE_ALLOWED_UNTIL,
    CONF_MAINTENANCE_REQUIRE_CONSENT,
    CONF_MAINTENANCE_WINDOW_HOURS,
    CONF_PROPERTY_NAME,
    DEFAULT_MAINTENANCE_WINDOW_HOURS,
    DOMAIN,
    SERVICE_APPLY_CHECKIN,
    SERVICE_APPLY_CHECKOUT,
    SERVICE_CALL_REMOTE,
    SERVICE_END_MAINTENANCE,
    SERVICE_GET_AUTOMATION_CONFIG,
    SERVICE_GRANT_CONSENT,
    SERVICE_LIST_AUTOMATIONS,
    SERVICE_LIST_PROPERTIES,
    SERVICE_PORTFOLIO_STATUS,
    SERVICE_REQUEST_MAINTENANCE,
    SERVICE_TRIGGER_AUTOMATION,
    SERVICE_UPDATE_AUTOMATION_CONFIG,
    SIGNAL_CONNECTION_UPDATE,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.service import SupportsResponse

_LOGGER = logging.getLogger(__name__)

# Property target: entry_id OR property_name OR calendar_entity_id
SERVICE_PROPERTY_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Optional("property_name"): cv.string,
        vol.Optional("calendar_entity_id"): cv.entity_id,
    }
)

SERVICE_MAINTENANCE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Optional("property_name"): cv.string,
        vol.Optional("calendar_entity_id"): cv.entity_id,
        vol.Optional("hours"): vol.Coerce(int),
    }
)

SERVICE_CALL_REMOTE_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("domain"): cv.string,
        vol.Required("service"): cv.string,
        vol.Optional("service_data"): dict,
    }
)

SERVICE_TRIGGER_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("entity_id"): cv.string,
        vol.Optional("skip_condition", default=False): cv.boolean,
    }
)

SERVICE_AUTOMATION_ID_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("automation_id"): cv.string,
    }
)

SERVICE_UPDATE_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("automation_id"): cv.string,
        vol.Required("config"): dict,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Property Bridge services (once)."""
    if hass.services.has_service(DOMAIN, SERVICE_APPLY_CHECKIN):
        return

    async def _get_connection(entry_id: str):
        data = hass.data.get(DOMAIN, {})
        conn = data.get(entry_id)
        if not conn:
            raise ValueError(f"No Property Bridge entry found for id {entry_id}")
        return conn

    async def _resolve_connection(call: ServiceCall):
        """Resolve a BridgeConnection from entry_id, property_name, or calendar."""
        data = hass.data.get(DOMAIN, {})
        entry_id = call.data.get("entry_id")
        if entry_id:
            return await _get_connection(entry_id)

        property_name = (call.data.get("property_name") or "").strip().lower()
        if property_name:
            for conn in data.values():
                if conn.property_name.lower() == property_name:
                    return conn
            raise ValueError(f"No Property Bridge property named '{property_name}'")

        calendar = call.data.get("calendar_entity_id")
        if calendar:
            calendar = calendar.lower()
            for conn in data.values():
                opts = {**conn.entry.data, **conn.entry.options}
                linked = (opts.get(CONF_CALENDAR_ENTITY) or "").strip().lower()
                if linked and linked == calendar:
                    return conn
            raise ValueError(
                f"No Property Bridge property linked to calendar '{calendar}'"
            )

        raise ValueError(
            "Provide entry_id, property_name, or calendar_entity_id to select a property"
        )

    async def handle_apply_checkin(call: ServiceCall) -> None:
        """Apply check-in preset (script and/or scene) for a property."""
        conn = await _resolve_connection(call)
        entry = conn.entry
        options = {**entry.data, **entry.options}

        script = options.get(CONF_CHECKIN_SCRIPT)
        scene = options.get(CONF_CHECKIN_SCENE)

        if script:
            _LOGGER.info(
                "Applying check-in script %s for property '%s'",
                script,
                conn.property_name,
            )
            await hass.services.async_call(
                "script", "turn_on", {"entity_id": script}, blocking=True
            )
        if scene:
            _LOGGER.info(
                "Applying check-in scene %s for property '%s'",
                scene,
                conn.property_name,
            )
            await hass.services.async_call(
                "scene", "turn_on", {"entity_id": scene}, blocking=True
            )
        if not script and not scene:
            _LOGGER.warning(
                "No check-in script or scene configured for property '%s'",
                conn.property_name,
            )

    async def handle_apply_checkout(call: ServiceCall) -> None:
        """Apply check-out preset (script and/or scene) for a property."""
        conn = await _resolve_connection(call)
        entry = conn.entry
        options = {**entry.data, **entry.options}

        script = options.get(CONF_CHECKOUT_SCRIPT)
        scene = options.get(CONF_CHECKOUT_SCENE)

        if script:
            _LOGGER.info(
                "Applying check-out script %s for property '%s'",
                script,
                conn.property_name,
            )
            await hass.services.async_call(
                "script", "turn_on", {"entity_id": script}, blocking=True
            )
        if scene:
            _LOGGER.info(
                "Applying check-out scene %s for property '%s'",
                scene,
                conn.property_name,
            )
            await hass.services.async_call(
                "scene", "turn_on", {"entity_id": scene}, blocking=True
            )
        if not script and not scene:
            _LOGGER.warning(
                "No check-out script or scene configured for property '%s'",
                conn.property_name,
            )

    async def handle_request_maintenance(call: ServiceCall) -> None:
        """Open a maintenance window for a property."""
        conn = await _resolve_connection(call)
        entry = conn.entry
        options = {**entry.data, **entry.options}

        hours = call.data.get(
            "hours",
            options.get(
                CONF_MAINTENANCE_WINDOW_HOURS, DEFAULT_MAINTENANCE_WINDOW_HOURS
            ),
        )
        require_consent = options.get(CONF_MAINTENANCE_REQUIRE_CONSENT, True)

        if require_consent and not conn.consent_granted:
            _LOGGER.warning(
                "Maintenance requested for '%s' but consent not granted. "
                "Call grant_maintenance_consent first.",
                conn.property_name,
            )
            conn.maintenance_requested = True
            conn._notify_update()
            return

        until = dt_util.utcnow() + timedelta(hours=int(hours))
        conn.maintenance_allowed_until = until
        conn.maintenance_requested = True
        conn.consent_granted = True

        new_options = dict(entry.options)
        new_options[CONF_MAINTENANCE_ALLOWED_UNTIL] = until.isoformat()
        hass.config_entries.async_update_entry(entry, options=new_options)

        _LOGGER.info(
            "Maintenance window opened for '%s' until %s (%s hours)",
            conn.property_name,
            until.isoformat(),
            hours,
        )
        conn._notify_update()

    async def handle_end_maintenance(call: ServiceCall) -> None:
        """Close the maintenance window."""
        conn = await _resolve_connection(call)
        entry = conn.entry

        conn.maintenance_allowed_until = None
        conn.maintenance_requested = False
        conn.consent_granted = False

        new_options = dict(entry.options)
        new_options.pop(CONF_MAINTENANCE_ALLOWED_UNTIL, None)
        hass.config_entries.async_update_entry(entry, options=new_options)

        _LOGGER.info("Maintenance window closed for '%s'", conn.property_name)
        conn._notify_update()

    async def handle_grant_consent(call: ServiceCall) -> None:
        """Grant consent for maintenance (multi-tenant safety)."""
        conn = await _resolve_connection(call)
        conn.consent_granted = True
        _LOGGER.info(
            "Maintenance consent granted for property '%s'", conn.property_name
        )
        conn._notify_update()

    async def handle_list_properties(call: ServiceCall) -> dict[str, Any]:
        """List all Property Bridge properties with basic status."""
        properties = []
        for entry_id, conn in hass.data.get(DOMAIN, {}).items():
            status = conn.get_status_data()
            opts = {**conn.entry.data, **conn.entry.options}
            properties.append(
                {
                    "entry_id": entry_id,
                    "property_name": conn.property_name,
                    "connected": status.get("connected"),
                    "entity_count": status.get("entity_count"),
                    "last_seen": status.get("last_seen"),
                    "host": status.get("host"),
                    "calendar_entity": opts.get(CONF_CALENDAR_ENTITY) or None,
                    "maintenance_allowed": status.get("maintenance_allowed"),
                }
            )
        return {"properties": properties, "count": len(properties)}

    async def handle_portfolio_status(call: ServiceCall) -> dict[str, Any]:
        """Bulk health summary for all connected properties."""
        properties = []
        connected = 0
        total_entities = 0
        for entry_id, conn in hass.data.get(DOMAIN, {}).items():
            status = conn.get_status_data()
            is_connected = bool(status.get("connected"))
            if is_connected:
                connected += 1
            total_entities += int(status.get("entity_count") or 0)
            properties.append(
                {
                    "entry_id": entry_id,
                    "property_name": conn.property_name,
                    "connected": is_connected,
                    "entity_count": status.get("entity_count"),
                    "last_seen": status.get("last_seen"),
                    "last_error": status.get("last_error"),
                    "remote_version": status.get("remote_version"),
                    "ws_url": status.get("ws_url"),
                    "maintenance_allowed": status.get("maintenance_allowed"),
                    "maintenance_until": status.get("maintenance_until"),
                }
            )
        total = len(properties)
        return {
            "total_properties": total,
            "connected": connected,
            "disconnected": total - connected,
            "total_mirrored_entities": total_entities,
            "healthy": total > 0 and connected == total,
            "properties": properties,
        }

    async def handle_call_remote(call: ServiceCall) -> None:
        """Call any service on the remote Home Assistant."""
        conn = await _get_connection(call.data["entry_id"])
        await conn.async_call_remote_service(
            call.data["domain"],
            call.data["service"],
            call.data.get("service_data") or {},
        )

    async def handle_trigger_automation(call: ServiceCall) -> None:
        """Trigger a mirrored (remote) automation."""
        conn = await _get_connection(call.data["entry_id"])
        entity_id = call.data["entity_id"]
        # Accept local or remote entity_id
        remote = conn._local_to_remote.get(entity_id, entity_id)
        data: dict[str, Any] = {"entity_id": remote}
        if call.data.get("skip_condition"):
            data["skip_condition"] = True
        await conn.async_call_remote_service("automation", "trigger", data)

    async def handle_list_automations(call: ServiceCall) -> dict[str, Any]:
        """List mirrored automations for a property."""
        conn = await _get_connection(call.data["entry_id"])
        automations = await conn.async_list_automations()
        return {"automations": automations, "count": len(automations)}

    async def handle_get_automation_config(call: ServiceCall) -> dict[str, Any]:
        """Fetch full automation config from the remote instance."""
        conn = await _get_connection(call.data["entry_id"])
        config = await conn.async_get_automation_config(call.data["automation_id"])
        return {"automation_id": call.data["automation_id"], "config": config}

    async def handle_update_automation_config(call: ServiceCall) -> dict[str, Any]:
        """Push an updated automation config to the remote instance."""
        conn = await _get_connection(call.data["entry_id"])
        result = await conn.async_update_automation_config(
            call.data["automation_id"], call.data["config"]
        )
        return {
            "automation_id": call.data["automation_id"],
            "result": result,
        }

    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_CHECKIN, handle_apply_checkin, schema=SERVICE_PROPERTY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_CHECKOUT,
        handle_apply_checkout,
        schema=SERVICE_PROPERTY_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REQUEST_MAINTENANCE,
        handle_request_maintenance,
        schema=SERVICE_MAINTENANCE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_END_MAINTENANCE,
        handle_end_maintenance,
        schema=SERVICE_PROPERTY_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GRANT_CONSENT,
        handle_grant_consent,
        schema=SERVICE_PROPERTY_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CALL_REMOTE,
        handle_call_remote,
        schema=SERVICE_CALL_REMOTE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER_AUTOMATION,
        handle_trigger_automation,
        schema=SERVICE_TRIGGER_AUTOMATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_AUTOMATIONS,
        handle_list_automations,
        schema=SERVICE_PROPERTY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_AUTOMATION_CONFIG,
        handle_get_automation_config,
        schema=SERVICE_AUTOMATION_ID_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_AUTOMATION_CONFIG,
        handle_update_automation_config,
        schema=SERVICE_UPDATE_AUTOMATION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_PROPERTIES,
        handle_list_properties,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PORTFOLIO_STATUS,
        handle_portfolio_status,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )

    _LOGGER.debug("Property Bridge services registered")


async def async_unload_services(hass: HomeAssistant) -> None:
    """Remove services when last entry is unloaded."""
    for service in (
        SERVICE_APPLY_CHECKIN,
        SERVICE_APPLY_CHECKOUT,
        SERVICE_REQUEST_MAINTENANCE,
        SERVICE_END_MAINTENANCE,
        SERVICE_GRANT_CONSENT,
        SERVICE_CALL_REMOTE,
        SERVICE_TRIGGER_AUTOMATION,
        SERVICE_LIST_AUTOMATIONS,
        SERVICE_GET_AUTOMATION_CONFIG,
        SERVICE_UPDATE_AUTOMATION_CONFIG,
        SERVICE_LIST_PROPERTIES,
        SERVICE_PORTFOLIO_STATUS,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
