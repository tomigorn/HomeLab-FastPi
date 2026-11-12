# Tech-Radar
Tech stack showcase at `stack.holy-grail.ch` (Holy Grail login). Static [AOE Technology Radar](https://github.com/AOEpeople/aoe_technology_radar) `4.6.1` (pinned, `package-lock.json`), built in a Node stage and served by Caddy. No Node at runtime.

| What | Where |
|---|---|
| Items | `radar/<YYYY-MM-DD>/<id>.md` (front matter: `title`, `ring`, `quadrant`, `tags`) |
| Quadrants | `languages`, `hardware`, `devops`, `services` |
| Rings | `production`, `daily`, `learning`, `retired` |
| Tags | `fastpi beefy tower security media network sso monitoring device dev` |
| Config, about, logo | `config.json`, `about.md`, `public/`, `custom.css` |
| Built output | `/srv` in the image; item URL `/<quadrant>/<id>/` |

## Access
| What | Where |
|---|---|
| Route, headers, CSP | `../Traefik/traefik/dynamic/tech-radar.yml` (`script-src 'self'`: the pages have no executable inline script; `style-src` keeps `unsafe-inline` for style attributes) |
| Login | Authentik app `Tech Stack` (`../Authentik/scripts/provision-admin-sso.py`), groups homelab-admins and homelab-users, Utilities tile (`dashboard-look.py`) |
| Checks | `../_global/post-update.d/Tech-Radar.sh`, `smoke-test.sh`, Prometheus probes of `stack.holy-grail.ch` |

## Update
```
free -m   # available >= 1500 MB first
docker compose --project-directory Docker/Tech-Radar up -d --build
docker builder prune -f
```

## Tests
```
python3 -m unittest discover -s Docker/Tech-Radar/tests          # content lint
TECH_RADAR_BUILD_DIR=<extracted /srv> python3 -m unittest discover -s Docker/Tech-Radar/tests   # build checks
```

## Notes
- Pinned: `package.json`/`package-lock.json` pin the package (exact `4.6.1`, 0 vulnerabilities). The package ships no lockfile and would run an unlocked `npm install` of its own tree (~1400 packages) while building, so `builder-lock.json` (its lockfile, generated from the 4.6.1 tarball) is copied into the build dir and installed with `npm ci` in the Dockerfile.
- Patched inner tree: `builder-package.json` is the package's own manifest with `next`/`eslint-config-next` raised to 15.5.29 and `overrides` for `postcss` (^8.5.32) and the lint chain's `minimatch` (^11.0.8); the Dockerfile copies it and `builder-lock.json` into the build dir before `npm ci`. `npm audit` on that tree (2026-11-12): 0 vulnerabilities. It lives only in the throwaway Node build stage; the image holds just Caddy plus static files.
- Update the inner tree: `npm pack aoe_technology_radar@<v>`, take its `package.json`, reapply the bumps/overrides above, `npm install --package-lock-only --ignore-scripts`, `npm audit` → 0, copy both files to `builder-package.json`/`builder-lock.json`; `tests/test_content.py` checks the minimum versions.
- Image size on disk: 63.7 MB.
- Measured container RAM (docker stats, idle, 2026-11-12): 22.9 MiB of the 32 MiB limit.
- `config.json` sets `social: []` and `imprint: ""` because the package otherwise falls back to AOE defaults; `custom.css` hides the footer link.
