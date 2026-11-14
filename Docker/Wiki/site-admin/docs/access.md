# Give or remove access

Access to apps comes from **groups**. A group does not include another group: someone who should watch **and** request needs both.

## The groups

| Group | What it unlocks | How someone gets it |
|---|---|---|
| `streaming-users` | Jellyfin, watch history (Tracker) | Automatic for every invited friend |
| `streaming-requesters` | Requests for films and series, audiobook requests | By hand |
| `streaming-admins` | Download tools (Radarr, Sonarr, Prowlarr, Bazarr, SABnzbd, qBittorrent) and admin rights in Jellyfin | By hand |
| `homelab-users` | Home Assistant, Grafana, UI mockups, activity | By hand |
| `homelab-admins` | All admin tools and this admin guide | By hand |

## Add a person to a group

1. Open `https://sso.holy-grail.ch` and click **Admin interface**.
2. Go to **Directory** → **Groups**.
3. Click the group name.
4. Open the **Users** tab and click **Add existing user**.
5. Pick the person and click **Add**.

## Remove a person from a group

1. Go to **Directory** → **Groups** and click the group name.
2. Open the **Users** tab.
3. Tick the person and click **Remove**.

!!! note "A tile is missing or still there?"
    The person logs out and in again. Then the dashboard shows the new tiles.

!!! warning "Be careful with the admin groups"
    `streaming-admins` and `homelab-admins` give a lot of power. Only add people you fully trust.
