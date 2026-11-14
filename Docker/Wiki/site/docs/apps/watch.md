# How to watch

Pick your device. Every way uses your Holy Grail login and needs no password in Jellyfin.

| Device | Use | First login |
|---|---|---|
| Laptop / PC | browser, `jellyfin.holy-grail.ch` | [Browser](#in-the-browser) |
| Phone / tablet | **Moonfin** app | [Quick Connect](#on-a-tv-or-phone-first-login-with-quick-connect) |
| Apple TV, Android TV, Google TV | **Moonfin** app | [Quick Connect](#on-a-tv-or-phone-first-login-with-quick-connect) |
| Samsung TV | **Moonfin**, installed by hand | [Samsung guide](moonfin.md#samsung-tv-tizen) |
| LG TV, Roku | official **Jellyfin** app | [Jellyfin apps](jellyfin.md#on-your-tv-or-phone-apps) |

!!! info "First start can take a minute"
    The media server sleeps to save power. Waiting is normal: [Why you sometimes wait](waiting.md).

## In the browser
1. Open `https://jellyfin.holy-grail.ch`.
2. Press **Sign In with Holy Grail**.
3. Log in with your username, password and authenticator code.
4. You see the home screen. Press a film or series.
5. Press **Play**.

Asleep page instead? See [Why you sometimes wait](waiting.md).

## On a TV or phone: first login with Quick Connect
You need the **TV (or phone)** and a **laptop or phone that is already signed in** to Jellyfin in the browser.

1. Install **Moonfin** from the app store of your device ([install list](moonfin.md#1-install)).
2. Open Moonfin.
3. When it asks for the server, type `https://jellyfin.holy-grail.ch`.
4. Choose **Quick Connect**. A code appears on the TV. Leave it open.
5. On the laptop, open `https://jellyfin.holy-grail.ch` (signed in).
6. Press your **profile picture** (top right), then **Quick Connect**.
7. Type the code from the TV, press **Authorize**.
8. The TV signs in by itself. You see the home screen.
9. Choose a film, press **Play**.

| Problem | Fix |
|---|---|
| The TV asks for a password | there is none: choose **Quick Connect** |
| "Can't connect" | the address must be `https://jellyfin.holy-grail.ch`, not `sso.holy-grail.ch`. Wait one minute, try again |
| The code does not work | the code runs out after a few minutes: choose **Quick Connect** again for a new one |

You only do this **once** per device. Next time the app opens straight away.

## Playing
| I want to | Do this |
|---|---|
| carry on | **Continue Watching** row |
| change audio or subtitles | [Audio & subtitles](../audio-subtitles.md) |
| skip an intro | [Skip buttons](skip-buttons.md) |
| find something new | [Home screen](jellyfin-home.md) |
| the film is not there | [Request it](requests.md) |
