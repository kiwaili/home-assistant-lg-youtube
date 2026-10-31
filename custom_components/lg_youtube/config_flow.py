"""Config flow for LG YouTube."""

from __future__ import annotations

from contextlib import suppress
import logging
from typing import Any
from urllib.parse import urlparse

from aiowebostv import WebOsClient, WebOsTvPairError
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_CLIENT_SECRET, CONF_HOST, CONF_MAC, CONF_MODEL
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.ssdp import (
    ATTR_UPNP_FRIENDLY_NAME,
    ATTR_UPNP_UDN,
    SsdpServiceInfo,
)

from .const import (
    ACCOUNT_DELAY_SECONDS,
    CONF_ACCOUNT_DELAY,
    CONF_APP_ID,
    CONF_CLOSE_BEFORE_PLAY,
    CONF_LAUNCH_METHOD,
    CONF_YOUTUBE_ACCOUNT,
    CONF_SOURCE,
    CONF_SW_VERSION,
    CONF_WEBOS_ENTITY,
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_NAME,
    DEFAULT_YOUTUBE_APP_ID,
    DOMAIN,
    LAUNCH_CONTENT_ID,
    LAUNCH_CONTENT_ID_URL,
    LAUNCH_CONTENT_TARGET,
    PAIR_OTHER,
    SOURCE_PAIRED,
    SOURCE_WEBOSTV,
    WEBOSTV_DOMAIN,
)
from .net import normalize_host, normalize_mac
from .youtube import find_youtube_app_id

_LOGGER = logging.getLogger(__name__)

_LAUNCH_METHOD_LABELS = {
    LAUNCH_CONTENT_TARGET: "contentTarget (v= video id)",
    LAUNCH_CONTENT_ID: "contentId (video id)",
    LAUNCH_CONTENT_ID_URL: "contentId (leanback link)",
}

_ACCOUNT_LABELS = {
    "ask": "Ask on the TV",
    "1": "Account 1",
    "2": "Account 2",
    "3": "Account 3",
    "4": "Account 4",
    "5": "Account 5",
    "6": "Account 6",
}

_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_MAC): cv.string,
    }
)


def webos_tv_choices(hass) -> dict[str, str]:
    """Map each LG webOS TV media player to a label."""
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    choices: dict[str, str] = {}
    for entity in registry.entities.values():
        if entity.platform != WEBOSTV_DOMAIN or entity.domain != "media_player":
            continue
        if entity.disabled_by is not None:
            continue
        label = entity.entity_id
        if entity.device_id and (device := devices.async_get(entity.device_id)):
            label = device.name_by_user or device.name or label
        choices[entity.entity_id] = label
    return dict(sorted(choices.items(), key=lambda item: item[1].casefold()))


def webos_entity_for_host(hass, host: str) -> str | None:
    """Return the webOS media player for a TV address, when one is set up."""
    registry = er.async_get(hass)
    for config_entry in hass.config_entries.async_entries(WEBOSTV_DOMAIN):
        if config_entry.data.get(CONF_HOST) != host:
            continue
        for entity in er.async_entries_for_config_entry(registry, config_entry.entry_id):
            if entity.domain == "media_player" and entity.disabled_by is None:
                return entity.entity_id
    return None


def _make_client(hass, host: str, key: str | None) -> WebOsClient:
    return WebOsClient(
        host,
        key,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        client_session=async_get_clientsession(hass),
    )


def _software_version(client: WebOsClient) -> str | None:
    software = client.tv_info.software or {}
    if isinstance(software, dict):
        product = software.get("product_name")
        major = software.get("major_ver")
        minor = software.get("minor_ver")
        if product and major is not None and minor is not None:
            return f"{product} {major}.{minor}"
        if product and major is not None:
            return f"{product} {major}"
        if product:
            return str(product)
    system = client.tv_info.system or {}
    if isinstance(system, dict) and system.get("firmwareVersion"):
        return str(system["firmwareVersion"])
    return None


class LgYoutubeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair an LG webOS TV so YouTube URLs can be launched on it."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host = ""
        self._mac: str | None = None
        self._name = ""

    @staticmethod
    @callback
    def async_get_options_flow(
        _config_entry: ConfigEntry,
    ) -> LgYoutubeOptionsFlow:
        """Create the options flow."""
        return LgYoutubeOptionsFlow()

    def is_matching(self, other_flow: LgYoutubeConfigFlow) -> bool:
        """Match discovery flows for the same TV."""
        return bool(self._host) and other_flow._host == self._host

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prefer a TV that the LG webOS TV integration already connected."""
        choices = webos_tv_choices(self.hass)
        if not choices:
            return await self.async_step_manual()

        options = {
            **choices,
            PAIR_OTHER: "Pair a TV that is not in this list",
        }
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input[CONF_WEBOS_ENTITY]
            if selected == PAIR_OTHER:
                return await self.async_step_manual()
            if selected not in choices:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_create_linked(selected)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_WEBOS_ENTITY, default=next(iter(choices))): vol.In(options)}
            ),
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair a TV that is not already in the LG webOS TV integration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            mac_raw = (user_input.get(CONF_MAC) or "").strip()
            if not host:
                errors[CONF_HOST] = "invalid_host"
            else:
                mac: str | None = None
                if mac_raw:
                    try:
                        mac = normalize_mac(mac_raw)
                    except ValueError:
                        errors[CONF_MAC] = "invalid_mac"
                if not errors:
                    existing = webos_entity_for_host(self.hass, host)
                    if existing:
                        return await self._async_create_linked(existing)
                    self._host = host
                    self._mac = mac
                    self._async_abort_entries_match({CONF_HOST: self._host})
                    return await self.async_step_pairing()

        return self.async_show_form(
            step_id="manual", data_schema=_MANUAL_SCHEMA, errors=errors
        )

    async def _async_create_linked(self, entity_id: str) -> ConfigFlowResult:
        """Store a pointer at the existing webOS media player. Do not pair."""
        registry = er.async_get(self.hass)
        entity = registry.async_get(entity_id)
        if entity is None or entity.config_entry_id is None:
            return self.async_abort(reason="cannot_connect")

        webos_entry = self.hass.config_entries.async_get_entry(entity.config_entry_id)
        if webos_entry is None:
            return self.async_abort(reason="cannot_connect")

        self._async_abort_entries_match({CONF_WEBOS_ENTITY: entity_id})
        if webos_entry.unique_id:
            await self.async_set_unique_id(
                webos_entry.unique_id, raise_on_progress=False
            )
            self._abort_if_unique_id_configured({CONF_WEBOS_ENTITY: entity_id})

        host = webos_entry.data.get(CONF_HOST, "")
        title = webos_tv_choices(self.hass).get(entity_id, webos_entry.title)
        data: dict[str, Any] = {
            CONF_SOURCE: SOURCE_WEBOSTV,
            CONF_WEBOS_ENTITY: entity_id,
            CONF_HOST: host,
            CONF_APP_ID: DEFAULT_YOUTUBE_APP_ID,
        }
        return self.async_create_entry(title=title, data=data)

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Start pairing from an LG second-screen SSDP advertisement."""
        location = discovery_info.ssdp_location
        host = urlparse(location).hostname if location else None
        if not host:
            return self.async_abort(reason="cannot_connect")

        self._host = host
        linked = webos_entity_for_host(self.hass, host)
        if linked:
            return await self._async_create_linked(linked)
        friendly = discovery_info.upnp.get(ATTR_UPNP_FRIENDLY_NAME, "")
        self._name = friendly.replace("[LG]", "LG").strip()
        udn = discovery_info.upnp.get(ATTR_UPNP_UDN)
        if udn:
            await self.async_set_unique_id(str(udn).removeprefix("uuid:"))
            self._abort_if_unique_id_configured({CONF_HOST: self._host})
        self._async_abort_entries_match({CONF_HOST: self._host})
        if self.hass.config_entries.flow.async_has_matching_flow(self):
            return self.async_abort(reason="already_in_progress")
        self.context["title_placeholders"] = {"name": self._name or self._host}
        return await self.async_step_pairing()

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect and wait for the TV to accept the prompt."""
        self.context["title_placeholders"] = {"name": self._name or self._host}
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_attempt_pair()
            if result.get("type"):
                return result
            errors = result
        return self.async_show_form(step_id="pairing", errors=errors)

    async def _async_attempt_pair(
        self,
    ) -> ConfigFlowResult | dict[str, str]:
        """Pair, store the client key, and create the config entry."""
        client = _make_client(self.hass, self._host, None)
        try:
            await client.connect()
        except WebOsTvPairError:
            _LOGGER.warning("Pairing with LG TV at %s was rejected", self._host)
            return {"base": "error_pairing"}
        except Exception:  # noqa: BLE001 - keep the form on screen
            _LOGGER.exception("Could not connect to LG TV at %s", self._host)
            return {"base": "cannot_connect"}

        try:
            if not client.client_key:
                return {"base": "error_pairing"}
            return await self._async_create_from_client(client)
        finally:
            with suppress(Exception):
                await client.disconnect()

    async def _async_create_from_client(self, client: WebOsClient) -> ConfigFlowResult:
        hello = client.tv_info.hello or {}
        uuid = hello.get("deviceUUID") if isinstance(hello, dict) else None
        if uuid:
            await self.async_set_unique_id(str(uuid), raise_on_progress=False)
            self._abort_if_unique_id_configured({CONF_HOST: self._host})

        system = client.tv_info.system or {}
        model = system.get("modelName") if isinstance(system, dict) else None
        app_id = DEFAULT_YOUTUBE_APP_ID
        with suppress(Exception):
            app_id = find_youtube_app_id(await client.get_apps())

        data: dict[str, Any] = {
            CONF_SOURCE: SOURCE_PAIRED,
            CONF_HOST: self._host,
            CONF_CLIENT_SECRET: client.client_key,
            CONF_APP_ID: app_id,
        }
        if self._mac:
            data[CONF_MAC] = self._mac
        if model:
            data[CONF_MODEL] = model
        if version := _software_version(client):
            data[CONF_SW_VERSION] = version

        title = self._name or (f"LG {model}" if model else DEFAULT_NAME)
        return self.async_create_entry(title=title, data=data)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start re-pairing after the TV rejects the stored key."""
        self._host = entry_data[CONF_HOST]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair again and store the new client key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = _make_client(self.hass, self._host, None)
            try:
                await client.connect()
            except WebOsTvPairError:
                errors["base"] = "error_pairing"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Could not re-pair LG TV at %s", self._host)
                errors["base"] = "cannot_connect"
            else:
                if not client.client_key:
                    errors["base"] = "error_pairing"
                else:
                    entry = self._get_reauth_entry()
                    data = {**entry.data, CONF_CLIENT_SECRET: client.client_key}
                    with suppress(Exception):
                        await client.disconnect()
                    return self.async_update_reload_and_abort(entry, data=data)
            with suppress(Exception):
                await client.disconnect()

        return self.async_show_form(step_id="reauth_confirm", errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the selected TV, or the address of a separately paired TV."""
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_SOURCE) == SOURCE_WEBOSTV:
            return await self.async_step_reconfigure_link(user_input)

        errors: dict[str, str] = {}

        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            mac_raw = (user_input.get(CONF_MAC) or "").strip()
            mac: str | None = None
            if not host:
                errors[CONF_HOST] = "invalid_host"
            elif mac_raw:
                try:
                    mac = normalize_mac(mac_raw)
                except ValueError:
                    errors[CONF_MAC] = "invalid_mac"
            if not errors:
                client = _make_client(
                    self.hass, host, entry.data.get(CONF_CLIENT_SECRET)
                )
                try:
                    await client.connect()
                    hello = client.tv_info.hello or {}
                    uuid = hello.get("deviceUUID") if isinstance(hello, dict) else None
                    if uuid:
                        await self.async_set_unique_id(str(uuid))
                        self._abort_if_unique_id_mismatch(reason="wrong_device")
                except AbortFlow:
                    with suppress(Exception):
                        await client.disconnect()
                    raise
                except WebOsTvPairError:
                    errors["base"] = "error_pairing"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Could not connect to LG TV at %s", host)
                    errors["base"] = "cannot_connect"
                else:
                    data = {**entry.data, CONF_HOST: host}
                    if mac:
                        data[CONF_MAC] = mac
                    else:
                        data.pop(CONF_MAC, None)
                    with suppress(Exception):
                        await client.disconnect()
                    return self.async_update_reload_and_abort(entry, data=data)
                with suppress(Exception):
                    await client.disconnect()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data.get(CONF_HOST, "")
                    ): cv.string,
                    vol.Optional(
                        CONF_MAC, default=entry.data.get(CONF_MAC, "")
                    ): cv.string,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point this entry at a different LG webOS TV media player."""
        entry = self._get_reconfigure_entry()
        choices = webos_tv_choices(self.hass)
        if not choices:
            return self.async_abort(reason="cannot_connect")

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input[CONF_WEBOS_ENTITY]
            if selected not in choices:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_relink(entry, selected)

        current = entry.data.get(CONF_WEBOS_ENTITY)
        default = current if current in choices else next(iter(choices))
        return self.async_show_form(
            step_id="reconfigure_link",
            data_schema=vol.Schema(
                {vol.Required(CONF_WEBOS_ENTITY, default=default): vol.In(choices)}
            ),
            errors=errors,
        )

    async def _async_relink(
        self, entry: ConfigEntry, entity_id: str
    ) -> ConfigFlowResult:
        registry = er.async_get(self.hass)
        entity = registry.async_get(entity_id)
        webos_entry = (
            self.hass.config_entries.async_get_entry(entity.config_entry_id)
            if entity is not None and entity.config_entry_id
            else None
        )
        if webos_entry is None:
            return self.async_abort(reason="cannot_connect")
        if webos_entry.unique_id:
            await self.async_set_unique_id(webos_entry.unique_id)
            self._abort_if_unique_id_mismatch(reason="wrong_device")
        data = {
            **entry.data,
            CONF_SOURCE: SOURCE_WEBOSTV,
            CONF_WEBOS_ENTITY: entity_id,
            CONF_HOST: webos_entry.data.get(CONF_HOST, ""),
        }
        title = webos_tv_choices(self.hass).get(entity_id, entry.title)
        return self.async_update_reload_and_abort(entry, data=data, title=title)


class LgYoutubeOptionsFlow(OptionsFlowWithReload):
    """Options for how a YouTube URL is handed to the TV."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the launch payload and whether to restart YouTube."""
        if user_input is not None:
            app_id = str(user_input[CONF_APP_ID]).strip() or DEFAULT_YOUTUBE_APP_ID
            account = str(user_input[CONF_YOUTUBE_ACCOUNT])
            if account not in _ACCOUNT_LABELS:
                account = "ask"
            return self.async_create_entry(
                title="",
                data={
                    CONF_CLOSE_BEFORE_PLAY: bool(user_input[CONF_CLOSE_BEFORE_PLAY]),
                    CONF_APP_ID: app_id,
                    CONF_LAUNCH_METHOD: user_input[CONF_LAUNCH_METHOD],
                    CONF_YOUTUBE_ACCOUNT: account,
                    CONF_ACCOUNT_DELAY: int(user_input[CONF_ACCOUNT_DELAY]),
                },
            )

        entry = self.config_entry
        suggested_app = entry.options.get(
            CONF_APP_ID, entry.data.get(CONF_APP_ID, DEFAULT_YOUTUBE_APP_ID)
        )
        account = str(entry.options.get(CONF_YOUTUBE_ACCOUNT, "ask"))
        if account not in _ACCOUNT_LABELS:
            account = "ask"
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLOSE_BEFORE_PLAY,
                        default=entry.options.get(CONF_CLOSE_BEFORE_PLAY, True),
                    ): cv.boolean,
                    vol.Required(
                        CONF_LAUNCH_METHOD,
                        default=entry.options.get(
                            CONF_LAUNCH_METHOD, LAUNCH_CONTENT_TARGET
                        ),
                    ): vol.In(_LAUNCH_METHOD_LABELS),
                    vol.Required(CONF_YOUTUBE_ACCOUNT, default=account): vol.In(
                        _ACCOUNT_LABELS
                    ),
                    vol.Required(
                        CONF_ACCOUNT_DELAY,
                        default=entry.options.get(
                            CONF_ACCOUNT_DELAY, ACCOUNT_DELAY_SECONDS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
                    vol.Required(CONF_APP_ID, default=suggested_app): cv.string,
                }
            ),
        )
