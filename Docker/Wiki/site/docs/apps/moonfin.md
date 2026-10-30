# Moonfin apps

Moonfin is an app for our Jellyfin server. Same login as Jellyfin, plus requests inside the app.

## 1. Install

| Device | How |
|---|---|
| Apple TV, iPhone, iPad | App Store: https://apps.apple.com/app/moonfin/id6761283970 |
| Android TV / Google TV, Android phone | Google Play: https://play.google.com/store/apps/details?id=org.moonfin.androidtv |
| Samsung TV (2017 or newer) | Sideload, see below |

### Samsung TV (Tizen)
Baby steps below. The same Developer Mode and Apps2Samsung steps are in the Jellyfin guide with more detail and troubleshooting: [Samsung TV: install the app yourself](jellyfin.md#samsung-tv-install-the-app-yourself). It needs a Windows PC on the **same home network** as the TV, only for installing and updating.

**A. Note the two IP addresses**

| Device | Where |
|---|---|
| PC (Windows) | Start menu → type `cmd` → Enter → type `ipconfig` → Enter → read **IPv4 Address** (the adapter you use for Wi-Fi or cable, e.g. `192.168.1.50`) |
| TV | **Settings → General → Network → Network Status → IP Settings** (menu names differ by TV year, look under Network or Connection) |

Turn **off any VPN** on the PC during the install.

**B. Developer Mode on the TV**
1. On the TV open the **Apps** screen (home bar).
2. Type **1 2 3 4 5** with the number keys. The remote's on-screen keypad often does not work: use the **SmartThings** phone app (your TV → Remote → number keypad) or a USB keyboard.
3. In the *Developer Mode* window switch **Developer mode** to **On**.
4. Next to **Host PC IP** enter the **PC's** IP, press **OK**.
5. Restart the TV fully: hold the power button until it turns off and back on, or unplug it briefly. Developer Mode only works after that.
6. Check: the Apps screen now says **Apps (DEVELOP MODE)**.

Developer Mode has no timer on Samsung: once installed, Moonfin stays.

**C. Install with Apps2Samsung (Windows)**
1. Open https://github.com/Apps2Samsung/Apps2Samsung/releases/latest (no GitHub account needed). Only download from there or https://apps2samsung.com.
2. Under **Assets** download `Apps2Samsung-v<version>-win-x64.msi` (the `win-x64.zip` works too: *Extract All*, run the program inside).
3. Open it. If a blue box says **Windows protected your PC**: **More info → Run anyway**. Then start **Apps2Samsung** from the Start menu.
4. The app scans the network and lists your TV. Pick it, or type the TV IP by hand. If it says Developer Mode is off or the IP does not match, redo B.
5. Choose the app. Two ways:

| Way | How |
|---|---|
| Catalog (easiest) | Search **Moonfin**. The app downloads the newest release from the Moonfin GitHub itself. |
| Own file | Download the `.wgt` from https://github.com/Moonfin-Client/Smart-TV/releases/latest (**Assets**), then pick it in Apps2Samsung as a custom `.wgt`. |

| `.wgt` file | For |
|---|---|
| `Moonfin_Tizen_Regular_v<version>.wgt` | 2017 or newer, square icon. **Start here.** |
| `Moonfin_Tizen_Oblong_v<version>.wgt` | 2017 or newer, if the Regular icon looks stretched on the home bar |
| `Moonfin_Tizen_Legacy_v<version>.wgt` | 2016 TVs (Tizen 2.4) |

6. Click **Install** and wait 1-2 minutes. The TV may ask to allow the connection: accept.
7. On the TV: **Apps** → **Moonfin**. To put it on the home row: highlight it, hold **Enter**, **Move**.

**D. First start:** enter the server `https://jellyfin.holy-grail.ch`, then [sign in with Quick Connect](#2-sign-in-quick-connect-all-devices-incl-samsung) and, for requests, [Code for TV](#4-samsung-requests-sign-in-with-code-for-tv).

**Update later:** repeat C with the newest release (B only if the Apps screen no longer says DEVELOP MODE or the PC IP changed: enter the new IP in Developer Mode, restart the TV). Installing over the old app keeps the server and sign-in on the TV. If it fails with *Author certificate not match*, delete Moonfin on the TV (highlight, hold Enter, **Delete**) and install again; you sign in once more.

!!! note "Store versions can lag"
    The Apple TV and Google Play versions may be older than the newest GitHub release. Version **2.8** adds rank order in collections; if your store version is older, install the file from GitHub (Samsung below, Android further down).

## 2. Sign in (Quick Connect, all devices incl. Samsung)
1. Open Moonfin, enter the server URL: `https://jellyfin.holy-grail.ch`
2. Choose **Quick Connect**. A code is shown.
3. On a phone or PC: Jellyfin web > your **profile** > **Quick Connect** > enter the code > confirm.
4. The app signs in by itself.

## 3. Requests in Moonfin
1. Open a movie or show, press **Request**.
2. Open **Advanced** and pick when it should download:

| Pick | Meaning |
|---|---|
| 🌙 Tonight | Downloads at night, lower power cost. Default. |
| ⚡ Now | Downloads in the daytime, higher price. |

3. Submit.

Limit: **10 requests per person per 7 days**. At the limit you see **"Request limit reached"** and Submit is greyed out.

## 4. Samsung: requests sign-in with "Code for TV"
The Samsung app signs in to Jellyfin with Quick Connect like the others, but its **requests** sign-in needs a username and password. Use a one-time code instead of a password:
1. On a phone or PC: Jellyfin web → **Popular movies** or **Popular shows** → **Code for TV** (top right).
2. On the TV: Moonfin **Settings → Requests sign-in → Jellyfin account**.
3. Enter your Jellyfin **username**, and the **code** as the password (upper/lower case, spaces and dashes don't matter).
4. The code works once and expires after 10 minutes. Get a new one if it fails.

## 5. Update to version 2.8 or newer
From 2.8, collections show in rank order.

| Device | How |
|---|---|
| Apple TV / iPhone | App Store > Updates (or turn on automatic updates) |
| Android TV / phone | Google Play > Manage apps > Updates |
| Samsung TV | Install the newest release again with Apps2Samsung ([Samsung steps](#samsung-tv-tizen), part C) |
| Android TV / phone, newer than Play | [Install the APK from GitHub](#6-android-install-a-newer-version-from-github) |

## 6. Android: install a newer version from GitHub
Use this when Google Play still has an older version. Download page: https://github.com/Moonfin-Client/Moonfin-Core/releases/latest (**Assets**).

| Device | File |
|---|---|
| Android phone / tablet | `Moonfin_Android_v<version>.apk` |
| Android TV / Google TV | `Moonfin_AndroidTV_v<version>.apk` |

**Phone**
1. Open the releases page in the phone's browser, tap `Moonfin_Android_v<version>.apk`, confirm the download.
2. Open the finished download (notification or Files app).
3. Android asks to allow installs from this app (Chrome or Files): tap **Settings**, switch **Allow from this source** on, go back, tap **Install**.
4. Open Moonfin.

**Android TV / Google TV**
1. Install **Downloader** (by AFTVnews, orange icon) from the Play Store on the TV.
2. Open Downloader, type `github.com/Moonfin-Client/Moonfin-Core/releases/latest` in the address box, scroll to **Assets**, select `Moonfin_AndroidTV_v<version>.apk`.
3. When the download ends, choose **Install**. If the TV blocks it, it opens the settings page: turn on **Install unknown apps** (or *Unknown sources*) for **Downloader**, go back, install again.
4. Moonfin is in the apps row, or under Settings → Apps → See all apps.

| Caveat | |
|---|---|
| No auto-update | A file install is not updated by Google Play. The app tells you when a new version is out: download the new APK and install it the same way (servers and sign-in are kept). |
| *App not installed* | The Play version and the GitHub file are signed with different keys. **Uninstall the Play version first**; you sign in again afterwards (Quick Connect). |
| Switch back | To return to Play updates, uninstall the file version and install from Play. |

## 7. Playback problems on Apple TV
| Problem | Try this |
|---|---|
| Subtitles flicker (appear and disappear) | Switch the subtitle track off and on again, or pick another track (tracks built into the film are steadier than separate subtitle files). From Moonfin 2.8: **Settings → Playback → Player → Video player → Standard**. Known Moonfin issue on Apple TV with separate SRT files |
| Picture sluggish or judders | Apple TV **Settings → Video and Audio → Match Content → Match Frame Rate: On**. Apple TV cannot pass DTS through; it decodes it itself, which is fine in most films |
| No sound for the first seconds | Normal: the TV and soundbar switch to the film's picture and sound format. Jump back 10 seconds if needed |
