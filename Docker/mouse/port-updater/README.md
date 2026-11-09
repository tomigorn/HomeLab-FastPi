# port-updater
Keeps qBittorrent's listen port on gluetun's forwarded VPN port and shows a status page. Rust, one static binary on `scratch` (uid 65042). The shell/Python original is in `legacy/` until it is removed by hand.

## What it does
| Job | How |
|---|---|
| Port sync | every `CHECK_INTERVAL` s: gluetun `GET /v1/portforward` + `/v1/publicip/ip` (basic auth) → qBittorrent `setPreferences listen_port` + `torrents/reannounce hashes=all` when the port changed or qBit shows 1/empty |
| gluetun API error | non-2xx or non-JSON answer (`Unauthorized`, `404 page not found`): port unknown, last port kept, no zero count, retry next cycle; log `gluetun API error: …` |
| qBit restart detection | every `SESSION_CHECK_INTERVAL` s `GET /api/v2/app/version`; 403 = qBittorrent restarted → re-apply at once |
| Interface binding | at start: when `current_network_interface` is not `tun0` yet, sets it and restarts `qbittorrent_mouse`; already `tun0` → no restart |
| Reattach | qBit WebUI not 200/302 → restart `qbittorrent_mouse mousehole sabnzbd` (log line counted by `PortUpdaterReattachLoop`) |
| Zero port | `ZERO_PORT_LIMIT` zero/invalid answers or no answer (`ZERO_RETRY_INTERVAL` s apart) → stop the three, restart `gluetun_mouse`, wait healthy, start them |
| Back-off | each stack restart that brings no port doubles the wait before the next one (`STACK_RESTART_BACKOFF` 240 s, cap `STACK_RESTART_BACKOFF_MAX` 3600 s); gluetun polled meanwhile, a valid port resets it; log `No port after stack restart - backing off N min (S s) before the next one` |
| Alert | `PortUpdaterReattachLoop`: ≥ 2 reattaches or ≥ 4 stack restarts in 6 h (`customization_check_exporter.py` counts the log lines) |
| History | `/data/port-history.json`, one JSON object per line (format unchanged from legacy), newest 2000 kept (~830 in 8 months); `vpn_ip` kept only if it is a plain IPv4/IPv6 string, else empty |
| Status page | `WEB_PORT`: `/`, `/index.html`, `/api/history`, `/api/status`; Basic auth when `WEB_USER` + `WEB_PASS` are set, open when both are empty, locked (always 401) when only one is set (e.g. unreadable secret file); history values are HTML-escaped; non-GET → 501 |

Docker API (through `socket-proxy-portupdater`, unversioned paths): `GET /containers/gluetun_mouse/json`, `POST /containers/{qbittorrent_mouse,mousehole,sabnzbd,gluetun_mouse}/{start,stop,restart}`. A subset of the legacy CLI's calls; the allow-list is unchanged.

qBit unreachable at login, a non-JSON qBit answer or a failed `docker restart` still end the process; compose restarts it, and the start skips the qBittorrent restart when it is already bound to `tun0`.

## Env
`GLUETUN_IP` (10.24.32.2), `QBIT_USER`, `QBIT_PASS[_FILE]`, `GLUETUN_AUTH_USER`, `GLUETUN_AUTH_PASS[_FILE]`, `WEB_USER`, `WEB_PASS[_FILE]`, `WEB_PORT` (8088), `CHECK_INTERVAL` (600), `SESSION_CHECK_INTERVAL` (15), `ZERO_RETRY_INTERVAL` (60), `ZERO_PORT_LIMIT` (3), `STACK_RESTART_BACKOFF` (240), `STACK_RESTART_BACKOFF_MAX` (3600), `DOCKER_HOST` (`tcp://host:port` only), `TZ`, `DATA_DIR` (/data).

## Commands
| What | Command |
|---|---|
| Unit tests | run in every `docker build` (stage `test`); alone: `docker build --target test .` |
| Black-box suite (fake gluetun, qBittorrent, Docker; allow-list read from `Docker-Socket-Proxy/portupdater-haproxy.cfg`) | `tests/blackbox/run.sh rust [IMAGE]` / `tests/blackbox/run.sh legacy` |
| Benchmark | `SCRIPT=bench.py tests/blackbox/run.sh rust IMAGE [history.json]` |
| Deploy | `Docker/_global/scripts/update-project.sh Docker/mouse build` with `SERVICES=port-updater` |
| HTTP probe from inside (no curl in the image) | `docker exec port_updater /port-updater probe URL [GET\|POST]` → status code |
| Image sanity | `/port-updater --self-test`, `--version` |
