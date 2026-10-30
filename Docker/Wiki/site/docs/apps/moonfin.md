# Moonfin apps

Moonfin is an app for our Jellyfin server. Same login as Jellyfin, plus requests inside the app.

## 1. Install

| Device | How |
|---|---|
| Apple TV, iPhone, iPad | App Store: https://apps.apple.com/app/moonfin/id6761283970 |
| Android TV / Google TV, Android phone | Google Play: https://play.google.com/store/apps/details?id=org.moonfin.androidtv |
| Samsung TV (2017 or newer) | Sideload, see below |

### Samsung TV (Tizen)
1. On the TV: **Apps** screen, press **1 2 3 4 5** on the remote.
2. Turn **Developer Mode** on, enter the IP of your PC.
3. Restart the TV fully (hold power until it turns off, or unplug briefly).
4. On the PC: download Apps2Samsung (https://github.com/Apps2Samsung/Apps2Samsung, Releases).
5. Download `Moonfin_Tizen_Regular_v*.wgt` from https://github.com/Moonfin-Client/Smart-TV/releases (square icon; use `Oblong` if your TV shows oblong icons, `Legacy` for 2016 TVs).
6. In Apps2Samsung: enter the TV IP (TV Settings > General > Network > Network Status), pick the `.wgt`, click **Install**.
7. Moonfin appears in the TV's Apps. PC and TV must be on the same network.

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
| Samsung TV | Download the newest `.wgt` and install it again with Apps2Samsung (steps above) |
