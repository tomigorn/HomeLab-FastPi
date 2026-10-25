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

## Samsung TV: install the app yourself
Use this when Jellyfin is **not in the Samsung app store** on your TV, or the store app says the **server version is not supported**. Samsung TVs from 2017 on (Tizen 3 or newer) work.

You need a computer (Windows, Mac or Linux) with **[Docker](https://docs.docker.com/get-started/get-docker/)** installed, on the **same Wi-Fi/network** as the TV. Samsung apps are `.wgt` files, not `.apk` (that is Android).

### 1. Find the TV's IP address
TV: **Settings → General → Network → Network Status → IP Settings**. Write down the **IP address**, e.g. `192.168.1.50`.

### 2. Turn on Developer Mode on the TV
1. Open **Apps** on the TV.
2. Press **1 2 3 4 5** on the remote, one after the other. A *Developer Mode* window opens.
3. Switch **Developer mode** to **On**.
4. Enter your **computer's** IP address (not the TV's) and press **OK**.
5. Restart the TV: hold the **power** button until it switches off and on again.

!!! tip "No window after 1 2 3 4 5?"
    Some remotes have no number keys: use the on-screen number pad (**123** button). On newer TVs, look under **Settings → General → System Manager**.

### 3. Install Jellyfin from the computer
Open a terminal (Windows: *PowerShell*) and run, with **your TV's** IP:

```bash
docker run --rm ghcr.io/georift/install-jellyfin-tizen 192.168.1.50
```

If the TV asks to **allow the connection**, accept it. When the command ends with *Installed*, Jellyfin is in the TV's app list.

!!! warning "App says the version doesn't match?"
    Install the build made for our server version explicitly:
    ```bash
    docker run --rm ghcr.io/georift/install-jellyfin-tizen 192.168.1.50 Jellyfin-12.z
    ```

### 4. Sign in
Open Jellyfin on the TV, enter `https://jellyfin.holy-grail.ch` and sign in with **Quick Connect** (steps above).

!!! info "No automatic updates"
    An app installed this way never updates itself. When the server moves to a new main version we announce it here; then repeat step 3.

Builds: [jellyfin-tizen-builds](https://github.com/jeppevinkel/jellyfin-tizen-builds) · installer: [install-jellyfin-tizen](https://github.com/Georift/install-jellyfin-tizen). Both are community projects, not made by Samsung.

## Rating and tracking
- **Heart** = favourite, and you can mark things **played**. The TV and phone apps have no star ratings.
- In the browser, film and series pages have a **Rate in Tracker** link: see [Watch history](tracker.md).
