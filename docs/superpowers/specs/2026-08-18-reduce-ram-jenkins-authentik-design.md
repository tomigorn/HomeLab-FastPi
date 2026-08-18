# Reduce fastpi RAM: Jenkins on-demand + Authentik web workers

**Date:** 2026-08-18
**Status:** Design approved, ready for planning

## Problem
After freeing ~950 MB by fixing clamav, fastpi is still memory-tight: `btop` showed 4.78 GiB used, 388 MiB free (5%), swap 72% (1.44 GiB). The remaining large resident consumers are Home Assistant (~550 MB), Jenkins (~313 MB), and Authentik (server ~365 MB + worker ~274 MB). Goal: cut resident RAM/swap pressure with low risk to the services the user actually relies on.

## Decisions (from the user)
- **Jenkins → on-demand.** It has exactly one job (LoyaltyCards CI) and is used rarely. Don't run it 24/7.
- **Authentik → minimize** the web side (it's the live SSO — must stay up, but a few users don't need 2 web workers).
- **Home Assistant → leave alone.** Recorder tuning saves ~0–30 MB RAM (its cost is disk/IO, not RAM); the only real HA RAM lever is trimming integrations, which is risky. Not worth it for the RAM goal.

## Expected savings (honest)
- Jenkins stopped: **−~313 MB** whenever idle (the large majority of the time).
- Authentik `AUTHENTIK_WEB__WORKERS` 2→1: **~−130 MB** (one fewer gunicorn worker process).
- HA: 0.
- Combined, with Jenkins idle: **~440 MB** back — enough to visibly ease swap.

---

## Component A — Jenkins on-demand

### Current
`Docker/Jenkins/docker-compose.yaml`: `restart: always`, `mem_limit: 2g`, no `-Xmx` (Java 21 is container-aware, so heap auto-sizes to ~25% of mem_limit). Exposed via Traefik at the Jenkins domain. One job: "LoyaltyCards Multibranch Pipeline".

### Design
- Change `restart: always` → **`restart: unless-stopped`** so a manual stop persists across Docker/host restarts.
- Recreate the container (applies the policy), then **stop it** so it is down by default (frees ~313 MB).
- Add a small helper `Docker/Jenkins/jenkins-ctl.sh` with `start` / `stop` / `status` for convenience (`docker start|stop|ps jenkins-jdk-21`).
- Leave `mem_limit: 2g` unchanged so builds have headroom when Jenkins IS running (the win is that it's stopped, not a smaller running footprint; shrinking the limit risks build OOMs).

### Consequence to document
While Jenkins is stopped, its Traefik route returns 502 and **automatic webhook/SCM builds do not run**. Start Jenkins (`jenkins-ctl.sh start`) when actively working on LoyaltyCards, stop it (`jenkins-ctl.sh stop`) when done.

### Test
- After stop: `docker ps` shows Jenkins not running; `docker stats` no longer lists it; it stays down after `docker restart` of the daemon is NOT required to verify — just confirm the container status is `exited` and RAM is freed.
- `jenkins-ctl.sh start` brings it back healthy (Traefik route serves the UI); `jenkins-ctl.sh stop` returns it to stopped.

### Optional future (not now)
Auto-start-on-request via a Traefik on-demand starter (like the existing beefy-wake pattern). Deferred — manual on-demand is simpler and fits "rarely used".

---

## Component B — Authentik: one web worker

### Current
`Docker/Authentik/docker-compose.yaml` runs `authentik-server` (command: server) and `authentik-worker` (command: worker), both from `ghcr.io/goauthentik/server:2026.5.2`, config via `.env` (env_file). No worker/web tuning set, so defaults apply: `AUTHENTIK_WEB__WORKERS=2`, `AUTHENTIK_WORKER__PROCESSES=1`, `AUTHENTIK_WORKER__THREADS=2`.

### Design
- Add **`AUTHENTIK_WEB__WORKERS=1`** to Authentik `.env` (and mirror the non-secret line into `.env.example`). This drops the server from 2 gunicorn workers to 1.
- **Do NOT** reduce `AUTHENTIK_WORKER__THREADS` below 2: docs advise ≥2 threads on a single worker replica (we have one), and threads share process memory so the RAM gain would be negligible anyway. Leave `PROCESSES=1`, `THREADS=2` at defaults.
- Recreate `authentik-server` only (worker unchanged).

### Risk / test
- Low risk for a handful of users; 1 web worker just means less parallel-request headroom.
- Verify the SSO stays healthy after recreate: `authentik-server` health endpoints `/-/health/live/` and `/-/health/ready/` return 200, and the public login page at the SSO host loads. Confirm `authentik-server` RAM dropped (~365 MB → ~230 MB).

### Non-goals
- Don't touch the worker, postgres, or the Authentik data/DB.

---

## Home Assistant — no change
Documented decision: left as-is (~550 MB). Its RAM is dominated by the Python core + `default_config` integrations, not the recorder. Revisit only if the user later wants integration trimming.

## Success criteria
- Jenkins is stopped by default and no longer in `docker stats`; a helper starts/stops it cleanly; builds work when it's running.
- Authentik SSO still logs in with `WEB__WORKERS=1`; `authentik-server` RAM is lower.
- Free RAM up and swap usage down versus the pre-change `btop` snapshot.
- Configs committed (no secrets); `.env` never committed.
