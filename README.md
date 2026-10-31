# LG YouTube

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kiwaili&repository=home-assistant-lg-youtube&category=integration)

Home Assistant custom integration that takes a YouTube URL and opens that video on an LG webOS TV. Written for a **32LM6300PCB on webOS 4.10**, and it uses the same launch the existing webOS tools use on that generation.

The TV's YouTube app id is `youtube.leanback.v4`. The video is not passed as a normal browser link. It is passed as:

```text
ssap://system.launcher/launch
{
  "id": "youtube.leanback.v4",
  "params": {
    "contentTarget": "http://www.youtube.com/tv?v=VIDEO_ID"
  }
}
```

That payload is what [klattimer/LGWebOSRemote](https://github.com/klattimer/LGWebOSRemote) sends from `openYoutubeURL`, and the same shape [Hybirdss/smartest-tv](https://github.com/Hybirdss/smartest-tv) uses for YouTube. The socket library is [aiowebostv](https://github.com/home-assistant-libs/aiowebostv) 0.10.0, which is the client the built-in [LG webOS TV](https://www.home-assistant.io/integrations/webostv/) integration uses. On webOS 4 it connects to `ws://<tv>:3000` first.

webOS 4 ignores a second launch while YouTube is already on screen, so a new URL closes YouTube, waits briefly, then launches again.

## Install

Requires Home Assistant 2025.1 or newer, and [HACS](https://hacs.xyz/).

[Open this repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=kiwaili&repository=home-assistant-lg-youtube&category=integration), or add it by hand:

1. In HACS, open **Integrations**.
2. Open the menu in the top right and choose **Custom repositories**.
3. Repository: `https://github.com/kiwaili/home-assistant-lg-youtube`
4. Category: **Integration**.
5. Click **Add**, then download **LG YouTube**.
6. Restart Home Assistant if HACS asks you to.
7. **Settings → Devices & services → Add integration → LG YouTube**.

To install without HACS, copy `custom_components/lg_youtube` into your config directory so this file exists:

```text
<config>/custom_components/lg_youtube/manifest.json
```

Restart Home Assistant, then add the **LG YouTube** integration.

## Pairing

1. Turn the TV on. It has to be on the same LAN as Home Assistant.
2. Enter the TV's IP address. A MAC address is optional and is only used for Wake-on-LAN.
3. Submit the pairing step, then accept the prompt on the TV. The prompt only stays up for a few seconds.
4. The integration reads the app list and stores `youtube.leanback.v4` when the TV reports it.

The client key is stored in the config entry, the same way the built-in LG webOS TV integration stores it.

If the TV's IP changes later, open the device and choose **Reconfigure**. That screen is also where you add or clear the MAC address. Wake-on-LAN needs the TV's **Mobile On** / **LG Connect Apps** / network standby option enabled, and Home Assistant has to be able to broadcast on the LAN.

## Play a video

Any of these are accepted: a `youtube.com/watch` link, a `youtu.be` link, Shorts, a live URL, an embed URL, a playlist URL, or the 11-character video id.

**Text box.** The device has a **YouTube URL** entity. Paste a link and it plays. Clearing the box does not stop the TV.

**Action:**

```yaml
action: lg_youtube.play
target:
  entity_id: media_player.lg_tv
data:
  url: "https://www.youtube.com/watch?v=jNQXAC9IVRw"
```

**Media player:**

```yaml
action: media_player.play_media
target:
  entity_id: media_player.lg_tv
data:
  media_content_type: video
  media_content_id: "https://youtu.be/jNQXAC9IVRw"
```

The player can also turn the TV on (when a MAC is set) and off, and it can set volume. Play and pause use the TV's media keys; those keys are not reliable inside the YouTube app on every firmware, and the URL launch does not depend on them.

## If the app opens but the video does not

Open **Configure** on the integration:

- **Close YouTube before opening a new video** should stay on for webOS 4.10.
- **Launch method** defaults to `contentTarget (webOS 4)`. The other two match older `contentId` examples from the Home Assistant community and from pylgtv: the bare video id, or the `http://www.youtube.com/tv?v=` URL placed in `contentId`.
- **YouTube app id** stays `youtube.leanback.v4` unless the TV listed a different YouTube id while pairing.

## One controller at a time

This integration keeps its own connection to the TV. webOS 4 often accepts only one SSAP client. If the built-in **LG webOS TV** integration is also connected to the same set, one of the two sessions can drop. Use this integration for the YouTube URL flow, or use the built-in integration's `webostv.command` action with the payload above if you already rely on that connection.

## Development

```text
python -m unittest discover -s tests -v
```

The tests cover URL parsing and MAC/host cleanup. They do not talk to a TV.
