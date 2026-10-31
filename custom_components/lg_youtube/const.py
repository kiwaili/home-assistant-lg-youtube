"""Constants for the LG YouTube integration."""

from __future__ import annotations

from homeassistant.const import Platform

from .youtube import DEFAULT_YOUTUBE_APP_ID

DOMAIN = "lg_youtube"

CONF_APP_ID = "app_id"
CONF_CLOSE_BEFORE_PLAY = "close_before_play"
CONF_LAUNCH_METHOD = "launch_method"
CONF_SOURCE = "source"
CONF_SW_VERSION = "sw_version"
CONF_WEBOS_ENTITY = "webos_entity"

SOURCE_WEBOSTV = "webostv"
SOURCE_PAIRED = "paired"
PAIR_OTHER = "pair_other"
WEBOSTV_DOMAIN = "webostv"

EP_LAUNCH = "system.launcher/launch"
EP_CLOSE = "system.launcher/close"

ATTR_URL = "url"
SERVICE_PLAY = "play"

DEFAULT_NAME = "LG TV"

LAUNCH_CONTENT_TARGET = "content_target"
LAUNCH_CONTENT_ID = "content_id"
LAUNCH_CONTENT_ID_URL = "content_id_url"
LAUNCH_METHODS = (
    LAUNCH_CONTENT_TARGET,
    LAUNCH_CONTENT_ID,
    LAUNCH_CONTENT_ID_URL,
)

CLOSE_SETTLE_SECONDS = 1.5
DUPLICATE_LAUNCH_SECONDS = 5
WAKE_TIMEOUT_SECONDS = 45
CONNECT_TIMEOUT_SECONDS = 8

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.TEXT]
