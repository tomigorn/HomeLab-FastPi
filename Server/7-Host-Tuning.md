# Host tuning (fastpi)

| Setting | Value | File | Why |
|---|---|---|---|
| `vm.swappiness` | 30 (default 60) | `/etc/sysctl.d/99-swappiness.conf` | 8 GB RAM, 10 GB swap file on NVMe: keep app memory in RAM, drop page cache first (2026-10-29) |
| Agent scratch cleanup | files older than 7 days | `/etc/tmpfiles.d/claude-scratch.conf` (`e /tmp/claude-1000 - - - 7d`) | `/tmp` is a 4 GB tmpfs backed by RAM/swap; old agent scratch filled it to 90 % (2026-10-29). Runs with `systemd-tmpfiles-clean` (05:28) |
| SCTP module disabled | `install sctp /bin/false` + `blacklist sctp` | `/etc/modprobe.d/disable-sctp.conf` | unused protocol, unprivileged autoload on `socket(…, IPPROTO_SCTP)`, past kernel CVEs (Lynis NETW-3200, 2026-10-31); dccp, rds, tipc are not built for this kernel |
| Authentik memory limits | server 1g, worker 1g, postgresql 512m | `Docker/Authentik/docker-compose.yaml` | had none; set live with `docker update` (no restart) on 2026-10-29 |

Apply on a fresh install:
```bash
echo 'vm.swappiness = 30' | sudo tee /etc/sysctl.d/99-swappiness.conf && sudo sysctl --system
echo 'e /tmp/claude-1000 - - - 7d' | sudo tee /etc/tmpfiles.d/claude-scratch.conf
printf 'install sctp /bin/false\nblacklist sctp\n' | sudo tee /etc/modprobe.d/disable-sctp.conf
```

Check: `cat /proc/sys/vm/swappiness` → 30 · `python3 -c 'import socket; socket.socket(2,1,132)'` → Protocol not supported · `free -h` · `df -h /tmp`
