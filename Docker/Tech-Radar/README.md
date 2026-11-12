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
- `npm audit` (2026-11-12): 0 vulnerabilities. Image size on disk: 63.7 MB.
- `config.json` sets `social: []` and `imprint: ""` because the package otherwise falls back to AOE defaults; `custom.css` hides the footer link.
