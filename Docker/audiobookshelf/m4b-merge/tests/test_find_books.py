#!/usr/bin/env python3
"""
Regression tests for find_books() classification.

Every case here is a state a crashed promote can really leave on disk. The one
that matters most is "installed .m4b + leftover originals": nothing else on disk
marks it, it looks exactly like a legitimate multi-part book, and merging it
produces a book containing all of its audio TWICE while every verification check
passes - because they all measure the same doubled set.

Run: ./tests/test_find_books.py
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
    for f in files:
        with open(os.path.join(d, f), "w") as fh:
            fh.write("x" * 1024)
    return d


CASES = [
    # (folder name, files, expected bucket)
    ("normal-mp3",        ["01.mp3", "02.mp3", "03.mp3"],            "candidate"),
    ("pure-multipart",    ["p1.m4b", "p2.m4b", "p3.m4b"],            "candidate"),
    ("already-done",      ["Book.m4b"],                              "ignored"),
    # --- crash states: every one of these must be reported, never merged ---
    ("crash-after-install", ["Book.m4b", "02.mp3", "03.mp3"],        "interrupted"),
    ("crash-with-marker", ["01.mp3", "02.mp3", ".m4b-merge-promoting"],
                                                                     "interrupted"),
    ("crash-part-only",   [".slug.m4b.part"],                        "interrupted"),
    ("crash-one-orig",    ["01.mp3", ".slug.m4b.part"],              "interrupted"),
    ("crash-rsync-temp",  ["01.mp3", "02.mp3", "..slug.m4b.part.AbC123"],
                                                                     "interrupted"),
    ("crash-m4b-plus-one", ["Book.m4b", "03.mp3"],                   "interrupted"),
]


def main():
    tmp = tempfile.mkdtemp(prefix="m4b-findbooks-")
    lib, quar = os.path.join(tmp, "lib"), os.path.join(tmp, "quar")
    os.makedirs(lib), os.makedirs(quar)
    try:
        o = load_orchestrate(lib, quar)
        for name, files, _ in CASES:
            book(lib, name, files)

        cands = o.find_books(include_multipart=True)
        cand_names = {os.path.basename(p) for p in cands}
        interrupted = {os.path.basename(p)
                       for p in getattr(o.find_books, "interrupted", [])}

        failures = []
        for name, _, expect in CASES:
            got = ("candidate" if name in cand_names else
                   "interrupted" if name in interrupted else "ignored")
            mark = "ok  " if got == expect else "FAIL"
            if got != expect:
                failures.append(f"{name}: expected {expect}, got {got}")
            print(f"  [{mark}] {name:<22} -> {got}")

        # The dangerous case deserves an explicit assertion of its own.
        if "crash-after-install" in cand_names:
            failures.append("crash-after-install was returned as a MERGE "
                            "CANDIDATE - this is the double-audio bug")

        print()
        if failures:
            print(f"{len(failures)} FAILURE(S):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print(f"all {len(CASES)} cases classified correctly")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
