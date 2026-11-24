# How long titles stay

New films and series don't stay forever: the disks would fill up. Old, rare and top-rated titles stay.

## The rule
| Title | Stays |
|---|---|
| most titles | **3 months** after the download or the **last play by anyone**. Watching it starts the 3 months again |
| **♾️ Keep forever** | always. By default: released 12 or more years ago, rare (few votes, Swiss German), or top-rated (IMDb 8.0 or more, with 25 000 votes or more) |

- Before it goes, a title shows **Leaving soon** for **7 days**.
- Nothing is removed that someone is in the middle of (Continue Watching, Next Up) or played in the last 14 days.
- After 1 month every title moves from the fast disk to the big one. It still plays, the first seconds may take a little longer.
- The big disk over 85 % full: the oldest titles leave a bit earlier.
- A title that left can be downloaded again at any time. Your likes and ratings in the [Tracker](tracker.md) stay.

## In Jellyfin
Two lists show what is leaving and what has left:

| List | Shows |
|---|---|
| **Leaving soon** | titles leaving in the next 7 days. Watch them now, or play them to keep them 3 more months |
| **Left the server** | titles that were removed. Download one again like a Top 10 title: **⬇ Download movie now** or **🌙 Download movie tonight** |

Where: on the TV **Media** (Android TV: **My media**) → **Collections & Trending**; in the browser **Collections**. How to download from a list: [Trending on the TV](jellyfin.md#trending-on-the-tv).

<!-- only: streaming-requesters -->
## In Requests
Every title in the library shows **On the server** on its page, and the same pill on the **Requests** page:

| Pill | Means |
|---|---|
| `🗑 Leaves on 26 Jan 2027` | leaves that day (3 months after the last play, or after the download if nobody played it). Tap it for the details |
| `♾️ Kept forever` | never leaves |
| orange `Leaving soon · 19 Nov` | leaves within 7 days |

### Keep forever
| Where | How |
|---|---|
| when requesting | tick **♾️ Keep forever** (below **Can wait**). It is ticked already for titles that are kept by default |
| a title in the library | its page → **On the server** → **♾️ Keep forever** |
| undo | **Let it leave**: only someone who requested the title, or the admin |

Anyone who may request can mark any title **Keep forever**. Use it for titles worth keeping, not for everything.

## Delete early
Watched it and don't need it anymore? Remove it before the 3 months end, so the space comes back sooner.

1. Open the title in Requests.
2. In the facts box, row **Delete early**, press **🗑 Delete early**. Series: pick **Whole series** or one **Season**.
3. Press **🗑 Delete**. The box shows how many deletions you have left this week.

| Rule | What |
|---|---|
| Recycle bin | the files stay **7 days** in the recycle bin. **↩ Restore** on the title page brings them back (you, someone who requested it, or the admin) |
| Limit | **10 per week** per person |
| Needs an OK | a title marked **♾️ Keep forever** that you didn't request → someone who requested it is asked. Someone else is in the middle of it (played in the last 30 days, not finished) → that person is asked. They answer with **✅ Approve** / **✖ Deny** on the title page. No answer in 7 days = not deleted |
| Told | if you delete someone else's request, they get a message with a link to restore it |
| Afterwards | the title stays in Requests and can be requested again. It shows in **Left the server** in Jellyfin |
<!-- /only -->
