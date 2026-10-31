# LG YouTube

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kiwaili&repository=home-assistant-lg-youtube&category=integration)

Home Assistant custom integration that takes a YouTube URL and opens that video on an LG webOS TV. Written for a **32LM6300PCB on webOS 4.10**, and it uses the same launch the existing webOS tools use on that generation.

The TV's YouTube app id is `youtube.leanback.v4`. The video is not passed as a normal browser link. It is passed as one launch:

```text
ssap://system.launcher/launch
{
  "id": "youtube.leanback.v4",
  "params": {
    "contentTarget": "v=VIDEO_ID"
  }
}
```

`v=VIDEO_ID` is the deeplink the YouTube app is registered for. The full `http://www.youtube.com/tv?v=VIDEO_ID` address, which [klattimer/LGWebOSRemote](https://github.com/klattimer/LGWebOSRemote) and [Hybirdss/smartest-tv](https://github.com/Hybirdss/smartest-tv) send, makes this set boot the app and then load that page, so YouTube shows its loading screen, opens again, and loads again. The socket library is [aiowebostv](https://github.com/home-assistant-libs/aiowebostv) 0.10.0, which is the client the built-in [LG webOS TV](https://www.home-assistant.io/integrations/webostv/) integration uses. On webOS 4 it connects to `ws://<tv>:3000` first.

webOS 4 ignores a new launch while YouTube is already on screen. A new URL closes YouTube only in that case, waits briefly, then launches once. A cold start does not close the app first, and a repeated request for the same video is ignored while the first launch is still opening.

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

Add the built-in **LG webOS TV** integration first, then add **LG YouTube** and select that TV. YouTube sends commands through that connection, so the webOS media player stays connected.

Choose **Pair a TV that is not in this list** only when the set is not already in the LG webOS TV integration. The TV has to be on. Accept the prompt on the TV within a few seconds. A MAC address is optional and is only used to wake it.

**Reconfigure** changes which LG webOS TV is selected. For a TV that was paired separately, that screen is where the address and MAC address are changed. Wake-on-LAN needs the TV's **Mobile On** / **LG Connect Apps** / network standby option enabled, and Home Assistant has to be able to broadcast on the LAN.

## Play a video

Any of these are accepted: a `youtube.com/watch` link, a `youtu.be` link, Shorts, a live URL, an embed URL, a playlist URL, or the 11-character video id.

**Text box.** The device has a **YouTube URL** entity. Paste a link and it plays. Clearing the box does not stop the TV.

**Action:**

```yaml
action: lg_youtube.play
target:
  entity_id: media_player.lg_tv_youtube
data:
  url: "https://www.youtube.com/watch?v=jNQXAC9IVRw"
```

**Media player:**

```yaml
action: media_player.play_media
target:
  entity_id: media_player.lg_tv_youtube
data:
  media_content_type: video
  media_content_id: "https://youtu.be/jNQXAC9IVRw"
```

The player can also turn the TV on (when a MAC is set) and off, and it can set volume. Play and pause use the TV's media keys; those keys are not reliable inside the YouTube app on every firmware, and the URL launch does not depend on them.

## YouTube account

The device has a **YouTube account** selector. The official app has no way to name a profile in the launch, so this uses the Who's watching screen.

**Ask on the TV** is the default. No remote keys are sent.

**Account 1** is the leftmost profile. Account 2 is the next one to the right, and so on through Account 6. After YouTube opens, the integration waits (6 seconds unless you change it under **Configure**), presses Left until the highlight is on the first profile, presses Right to the account you chose, then OK.

Leave it on **Ask on the TV** when that screen does not appear. Otherwise those keys land on the video.

## If the app opens but the video does not

Open **Configure** on the integration:

- **Close YouTube before opening a new video** stays on. It runs only when YouTube is already the app on screen.
- **Launch method** defaults to `contentTarget (v= video id)`. That is one launch. The other two match older `contentId` examples: the bare video id, or the leanback `http://www.youtube.com/tv?v=` address placed in `contentId`. The leanback address can make the app load twice.
- **YouTube app id** stays `youtube.leanback.v4` unless the TV listed a different YouTube id while pairing.

## One controller at a time

When you select a TV from the LG webOS TV integration, this integration does not open a second connection. webOS 4 often accepts only one controller, and the built-in media player keeps its session. A separately paired TV uses its own connection.

## Development

```text
python -m unittest discover -s tests -v
```

The tests cover URL parsing and MAC/host cleanup. They do not talk to a TV.
