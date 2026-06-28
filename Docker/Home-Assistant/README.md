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
  and the `automations`/`scripts`/`scenes` includes.
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

## Notes

- **Bluetooth disabled.** The Pi's onboard adapter (`hci0`) is auto-detected and
  spams the log (no D-Bus in the container). It is not needed (we use WiFi +
  future Zigbee USB), so the **Bluetooth integration is deleted in the UI**
  (*Settings → Devices & Services → Bluetooth → Delete*).

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
