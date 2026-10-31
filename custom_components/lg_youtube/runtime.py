"""Runtime client for one paired LG webOS TV."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any

import aiohttp
from aiowebostv import WebOsClient, WebOsTvCommandError, WebOsTvPairError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_SECRET, CONF_HOST, CONF_MAC, CONF_MODEL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ACCOUNT_DELAY_SECONDS,
    ACCOUNT_KEY_GAP_SECONDS,
    CLOSE_SETTLE_SECONDS,
    CONF_ACCOUNT_DELAY,
    CONF_YOUTUBE_ACCOUNT,
    DUPLICATE_LAUNCH_SECONDS,
    CONF_APP_ID,
    CONF_CLOSE_BEFORE_PLAY,
    CONF_LAUNCH_METHOD,
    CONF_SOURCE,
    CONF_SW_VERSION,
    CONF_WEBOS_ENTITY,
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_YOUTUBE_APP_ID,
    DOMAIN,
    EP_CLOSE,
    EP_LAUNCH,
    LAUNCH_CONTENT_ID,
    LAUNCH_CONTENT_ID_URL,
    LAUNCH_CONTENT_TARGET,
    SOURCE_WEBOSTV,
    WAKE_TIMEOUT_SECONDS,
    WEBOSTV_DOMAIN,
)
from .net import send_wake_on_lan
from .youtube import (
    ACCOUNT_ASK,
    ACCOUNT_SLOTS,
    YoutubeTarget,
    account_buttons,
    parse_youtube_target,
    youtube_deeplink,
)

_LOGGER = logging.getLogger(__name__)

_CONNECT_ERRORS = (
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
    WebOsTvCommandError,
    aiohttp.ClientError,
)
_COMMAND_ERRORS = (WebOsTvCommandError, HomeAssistantError)
_OFF_STATES = {"off", "unavailable", "unknown"}


class LgYoutubeRuntime:
    """Owns the webOS socket and the YouTube launch sequence."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Create a client. Connection happens in async_setup."""
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data.get(CONF_HOST, "")
        self.last_input: str | None = None
        self.last_target: YoutubeTarget | None = None
        self._recent_target: YoutubeTarget | None = None
        self._recent_launch_at = 0.0
        self._listeners: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._unsub_linked: Callable[[], None] | None = None
        self.client: WebOsClient | None = None
        if not self.uses_webos_connection:
            self.client = WebOsClient(
                self.host,
                entry.data.get(CONF_CLIENT_SECRET),
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                client_session=async_get_clientsession(hass),
            )

    @property
    def uses_webos_connection(self) -> bool:
        """True when commands go through the LG webOS TV integration."""
        return self.entry.data.get(CONF_SOURCE) == SOURCE_WEBOSTV

    @property
    def webos_entity_id(self) -> str:
        """Media player from the LG webOS TV integration."""
        return str(self.entry.data.get(CONF_WEBOS_ENTITY, ""))

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
    def youtube_account(self) -> str:
        """Profile slot on Who's watching. ``ask`` sends no remote keys."""
        raw = str(self.entry.options.get(CONF_YOUTUBE_ACCOUNT, ACCOUNT_ASK))
        if raw in ACCOUNT_SLOTS:
            return raw
        return ACCOUNT_ASK

    @property
    def account_delay(self) -> float:
        """Seconds to wait for Who's watching before sending keys."""
        raw = self.entry.options.get(CONF_ACCOUNT_DELAY, ACCOUNT_DELAY_SECONDS)
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            return float(ACCOUNT_DELAY_SECONDS)
        return min(20.0, max(1.0, seconds))

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry record shared by the player and the URL box."""
        if self.uses_webos_connection:
            linked = self._linked_device_info()
            if linked is not None:
                return linked
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer="LG",
            model=self.entry.data.get(CONF_MODEL),
            name=self.entry.title,
            sw_version=self.entry.data.get(CONF_SW_VERSION),
        )

    def _linked_device_info(self) -> DeviceInfo | None:
        """Attach entities to the device the LG webOS TV integration already owns."""
        registry = er.async_get(self.hass)
        entity = registry.async_get(self.webos_entity_id)
        if entity is None or not entity.device_id:
            return None
        device = dr.async_get(self.hass).async_get(entity.device_id)
        if device is None or not device.identifiers:
            return None
        return DeviceInfo(identifiers=set(device.identifiers))

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
        if self.uses_webos_connection:
            self._unsub_linked = async_track_state_change_event(
                self.hass, [self.webos_entity_id], self._on_linked_state
            )
            _LOGGER.info(
                "Using the LG webOS TV connection for %s (%s)",
                self.entry.title,
                self.webos_entity_id,
            )
            return

        assert self.client is not None
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
        """Drop the websocket. A linked TV keeps the LG webOS TV connection."""
        if self._unsub_linked is not None:
            self._unsub_linked()
            self._unsub_linked = None
        if self.client is None:
            return
        self.client.clear_state_update_callbacks()
        await self.client.disconnect()

    @callback
    def _on_linked_state(self, _event: object) -> None:
        self.publish()

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
            if self.uses_webos_connection:
                await self._media_player_service("turn_off")
                return
            await self.async_ensure_connected(wake=False)
            assert self.client is not None
            await self.client.power_off()

    async def async_set_volume(self, level: int) -> None:
        """Set the TV volume from 0 to 100."""
        async with self._lock:
            if self.uses_webos_connection:
                await self._media_player_service(
                    "volume_set", volume_level=max(0, min(100, level)) / 100
                )
                return
            await self.async_ensure_connected(wake=False)
            assert self.client is not None
            await self.client.set_volume(max(0, min(100, level)))

    async def async_mute(self, mute: bool) -> None:
        """Mute or unmute."""
        async with self._lock:
            if self.uses_webos_connection:
                await self._media_player_service("volume_mute", is_volume_muted=mute)
                return
            await self.async_ensure_connected(wake=False)
            assert self.client is not None
            await self.client.set_mute(mute)

    async def async_volume_up(self) -> None:
        """Volume up one step."""
        async with self._lock:
            if self.uses_webos_connection:
                await self._media_player_service("volume_up")
                return
            await self.async_ensure_connected(wake=False)
            assert self.client is not None
            await self.client.volume_up()

    async def async_volume_down(self) -> None:
        """Volume down one step."""
        async with self._lock:
            if self.uses_webos_connection:
                await self._media_player_service("volume_down")
                return
            await self.async_ensure_connected(wake=False)
            assert self.client is not None
            await self.client.volume_down()

    async def async_media_play(self) -> None:
        """Send play to the current app."""
        if self.uses_webos_connection:
            async with self._lock:
                await self._media_player_service("media_play")
            return
        await self._media_command("play")

    async def async_media_pause(self) -> None:
        """Send pause to the current app."""
        if self.uses_webos_connection:
            async with self._lock:
                await self._media_player_service("media_pause")
            return
        await self._media_command("pause")

    async def async_media_stop(self) -> None:
        """Close YouTube when it is in front, otherwise send stop."""
        async with self._lock:
            if self.uses_webos_connection:
                try:
                    await self._tv_request(EP_CLOSE, {"id": self.youtube_app_id})
                except _COMMAND_ERRORS:
                    await self._media_player_service("media_stop")
                return
            await self.async_ensure_connected(wake=False)
            assert self.client is not None
            app_id = self.youtube_app_id
            if self.client.tv_state.current_app_id == app_id:
                await self.client.close_app(app_id)
                return
            await self._send_media("stop")

    async def async_ensure_connected(self, *, wake: bool) -> None:
        """Connect, optionally waking the TV first. Caller holds the lock."""
        if self.uses_webos_connection:
            await self._ensure_webos_ready(wake=wake)
            return

        assert self.client is not None
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

    def _youtube_is_foreground(self) -> bool:
        """True when the TV is already showing YouTube."""
        app_id = self.youtube_app_id
        if self.uses_webos_connection:
            state = self.hass.states.get(self.webos_entity_id)
            if state is None:
                return False
            if state.attributes.get("app_id") == app_id:
                return True
            source = state.attributes.get("source")
            return isinstance(source, str) and "youtube" in source.lower()
        client = self.client
        if client is None or not client.is_connected():
            return False
        return client.tv_state.current_app_id == app_id

    async def _launch(self, target: YoutubeTarget) -> None:
        """Open the video with one launch.

        A full leanback URL makes YouTube boot, then load that page, so the
        app shows its loading screen twice. The default parameter is
        ``v=<video id>``. webOS 4 also ignores a launch while YouTube is
        already in front, so a video that replaces one already playing
        closes the app first. A cold start does not. A second request for
        the same video while the first is still opening is ignored, because
        that second launch is what restarts the loading screen.
        """
        now = time.monotonic()
        if (
            self._recent_target == target
            and now - self._recent_launch_at < DUPLICATE_LAUNCH_SECONDS
        ):
            _LOGGER.debug(
                "Ignoring a repeated launch of %s", target.content_target
            )
            return

        app_id = self.youtube_app_id
        if self.close_before_play and self._youtube_is_foreground():
            try:
                await self._tv_request(EP_CLOSE, {"id": app_id})
            except _COMMAND_ERRORS:
                _LOGGER.debug("YouTube was not running (%s)", app_id)
            else:
                await asyncio.sleep(CLOSE_SETTLE_SECONDS)

        self._recent_target = target
        self._recent_launch_at = time.monotonic()
        method = self.launch_method
        _LOGGER.debug(
            "Launching %s via %s with %s", app_id, method, youtube_deeplink(target)
        )
        await self._launch_with_method(app_id, target, method)
        await self._choose_account()

    async def _choose_account(self) -> None:
        """Confirm a profile when Who's watching is on screen.

        The official app has no account parameter. The highlighted profile
        is the one used last, so the keys go to the left edge, then right
        to the chosen slot, then OK. Ask on the TV sends nothing.
        """
        buttons = account_buttons(self.youtube_account)
        if not buttons:
            return
        _LOGGER.debug(
            "Choosing YouTube account %s after %.0f s",
            self.youtube_account,
            self.account_delay,
        )
        await asyncio.sleep(self.account_delay)
        try:
            for button in buttons:
                await self._send_button(button)
                await asyncio.sleep(ACCOUNT_KEY_GAP_SECONDS)
        except _COMMAND_ERRORS:
            _LOGGER.warning(
                "Could not choose YouTube account %s", self.youtube_account
            )

    async def _send_button(self, button: str) -> None:
        """Send one remote key through the webOS connection."""
        if self.uses_webos_connection:
            await self.hass.services.async_call(
                WEBOSTV_DOMAIN,
                "button",
                {"entity_id": self.webos_entity_id, "button": button},
                blocking=True,
            )
            return
        if self.client is None:
            raise HomeAssistantError("The LG TV is not connected.")
        await self.client.button(button)

    async def _launch_with_method(
        self, app_id: str, target: YoutubeTarget, method: str
    ) -> None:
        if method == LAUNCH_CONTENT_ID and target.video_id:
            await self._tv_request(
                EP_LAUNCH, {"id": app_id, "contentId": target.video_id}
            )
            return
        if method == LAUNCH_CONTENT_ID_URL:
            await self._tv_request(
                EP_LAUNCH, {"id": app_id, "contentId": target.content_target}
            )
            return
        await self._tv_request(
            EP_LAUNCH,
            {"id": app_id, "params": {"contentTarget": youtube_deeplink(target)}},
        )

    async def _tv_request(self, command: str, payload: dict[str, Any]) -> None:
        """Send one SSAP command, through the existing webOS connection when linked."""
        if self.uses_webos_connection:
            await self.hass.services.async_call(
                WEBOSTV_DOMAIN,
                "command",
                {
                    "entity_id": self.webos_entity_id,
                    "command": command,
                    "payload": payload,
                },
                blocking=True,
            )
            return
        if self.client is None:
            raise HomeAssistantError("The LG TV is not connected.")
        await self.client.request(command, payload)

    async def _media_player_service(self, service: str, **data: Any) -> None:
        """Forward a media player action to the LG webOS TV entity."""
        await self.hass.services.async_call(
            "media_player",
            service,
            {"entity_id": self.webos_entity_id, **data},
            blocking=True,
        )

    async def _ensure_webos_ready(self, *, wake: bool) -> None:
        """Wait until the already configured LG webOS TV entity is on."""
        state = self.hass.states.get(self.webos_entity_id)
        if state is None:
            raise HomeAssistantError(
                "The LG webOS TV entity is no longer available. Select the TV again."
            )
        if state.state not in _OFF_STATES:
            return
        if not wake:
            raise HomeAssistantError("The LG TV is off.")
        await self._media_player_service("turn_on")
        deadline = time.monotonic() + WAKE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            state = self.hass.states.get(self.webos_entity_id)
            if state is not None and state.state not in _OFF_STATES:
                return
        raise HomeAssistantError("The LG TV did not come online.")

    async def _media_command(self, name: str) -> None:
        async with self._lock:
            await self.async_ensure_connected(wake=False)
            await self._send_media(name)

    async def _send_media(self, name: str) -> None:
        assert self.client is not None
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
