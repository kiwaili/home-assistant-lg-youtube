"""Text entity used to paste a YouTube URL."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .runtime import LgYoutubeRuntime

_IGNORED_STATES = {"", "unknown", "unavailable", "none"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the URL box for this TV."""
    runtime: LgYoutubeRuntime = entry.runtime_data
    async_add_entities([LgYoutubeUrl(runtime)])


class LgYoutubeUrl(TextEntity, RestoreEntity):
    """Paste a YouTube link here and the TV opens it."""

    _attr_has_entity_name = True
    _attr_translation_key = "url"
    _attr_name = "YouTube URL"
    _attr_icon = "mdi:youtube"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 1024
    _attr_should_poll = False

    def __init__(self, runtime: LgYoutubeRuntime) -> None:
        """Tie the box to the TV runtime."""
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.unique_id}_youtube_url"
        self._attr_device_info = runtime.device_info

    @property
    def native_value(self) -> str | None:
        """Last URL typed into this box."""
        return self.runtime.last_input

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Keep the full URL. Entity state itself is capped at 255 characters."""
        if not self.runtime.last_input:
            return {}
        return {"url": self.runtime.last_input}

    async def async_added_to_hass(self) -> None:
        """Restore the last URL and follow later launches."""
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.add_listener(self.schedule_update_ha_state))
        last = await self.async_get_last_state()
        if last is None:
            return
        restored = None
        if last.attributes:
            restored = last.attributes.get("url")
        if not restored and last.state not in _IGNORED_STATES:
            restored = last.state
        if isinstance(restored, str) and restored.strip():
            self.runtime.remember(restored)

    async def async_set_value(self, value: str) -> None:
        """Play the URL, or clear the box when the value is blank."""
        if not value.strip():
            self.runtime.last_input = ""
            self.runtime.last_target = None
            self.runtime.publish()
            return
        await self.runtime.async_play(value)
