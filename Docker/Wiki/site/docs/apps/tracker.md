# Watch history (Tracker)

**Address:** `https://tracker.holy-grail.ch`

The Tracker (Ryot) keeps your history, ratings and lists of films and series.

1. Open the address and press **Sign in with Holy Grail**. Your account is created on the first login.
2. Search for a title to rate it or add it to a list.

!!! info "The media server sleeps"
    The Tracker runs on the media server. If it is asleep, log in and wait about a minute on the waiting page.

## Rate from Jellyfin
In the Jellyfin browser, film and series pages have a **Rate in Tracker** link next to the IMDb/TMDB links. It opens the title in the Tracker. The TV and phone apps don't have the link.

## Track what you watch automatically
Sign in to Jellyfin and to the Tracker once each, then:

1. Tracker → **Settings** → **Integrations** → **Add** → **Jellyfin Sink**.
2. Provider **TMDB**, leave the username filter empty, switch **auto-pause on errors** off.
3. Copy the URL and send it to the admin **privately**: it is a secret.
4. The admin switches it on. After about 3 minutes of watching, the title shows up in your history.

## On your phone
Open the address in your phone's browser → menu → **Install app** / **Add to Home screen**.
