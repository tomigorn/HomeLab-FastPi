# fastpi Resource Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add historical per-container RAM/CPU metrics and Home Assistant electricity usage to the existing Grafana stack, in one unified dashboard, so RAM pressure can be attributed to specific containers over time.

**Architecture:** Reuse the running `telegraf → InfluxDB v2 → Grafana` stack. Enable telegraf's Docker input plugin for per-container metrics (no cAdvisor — too heavy on this Pi). Push HA energy/power sensors into the same InfluxDB via HA's native `influxdb:` integration. Visualize everything in one provisioned Grafana dashboard.

**Tech Stack:** telegraf `inputs.docker`, InfluxDB 2.7 (Flux), Home Assistant `influxdb:` integration, Grafana provisioning (datasource + dashboard as code).

**Note (infra plan):** This is infrastructure, not unit-testable code. Each task = concrete edit → verification command with expected output → commit. All commands run on fastpi (`/home/pi`). Repo root: `/home/pi/Projects` (branch `main`). Commit prefix convention: `Project: description`. Never commit secrets.

---

## File map

- `Docker/grafana/telegraf/telegraf.conf` — add `[[inputs.docker]]` (real config)
- `Docker/grafana/telegraf/telegraf.conf.example` — mirror the change (committed template)
- `Docker/grafana/docker-compose.yaml` — telegraf: docker.sock mount + `group_add`; grafana: provisioning mount + `INFLUX_TOKEN` env
- `Docker/Home-Assistant/config/packages/influxdb.yaml` — HA `influxdb:` integration (create)
- `Docker/Home-Assistant/config/secrets.yaml` — add `influxdb_token` (gitignored, NOT committed)
- `Docker/grafana/provisioning/datasources/influxdb.yml` — provisioned InfluxDB datasource (create)
- `Docker/grafana/provisioning/dashboards/dashboards.yml` — dashboard provider (create)
- `Docker/grafana/provisioning/dashboards/fastpi-resources.json` — the dashboard (create)

---

## Task 1: Enable telegraf Docker input (per-container metrics)

**Files:**
- Modify: `Docker/grafana/telegraf/telegraf.conf`
- Modify: `Docker/grafana/telegraf/telegraf.conf.example`
- Modify: `Docker/grafana/docker-compose.yaml`

- [ ] **Step 1: Add the Docker input to `telegraf.conf`** (append after the `[[inputs.file]]` block, before `[[outputs.influxdb_v2]]`):

```toml
[[inputs.docker]]
  endpoint = "unix:///var/run/docker.sock"
  gather_services = false
  container_name_include = []
  container_name_exclude = []
  timeout = "5s"
  perdevice = false
  total = false
  docker_label_include = []
  docker_label_exclude = []
```

- [ ] **Step 2: Mirror the exact same block into `telegraf.conf.example`** (keep the two files identical).

- [ ] **Step 3: Give the telegraf container socket access.** In `Docker/grafana/docker-compose.yaml`, the `telegraf` service, add the read-only socket mount and the `docker` group (GID **991** on this host). Result:

```yaml
  telegraf:
    image: telegraf:latest
    container_name: telegraf
    mem_limit: 256m
    user: telegraf
    group_add:
      - "991"          # docker group — required for telegraf (non-root) to read docker.sock
    environment:
      - INFLUX_TOKEN=${INFLUX_TOKEN}
    volumes:
      - ./telegraf/telegraf.conf:/etc/telegraf/telegraf.conf:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    restart: unless-stopped
```

- [ ] **Step 4: Recreate telegraf.**

Run: `cd /home/pi/Projects/Docker/grafana && docker compose up -d telegraf`
Expected: `Container telegraf  Started` (recreated), no errors.

- [ ] **Step 5: Verify telegraf reads the socket (no permission error).**

Run: `docker logs --since 30s telegraf 2>&1 | grep -iE 'docker|permission|error' | head`
Expected: NO "permission denied" on `/var/run/docker.sock`. (Startup lines about inputs are fine.)

- [ ] **Step 6: Verify per-container memory is now in InfluxDB.**

Run:
```bash
cd /home/pi/Projects
TOKEN=$(grep -E '^INFLUX_TOKEN=' Docker/grafana/.env | cut -d= -f2-)
docker exec influxdb influx query --token "$TOKEN" --org myorg '
from(bucket:"rpi") |> range(start:-5m)
  |> filter(fn:(r)=> r._measurement=="docker_container_mem" and r._field=="usage")
  |> keep(columns:["container_name","_value"]) |> last()' 2>&1 | grep -iE 'languagetool|clamav|container_name' | head
```
Expected: rows listing `languagetool`, `clamav`, etc. with byte values. (If empty, wait 30s for the next telegraf flush and retry.)

- [ ] **Step 7: Commit.**

```bash
cd /home/pi/Projects
git add Docker/grafana/telegraf/telegraf.conf Docker/grafana/telegraf/telegraf.conf.example Docker/grafana/docker-compose.yaml
git commit -m "Grafana: enable telegraf Docker input for per-container metrics"
```

---

## Task 2: Create InfluxDB bucket + write token for Home Assistant

**Files:**
- Modify: `Docker/Home-Assistant/config/secrets.yaml` (gitignored — NOT committed)

- [ ] **Step 1: Create the `homeassistant` bucket (365d retention).**

```bash
cd /home/pi/Projects
TOKEN=$(grep -E '^INFLUX_TOKEN=' Docker/grafana/.env | cut -d= -f2-)
docker exec influxdb influx bucket create --token "$TOKEN" --org myorg --name homeassistant --retention 365d
```
Expected: a line with the new bucket `homeassistant`. (If "bucket already exists", that's fine — continue.)

- [ ] **Step 2: Create a least-privilege write token scoped to that bucket.**

```bash
BUCKET_ID=$(docker exec influxdb influx bucket list --token "$TOKEN" --org myorg --name homeassistant --hide-headers | awk '{print $1}')
docker exec influxdb influx auth create --token "$TOKEN" --org myorg --write-bucket "$BUCKET_ID" --description "home-assistant write" --hide-headers
```
Expected: output whose first column is the new token string. Copy that token for Step 3.

- [ ] **Step 3: Store the token in HA secrets (gitignored).** Append to `Docker/Home-Assistant/config/secrets.yaml`:

```yaml
influxdb_token: <PASTE_TOKEN_FROM_STEP_2>
```

- [ ] **Step 4: Confirm the secret file is still ignored (safety).**

Run: `cd /home/pi/Projects && git check-ignore Docker/Home-Assistant/config/secrets.yaml`
Expected: prints the path (i.e. ignored). NOTHING to commit in this task.

---

## Task 3: Enable Home Assistant InfluxDB integration (electricity)

**Files:**
- Create: `Docker/Home-Assistant/config/packages/influxdb.yaml`

- [ ] **Step 1: Discover the energy/power entities to export.**

Run:
```bash
docker exec homeassistant python -c "print('use API below')" 2>/dev/null; \
grep -rniE 'sensor\..*(power|energy|watt|kwh)' /home/pi/Projects/Docker/Home-Assistant/config/packages /home/pi/Projects/Docker/Home-Assistant/config/ui-lovelace.yaml 2>/dev/null | grep -oiE 'sensor\.[a-z0-9_]+' | sort -u | head -30
```
Expected: a list of `sensor.*_power` / `sensor.*_energy` entity ids (e.g. the myStrom plug). Note them; if the list is empty, fall back to exporting by unit (Step 2 already does this via `include: domains`).

- [ ] **Step 2: Create `Docker/Home-Assistant/config/packages/influxdb.yaml`** (exports only sensor/energy data, keyed to the existing InfluxDB v2):

```yaml
# Push Home Assistant energy/power data to the shared InfluxDB v2 so it can be
# correlated with fastpi RAM/swap in Grafana. Only sensors are exported (energy,
# power, temperature, etc.) to keep the bucket small. Token in secrets.yaml.
influxdb:
  api_version: 2
  host: influxdb
  port: 8086
  ssl: false
  token: !secret influxdb_token
  organization: myorg
  bucket: homeassistant
  max_retries: 3
  measurement_attr: unit_of_measurement
  include:
    domains:
      - sensor
  exclude:
    entity_globs:
      - sensor.*_uptime
      - sensor.*_last_*
```

Note: `homeassistant` (the HA container) reaches `influxdb` by name because both are on the shared Docker network via Traefik/compose. If HA cannot resolve `influxdb`, verify they share a network (see Step 4 troubleshooting).

- [ ] **Step 3: Validate HA config before restarting.**

Run: `docker exec homeassistant python -m homeassistant --script check_config --config /config 2>&1 | tail -20`
Expected: `Testing configuration at /config` ending without ERROR lines for `influxdb`. (If the script is unavailable, proceed and rely on Step 5 logs.)

- [ ] **Step 4: Restart Home Assistant.**

Run: `docker restart homeassistant`
Expected: container restarts. Wait ~40s for HA to come up.

- [ ] **Step 5: Verify no InfluxDB errors in HA logs.**

Run: `docker logs --since 90s homeassistant 2>&1 | grep -iE 'influxdb' | head`
Expected: NO "connection", "unauthorized", or "unable to resolve host" errors. Empty output is fine (silent = working).

Troubleshooting (if "unable to resolve host influxdb" or connection refused): the HA and grafana stacks are on different Docker networks. Fix by adding a shared external network to both compose files, OR set `host: <fastpi-LAN-IP>` and `port: 8086` in the package (InfluxDB already publishes 8086). Prefer the LAN-IP fallback for minimal change; document it in the package comment.

- [ ] **Step 6: Verify HA data landed in InfluxDB.**

```bash
cd /home/pi/Projects
TOKEN=$(grep -E '^INFLUX_TOKEN=' Docker/grafana/.env | cut -d= -f2-)
docker exec influxdb influx query --token "$TOKEN" --org myorg '
from(bucket:"homeassistant") |> range(start:-10m)
  |> filter(fn:(r)=> r._field=="value")
  |> keep(columns:["_measurement","entity_id"]) |> group() |> distinct(column:"entity_id")' 2>&1 | head -20
```
Expected: a list of exported `entity_id`s (including power/energy sensors). If empty, wait 2-3 min (HA flushes periodically) and retry.

- [ ] **Step 7: Commit (package only — no secret).**

```bash
cd /home/pi/Projects
git add Docker/Home-Assistant/config/packages/influxdb.yaml
git commit -m "Home-Assistant: export energy/power sensors to shared InfluxDB"
```

---

## Task 4: Provision the unified Grafana dashboard

**Files:**
- Create: `Docker/grafana/provisioning/datasources/influxdb.yml`
- Create: `Docker/grafana/provisioning/dashboards/dashboards.yml`
- Create: `Docker/grafana/provisioning/dashboards/fastpi-resources.json`
- Modify: `Docker/grafana/docker-compose.yaml` (grafana service)

- [ ] **Step 1: Provision the InfluxDB (Flux) datasource.** Create `Docker/grafana/provisioning/datasources/influxdb.yml`:

```yaml
apiVersion: 1
datasources:
  - name: InfluxDB-fastpi
    uid: influxdb_fastpi
    type: influxdb
    access: proxy
    url: http://influxdb:8086
    jsonData:
      version: Flux
      organization: myorg
      defaultBucket: rpi
    secureJsonData:
      token: ${INFLUX_TOKEN}
    isDefault: false
    editable: true
```

- [ ] **Step 2: Provision the dashboard provider.** Create `Docker/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
apiVersion: 1
providers:
  - name: fastpi
    orgId: 1
    folder: fastpi
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
```

- [ ] **Step 3: Create the dashboard** `Docker/grafana/provisioning/dashboards/fastpi-resources.json`:

```json
{
  "uid": "fastpi-resources",
  "title": "fastpi — RAM, containers & electricity",
  "tags": ["fastpi", "monitoring"],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "refresh": "30s",
  "time": { "from": "now-24h", "to": "now" },
  "templating": { "list": [] },
  "panels": [
    {
      "id": 1,
      "type": "timeseries",
      "title": "Host memory & swap",
      "datasource": { "type": "influxdb", "uid": "influxdb_fastpi" },
      "gridPos": { "h": 9, "w": 24, "x": 0, "y": 0 },
      "fieldConfig": { "defaults": { "unit": "decbytes" }, "overrides": [] },
      "targets": [
        {
          "refId": "used",
          "query": "from(bucket:\"rpi\") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn:(r)=> r._measurement==\"mem\" and r._field==\"used\") |> aggregateWindow(every: v.windowPeriod, fn: mean) |> set(key:\"_field\", value:\"mem_used\")"
        },
        {
          "refId": "available",
          "query": "from(bucket:\"rpi\") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn:(r)=> r._measurement==\"mem\" and r._field==\"available\") |> aggregateWindow(every: v.windowPeriod, fn: mean) |> set(key:\"_field\", value:\"mem_available\")"
        },
        {
          "refId": "swap",
          "query": "from(bucket:\"rpi\") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn:(r)=> r._measurement==\"swap\" and r._field==\"used\") |> aggregateWindow(every: v.windowPeriod, fn: mean) |> set(key:\"_field\", value:\"swap_used\")"
        }
      ]
    },
    {
      "id": 2,
      "type": "timeseries",
      "title": "Per-container memory (stacked)",
      "datasource": { "type": "influxdb", "uid": "influxdb_fastpi" },
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 9 },
      "fieldConfig": {
        "defaults": {
          "unit": "decbytes",
          "custom": { "stacking": { "mode": "normal", "group": "A" }, "fillOpacity": 30, "showPoints": "never" }
        },
        "overrides": []
      },
      "targets": [
        {
          "refId": "A",
          "query": "from(bucket:\"rpi\") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn:(r)=> r._measurement==\"docker_container_mem\" and r._field==\"usage\") |> aggregateWindow(every: v.windowPeriod, fn: mean) |> group(columns:[\"container_name\"]) |> keep(columns:[\"_time\",\"_value\",\"container_name\"])"
        }
      ]
    },
    {
      "id": 3,
      "type": "timeseries",
      "title": "Electricity — power (W)",
      "datasource": { "type": "influxdb", "uid": "influxdb_fastpi" },
      "gridPos": { "h": 9, "w": 24, "x": 0, "y": 19 },
      "fieldConfig": { "defaults": { "unit": "watt" }, "overrides": [] },
      "targets": [
        {
          "refId": "A",
          "query": "from(bucket:\"homeassistant\") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn:(r)=> r._measurement==\"W\" and r._field==\"value\") |> aggregateWindow(every: v.windowPeriod, fn: mean) |> group(columns:[\"entity_id\"]) |> keep(columns:[\"_time\",\"_value\",\"entity_id\"])"
        }
      ]
    }
  ]
}
```

Note on the electricity query: HA's `measurement_attr: unit_of_measurement` stores power sensors under measurement `W` and energy under `kWh`. If Task 3 Step 1 showed the plug reports a different unit, adjust `r._measurement==\"W\"` accordingly (verified live in Step 6).

- [ ] **Step 4: Mount provisioning + pass the token into Grafana.** In `Docker/grafana/docker-compose.yaml`, the `grafana` service:

```yaml
  grafana:
    image: grafana/grafana-oss:latest
    container_name: grafana
    mem_limit: 512m
    restart: unless-stopped
    ports:
      - "3001:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./provisioning:/etc/grafana/provisioning:ro
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
      - INFLUX_TOKEN=${INFLUX_TOKEN}
```

- [ ] **Step 5: Recreate Grafana.**

Run: `cd /home/pi/Projects/Docker/grafana && docker compose up -d grafana`
Expected: `Container grafana  Started`.

- [ ] **Step 6: Verify provisioning loaded (no errors).**

Run: `docker logs --since 60s grafana 2>&1 | grep -iE 'provisioning|datasource|dashboard|error' | head`
Expected: lines showing the datasource and dashboard provisioned; no fatal provisioning errors.

- [ ] **Step 7: Verify the dashboard is queryable via the Grafana API.**

```bash
PW=$(grep -E '^GRAFANA_ADMIN_PASSWORD=' /home/pi/Projects/Docker/grafana/.env | cut -d= -f2-)
curl -s -u "admin:$PW" http://localhost:3001/api/dashboards/uid/fastpi-resources | head -c 300; echo
```
Expected: JSON containing `"title":"fastpi — RAM, containers & electricity"` (not a "not found" error).

- [ ] **Step 8: Commit.**

```bash
cd /home/pi/Projects
git add Docker/grafana/provisioning Docker/grafana/docker-compose.yaml
git commit -m "Grafana: provision unified fastpi RAM + container + electricity dashboard"
```

---

## Task 5: Final verification & handoff

- [ ] **Step 1: Confirm all three data sources are live in one place.**

```bash
cd /home/pi/Projects
TOKEN=$(grep -E '^INFLUX_TOKEN=' Docker/grafana/.env | cut -d= -f2-)
echo "container mem samples (last 5m):"
docker exec influxdb influx query --token "$TOKEN" --org myorg 'from(bucket:"rpi")|>range(start:-5m)|>filter(fn:(r)=>r._measurement=="docker_container_mem" and r._field=="usage")|>count()|>sum()' 2>&1 | tail -3
echo "HA electricity samples (last 15m):"
docker exec influxdb influx query --token "$TOKEN" --org myorg 'from(bucket:"homeassistant")|>range(start:-15m)|>filter(fn:(r)=>r._field=="value")|>count()|>sum()' 2>&1 | tail -3
```
Expected: non-zero counts for both.

- [ ] **Step 2: Confirm monitoring overhead stayed small.**

Run: `docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -E 'telegraf|grafana|influxdb'`
Expected: telegraf still well under its 256m limit; no new heavy container added.

- [ ] **Step 3: Tell the user the dashboard URL.** Grafana is at `http://<fastpi-LAN-IP>:3001` (or its Traefik hostname if routed) → folder **fastpi** → dashboard **"fastpi — RAM, containers & electricity"**. Point out that container memory and host swap now share a timeline with electricity, so they can see whether LanguageTool, clamav, or the sum causes the pressure.

- [ ] **Step 4: Update memory.** Record in `languagetool-project` / a new `fastpi-monitoring` memory: telegraf Docker input enabled, HA→InfluxDB `homeassistant` bucket, provisioned Grafana dashboard `fastpi-resources`, and the finding that clamav rivals LanguageTool for RAM.

---

## Self-review notes

- **Spec coverage:** per-container RAM (Task 1) ✓, host RAM/swap already collected ✓, electricity (Tasks 2-3) ✓, unified dashboard (Task 4) ✓, minimal footprint — telegraf reuse, no cAdvisor ✓, established tooling ✓.
- **Deferred (non-goals):** alerting and new hard caps intentionally out of scope.
- **Secrets:** only HA `influxdb_token` is a secret; it lives in gitignored `secrets.yaml` and is never staged. Verified in Task 2 Step 4.
- **Known risk:** HA↔InfluxDB network reachability (Task 3 Step 5 troubleshooting covers the LAN-IP fallback).
