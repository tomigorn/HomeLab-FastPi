#!/usr/bin/env python3
"""
Undo a merge: move the quarantined original tracks back into the library folder
and remove the generated .m4b. The merge never deletes anything, so this is a
complete reversal.

  ./restore-book.py --list
  ./restore-book.py "Diamond Dogs"        # substring match
  ./restore-book.py --all
"""
import argparse
import os
import sys

LIB = "/mnt/seagate-black/library/audiobooks"
QUARANTINE = "/mnt/seagate-black/m4b-originals-quarantine"


def quarantined_books():
    out = []
    for root, dirs, files in os.walk(QUARANTINE):
        if files and not any(os.path.isdir(os.path.join(root, d)) for d in dirs):
            out.append(os.path.relpath(root, QUARANTINE))
    return sorted(out)


def restore(rel, dry=False):
    qdir = os.path.join(QUARANTINE, rel)
    bdir = os.path.join(LIB, rel)
    if not os.path.isdir(qdir):
        return False, f"no quarantine dir for {rel}"
    if not os.path.isdir(bdir):
        return False, f"library folder is gone: {bdir}"
    originals = sorted(f for f in os.listdir(qdir)
                       if os.path.isfile(os.path.join(qdir, f)))
    if not originals:
        return False, f"quarantine dir is empty: {qdir}"
    m4bs = [f for f in os.listdir(bdir) if f.lower().endswith(".m4b")]
    if dry:
        return True, f"would restore {len(originals)} file(s), remove {m4bs}"
    for f in originals:
        dst = os.path.join(bdir, f)
        if os.path.exists(dst):
            return False, f"refusing to overwrite existing {dst}"
    for f in originals:
        os.rename(os.path.join(qdir, f), os.path.join(bdir, f))
    for f in m4bs:
        os.remove(os.path.join(bdir, f))
    # rmdir, NOT removedirs: removedirs walks upward and would delete the
    # quarantine root itself once the last book came out of it.
    d = qdir
    while os.path.abspath(d).startswith(os.path.abspath(QUARANTINE) + os.sep):
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)
    return True, f"restored {len(originals)} file(s), removed {len(m4bs)} .m4b"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("match", nargs="*", help="substring of the book path")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    books = quarantined_books()
    if a.list:
        print(f"{len(books)} book(s) with quarantined originals:")
        for b in books:
            n = len(os.listdir(os.path.join(QUARANTINE, b)))
            print(f"  [{n:>3}] {b}")
        return 0

    if a.all:
        targets = books
    elif a.match:
        targets = [b for b in books
                   if any(m.lower() in b.lower() for m in a.match)]
    else:
        ap.error("give a substring, or --all, or --list")

    if not targets:
        print("nothing matched")
        return 1
    rc = 0
    for b in targets:
        ok, msg = restore(b, dry=a.dry_run)
        print(f"  {'OK  ' if ok else 'FAIL'} {b}: {msg}")
        if not ok:
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
