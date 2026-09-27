# M4b-Auto-Merge design

**Goal:** keep the Audiobookshelf library converged on single-file chaptered `.m4b`
as new books arrive, without manual steps.

**Decisions (user, 2026-09-27):** inotify trigger plus a weekly safety sweep at
Saturday 04:00; auto-promote; always use beefy.

## Principle

This project does **not** merge anything itself. It is a trigger for
`/home/pi/Projects/Docker/audiobookshelf/m4b-merge/orchestrate.py`, which already
stages to beefy, merges, runs all eight verification checks, md5-round-trips the
result, promotes, quarantines the originals and recovers from beefy powering
itself off. Re-implementing any of that would mean re-earning the guarantees an
independent review and a day of testing just established.

"A new book" is not a special case: it is a folder holding two or more audio
files, which is exactly what `find_books()` already returns. So the trigger runs
the ordinary orchestrator over the whole library; being idempotent, it merges
whatever is new and skips everything already done.

## Components

| File | Responsibility |
|---|---|
| `app/watcher.py` | the only new logic: inotify, debounce, weekly sweep, invoke the orchestrator |
| `Dockerfile` | python + openssh-client + rsync + ffmpeg + watchdog |
| `docker-compose.yaml` | mounts, env, hardening, no published ports |
| `.env` / `.env.example` | paths, quiet period, sweep schedule, job count |
| `README.md` | how it works and how to operate it |

## Data flow

1. inotify (recursive, via `watchdog`) reports a change under the library.
2. The watcher marks the tree dirty and records the time. Every further event
   pushes that time forward.
3. When `QUIET_MINUTES` (default 5) pass with no event, the tree is considered
   settled. A copy in progress keeps resetting the clock, so the watcher never
   acts on a half-written folder.
4. The watcher checks cheaply whether any merge candidate actually exists. If
   not, it clears the dirty flag and goes back to waiting — this is what stops a
   promote (which writes a `.m4b` into the library) from triggering an endless
   self-feeding loop.
5. Otherwise it runs `orchestrate.py --jobs N --include-multipart`, which does
   everything else, including waking beefy.
6. Saturday 04:00 local time, the same run happens regardless of events.

## Concurrency

`orchestrate.py` takes an exclusive `flock` on `runs/merge.lock` for the whole
run and exits with status 3 if another run already holds it.

This is not theoretical: when two orchestrators overlapped earlier today, both
computed the same slug for the same book, so one run's `merge-book.py` deleted
the other's output mid-write and seven books failed with
`Unable to re-open ... output file`. The lock makes that impossible.

Exit 3 is not an error for the watcher: if the big batch is running it will merge
the new books anyway, so the watcher simply logs it, stays dirty and retries in
`RETRY_MINUTES` (default 15).

## Failure handling

- The orchestrator's own guarantees are unchanged: any failure leaves the book
  untouched, originals are moved and never deleted, `restore-book.py` reverses
  any merge.
- beefy unreachable: the orchestrator wakes it via Beefy-Waker and retries.
- Nothing to merge: the orchestrator returns before contacting beefy at all, so
  an idle trigger costs nothing and never powers a machine on.
- Container restart: state is only the dirty flag; a restart re-arms the watcher
  and the weekly sweep still fires. Nothing is lost because the library itself is
  the source of truth.

## Security and access

The container needs the `~/.ssh/beefy` private key to reach beefy, mounted
read-only, plus `known_hosts`. The key is a secret: it lives under `secrets/`,
which is gitignored, and is never committed. The container publishes no ports and
runs non-root with all capabilities dropped.

## Observability

The watcher writes to the same `runs/` directory as the batch, so the existing
LAN dashboard at `http://192.168.1.2:8099/` shows an automatic merge exactly as it
shows a manual one. No second dashboard.

## Explicitly out of scope

- A local (fastpi) encode path. The decision is always-beefy, so building a
  second execution path would be unused code.
- Per-book targeting. Scanning the library is already cheap and idempotent, and
  a whole-library scan cannot miss a book that inotify failed to report.
- Any change to the merge or verification logic itself.
