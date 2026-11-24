# Report a problem

**Address:** `https://report.holy-grail.ch`

A film or episode won't play, has broken picture or sound, or is the wrong one? Report it: the server fixes most problems by itself, no admin needed. Works on the phone too.

## Baby steps
1. Open `https://report.holy-grail.ch`.
2. Search the title, or pick it from the list below the search (**Films** | **Series**, sort A–Z, release year, recently added or **recently watched by you**).
3. Series: pick the season and the episode.
4. Pick **what is wrong**. Add a note if you like (needed for **Other**).
5. Send. The status page updates by itself.

!!! tip "From Jellyfin"
    In Jellyfin in the browser, film, series, season and episode pages have a **⚠ Report a problem** link next to the TMDB/IMDb links. It opens the report with the title already picked. The TV and phone apps don't have the link: open the address directly.

## What the server does

| You pick | What happens |
|---|---|
| Doesn't start / stops, picture glitches, sound glitches, wrong title or episode | the broken version is blocked and another one downloads at once |
| Bad video quality | a better version downloads, if there is one ("no better version found" otherwise) |
| No sound / wrong audio track, wrong language | if the file has German, English or the original language, the admin has a look (try switching the track first: [Audio & subtitles](../audio-subtitles.md)); otherwise a version with one of them downloads |
| Subtitles missing, wrong or out of sync | the subtitles are searched again; the film stays as it is |
| Other | the admin has a look |

- You keep the old version until the new one is in Jellyfin.
- Nothing found? The report stays open and the admin has a look.

## Limits
- **2 reports per day.**
- **1 open report per film or episode.** Someone was faster? You see their report's status instead.
