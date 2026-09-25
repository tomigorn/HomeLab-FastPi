# Holy Grail branding — instructions

Read `README.md` in this directory before changing anything here. Key points:

- This is the **single source of truth** for the Holy Grail icon set. Services
  reference it by symlink or bind mount. **Never copy these files into a
  service's own directory** — deduplicating those copies is why this exists.

- Everything is deliberately `root:root`, files `444`, directories `555`. Use
  `sudo` to change anything, and **`sudo chmod 444` afterwards** — `cp` preserves
  the source mode, so a freshly unzipped (644) set lands writable and silently
  drops the protection.

- After changing `icons/`, run `sudo ./deploy-to-authentik.sh`. Symlinks pick up
  new bytes instantly, but two things do not: Cloudflare caches the login logo for
  four hours (hence md5-prefixed filenames — new content, new URL), and
  `logo_data()` is `lru_cache`d (hence the restart). Skipping the script looks
  exactly like a failed deploy.

- `docker-compose.yaml` mounts this directory at the **same absolute path** it has
  on the host. That is required, not cosmetic: a symlink inside a bind mount
  resolves in the *container's* namespace, so a link to `/home/pi/Projects/...`
  dangles inside a container that only sees `/data`. Do not shorten that mount
  point without rewriting every symlink.

- This directory is inside the `/home/pi/Projects` git repo. Commit artwork
  changes — version history is the real protection, not the file mode.

- Verify rather than assume: after a deploy, check the served bytes actually
  match (`md5sum`) and that `cf-cache-status` is `MISS`, not `HIT`.
