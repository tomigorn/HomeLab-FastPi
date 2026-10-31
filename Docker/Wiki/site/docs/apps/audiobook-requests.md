# Requesting audiobooks

**Address:** `https://books.holy-grail.ch`

Also in Requests: the **Audiobooks** entry in the menu (after Series) opens it.

1. Open the address and sign in with **Holy Grail**.
2. Search for a book and pick the right **edition** (see below).
3. Press the request button. The download starts at once, no approval needed.

## Requesting

### Language = edition
The language of the book is the Audible edition you pick. For a German book, switch the search **region to `de`** and pick the German edition. English is the default. If no release in that language exists, nothing is downloaded and the request stays open.

### Which release gets downloaded
Automatic, in this order:

| Order | What counts |
|---|---|
| 1 | **Unabridged** (abridged only when no unabridged release exists) |
| 2 | **M4B** before MP3 or FLAC |
| 3 | free-to-download releases first |
| 4 | newest upload |

Books made of several files are merged into one M4B with chapters.

### Limit
**5 books per 7 days** per person, everyone included. The 6th request shows "Limit reached": wait until an earlier one is a week old.

## Your requests

### All requests
**All requests** (top menu) lists everyone's requests: who asked, date, size, cover and status (open, downloading, in library). **Sort** shows the largest or smallest first.

### Sizes on the wishlist
**Requests** and **Downloaded** show a **Size** column. Click **Size** to sort: largest first, smallest first, back to normal. `–` = size not known yet.

## Finding your book

### Where do I find the book?
In [Audiobookshelf](audiobookshelf.md), in the library of its language (English, German, other), under author and title. The book appears after the download and import, normally within minutes to hours. Cover, narrator and description are filled in automatically.

!!! note "Already in the library?"
    The search shows a badge and the request button is disabled.

### Library
**Library** (top menu) lists every book you can open in [Audiobookshelf](audiobookshelf.md), not only requests: cover, title, author, narrator, series, length, size, date added.

| Do | How |
|---|---|
| find a book | type in the search box (title, author, narrator, series) |
| sort | newest added, title, author, largest, smallest, longest |
| one language only | pick the library (English, German, other) |
| listen | **Open in Audiobookshelf** |

You see exactly what your Audiobookshelf account sees. "No Audiobookshelf account yet": open Audiobookshelf once (Login with Holy Grail), then reload.

## The bar at the top
The same thin bar as in [Requests](requests.md#the-indexer-bar-at-the-top), on every audiobook page. **more** opens the full list; click **Indexers** to make the bar smaller.

| You see | Means |
|---|---|
| `MyAnonamouse 2/∞ searches 0/∞ downloads` | searches and downloads of the last 24 hours; `∞` = no limit |
| `My requests 1/5 in 7 days` | your own requests this week; red with "next free" when all 5 are used |
| `MAM unsatisfied 12/150` | MyAnonamouse downloads that have not seeded 72 h yet (MAM rule: 72 h in total within 30 days), of the limit for our class; green under 70 %, yellow 70–90 %, red from 90 % |
| `… 1 at risk` (red) | a MAM torrent was paused or removed before its 72 h; **more** names it. Resume it in qBittorrent |
| `Next renewal: ProtonVPN Plus in 230 d` | days until the VPN the downloads use must be renewed |
| `MAM VIP 20 days left` | the MyAnonamouse VIP class ends; yellow 30 days or less, orange 7 or less, red on the end date |
| `Library 376 GB/1.8 TB 22 %` | the Audiobookshelf disk |
| `Downloads 253 GB/1.8 TB 14 %` | the download disk; torrents keep seeding, so it only grows |
| green · yellow · red (disks) | under 70 % · 70–80 % · from 80 % |

Point at a disk (or open **more**) for the free space; point at **MAM unsatisfied** for when the next one is done. Nothing is deleted automatically. German browsers get the disk texts in German.
