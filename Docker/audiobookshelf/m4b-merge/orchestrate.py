#!/usr/bin/env python3
"""
Drive the multi-file -> .m4b merge across the library. Runs on fastpi; all
transcoding happens on beefy.

Per book:
  1. rsync the source folder to beefy
  2. beefy merges and runs the full 7-check verification (incl. a complete
     decode and a loudness spot-check against the staged originals)
  3. md5 the result on beefy, pull it, md5 locally - the bytes we keep are
     provably the bytes that passed verification
  4. cheap local ffprobe sanity check (no decode; the Pi does no heavy work)
  5. only then: originals are MOVED to a quarantine dir - never deleted - and
     the .m4b takes their place

Any failure leaves the book completely untouched and the run moves on.
"""
import argparse
import concurrent.futures as cf
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time

LIB = "/mnt/seagate-black/library/audiobooks"
QUARANTINE = "/mnt/seagate-black/m4b-originals-quarantine"
REMOTE = "beefy"
REMOTE_IP = "192.168.1.102"   # pinned: parallel DNS lookups for beefy.homelab
                             # intermittently fail under load
RWORK = "m4b-work"
_RHOME = None

# One multiplexed SSH connection shared by every job: no repeated DNS lookups,
# no repeated handshakes, and rsync rides the same channel.
# Deliberately NOT multiplexed: one shared connection caps out at sshd's
# MaxSessions (10), which fewer sessions than we run in parallel. Separate
# connections have no such ceiling, and pinning the IP is what actually fixed
# the DNS failures.
SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", f"HostName={REMOTE_IP}",
    "-o", "ControlMaster=no",
    "-o", "ControlPath=none",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=6",
    "-o", "ConnectTimeout=20",
]
SSH_E = "ssh " + " ".join(SSH_OPTS)
AUDIO_EXT = (".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".flac", ".wav")
COVER_EXT = (".jpg", ".jpeg", ".png")
# Dropped in the book folder for the length of the promote. The .part file is
# consumed by the rename that installs the .m4b, so between that rename and the
# last original moving out there is no other evidence a promote was in flight.
PROMOTE_MARK = ".m4b-merge-promoting"
# Beefy-Waker: sends the WoL magic packet. Used to recover when beefy's idle
# watcher powers it off under a running job.
WAKER_URL = "http://192.168.1.2:9001/wake"


def run(cmd, timeout=None):
    """Like subprocess.run, but a timeout is a FAILED result, not an exception.

    Every caller here already treats a non-zero returncode as failure. Letting
    TimeoutExpired propagate instead would blow up the one path that exists to
    handle an unreachable host - `ssh true` against a powered-off beefy times
    out rather than returning, so the retry logic would crash exactly when it
    is needed.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            cmd, 124, stdout=(e.stdout or b"").decode("utf-8", "replace")
            if isinstance(e.stdout, bytes) else (e.stdout or ""),
            stderr=f"timed out after {timeout}s")


def ssh(script, timeout=None):
    return run(["ssh", *SSH_OPTS, REMOTE, script], timeout=timeout)


def rbase():
    """Absolute work dir on the remote; ~ is not expanded inside quoted paths."""
    global _RHOME
    if _RHOME is None:
        h = ssh("echo $HOME").stdout.strip()
        if not h:
            raise RuntimeError("cannot determine remote $HOME")
        _RHOME = f"{h}/{RWORK}"
    return _RHOME


def natkey(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def audio_files(d):
    return sorted((f for f in os.listdir(d)
                   if os.path.splitext(f)[1].lower() in AUDIO_EXT
                   and os.path.isfile(os.path.join(d, f))), key=natkey)


def ci_glob(ext):
    """'.mp3' -> '.[mM][pP]3' so an rsync filter matches any capitalisation."""
    return "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in ext)


def wake_remote(timeout=420):
    """Wake beefy and wait for ssh. Returns True once it answers.

    beefy's idle watcher powers the host off (DRY_RUN=0) after 15 idle minutes,
    and its probes ignore port 22 and the NVMe the work dir lives on - so a long
    run CAN be shut down under itself. The inhibit file it honours needs root,
    which we do not have there, so instead of preventing the poweroff we survive
    it: wake the host back up and retry the book. This also covers a reboot or a
    crash, which no inhibit file would have helped with.
    """
    try:
        import urllib.request
        urllib.request.urlopen(
            urllib.request.Request(WAKER_URL, method="POST"), timeout=20).read()
    except Exception as e:
        print(f"    wake request failed: {e}", file=sys.stderr)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ssh("true", timeout=30).returncode == 0:
            return True
        time.sleep(15)
    return False


class KeepAwake:
    """Hold beefy awake for the life of a run.

    beefy's idle watcher powers the host off after 15 idle minutes, and its idea
    of idle does not match ours: it measures WHOLE-HOST cpu against a 15%
    threshold, so one encode (1 core of 12, about 8%) reads as idle; the work dir
    is on the NVMe, which its disk probe excludes; port 22 is excluded from its
    connection probe; and `ssh host cmd` is deliberately not counted. A long
    single-book encode therefore looks like nothing is happening. It is not
    hypothetical - it logged "idle 15 min -> systemctl poweroff" at 00:30 while
    Shogun was mid-encode, and the encode had to start over.

    Two ways to hold it, in order of preference:

    1. The watcher's own inhibit file, via a one-purpose helper granted by a
       single sudoers rule. Exact, and what the watcher documents. See _helper().
    2. If that is not installed: an interactive pty session, which the watcher
       also counts as "someone is working here" (`ssh=1 -> BUSY (ssh)`), renewed
       well inside the idle window.

    Either way the hold stops when the run does, so beefy still powers itself
    off normally once the work is finished.
    """

    RENEW = 240           # seconds per session, comfortably under the 15 min window
    HELPER = "/usr/local/sbin/beefy-keep-awake"

    def __init__(self, enabled=True):
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread = None
        self._proc = None
        self._inhibit = False

    def _helper(self, action):
        """Drive the watcher's own inhibit file through the one-purpose helper.

        This is the mechanism the watcher documents: exact, no polling, no
        session to renew, no dependence on how it happens to count sessions. It
        needs root on the remote, so it works only once the helper is installed
        and granted:

          sudo install -m 755 beefy-keep-awake /usr/local/sbin/beefy-keep-awake
          echo 'buntu ALL=(root) NOPASSWD: /usr/local/sbin/beefy-keep-awake' \\
            | sudo tee /etc/sudoers.d/beefy-keep-awake
          sudo chmod 440 /etc/sudoers.d/beefy-keep-awake

        Without it sudo -n fails and we fall back to holding a pty session,
        which the watcher also counts as activity.
        """
        return ssh(f"sudo -n {shlex.quote(self.HELPER)} {action}",
                   timeout=30).returncode == 0

    def __enter__(self):
        if not self.enabled:
            return self
        if self._helper("on"):
            self._inhibit = True
            print(f"holding {REMOTE} awake via its inhibit file")
        else:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            print(f"holding {REMOTE} awake with an interactive session "
                  f"({self.HELPER} not available)")
        return self

    def _loop(self):
        while not self._stop.is_set():
            try:
                # -tt forces a pty even though stdin is not a terminal; that is
                # precisely what makes the watcher count the session.
                self._proc = subprocess.Popen(
                    ["ssh", "-tt", *SSH_OPTS, REMOTE, f"sleep {self.RENEW}"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self._stop.wait(15)
                continue
            while not self._stop.is_set() and self._proc.poll() is None:
                self._stop.wait(5)
            if self._stop.is_set():
                return
            self._stop.wait(5)        # session ended; renew shortly

    def __exit__(self, *exc):
        self._stop.set()
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=15)
        if self._inhibit:
            # Must be released, or beefy never sleeps again. /run is a tmpfs so a
            # reboot would clear it, but do not rely on that.
            if not self._helper("off"):
                print(f"WARNING: could not release the inhibit file on {REMOTE} "
                      f"- it will not power itself off until you run "
                      f"`sudo {self.HELPER} off` there", file=sys.stderr)
            self._inhibit = False
        return False


def md5_local(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def slug_for(relpath):
    s = re.sub(r"[^A-Za-z0-9]+", "_", relpath).strip("_")[:120]
    return f"{s}_{hashlib.md5(relpath.encode()).hexdigest()[:8]}"


def meta_from_path(bookdir):
    """audiobooks/<LANG>/<Author>/[Series/]<NN - Title>  ->  (title, artist)"""
    rel = os.path.relpath(bookdir, LIB)
    parts = rel.split(os.sep)
    artist = parts[1] if len(parts) >= 2 else None
    # '.' is NOT a separator here: it would turn '17.5 - Big Jack' into
    # '5 - Big Jack' by eating the '17.' as the index.
    title = re.sub(r"^\s*\d+(?:\.\d+)?\s*[-_]\s*", "", parts[-1]).strip() \
        or parts[-1]
    return title, artist


def find_books(limit=None, only=None, include_multipart=False,
               allow_single=False):
    """Folders holding >=2 audio files that are not already a single file.

    A folder with exactly one audio file is done. A folder with several .m4b/.m4a
    parts is still a merge candidate - skipping those silently hid 69 books,
    38.9 GB, including the worst offenders (63- and 68-part sets). They are
    returned only on request because merging them means AAC->AAC, a second lossy
    generation, so they want a stream-copy path rather than this one.
    """
    out, multipart, interrupted = [], [], []
    for root, dirs, files in os.walk(LIB):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        # -- interrupted-promote detection, BEFORE any audio-file test --------
        # A promote that dies partway leaves several states, and an audio-file
        # count would hide most of them - including a folder holding ONLY the
        # .part, which has no audio at all and would otherwise be invisible even
        # though the book has no playable file left.
        # `in` not `endswith`: rsync's own temp is `..<slug>.m4b.part.XXXXXX`.
        if any(".m4b.part" in f or f == PROMOTE_MARK for f in files):
            interrupted.append(root)
            continue
        af = [f for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT]
        if not af:
            continue
        # A folder holding BOTH an .m4b and loose tracks is the crash window
        # between "install the .m4b" and "move the originals": the .part is
        # already consumed, so nothing else marks it. Merging it would produce a
        # book containing its audio TWICE, and every check would pass because
        # they all measure the same doubled set. No such folder exists today.
        has_m4b = any(os.path.splitext(f)[1].lower() in (".m4b", ".m4a") for f in af)
        has_other = any(os.path.splitext(f)[1].lower() not in (".m4b", ".m4a")
                        for f in af)
        if has_m4b and has_other:
            interrupted.append(root)
            continue
        if len(af) < 2:
            # A folder with one audio file is already done - unless it is a
            # standalone edition split out of a two-edition folder and the
            # caller explicitly asked to convert it to .m4b.
            if not (allow_single and len(af) == 1
                    and os.path.splitext(af[0])[1].lower() != ".m4b"):
                continue
        if has_m4b:
            multipart.append(root)
            if not include_multipart:
                continue
        out.append(root)
    find_books.multipart = multipart
    find_books.interrupted = interrupted
    out.sort(key=lambda p: sum(os.path.getsize(os.path.join(p, f))
                               for f in audio_files(p)))
    if only:
        out = [b for b in out if any(o.lower() in b.lower() for o in only)]
    return out[:limit] if limit else out


def process(bookdir, dry_run=False, samples=0, keep_remote=False, mode="auto",
            allow_single=False):
    t0 = time.time()
    rel = os.path.relpath(bookdir, LIB)
    slug = slug_for(rel)
    title, artist = meta_from_path(bookdir)
    files = audio_files(bookdir)
    src_bytes = sum(os.path.getsize(os.path.join(bookdir, f)) for f in files)
    res = {"book": rel, "title": title, "artist": artist, "n_files": len(files),
           "src_bytes": src_bytes, "stage": "start", "ok": False}

    if dry_run:
        res.update(ok=True, stage="dry-run")
        return res

    rb = rbase()
    rstage = f"{rb}/staging/{slug}"
    rout = f"{rb}/out/{slug}.m4b"
    rrep = f"{rb}/out/{slug}.json"
    try:
        # -- 1. stage to beefy (audio + cover only) ----------------------
        res["stage"] = "stage"
        ssh(f"mkdir -p {shlex.quote(rstage)} {shlex.quote(rb + '/out')}"
            ).check_returncode()
        # Case-insensitive globs. Listing only `*.mp3` and `*.MP3` misses a file
        # named `.Mp3`, which audio_files() DOES count because it lowercases the
        # extension - the Pi would then quarantine a file beefy never received.
        incl = [f"--include=*{ci_glob(e)}" for e in AUDIO_EXT + COVER_EXT]
        r = run(["rsync", "-a", "-e", SSH_E,
                 "--no-perms", "--no-owner", "--no-group",
                 "--prune-empty-dirs", *incl, "--exclude=*",
                 bookdir + "/", f"{REMOTE}:{rstage}/"], timeout=7200)
        if r.returncode != 0:
            raise RuntimeError(f"rsync push failed: {r.stderr[-500:]}")

        # -- 2. merge + verify on beefy ----------------------------------
        res["stage"] = "merge"
        cmd = (f"{shlex.quote(rb + '/merge-book.py')} {shlex.quote(rstage)} "
               f"{shlex.quote(rout)} --report {shlex.quote(rrep)} "
               f"--samples {samples} --mode {shlex.quote(mode)} "
               + ("--allow-single " if allow_single else "") +
               f"--title {shlex.quote(title)}"
               + (f" --artist {shlex.quote(artist)}" if artist else ""))
        r = ssh(cmd, timeout=14400)
        try:
            res["verify"] = json.loads(r.stdout)
        except Exception:
            res["verify"] = {"raw": (r.stdout or r.stderr)[-2000:]}
        if r.returncode != 0 or not res["verify"].get("ok"):
            raise RuntimeError("verification FAILED on beefy")

        # -- 3. pull, with md5 proving the bytes match ------------------
        res["stage"] = "pull"
        rmd5 = ssh(f"md5sum {shlex.quote(rout)} | cut -d' ' -f1").stdout.strip()
        tmp = os.path.join(bookdir, f".{slug}.m4b.part")
        r = run(["rsync", "-a", "-e", SSH_E,
                 "--no-perms", "--no-owner", "--no-group",
                 f"{REMOTE}:{rout}", tmp], timeout=7200)
        if r.returncode != 0:
            raise RuntimeError(f"rsync pull failed: {r.stderr[-500:]}")
        lmd5 = md5_local(tmp)
        res["md5"] = {"remote": rmd5, "local": lmd5}
        if not rmd5 or rmd5 != lmd5:
            os.remove(tmp)
            raise RuntimeError(f"md5 mismatch: {rmd5} != {lmd5}")

        # -- 4. cheap local sanity (no decode - beefy already did that) --
        res["stage"] = "local-check"
        pr = run(["ffprobe", "-v", "error", "-show_entries",
                  "format=duration", "-show_chapters", "-of", "json", tmp])
        pd = json.loads(pr.stdout or "{}")
        ldur = float((pd.get("format") or {}).get("duration") or 0)
        lch = len(pd.get("chapters") or [])
        want = float(res["verify"]["source_total_duration"])
        # NOT len(files): a multi-part book whose parts carry their own chapter
        # tables expands to more chapters than it has files.
        want_ch = int(res["verify"].get("n_chapters_planned") or len(files))
        res["local"] = {"duration": ldur, "chapters": lch, "want_chapters": want_ch}
        if lch != want_ch or abs(ldur - want) > max(0.5, len(files) * 0.01):
            os.remove(tmp)
            raise RuntimeError(f"local check failed: {lch} chapters, {ldur:.1f}s "
                               f"(want {want_ch}, {want:.1f}s)")

        # -- 5. promote: quarantine originals, install the .m4b ---------
        res["stage"] = "promote"

        # The Pi is about to quarantine `files`. If beefy merged a different set
        # - because an rsync filter missed one, or a file appeared or vanished
        # between enumeration and transfer - then every check above still passed,
        # because they all measure beefy's set against itself. This is the only
        # thing comparing what was merged with what is about to be moved away.
        merged_n = int(res["verify"].get("n_files") or -1)
        if merged_n != len(files):
            raise RuntimeError(
                f"file-count mismatch: beefy merged {merged_n} file(s) but "
                f"{len(files)} are about to be quarantined - refusing to promote")

        qdir = os.path.join(QUARANTINE, rel)
        os.makedirs(qdir, exist_ok=True)
        final = os.path.join(bookdir, f"{title}.m4b")
        # A multi-part set can contain a part named exactly like the target, e.g.
        # 'Title.m4b' alongside 'Title 02.m4b'. That one source has to move out of
        # the way before the merged file can take its name.
        collides = os.path.basename(final) in files
        if os.path.exists(final) and not collides:
            raise RuntimeError(f"refusing to overwrite existing {final}")

        # Order matters. If the originals moved first and we then died, the folder
        # would hold a SUBSET of the tracks and no .m4b - and the next run would
        # merge that subset, pass all seven checks against it, and promote a
        # truncated book. Installing the .m4b first means an interrupted promote
        # leaves .m4b + leftover originals, which find_books() skips.
        # In the colliding case that order is impossible, so we rely on the other
        # guard: the .part file is still on disk until the rename, and
        # find_books() refuses any folder that has one.
        moved = []

        def _unwind():
            for f in moved:                      # put back what we moved
                try:
                    os.rename(os.path.join(qdir, f), os.path.join(bookdir, f))
                except OSError:
                    pass

        # Installing the .m4b consumes the .part, so from that rename until the
        # last original leaves, nothing on disk says a promote was in flight. A
        # crash there would leave .m4b + some originals, which looks exactly like
        # a legitimate multi-part book - and re-merging it yields a book holding
        # its audio twice, with every check passing. This marker is the evidence.
        mark = os.path.join(bookdir, PROMOTE_MARK)
        try:
            with open(mark, "w") as fh:
                fh.write(slug + "\n")
        except OSError as e:
            raise RuntimeError(f"cannot write promote marker: {e}")

        try:
            if not collides:
                os.rename(tmp, final)
                os.chmod(final, 0o664)
            for f in files:
                os.rename(os.path.join(bookdir, f), os.path.join(qdir, f))
                moved.append(f)
            if collides:
                os.rename(tmp, final)
                os.chmod(final, 0o664)
        except OSError as e:
            _unwind()
            if not collides:
                try:
                    os.remove(final)
                except OSError:
                    pass
            raise RuntimeError(f"promote failed, rolled back: {e}")
        finally:
            # Removed on BOTH paths: after a successful promote the folder is a
            # normal single-file book, and after a rollback it is untouched.
            try:
                os.remove(mark)
            except OSError:
                pass
        res["quarantined"] = len(moved)
        res["final"] = os.path.relpath(final, LIB)
        res["out_bytes"] = os.path.getsize(final)
        res.update(ok=True, stage="done")

    except Exception as e:
        res["error"] = str(e)[:2000]
    finally:
        # an exception anywhere after the pull would otherwise leave
        # .<slug>.m4b.part sitting in the library folder forever
        if not res.get("ok"):
            for leftover in (os.path.join(bookdir, f".{slug}.m4b.part"),
                             os.path.join(bookdir, PROMOTE_MARK)):
                try:
                    if os.path.exists(leftover):
                        os.remove(leftover)
                except OSError:
                    pass
        if not keep_remote:
            ssh(f"rm -rf {shlex.quote(rstage)} {shlex.quote(rout)}", timeout=120)
        res["seconds"] = round(time.time() - t0, 1)
        res["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return res


_wake_lock = threading.Lock()


def process_retry(bookdir, attempts=3, **kw):
    last = None
    for i in range(attempts):
        r = process(bookdir, **kw)
        if r["ok"]:
            if i:
                r["attempts"] = i + 1
            return r
        last = r
        if i == attempts - 1:
            break

        # Is the host itself gone? beefy powers itself off when its idle watcher
        # decides nothing is happening, and it can do that under a running job.
        # That kills whatever stage we were in, so the stage is not a useful
        # signal - ask the host directly instead of parsing error strings.
        if ssh("true", timeout=30).returncode != 0:
            with _wake_lock:                     # one waker for all the jobs
                if ssh("true", timeout=30).returncode != 0:
                    print(f"    {REMOTE} is down - waking it and retrying",
                          file=sys.stderr)
                    if not wake_remote():
                        r["error"] = (r.get("error", "") +
                                      f" | {REMOTE} did not come back up")
                        break
            r["woke_remote"] = True
            time.sleep(5)
            continue

        # Host is fine: only a transfer/setup failure is worth retrying. A
        # verification failure is a real problem with the book and must be
        # looked at, not retried until it happens to pass.
        if r.get("stage") not in ("stage", "pull"):
            break
        time.sleep(5)
    return last


def acquire_lock(path, wait=0):
    """Exclusive lock. Returns the open fd, or None if another run holds it.

    `wait` seconds of polling before giving up; 0 means fail immediately.

    Two orchestrators running at once is not a hypothetical: when it happened,
    both derived the SAME slug for the same book, so one run's merge-book.py
    deleted the other's output mid-write and seven books died with
    "Unable to re-open ... output file". The fd is held for the whole run and
    released when the process exits.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.time() + max(0, wait)
    while True:
        fd = open(path, "w")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()
            if time.time() >= deadline:
                return None
            time.sleep(5)
            continue
        fd.write(f"{os.getpid()}\n")
        fd.flush()
        return fd


def write_progress(path, payload):
    """Atomic: the dashboard polls this and must never read a half-written file."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", action="append", default=None,
                    help="substring filter on the book path (repeatable)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-multipart", action="store_true",
                    help="also merge folders made of several .m4b/.m4a parts; "
                         "these are stream-copied (lossless) when their streams "
                         "match, so this is normally safe to enable")
    ap.add_argument("--mode", choices=("auto", "encode", "copy"), default="auto")
    ap.add_argument("--allow-single", action="store_true",
                    help="also convert folders holding ONE non-.m4b audio file. "
                         "Requires --only, because without a filter it would "
                         "re-encode every single-file book in the library")
    ap.add_argument("--samples", type=int, default=0,
                    help="chapters the content check correlates per book; 0 "
                         "(default) means EVERY chapter. Passing 5 here silently "
                         "defeated the full-coverage default in merge-book.py")
    ap.add_argument("--log", default="/home/pi/Projects/Docker/audiobookshelf/"
                                     "m4b-merge/runs/run.jsonl")
    ap.add_argument("--progress", default="/home/pi/Projects/Docker/audiobookshelf/"
                                          "m4b-merge/runs/progress.json")
    ap.add_argument("--lock", default="/home/pi/Projects/Docker/audiobookshelf/"
                                      "m4b-merge/runs/merge.lock",
                    help="exclusive lock file; a second run exits 3 rather than "
                         "colliding with the first")
    ap.add_argument("--no-keep-awake", action="store_true",
                    help="do not hold an interactive session open on the remote. "
                         "Without it, a long single-book encode reads as idle to "
                         "beefy's watcher (1 core of 12 is under its 15%% cpu "
                         "threshold) and the host powers off mid-job")
    ap.add_argument("--lock-wait", type=int, default=0, metavar="SECONDS",
                    help="wait this long for the lock before giving up "
                         "(default 0: exit 3 immediately)")
    a = ap.parse_args()

    lock_fd = None
    if not a.dry_run:
        lock_fd = acquire_lock(a.lock, wait=a.lock_wait)
        if lock_fd is None:
            print(f"another merge run holds {a.lock} - exiting", file=sys.stderr)
            return 3

    if a.allow_single and not a.only:
        print("--allow-single needs --only: without a filter it would convert "
              "every single-file book in the library", file=sys.stderr)
        return 1
    books = find_books(limit=a.limit, only=a.only,
                       include_multipart=a.include_multipart,
                       allow_single=a.allow_single)
    stuck = getattr(find_books, "interrupted", [])
    if stuck:
        print(f"WARNING: {len(stuck)} folder(s) hold a leftover .m4b.part from an "
              f"interrupted promote and were EXCLUDED. Check them by hand:")
        for b in stuck:
            print(f"  ! {os.path.relpath(b, LIB)}")
    skipped = [b for b in getattr(find_books, "multipart", [])
               if b not in books]
    if skipped:
        sz = sum(sum(os.path.getsize(os.path.join(b, f)) for f in audio_files(b))
                 for b in skipped)
        print(f"NOTE: {len(skipped)} multi-part .m4b/.m4a book(s), {sz/1e9:.1f} GB, "
              f"NOT included; --include-multipart to merge them losslessly")
    tot = sum(sum(os.path.getsize(os.path.join(b, f)) for f in audio_files(b))
              for b in books)
    print(f"{len(books)} book(s) to merge, {tot/1e9:.1f} GB, {a.jobs} parallel job(s)")
    if a.dry_run:
        for b in books:
            print(f"  [{len(audio_files(b)):>3}] {os.path.relpath(b, LIB)}")
        return 0

    # Return BEFORE touching beefy. The auto-merge watcher fires on any library
    # change, including the .m4b a promote just wrote, so an idle trigger must
    # not power a machine on to discover there is nothing to do.
    if not books:
        print("nothing to merge")
        return 0

    if ssh("true", timeout=60).returncode != 0:
        # beefy powers itself off when idle, so "unreachable" is the NORMAL
        # state between runs, not an error. Wake it rather than giving up -
        # otherwise a book arriving while beefy sleeps would simply be skipped.
        print(f"{REMOTE} is not reachable - waking it")
        if not wake_remote():
            print(f"cannot reach {REMOTE} over ssh, and it did not wake",
                  file=sys.stderr)
            return 1
    rb = rbase()

    # Deploy the merger every run. Editing it locally and forgetting to copy it
    # is exactly how an entire batch got encoded by stale code.
    merger = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "merge-book.py")
    if run(["rsync", "-a", "-e", SSH_E, merger,
            f"{REMOTE}:{rb}/merge-book.py"], timeout=300).returncode != 0:
        print("failed to deploy merge-book.py to beefy", file=sys.stderr)
        return 1
    ssh(f"chmod +x {shlex.quote(rb + '/merge-book.py')}", timeout=60)
    local_md5 = hashlib.md5(open(merger, "rb").read()).hexdigest()
    remote_md5 = ssh(f"md5sum {shlex.quote(rb + '/merge-book.py')}",
                     timeout=60).stdout.split()[:1]
    if not remote_md5 or remote_md5[0] != local_md5:
        print(f"merger md5 mismatch after deploy: {local_md5} vs {remote_md5}",
              file=sys.stderr)
        return 1
    print(f"remote work dir {rb}, merger {local_md5[:12]} deployed")

    keep = KeepAwake(enabled=not a.no_keep_awake)
    keep.__enter__()
    try:
        return _run(a, books, tot, rb)
    finally:
        keep.__exit__(None, None, None)


def _run(a, books, tot, rb):
    os.makedirs(os.path.dirname(a.log), exist_ok=True)
    os.makedirs(os.path.dirname(a.progress), exist_ok=True)
    ok = fail = 0
    saved = 0
    bytes_done = 0
    t_start = time.time()
    in_flight = {}
    recent, failures = [], []
    lock = threading.Lock()

    def snapshot(finished):
        el = time.time() - t_start
        rate = finished / el if el > 0 and finished else 0
        left = len(books) - finished
        return {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S",
                                        time.localtime(t_start)),
            "pid": os.getpid(), "jobs": a.jobs, "mode": a.mode,
            "host": REMOTE,
            "total_books": len(books), "total_bytes": tot,
            "done": ok, "failed": fail, "finished": finished,
            "remaining": left,
            "bytes_done": bytes_done,
            "elapsed_s": round(el),
            "eta_s": round(left / rate) if rate > 0 else None,
            "books_per_hour": round(rate * 3600, 2),
            "saved_bytes": saved,
            "in_flight": sorted(
                ({"book": b, "started_at": time.strftime("%H:%M:%S",
                                                         time.localtime(t))}
                 for b, t in in_flight.items()), key=lambda x: x["started_at"]),
            "recent": recent[-40:],
            "failures": failures[-80:],
        }

    def track(bookdir):
        rel = os.path.relpath(bookdir, LIB)
        with lock:
            in_flight[rel] = time.time()
        try:
            return process_retry(bookdir, samples=a.samples, mode=a.mode,
                                 allow_single=a.allow_single)
        finally:
            with lock:
                in_flight.pop(rel, None)

    # A book takes minutes, so writing progress only when one FINISHES leaves the
    # dashboard blank for the whole first round and then frozen between
    # completions. A ticker keeps in-flight and elapsed honest.
    done_evt = threading.Event()
    finished_n = [0]

    def ticker():
        while not done_evt.wait(10):
            write_progress(a.progress, snapshot(finished_n[0]))

    write_progress(a.progress, snapshot(0))
    tick_t = threading.Thread(target=ticker, daemon=True)
    tick_t.start()
    with open(a.log, "a") as lf, \
            cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(track, b): b for b in books}
        for i, fu in enumerate(cf.as_completed(futs), 1):
            try:
                r = fu.result()
            except Exception as e:
                # A worker raising (a file vanishing between find_books and
                # process, say) must not abandon the books still in flight.
                b = futs[fu]
                r = {"book": os.path.relpath(b, LIB), "ok": False,
                     "stage": "worker", "n_files": 0, "src_bytes": 0,
                     "error": f"{type(e).__name__}: {e}"[:2000],
                     "seconds": 0,
                     "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            lf.write(json.dumps(r, ensure_ascii=False) + "\n")
            lf.flush()
            v = r.get("verify") or {}
            row = {"book": r["book"], "ok": r["ok"], "n_files": r["n_files"],
                   "seconds": r.get("seconds"), "stage": r.get("stage"),
                   "mode": v.get("mode"), "chapters": v.get("n_chapters"),
                   "chapter_source": v.get("chapter_source"),
                   "src_bytes": r.get("src_bytes"), "out_bytes": r.get("out_bytes"),
                   "finished_at": r.get("finished_at")}
            if r["ok"]:
                ok += 1
                bytes_done += r["src_bytes"]
                saved += r["src_bytes"] - r.get("out_bytes", r["src_bytes"])
                recent.append(row)
                print(f"  [{i}/{len(books)}] OK   {r['book']}  "
                      f"{r['n_files']}f  {r['src_bytes']/1e6:.0f}->"
                      f"{r.get('out_bytes',0)/1e6:.0f} MB  "
                      f"{v.get('mode','?')}  {v.get('n_chapters','?')}ch  "
                      f"{r['seconds']}s")
            else:
                fail += 1
                bytes_done += r["src_bytes"]
                row["error"] = r.get("error", "")[:400]
                recent.append(row)
                failures.append(row)
                print(f"  [{i}/{len(books)}] FAIL {r['book']}  "
                      f"({r['stage']}) {r.get('error','')[:160]}")
            finished_n[0] = i
            write_progress(a.progress, snapshot(i))
    done_evt.set()
    final = snapshot(len(books))
    final["complete"] = True
    write_progress(a.progress, final)
    print(f"\ndone: {ok} merged, {fail} failed, "
          f"{saved/1e9:+.2f} GB change, log: {a.log}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
