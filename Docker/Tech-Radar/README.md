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
- Audit of that inner tree (2026-11-12): `npm audit` reports 9 vulnerabilities (6 moderate, 2 high, 1 critical: next, postcss, sharp, minimatch), all dev-time; `npm audit --omit=dev` finds 0. They live only in the throwaway Node build stage: the image holds just Caddy plus static files, no Next server or sharp.
- Update the inner lock: extract the new tarball (`npm pack aoe_technology_radar@<v>`), `npm install --package-lock-only --ignore-scripts` there, copy `package-lock.json` to `builder-lock.json`.
- Image size on disk: 63.7 MB.
- `config.json` sets `social: []` and `imprint: ""` because the package otherwise falls back to AOE defaults; `custom.css` hides the footer link.
