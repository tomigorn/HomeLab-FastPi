# BackdropCarousel

Wallpaper photos for the landing page: `https://backdrop-carousel.holy-grail.ch` (public, no login; Traefik `dynamic/backdrop-carousel.yml`, rate limit + strict CSP).

| Endpoint | Answer |
|---|---|
| `GET /` | JSON list `[{"name", "url"}]` of the photos, sorted, `url` = `http://<Host>/photo/<name>` |
| `GET /random` | one random photo; empty folder: 404 `{"error":"no photos available"}` |
| `GET /photo/<name>` | that photo (Range, ETag, Last-Modified, If-None-Match → 304); missing, other type or outside `photos/`: 404 `{"error":"not found"}` |
| anything else | 404 `{"detail":"Not Found"}`, other methods 405 |

Photos: `photos/` (gitignored, mounted read-only), `.jpg .jpeg .png .webp .bmp .gif`; new files show up without a restart.

## Code

| | |
|---|---|
| Server | Rust (`rust/`, hyper), one static binary in a `scratch` image, uid 65008, read-only, 32 MB limit |
| Legacy | Python/FastAPI original in `legacy/` (until removed), runs with `docker build legacy/` |
| Healthcheck | `/backdrop-carousel healthcheck` (the image has no shell) |

```bash
docker compose up -d --build                      # build + deploy (cargo test runs in the build)
tests/blackbox/run.sh new <binary>                # black-box suite (17 HTTP tests); also: old (legacy), image <image>
```

Weekly rebuild: `rebuild-local` Sat, runs the black-box suite against the new image (`../_global/rebuild-local.conf`).
