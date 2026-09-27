#!/usr/bin/env python3
"""
Trigger the audiobook merge when new multi-file books appear.

This deliberately contains NO merge logic. It decides *when* to run
`orchestrate.py`, which already stages to beefy, merges, runs all eight
verification checks, md5-round-trips the result, promotes, quarantines the
originals and recovers from beefy powering itself off. Re-implementing any of
that here would mean re-earning guarantees that an independent review and a day
of testing established.

"A new book" is not a special case: it is a folder holding two or more audio
files, which is exactly what the orchestrator's find_books() already returns. So
the trigger just runs the ordinary whole-library pass; being idempotent, it
merges what is new and skips what is done.

Two triggers:
  * inotify, debounced - the tree must be quiet for QUIET_SECONDS before acting,
    so a copy still in progress keeps pushing the deadline out and is never
    merged half-written
  * a weekly sweep, as a backstop for any event inotify failed to deliver
"""
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

LIB = os.environ.get("LIB_DIR", "/mnt/seagate-black/library/audiobooks")
MERGE_DIR = os.environ.get(
    "MERGE_DIR", "/home/pi/Projects/Docker/audiobookshelf/m4b-merge")
QUIET_SECONDS = int(os.environ.get("QUIET_SECONDS", "300"))
RETRY_SECONDS = int(os.environ.get("RETRY_SECONDS", "900"))
JOBS = os.environ.get("JOBS", "10")
SWEEP_DOW = int(os.environ.get("SWEEP_DOW", "5"))     # Mon=0 .. Sat=5, Sun=6
SWEEP_HOUR = int(os.environ.get("SWEEP_HOUR", "4"))
SWEEP_MINUTE = int(os.environ.get("SWEEP_MINUTE", "0"))

AUDIO_EXT = (".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".flac", ".wav")
IN_PROGRESS = (".part", ".!qb", ".crdownload", ".tmp", ".filepart")

_state = threading.Lock()
_last_event = 0.0          # monotonic time of the most recent inotify event
_dirty = False
_wake = threading.Event()  # poked by inotify and by the sweep timer


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')}  {msg}", flush=True)


def touch(settled=False):
    """Record that something changed under the library.

    settled=True backdates the event clock so the next loop pass acts at once -
    used by the weekly sweep, which must fire even when nothing changed.
    """
    global _last_event, _dirty
    with _state:
        _last_event = time.monotonic() - (QUIET_SECONDS if settled else 0)
        _dirty = True
    _wake.set()


def clear_dirty():
    global _dirty
    with _state:
        _dirty = False


def set_dirty():
    global _dirty
    with _state:
        _dirty = True


class Handler(FileSystemEventHandler):
    def on_any_event(self, event):
        # The merge itself writes into the library (the .m4b it installs) and
        # into quarantine. Those events are harmless - they just mark the tree
        # dirty, and candidates() then finds nothing and the run is skipped
        # before beefy is ever contacted.
        touch()


def candidates():
    """Cheap check: does any folder actually hold >=2 audio files?

    This is what stops a promote from feeding the watcher forever. It mirrors
    the orchestrator's own rule closely enough to answer "is there any point
    starting a run", and the orchestrator remains the authority.
    """
    found = []
    for root, dirs, files in os.walk(LIB):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        lower = [f.lower() for f in files]
        if any(".m4b.part" in f or f == ".m4b-merge-promoting" for f in lower):
            continue                      # an interrupted promote; needs a human
        if any(f.endswith(IN_PROGRESS) for f in lower):
            continue                      # still being written into
        audio = [f for f in lower if os.path.splitext(f)[1] in AUDIO_EXT]
        if len(audio) >= 2:
            found.append(root)
    return found


def run_merge(reason):
    """Run the orchestrator. Returns True if it ran to completion."""
    books = candidates()
    if not books:
        log(f"{reason}: nothing to merge")
        return True

    log(f"{reason}: {len(books)} candidate folder(s) - starting merge")
    cmd = [os.path.join(MERGE_DIR, "orchestrate.py"),
           "--jobs", str(JOBS), "--include-multipart"]
    try:
        p = subprocess.run(cmd, cwd=MERGE_DIR)
    except OSError as e:
        log(f"could not start the orchestrator: {e}")
        return False

    if p.returncode == 3:
        # Another merge already holds the lock - the big batch, or a previous
        # trigger. That run scans the whole library, so it will pick these books
        # up anyway; stay dirty and try again later rather than colliding.
        log(f"another merge run holds the lock; retrying in {RETRY_SECONDS}s")
        return False
    if p.returncode != 0:
        # Non-zero also means "some books failed", which is normal and not a
        # reason to keep retrying - the failures are recorded and the originals
        # are untouched.
        log(f"orchestrator exited {p.returncode} (some books failed); "
            f"see runs/run.jsonl")
    else:
        log("merge run finished cleanly")
    return True


def next_sweep(now=None):
    """Next SWEEP_DOW at SWEEP_HOUR:SWEEP_MINUTE, local time."""
    now = now or datetime.now()
    target = now.replace(hour=SWEEP_HOUR, minute=SWEEP_MINUTE,
                         second=0, microsecond=0)
    days = (SWEEP_DOW - now.weekday()) % 7
    target += timedelta(days=days)
    if target <= now:
        target += timedelta(days=7)
    return target


def sweep_timer():
    while True:
        nxt = next_sweep()
        log(f"weekly sweep scheduled for {nxt.isoformat(timespec='minutes')}")
        while True:
            remaining = (nxt - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 3600))     # re-check hourly: DST, clock set
        # Force a run even if nothing changed, so the sweep is a real backstop.
        touch(settled=True)
        time.sleep(90)                            # don't re-fire the same minute


def main():
    if not os.path.isdir(LIB):
        log(f"library {LIB} is not a directory")
        return 1
    orch = os.path.join(MERGE_DIR, "orchestrate.py")
    if not os.path.isfile(orch):
        log(f"orchestrator not found at {orch}")
        return 1

    log(f"watching {LIB}")
    log(f"quiet period {QUIET_SECONDS}s, {JOBS} parallel jobs, "
        f"retry {RETRY_SECONDS}s")

    obs = Observer()
    obs.schedule(Handler(), LIB, recursive=True)
    obs.start()
    threading.Thread(target=sweep_timer, daemon=True).start()

    # Startup sweep: books may have arrived while the container was down.
    touch()

    retry_at = 0.0
    try:
        while True:
            _wake.wait(timeout=30)
            _wake.clear()
            with _state:
                dirty, last = _dirty, _last_event
            now = time.monotonic()
            if not dirty:
                continue
            if now - last < QUIET_SECONDS:
                continue                          # still settling
            if now < retry_at:
                continue                          # backing off after a lock miss

            clear_dirty()
            if not run_merge("trigger"):
                set_dirty()                       # stay armed
                retry_at = time.monotonic() + RETRY_SECONDS
    except KeyboardInterrupt:
        pass
    finally:
        obs.stop()
        obs.join(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
