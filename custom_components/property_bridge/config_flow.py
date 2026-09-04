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
    CONF_ENTITY_PREFIX,
    CONF_FRIENDLY_NAME_PREFIX,
    CONF_PROPERTY_NAME,
    CONF_SECURE,
    CONF_VERIFY_SSL,
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
    }
)


async def validate_connection(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Returns info that can be stored in the config entry.
    Raises an exception if connection fails.
    """
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
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
