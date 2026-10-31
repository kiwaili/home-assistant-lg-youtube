"""Parse YouTube URLs into the target string LG webOS 4 YouTube expects.

The launch payload matches klattimer/LGWebOSRemote ``openYoutubeURL`` and the
webOS 4 path in Hybirdss/smartest-tv: app id ``youtube.leanback.v4`` with

    params.contentTarget = "http://www.youtube.com/tv?v=<video id>"

A normal ``/watch?v=`` browser link is not what the leanback app reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
import re

DEFAULT_YOUTUBE_APP_ID = "youtube.leanback.v4"
YOUTUBE_TV_BASE = "http://www.youtube.com/tv"

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{2,}$")
_YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
}
_PATH_WITH_VIDEO_ID = {"embed", "v", "shorts", "live", "e"}


@dataclass(frozen=True, slots=True)
class YoutubeTarget:
    """A video and/or playlist the TV YouTube app can open."""

    video_id: str | None
    playlist_id: str | None
    content_target: str


def parse_youtube_target(raw: str) -> YoutubeTarget:
    """Return a TV content target for a YouTube URL, short link, or video id."""
    text = raw.strip()
    if not text:
        raise ValueError("Enter a YouTube URL or video id")

    if _VIDEO_ID.fullmatch(text):
        return _build_target(text, None)

    if "://" not in text:
        text = "https://" + text

    parsed = urlparse(text)
    host = _normalize_host(parsed.hostname)
    if host not in _YOUTUBE_HOSTS and not host.endswith(".youtube.com"):
        raise ValueError(f"Not a YouTube URL: {raw.strip()}")

    query = parse_qs(parsed.query)
    video_id = _first_video_id(query.get("v"))
    playlist_id = _first_playlist_id(query.get("list"))
    parts = [part for part in parsed.path.strip("/").split("/") if part]

    if host == "youtu.be":
        if parts:
            video_id = _valid_video_id(parts[0]) or video_id
    elif parts:
        head = parts[0]
        if head in _PATH_WITH_VIDEO_ID and len(parts) > 1:
            video_id = _valid_video_id(parts[1]) or video_id
        elif head not in {"watch", "tv", "playlist"} and _VIDEO_ID.fullmatch(head):
            video_id = head

    if video_id is None and playlist_id is None:
        raise ValueError(f"No YouTube video or playlist id in: {raw.strip()}")
    return _build_target(video_id, playlist_id)


def find_youtube_app_id(apps: object) -> str:
    """Pick the YouTube app id reported by the TV.

    webOS 4.10 (including the 32LM6300) ships ``youtube.leanback.v4``. If the
    TV lists another YouTube id, use that instead of guessing.
    """
    ids: list[str] = []
    if isinstance(apps, dict):
        ids = [str(app_id) for app_id in apps if app_id]
    elif isinstance(apps, list):
        for app in apps:
            if isinstance(app, dict) and app.get("id"):
                ids.append(str(app["id"]))

    if DEFAULT_YOUTUBE_APP_ID in ids:
        return DEFAULT_YOUTUBE_APP_ID
    for app_id in ids:
        if "youtube" in app_id.lower():
            return app_id
    return DEFAULT_YOUTUBE_APP_ID


def _build_target(video_id: str | None, playlist_id: str | None) -> YoutubeTarget:
    pieces: list[str] = []
    if video_id:
        pieces.append(f"v={video_id}")
    if playlist_id:
        pieces.append(f"list={playlist_id}")
    return YoutubeTarget(
        video_id=video_id,
        playlist_id=playlist_id,
        content_target=f"{YOUTUBE_TV_BASE}?{'&'.join(pieces)}",
    )


def _normalize_host(hostname: str | None) -> str:
    host = (hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _first_video_id(values: list[str] | None) -> str | None:
    if not values:
        return None
    return _valid_video_id(values[0])


def _first_playlist_id(values: list[str] | None) -> str | None:
    if not values:
        return None
    playlist_id = values[0].strip()
    if _PLAYLIST_ID.fullmatch(playlist_id):
        return playlist_id
    return None


def _valid_video_id(value: str) -> str | None:
    video_id = value.strip()
    if _VIDEO_ID.fullmatch(video_id):
        return video_id
    return None
