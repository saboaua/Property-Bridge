"""Property Bridge integration for Home Assistant.

Links multiple remote Home Assistant instances into a central portal
so property managers and rental operators can view and control devices
from many properties in one place.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .connection import BridgeConnection

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Property Bridge integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Property Bridge from a config entry (one remote property)."""
    hass.data.setdefault(DOMAIN, {})

    connection = BridgeConnection(hass, entry)
    try:
        await connection.async_connect()
    except Exception as err:
        _LOGGER.exception("Failed to connect to remote Home Assistant: %s", err)
        raise ConfigEntryNotReady(
            f"Unable to connect to remote instance: {err}"
        ) from err

    hass.data[DOMAIN][entry.entry_id] = connection

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info(
        "Property Bridge: connected to property '%s' at %s",
        entry.data.get("property_name", entry.title),
        entry.data.get("host"),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and clean up the connection."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        connection: BridgeConnection | None = hass.data[DOMAIN].pop(
            entry.entry_id, None
        )
        if connection:
            await connection.async_disconnect()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry when options change."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
