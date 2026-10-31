"""Runtime client for one paired LG webOS TV."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time

import aiohttp
from aiowebostv import WebOsClient, WebOsTvCommandError, WebOsTvPairError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_SECRET, CONF_HOST, CONF_MAC, CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CLOSE_SETTLE_SECONDS,
    CONF_APP_ID,
    CONF_CLOSE_BEFORE_PLAY,
    CONF_LAUNCH_METHOD,
    CONF_SW_VERSION,
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_YOUTUBE_APP_ID,
    DOMAIN,
    LAUNCH_CONTENT_ID,
    LAUNCH_CONTENT_ID_URL,
    LAUNCH_CONTENT_TARGET,
    WAKE_TIMEOUT_SECONDS,
)
from .net import send_wake_on_lan
from .youtube import YoutubeTarget, parse_youtube_target

_LOGGER = logging.getLogger(__name__)

_CONNECT_ERRORS = (
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
    WebOsTvCommandError,
    aiohttp.ClientError,
)


class LgYoutubeRuntime:
    """Owns the webOS socket and the YouTube launch sequence."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Create a client. Connection happens in async_setup."""
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self.last_input: str | None = None
        self.last_target: YoutubeTarget | None = None
        self._listeners: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self.client = WebOsClient(
            self.host,
            entry.data.get(CONF_CLIENT_SECRET),
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            client_session=async_get_clientsession(hass),
        )

    @property
    def unique_id(self) -> str:
        """Stable id for entities on this TV."""
        return self.entry.unique_id or self.entry.entry_id

    @property
    def youtube_app_id(self) -> str:
        """YouTube application id, overridable from options."""
        return (
            self.entry.options.get(CONF_APP_ID)
            or self.entry.data.get(CONF_APP_ID)
            or DEFAULT_YOUTUBE_APP_ID
        )

    @property
    def close_before_play(self) -> bool:
        """webOS 4 ignores a new video when YouTube is already in front."""
        return bool(self.entry.options.get(CONF_CLOSE_BEFORE_PLAY, True))

    @property
    def launch_method(self) -> str:
        """Which launch payload to send. Default matches webOS 4."""
        return str(self.entry.options.get(CONF_LAUNCH_METHOD, LAUNCH_CONTENT_TARGET))

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry record shared by the player and the URL box."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer="LG",
            model=self.entry.data.get(CONF_MODEL),
            name=self.entry.title,
            sw_version=self.entry.data.get(CONF_SW_VERSION),
        )

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback invoked when playback or TV state changes."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def publish(self) -> None:
        """Ask entities to write their state."""
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - one entity must not break the socket
                _LOGGER.exception("LG YouTube state listener failed")

    def remember(self, raw: str) -> None:
        """Keep the last URL for the text box without launching it."""
        self.last_input = raw
        try:
            self.last_target = parse_youtube_target(raw)
        except ValueError:
            self.last_target = None
        self.publish()

    async def async_setup(self) -> None:
        """Subscribe to TV pushes and connect if the set is already on."""
        await self.client.register_state_update_callback(self._on_tv_state)
        try:
            await self.client.connect()
        except WebOsTvPairError:
            _LOGGER.error(
                "LG TV at %s rejected the saved key; re-pair the integration",
                self.host,
            )
            self.entry.async_start_reauth(self.hass)
        except _CONNECT_ERRORS as err:
            _LOGGER.warning("LG TV at %s is not reachable: %s", self.host, err)
        else:
            _LOGGER.info(
                "Connected to %s at %s; YouTube app id %s",
                self.entry.title,
                self.host,
                self.youtube_app_id,
            )

    async def async_shutdown(self) -> None:
        """Drop the websocket. The client key stays in the config entry."""
        self.client.clear_state_update_callbacks()
        await self.client.disconnect()

    async def async_play(self, raw_url: str) -> None:
        """Wake the TV if needed and open the YouTube URL."""
        text = (raw_url or "").strip()
        if not text:
            raise ServiceValidationError("Enter a YouTube URL or video id")
        try:
            target = parse_youtube_target(text)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

        async with self._lock:
            await self.async_ensure_connected(wake=True)
            await self._launch(target)
            self.remember(text)

    async def async_turn_on(self) -> None:
        """Connect, sending Wake-on-LAN when a MAC address is stored."""
        async with self._lock:
            await self.async_ensure_connected(wake=True)

    async def async_turn_off(self) -> None:
        """Turn the TV off. The set has to be reachable on the network."""
        async with self._lock:
            await self.async_ensure_connected(wake=False)
            await self.client.power_off()

    async def async_set_volume(self, level: int) -> None:
        """Set the TV volume from 0 to 100."""
        async with self._lock:
            await self.async_ensure_connected(wake=False)
            await self.client.set_volume(max(0, min(100, level)))

    async def async_mute(self, mute: bool) -> None:
        """Mute or unmute."""
        async with self._lock:
            await self.async_ensure_connected(wake=False)
            await self.client.set_mute(mute)

    async def async_volume_up(self) -> None:
        """Volume up one step."""
        async with self._lock:
            await self.async_ensure_connected(wake=False)
            await self.client.volume_up()

    async def async_volume_down(self) -> None:
        """Volume down one step."""
        async with self._lock:
            await self.async_ensure_connected(wake=False)
            await self.client.volume_down()

    async def async_media_play(self) -> None:
        """Send play to the current app."""
        await self._media_command("play")

    async def async_media_pause(self) -> None:
        """Send pause to the current app."""
        await self._media_command("pause")

    async def async_media_stop(self) -> None:
        """Close YouTube when it is in front, otherwise send stop."""
        async with self._lock:
            await self.async_ensure_connected(wake=False)
            app_id = self.youtube_app_id
            if self.client.tv_state.current_app_id == app_id:
                await self.client.close_app(app_id)
                return
            await self._send_media("stop")

    async def async_ensure_connected(self, *, wake: bool) -> None:
        """Connect, optionally waking the TV first. Caller holds the lock."""
        if self.client.is_connected():
            return

        last_error: Exception | None = None
        try:
            await self.client.connect()
        except WebOsTvPairError:
            self._start_reauth()
        except _CONNECT_ERRORS as err:
            last_error = err
        else:
            return

        mac = self.entry.data.get(CONF_MAC)
        if not wake or not mac:
            raise HomeAssistantError(
                f"LG TV at {self.host} is not reachable. Turn it on, or reconfigure "
                "the integration with a MAC address so Home Assistant can wake it."
            ) from last_error

        _LOGGER.info("Waking LG TV %s at %s", mac, self.host)
        await self.hass.async_add_executor_job(send_wake_on_lan, mac, self.host)
        deadline = time.monotonic() + WAKE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            try:
                await self.client.connect()
                return
            except WebOsTvPairError:
                self._start_reauth()
            except _CONNECT_ERRORS as err:
                last_error = err

        raise HomeAssistantError(
            f"LG TV at {self.host} did not come online after Wake-on-LAN"
        ) from last_error

    async def _launch(self, target: YoutubeTarget) -> None:
        """Close YouTube if it is running, then launch the video.

        On webOS 4.10 a second ``launch`` while YouTube is already the
        foreground app is ignored. Closing first is a no-op when the app is
        not open. The default payload is the one klattimer/LGWebOSRemote sends.
        """
        app_id = self.youtube_app_id
        if self.close_before_play:
            try:
                await self.client.close_app(app_id)
            except WebOsTvCommandError:
                _LOGGER.debug("YouTube was not running (%s)", app_id)
            else:
                await asyncio.sleep(CLOSE_SETTLE_SECONDS)

        method = self.launch_method
        _LOGGER.debug(
            "Launching %s via %s with %s", app_id, method, target.content_target
        )
        try:
            await self._launch_with_method(app_id, target, method)
        except WebOsTvCommandError:
            fallback = (
                LAUNCH_CONTENT_ID
                if method == LAUNCH_CONTENT_TARGET
                else LAUNCH_CONTENT_TARGET
            )
            _LOGGER.debug("%s launch failed; trying %s", method, fallback)
            await self._launch_with_method(app_id, target, fallback)

    async def _launch_with_method(
        self, app_id: str, target: YoutubeTarget, method: str
    ) -> None:
        if method == LAUNCH_CONTENT_ID and target.video_id:
            await self.client.launch_app_with_content_id(app_id, target.video_id)
            return
        if method == LAUNCH_CONTENT_ID_URL:
            await self.client.launch_app_with_content_id(app_id, target.content_target)
            return
        await self.client.launch_app_with_params(
            app_id, {"contentTarget": target.content_target}
        )

    async def _media_command(self, name: str) -> None:
        async with self._lock:
            await self.async_ensure_connected(wake=False)
            await self._send_media(name)

    async def _send_media(self, name: str) -> None:
        try:
            await getattr(self.client, name)()
        except WebOsTvCommandError as err:
            raise HomeAssistantError(
                "The TV rejected the media button. Starting a video from the "
                "YouTube URL still works."
            ) from err

    def _start_reauth(self) -> None:
        self.entry.async_start_reauth(self.hass)
        raise HomeAssistantError(
            "The LG TV rejected the saved pairing key. Re-pair the integration."
        )

    async def _on_tv_state(self, _state: object) -> None:
        self.publish()
