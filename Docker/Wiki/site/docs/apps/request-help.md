# My request isn't there yet

## Check the status
<!-- only: streaming-requesters -->
1. Open `https://requests.holy-grail.ch`.
2. Press **Requests** in the menu.
3. Find your title. Look at the **icon** next to it.
<!-- /only -->
<!-- only: !streaming-requesters -->
Find the title in **Popular movies** or **Popular shows** in Jellyfin. The card shows where it stands: 🌙 waits for the night, 🔍 is searching, 📅 is not released yet, ⬇️ is downloading. Once it is in Jellyfin the poster is no longer dimmed. All cards: [Home screen](jellyfin-home.md#the-cards).
<!-- /only -->

<!-- only: streaming-requesters -->
| You see | Means | What to do |
|---|---|---|
| 🌙 **Waiting for the night** | it downloads tonight (22:00-06:00, all Sunday), when power is cheap | wait until morning |
| magnifier | searching right now | wait a few minutes |
| 🧭 | searched, nothing found yet | nothing: it searches again every night |
| 📅 | not released yet | nothing: it comes after the release |
| spinning ring | downloading now | wait |
| ✅ | ready in Jellyfin | press play. Not visible? Reload Jellyfin |
| ⚠️ | a problem | hover or tap it to read why. The server tries again by itself |

All icons: [Status icons](requests.md#status-icons). ⚠️ or 🧭 for days: anyone can help in [Manual interaction](requests.md#manual-interaction).
<!-- /only -->

## I want it sooner
<!-- only: streaming-requesters -->
1. Open your title in Requests.
2. Press **⚡ Download now** (next to the request button).
3. It starts at once. It costs more power, so use it only when you need it.

The button is only on titles **you** requested.
<!-- /only -->
<!-- only: !streaming-requesters -->
Ask the admin.
<!-- /only -->

## Still not there?
| Case | What to do |
|---|---|
| Status ✅ but not in Jellyfin | reload Jellyfin. A sleeping server needs a minute: [Why you sometimes wait](waiting.md) |
| 🧭 for many days | rare titles can take long, or never appear. Ask the admin |
| The request button is missing | you have no request right. Ask the admin |
| "Request limit reached" | 10 requests per 7 days. Try again later |
| It's there but won't play, or picture or sound is broken | [Report a problem](report.md): the server replaces it |

<!-- only: streaming-requesters -->
Audiobook instead? [Request audiobooks](audiobook-requests.md).
<!-- /only -->
