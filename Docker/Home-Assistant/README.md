# Home Assistant

[Home Assistant](https://www.home-assistant.io/) home-automation platform, run
on **fastpi** (`192.168.1.2`) as a single Docker Compose service. Current use
case: **electricity monitoring + on/off control** of smart plugs (the
"Grafana/Prometheus, but interactive" goal).

Runs the official **`ghcr.io/home-assistant/home-assistant:stable`** image
(Container install — no Supervisor / no add-ons; anything that would be an
"add-on" becomes its own container here, e.g. a future Zigbee2MQTT + Mosquitto).

## Deployment

```bash
cd /home/pi/Projects/Docker/Home-Assistant
docker compose up -d
docker compose logs -f          # watch boot; Ctrl+C stops the view, not HA
```

- **`network_mode: host`** — HA needs the host network for LAN device discovery
  (mDNS/SSDP) and to reach smart plugs directly. With host mode HA serves on the
  host at **`http://192.168.1.2:8123`** (the `ports:` key is ignored).
- Config is a **bind mount** (`./config`) so it is easy to inspect/back up/commit.
- `mem_limit: 1g`, `TZ` from `.env` (Europe/Zurich).

### Accessing the UI

| URL | Works? | Notes |
|---|---|---|
| `http://192.168.1.2:8123` | ✅ always | Plain HTTP on the IP — the reliable address. |
| `http://fastpi.homelab:8123` | ✅ on LAN | Resolves via AdGuard. May need an explicit `http://`. |
| `https://…:8123` | ❌ | HA serves **plain HTTP** here, no TLS. Don't use `https`. |

> **Browser gotcha:** modern browsers auto-upgrade typed hostnames to `https://`
> ("Always use secure connections" / HSTS from other `*.holy-grail.ch` sites).
> Since HA has no TLS on `:8123`, the upgraded request fails. Use the **IP**, an
> **incognito** window, or disable the browser's HTTPS-upgrade for the hostname.
> A proper `https://` name would require fronting HA with Traefik (see TODO).

### Onboarding (one-time, manual — NOT in git)

There is no YAML for "create my login". On first run, open the UI and:

1. Create the **admin account** (username + strong password).
2. Set location / **Metric** units / currency **CHF** (CHF matters for Energy
   dashboard cost calc).
3. Enable **2FA**: *username (bottom-left) → Multi-factor Authentication → TOTP*.

Credentials live in `config/.storage/auth` (password hashes + tokens) — this is
**gitignored** and must never be committed.

## Config-as-code

HA is a **hybrid**: human-authored YAML is committed; the machine-managed
runtime store (`.storage/`), the database, logs, and secrets are not.

**Committed** (`config/`):
- `configuration.yaml` — loads `default_config`, enables `packages/`, themes,
  the `automations`/`scripts`/`scenes` includes, and the dashboard registration
  (see [Dashboards](#dashboards)).
- `ui-lovelace.yaml` — the default **Overview** dashboard, config-as-code
  (see [Dashboards](#dashboards)).
- `packages/*.yaml` — one file per feature (see [Smart plugs](#smart-plugs-mystrom)).
- `automations.yaml`, `scripts.yaml`, `scenes.yaml` — the UI editors write here.
- `secrets.yaml.example` — template; copy to `secrets.yaml` and fill real values.

**Ignored** (see `.gitignore`): `secrets.yaml`, `*.db*`, `*.log*`, `.storage/`
(auth tokens, device/entity registries, **integration config entries**),
`.cloud/`, `tts/`, `deps/`, `backups/`.

> Integrations/devices added via the **UI** (config flow) land in `.storage` and
> are **not** committable. To keep a device in git, define it in YAML instead
> (the myStrom plug below does exactly this).

### Editing workflow

HA runs as **root**, so `config/*` files are root-owned — edit with `sudo`.

```bash
sudo nano config/packages/plug_fastpi.yaml
# validate before applying:
docker exec homeassistant python -m homeassistant --script check_config -c /config
# apply: reload the domain in Developer Tools → YAML (REST/Template/Automations),
# or restart for core/package changes:
docker compose restart
```

## Dashboards

Our config-as-code dashboard is `config/ui-lovelace.yaml`, registered in
`configuration.yaml` under `lovelace.dashboards`:

```yaml
lovelace:
  dashboards:
    lovelace:
      mode: yaml
      filename: ui-lovelace.yaml
      title: Electricity
      icon: mdi:power-plug
      show_in_sidebar: true
```

In the sidebar it shows as **Electricity** 🔌, with two views:
- **Overview** 🔌 — a `panel`-mode two-row grid (`vertical-stack` of
  `horizontal-stack`s, so each row spans full width instead of being scattered
  by masonry): **row 1** = total-power gauge · *Total — measured* (both plugs) ·
  *Total — incl. vampire*; **row 2** = FastPi · Beefy · **Vampire draw** cards;
  then the 24 h power history (per plug + total). See
  [Vampire draw](#vampire-draw-standby--parasitic-loads).
- **Measured** 📟 (`mdi:gauge`, path `/measured`) — live snapshot, tariff &
  price, projected yearly cost, per-period kWh + cost tables, and long-term
  day/month/power graphs. (Renamed from "Energy" to avoid clashing with HA's
  native Energy dashboard.) Two controls sit directly under **Live**:
  - a **timeframe dropdown** (`input_select.measured_timeframe`: Today / This
    week / This month / This year / Lifetime) — the kWh + CHF tables show **only
    the selected period** (via one `conditional` card per timeframe), instead of
    one giant always-on table of every period.
  - a **Show-vampire toggle** (`input_boolean.measured_show_vampire`) — adds a
    **Vampire** row and a **Total incl. vampire** row to those tables and to the
    projected-yearly-cost card (via `conditional` entity rows). Off by default;
    the graphs stay plugs-only.

    Both helpers live in `config/packages/measured_controls.yaml`. Lifetime shows
    energy only (no reset-period lifetime cost — see below).

Editing the YAML content only needs a **browser refresh**; changing the
registration (title/icon/mode) needs `docker compose restart`.

### The default "Overview" is HA's own auto dashboard (not ours)

In HA **2026** the default landing page — the top **Overview** in the sidebar —
is HA's **auto-generated "home" dashboard** (Welcome / Areas / Summaries, plus a
**Favorites** row that auto-picks your ~8 most-used devices). It is *generated*,
not config-as-code, and **registering `dashboards.lovelace` did not replace it** —
in this HA version our dashboard simply shows up as a **second** sidebar entry
(Electricity). Nothing for it lives in `.storage`; the Favorites are automatic.

To **land on the Electricity dashboard** instead of the auto Overview, set it as
your default: avatar (bottom-left) → **Dashboard** → *Electricity* (per-user,
stored in your profile — not config-as-code).

> **Pitfall:** the old top-level `lovelace: mode: yaml` is **deprecated** (removed
> in HA 2026.8) and in current HA no longer claims the Overview slot — it leaves
> the auto "home" dashboard in place and shows your YAML as a *duplicate* Overview.
> Use the `dashboards.lovelace` form above.

Other dashboards (e.g. **Map**) stay storage-mode (UI-managed, in `.storage`).

## Smart plugs (myStrom)

Two **myStrom WiFi Switches**, each defined **entirely in YAML** via its **local
HTTP API** — no cloud, no myStrom account, **no subscription** (HA talks to the
device directly on the LAN):

| Plug | Powers | File | IP | MAC |
|---|---|---|---|---|
| **FastPi** | the FastPi server | `config/packages/plug_fastpi.yaml` | `192.168.1.151` | `3c:e9:0e:7d:85:8c` |
| **Beefy**  | the Beefy server  | `config/packages/plug_beefy.yaml`  | `192.168.1.152` | `3c:e9:0e:7c:7e:80` |

Local API used (both plugs — same model):

| Endpoint | Purpose |
|---|---|
| `GET /report` | `{"power":W, "Ws":.., "relay":bool, "temperature":C}` |
| `GET /relay?state=1` / `?state=0` | switch the relay on / off |

Per-plug entities (all config-as-code; `<p>` = `fastpi` or `beefy`):

| Entity | Purpose |
|---|---|
| `switch.<p>_plug` | on/off button (template switch → `rest_command`) |
| `sensor.<p>_plug_power` | live power (W) |
| `sensor.<p>_plug_energy` | derived kWh (Riemann `integration`) |
| `sensor.<p>_plug_temperature` | plug temperature (°C) |
| `binary_sensor.<p>_plug_relay` | relay state feedback |

> **⚠️ Foot-gun:** `switch.fastpi_plug` cuts power to the very host HA runs on —
> toggling it off **hard-kills Home Assistant** (and FastPi). `switch.beefy_plug`
> is a hard power switch for Beefy (pairs with its WOL / S5-poweroff automation).

### ⚠️ IP addresses — static DHCP reservations REQUIRED

Each plug's YAML **hardcodes its IP**, so the addresses must never change. HA
talks to devices over **IP** (a MAC is layer-2, not routable — you can't HTTP to
a MAC), and the plain `rest:` integration has no discovery, so it cannot re-find
a device whose IP moved. The fix is a **static DHCP reservation** per plug.

Router: **AX7501-B1 → Home Networking → Static DHCP**

| Plug | MAC | Reserved IP | Band |
|---|---|---|---|
| FastPi | `3c:e9:0e:7d:85:8c` | `192.168.1.151` | WiFi 2.4 GHz |
| Beefy  | `3c:e9:0e:7c:7e:80` | `192.168.1.152` | WiFi 2.4 GHz |

If a plug ever gets a new IP, update **both** the reservation **and** the IP in
its `config/packages/plug_<p>.yaml` (3 references), then `docker compose restart`.

> **Alternative if you dislike hardcoding:** the native myStrom integration (UI)
> uses mDNS discovery and tracks the device by its MAC-derived unique ID, so it
> auto-updates on IP change — but the device entry then lives in `.storage`
> (not committed). We chose YAML + static lease to keep everything in git.

## Electricity metering, tariffs & cost

`config/packages/electricity.yaml` holds the **shared tariff/price** and the
**combined "both plugs" totals**; each plug's own meters live in its
`plug_<p>.yaml` (built on `sensor.<p>_plug_energy` / `_power`).

- **Forever history** — any sensor with a `state_class` keeps **long-term
  statistics** (hourly aggregates) **forever**; only the every-5s detail is purged
  (recorder default 10 days). The dashboard's `statistics-graph` cards read these.
- **Per-plug per-period kWh** — `utility_meter` cycles per plug:
  `sensor.<p>_plug_hourly`, `…_weekly`, and tariff-split
  `<p>_plug_daily/monthly/yearly/total` → `sensor.<p>_plug_<cycle>_high` / `_low`
  (+ a `select.<p>_plug_<cycle>`).
- **Tariff (City of Zürich / EWZ)** — **HIGH** = Mon–Sat 06:00–22:00; **LOW** =
  nights 22:00–06:00 **and all day Sunday**. One automation applies the correct
  tariff to **both plugs'** `select`s at 06:00 / 22:00 / on start
  (`now().weekday() != 6 and 6 <= hour < 22` → high).
  `sensor.electricity_current_tariff` shows the active one.
- **Prices — per-year table in git** — prices come from a single source of truth,
  the `sensor.electricity_tariff_now` template in `electricity.yaml`: a
  `{ year: {high, low} }` map (CHF/kWh) keyed by the current year, exposed as
  `sensor.electricity_price_high` / `_low`. Add next year's prices when EWZ
  publishes them. Because EWZ changes prices on **Jan 1** — the same instant the
  yearly and monthly meters reset — per-year and per-month costs are **exact**.
  Seeded with the **real EWZ 2026 tariffs**: high **0.2988**, low **0.1870** CHF/kWh.
- **No silent wrong numbers** — if the current year is **not** in the table, the
  price sensors go **unavailable** (they never guess with last year's price), and
  every cost sensor carries an `availability:` guard so it follows suit — you get
  a visible blank, never a plausible-looking wrong figure.
  `sensor.electricity_tariff_coverage` shows `OK` / `MISSING — add <year>` and is
  on the dashboard's *Tariff & price* card.
- **Per-plug cost (per period, resets)** —
  `sensor.<p>_plug_cost_today/this_week/this_month/this_year` =
  `high_kWh × price_high + low_kWh × price_low`. Each is tied to a meter that
  **resets at the start of its period** (so "this week" starts at 0 every Monday
  — it is *not* a running total). There is deliberately **no lifetime cost sum**.
  (Caveat: the single week that spans New Year prices its December kWh at the new
  year's price — a tiny, once-a-year approximation; year and month stay exact.)
- **Per-plug cost odometer** — `sensor.<p>_plug_cost_accumulated` integrates the
  live CHF/h rate (Riemann, `max_sub_interval` so it accrues even at constant
  standby power). Never shown directly; its per-day / per-month *change* drives
  the historical **Cost per day / month** graphs, and it is correct across price
  changes because the rate already uses the current period's price.
- **Combined totals** — `sensor.plugs_total_power`, `…_energy` (lifetime kWh;
  feeds the Energy dashboard), `…_energy_today/this_week/this_month/this_year`,
  `…_cost_today/this_week/this_month/this_year`, and `…_current_cost_rate` — each
  the sum of both plugs. (No combined lifetime cost, by design.)
- **Grand totals incl. vampire** — add the standby draw (below) on top of the two
  metered plugs: `sensor.total_incl_vampire_power` /
  `…_current_cost_rate` (live, shown as the *Total — incl. vampire* glance on
  Overview), plus per-period `sensor.total_incl_vampire_energy` (lifetime) /
  `…_energy_today/this_week/this_month/this_year` and
  `…_cost_today/this_week/this_month/this_year`. These feed the *Total incl.
  vampire* rows the Measured view shows when the vampire toggle is on.

Shown on the dashboard's **Measured** view (live, per-period kWh + cost by tariff,
projected-year estimate, and forever day/month/power/cost graphs).

### Vampire draw (standby / parasitic loads)

`config/packages/plug_vampire.yaml` is a **virtual "plug"** (no hardware) that
sums the small always-on / off-state loads the two real myStrom plugs do **not**
meter — a myStrom plug measures only the load *behind* it, so its own electronics
draw is invisible to it and is counted here instead.

`sensor.vampire_plug_power` (W) = sum of, with a per-component attribute breakdown:

| Component | Draw |
| --- | --- |
| myStrom plug self-draw (each, ×2) | **1.4 W on / 0.9 W off** — dynamic, follows `binary_sensor.<p>_plug_relay` |
| Noctua fan + AC→DC header | 0.4 W |
| Tuya legacy plug (spare / future NAS) | 1.2 W |
| Netgear 1 GbE switch | 2.0 W |
| Power strip | 0.4 W |

Fixed part = 4.0 W; the two plugs add 1.8 W (both off) … 2.8 W (both on) → total
**≈ 5.8–6.8 W**. `sensor.vampire_plug_current_cost_rate` prices it at the live
tariff. These are **measured** values, roughly static except the two plugs which
track their relay state. Shown as the **Vampire draw** card on Overview; a
self-draw remark also sits on each plug card. The plugs' own metered
`sensor.<p>_plug_power` values are untouched.

**Per-period energy & cost (odometer method).** So the *Show-vampire* toggle can
populate the Measured view's timeframe tables, vampire has its own history:
`sensor.vampire_plug_energy` (Riemann integration of the power) and
`sensor.vampire_plug_cost_accumulated` (integration of the price-aware cost
rate), each fed into plain day/week/month/year `utility_meter`s
(`sensor.vampire_energy_<cycle>` / `sensor.vampire_cost_<cycle>`). Because the
cost rate already carries the current tariff price, the accumulated cost — and
every per-period cost meter — is **correct across price changes without any
tariff-split meters**, so (unlike the plugs) vampire needs **no entry in the
tariff-switching automation**. The values are estimates-derived, so they stay out
of the native Energy dashboard and the bar graphs (plugs-only).

> **Seeding caveat — no backfill.** Like any HA integration, these meters only
> accrue *while the sensor exists*; HA cannot reconstruct draw from before they
> were created. So the first partial period reads low — "today" counts only from
> creation, and this-week/month/year are mid-period seeds — until each cycle rolls
> over fresh (next Mon / 1st / Jan 1), after which they are exact. Projected-yearly
> is correspondingly noisy at first. This is the same warm-up the plugs had when
> first added; it self-corrects and cannot be backfilled.

### Changing the tariff prices (add a year)

Edit the year map in `sensor.electricity_tariff_now` (in
`config/packages/electricity.yaml`) — add a `YYYY: {high, low}` row — and restart.
Enter next year's prices before Jan 1 so cost accrues at the right price from the
new year's first day. Because HA banks cost at time-of-use, editing a price only
affects consumption **from then on** — it never rewrites already-recorded cost,
and past years stay correct at their old prices.

### Native Energy dashboard (configured — UI-only)

HA's built-in **Energy** dashboard is set up (Settings → Dashboards → Energy).
It is **UI-configured and lives in `.storage/energy`** — there is no YAML for it.

- **Grid consumption** = `sensor.plugs_total_energy` (combined both plugs). (Only
  grid sources get cost tracking; an *Individual device* would be energy-only.)
- **Cost** = *"Use an entity with current price"* → `sensor.electricity_current_price`
  (tariff-aware). HA auto-creates `sensor.plugs_total_energy_cost`.
- The Energy panel's **date-range picker** then shows kWh **and** CHF for any
  period (hourly/daily resolution — long-term stats are hourly). Cost accrues
  **from setup onward**; historical kWh is present but past cost is not
  back-calculated.

## Areas & device location

HA **areas** (rooms) are UI/registry data in `.storage` (not YAML). The home's
rooms are:

> WC · Dusche · Eingang · Schlafzimmer Tomas · Schlafzimmer Rafi · Küche ·
> Esszimmer · Reduit · Wohnzimmer · Balkon

Both plugs live in **Wohnzimmer**. Because they're defined in YAML (no
auto-created *device*), the room is assigned at the **entity** level (in the UI:
Settings → Entities → pick entity → area). Each plug's physical entities carry
`area_id: wohnzimmer` — `switch.<p>_plug`, `binary_sensor.<p>_plug_relay`, and
`sensor.<p>_plug_power` / `_temperature` / `_energy` (10 entities total). The
derived tariff/price/cost sensors are left unassigned (calculations, not
physically located). Area assignments live in `.storage` (not git).

## Notes

- **Bluetooth disabled.** The Pi's onboard adapter (`hci0`) is auto-detected and
  spams the log (no D-Bus in the container). It is not needed (we use WiFi +
  future Zigbee USB), so the **Bluetooth integration is deleted in the UI**
  (*Settings → Devices & Services → Bluetooth → Delete*).
- **Animated rain-forecast map — shelved.** Evaluated Windy, meteoblue, RainViewer
  and the `weather-radar-card`. MeteoSwiss's own radar/nowcast **can't be embedded**
  in HA (its integration provides forecast *numbers* only), and the alternatives
  didn't fit cleanly. Dropped for now.

## TODO / future

- **Zigbee** via the SONOFF **ZBDongle-P** (CC2652P) — USB passthrough
  (`/dev/serial/by-id/...`), ZHA built-in (simplest) or Zigbee2MQTT + Mosquitto
  (extra containers). Use the USB extension cable (2.4 GHz interference).
- **Traefik route + HTTPS** — `homeassistant.holy-grail.ch` (file provider,
  service `http://192.168.1.2:8123` since HA is host-networked). Needs HA's
  reverse-proxy trust block (`http: use_x_forwarded_for + trusted_proxies`).
  No Authentik forward-auth (breaks the HA mobile app/API) — rely on HA login + 2FA.
- **Prometheus export** — HA's built-in `prometheus:` endpoint (`/api/prometheus`)
  to feed the existing Prometheus/Grafana stack.
