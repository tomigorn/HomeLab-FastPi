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
    Rare films can take longer to find. Check the status under **Requests**.

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

??? question "Something else"
    Ask the admin.
