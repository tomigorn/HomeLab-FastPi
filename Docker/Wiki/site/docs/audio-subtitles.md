# Audio & subtitles

## Which version do we get?
We always keep the **original language**, plus German and English audio when a release has them. Ranking, best first:

| Rank | Audio in the file |
|---|---|
| 1 | original + German + English |
| 2 | original + English |
| 3 | original + German |
| 4 | original only |

A release that only has a dub and no original track is never taken. The same applies to films, series and anime. Titles already in the library are upgraded when a better version exists, up to 4K HDR (see the full order below).

Picture quality (resolution, HDR) is decided **before** languages; with equal picture and rank, a release with **more extra languages** wins. Full order: [Which version gets downloaded](apps/requests.md#which-version-gets-downloaded).

**Subtitles:** English, German and the original language, each synced to the original voices.

## What plays by default?
Jellyfin starts with the **original language** (the track is labelled **(Original)**), unless you've set a preferred audio language in your profile and that language exists for the title. Tracks you pick yourself are remembered per film or episode.

!!! tip "Set your subtitle language once"
    Jellyfin web or phone app: profile → **Settings** → **Subtitles** → **Preferred subtitle language**. Without it, subtitles only appear for forced parts.

## Subtitles automatically when the audio isn't your language

Set this once and Jellyfin turns on subtitles by itself whenever the film plays in another language:

1. Open Jellyfin in the browser → your **profile icon** (top right) → **Settings** → **Subtitles**.
2. **Preferred subtitle language:** your language, e.g. *English*.
3. **Subtitle mode:** **Smart**.
4. **Save**.

| The film plays in… | You get |
|---|---|
| another language (e.g. the Spanish original) | subtitles in your language |
| your language | no subtitles (only short foreign-language parts, if the file has them) |

!!! info
    This is saved in your profile, so it works on your TV and phone apps too. Jellyfin allows one subtitle language. Set **Playback → Preferred audio language** the same way if you want a dub in your language whenever one exists.

## Switching audio or subtitles

| Where | Audio | Subtitles |
|---|---|---|
| Browser, Android and iPhone apps | film page: **Audio** dropdown under Play; while playing: **Audio** button in the bottom bar | while playing: subtitle button in the bottom bar |
| Android TV | playback overlay: **Select audio track** | playback overlay: subtitle button |

!!! note "Swiss German"
    A Swiss German track is often labelled "German" like High German. Pick it by its title (for example "Schweizerdeutsch").

!!! tip "Subtitles feel early or late?"
    Subtitles are timed to the **original voices**. If you watch a dub, switch the audio to the original.
