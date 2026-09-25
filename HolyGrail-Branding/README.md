# Holy Grail branding

Single source of truth for the Holy Grail icon set. Services **reference** these
files; none of them keeps a copy. Update here, and every service follows.

```
icons/                    the icon set - what services reference
original/                 the pristine downloaded zip, kept for provenance
deploy-to-authentik.sh    re-point authentik after changing icons/
```

---

## Updating the artwork

Three commands, in this order:

```bash
# 1. replace the files (root: this directory is read-only on purpose)
sudo cp /path/to/new-icons/* /home/pi/Projects/HolyGrail-Branding/icons/

# 2. RESTORE READ-ONLY - do not skip this
sudo chmod 444 /home/pi/Projects/HolyGrail-Branding/icons/*

# 3. re-point authentik and restart it
sudo /home/pi/Projects/HolyGrail-Branding/deploy-to-authentik.sh
```

**Step 2 is not optional.** `cp` preserves the *source* file's mode, and a freshly
unzipped set is `644` - so without it the new files land writable and the
protection this directory exists for is silently gone. Verified: copying a 644
file in lands as 644.

Then check it worked:

```bash
ls -l /home/pi/Projects/HolyGrail-Branding/icons/          # expect -r--r--r-- root root
ls -l /home/pi/Projects/Docker/Authentik/data/media/public/ # expect symlinks into icons/
```

and hard-refresh `https://sso.holy-grail.ch` (browsers cache favicons hard).

Finally commit - this directory is inside the `/home/pi/Projects` git repo, and
version history is the real protection:

```bash
cd /home/pi/Projects && git add -A HolyGrail-Branding && git commit
```

### Why a script, when symlinks should be automatic

The symlinks *do* pick up new bytes instantly. The script exists for the two
things that are **not** automatic:

- **Cloudflare caches the login logo for four hours** (`cache-control:
  max-age=14400`). Replacing a file in place therefore appears to do nothing - the
  container serves new bytes while the edge keeps returning the old image
  (`cf-cache-status: HIT`). This already happened once and looked exactly like a
  failed deploy. Filenames embed the file's md5 prefix, so new content means a new
  URL and the cache is bypassed. The script recomputes those names and updates the
  authentik Brand.
- **`logo_data()` is `lru_cache`d**, so the email logo is held in memory until the
  containers restart. The script restarts them.

---

## Read-only by construction

`root:root`, files `444`, directories `555`. Nothing - not `pi`, not a container,
not a stray script - modifies these without `sudo`. Changing the artwork has to be
deliberate.

Because this lives in the git repo, the stronger protection is version history:
any change shows in `git diff` and reverts in one command.

---

## Who consumes these files, and how

### authentik

Two different mechanisms, because authentik treats the two logos differently:

| What | How |
|---|---|
| Login page logo + favicon | `Docker/Authentik/data/media/public/` holds **symlinks** into `icons/` |
| Email logo (every mail) | `icons/android-chrome-192x192.png` bind-mounted to `/web/icons/icon_left_brand.png` in **both** server and worker |

The email logo is not a URL on purpose: authentik's media URLs are **signed and
expire**, so a linked image breaks in any mail older than its token, and Gmail
strips SVG. It rides along as the `cid:logo` attachment that `tasks.py` adds to
every message.

### The symlink trap - read before changing the mounts

A symlink inside a bind mount is resolved in the **container's** namespace, not
the host's. A link pointing at `/home/pi/Projects/...` would dangle inside a
container that only sees `/data`, and the logo would silently 404.

`docker-compose.yaml` works around this by mounting this directory at the **same
absolute path** it has on the host:

```yaml
- /home/pi/Projects/HolyGrail-Branding/icons:/home/pi/Projects/HolyGrail-Branding/icons:ro
```

One target path, valid on both sides. Do not "tidy" this into a shorter mount
point without rewriting every symlink.

### Adding another service

Mount `icons/` read-only, or symlink into it using a path valid inside that
container. **Never copy** - a copy is exactly what this directory exists to
eliminate.

---

## Gotcha: `--force-recreate` wipes authentik's blueprints

Unrelated to branding but it bites during these deploys. `Docker/Authentik/blueprints/`
is **not** mounted; those YAML files are `docker cp`'d into the container's writable
layer, so any `docker compose up -d --force-recreate` or image bump destroys them.
The applied state survives (it lives in Postgres) - only the source files vanish.
Re-copy afterwards:

```bash
cd /home/pi/Projects/Docker/Authentik
for f in blueprints/*.yaml; do docker cp "$f" authentik-server:/blueprints/; done
```

A plain `docker restart` - what `deploy-to-authentik.sh` does - is safe.
