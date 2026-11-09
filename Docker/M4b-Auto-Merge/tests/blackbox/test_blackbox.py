#!/usr/bin/env python3
"""Black-box tests for the watcher: start the command in $WATCHER against a scratch library under /tmp with a fake orchestrator, act on the files, read its log and the fake's call record.
Run with tests/blackbox/run.sh IMAGE (inside a ctest container, this folder at /t)."""
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, "fake-merge")
NOEXEC = os.path.join(HERE, "fake-noexec")
WATCHER = shlex.split(os.environ.get("WATCHER", "python3 /app/watcher.py"))
SCRATCH = os.environ.get("SCRATCH", "/tmp/bb")
QUIET = 2
RETRY = 3
POLL_SLACK = 35          # the Python watcher re-checks every 30 s; a faster implementation is fine too
LEGACY = "watcher.py" in os.environ.get("WATCHER", "")
LINE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d  \S")

os.environ["TZ"] = "Europe/Zurich"
time.tzset()


def next_sweep(dow, hour, minute, now):
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target += timedelta(days=(dow - now.weekday()) % 7)
    if target <= now:
        target += timedelta(days=7)
    return target


def far_dow():
    return (datetime.now().weekday() + 3) % 7


def touch_file(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "ab") as f:
        f.write(data)


class Watcher:
    def __init__(self, name, files=(), merge_dir=FAKE, lib=None, **env):
        self.root = os.path.join(SCRATCH, name)
        os.makedirs(self.root)
        self.lib = lib or os.path.join(self.root, "lib")
        if lib is None:
            os.makedirs(self.lib)
        for f in files:
            touch_file(os.path.join(self.lib, f))
        e = dict(os.environ)
        e.update(LIB_DIR=self.lib, MERGE_DIR=merge_dir, QUIET_SECONDS=str(QUIET), RETRY_SECONDS=str(RETRY), JOBS="7",
                 SWEEP_DOW=str(far_dow()), SWEEP_HOUR="4", SWEEP_MINUTE="0", FAKE_DIR=self.root, FAKE_MARK="mark-" + name)
        e.update({k: str(v) for k, v in env.items()})
        self.lines = []
        self.cond = threading.Condition()
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen(WATCHER, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            with self.cond:
                self.lines.append((time.monotonic(), line.rstrip("\n")))
                self.cond.notify_all()

    def write(self, rel, data=b"x"):
        touch_file(os.path.join(self.lib, rel), data)
        return time.monotonic()

    def control(self, name, value):
        with open(os.path.join(self.root, name), "w") as f:
            f.write(value)

    def wait_for(self, pattern, timeout, start=0):
        """(index, receive time) of the first line from index `start` on matching `pattern`."""
        rx = re.compile(pattern)
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                for i in range(start, len(self.lines)):
                    if rx.search(self.lines[i][1]):
                        return i, self.lines[i][0]
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError(f"no line matching {pattern!r} within {timeout}s; log:\n" + self.log())
                self.cond.wait(left)

    def count(self, pattern):
        rx = re.compile(pattern)
        with self.cond:
            return sum(1 for _, l in self.lines if rx.search(l))

    def log(self):
        with self.cond:
            return "\n".join(l for _, l in self.lines)

    def calls(self):
        try:
            with open(os.path.join(self.root, "calls")) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def stop(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


class Base(unittest.TestCase):
    def watcher(self, *a, **kw):
        w = Watcher(self.id().rsplit(".", 1)[-1], *a, **kw)
        self.addCleanup(w.stop)
        return w

    def idle(self, w, start=0):
        return w.wait_for(r"  trigger: nothing to merge$", QUIET + POLL_SLACK, start)


class Startup(Base):
    def test_missing_library_exits_1(self):
        w = self.watcher(lib=os.path.join(SCRATCH, "does-not-exist"))
        self.assertEqual(w.proc.wait(15), 1)
        w.wait_for(r"  library .*/does-not-exist is not a directory$", 5)

    def test_missing_orchestrator_exits_1(self):
        w = self.watcher(merge_dir=HERE)
        self.assertEqual(w.proc.wait(15), 1)
        w.wait_for(r"  orchestrator not found at " + re.escape(HERE + "/orchestrate.py") + "$", 5)

    def test_startup_lines(self):
        dow = far_dow()
        w = self.watcher(SWEEP_DOW=dow, SWEEP_HOUR=5, SWEEP_MINUTE=7, JOBS=9, QUIET_SECONDS=11, RETRY_SECONDS=13)
        w.wait_for("  watching " + re.escape(w.lib) + "$", 10)
        w.wait_for(r"  quiet period 11s, 9 parallel jobs, retry 13s$", 10)
        exp = next_sweep(dow, 5, 7, datetime.now()).isoformat(timespec="minutes")
        w.wait_for(r"  weekly sweep scheduled for " + re.escape(exp) + "$", 10)
        for l in w.log().splitlines():
            self.assertRegex(l, LINE)

    def test_startup_with_empty_library_does_nothing(self):
        w = self.watcher()
        i, t = self.idle(w)
        self.assertGreaterEqual(t - w.t0, QUIET - 0.5)
        self.assertEqual(w.calls(), [])

    def test_startup_with_waiting_book_runs_orchestrator(self):
        w = self.watcher(files=["Author/Book/01.mp3", "Author/Book/02.mp3"])
        i, _ = w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK)
        w.wait_for(r"^FAKE-ORCHESTRATOR-OUTPUT$", 10, i)
        w.wait_for(r"  merge run finished cleanly$", 10, i)
        self.assertEqual(w.calls(), [f"cwd={FAKE} args=--jobs 7 --include-multipart env=mark-test_startup_with_waiting_book_runs_orchestrator"])

    def test_stop_while_idle(self):
        w = self.watcher()
        self.idle(w)
        w.proc.send_signal(signal.SIGTERM)
        w.proc.wait(5)


class Triggers(Base):
    def test_new_book_after_startup(self):
        w = self.watcher()
        i, _ = self.idle(w)
        w.write("EN/Author/Series/01 - Book/01.mp3")
        last = w.write("EN/Author/Series/01 - Book/02.mp3")
        j, t = w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK, i + 1)
        self.assertGreaterEqual(t - last, QUIET - 0.5)
        w.wait_for(r"  merge run finished cleanly$", 10, j)
        self.assertEqual(len(w.calls()), 1)

    def test_quiet_period_restarts_on_every_write(self):
        w = self.watcher(QUIET_SECONDS=4)
        i, _ = w.wait_for(r"  trigger: nothing to merge$", 4 + POLL_SLACK)
        last = None
        for n in range(8):
            last = w.write(f"Book/{n:02}.mp3", b"y" * 1000)
            time.sleep(1)
        j, t = w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", 4 + POLL_SLACK, i + 1)
        self.assertGreaterEqual(t - last, 4 - 0.5)
        self.assertEqual(w.count(r"  trigger: "), 2)

    def test_reads_do_not_arm(self):
        w = self.watcher(files=["Book/only.mp3", "Book/cover.jpg"])
        self.idle(w)
        end = time.monotonic() + QUIET + POLL_SLACK
        while time.monotonic() < end:
            for f in ("Book/only.mp3", "Book/cover.jpg"):
                with open(os.path.join(w.lib, f), "rb") as fh:
                    fh.read()
            os.listdir(os.path.join(w.lib, "Book"))
            os.stat(os.path.join(w.lib, "Book/only.mp3"))
            time.sleep(0.5)
        self.assertEqual(w.count(r"  trigger: "), 1)
        w.write("Book/second.mp3")
        w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK)

    def test_delete_arms(self):
        w = self.watcher(files=["Book/a.mp3", "Book/notes.txt"])
        i, _ = self.idle(w)
        os.remove(os.path.join(w.lib, "Book/notes.txt"))
        self.idle(w, i + 1)

    def test_new_directory_is_watched(self):
        w = self.watcher()
        i, _ = self.idle(w)
        os.makedirs(os.path.join(w.lib, "A/B/C"))
        i, _ = self.idle(w, i + 1)
        w.write("A/B/C/01.mp3")
        w.write("A/B/C/02.mp3")
        w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK, i + 1)

    def test_directory_moved_in_is_watched(self):
        w = self.watcher()
        i, _ = self.idle(w)
        outside = os.path.join(w.root, "incoming/Book")
        touch_file(os.path.join(outside, "Part/01.mp3"))
        touch_file(os.path.join(outside, "Part/02.mp3"))
        os.rename(os.path.join(w.root, "incoming"), os.path.join(w.lib, "incoming"))
        w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK, i + 1)

    @unittest.skipIf(LEGACY, "legacy gap: watchdog does not watch the subfolders of a tree moved in; only the weekly sweep finds those books")
    def test_tree_moved_in_is_watched_deep(self):
        w = self.watcher()
        i, _ = self.idle(w)
        outside = os.path.join(w.root, "incoming/Book")
        touch_file(os.path.join(outside, "Part/01.mp3"))
        touch_file(os.path.join(outside, "Part/02.mp3"))
        os.rename(os.path.join(w.root, "incoming"), os.path.join(w.lib, "incoming"))
        i, _ = w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK, i + 1)
        w.wait_for(r"  merge run finished cleanly$", 10, i)
        w.write("incoming/Book/Part/03.mp3")
        i, _ = w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK, i + 1)
        w.wait_for(r"  merge run finished cleanly$", 10, i)
        w.write("incoming/Book/Other/01.mp3")
        w.write("incoming/Book/Other/02.mp3")
        w.wait_for(r"  trigger: 2 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK, i + 1)


class Candidates(Base):
    def test_markers_skip_folders(self):
        files = []
        for book in ("Good1", "Good2", "Nested/Good3"):
            files += [f"{book}/01.mp3", f"{book}/02.mp3"]
        for book, marker in (("Part", "03.mp3.part"), ("Qb", "03.mp3.!qB"), ("Chrome", "x.crdownload"), ("Tmp", "x.TMP"),
                             ("Filepart", "x.filepart"), ("Promote", ".m4b-merge-promoting"), ("Rsync", "..book.m4b.part.Ab12")):
            files += [f"{book}/01.mp3", f"{book}/02.mp3", f"{book}/{marker}"]
        w = self.watcher(files=files)
        w.wait_for(r"  trigger: 3 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK)

    def test_audio_extension_rules(self):
        files = ["01.mp3", "02.mp3",                                # the library root itself counts
                 "Upper/01.MP3", "Upper/02.Mp3",
                 "Mixed/a.m4a", "Mixed/b.flac",
                 "Open/a.ogg", "Open/b.opus",
                 "Wave/a.wav", "Wave/b.m4b",
                 "Parent/01.mp3", "Parent/02.mp3", "Parent/Child/01.mp3", "Parent/Child/02.mp3",
                 "Single/01.mp3", "Single/cover.jpg", "Single/info.txt", "Single/x.aac",
                 "Dotfile/.mp3", "Dotfile/a.mp3",
                 "Dotdot/..mp3", "Dotdot/a.mp3",
                 ".hidden/01.mp3", ".hidden/02.mp3", ".hidden/Sub/01.mp3", ".hidden/Sub/02.mp3",
                 "Visible/.trash/01.mp3", "Visible/.trash/02.mp3"]
        w = self.watcher(files=files)
        w.wait_for(r"  trigger: 7 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK)

    def test_symlinks(self):
        files = ["Real/01.mp3", "Real/02.mp3", "Links/01.mp3"]
        w_lib = os.path.join(SCRATCH, "symlink-lib")
        os.makedirs(w_lib)
        for f in files:
            touch_file(os.path.join(w_lib, f))
        os.symlink(os.path.join(w_lib, "Real/01.mp3"), os.path.join(w_lib, "Links/02.mp3"))
        os.symlink(os.path.join(w_lib, "Real"), os.path.join(w_lib, "Links/DirLink.mp3"))
        os.makedirs(os.path.join(w_lib, "Broken"))
        os.symlink(os.path.join(w_lib, "nowhere.mp3"), os.path.join(w_lib, "Broken/a.mp3"))
        os.symlink(os.path.join(w_lib, "nowhere2.mp3"), os.path.join(w_lib, "Broken/b.mp3"))
        os.makedirs(os.path.join(w_lib, "Via"))
        os.symlink(os.path.join(w_lib, "Real"), os.path.join(w_lib, "Via/real-link"))
        w = self.watcher(lib=w_lib)
        # Real, Links (a file link counts, a dir link does not), Broken (dangling links count as files); Via/real-link is not descended
        w.wait_for(r"  trigger: 3 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK)


class Orchestrator(Base):
    BOOK = ["Book/01.mp3", "Book/02.mp3"]

    def test_lock_held_retries_without_new_event(self):
        w = self.watcher(files=self.BOOK)
        w.control("rcseq", "3\n0\n")
        i, t1 = w.wait_for(r"  another merge run holds the lock; retrying in 3s$", QUIET + POLL_SLACK)
        j, t2 = w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", RETRY + POLL_SLACK, i + 1)
        self.assertGreaterEqual(t2 - t1, RETRY - 0.5)
        w.wait_for(r"  merge run finished cleanly$", 10, j)
        self.assertEqual(len(w.calls()), 2)

    def test_failed_books_are_not_retried(self):
        w = self.watcher(files=self.BOOK)
        w.control("rcseq", "1\n")
        w.wait_for(r"  orchestrator exited 1 \(some books failed\); see runs/run.jsonl$", QUIET + POLL_SLACK)
        time.sleep(RETRY + POLL_SLACK)
        self.assertEqual(len(w.calls()), 1)
        self.assertEqual(w.count(r"  trigger: "), 1)

    def test_killed_orchestrator_reports_negative_signal(self):
        w = self.watcher(files=self.BOOK)
        w.control("sleep", "30")
        w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK)
        deadline = time.monotonic() + 10
        pid = None
        while pid is None and time.monotonic() < deadline:
            for p in os.listdir("/proc"):
                if p.isdigit():
                    try:
                        with open(f"/proc/{p}/cmdline", "rb") as f:
                            cmd = f.read()
                        with open(f"/proc/{p}/environ", "rb") as f:
                            env = f.read()
                    except OSError:
                        continue
                    if b"orchestrate.py" in cmd and b"FAKE_MARK=mark-test_killed_orchestrator_reports_negative_signal\0" in env:
                        pid = int(p)
            time.sleep(0.2)
        self.assertIsNotNone(pid)
        os.kill(pid, signal.SIGKILL)
        w.wait_for(r"  orchestrator exited -9 \(some books failed\); see runs/run.jsonl$", 10)

    def test_unstartable_orchestrator_retries(self):
        w = self.watcher(files=self.BOOK, merge_dir=NOEXEC)
        msg = r"  could not start the orchestrator: \[Errno 13\] Permission denied: '" + re.escape(NOEXEC + "/orchestrate.py") + "'$"
        i, t1 = w.wait_for(msg, QUIET + POLL_SLACK)
        _, t2 = w.wait_for(msg, RETRY + POLL_SLACK, i + 1)
        self.assertGreaterEqual(t2 - t1, RETRY - 0.5)

    def test_promote_does_not_feed_itself(self):
        w = self.watcher(files=self.BOOK)
        w.control("promote", "Book")
        i, _ = w.wait_for(r"  merge run finished cleanly$", QUIET + POLL_SLACK)
        self.idle(w, i + 1)
        time.sleep(RETRY + 5)
        self.assertEqual(len(w.calls()), 1)
        self.assertTrue(os.path.exists(os.path.join(w.lib, "Book/merged.m4b")))

    def test_change_during_run_rearms(self):
        w = self.watcher(files=self.BOOK)
        w.control("sleep", "4")
        i, _ = w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK)
        time.sleep(1)
        w.write("Second/01.mp3")
        w.write("Second/02.mp3")
        j, _ = w.wait_for(r"  merge run finished cleanly$", 15, i)
        w.wait_for(r"  trigger: 2 candidate folder\(s\) - starting merge$", QUIET + POLL_SLACK, j + 1)


class Sweep(Base):
    def test_schedule_edges(self):
        now = datetime.now()
        if now.hour in (0, 23):
            self.skipTest("too close to midnight for same-day cases")
        cases = {"passed_today": (now.weekday(), now.hour - 1, 0), "later_today": (now.weekday(), now.hour + 1, 30),
                 "tomorrow": ((now.weekday() + 1) % 7, 0, 5), "this_minute": (now.weekday(), now.hour, now.minute)}
        ws = {}
        for name, (d, h, m) in cases.items():
            ws[name] = Watcher(f"edge-{name}", SWEEP_DOW=d, SWEEP_HOUR=h, SWEEP_MINUTE=m)
            self.addCleanup(ws[name].stop)
        for name, (d, h, m) in cases.items():
            exp = next_sweep(d, h, m, datetime.now()).isoformat(timespec="minutes")
            ws[name].wait_for(r"  weekly sweep scheduled for " + re.escape(exp) + "$", 10)

    def test_sweep_fires_without_any_change(self):
        now = datetime.now()
        at = (now + timedelta(minutes=2 if now.second > 45 else 1)).replace(second=0, microsecond=0)
        w = self.watcher(files=["Book/01.mp3", "Book/02.mp3"], QUIET_SECONDS=100000,
                         SWEEP_DOW=at.weekday(), SWEEP_HOUR=at.hour, SWEEP_MINUTE=at.minute)
        w.wait_for(r"  weekly sweep scheduled for " + re.escape(at.isoformat(timespec="minutes")) + "$", 10)
        i, _ = w.wait_for(r"  trigger: 1 candidate folder\(s\) - starting merge$", 140)
        self.assertGreaterEqual(datetime.now(), at)
        self.assertEqual(w.count(r"  trigger: "), 1)
        nxt = (at + timedelta(days=7)).isoformat(timespec="minutes")
        w.wait_for(r"  weekly sweep scheduled for " + re.escape(nxt) + "$", 100, i)


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    tests = list(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    flat = [t for suite in tests for t in suite]
    if len(sys.argv) > 1:
        flat = [t for t in flat if any(a in t.id() for a in sys.argv[1:])]
    results = []

    def run(t):
        r = unittest.TestResult()
        start = time.monotonic()
        t.run(r)
        return t, r, time.monotonic() - start

    with ThreadPoolExecutor(max_workers=len(flat) or 1) as ex:
        for t, r, secs in ex.map(run, flat):
            name = t.id().split(".", 1)[1]
            status = "ok" if r.wasSuccessful() and not r.skipped else ("skip" if r.skipped else "FAIL")
            print(f"{status:4}  {secs:5.1f}s  {name}", flush=True)
            for _, tb in r.failures + r.errors:
                print(tb, flush=True)
            results.append(r)
    failed = sum(len(r.failures) + len(r.errors) for r in results)
    print(f"\n{len(flat)} tests, {failed} failed, {sum(len(r.skipped) for r in results)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
