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
