# Beefy power-management — adversarial review (2026-06-26)

Review of the two-part system that lets **beefy** sleep (S5) when idle and wake on
demand via WoL, with **fastpi** as the always-on edge. Scope: the Beefy-Waker gate +
manual page (fastpi) and the `beefy-idle-watcher` daemon (beefy). Done by a review
agent; findings below were spot-verified against the code/config.

**Components reviewed:** `Beefy-Waker/app/waker.py`, `docker-compose.yaml`,
`Traefik/.../dynamic/beefy-wake.yml`, `beefy-wol.yml`; `8-Idle-Watcher/beefy_idle_watcher.py`,
its unit + design doc. idle-watcher = **v1.1.0 (armed)**, Beefy-Waker = **v1.0.0**.

## Prioritized findings

1. **Cold-boot / shutdown race when gating on port 22** *(High, future)* — the gate's
   default probe is `:22`, which sshd opens early in boot and keeps open during
   shutdown. So `/gate` can report "up" while the actual service is still down (boot) or
   already going away (shutdown) → Traefik proxies to a dead port → a confusing 502
   instead of the "waking" page. **Today this is latent** — `beefy-wake` is defined but
   not attached to any router yet. **When you attach it to a real beefy route, use a
   per-service `?port=<service-port>` probe**, not host:22.

2. **Raw `:9001` bypasses the Traefik `ipAllowList`** *(Medium)* — the waker binds
   `0.0.0.0:9001` on host networking. The `beefy-wol` *route* is IP-restricted, but the
   raw port is not, so any host that can reach `fastpi:9001` (LAN + docker bridges; **not**
   the internet — it isn't in the Cloudflare tunnel) can trigger unauthenticated WoL and
   port-probe beefy. **Recommend:** bind to the LAN IP (`192.168.1.2:9001`) or add a host
   firewall rule limiting `:9001` to LAN/bridge ranges.

3. **Waker is a single point of failure, with no healthcheck** *(Medium, best-practice)* —
   all automatic wakes flow through one process. `restart: unless-stopped` recovers a
   *crash* but not a *hung* process. **Recommend:** add a Docker `healthcheck` (e.g.
   `GET /status`) so a wedged gate is restarted. Manual `wakeonlan` from fastpi remains the
   out-of-band fallback.

4. **Sleep mid-`apt`/unattended job** *(Medium, highest-consequence)* — a long job below
   all thresholds (CPU<15% / net<200kB/s / disk<2000kB/s) with no SSH and no inbound conn
   reads as idle → real poweroff mid-job. Powering off mid-`apt`/`dpkg` can corrupt the
   package DB. **Recommend:** an `apt` `DPkg::Pre-Invoke`/`Post-Invoke` hook that touches/
   removes `/run/beefy-keep-awake`, and the habit of `sudo touch /run/beefy-keep-awake`
   before any detached job. (The "idle seeding/download" case is scoped out by design.)

5. **`DATA_DISKS=sda,sdb,sdc` are hardcoded basenames** *(Medium, verify)* — if beefy's disk
   layout differs (NVMe `nvme0n1`, mergerfs/USB reorder), the disk probe silently watches
   the wrong devices → always 0 kB/s → the disk signal is blind. **Verify** the basenames
   match beefy's real data disks (`lsblk`).

6. **Doc/code discrepancy: no second confirmation before poweroff** *(Medium)* — the design
   doc (`8-Idle-Watcher.md` "The loop" step 3) promises *"re-evaluate once more, and if still
   idle"* before powering off; the code powers off on the first cycle where
   `not busy and should_sleep(...)`. The 15-min **continuous**-idle requirement already gives
   strong confidence (any busy sample resets the timer), so impact is small — but for a
   destructive action, reconcile: **either implement the re-check, or fix the doc.**

7. **HTTP server has no thread cap / request timeout** *(Low/Medium)* — `ThreadingHTTPServer`
   + `mem_limit: 64m`: a burst of slow/never-closing clients (e.g. a wake-storm) spawns
   unbounded threads and could OOM-restart the gate exactly when it's needed. **Recommend:**
   a thread cap and a handler `timeout`.

8. **"Never sleeps" from a persistent service connection** *(Medium)* — `conns>0` ⇒ busy with
   no duration/throughput qualifier. A keepalive monitor (Uptime-Kuma, Prometheus blackbox),
   a left-open browser tab, or an idle WebSocket on a service port pins beefy awake forever.
   **Document**; optionally count only connections with recent throughput, or exclude monitor
   source IPs.

9. **Probe regexes are upgrade-brittle** *(Low)* — interactive-SSH (`sshd-session: …@pts/N`)
   and VS Code (`.vscode-server/.../server-main.js`) detection depends on process-title /
   path conventions that can change across OpenSSH / VS Code releases, silently disabling a
   probe. **Recommend:** a startup self-test or periodic raw-match logging so a break is
   visible.

10. **Minor:** `/history` `BEEFY_SSH_USER` must match the user whose `authorized_keys` holds
    the forced-command key (else `/history` silently 503s — panel degrades gracefully). The
    gate is still an *arbitrary-port* probe oracle against beefy (low impact, LAN-only).

## Done well — do NOT change

- **Fail-busy/fail-closed** throughout the watcher (`_run()` → `None` on failure → BUSY; whole
  cycle wrapped to treat any exception as BUSY). Correct safety direction for a poweroff daemon.
- **Monotonic clock** for idle/rate deltas (v1.1.0) — immune to NTP / `set-time`.
- **Counter-reset clamping** (`max(0, …)`) on net/disk deltas.
- **Port 22 excluded** from the inbound-conn probe.
- **`/wake` POST-only**; **`/gate` rejects `?host=`**, range-checks `?port=`, never crashes on bad input.
- **`/history` SSH lockdown** (forced command, BatchMode, pinned known_hosts, no stderr leak).
- **Non-root container**, `cap_drop: ALL`, `no-new-privileges`, read-only mounts.
- **DRY_RUN-first rollout** — validated "would sleep" timing before arming.

## Status of fixes (updated 2026-06-26)

- **#2 — bind `:9001` to LAN IP** — **DONE** (`WAKER_BIND=192.168.1.2` in `.env`; `127.0.0.1`
  now refused, Traefik path verified 200).
- **#3 — Docker healthcheck** — **DONE** (`GET /status`; reports healthy. Observability only —
  plain compose doesn't auto-restart on unhealthy; `restart:unless-stopped` covers crashes/OOM).
- **#7 — request timeout / thread guard** — **DONE** (`Handler.timeout = 10`).
- **#5 — DATA_DISKS basenames** — **VERIFIED OK** (`lsblk`: sda/sdb = 7.3T, sdc = 27.3T data
  disks; nvme0n1 = 931.5G OS, correctly excluded).
- **#6 — doc vs code (second confirmation)** — **doc aligned to code**; an actual second-sample
  re-check remains a possible future enhancement.
- **#4 — apt inhibit hook** — **applying on beefy** (`/etc/apt/apt.conf.d/99-beefy-keep-awake`).
- **#1 — `?port=` gating** — **deferred** until a beefy service is attached to `beefy-wake`.
- **#8 / #9 / #10** — documented; monitor (persistent-conn pinning, regex brittleness, ssh-user).
