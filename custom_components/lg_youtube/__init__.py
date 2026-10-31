"""LG YouTube integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .runtime import LgYoutubeRuntime

type LgYoutubeConfigEntry = ConfigEntry[LgYoutubeRuntime]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration. Configuration is done through the UI."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LgYoutubeConfigEntry) -> bool:
    """Connect to one TV and expose the player plus the URL box."""
    runtime = LgYoutubeRuntime(hass, entry)
    entry.runtime_data = runtime
    try:
        await runtime.async_setup()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await runtime.async_shutdown()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LgYoutubeConfigEntry) -> bool:
    """Disconnect the TV and remove its entities."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
