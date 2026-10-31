"""Media player that opens YouTube URLs on an LG webOS TV."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_URL, DOMAIN, SERVICE_PLAY
from .runtime import LgYoutubeRuntime

_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the player and the play-url action."""
    platform = entity_platform.async_get_current_platform()
    if not hass.services.has_service(DOMAIN, SERVICE_PLAY):
        platform.async_register_entity_service(
            SERVICE_PLAY,
            {vol.Required(ATTR_URL): cv.string},
            "async_play_url",
            [MediaPlayerEntityFeature.PLAY_MEDIA],
        )
    runtime: LgYoutubeRuntime = entry.runtime_data
    async_add_entities([LgYoutubeMediaPlayer(runtime)])


class LgYoutubeMediaPlayer(MediaPlayerEntity):
    """One LG TV, used to launch YouTube."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_icon = "mdi:youtube-tv"
    _attr_supported_features = _FEATURES
    _attr_media_content_type = MediaType.VIDEO

    def __init__(self, runtime: LgYoutubeRuntime) -> None:
        """Tie the entity to the TV runtime."""
        self.runtime = runtime
        self._attr_unique_id = runtime.unique_id
        self._attr_device_info = runtime.device_info

    async def async_added_to_hass(self) -> None:
        """Refresh when the TV pushes a state change."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.runtime.add_listener(self.schedule_update_ha_state)
        )

    @property
    def assumed_state(self) -> bool:
        """Volume is unknown until the websocket is up."""
        return not self.runtime.client.is_connected()

    @property
    def state(self) -> MediaPlayerState:
        """Report off, idle, or playing."""
        client = self.runtime.client
        if not client.is_connected() or not client.tv_state.is_on:
            return MediaPlayerState.OFF
        if client.tv_state.current_app_id == self.runtime.youtube_app_id:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        """Volume as a fraction, matching other Home Assistant players."""
        volume = self.runtime.client.tv_state.volume
        if volume is None:
            return None
        return max(0.0, min(1.0, volume / 100))

    @property
    def is_volume_muted(self) -> bool | None:
        """Mute flag from the TV, when it has reported one."""
        return self.runtime.client.tv_state.muted

    @property
    def media_title(self) -> str | None:
        """Video id or playlist id of the last successful launch."""
        target = self.runtime.last_target
        if target is None:
            return None
        return target.video_id or target.playlist_id

    @property
    def media_content_id(self) -> str | None:
        """TV content target of the last successful launch."""
        target = self.runtime.last_target
        if target is None:
            return None
        return target.content_target

    async def async_turn_on(self) -> None:
        """Wake the TV when a MAC address is stored, then connect."""
        await self.runtime.async_turn_on()

    async def async_turn_off(self) -> None:
        """Turn the TV off."""
        await self.runtime.async_turn_off()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume from the media player card."""
        await self.runtime.async_set_volume(round(volume * 100))

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await self.runtime.async_mute(mute)

    async def async_volume_up(self) -> None:
        """Volume up."""
        await self.runtime.async_volume_up()

    async def async_volume_down(self) -> None:
        """Volume down."""
        await self.runtime.async_volume_down()

    async def async_media_play(self) -> None:
        """Send play."""
        await self.runtime.async_media_play()

    async def async_media_pause(self) -> None:
        """Send pause."""
        await self.runtime.async_media_pause()

    async def async_media_stop(self) -> None:
        """Close YouTube, or send stop."""
        await self.runtime.async_media_stop()

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a YouTube URL passed as the media id."""
        await self.async_play_url(media_id)

    async def async_play_url(self, url: str) -> None:
        """Play a YouTube URL, short link, or 11-character video id."""
        await self.runtime.async_play(url)
