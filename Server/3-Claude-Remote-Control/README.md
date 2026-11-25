# 3 - Claude Remote Control, `claude-here`

Claude Code Remote Control sessions on fastpi, used from [claude.ai/code](https://claude.ai/code) and the Claude app. Claude runs here, only the UI is remote. One systemd user instance `claude-remote@<mode>:<folder>` per folder and mode.

```bash
claude-here ~/landingpage            # auto mode (default) → session "fastpi-landingpage"
claude-here ~/Projects batch         # bypass mode, cannot ask → "fastpi-Projects-batch"
claude-here --list                   # name, folder, mode, since, idle
claude-here --stop landingpage       # folder, path or session name
claude-here --done                   # inside a batch session: stop it at the next check
```

## Sessions

| Name | Folder | Mode | Runs |
|---|---|---|---|
| `fastpi` | `~` | auto | always: enabled at boot, `Restart=always`, never auto-stopped, `--stop` refuses |
| `fastpi-batch` | `~/batch` | batch | always, same as `fastpi` |
| `fastpi-<folder>[-batch]` | an allowlist folder | auto / batch | until stopped or auto-stopped; not after a reboot |

| Mode | Permission mode | Extra |
|---|---|---|
| auto | `auto` | – |
| batch | `bypassPermissions` | `--settings /etc/claude-here/batch-settings.json` (root-owned 0644): `permissions.deny: ["AskUserQuestion"]`, the session cannot ask; decisions go into the batch report |

## Rules

- **Allowlist** (`allowlist`, `/*` = every folder directly below): `~/Projects`, `~/landingpage`, `~/notes`, `~/batch`, `~/Documents/development/*`, `~/HomeLab-Unraid-Tower`. Paths are resolved (`readlink -f`), symlinks out of an allowed folder are refused. `~` is only `fastpi`.
- **Trust:** Remote Control refuses an untrusted folder. `claude-here` checks `projects["<repo root>"].hasTrustDialogAccepted` in `~/.claude.json` first; fix: run `claude` once in the folder and accept the dialog. A repo is keyed on its root; a parent's trust does not cover a nested repo.
- **Start check:** a session that restarts within 15 s is stopped again; the hint names `journalctl --user-unit <unit>` (`--user -u` shows nothing here).
- **Auto-stop** (`claude-here-reap.timer`, every 15 min): auto after 8 h without a transcript write (`~/.claude/projects/<folder>/`) and no tool process in its cgroup; batch after `--done` or at 10:00 (the first 10:00 after its start). `fastpi` and `fastpi-batch` are exempt.
- **04:00 restart** (`Server/8-Claude-Scratch/`, "Restart guard"): restarts every running `claude-remote@*` (and a leftover `claude-remote.service`) once no session is busy.
- Memory per instance: `MemoryHigh=1500M`, `MemoryMax=2G` (RAM). Scratch drop-in `claude-remote@.service.d/scratch.conf` (`Server/8-Claude-Scratch/README.md`).

## Files

| File | Installed as |
|---|---|
| `claude-here` | `~/.local/bin/claude-here` (link) |
| `claude-here.bash`, `claude-here.fish` | `~/.local/share/bash-completion/completions/claude-here`, `~/.config/fish/completions/claude-here.fish` (links) |
| `allowlist` | read in place |
| `batch-settings.json` | `/etc/claude-here/batch-settings.json` (root, 0644) |
| `claude-remote@.service`, `claude-here-reap.service/.timer` | `~/.config/systemd/user/` |

```bash
Server/3-Claude-Remote-Control/install.sh             # install / update, starts and stops nothing
Server/3-Claude-Remote-Control/test_claude_here.sh
systemctl --user start 'claude-remote@batch:-home-pi-batch.service' 'claude-remote@auto:-home-pi.service'
journalctl --user-unit 'claude-remote@auto:-home-pi-landingpage.service' -n 20
systemctl --user list-units 'claude-remote@*'
```

## Migration from the old units

A folder can be served by one Remote Control only ("already served … Stop it first"), so each switch has a gap of seconds; switch one at a time, the other entry point stays up. Run each from a session that is not the one being switched, when it is idle.

```bash
# fastpi-batch (ends any chat in the old fastpi-batch)
systemctl --user stop claude-remote-batch.service && systemctl --user start 'claude-remote@batch:-home-pi-batch.service'
# fastpi (ends any chat in the old fastpi)
systemctl --user disable --now claude-remote.service && systemctl --user enable --now 'claude-remote@auto:-home-pi.service'
claude-here --list                    # both listed, then remove claude-remote.service, claude-remote-batch.service, claude-remote.service.d/
```

Needs: linger for `pi` (`loginctl enable-linger pi`, set), so the user units start at boot without a login; a logged-in Claude account (`~/.claude/.credentials.json`).
