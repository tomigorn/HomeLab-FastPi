# Getting started

## 1. Accept your invite
You get a link like `https://sso.holy-grail.ch/if/flow/enrollment/?itoken=…`. Account creation is by invite only.

1. Open the link on the device you're setting up on. A short notice page appears first: read it and press **Continue**.
2. Choose a **username** and enter your **name**, **email** and a **password** (twice).
3. Check your email and click the confirmation link.
4. Set up your authenticator app (next step).

!!! info "Password rules"
    At least **15 characters**, not found in known data breaches, and not trivially guessable. A passphrase of several random words works well.

!!! warning "Open the invite link once"
    The invite works one time. If the page shows an error after you already got in once, ask the admin for a new one.

## 2. Set up your authenticator app
Holy Grail asks for a 6-digit code when you log in. You can't skip this step.

=== "Phone with an authenticator app"
    1. Install an authenticator app (for example Aegis, 2FAS, Google Authenticator or Microsoft Authenticator).
    2. Scan the QR code shown on screen.
    3. Type the 6-digit code from the app.

=== "Password manager"
    Most password managers (Bitwarden, 1Password, Proton Pass) can store the code too: scan the QR code with them.

!!! warning "Keep your authenticator safe"
    Without it you can't log in. If you lose your phone, ask the admin to reset it; you'll set up a new one at your next login.

## 3. Log in
Open any app. If you're not logged in you land on the Holy Grail login page: enter your username, your password, then the 6-digit code. Tick **stay signed in** to be asked less often.

Forgot your password? Use **Forgot password?** on the login page. You get an email link and must also enter a code from your authenticator.

## 4. Your dashboard
Open `https://sso.holy-grail.ch` and go to your **Application Dashboard**: every app you may use has a tile. Click a tile to open it.

| Group | What's there |
|---|---|
| Media | Films & series, requests, watch history, audiobooks |
| Account | Your profile picture, this guide |
| Homelab | Machines |

!!! note "A tile is missing?"
    New accounts get Jellyfin and the Tracker automatically. Requests are switched on by the admin: just ask.
