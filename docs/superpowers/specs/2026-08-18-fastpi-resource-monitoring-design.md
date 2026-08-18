# fastpi resource monitoring — historical per-container RAM + electricity

**Date:** 2026-08-18
**Status:** Design approved, ready for planning

## Problem

fastpi (8 GB Pi 5, Raspberry Pi OS) periodically runs low on RAM and dips
into swap, occasionally near-freezing. LanguageTool is *suspected* of eating
all the resources, but there is currently **no per-container history** to
confirm which container(s) actually cause the pressure and *when*. Host-level
RAM/swap history exists; per-container attribution does not.

## Current state (already running, `Docker/grafana/`)

- **telegraf** → InfluxDB v2 (org `myorg`, bucket `rpi`): host cpu/mem/swap/
  disk/net/system/processes/kernel/CPU-temp. No `[[inputs.docker]]`.
- **prometheus** (5s scrape) → `node-exporter:9100`: host metrics.
- **influxdb** v2, **grafana**: the visualization layer.
- Memory cgroup **is enabled** (`cgroup_enable=memory` in cmdline; `docker
  stats` reports real per-container memory) — prerequisite satisfied.
- Home Assistant (`Docker/Home-Assistant/config/configuration.yaml`) already
  tracks electricity (myStrom plug @ 192.168.1.150 among others).

### Snapshot that motivated the design (2026-08-18)
Top RAM consumers: languagetool 963 MiB (capped at 1.25 GiB, i.e. mem_limit
IS deployed), **clamav 950 MiB**, homeassistant 414, authentik-server 365 +
worker 277, jenkins 335. Conclusion: no single container OOMs the Pi; the
**sum** pushes it into swap. clamav is nearly tied with LanguageTool — the
historical view must cover all containers, not just LanguageTool.

## Goals

1. Historical, per-container RAM (and CPU) visible in Grafana over time.
2. Fold Home Assistant electricity usage into the same Grafana so RAM spikes,
   swap pressure, and power draw share one timeline.
3. Keep the monitoring footprint minimal — the Pi is already memory-pressured.
4. Use established, standard tooling (reuse the running stack).

## Non-goals (deferred, not built now)

- Proactive alerting — Grafana has built-in alerting; layer on later if wanted.
- New hard memory caps — LanguageTool's mem_limit already works; other
  containers can be capped later as a separate task.
- Replacing/duplicating the existing stack (no Netdata/Beszel/Zabbix).

## Design

Single pane of glass = **Grafana**. All metrics land in the **existing
InfluxDB**. No new heavyweight containers.

### 1. Per-container metrics — telegraf Docker input
Enable telegraf's built-in `[[inputs.docker]]`, reading the Docker socket:
- Mount `/var/run/docker.sock:/var/run/docker.sock:ro` into the telegraf
  container (read-only).
- Config: `endpoint = "unix:///var/run/docker.sock"`, `perdevice = false`,
  `total = false`, gather container cpu/mem. Writes to the same `rpi` bucket.
- **Rejected alternative — cAdvisor + Prometheus:** heavy on Pi (research
  cites up to 28% CPU / high RAM), and splits container metrics into
  Prometheus while electricity is in InfluxDB → two datasources, harder
  unified dashboard. Consolidating on InfluxDB is lighter and simpler.

### 2. Electricity — Home Assistant InfluxDB integration
Add the native `influxdb:` integration to HA `configuration.yaml`, pointing at
the existing InfluxDB v2 (own bucket `homeassistant` for independent
retention). **Filter to energy/power entities only** (include-list by
domain/entity) to avoid bloating InfluxDB with all HA state. Needs an InfluxDB
token/bucket for HA (created in InfluxDB, stored in HA secrets).

### 3. Unified Grafana dashboard
One dashboard, InfluxDB datasource, shared time range:
- Host memory used / available + swap used (from existing `rpi` data).
- Top-N container memory (stacked or multi-line) from the new docker input —
  LanguageTool, clamav, etc. clearly separated.
- Electricity: current power (W) and/or cumulative energy from HA bucket.
- Provisioned as a dashboard JSON in `Docker/grafana/` where possible so it
  is version-controlled, not click-configured only.

## Data flow

```
docker.sock ─▶ telegraf[[inputs.docker]] ─┐
host sensors ─▶ telegraf (existing) ──────┼─▶ InfluxDB(rpi) ─┐
                                          │                  ├─▶ Grafana dashboard
Home Assistant (energy) ─▶ HA influxdb: ──┴─▶ InfluxDB(homeassistant) ─┘
```

## Risks / gotchas

- **Telegraf 0-byte container memory on Pi** (historic issue #8079): mitigated
  — cgroup memory confirmed enabled; `docker stats` already reports real
  values. Verify after enabling.
- **docker.sock exposure**: mounted read-only; telegraf is a trusted
  first-party container. Standard practice, acceptable.
- **InfluxDB growth from HA**: mitigated by filtering to energy/power entities
  and setting bucket retention.
- **Secrets**: HA InfluxDB token goes in HA `secrets.yaml` (gitignored); the
  telegraf change needs no new secret.

## Success criteria

- Grafana shows each container's RAM over the past hours/days, with
  LanguageTool and clamav distinguishable.
- The same dashboard shows electricity usage on the shared timeline.
- Added monitoring overhead is negligible (no new heavy container).
- Configs committed (secrets excluded), following the repo's project layout.
