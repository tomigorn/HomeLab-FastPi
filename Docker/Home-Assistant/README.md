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
- `packages/*.yaml` — one file per feature (see [myStrom plug](#mystrom-plug)).
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
sudo nano config/packages/mystrom_plug.yaml
# validate before applying:
docker exec homeassistant python -m homeassistant --script check_config -c /config
# apply: reload the domain in Developer Tools → YAML (REST/Template/Automations),
# or restart for core/package changes:
docker compose restart
```

## Dashboards

The default **Overview** dashboard is config-as-code: `config/ui-lovelace.yaml`,
registered in `configuration.yaml` under `lovelace.dashboards` at the reserved
`lovelace` url-path. That key **claims the default Overview slot**, replacing HA's
auto-generated "home" dashboard:

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
- **Overview** — myStrom plug controls, power gauge, 24 h power history.
- **Energy** — live + per-period kWh, by-tariff, cost, and long-term
  day/month/power graphs.

Editing the YAML content only needs a **browser refresh**; changing the
registration (title/icon/mode) needs `docker compose restart`.

> **Pitfall:** the old top-level `lovelace: mode: yaml` is **deprecated** (removed
> in HA 2026.8) and in current HA no longer claims the Overview slot — it leaves
> the auto "home" dashboard in place and shows your YAML as a *duplicate* Overview.
> Use the `dashboards.lovelace` form above. Full decision record:
> [`docs/2026-06-29-overview-electricity-dashboard.md`](docs/2026-06-29-overview-electricity-dashboard.md).

Other dashboards (e.g. **Map**) stay storage-mode (UI-managed, in `.storage`).

## myStrom plug

A **myStrom WiFi Switch** (`myStrom-Switch-61A328`), defined **entirely in YAML**
(`config/packages/mystrom_plug.yaml`) via its **local HTTP API** — no cloud, no
myStrom account, **no subscription** (the app's paid "myStrom PLUS" abo is
irrelevant; HA talks to the device directly on the LAN).

Local API used:

| Endpoint | Purpose |
|---|---|
| `GET /report` | `{"power":W, "Ws":.., "relay":bool, "temperature":C}` |
| `GET /relay?state=1` / `?state=0` | switch the relay on / off |

Entities created (all config-as-code):

| Entity | Purpose |
|---|---|
| `switch.mystrom_plug` | on/off button (template switch → `rest_command`) |
| `sensor.mystrom_plug_power` | live power (W) |
| `sensor.mystrom_plug_energy` | derived kWh (Riemann `integration`) → Energy dashboard |
| `sensor.mystrom_plug_temperature` | plug temperature (°C) |
| `binary_sensor.mystrom_plug_relay` | relay state feedback |

### ⚠️ IP address — static DHCP reservation REQUIRED

The YAML **hardcodes the plug's IP**, so the address must never change. HA talks
to devices over **IP** (a MAC is layer-2, not routable — you can't HTTP to a
MAC), and the plain `rest:` integration has no discovery, so it cannot re-find a
device whose IP moved. The fix is a **static DHCP reservation** on the router.

Router: **AX7501-B1 → Home Networking → Static DHCP**

| Field | Value |
|---|---|
| **MAC** | `34:98:7A:61:A3:28` |
| **Reserved IP** | `192.168.1.150` |
| **Band** | WiFi 2.4 GHz |

If the plug ever gets a new IP, update **both** the reservation **and** the IP in
`config/packages/mystrom_plug.yaml` (4 references), then `docker compose restart`.

> **Alternative if you dislike hardcoding:** the native myStrom integration (UI)
> uses mDNS discovery and tracks the device by its MAC-derived unique ID, so it
> auto-updates on IP change — but the device entry then lives in `.storage`
> (not committed). We chose YAML + static lease to keep everything in git.

## Electricity metering, tariffs & cost

`config/packages/electricity.yaml` builds the metering layer on top of the plug's
`sensor.mystrom_plug_energy` (lifetime kWh) and `sensor.mystrom_plug_power` (W).

- **Forever history** — any sensor with a `state_class` keeps **long-term
  statistics** (hourly aggregates) **forever**; only the every-5s detail is purged
  (recorder default 10 days). The dashboard's `statistics-graph` cards read these.
- **Per-period kWh** — `utility_meter` cycles: `sensor.mystrom_hourly`,
  `…_weekly`, and tariff-split `mystrom_daily/monthly/yearly/total` →
  `sensor.mystrom_<cycle>_high` / `_low` (+ a `select.mystrom_<cycle>`).
- **Tariff (City of Zürich / EWZ)** — **HIGH** = Mon–Sat 06:00–22:00; **LOW** =
  nights 22:00–06:00 **and all day Sunday**. One automation applies the correct
  tariff to all `select`s at 06:00 / 22:00 / on start (`now().weekday() != 6 and
  6 <= hour < 22` → high). `sensor.mystrom_current_tariff` shows the active one.
- **Prices** — two `input_number` helpers (`electricity_price_high` / `_low`,
  CHF/kWh), **editable in the UI** (Energy view). The YAML `initial:` defaults are
  the **real EWZ 2026 tariffs**: high **0.2988**, low **0.1870** CHF/kWh.
- **Cost** — `sensor.mystrom_cost_today/this_month/this_year/total` =
  `high_kWh × price_high + low_kWh × price_low` (true time-of-use cost).

Shown on the dashboard's **Energy** view (live, per-period kWh, by-tariff, cost,
and forever day/month/power graphs).

### Setting the real tariff prices

Open the **Energy** view → edit **Price — high** and **Price — low**. Values
persist in `.storage` (not git). To bake new defaults into git, change `initial:`
in `electricity.yaml` (only applied on a fresh install).

### Native Energy dashboard (configured — UI-only)

HA's built-in **Energy** dashboard is set up (Settings → Dashboards → Energy).
It is **UI-configured and lives in `.storage/energy`** — there is no YAML for it.

- **Grid consumption** = `sensor.mystrom_plug_energy`. (Only grid sources get cost
  tracking; an *Individual device* would be energy-only.)
- **Cost** = *"Use an entity with current price"* → `sensor.mystrom_current_price`
  (tariff-aware). HA auto-creates `sensor.mystrom_plug_energy_cost`.
- The Energy panel's **date-range picker** then shows kWh **and** CHF for any
  period (hourly/daily resolution — long-term stats are hourly). Cost accrues
  **from setup onward**; historical kWh is present but past cost is not
  back-calculated.

## Areas & device location

HA **areas** (rooms) are UI/registry data in `.storage` (not YAML). The home's
rooms are:

> WC · Dusche · Eingang · Schlafzimmer Tomas · Schlafzimmer Rafi · Küche ·
> Esszimmer · Reduit · Wohnzimmer · Balkon

The myStrom plug lives in **Schlafzimmer Rafi**. Because it's defined in YAML
(no auto-created *device*), the room is assigned at the **entity** level — the
physical entities (`switch.mystrom_plug`, `binary_sensor.mystrom_plug_relay`,
`sensor.mystrom_plug_power` / `_temperature` / `_energy` / `_energy_cost`) carry
`area_id: schlafzimmer_rafi`. The derived tariff/price/cost sensors are left
unassigned (they're calculations, not physically located).

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
