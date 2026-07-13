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
Then use the matching recipe. Back up into a gitignored `backups/` dir:

```bash
mkdir -p backups
```

**a) Bind-mounted dir** (`./data`, `./config`) — stop the stack first for a consistent copy:
```bash
docker compose stop
tar czf "backups/data-$(date +%F).tgz" data config 2>/dev/null
```

**b) Named volume:**
```bash
docker run --rm -v <volume_name>:/from -v "$PWD/backups":/to alpine \
  tar czf "/to/<volume_name>-$(date +%F).tgz" -C /from .
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
