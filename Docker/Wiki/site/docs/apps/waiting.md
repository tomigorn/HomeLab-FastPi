# Why you sometimes wait

Our media server **sleeps when nobody uses it**. This saves electricity. When you open something, it wakes up.

| What | Sleeps? |
|---|---|
| Jellyfin (films, series) | yes |
| Requests (films, series) | yes |
| Tracker | yes |
| Audiobooks (Audiobookshelf), Request audiobooks | no, always ready |

## How long
| Step | Time |
|---|---|
| Waking up | about **1 minute** |
| Longer than 2 minutes | the page says **"Taking longer than it should"**. The server restarts by itself and tries once more |
| Still not working | the page says **"The server can't be started right now"**. The admin is told automatically |

## What you see
| Where | What you see | What to do |
|---|---|---|
| Browser, Jellyfin | page **"asleep, sign in to start"** | press the sign-in button, log in, then wait. A countdown runs. Jellyfin opens by itself |
| Browser, Requests | page **"Requests is starting"** | wait. Reload if nothing happens |
| TV or phone app | "can't connect", or an empty screen | wait 1 minute, open the app again |

## Baby steps: the browser
1. Open `https://jellyfin.holy-grail.ch`.
2. You see **"asleep, sign in to start"**.
3. Press the sign-in button.
4. Log in with Holy Grail.
5. Wait on the waiting page. Do not close it.
6. Jellyfin opens by itself after about a minute.

## Baby steps: the TV
1. Open the Moonfin app.
2. It may say it can't connect. Wait **1 minute**.
3. Close the app and open it again.
4. The home screen appears.

!!! note "Leaving the TV on the home screen"
    A TV that only refreshes its home screen in the background does **not** wake the server any more. Opening the app and pressing something does.

## Nothing happens after 2 minutes?
1. Reload the page (browser) or close and open the app (TV).
2. Wait 1 more minute.
3. Still nothing: ask the admin. Say the time and which device.
