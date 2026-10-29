# Watching with Jellyfin

**Address:** `https://jellyfin.holy-grail.ch`

**Server version:** Jellyfin **12.2** (October 2026). TV and phone apps must be made for version **12**: an older app (10.x) can't connect.

## On the laptop/PC in the browser
1. Open the address.
2. Press **Sign In with Holy Grail**. There is no password field in Jellyfin itself: your Holy Grail account is the only login.
3. Pick something and press play.

!!! tip "Hardware acceleration: leave it ON"
    With it on, your graphics chip decodes the video: smoother playback, less battery and fan, and the server more often streams the original file instead of converting it. It is on by default; turn it **off only if** videos stay black, show green blocks or stutter, then restart the browser.

    | Browser | Where |
    |---|---|
    | Chrome, Brave, Edge | **Settings → System → Use graphics acceleration when available** (older versions: *hardware acceleration*) → **Relaunch** |
    | Firefox | **Settings → General → Performance** → untick *Use recommended performance settings* → **Use hardware acceleration when available** → restart Firefox |
    | Safari (Mac, iPhone, iPad) | **nothing to do**: always on, Safari has no switch for it |

!!! info "The media server sleeps"
    To save power the media server sleeps when nobody uses it. If it is asleep, your browser shows an **"asleep, sign in to start"** page instead. Log in with Holy Grail and a waiting page starts the server and sends you on to Jellyfin when it's ready, after about a minute. Just wait on the page.

## On your TV or phone (apps)
The apps can't show the Holy Grail login page, so you connect them with **Quick Connect**.

1. Install the **Jellyfin** app. Official apps exist for these:

    | Device | Where |
    |---|---|
    | Android phone / tablet | Google Play, F-Droid, Amazon Appstore |
    | Android TV and Fire TV | Google Play, F-Droid, Amazon Appstore |
    | iPhone / iPad | App Store |
    | LG TV (webOS) | LG Content Store |
    | Samsung TV (Tizen) | Samsung Smart TV App Store, or [install it yourself](#samsung-tv-install-the-app-yourself) |
    | Roku | Roku Channel Store |

2. Server address: `https://jellyfin.holy-grail.ch` (**not** `sso.holy-grail.ch`: that is only the login page, the app finds no server there)
3. In the app choose **Quick Connect**. It shows a **6-character code**.
4. On your phone or computer, open Jellyfin in the browser (signed in) → your profile menu → **Quick Connect** → enter the code → **Authorize**.
5. The TV app is now signed in.

!!! tip "App can't connect?"
    Opening an app also wakes a sleeping server. Wait a minute and try again.

### Trending on the TV
Open **Media** (Android TV: **My media**) → **Collections & Trending**. Pick a list (Top 10 Switzerland, Coming soon, a service or genre), then a title. Under **Version** (Apple TV: **⋯** next to Play) choose **⬇ Download movie now** or **🌙 Download movie tonight · lower power cost**, then press **Play** and let the 10-second clip run to the end. **Back** cancels. Titles you already have sit at the end of a list and play normally.

## Samsung TV: install the app yourself
Use this when Jellyfin is **not in the Samsung app store** on your TV, or the store app says the **server version is not supported**. Tested on a 2021 Samsung TV (Tizen 6.0) with the app version 12.2. A reinstall takes about 15 minutes.

| | |
|---|---|
| You need | a laptop/PC on the **same home Wi-Fi** as the TV, only for installing and updating (not for watching) |
| Samsung account | not needed (only TVs from 2023 on need one) |
| App files | `.wgt`, not `.apk` (that is Android) |

### 1. Note two IP addresses
- **TV:** Settings → General → Network → Network Status → **IP Settings**.
- **Laptop:** Windows: open *Command Prompt*, type `ipconfig`, read the **IPv4 address**. Mac: System Settings → Network → Wi-Fi → Details.

Turn **off any VPN** on the laptop during the install.

### 2. Turn on Developer Mode on the TV
1. On the TV, open the **Apps** page.
2. Type **1 2 3 4 5**. The TV remote's on-screen number pad (123 button) often does **not** work. What works: the **SmartThings** app on your phone → your TV → Remote → **number keypad**, or a USB keyboard.
3. In the *Developer Mode* window switch it **On**, enter the **laptop's** IP as *Host PC IP*, press **OK**.
4. Restart the TV fully: **hold the power button about 3 seconds**.

The Apps page now says **Apps (DEVELOP MODE)**.

### 3. Install Jellyfin
=== "Windows: Apps2Samsung (easiest)"

    1. Open [github.com/Apps2Samsung/Apps2Samsung/releases/latest](https://github.com/Apps2Samsung/Apps2Samsung/releases/latest) (no GitHub account needed). Download only from there or [apps2samsung.com](https://apps2samsung.com), never from other sites.
    2. Under **Assets** download `Apps2Samsung-…-win-x64.msi`.
    3. Open it. At *Windows protected your PC* click **More info → Run anyway**, then **Yes**. It installs silently without a window; then start **Apps2Samsung** from the Start menu. (Doesn't appear? Use the `win-x64.zip`: *Extract All*, run the program in the folder.)
    4. In Apps2Samsung: **App:** `Jellyfin - <date>` (the standard build, see the table below) · **Version:** **12.2** (our server) · **Select TV:** pick it or type its IP.
    5. Click **Download and install** and wait 1–2 minutes.

=== "Mac / Linux: one command with Docker"

    With [Docker](https://docs.docker.com/get-started/get-docker/) installed, open a terminal and run, with **your TV's** IP:

    ```bash
    docker run --rm ghcr.io/georift/install-jellyfin-tizen 192.168.1.50
    ```

    If the TV asks to **allow the connection**, accept it. If the app later says the version doesn't match, install the build for our server explicitly:

    ```bash
    docker run --rm ghcr.io/georift/install-jellyfin-tizen 192.168.1.50 Jellyfin-12.z
    ```

### 4. First start
1. Find **Jellyfin** under Apps. To put it on the home row: highlight it, **hold Enter**, **Move**.
2. Server address: `https://jellyfin.holy-grail.ch` (the TV doesn't find it by itself).
3. Sign in with **Quick Connect** (steps above), then play a film to test.

### Which build to pick
Apps2Samsung lists several Jellyfin builds:

| Entry | What it is | Use it when |
|---|---|---|
| `Jellyfin - <date>` | standard app, newest build | **default**, matches our 12.x server |
| `Jellyfin - AVPlay` | uses Samsung's built-in video player | a film stutters, has no sound or won't start |
| `… 10.10z …`, `Legacy`, `+ Bonfire` | old servers / old TVs / modified build | not for us |

### Reinstall or update
Needed when a Samsung software update removed the app, or when our server moves to a new main version (announced here).

1. The Apps page still shows **Apps (DEVELOP MODE)**? If not, repeat step 2.
2. The laptop's IP still the same? If not, enter the new one in Developer Mode and restart the TV.
3. Laptop on home Wi-Fi, VPN off: install again (step 3), same build, version matching our server.

Your watch progress and favourites live on the server, so a reinstall loses nothing. Turning off automatic TV updates (Settings → Support → Software Update) lowers the chance that the app gets removed.

### Troubleshooting
| Problem | Fix |
|---|---|
| Typing 1 2 3 4 5 does nothing | SmartThings phone keypad or a USB keyboard, not the TV's on-screen pad |
| Installer can't find the TV | laptop IP in Developer Mode current? VPN off? same Wi-Fi? Restart the TV (hold power 3 s) |
| *Author certificate not match* | delete the old Jellyfin app on the TV (highlight, hold Enter, **Delete**), install again |
| App can't connect | address exactly `https://jellyfin.holy-grail.ch`, not the login page `sso.holy-grail.ch`; a sleeping server needs about a minute, try again |
| Film stutters or buffers | in the TV app: Settings → Playback → lower the **maximum streaming bitrate** (e.g. 20 Mbit/s) |
| No sound or film won't start | install the `Jellyfin - AVPlay` build over the standard one |

Tools: [Apps2Samsung](https://github.com/Apps2Samsung/Apps2Samsung) · [jellyfin-tizen-builds](https://github.com/jeppevinkel/jellyfin-tizen-builds) · [install-jellyfin-tizen](https://github.com/Georift/install-jellyfin-tizen). Community projects, not made by Samsung.

## Rating and tracking
- **Heart** = favourite, and you can mark things **played**. The TV and phone apps have no star ratings.
- In the browser, film and series pages have a **Rate in Tracker** link: see [Watch history](tracker.md).
