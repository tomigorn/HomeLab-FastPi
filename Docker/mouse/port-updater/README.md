# port-updater
Keeps qBittorrent's listen port on gluetun's forwarded VPN port and shows a status page. Rust, one static binary on `scratch` (uid 65042). The shell/Python original is in `legacy/` until it is removed by hand.

## What it does
| Job | How |
|---|---|
| Port sync | every `CHECK_INTERVAL` s: gluetun `GET /v1/portforward` + `/v1/publicip/ip` (basic auth) → qBittorrent `setPreferences listen_port` + `torrents/reannounce hashes=all` when the port changed or qBit shows 1/empty |
| qBit restart detection | every `SESSION_CHECK_INTERVAL` s `GET /api/v2/app/version`; 403 = qBittorrent restarted → re-apply at once |
| Interface binding | at start: `current_network_interface=tun0`, then restarts `qbittorrent_mouse` |
| Reattach | qBit WebUI not 200/302 → restart `qbittorrent_mouse mousehole sabnzbd` (log line counted by `PortUpdaterReattachLoop`) |
| Zero port | `ZERO_PORT_LIMIT` zero answers (`ZERO_RETRY_INTERVAL` s apart) → stop the three, restart `gluetun_mouse`, wait healthy, start them |
| History | `/data/port-history.json`, one JSON object per line (format unchanged from legacy) |
| Status page | `WEB_PORT`: `/`, `/index.html`, `/api/history`, `/api/status`; Basic auth when `WEB_USER` + `WEB_PASS` are set; non-GET → 501 |

Docker API (through `socket-proxy-portupdater`, unversioned paths): `GET /containers/gluetun_mouse/json`, `POST /containers/{qbittorrent_mouse,mousehole,sabnzbd,gluetun_mouse}/{start,stop,restart}`. A subset of the legacy CLI's calls; the allow-list is unchanged.

Errors where the legacy script died under `set -e` (qBit unreachable at login, a non-JSON answer from gluetun or qBit, a failed `docker restart`) also end the process here; compose restarts it.

## Env
`GLUETUN_IP` (10.24.32.2), `QBIT_USER`, `QBIT_PASS[_FILE]`, `GLUETUN_AUTH_USER`, `GLUETUN_AUTH_PASS[_FILE]`, `WEB_USER`, `WEB_PASS[_FILE]`, `WEB_PORT` (8088), `CHECK_INTERVAL` (600), `SESSION_CHECK_INTERVAL` (15), `ZERO_RETRY_INTERVAL` (60), `ZERO_PORT_LIMIT` (3), `DOCKER_HOST` (`tcp://host:port` only), `TZ`, `DATA_DIR` (/data).

## Commands
| What | Command |
|---|---|
| Unit tests | run in every `docker build` (stage `test`); alone: `docker build --target test .` |
| Black-box suite (fake gluetun, qBittorrent, Docker; allow-list read from `Docker-Socket-Proxy/portupdater-haproxy.cfg`) | `tests/blackbox/run.sh rust [IMAGE]` / `tests/blackbox/run.sh legacy` |
| Benchmark | `SCRIPT=bench.py tests/blackbox/run.sh rust IMAGE [history.json]` |
| Deploy | `Docker/_global/scripts/update-project.sh Docker/mouse build` with `SERVICES=port-updater` |
| HTTP probe from inside (no curl in the image) | `docker exec port_updater /port-updater probe URL [GET\|POST]` → status code |
| Image sanity | `/port-updater --self-test`, `--version` |
