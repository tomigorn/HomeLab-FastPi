# Disable or remove a person

| Action | What happens | Can you undo it? |
|---|---|---|
| **Disable** (set inactive) | The person cannot log in any more. Their account and groups stay. | Yes: set it active again |
| **Delete** | The account is gone. | No |

Disable first. Delete only when you are sure.

## Disable a person

1. Open `https://sso.holy-grail.ch` and click **Admin interface**.
2. Go to **Directory** → **Users**.
3. Click the person.
4. Click **Edit**, switch **Is active** off and click **Update**.

To let them back in, switch **Is active** on again.

## Delete a person

1. Go to **Directory** → **Users**.
2. Tick the person and click **Delete**.
3. Confirm.

!!! warning "Apps keep their own data"
    Some apps (for example Jellyfin) keep their own user list. Deleting the login does not remove the person there.
