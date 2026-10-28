# Help & FAQ

??? question "Jellyfin, Requests or the Tracker is slow to open"
    The media server sleeps when nobody uses it and takes about a minute to wake. Wait on the waiting page ("asleep, sign in to start" or "Requests is starting") and reload if it doesn't open by itself.

??? question "I lost my authenticator / phone"
    Ask the admin to reset your second factor. You'll set it up again at your next login.

??? question "I forgot my password"
    On the login page press **Forgot password?**. You need access to your email and your authenticator.

??? question "A tile is missing on my dashboard"
    Jellyfin and the Tracker come with your invite. Requests are switched on by the admin: ask.

??? question "A film I requested isn't there yet"
    Rare films can take longer to find. Check the status under **Requests**. If **Can wait** was ticked in the request, the download starts at night. Need it sooner? Ask the admin, or untick the box next time. See [Requesting](apps/requests.md#can-wait-download-tonight).

??? question "Audiobook request: limit reached"
    You can request 5 audiobooks per 7 days. Try again when an earlier request is a week old. See [Requesting audiobooks](apps/audiobook-requests.md).

??? question "My audiobook isn't in Audiobookshelf yet"
    It appears after download and import, normally within minutes to hours, in the library of its language. If no release exists in that language, the request stays open. Check **All requests** at `books.holy-grail.ch`.

??? question "How do I log in to the Tracker?"
    Press the **Holy Grail** button on its login page. See [Tracker](apps/tracker.md).

??? question "Why did a series arrive as one big download?"
    Complete season packs are preferred over single episodes: fewer, faster downloads. See [Requesting](apps/requests.md#which-version-gets-downloaded).

??? question "A download failed"
    Nothing to do. A failed download is noticed within seconds and another release is searched automatically. Downloaded files are virus-scanned: executables and archives are blocked at once, video files are scanned in the background.

??? question "The TV app asks for a password"
    There are no passwords in Jellyfin. Use **Quick Connect**, see [Watching](apps/jellyfin.md).

??? question "The Jellyfin app can't connect"
    Use the address `https://jellyfin.holy-grail.ch` (not `sso.holy-grail.ch`), sign in with **Quick Connect**, and give a sleeping server a minute. See [Watching](apps/jellyfin.md).

??? question "The film plays in the wrong language"
    Switch the audio track while playing, see [Audio & subtitles](audio-subtitles.md).

??? question "A row on the Jellyfin home screen looks old"
    Reload with Ctrl+Shift+R, or close and reopen the TV app. See [Home screen](apps/jellyfin-home.md).

??? question "There is no Skip intro button"
    New episodes get their buttons the next day. For recaps and previews, turn on **Ask to skip** in Settings → Playback → Advanced. See [Skip buttons](apps/skip-buttons.md).

??? question "Requests says 'Waiting for the night'"
    The download starts at night when power is cheaper. See [Requesting](apps/requests.md#can-wait-download-tonight).

??? question "Something else"
    Ask the admin.
