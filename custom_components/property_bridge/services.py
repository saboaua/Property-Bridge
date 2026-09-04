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
    SERVICE_END_MAINTENANCE,
    SERVICE_GRANT_CONSENT,
    SERVICE_REQUEST_MAINTENANCE,
    SIGNAL_CONNECTION_UPDATE,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send

_LOGGER = logging.getLogger(__name__)

SERVICE_PROPERTY_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
    }
)

SERVICE_MAINTENANCE_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Optional("hours"): vol.Coerce(int),
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
        """Apply check-in preset (script and/or scene) for a property."""
        entry_id = call.data["entry_id"]
        conn = await _get_connection(entry_id)
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
        entry_id = call.data["entry_id"]
        conn = await _get_connection(entry_id)
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
        entry_id = call.data["entry_id"]
        conn = await _get_connection(entry_id)
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
            # Still allow request tracking; binary sensor stays off until consent
            conn.maintenance_requested = True
            conn._notify_update()
            return

        until = dt_util.utcnow() + timedelta(hours=hours)
        conn.maintenance_allowed_until = until
        conn.maintenance_requested = True
        conn.consent_granted = True

        # Persist in options so it survives reload
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
        entry_id = call.data["entry_id"]
        conn = await _get_connection(entry_id)
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
        entry_id = call.data["entry_id"]
        conn = await _get_connection(entry_id)
        conn.consent_granted = True
        _LOGGER.info(
            "Maintenance consent granted for property '%s'", conn.property_name
        )
        conn._notify_update()

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

    _LOGGER.debug("Property Bridge services registered")


async def async_unload_services(hass: HomeAssistant) -> None:
    """Remove services when last entry is unloaded."""
    for service in (
        SERVICE_APPLY_CHECKIN,
        SERVICE_APPLY_CHECKOUT,
        SERVICE_REQUEST_MAINTENANCE,
        SERVICE_END_MAINTENANCE,
        SERVICE_GRANT_CONSENT,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
