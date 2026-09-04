"""Constants for the Property Bridge integration."""

from typing import Final

DOMAIN: Final = "property_bridge"

# Configuration keys
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_SECURE: Final = "secure"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_PROPERTY_NAME: Final = "property_name"
CONF_ENTITY_PREFIX: Final = "entity_prefix"
CONF_FRIENDLY_NAME_PREFIX: Final = "friendly_name_prefix"
CONF_INCLUDE_DOMAINS: Final = "include_domains"
CONF_EXCLUDE_DOMAINS: Final = "exclude_domains"

# Defaults
DEFAULT_PORT: Final = 8123
DEFAULT_SECURE: Final = True
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_ENTITY_PREFIX: Final = ""

# Platforms
PLATFORMS: Final = ["sensor"]

# Connection status attributes
ATTR_CONNECTED: Final = "connected"
ATTR_LAST_SEEN: Final = "last_seen"
ATTR_ENTITY_COUNT: Final = "entity_count"
ATTR_REMOTE_VERSION: Final = "remote_version"

# Dispatcher signal
SIGNAL_CONNECTION_UPDATE: Final = f"{DOMAIN}_connection_update"
