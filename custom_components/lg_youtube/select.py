"""Select entity for the YouTube profile on Who's watching."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_YOUTUBE_ACCOUNT
from .runtime import LgYoutubeRuntime
from .youtube import ACCOUNT_ASK, ACCOUNT_SLOTS

_OPTIONS = [ACCOUNT_ASK, *ACCOUNT_SLOTS]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the account selector for this TV."""
    runtime: LgYoutubeRuntime = entry.runtime_data
    async_add_entities([LgYoutubeAccount(runtime)])


class LgYoutubeAccount(SelectEntity):
    """Which profile to confirm after YouTube opens."""

    _attr_has_entity_name = True
    _attr_translation_key = "account"
    _attr_icon = "mdi:account"
    _attr_options = _OPTIONS
    _attr_should_poll = False

    def __init__(self, runtime: LgYoutubeRuntime) -> None:
        """Tie the selector to the TV runtime."""
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.unique_id}_youtube_account"
        self._attr_device_info = runtime.device_info

    @property
    def current_option(self) -> str:
        """Profile slot, or ask when the TV should wait for the remote."""
        return self.runtime.youtube_account

    async def async_added_to_hass(self) -> None:
        """Refresh when playback or the saved account changes."""
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.add_listener(self.schedule_update_ha_state))

    async def async_select_option(self, option: str) -> None:
        """Remember the profile. The next play confirms it on the TV."""
        if option not in _OPTIONS:
            return
        entry = self.runtime.entry
        self.hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_YOUTUBE_ACCOUNT: option},
        )
        self.runtime.publish()
