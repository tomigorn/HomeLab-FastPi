# Reduce fastpi RAM (Jenkins on-demand + Authentik web workers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Free ~440 MB of resident RAM on fastpi by making Jenkins on-demand (stopped by default) and dropping Authentik's web server from 2 gunicorn workers to 1, without disrupting the live SSO.

**Architecture:** Jenkins → change `restart: always` to `unless-stopped`, add a start/stop helper, and leave it stopped (frees ~313 MB; builds run only while it's manually started). Authentik → set `AUTHENTIK_WEB__WORKERS=1` in its `.env` (env_file) and recreate `authentik-server` only (frees ~130 MB). Home Assistant is intentionally untouched.

**Tech Stack:** Docker Compose; Jenkins (Java 21, container-aware JVM); Authentik `ghcr.io/goauthentik/server:2026.5.2` (gunicorn web workers).

**Note (infra plan):** Infrastructure, not unit-testable code. Each task = concrete edit → verification command with expected output → commit. Runs on host `fastpi`. Repo root `/home/pi/Projects` (branch `main`). Commit prefix convention `Project: description`. NEVER add an AI co-author trailer. Do NOT push. Stage only listed files; leave unrelated modified files alone. NEVER commit any `.env` (real secrets).

---

## File map
- `Docker/Jenkins/docker-compose.yaml` — `restart: always` → `unless-stopped`
- `Docker/Jenkins/jenkins-ctl.sh` — new start/stop/status helper
- `Docker/Authentik/.env` — add `AUTHENTIK_WEB__WORKERS=1` (gitignored, NOT committed)
- `Docker/Authentik/.env.example` — add `AUTHENTIK_WEB__WORKERS=1` (committed template; non-secret, same value)

---

## Task A: Jenkins on-demand

**Files:**
- Modify: `Docker/Jenkins/docker-compose.yaml`
- Create: `Docker/Jenkins/jenkins-ctl.sh`

- [ ] **Step 1: Change the restart policy.** In `Docker/Jenkins/docker-compose.yaml`, change the jenkins service line `    restart: always` to:

```yaml
    restart: unless-stopped
```
(Leave `mem_limit: 2g` and everything else unchanged — the win is that Jenkins is stopped, and builds still need headroom when it runs.)

- [ ] **Step 2: Create the helper `Docker/Jenkins/jenkins-ctl.sh`:**

```bash
#!/usr/bin/env bash
# Start/stop Jenkins on demand. Jenkins runs on-demand to save ~313 MB RAM;
# automatic webhook/SCM builds only run while it is up. Start it when working
# on LoyaltyCards, stop it when done.
set -euo pipefail
C=jenkins-jdk-21
case "${1:-}" in
  start)  docker start "$C"  && echo "Jenkins starting — wait ~30-60s, then open the Jenkins URL." ;;
  stop)   docker stop  "$C"  && echo "Jenkins stopped (RAM freed)." ;;
  status) docker ps -a --filter "name=^/${C}$" --format 'table {{.Names}}\t{{.Status}}' ;;
  *) echo "usage: $0 {start|stop|status}"; exit 1 ;;
esac
```

- [ ] **Step 3: Make it executable:**

Run: `chmod +x /home/pi/Projects/Docker/Jenkins/jenkins-ctl.sh && echo ok`
Expected: `ok`.

- [ ] **Step 4: Apply the compose change (recreates Jenkins with the new policy):**

Run: `cd /home/pi/Projects/Docker/Jenkins && docker compose up -d`
Expected: `Container jenkins-jdk-21  Started` (recreated), no errors.

- [ ] **Step 5: Stop Jenkins so it is off by default:**

Run: `/home/pi/Projects/Docker/Jenkins/jenkins-ctl.sh stop`
Expected: `Jenkins stopped (RAM freed).`

- [ ] **Step 6: Verify it is stopped and no longer consuming RAM:**

```bash
/home/pi/Projects/Docker/Jenkins/jenkins-ctl.sh status
docker stats --no-stream --format '{{.Name}}' | grep -c '^jenkins-jdk-21$' || true
```
Expected: status shows `Exited`; the grep count is `0` (Jenkins not in the live stats list).

- [ ] **Step 7: Verify on-demand start works, then stop again:**

```bash
/home/pi/Projects/Docker/Jenkins/jenkins-ctl.sh start
sleep 45
docker ps --filter "name=^/jenkins-jdk-21$" --format '{{.Names}} {{.Status}}'
/home/pi/Projects/Docker/Jenkins/jenkins-ctl.sh stop
```
Expected: after start, status shows `Up ... (healthy)` or `Up` (health may still be starting); after stop, it exits. (This proves the on-demand cycle works; final state = stopped.)

- [ ] **Step 8: Commit:**

```bash
cd /home/pi/Projects
git add Docker/Jenkins/docker-compose.yaml Docker/Jenkins/jenkins-ctl.sh
git commit -m "Jenkins: run on-demand (restart unless-stopped) + add start/stop helper"
```

---

## Task B: Authentik — one web worker

**Files:**
- Modify: `Docker/Authentik/.env` (gitignored — NOT committed)
- Modify: `Docker/Authentik/.env.example` (committed template)

- [ ] **Step 1: Add the setting to the real `.env`** (owner-only file). Append to `Docker/Authentik/.env`:

```
# Web: single gunicorn worker (few users) — saves ~130 MB. Worker threads left
# at the recommended default of 2 (single worker replica).
AUTHENTIK_WEB__WORKERS=1
```

- [ ] **Step 2: Mirror the same non-secret line into `.env.example`** (append identical lines to `Docker/Authentik/.env.example` so the template matches).

- [ ] **Step 3: Confirm `.env` is still gitignored (safety):**

Run: `cd /home/pi/Projects && git check-ignore Docker/Authentik/.env`
Expected: prints the path (ignored).

- [ ] **Step 4: Find the compose service name for the server** (container is `authentik-server`; the compose service key may be `server`):

Run: `cd /home/pi/Projects/Docker/Authentik && docker compose config --services`
Expected: a list including the server service (e.g. `server`, `worker`, `postgresql`). Use the server service name in the next step.

- [ ] **Step 5: Recreate ONLY the server so it picks up the new env:**

Run: `cd /home/pi/Projects/Docker/Authentik && docker compose up -d --force-recreate <server-service-name>`
Expected: `Container authentik-server  Started` (recreated). Do NOT recreate `worker` or `postgresql`.

- [ ] **Step 6: Wait for health, then verify the server is healthy (SSO not broken):**

```bash
sleep 40
docker exec authentik-server ak healthcheck && echo "AUTHENTIK_HEALTHY"
```
Expected: ends with `AUTHENTIK_HEALTHY` (the `ak healthcheck` returns success). If it fails, wait another 30s and retry once (startup can take a bit).

- [ ] **Step 7: Verify there is now 1 web worker (not 2) and RAM dropped:**

```bash
docker exec authentik-server sh -c 'ps -eo rss,args | grep -c "[g]unicorn.*worker"' || true
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' authentik-server
```
Expected: the gunicorn worker count is `1` (plus a master process not matched); `authentik-server` memory is meaningfully lower than the previous ~365 MiB (roughly ~230 MiB, may still be settling).

- [ ] **Step 8: Verify the public SSO login still responds through Traefik:**

```bash
curl -s -o /dev/null -w "SSO health HTTP %{http_code}\n" https://sso.holy-grail.ch/-/health/live/
```
Expected: `HTTP 200` (or `204`). If this returns a connection error, re-check Step 6 health before proceeding.

- [ ] **Step 9: Commit (only the template — never `.env`):**

```bash
cd /home/pi/Projects
git add Docker/Authentik/.env.example
git commit -m "Authentik: single web worker (AUTHENTIK_WEB__WORKERS=1) to cut server RAM"
```

---

## Task C: Confirm the net RAM/swap improvement

**Files:** none (verification only)

- [ ] **Step 1: Snapshot host memory and the changed services:**

```bash
echo "=== host memory ==="; free -h | grep -E 'Mem|Swap'
echo "=== jenkins should be ABSENT (stopped); authentik-server should be lower ==="
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -E 'jenkins-jdk-21|authentik-server' || echo "(jenkins not running — expected)"
```
Expected: Jenkins not listed (stopped); `authentik-server` lower than ~365 MiB; `free` shows more available and ideally lower swap than the pre-change baseline (btop snapshot: used 4.78 GiB, free 388 MiB, swap 1.44 GiB). Swap may take time to drain — free/available going up is the immediate signal.

- [ ] **Step 2: Report the before/after numbers to the user** (host free/available/swap, plus the Jenkins-stopped and authentik-server-RAM deltas), and remind them: **start Jenkins with `Docker/Jenkins/jenkins-ctl.sh start` before working on LoyaltyCards, and stop it after.**

---

## Self-review notes
- **Spec coverage:** Jenkins on-demand (Task A: restart policy + helper + stopped-by-default + start/stop test) ✓; Authentik WEB__WORKERS=1 with worker/threads untouched (Task B) ✓; SSO health verified before/after (Task B Steps 6/8) ✓; HA untouched (no task, per decision) ✓; net RAM/swap confirmation (Task C) ✓.
- **Placeholder scan:** none — the one intentional lookup is the compose service name (Task B Step 4 discovers it explicitly before use), not a placeholder.
- **Consistency:** container names used consistently (`jenkins-jdk-21`, `authentik-server`). `.env` never staged; only `.env.example` and non-secret compose/script files committed.
- **Risks:** (1) Jenkins stopped ⇒ no automatic builds while down — documented and surfaced to the user. (2) `mem_limit` left at 2g so builds have headroom when running. (3) Authentik recreate limited to the server; worker/postgres/DB untouched; health checked before declaring success. (4) `docker compose up` in the Jenkins dir recreates only the jenkins service (it's the only app service there).
