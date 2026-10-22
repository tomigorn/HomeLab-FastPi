# Monitoring stack review — 2026-10-22

Scope: `Docker/grafana` — Prometheus, Grafana, Alertmanager, blackbox-exporter, node-exporter, json-exporter, InfluxDB, Telegraf, container-exporter.

Method: read every config + rule file; queried the live Prometheus (targets, alerts, rule health, metric presence); compared running image versions against upstream releases.

Live state at review time: all 19 scrape targets `up`; config last reload OK; no rule evaluation errors across 18 groups; firing alerts were only the expected info/heartbeat ones (CriticalImageVulnerabilities, NewCriticalImageVulnerabilities, UnraidUpdateAvailable, AlertingHeartbeat). Every metric referenced by a rule has live series — **no dead rules found**. The new `blackbox-lan-locked` 403 job (commit 1aefad5) is healthy: all 6 admin apps return 403 → `probe_success=1`.

Severity key: 🔴 high · 🟠 medium · 🟡 low · 🟢 good (no action). Status: **safe-now** = apply without asking · **confirm** = needs owner decision.

---

## (a) Versions

Containers were all recreated 2026-10-21. Running vs upstream latest:

| Image | Tag in compose | Running | Upstream latest | Status | Action |
|---|---|---|---|---|---|
| grafana/grafana-oss | `:latest` | **13.0.2** | **13.2.4** (2026-10-13) | 🟠 2 minor behind | confirm |
| prom/prometheus | `:latest` | **3.15.0** | **3.15.1** (2026-10-21) | 🟡 1 patch behind | confirm |
| prom/blackbox-exporter | `v0.29.0` | 0.29.0 | **0.29.1** (2026-10-21) | 🟡 1 patch behind | confirm |
| prom/node-exporter | `:latest` | 1.12.1 | 1.12.1 | 🟢 current | — |
| quay.io/prometheus/alertmanager | `v0.34.1` | 0.34.1 | 0.34.1 | 🟢 current | — |
| quay.io/prometheuscommunity/json-exporter | `v0.8.0` | 0.8.0 | 0.8.0 | 🟢 current | — |
| influxdb | `2.9.1` | 2.9.1 | 3.12.1 (v3) | 🟢 current for v2 line | **do not move** |
| telegraf | `:latest` | 1.40.2 | 1.40.2 | 🟢 current | — |

Findings:

- 🟠 **A1 — Grafana is 2 minor versions behind despite `:latest`.** The tag is `:latest` but the running binary is 13.0.2 while upstream is 13.2.4 (released 2026-10-13). The 2026-10-21 recreate reused a cached local image instead of pulling, so `:latest` gives a false "always current" impression while silently drifting. Grafana is not edge-critical. **Fix:** `docker compose pull grafana && docker compose up -d grafana`, verify login + dashboards, then pin the tag (see C1). **confirm** (not blind — read 13.1/13.2 release notes first).
- 🟡 **A2 — Prometheus 3.15.0 → 3.15.1** (patch, released the same day as the recreate so the pull just missed it). Safe patch. **confirm.**
- 🟡 **A3 — blackbox-exporter v0.29.0 → v0.29.1** (patch, 2026-10-21). Pinned, so needs an explicit tag edit. Safe. **confirm.**
- 🟢 **A4 — InfluxDB deliberately pinned to the 2.x line.** Upstream "latest" is v3.x, a breaking rewrite. The pin + comment are correct; leave as-is.
- 🟢 **A5 — alertmanager, json-exporter, node-exporter, telegraf are current.**

Note: none of the monitoring images are in the edge stack (Traefik/Authentik/CrowdSec/AdGuard), so version bumps here are low-blast-radius. The `grafana` row in `_global/checklist.md` is still ❌/❌ (unreviewed) — worth a look when the owner next updates that list.

---

## (b) Config drift vs reality

Overall: **the config matches the real homelab well.** Checked against the known recent changes (6 LAN-locked admin apps, media → beefy, deleted Cloudflare endpoints) and against live Prometheus.

- 🟢 **B1 — LAN-locked job is correct.** `blackbox-lan-locked` (radarr/sonarr/prowlarr/bazarr/qbittorrent/sabnzbd, `http_forbidden` module, 403-healthy) all `up`. Matches commit 1aefad5. No action — as instructed.
- 🟢 **B2 — No stale probe targets.** Every `blackbox-public`/`blackbox-gated` target (audiobookshelf, sso, claude-mockups, cup) resolves and is healthy. No probe points at a deleted Cloudflare endpoint.
- 🟢 **B3 — Jellyfin correctly excluded.** Media moved to beefy; the deliberate no-probe on Jellyfin (wake-loop) is documented and consistent. The arr apps are still probed by hostname regardless of host — fine.
- 🟢 **B4 — No dead rules.** All rule-referenced metrics have live series (`container_*`, `host_last_boot_unclean`, `clamav_*`, `security_*`, `crowdsec_*`, `cup_updates_*`, `probe_*`). No rule evaluates against a metric that no longer exists.
- 🟠 **B5 — No external "fastpi is down" dead-man's switch wired.** The only cover for fastpi itself being offline is `AlertingHeartbeat`, which is **email-only every 28 days** — a fastpi outage could go unsurfaced for up to 4 weeks. A healthchecks.io setup guide exists (commit 9c71c0d) but no ping timer/cron is installed (`systemctl list-timers` shows none). **Fix:** finish wiring the external dead-man's switch from that guide. **confirm** (enrolling an external service needs a yes per machine.md). Already flagged in the stack README as a known gap.
- 🟠 **B6 — AdGuard (LAN DNS) has no functional probe.** AdGuard is edge-critical (DHCP DNS for the LAN) but is only covered at container level by `ContainerDown`. If it stays up but answers wrongly/empty, nothing notices. **Fix:** add a blackbox `dns` module probe (resolve a known `*.holy-grail.ch` name against AdGuard) + a rule. **confirm** (new target + rule; owner should decide the assertion — which name, expected answer).
- 🟡 **B7 — Duplicate/possibly-unused InfluxDB datasource.** `provisioning/datasources/influxdb.yml` defines two InfluxDB datasources: `influxdb_fastpi` (used — 19 refs across fastpi-resources + languagetool-watch) and `influxdb` / uid `dfc6d7roab08we` (the UI-created one re-pointed to the container name). No provisioned dashboard references the second. It may still back ad-hoc UI dashboards, so don't remove blindly. **Fix:** confirm nothing uses `dfc6d7roab08we`, then drop it. **confirm.**

---

## (c) Best practice

- 🔴 **C1 — Four images float on `:latest`** (prometheus, node-exporter, grafana, telegraf) while the rest of the homelab pins by version/digest and tracks updates through Cup. `:latest` here (i) hides drift — A1 proves it (Grafana looked current, was 2 minor behind); (ii) is not reproducible — a recreate can silently pull an unvetted new **major** (e.g. a node-exporter/telegraf breaking change) with no review; (iii) sidesteps the Cup + Trivy update-review flow every other project uses. **Fix:** pin all four to explicit version tags (digest-pin where you want to match the Mousehole pattern), matching the homelab convention, and let Cup surface updates. **confirm** (coordinate with the normal update-review process; InfluxDB already shows the right pattern).
- 🟠 **C2 — Global `scrape_interval: 5s` is aggressive for a Pi.** node-exporter, traefik and alertmanager are scraped every 5s (crowdsec 30s, blackbox 60s, cup 15m already override). 5s is 3× the standard 15s sample volume → more TSDB churn, CPU and WAL, and it eats the 60 GB retention headroom faster than the comment's own math assumes. No rule needs sub-15s resolution (all windows are ≥15m). **Fix:** set global to 15s, keep the per-job overrides. **confirm** (changes dashboard/graph resolution — a visible, if minor, change).
- 🟠 **C3 — `scrape_timeout` is clamped to 5s.** Because global `scrape_timeout` is unset and the interval is 5s, Prometheus pinned the effective timeout to 5s for the 5s jobs. On a loaded Pi a node-exporter scrape can exceed 5s → a spurious `up==0` and a false alert. Resolved for free by C2 (15s interval ⇒ 10s default timeout), or set `scrape_timeout` explicitly. **confirm** (bundle with C2).
- 🟠 **C4 — No Alertmanager inhibition rules.** `group_by: ['alertname']` collapses same-alert fan-out (good), but a whole-edge outage still sends `AllPublicEndpointsDown` **and** separate `PublicEndpointDown` groups (different alertnames → different groups) — the pile-on the design says it wants to avoid. Likewise `AlertmanagerDown`/`BlackboxExporterDown` don't suppress the alerts that depend on them. **Fix:** add `inhibit_rules` (e.g. `AllPublicEndpointsDown` inhibits `PublicEndpointDown`; `BlackboxExporterDown` inhibits probe-derived alerts). **confirm.**
- 🟡 **C5 — blackbox.yml comment block is scrambled.** The comment above `tcp_connect` (lines ~64–74) starts correctly on tcp_connect, then mixes in text that actually describes `http_forbidden` ("Expects exactly 403… cloud.holy-grail.ch/.env") and `http_nextcloud_login` ("Nextcloud on tower must redirect /login…"), while those two modules below carry little/no context. Cosmetic, but misleading. **Fix:** move each stray line above its real module. **safe-now** (comment-only) — left for owner since it needs careful per-module reattribution; not applied to avoid misattributing.
- 🟡 **C6 — Dashboards: `allowUiUpdates: true` + `disableDeletion: false`.** UI edits are allowed and not reliably persisted back to git, so UI↔file drift is possible. This is a deliberate editability trade-off; noting it so dashboard changes get exported to the JSON files to stay version-controlled.
- 🟢 **C7 — Secrets handling is correct.** Alertmanager secrets are files mode `600`, gitignored, container runs as uid 1000 to match. Grafana/Influx tokens via `.env` (gitignored). Telegraf token externalised to `.conf.example` pattern. json-exporter hits Cup's unauth API but it's bound to the bridge gateway only. No inline secrets. `.gitignore` covers `telegraf.conf`, `alertmanager.yml`, `secrets/`.
- 🟢 **C8 — Blackbox module reuse is good.** 5 modules cleanly cover 8 probe jobs (`http_forbidden` reused by lan-locked + tower-guard; `tcp_connect` by beefy + tower). No redundant modules.
- 🟢 **C9 — Retention is sized and documented** (400d / 60 GB cap, with the series math and the size-cap-as-guard rationale). mem_limit set on every service. Networks scoped (crowdsec/socket_proxy/traefik_proxy external, internal-only). Ports bound to 127.0.0.1 per the SSO-only policy.

---

## Applied (this review)

| # | Change | File | Risk |
|---|---|---|---|
| ✅ | Moved the Traefik scrape-job description comment from above the `alertmanager` job to above the `traefik` job (it was misattributed — the comment described Traefik but sat over Alertmanager). Comment-only, zero behaviour change. | `prometheus/prometheus.yml` | none — `promtool check config` passes |

Nothing else was changed. All other findings are left for owner confirmation as noted.

---

## Suggested priority order

1. **C1** pin the four `:latest` images (fixes the root cause of A1/A2) — then **A1/A3** bump Grafana + blackbox.
2. **B5** wire the external dead-man's switch (biggest real coverage gap).
3. **C2+C3** drop global interval to 15s (perf + false-alert fix, one edit).
4. **C4** add inhibition rules.
5. **B6** AdGuard DNS probe.
6. **B7, C5, C6** cleanups.
