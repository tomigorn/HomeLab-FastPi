# Holy Grail branding

Single source of truth for the Holy Grail icon set. Every service references the
files here rather than keeping its own copy, so updating them here updates
everything.

```
icons/     the icon set - this is what services reference
original/  the pristine downloaded zip, kept for provenance
deploy-to-authentik.sh   re-point authentik after changing icons/
```

## Read-only on purpose

Everything is `root:root`, files `444`, directories `555`. Nothing - not the `pi`
user, not a container, not a stray script - can modify or delete these without
`sudo`. To change the artwork you must deliberately reach for root.

This directory sits inside the `/home/pi/Projects` git repo, so the real
protection is version history: any change is visible in `git diff` and revertible.

## How authentik consumes it

Two different mechanisms, because authentik treats the two logos differently:

| What | How |
|---|---|
| Login page logo + favicon | `Docker/Authentik/data/media/public/` holds **symlinks** into `icons/` |
| Email logo (every mail) | `icons/android-chrome-192x192.png` is bind-mounted to `/web/icons/icon_left_brand.png` in **both** the server and worker |

### The symlink trap

A symlink inside a bind mount is resolved in the **container's** namespace, not
the host's. A link pointing at `/home/pi/Projects/...` would therefore dangle
inside the container, which only sees `/data`.

`docker-compose.yaml` works around this by mounting this directory at the **same
absolute path** it has on the host:

```yaml
- /home/pi/Projects/HolyGrail-Branding/icons:/home/pi/Projects/HolyGrail-Branding/icons:ro
```

One target path, valid on both sides. Do not "tidy" that into a shorter mount
point without also rewriting every symlink.

## Updating the artwork

```bash
sudo cp new-icons/* /home/pi/Projects/HolyGrail-Branding/icons/
sudo chmod 444 /home/pi/Projects/HolyGrail-Branding/icons/*
sudo /home/pi/Projects/HolyGrail-Branding/deploy-to-authentik.sh
```

The symlinks pick up new bytes immediately. The script exists for the two things
that are *not* automatic:

- **Cloudflare** caches the login logo for four hours (`max-age=14400`), so
  replacing a file in place appears to do nothing. Filenames embed the file's md5
  prefix, so new content means a new URL and the cache is bypassed. The script
  recomputes those names and updates the Brand.
- **`logo_data()` is `lru_cache`d**, so the email logo needs a container restart.

## Adding another service

Mount `icons/` read-only, or symlink to it. Never copy - a copy is what this
directory exists to eliminate.
