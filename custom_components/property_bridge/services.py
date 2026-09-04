"""Services for Property Bridge – rental presets, maintenance, automation control."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import SupportsResponse
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHECKIN_SCENE,
    CONF_CHECKIN_SCRIPT,
    CONF_CHECKOUT_SCENE,
    CONF_CHECKOUT_SCRIPT,
    CONF_MAINTENANCE_ALLOWED_UNTIL,
    CONF_MAINTENANCE_REQUIRE_CONSENT,
    CONF_MAINTENANCE_WINDOW_HOURS,
    DEFAULT_MAINTENANCE_WINDOW_HOURS,
    DOMAIN,
    SERVICE_APPLY_CHECKIN,
    SERVICE_APPLY_CHECKOUT,
    SERVICE_CALL_REMOTE,
    SERVICE_END_MAINTENANCE,
    SERVICE_GET_AUTOMATION_CONFIG,
    SERVICE_GRANT_CONSENT,
    SERVICE_LIST_AUTOMATIONS,
    SERVICE_REQUEST_MAINTENANCE,
    SERVICE_TRIGGER_AUTOMATION,
    SERVICE_UPDATE_AUTOMATION_CONFIG,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_PROPERTY_SCHEMA = vol.Schema({vol.Required("entry_id"): cv.string})
SERVICE_MAINTENANCE_SCHEMA = vol.Schema(
    {vol.Required("entry_id"): cv.string, vol.Optional("hours"): vol.Coerce(int)}
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
    {vol.Required("entry_id"): cv.string, vol.Required("automation_id"): cv.string}
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

    async def handle_apply_checkin(call: ServiceCall) -> None:
        conn = await _get_connection(call.data["entry_id"])
        entry = conn.entry
        options = {**entry.data, **entry.options}
        script = options.get(CONF_CHECKIN_SCRIPT)
        scene = options.get(CONF_CHECKIN_SCENE)
        if script:
            await hass.services.async_call(
                "script", "turn_on", {"entity_id": script}, blocking=True
            )
        if scene:
            await hass.services.async_call(
                "scene", "turn_on", {"entity_id": scene}, blocking=True
            )

    async def handle_apply_checkout(call: ServiceCall) -> None:
        conn = await _get_connection(call.data["entry_id"])
        entry = conn.entry
        options = {**entry.data, **entry.options}
        script = options.get(CONF_CHECKOUT_SCRIPT)
        scene = options.get(CONF_CHECKOUT_SCENE)
        if script:
            await hass.services.async_call(
                "script", "turn_on", {"entity_id": script}, blocking=True
            )
        if scene:
            await hass.services.async_call(
                "scene", "turn_on", {"entity_id": scene}, blocking=True
            )

    async def handle_request_maintenance(call: ServiceCall) -> None:
        from datetime import timedelta

        conn = await _get_connection(call.data["entry_id"])
        entry = conn.entry
        options = {**entry.data, **entry.options}
        require = options.get(CONF_MAINTENANCE_REQUIRE_CONSENT, True)
        if require and not conn.consent_granted:
            raise ValueError("Maintenance consent has not been granted")
        hours = call.data.get("hours") or options.get(
            CONF_MAINTENANCE_WINDOW_HOURS, DEFAULT_MAINTENANCE_WINDOW_HOURS
        )
        until = dt_util.utcnow() + timedelta(hours=int(hours))
        conn.maintenance_allowed_until = until
        conn.maintenance_requested = True
        new_options = dict(entry.options)
        new_options[CONF_MAINTENANCE_ALLOWED_UNTIL] = until.isoformat()
        hass.config_entries.async_update_entry(entry, options=new_options)
        conn._notify_update()

    async def handle_end_maintenance(call: ServiceCall) -> None:
        conn = await _get_connection(call.data["entry_id"])
        entry = conn.entry
        conn.maintenance_allowed_until = None
        conn.maintenance_requested = False
        conn.consent_granted = False
        new_options = dict(entry.options)
        new_options.pop(CONF_MAINTENANCE_ALLOWED_UNTIL, None)
        hass.config_entries.async_update_entry(entry, options=new_options)
        conn._notify_update()

    async def handle_grant_consent(call: ServiceCall) -> None:
        conn = await _get_connection(call.data["entry_id"])
        conn.consent_granted = True
        conn._notify_update()

    async def handle_call_remote(call: ServiceCall) -> None:
        conn = await _get_connection(call.data["entry_id"])
        await conn.async_call_remote_service(
            call.data["domain"],
            call.data["service"],
            call.data.get("service_data") or {},
        )

    async def handle_trigger_automation(call: ServiceCall) -> None:
        conn = await _get_connection(call.data["entry_id"])
        entity_id = call.data["entity_id"]
        remote = conn._local_to_remote.get(entity_id, entity_id)
        data: dict[str, Any] = {"entity_id": remote}
        if call.data.get("skip_condition"):
            data["skip_condition"] = True
        await conn.async_call_remote_service("automation", "trigger", data)

    async def handle_list_automations(call: ServiceCall) -> dict[str, Any]:
        conn = await _get_connection(call.data["entry_id"])
        automations = await conn.async_list_automations()
        return {"automations": automations, "count": len(automations)}

    async def handle_get_automation_config(call: ServiceCall) -> dict[str, Any]:
        conn = await _get_connection(call.data["entry_id"])
        config = await conn.async_get_automation_config(call.data["automation_id"])
        return {"automation_id": call.data["automation_id"], "config": config}

    async def handle_update_automation_config(call: ServiceCall) -> dict[str, Any]:
        conn = await _get_connection(call.data["entry_id"])
        result = await conn.async_update_automation_config(
            call.data["automation_id"], call.data["config"]
        )
        return {"automation_id": call.data["automation_id"], "result": result}

    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_CHECKIN, handle_apply_checkin, schema=SERVICE_PROPERTY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_CHECKOUT, handle_apply_checkout, schema=SERVICE_PROPERTY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REQUEST_MAINTENANCE,
        handle_request_maintenance,
        schema=SERVICE_MAINTENANCE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_END_MAINTENANCE, handle_end_maintenance, schema=SERVICE_PROPERTY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GRANT_CONSENT, handle_grant_consent, schema=SERVICE_PROPERTY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CALL_REMOTE, handle_call_remote, schema=SERVICE_CALL_REMOTE_SCHEMA
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
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
