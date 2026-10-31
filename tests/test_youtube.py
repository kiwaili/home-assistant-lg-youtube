"""URL parsing and address helpers. No Home Assistant install required."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "lg_youtube"


def _load(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


youtube = _load("lg_youtube_youtube", "youtube.py")
net = _load("lg_youtube_net", "net.py")

VIDEO = "jNQXAC9IVRw"
TV_URL = f"http://www.youtube.com/tv?v={VIDEO}"


class ParseYoutubeTests(unittest.TestCase):
    def test_watch_url(self) -> None:
        target = youtube.parse_youtube_target(
            f"https://www.youtube.com/watch?v={VIDEO}&t=30s"
        )
        self.assertEqual(target.video_id, VIDEO)
        self.assertIsNone(target.playlist_id)
        self.assertEqual(target.content_target, TV_URL)

    def test_short_link(self) -> None:
        target = youtube.parse_youtube_target(f"https://youtu.be/{VIDEO}?si=abc")
        self.assertEqual(target.content_target, TV_URL)

    def test_shorts_embed_live_and_music(self) -> None:
        for url in (
            f"https://www.youtube.com/shorts/{VIDEO}",
            f"https://www.youtube.com/embed/{VIDEO}",
            f"https://www.youtube.com/live/{VIDEO}/",
            f"https://music.youtube.com/watch?v={VIDEO}",
            f"https://m.youtube.com/watch?v={VIDEO}",
            f"youtube.com/watch?v={VIDEO}",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    youtube.parse_youtube_target(url).content_target, TV_URL
                )

    def test_bare_id_and_existing_tv_url(self) -> None:
        self.assertEqual(youtube.parse_youtube_target(VIDEO).content_target, TV_URL)
        self.assertEqual(
            youtube.parse_youtube_target(TV_URL).content_target, TV_URL
        )

    def test_playlist(self) -> None:
        playlist = "PL1234567890abcdef"
        target = youtube.parse_youtube_target(
            f"https://www.youtube.com/watch?v={VIDEO}&list={playlist}"
        )
        self.assertEqual(target.video_id, VIDEO)
        self.assertEqual(target.playlist_id, playlist)
        self.assertEqual(
            target.content_target,
            f"http://www.youtube.com/tv?v={VIDEO}&list={playlist}",
        )
        only = youtube.parse_youtube_target(
            f"https://www.youtube.com/playlist?list={playlist}"
        )
        self.assertIsNone(only.video_id)
        self.assertEqual(
            only.content_target, f"http://www.youtube.com/tv?list={playlist}"
        )

    def test_rejects_non_youtube(self) -> None:
        for value in ("", "   ", "abcd", "https://vimeo.com/123", "https://youtu.be/"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    youtube.parse_youtube_target(value)

    def test_account_buttons(self) -> None:
        self.assertEqual(youtube.account_buttons("ask"), [])
        self.assertEqual(youtube.account_buttons("0"), [])
        self.assertEqual(
            youtube.account_buttons("1"), ["LEFT"] * 6 + ["ENTER"]
        )
        self.assertEqual(
            youtube.account_buttons("3"),
            ["LEFT"] * 6 + ["RIGHT", "RIGHT", "ENTER"],
        )

    def test_deeplink_is_v_equals_id(self) -> None:
        target = youtube.parse_youtube_target(
            f"https://www.youtube.com/watch?v={VIDEO}"
        )
        self.assertEqual(youtube.youtube_deeplink(target), f"v={VIDEO}")
        playlist = "PL1234567890abcdef"
        with_list = youtube.parse_youtube_target(
            f"https://www.youtube.com/watch?v={VIDEO}&list={playlist}"
        )
        self.assertEqual(
            youtube.youtube_deeplink(with_list), f"v={VIDEO}&list={playlist}"
        )

    def test_app_id_prefers_webos4_leanback(self) -> None:
        apps = [
            {"id": "youtube.leanback.other", "title": "YouTube"},
            {"id": "youtube.leanback.v4", "title": "YouTube"},
        ]
        self.assertEqual(
            youtube.find_youtube_app_id(apps), "youtube.leanback.v4"
        )
        self.assertEqual(
            youtube.find_youtube_app_id([{"id": "youtube.leanback.v3"}]),
            "youtube.leanback.v3",
        )
        self.assertEqual(
            youtube.find_youtube_app_id([{"id": "netflix"}]),
            "youtube.leanback.v4",
        )
        self.assertEqual(youtube.find_youtube_app_id(None), "youtube.leanback.v4")
        self.assertEqual(
            youtube.find_youtube_app_id({"youtube.leanback.v4": {}}),
            "youtube.leanback.v4",
        )


class NetTests(unittest.TestCase):
    def test_normalize_mac(self) -> None:
        self.assertEqual(net.normalize_mac("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")
        self.assertEqual(net.normalize_mac("aabbccddeeff"), "aa:bb:cc:dd:ee:ff")
        with self.assertRaises(ValueError):
            net.normalize_mac("aa:bb")

    def test_normalize_host(self) -> None:
        self.assertEqual(net.normalize_host(" http://192.168.1.20/ "), "192.168.1.20")
        self.assertEqual(net.normalize_host("tv.local"), "tv.local")
        self.assertEqual(net.normalize_host(""), "")


if __name__ == "__main__":
    unittest.main()
