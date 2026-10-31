# LG YouTube

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kiwaili&repository=home-assistant-lg-youtube&category=integration)

Play a YouTube URL on an LG webOS TV. Aimed at the 32LM6300PCB on webOS 4.10.

## Install with HACS

Requires Home Assistant 2025.1 or newer.

1. In HACS, open **Integrations**.
2. Open the menu in the top right and choose **Custom repositories**.
3. Repository: `https://github.com/kiwaili/home-assistant-lg-youtube`
4. Category: **Integration**.
5. Click **Add**, then download **LG YouTube**.
6. Restart Home Assistant if HACS asks you to.
7. **Settings → Devices & services → Add integration → LG YouTube**.

## Use

Paste a YouTube link into the **YouTube URL** text entity, or run:

```yaml
action: lg_youtube.play
target:
  entity_id: media_player.lg_tv
data:
  url: "https://www.youtube.com/watch?v=jNQXAC9IVRw"
```

`youtube.com`, `youtu.be`, Shorts, live links, playlists, and an 11-character video id are all accepted.

The TV must be on for pairing. Accept the prompt on the TV within a few seconds. A MAC address is optional and is only used to turn the TV on later.
