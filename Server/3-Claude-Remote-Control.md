# Claude Code Remote Control (always-on)

This Pi runs **Claude Code Remote Control** as a persistent background service, so the
host is always reachable from **[claude.ai/code](https://claude.ai/code)** and the
**Claude mobile app** without touching the terminal.

`claude remote-control` runs a persistent server that registers the local machine with
your Claude account. Sessions started from the web/phone run **here, on the Pi**, with
full access to the local filesystem, tools and MCP servers — only the UI is remote.
The session shows up in the session list named **`fastpi`** (the `--name`).

> Requires being logged in with a Claude account that has a subscription. Auth lives in
> `~/.claude/.credentials.json` and is refreshed by the CLI.

---

## How to use it

1. Open **[claude.ai/code](https://claude.ai/code)** (or the Claude mobile app) on any device.
2. Pick the session named **`fastpi`** from the session list.
3. Type — it runs in the Pi's home directory. New sessions are created in the same
   directory (capacity 32). The service keeps one session pre-created so there's always
   somewhere to type.

Nothing to copy/paste per session — as long as the service is running, `fastpi` is
listed automatically.

---

## The service

systemd **user** service (not system-wide), so it runs as `pi` with the user's
environment and Claude credentials.

**Unit file:** `~/.config/systemd/user/claude-remote.service`

```ini
[Unit]
Description=Claude Code Remote Control (drive local sessions from claude.ai/code & the Claude mobile app)
# Never permanently give up: always keep retrying (no start-rate limit) so a
# transient crash-loop (auth/network blip) can't leave the service dead until reboot.
StartLimitIntervalSec=0

[Service]
Type=simple

# The directory Claude works in. Change this to a specific project/repo if you prefer.
WorkingDirectory=%h

# Stable, fnm-independent PATH (the /run/user fnm multishell path is per-shell and must NOT be used here)
Environment=HOME=%h
Environment=PATH=%h/.local/bin:%h/.local/share/fnm/node-versions/v24.14.1/installation/bin:/usr/local/bin:/usr/bin:/bin

ExecStart=%h/.local/bin/claude remote-control --name fastpi --permission-mode auto

# Resilience: come back from crashes, network blips, transient auth hiccups
Restart=always
RestartSec=10

# Memory ceiling so a long-running/leaking session can't take the Pi down.
# MemoryHigh throttles first (soft), MemoryMax is the hard kill line.
MemoryHigh=1500M
MemoryMax=2G

[Install]
WantedBy=default.target
```

### What makes it "always available"

- **`enabled`** — symlinked into `default.target.wants`, so it starts at user login / boot.
- **Linger enabled for `pi`** (`/var/lib/systemd/linger/pi`) — the user manager starts at
  **boot without anyone logging in**, so the service is up after a reboot/power cycle.
  This is the key piece; a user service without linger only runs while you're logged in.
- **`Restart=always` / `RestartSec=10`** — auto-recovers from crashes, network blips or
  transient auth hiccups.
- **`StartLimitIntervalSec=0`** — no start-rate limit, so a transient crash-loop can't
  trip systemd's "give up" threshold and leave the service dead until the next reboot.
- **Memory ceiling (`MemoryHigh=1500M` / `MemoryMax=2G`)** — long-running Claude sessions
  accumulate memory; this throttles then hard-caps the cgroup so a leak can't OOM the Pi.
- **Nightly restart timer** (see below) — reclaims memory, refreshes auth, and picks up
  any manually-installed `claude` update once a day.
- **Pinned PATH** — uses the absolute fnm node path, not the per-shell
  `/run/user/.../fnm_multishells` path which doesn't exist outside an interactive shell.

### Nightly restart timer

A oneshot service + timer restart Remote Control every night at 04:00. This is the
standard "just restart it" mitigation for the three long-uptime risks above (memory
growth, silent OAuth-refresh stalls, running a stale binary after a manual update).

**`~/.config/systemd/user/claude-remote-restart.service`**

```ini
[Unit]
Description=Nightly restart of Claude Code Remote Control (reclaim memory, refresh auth, pick up updates)
Wants=claude-remote.service

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl --user restart claude-remote.service
```

**`~/.config/systemd/user/claude-remote-restart.timer`**

```ini
[Unit]
Description=Nightly restart timer for Claude Code Remote Control

[Timer]
# Every day at 04:00 local time; Persistent catches up if the Pi was off at 04:00.
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable + inspect:

```bash
systemctl --user daemon-reload
systemctl --user enable --now claude-remote-restart.timer
systemctl --user list-timers claude-remote-restart.timer
```

---

## Managing it

```bash
# Status / is it running?
systemctl --user status claude-remote.service

# Live logs (includes the session URL + QR on (re)start)
journalctl --user -u claude-remote.service -f

# Restart / stop / start
systemctl --user restart claude-remote.service
systemctl --user stop claude-remote.service
systemctl --user start claude-remote.service

# Disable autostart (keep the file) / re-enable
systemctl --user disable claude-remote.service
systemctl --user enable claude-remote.service

# After editing the unit file
systemctl --user daemon-reload
systemctl --user restart claude-remote.service
```

Linger (only needed once; already set):

```bash
loginctl enable-linger pi      # survive reboots without login
loginctl show-user pi | grep Linger
```

---

## Security note — permission mode

The service currently runs with **`--permission-mode auto`**. Other modes you can set on
the `ExecStart` line (then daemon-reload + restart):

```ini
# Safest — prompts before edits/commands (approve from web/phone)
ExecStart=%h/.local/bin/claude remote-control --name fastpi --permission-mode default

# Auto-accept file edits, prompt for everything else
ExecStart=%h/.local/bin/claude remote-control --name fastpi --permission-mode acceptEdits

# No prompts at all — full unattended control of the Pi (convenient, higher risk)
ExecStart=%h/.local/bin/claude remote-control --name fastpi --permission-mode bypassPermissions
```

```bash
systemctl --user daemon-reload && systemctl --user restart claude-remote.service
```

Because this grants control of the host, keep the Claude account locked down (strong
auth + MFA).

---

## Recreating from scratch

```bash
mkdir -p ~/.config/systemd/user
# write the three unit files above:
#   ~/.config/systemd/user/claude-remote.service
#   ~/.config/systemd/user/claude-remote-restart.service
#   ~/.config/systemd/user/claude-remote-restart.timer
loginctl enable-linger pi
systemctl --user daemon-reload
systemctl --user enable --now claude-remote.service
systemctl --user enable --now claude-remote-restart.timer
systemctl --user status claude-remote.service
systemctl --user list-timers claude-remote-restart.timer
```
