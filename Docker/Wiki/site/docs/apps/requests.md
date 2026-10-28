# Requesting films & series

**Address:** `https://requests.holy-grail.ch`

1. Open the address and press **Holy Grail** to sign in. Your account is created on the first login.
2. Search for a title (or browse with **Discover**), open it and press **Request**.
3. Your request is approved automatically. The title is downloaded and appears in Jellyfin on its own.
4. Follow its status under **Requests**.

Looking for an audiobook? Use the **Audiobooks** entry in the menu (after Series), see [Requesting audiobooks](audiobook-requests.md).

!!! info "Needs the requester role"
    Requests are not switched on for every account. If the tile is missing or you get "no permission", ask the admin.

!!! info "The media server sleeps"
    Requests runs on the media server. If it is asleep you see a **"Requests is starting"** page: wait about a minute and it opens by itself (reload if it doesn't). If your browser shows the "asleep, sign in to start" page instead, log in and wait, see [Watching](jellyfin.md).

## Can wait: download tonight
The request dialog has a checkbox, **ticked by default**: **Can wait, download tonight (cheaper power)**.

| Box | What happens |
|---|---|
| Ticked | the title is searched at once, the download starts at night (22:00-06:00, all Sunday) when power is cheaper |
| Unticked | downloads at once (first download only; later episodes and upgrades wait for the night again) |

Untick it only when you want to watch it soon.

A title waiting for the night shows **Waiting for the night 🌙** instead of a stuck 0 %. That is normal.

Small icons next to the status and on the posters (hover, or tap on the phone, shows what they mean):

| Icon | Means |
|---|---|
| 🌙 | Can wait: downloads at night (cheaper power) |
| 🧭 | searched, nothing found yet; tonight's search (04:17) keeps looking |
| 📅 | not released yet (with the expected date) |
| spinning ring | downloading now, with the percent |
| ✅ | available in Jellyfin |
| ☑️ | partly available (the rest can show 🌙 🧭 📅 next to it) |

**At night:** films download in parallel, series one after another, episodes in order.

!!! info "Download now"
    Open a title **you requested** → **⚡ Download now** (next to the request button). It starts the waiting download at once, at the higher daytime power price. Titles other people requested have no button; admins see it on every title.

    Nothing grabbed yet: it searches first. **🔍 Searching…** shows while the search runs (several searches run one after the other). Found → **✅ Downloading**. Nothing found → **🧭 No release found yet**: the title goes back to the night queue (🌙) and tonight's search keeps looking; **⚡ Search again** tries once more.

## My request: see and change it
Open a title **you requested** → the card **My request** under the title (tap to open).

| You can | How |
|---|---|
| change the quality | pick another in **Quality** |
| add or remove audio / subtitle languages | × on a language, or **Add…** |
| switch Can wait on or off | the checkbox (off = downloads at once, like ⚡ Download now) |
| delete your request | **Delete request**; the question says exactly what goes |

Press **Save**; the server searches again within 2 minutes. If someone else requested the same title too, the card is read-only: ask the admin to change it. Deleting then removes only your request; the title stays.

## Search tips

The search box understands four prefixes. Only one per search.

| Type this | Finds |
|---|---|
| `imdb:tt0111161` | the film or series with that IMDb number |
| `tmdb:278` | the TMDB number |
| `tvdb:81189` | a series by its TheTVDB number |
| `matrix year:1999` | a title, narrowed to one year (good for remakes) |

!!! tip "Where do I find the IMDb number?"
    It's in the IMDb address: `imdb.com/title/`**`tt0111161`**`/`. Type it with the prefix: `imdb:tt0111161`.

## Browsing with filters
**Discover → Movies** (or **Series**) → filter icon (top right):

- **Release date** from/to
- **Genres**, **Keywords** (and keywords to exclude)
- **Original language**
- **Streaming services** available in Switzerland (Netflix, Disney+, …)
- **Runtime**, **TMDB user score** + **minimum votes**, **age rating**, **status** (series)

!!! example "Example"
    German-language comedies since 2015, score at least 7, on Netflix CH: Original language *German* · Genres *Comedy* · Release date from *2015* · TMDB user score *7–10*, minimum votes *200* · Streaming services *Netflix*.

## Which version gets downloaded
You don't need to choose anything: the server picks the best version automatically, in this order.

| Order | What counts | Example |
|---|---|---|
| 1 | **Hard language tag** (if you set one under *Advanced*) | `audio-swiss-german`: without Swiss German nothing is downloaded |
| 2 | **Resolution and source** | 4K before 1080p; 4K Blu-ray › 4K web |
| 3 | **HDR** | at the same resolution, HDR beats non-HDR whatever the languages; 4K without HDR still beats 1080p HDR |
| 4 | **Languages** | original + English + German › original + English › original + German › original only |
| 5 | Source, release group, sound | Atmos, lossless audio, known good groups |
| 6 | **Extra languages** (Spanish, …) | only a tie-break: a clean Apple TV / Netflix release beats a dub-heavy one |

Also counted:

| Rule | What it means for you |
|---|---|
| **Complete season packs** are preferred over single episodes of the same quality | a season may arrive as one big download: fewer, faster downloads |
| Torrents need at least **5 seeders** (old & rare titles: 1) | rare old films can take longer, or may not be found |
| **Usenet** is preferred when everything else is equal | |

A film that is already there is replaced by a better version (also one with better audio or an extra language) until it is 4K HDR with the original language and English (for English films: with German; anime: 1080p with original + English); after that it stays. German-only dubs are never downloaded.

If the server grabbed the wrong film (same title, different year), it notices and replaces it automatically.

!!! note "Languages come from the release name"
    The server mainly knows the languages written in a release's name (e.g. *German.DL* = German + original). For a release that only says *MULTi*, it also reads the release's info file (NFO) where the indexer offers it; without one, it counts as original only until it has been downloaded. *MULTi* releases that only contain dubs and no original track are blocked automatically.

## Advanced options
In the request dialog, **Advanced** is only needed in special cases. Leave the quality profile on the default (**4K preferred · older versions allowed**).

| You want | Choose |
|---|---|
| a must-have audio language | Tags: `audio-<language>`. A hard filter: nothing is downloaded without that audio |
| Swiss German (Mundart) | Tags: `audio-swiss-german`. Only Swiss German, any quality; if none exists nothing is downloaded |
| extra subtitles | Tags: `subs-<language>`, on top of English, German and the original language |

Old and rare titles are moved to a more tolerant quality profile automatically.

## What happens after a request
Your request is searched for, downloaded (tonight, if **Can wait** is ticked) and added to Jellyfin, with audio and subtitles as described in [Audio & subtitles](../audio-subtitles.md). Rare films can take longer to find, or may not be found at all.

## The indexer bar at the top
A thin bar at the top of every Requests page shows how much of the search services (indexers) is used up. **more** opens the full list; click **Indexers** to make the bar smaller.

| You see | Means |
|---|---|
| `8/100 searches` | searches used / allowed in the current window |
| `0/5 downloads` | downloads used / allowed |
| green · amber · red | under 70 % · 70–95 % · 95 % or used up |
| `used up, resets 14:32` | that indexer pauses until then |
| `∞` (under **more**) | no limit, only the count of the last 24 hours |
| Subscriptions | days left until a paid service ends; amber 14 days or less, red 3 days or less; `lifetime` never ends |
| `usage unavailable` | the numbers can't be read right now; requests still work |

- **Used up:** your request may wait until the indexer resets. The other indexers keep searching.
- **When it resets:** "last 24 h" indexers when their oldest counted search is 24 hours old; "per day" indexers at midnight.
- Searches made by hand on the indexer websites are not counted.

!!! note "Admin: limits and renewal dates"
    Both live in `indexer-bar/limits.toml` in the Seerr project on the media server. After a renewal change the `expires` date (or set `lifetime = true`); the bar picks it up within a minute.
