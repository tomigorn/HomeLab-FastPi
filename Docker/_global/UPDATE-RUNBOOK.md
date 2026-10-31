# Docker Update Runbook

**Cup tells you _what_ is outdated. It does not tell you how to update safely.**
The `docker pull …` string Cup shows you is not enough:

- Pulling an image only downloads it — your running container keeps the **old** version
  until you bump the tag and recreate it.
- It does **no backup**. Many apps run **one-way data/schema migrations** on first start of
  a new version. After that, the old image often can't read the data anymore — so "just roll
  the tag back" won't save you. You must back up **before** recreating.

Follow this per project, **one at a time**.

---

## Golden rules

1. **Read the release notes first** — especially for a **Major** update (Cup labels the type).
   Look for breaking changes, required config edits, or mandatory intermediate versions.
2. **Back up data _before_ `up -d`.** Migrations are frequently irreversible.
3. **One project at a time. Verify before moving to the next.** Don't mass-update all 94 at once —
   batch the low-risk patches, and treat each **Major** individually.
4. **Rollback plan = old tag + data backup.** Know both before you start.

---

## Procedure

Work inside the project folder, e.g. `cd /home/pi/Projects/Docker/<Project>`.

### 0. Triage (in Cup)
- Note the update **type**: patch / minor / **major**.
  - Patch/minor → usually safe, still verify.
  - **Major** → read the upstream upgrade guide before doing anything.

### 1. Pre-flight
```bash
cd /home/pi/Projects/Docker/<Project>

# Config rollback is git — commit any local changes so you have a clean point to return to.
git add -A && git commit -m "<Project>: pre-update snapshot"     # skip if nothing changed

# Record the CURRENT working tag — this is your rollback target.
grep _IMAGE_TAG .env        # e.g. CUP_IMAGE_TAG=v3.5.1
```

### 2. Back up data  ← the part Cup skips
First figure out what's stateful (bind-mounts like `./data` / `./config`, named volumes, or a DB).
Then use the matching recipe. Back up into a gitignored `backups/` dir, owner-only (backups hold DBs and secrets; `umask 077` makes every file below 0600):

```bash
umask 077; mkdir -p backups && chmod 700 backups
```

**a) Bind-mounted dir** (`./data`, `./config`) — stop the stack first for a consistent copy:
```bash
docker compose stop
tar czf "backups/data-$(date +%F).tgz" data config 2>/dev/null
```

**b) Named volume:**
```bash
docker run --rm -v <volume_name>:/from:ro alpine tar czf - -C /from . > "backups/<volume_name>-$(date +%F).tgz"   # written by you, not by root in the container
```

**c) Database — do a real dump, not a file copy of a live DB:**
```bash
# Postgres (e.g. Authentik):
docker compose exec <db_service> pg_dump -U <user> <db> > "backups/db-$(date +%F).sql"

# SQLite (e.g. many apps): stop first, then copy the file
docker compose stop
cp path/to/app.db "backups/app-$(date +%F).db"
```

> Optional: push `backups/` to the beefy storage tier for anything you can't afford to lose.

### 3. Update
```bash
# Bump the pinned tag to the new version Cup showed you:
#   edit .env  →  <PROJECT>_IMAGE_TAG=<new-version>
docker compose pull
docker compose up -d
```
> Note: `docker compose pull` + `up -d` is what actually upgrades the container.
> The bare `docker pull …` that Cup prints does **not** switch your running container.

### 4. Verify
```bash
docker compose ps                       # container healthy / up?
docker compose logs -f --tail=100       # watch for migration errors or a crash loop
```
Then open the app's UI / endpoint and exercise a **real** action (log in, load a page, etc.).

Then check the project's customizations ([CUSTOMIZATIONS.md](../CUSTOMIZATIONS.md)); a FAIL means fix or roll back:
```bash
_global/scripts/post-update-check.sh <Project>    # compose dir name; `all` for everything
```

### 5. Rollback (if broken)
```bash
# a) Revert the version: set <PROJECT>_IMAGE_TAG back to the OLD tag in .env, then:
docker compose up -d

# b) If the new version already migrated the data (old image won't start / errors):
docker compose down
# restore the backup from step 2 (untar the dir, or restore the DB dump), then:
docker compose up -d      # on the OLD tag
```

### 6. Record
Update `_global/checklist.md` for this project: **Image / Tag Version** and
**my update performed date**. (These columns are yours to fill in.)

---

## Highest-risk updates (extra care)

- **Any Major version bump** (Cup's red ↑). Breaking changes are expected — read the upgrade guide.
- **Stateful / stored-data apps:** Vault, Authentik (+ Postgres), Home-Assistant, Bitwarden/Vaultwarden,
  Grafana, LoyaltyCards. These can migrate storage irreversibly — **never skip the backup**, and for
  DBs always take a dump.
- **Chained majors:** some apps require going 1.x → 2.x → 3.x in order. Check before you leapfrog.

---

## Per-project setup note

Add `backups/` to each project's `.gitignore` so dumps/snapshots aren't committed:

```gitignore
backups/
```

---

## Scripted variant (`_global/scripts/update-project.sh`)

The steps above, automated for the routine cases (first used for the 2026-10-17
CVE round, 20 projects, 1 automatic rollback):

```bash
_global/scripts/update-project.sh <compose-dir> snapshot        # BEFORE you edit a tag/digest in compose or .env
# edit the image ref, then:
_global/scripts/update-project.sh <compose-dir> pull|build|recreate [backup paths...]
```

Rollback safety:

| What | How |
|---|---|
| compose + `.env` | snapshot of the files that define the image refs (`snapshot` mode before your edit, used within 12 h; else taken at the start) -> `~/backups/pre-update/<date>/<project>/compose-snapshot-*`; the rollback restores them |
| old image | tagged `rollback.invalid/<repo>:<date>-<project>` before any pull/build/recreate, so `docker image prune` cannot take it; the newest `ROLLBACK_KEEP` (3) per repo and project stay; `image-cleanup.sh` keeps them 14 days (see Rollback tags) |
| tag ref | old tag re-pointed at the old image id |
| digest ref (`@sha256:`) | restored compose names the old digest again; never re-tagged |
| edited without `snapshot` | compose still names the new ref: the service is pinned to its rollback tag (`rollback-override.yaml`) and a `WARN` says to revert the edit, else the next `up -d` moves it |
| data (backup paths given) | a missing path aborts before the pull; a failed or empty tar aborts before `up -d` (old tags re-pointed, stopped containers started again, exit 2). A rollback after an image change stops the services and restores this run's backups first (the new image may have migrated them one way); the failed data stays as `<path>.failed-update-<time>` / `vol-<name>.failed-update-<time>.tgz`, delete it once the old version is fine. Restore fails: services stay stopped, exit 3, restore by hand |

It snapshots the running image IDs, pulls (or `build --pull`s, or just recreates on an already-pulled image), then, only when backup paths are given, stops the services and tars the given bind dirs / `vol:<name>` volumes cold into `~/backups/pre-update/<date>/<project>/` (owner-only: `umask 077`, dirs 0700, files 0600; a live Postgres/SQLite/InfluxDB copy can be torn), starts them on the new image, waits 45 s, and requires every
container to be running (and healthy if it has a healthcheck) with 0 restarts —
otherwise it restores compose/`.env`, re-tags the old image IDs and recreates on them (automatic rollback, table above).
A container whose tag already points at a newer image (another project sharing the tag pulled it first) is force-recreated (`stale :` line); plain `up -d` keeps it.
`SERVICES="a b"` limits the pull/build and the recreate (`--no-deps`) to those services, a forced-drill rollback too; the verify still covers every container of the project (keep gluetun out of it).
For Traefik it first runs `Traefik/scripts/traefik-plugin-test.sh <new tag>` and stops, unchanged, if the local plugins fail on the new version.
`CHECK='<shell command>'` adds a functional check after the container checks (retried 6 × 10 s; it runs inside the project folder, so use absolute paths; for the Authentik canary use `CHECK='sleep 35; bash /home/pi/Projects/Docker/Authentik/scripts/canary-verify.sh'`, because a retry within the same 30 s TOTP window is refused); `TEST_FORCE_FAIL=1` forces the rollback (drill). The rollback recreates only the changed or down services and is verified itself: exit 0 ok, 1 rolled back, 2 nothing changed (no project name, backup failed), 3 rollback or data restore did not verify.
After the container checks and CHECK it runs `post-update-check.sh <dir name>` when `post-update.d/<dir name>.sh` exists (registry: [CUSTOMIZATIONS.md](../CUSTOMIZATIONS.md)) and rolls back when a customization is missing; `POST_CHECK=0` skips it.
It does NOT read release notes for you: majors and the stateful apps listed above
still get the manual treatment.

### Rollback tags

| Rule | Why |
|---|---|
| One namespace: `rollback.invalid/<repo>:<date>-<project>` (`:` in a registry port becomes `-`, e.g. `rollback.invalid/lscr.io/linuxserver/prowlarr:2026-10-29-mouse`) | Cup reads only the first tag of an image and exits on a tag with no remote versions (crash loop, 2026-10-29); one prefix excludes them all |
| `.invalid` registry host, not `local/rollback/` | Docker lists tags sorted by full name; `rollback.invalid/` sorts after `docker.io/`, `ghcr.io/`, `lscr.io/`, `quay.io/`, so an in-use image keeps its real tag first in Cup. `.invalid` never resolves: no accidental push or pull |
| Cup: `images.exclude: ["rollback.invalid/"]` + `registries: {"rollback.invalid": {"ignore": true}}` in `Cup/cup.json`, `Cup/cup-agent.json`, beefy `Cup-Agent/cup.json` | Cup 3.6 `exclude` is a prefix match on the reference; the registry ignore stops its auth probe of the fake host (3 retries per start) |
| Manual tags with `rollback` elsewhere in the name (`avatar-picker:v1.13.0-rollback`, `traefik-rollback:v3.7.16-20261027`) | kept forever by `image-cleanup.sh`; give them no registry digest or exclude them in Cup |
| Old `<repo>:rollback-*` tags | `scripts/migrate-rollback-tags.sh [--dry-run]` re-tags them (tags only, never images; a tag a container runs by name is left alone) |

Check: `post-update-check.sh Cup` (beefy: `Cup-Agent`): `cup.exclude-rollback`, `cup.rollback-tags-last`, `cup.no-crash-loop`.

---

## Automatically updated: tiered nightly run

`scripts/auto_update.py` (daily 03:10, `auto-update.timer`) moves the digest behind the tags in the repo for the `auto` stacks in `auto-update.conf` (24 h cool-down, `CHECK` per stack, rollback) and reports the rest with the command. Tiers, switches, risks: `Server/4-Security-Monitoring/auto-updates.md`. Custom builds are never pulled: the first-Monday digest lists them, rebuild with `update-project.sh <dir> build`.

## Automatically updated: CrowdSec

CrowdSec is the one project that updates itself (`Docker/CrowdSec/scripts/crowdsec-autoupdate.sh`,
daily 05:07, `crowdsec-autoupdate.timer`). It follows this runbook (backup of both volumes ->
pull -> recreate -> verify -> rollback), with CrowdSec-specific checks (LAPI, bouncer re-pull,
a test ban enforced by Traefik, public route) and a rollback that **also restores the volumes**.
Patch/minor only; a new major is reported to Telegram and left for you. Hub content
(parsers/scenarios) is upgraded the same night.

- **Pause:** `CROWDSEC_AUTOUPDATE=off` in `Docker/CrowdSec/.env`, or
  `sudo systemctl disable --now crowdsec-autoupdate.timer`.
- **After an auto-update:** commit the bumped `Docker/CrowdSec/.env.example`.
- **After a rollback:** the bad version sits in `/var/lib/crowdsec-autoupdate/bad_versions` and is
  skipped until a newer release exists.
- Safe because the Traefik bouncer fails **open** (stream mode, `updateMaxFailure: -1`): a CrowdSec
  restart or a failed update never takes the public edge down.

Details: `Docker/CrowdSec/README.md` -> "Auto-update".
