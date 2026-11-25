# Docker daemon (fastpi)

| File | Live path | State | Finding |
|---|---|---|---|
| `docker.service.d/require-disks.conf` | `/etc/systemd/system/docker.service.d/require-disks.conf` | installed 2026-11-25, active from the next docker start (next boot) | FB-07 |
| `daemon.json.proposed` | `/etc/docker/daemon.json` | prepared, not applied (needs a docker restart = yes-first) | FB-08 |

## require-disks (FB-07)
- `RequiresMountsFor=/mnt/seagate-red /mnt/seagate-black`: if a Seagate disk does not mount at boot, docker does not start, instead of qBittorrent, Prowlarr, SABnzbd, importer, samba … writing into the empty mountpoint on the NVMe.
- Trade-off: a dead disk then stops every container, the edge too (Traefik, Authentik, cloudflared). Fix from the LAN by SSH: repair the disk or comment it out in `/etc/fstab`, then `sudo systemctl start docker`.
- `systemctl stop 'mnt-seagate\x2dred.mount'` stops docker too (Requires=).
- Install: `Server/10-Docker-Daemon/install.sh` (daemon-reload only, never restarts docker).
- Check: `systemctl show docker -p RequiresMountsFor` → both paths.
- Rollback: `sudo rm /etc/systemd/system/docker.service.d/require-disks.conf && sudo systemctl daemon-reload`.

## DNS fallback (FB-08, prepared)
Every container's upstream DNS is AdGuard only (`192.168.1.2`, itself a container here). While AdGuard is down, containers have no DNS. The proposed file adds the router `192.168.1.1` as second server; nothing else changes.

Apply (attended, restarts the docker daemon; `live-restore` keeps containers running):
```bash
sudo cp -a /etc/docker/daemon.json /etc/docker/daemon.json.bak-2026-11-25
sudo install -m 0644 ~/Projects/Server/10-Docker-Daemon/daemon.json.proposed /etc/docker/daemon.json
sudo systemctl restart docker
docker logs traefik --since 2m 2>&1 | grep -i error
```
Check: a container created or restarted afterwards shows `# ExtServers: [192.168.1.2 192.168.1.1]` in `docker exec <c> cat /etc/resolv.conf`; running containers may keep the old list until then. Traefik (`1.1.1.1 8.8.8.8`) and blackbox-exporter-wan set their own `dns:`.

Rollback: `sudo cp -a /etc/docker/daemon.json.bak-2026-11-25 /etc/docker/daemon.json && sudo systemctl restart docker`.
