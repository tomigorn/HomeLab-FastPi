# M4b-Auto-Merge

Keeps the Audiobookshelf library converged on single-file chaptered `.m4b` as new
books arrive.

The watcher is a small Rust binary (`rust/`, since 2026-11-09; the old Python watcher stays in `legacy/` until removed). **This project contains no merge logic.** It decides *when* to run
`/home/pi/Projects/Docker/audiobookshelf/m4b-merge/orchestrate.py`, which already
stages each book to beefy, merges it, runs all eight verification checks,
md5-round-trips the result, promotes it, quarantines the originals and recovers
if beefy powers itself off mid-job. Re-implementing any of that here would mean
re-earning guarantees that an independent review and a day of testing
established.

A "new book" is not a special case: it is a folder holding two or more audio
files, which is exactly what the orchestrator already looks for. So the trigger
runs the ordinary whole-library pass. That pass is idempotent — it merges what is
new and skips what is done — which also means it cannot miss a book that inotify
failed to report.

## When it runs

| Trigger | Behaviour |
|---|---|
| **inotify** | any change under the library arms it; it then waits for `QUIET_SECONDS` (default 5 min) of complete quiet before acting |
| **Weekly sweep** | Saturday 04:00 local, whether or not anything changed — a backstop for a missed event |
| **Startup** | arms once, so books that arrived while the container was down are picked up |

The quiet period is what makes this safe against a copy in progress: every write
pushes the deadline out, so a folder is only ever merged once it has stopped
changing. Folders holding an in-progress marker (`.part`, `.!qB`, `.crdownload`,
`.tmp`) are skipped outright.

## Why it can't feed itself

A promote writes a `.m4b` into the library and moves the originals to quarantine
— which is itself a change under the library, so it re-arms the watcher. That
would be an endless loop if the watcher blindly ran the orchestrator.

It doesn't: before starting a run it checks whether any folder actually holds two
or more audio files. After a successful promote none do, so it logs
`nothing to merge` and goes back to waiting **without contacting beefy at all**.
The orchestrator makes the same check and returns before its ssh probe, so an
idle trigger can never power a machine on.

## Concurrency

`orchestrate.py` takes an exclusive `flock` on `runs/merge.lock` and exits 3 if
another run holds it. That is not a theoretical concern: when two orchestrators
overlapped, both derived the same slug for the same book, so one run's
`merge-book.py` deleted the other's output mid-write and seven books failed with
`Unable to re-open ... output file`.

Exit 3 is not an error here. The other run scans the whole library anyway, so the
watcher logs it, stays armed and retries in `RETRY_SECONDS` (default 15 min).

## Operating it

    cd /home/pi/Projects/Docker/M4b-Auto-Merge

    docker compose up -d                      # start
    docker compose logs -f                    # what it is doing and why
    docker compose up -d --build              # after editing rust/ (runs cargo test in the build)
    docker compose up -d --force-recreate     # after editing compose/.env

Progress during a merge is on the existing dashboard at
**http://192.168.1.2:8099/** — this project writes into the same `runs/`
directory, so an automatic merge looks exactly like a manual one. There is no
second dashboard and no port published here.

To force a merge now rather than waiting:

    cd /home/pi/Projects/Docker/audiobookshelf/m4b-merge
    ./orchestrate.py --jobs 10 --include-multipart

## Secrets

`secrets/` holds the private ssh key for beefy, its `known_hosts` entry and an
ssh config. The whole directory is gitignored and must never be committed. To
rebuild it on a fresh checkout:

    mkdir -p secrets
    cp ~/.ssh/beefy secrets/beefy && chmod 600 secrets/beefy
    ssh-keyscan -H 192.168.1.102 > secrets/known_hosts
    # then write secrets/ssh_config pointing IdentityFile at /ssh/beefy

## Notes

- The container runs as uid 65018 (group 1100 for the library ACL), read-only root with a `/tmp` tmpfs, `init: true`, all capabilities dropped, cpus 2 / pids 256 / 512 MB (for the orchestrator; the watcher itself uses under 1 MB), no ports.
- `MERGE_DIR` is mounted at the **same path** inside the container as on the
  host, so the orchestrator's absolute default paths resolve unchanged. The
  scripts are read-only; only `runs/` is writable.
- `TZ` matters: the weekly sweep uses local time. Without it the container would
  run in UTC and the sweep would drift by an hour across DST.
- Nothing is ever deleted. Originals move to
  `/mnt/seagate-black/m4b-originals-quarantine`, and `restore-book.py` in the
  m4b-merge project reverses any merge.
- Library and quarantine come in through ONE bind of their disk (`DISK_DIR`): a rename across two separate bind mounts fails with `EXDEV` even on one filesystem (every promote failed until 2026-11-02). The rest of the disk (`library/podcasts`, `lost+found`) is bound read-only on top. Checks: `m4b.one-mount`, `m4b.rest-read-only`.
- Disk not mounted: `/mnt/seagate-black` is then an empty directory, the watcher finds no library, exits and restarts (nothing is written).
- Reads under the library (ABS scans, `find`) do not restart the quiet period, only changes do (no IN_OPEN/IN_ACCESS watch).
- The merge starts exactly `QUIET_SECONDS` after the last change (the Python watcher polled every 30 s on top). Folders moved into the library are watched all the way down (the Python watcher missed changes deep inside a moved-in tree).
- `docker stop` while idle exits at once; during a merge the watcher waits for the orchestrator, so docker's kill timeout ends it as before (then check `pgrep ffmpeg` on beefy).

## Tests

| What | Command |
|---|---|
| Unit (Rust, in the build) | `docker build --target build .` |
| Black-box, 24 cases (fake orchestrator, scratch library in /tmp) | `tests/blackbox/run.sh m4b-auto-merge:local` |
| Benchmark (startup, RSS, CPU, trigger latency) | `BENCH=1 tests/blackbox/run.sh m4b-auto-merge:local` |
| Legacy watcher | `docker build -t m4b-auto-merge:legacy -f legacy/Dockerfile . && tests/blackbox/run.sh m4b-auto-merge:legacy` |

New dependency versions: `docker build --target lockfile -o rust .` rewrites `rust/Cargo.lock`.
- beefy is always used, by design. It gets woken if it is asleep and idles back
  off afterwards.

**Rebuild** (`m4b-auto-merge:local`, `rust:1-alpine@sha256:…` build stage, FROM `python:3.12-alpine@sha256:…` because orchestrate.py is Python, both pinned by digest, A-30): set the `FROM` digests to the current ones (`docker buildx imagetools inspect <image:tag>`, first `Digest:`), then `docker compose up -d --build`. Automatic: weekly `rebuild-local` (`Server/4-Security-Monitoring/auto-updates.md` "Local builds") moves the pin, rebuilds, runs the black-box suite and rolls back on failure; by hand: `python3 ../_global/scripts/rebuild_local.py M4b-Auto-Merge`.
