"""Config flow for Property Bridge."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CHECKIN_SCENE,
    CONF_CHECKIN_SCRIPT,
    CONF_CHECKOUT_SCENE,
    CONF_CHECKOUT_SCRIPT,
    CONF_CREATE_AREA,
    CONF_CREATE_LABEL,
    CONF_ENTITY_PREFIX,
    CONF_FRIENDLY_NAME_PREFIX,
    CONF_MAINTENANCE_ENABLED,
    CONF_MAINTENANCE_REQUIRE_CONSENT,
    CONF_MAINTENANCE_WINDOW_HOURS,
    CONF_PROPERTY_NAME,
    CONF_SECURE,
    CONF_VERIFY_SSL,
    DEFAULT_CREATE_AREA,
    DEFAULT_CREATE_LABEL,
    DEFAULT_MAINTENANCE_ENABLED,
    DEFAULT_MAINTENANCE_REQUIRE_CONSENT,
    DEFAULT_MAINTENANCE_WINDOW_HOURS,
    DEFAULT_PORT,
    DEFAULT_SECURE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PROPERTY_NAME): str,
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_ACCESS_TOKEN): str,
        vol.Optional(CONF_SECURE, default=DEFAULT_SECURE): bool,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
        vol.Optional(CONF_ENTITY_PREFIX, default=""): str,
        vol.Optional(CONF_FRIENDLY_NAME_PREFIX, default=""): str,
        vol.Optional(CONF_CREATE_AREA, default=DEFAULT_CREATE_AREA): bool,
        vol.Optional(CONF_CREATE_LABEL, default=DEFAULT_CREATE_LABEL): bool,
    }
)


async def validate_connection(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)
    scheme = "https" if data.get(CONF_SECURE, True) else "http"
    url = f"{scheme}://{data[CONF_HOST]}:{data.get(CONF_PORT, DEFAULT_PORT)}/api/"

    headers = {
        "Authorization": f"Bearer {data[CONF_ACCESS_TOKEN]}",
        "Content-Type": "application/json",
    }

    try:
        async with session.get(
            url,
            headers=headers,
            ssl=data.get(CONF_VERIFY_SSL, True),
            timeout=10,
        ) as resp:
            if resp.status in (200, 401, 403):
                return {"title": data[CONF_PROPERTY_NAME]}
            resp.raise_for_status()
    except Exception as err:
        _LOGGER.debug("Connection validation failed: %s", err)
        raise CannotConnect from err

    return {"title": data[CONF_PROPERTY_NAME]}


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Property Bridge."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            unique_id = f"{user_input[CONF_PROPERTY_NAME]}_{user_input[CONF_HOST]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                info = await validate_connection(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during validation")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Property Bridge."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = {**self.config_entry.data, **self.config_entry.options}

        options_schema = vol.Schema(
            {
                # Connection / naming
                vol.Optional(
                    CONF_ENTITY_PREFIX,
                    default=data.get(CONF_ENTITY_PREFIX, ""),
                ): str,
                vol.Optional(
                    CONF_FRIENDLY_NAME_PREFIX,
                    default=data.get(CONF_FRIENDLY_NAME_PREFIX, ""),
                ): str,
                vol.Optional(
                    CONF_SECURE,
                    default=data.get(CONF_SECURE, DEFAULT_SECURE),
                ): bool,
                vol.Optional(
                    CONF_VERIFY_SSL,
                    default=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                ): bool,
                # Area / label
                vol.Optional(
                    CONF_CREATE_AREA,
                    default=data.get(CONF_CREATE_AREA, DEFAULT_CREATE_AREA),
                ): bool,
                vol.Optional(
                    CONF_CREATE_LABEL,
                    default=data.get(CONF_CREATE_LABEL, DEFAULT_CREATE_LABEL),
                ): bool,
                # Rental presets
                vol.Optional(
                    CONF_CHECKIN_SCRIPT,
                    default=data.get(CONF_CHECKIN_SCRIPT, ""),
                ): str,
                vol.Optional(
                    CONF_CHECKOUT_SCRIPT,
                    default=data.get(CONF_CHECKOUT_SCRIPT, ""),
                ): str,
                vol.Optional(
                    CONF_CHECKIN_SCENE,
                    default=data.get(CONF_CHECKIN_SCENE, ""),
                ): str,
                vol.Optional(
                    CONF_CHECKOUT_SCENE,
                    default=data.get(CONF_CHECKOUT_SCENE, ""),
                ): str,
                # Maintenance / consent
                vol.Optional(
                    CONF_MAINTENANCE_ENABLED,
                    default=data.get(
                        CONF_MAINTENANCE_ENABLED, DEFAULT_MAINTENANCE_ENABLED
                    ),
                ): bool,
                vol.Optional(
                    CONF_MAINTENANCE_REQUIRE_CONSENT,
                    default=data.get(
                        CONF_MAINTENANCE_REQUIRE_CONSENT,
                        DEFAULT_MAINTENANCE_REQUIRE_CONSENT,
                    ),
                ): bool,
                vol.Optional(
                    CONF_MAINTENANCE_WINDOW_HOURS,
                    default=data.get(
                        CONF_MAINTENANCE_WINDOW_HOURS,
                        DEFAULT_MAINTENANCE_WINDOW_HOURS,
                    ),
                ): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
