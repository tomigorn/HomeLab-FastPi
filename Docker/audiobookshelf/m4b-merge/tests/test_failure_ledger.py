#!/usr/bin/env python3
"""
Regression tests for the failure ledger - the thing that stops a book that
cannot merge from being retried forever.

WHAT WENT WRONG WITHOUT IT
--------------------------
main() already refuses to wake beefy for nothing:

    # Return BEFORE touching beefy. [...] an idle trigger must not power a
    # machine on to discover there is nothing to do.
    if not books:
        print("nothing to merge")
        return 0

That guard is correct and it never fired, because find_books() had no memory of
failure. Four books that could not merge stayed candidates forever, so `books`
was never empty, so every library event - ours or Audiobookshelf's - turned into
a full ~20-minute beefy grind. Between 2026-09-28 09:07 and 2026-10-05 00:39
beefy never slept once: 6 days 15 hours awake, ~480 attempts per book, runs
restarting in the same second they exited.

The ledger gives find_books() that memory. A parked book makes `books` empty,
the existing guard fires, and beefy is simply never contacted.

The ledger is keyed by a FINGERPRINT of the book's audio files, so it expires
itself the moment the sources actually change - repair or replace a damaged file
and the book gets a fresh chance with no bookkeeping. Cover art and metadata are
deliberately not part of it: Audiobookshelf rewrites those, and that is no
reason to re-attempt a merge that failed on the audio.

Run: ./tests/test_failure_ledger.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_orchestrate(lib, quarantine):
    spec = importlib.util.spec_from_file_location(
        "orch", os.path.join(HERE, "orchestrate.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.LIB, m.QUARANTINE = lib, quarantine
    return m


def book(lib, name, files):
    d = os.path.join(lib, "EN", "Author", name)
    os.makedirs(d, exist_ok=True)
    for f, body in files.items():
        with open(os.path.join(d, f), "w") as fh:
            fh.write(body)
    return d


FAILS = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILS.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="ledger-test-")
    try:
        lib = os.path.join(tmp, "lib")
        os.makedirs(lib)
        m = load_orchestrate(lib, os.path.join(tmp, "q"))
        led = os.path.join(tmp, "failures.json")

        for fn in ("book_fingerprint", "ledger_load", "ledger_save",
                   "ledger_blocked", "ledger_record", "ledger_clear"):
            if not hasattr(m, fn):
                print(f"FAIL: orchestrate.py has no {fn}()")
                return 1

        # ---- fingerprint identity -------------------------------------
        b = book(lib, "Damaged", {"01.mp3": "a" * 100, "02.mp3": "b" * 100,
                                  "cover.jpg": "x"})
        fp1 = m.book_fingerprint(b)
        check(fp1 == m.book_fingerprint(b), "fingerprint is stable")

        with open(os.path.join(b, "cover.jpg"), "w") as fh:
            fh.write("totally different cover")
        check(m.book_fingerprint(b) == fp1,
              "cover art does not change the fingerprint")

        with open(os.path.join(b, "02.mp3"), "w") as fh:
            fh.write("b" * 250)                       # the file got replaced
        fp2 = m.book_fingerprint(b)
        check(fp2 != fp1, "replacing an audio file changes the fingerprint")

        with open(os.path.join(b, "03.mp3"), "w") as fh:
            fh.write("c" * 100)                       # a part was added
        check(m.book_fingerprint(b) != fp2,
              "adding an audio file changes the fingerprint")

        # ---- parking rules --------------------------------------------
        check(m.ledger_load(led) == {}, "a missing ledger loads as empty")
        check(not m.ledger_blocked(m.ledger_load(led), "EN/Author/Damaged", fp1),
              "an unknown book is never blocked")

        rel = "EN/Author/Damaged"
        for n in range(1, m.FAIL_MAX_ATTEMPTS):
            m.ledger_record(led, rel, fp1, "merge", "SOURCE FILES DAMAGED ...")
            check(not m.ledger_blocked(m.ledger_load(led), rel, fp1),
                  f"attempt {n} of {m.FAIL_MAX_ATTEMPTS} still gets a retry")

        m.ledger_record(led, rel, fp1, "merge", "SOURCE FILES DAMAGED ...")
        d = m.ledger_load(led)
        check(m.ledger_blocked(d, rel, fp1),
              f"parked after {m.FAIL_MAX_ATTEMPTS} failures")
        check(d[rel]["attempts"] == m.FAIL_MAX_ATTEMPTS,
              "attempts counted correctly")
        check(d[rel]["error"].startswith("SOURCE FILES DAMAGED"),
              "the reason is kept for the human to read")
        check("first_failed" in d[rel] and "last_failed" in d[rel],
              "first and last failure times are recorded")

        # The whole point: new sources get a fresh chance, automatically.
        check(not m.ledger_blocked(d, rel, "a-different-fingerprint"),
              "changed sources un-park the book without manual cleanup")
        m.ledger_record(led, rel, "newfp", "merge", "different failure")
        check(m.ledger_load(led)[rel]["attempts"] == 1,
              "a new fingerprint resets the attempt count")

        # ---- a success must forget the past ---------------------------
        m.ledger_clear(led, rel)
        check(rel not in m.ledger_load(led), "a successful merge clears the entry")
        m.ledger_clear(led, "never-seen")      # must not raise
        check(True, "clearing an absent entry is harmless")

        # ---- survives a corrupt file rather than killing a run --------
        with open(led, "w") as fh:
            fh.write("{ this is not json")
        check(m.ledger_load(led) == {}, "a corrupt ledger loads as empty")

        print()
        if FAILS:
            print(f"{len(FAILS)} failure(s)")
            return 1
        print("all ledger cases pass")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
