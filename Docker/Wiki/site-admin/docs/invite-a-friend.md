# Invite a friend

New accounts are only possible with an invite link. The link works **one time**.

## Create the link

1. Open `https://sso.holy-grail.ch` and click **Admin interface**.
2. Go to **Directory** → **Invitations**.
3. Click **Create**.
4. Fill in the form:

    | Field | What to enter |
    |---|---|
    | Name | A short label, for example `anna` |
    | Flow | `enrollment (Enrollment Holy Grail)` |
    | Expires | A date a few days away |
    | Single use | On |

!!! warning "Pick the right flow"
    Choose exactly `enrollment (Enrollment Holy Grail)`. Do **not** pick `default-source-enrollment`: that one is for logins from outside sources.

5. Click **Create**.
6. Click the new invitation and copy its link. It looks like `https://sso.holy-grail.ch/if/flow/enrollment/?itoken=...`

## Send it

Send your friend two things:

1. The invite link.
2. The link to the guide: `https://wiki.holy-grail.ch/getting-started/`. It explains every step they will do.

!!! warning "The link works one time"
    If your friend opened it and got stuck, make a new invitation. The old one is used up.

## What your friend gets automatically

| What | Detail |
|---|---|
| Group `streaming-users` | Jellyfin and the watch history (Tracker) |
| Login | Password (15+ characters with upper, lower, digit and symbol) and an authenticator app |

Requests are **not** automatic. See [Give or remove access](access.md).

## Check it worked

1. Go to **Directory** → **Users**.
2. Your friend appears in the list after they finish the form.
3. If the invitation is still listed under **Invitations**, it was not used yet.
