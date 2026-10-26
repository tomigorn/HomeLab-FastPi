# mouse
Torrent/usenet download stack (gluetun, qBittorrent, SABnzbd, MouseHole, port-updater) plus the Samba file server.

## Samba shares
The samba container mounts only the folders below; the qBittorrent/SABnzbd config dirs and the disk roots are not mounted. `wide links = no` on every share.

| Share | Path in container | Host path | Access | Users |
|---|---|---|---|---|
| `mouse` | `/srv/downloads/torrents` | `/mnt/seagate-red/qbittorrent/downloads` | rw | mouse |
| `mouse` | `/srv/downloads/usenet` | `/mnt/seagate-red/sabnzbd/config/Downloads` | rw | mouse |
| `admin_books` | `/mnt/seagate-black/library` | same | rw | mouse |
| `books` | `/mnt/seagate-black/library` | same | ro | books, mouse |

The Audiobookshelf library is `library/audiobooks` (inside `admin_books`).

Connect: `\\fastpi\mouse`, `smb://fastpi.homelab/mouse` (same for `admin_books`, `books`).

## Web UIs (Holy Grail SSO, LAN + VPN only)
| App | URL | Group | Shell recovery |
|---|---|---|---|
| qBittorrent | https://qbittorrent-audiobooks.holy-grail.ch | `streaming-admins` | `ssh -L 8085:127.0.0.1:8085 fastpi`, login `admin` + `secrets/qbit_pass` |
| SABnzbd | https://sabnzbd-audiobooks.holy-grail.ch | `streaming-admins` | `ssh -L 8090:127.0.0.1:8090 fastpi` (no login) |
| VPN status | https://vpn-status-mouse.holy-grail.ch | `homelab-admins` | `ssh -L 8087:127.0.0.1:8087 fastpi` |

- Traefik reaches gluetun over `traefik_mouse` (internal, Traefik `10.24.25.3`, gluetun `10.24.25.2`). Routes: `Traefik/traefik/dynamic/{qbittorrent,sabnzbd}-audiobooks.yml`.
- qBittorrent: auth bypass only for `10.24.25.3/32` (Options → WebUI), reverse-proxy support off.
- `sabnzbd.ini` (edit only while stopped): `local_ranges = 10.24.32.0/24, 192.168.1.0/24, 10.24.25.3/32, 10.24.5.5/32`, `host_whitelist` += `sabnzbd-audiobooks.holy-grail.ch`, username/password empty.
