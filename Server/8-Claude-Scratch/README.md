# 8 - Claude scratch on disk, restart guard

Claude Code writes per-session scratch to `/tmp/claude-1000/<project>/<session>/`. `/tmp` is a 4 GB tmpfs (RAM): agent clones filled it to 98 % (2026-11-01). The scratch now lives on the NVMe; Claude's paths stay the same.

| Piece | What |
|---|---|
| `claude-scratch.sh` | moves what is in `/tmp/claude-1000` to `/home/pi/.cache/claude-tmp` (0700), then `mount -o bind,nosuid,nodev` over it; gives the owner back `rwx` on `~/.cache` if that was lost (set to 600 by mistake on 2026-11-01); idempotent. Root copy in `/usr/local/libexec/fastpi` |
| `claude-scratch.service` | runs it at boot, before `user@1000` |
| `claude-remote-scratch.conf` | user drop-in `claude-remote.service.d/scratch.conf`: runs it at each claude-remote start, so the first switch happens at the 04:00 idle restart, never under a running session |
| `/etc/tmpfiles.d/claude-scratch.conf` | files older than 7 days deleted at 05:28 (`Server/7-Host-Tuning.md`) |
| `HostTmpFull` | alert at > 80 % `/tmp` (`Docker/grafana/prometheus/rules/host-resources.yml`) |

Large clones still go to `~/.cache/claude-work/<task>`, not the scratch. `~/.cache` is not in the backup.

## Restart guard

`claude-remote` restarts daily at 04:00 to pick up updates and free memory, only when no session is busy (`Server/3-Claude-Remote-Control.md`). A hung `node --test` blocked it 2026-10-28 → 11-02 unnoticed.

| Piece | What |
|---|---|
| `claude-remote-safe-restart` | restarts when idle, else exits 75 (retry in 15 min); writes `claude_remote_restart.prom` (deferral start, reason, first blocking command). Linked as `~/.local/bin/claude-remote-safe-restart` |
| `claude-remote-restart.service` / `.timer` | user units, 04:00 daily, retry every 15 min while busy |
| `ClaudeRemoteRestartBlocked` | Telegram when deferred > 1 day (`Docker/grafana/prometheus/rules/claude-remote.yml`) |

```bash
Server/8-Claude-Scratch/install.sh            # install / update
Server/8-Claude-Scratch/test_claude_scratch.sh
Server/8-Claude-Scratch/test_claude_remote_safe_restart.sh
DRY_RUN=1 claude-remote-safe-restart           # decision only, no restart, no metrics
journalctl --user -u claude-remote-restart -n 5
findmnt /tmp/claude-1000; df -h /tmp           # check: bind mount from nvme0n1p2
sudo umount /tmp/claude-1000                   # undo now (files stay in ~/.cache/claude-tmp); disable: sudo systemctl disable claude-scratch.service + remove the drop-in
```
