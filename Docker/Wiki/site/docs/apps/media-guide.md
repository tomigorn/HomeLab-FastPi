# How to use the media stack

The short guide: which app where, how to watch, find and request. Details are one click away.

## 1. Which app where

| Where | Use | Sign in |
|---|---|---|
| Laptop / PC browser | **Jellyfin website** `jellyfin.holy-grail.ch` | **Sign In with Holy Grail** |
| Apple TV, Android TV / Google TV | **Moonfin** app | **Quick Connect** |
| iPhone / iPad, Android phone | **Moonfin** app | **Quick Connect** |
| Samsung TV | **Moonfin** via the [Samsung guide](moonfin.md#samsung-tv-tizen) | **Quick Connect** |

Quick Connect in 3 steps: the TV shows a code → on your laptop open Jellyfin → profile → **Quick Connect** → enter the code. Details: [Moonfin](moonfin.md#2-sign-in-quick-connect-all-devices-incl-samsung).

## 2. Watching

| I want to | Do this |
|---|---|
| carry on | **Continue Watching** row on the home screen |
| next episode of a show | **Next Up** row |
| start on the big screen from the website | **▶ Play on TV** on a card, pick your TV |
| subtitles | set your language once: [Audio & subtitles](../audio-subtitles.md) |
| skip an intro | press **Skip intro**: [Skip buttons](skip-buttons.md) |

- **Play on TV** is on Popular, Top 10 and Coming soon cards. Soon also on every title page and in the player as **Continue on TV**.
- It only lists TVs where **Moonfin is open**. Open the app on the TV first.

## 3. Finding something new

| Look at | What it is |
|---|---|
| **Popular movies** / **Popular shows** | what streams in Switzerland now |
| **Top 10** rows | Netflix's weekly Top 10 for Switzerland, with 🇨🇭 rank badges |
| **Coming soon** | new episodes and films with their date |
| **Hidden Gems** | well rated, not watched yet |
| **For you** | a showcase picked just for you (big banner at the top in Moonfin) |
| Studio rows, genre lists | browse by studio, network or genre |
| Collections | film series, e.g. all Harry Potter films |

- On the TV the lists are **collections and rows** in Moonfin (home, or Collections & Trending).
- All rows explained: [Home screen](jellyfin-home.md).

## 4. Requesting a film or show

Not here yet? Ask for it. Pick one way:

| Where | Steps |
|---|---|
| **Jellyfin website** (Popular cards) | press **🌙 Download tonight** or **⚡ Download now** on the card |
| **Moonfin** (TV, phone) | open the title → **Request** → **Advanced** → **🌙 Tonight** or **⚡ Now** → Submit |
| **Samsung TV** | website → Popular → **Code for TV**, then enter it in Moonfin: [steps](moonfin.md#4-samsung-requests-sign-in-with-code-for-tv) |
| **requests.holy-grail.ch** | search, open the title, **Request**; the box **Can wait, download tonight** is ticked by default |

| | 🌙 Tonight | ⚡ Now |
|---|---|---|
| Downloads | at night (22:00-06:00) | right away |
| Electricity | cheaper | daytime price |
| Choose it | default, when you can wait | when you want to watch soon |

### On requests.holy-grail.ch
- **Search tips:** type `imdb:tt0111161` for an exact title, or `matrix year:1999` to narrow by year.
- **Download now:** open a title you requested → **⚡ Download now**.
- **All requests:** the **Requests** page shows everyone's, marked **via Jellyfin**, **via Moonfin** or **via TV**.
- **Status pills** (e.g. Waiting for the night, Downloading, Available): all icons in [Requesting](requests.md#can-wait-download-tonight).

### Limits

| Limit | Value |
|---|---|
| per person | **10 requests per 7 days** |
| everyone together | **30 per day** |

- At the limit the button says so (Moonfin: **Request limit reached**).
- A grey card with a red banner **Not able to download**: no good version exists yet. It is checked again every night; the buttons appear by themselves.
- Timing: **Tonight** downloads between 22:00 and 06:00, **Now** starts right away. Rare titles can take longer or may not be found.

### Which version gets downloaded
The server picks the best one by itself (4K before 1080p, original language plus English and German). Nothing to choose: [Which version gets downloaded](requests.md#which-version-gets-downloaded).

## 5. Problems

| Problem | What to do |
|---|---|
| The title isn't there yet | check the card or [Requests](requests.md#can-wait-download-tonight): 🌙 waits for tonight, 🔍 is searching, 📅 is not released yet |
| It says "requested" for a long time | nothing to do, it comes by itself; **⚡ Download now** speeds it up |
| Wrong subtitle track | pick another while playing; never choose **Forced** for full subtitles: [Audio & subtitles](../audio-subtitles.md) |
| No TV in the Play on TV list | open **Moonfin on the TV** first, then try again |
| First start is slow | the media server sleeps to save power: wait about 45 seconds to a minute |

More: [Help & FAQ](../help.md).
