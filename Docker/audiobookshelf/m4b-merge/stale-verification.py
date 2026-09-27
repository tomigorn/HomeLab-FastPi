#!/usr/bin/env python3
"""
List merged books whose verification was produced by a superseded merge-book.py.

Every report records the md5 of the merger that wrote it (`merger_md5`). A book is
stale when that md5 is not the md5 of the current merge-book.py - which is the only
honest marker: any content-based guess ("does the report have field X") silently
under-reports, because fields are added before the bugs they relate to are fixed.

A stale book is not necessarily wrong, but it was not checked by the code we
currently trust, so it should be restored and merged again.

  ./stale-verification.py             # list
  ./stale-verification.py --restore   # restore them so a normal re-run redoes them
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "runs/run.jsonl")
QUARANTINE = "/mnt/seagate-black/m4b-originals-quarantine"
MERGER = os.path.join(HERE, "merge-book.py")


def main():
    with open(MERGER, "rb") as fh:
        current = hashlib.md5(fh.read()).hexdigest()

    latest = {}
    with open(LOG) as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("ok"):
                latest[d["book"]] = d          # last successful report wins

    stale, fresh, gone = [], [], []
    for book, d in latest.items():
        if not os.path.isdir(os.path.join(QUARANTINE, book)):
            gone.append(book)                  # already restored, or never promoted
            continue
        md5 = (d.get("verify") or {}).get("merger_md5")
        (fresh if md5 == current else stale).append((book, md5))

    print(f"current merge-book.py : {current}")
    print(f"{len(latest)} merged book(s) in the log: "
          f"{len(fresh)} verified by current code, {len(stale)} stale, "
          f"{len(gone)} not currently promoted")
    if stale:
        print("\nstale (verified by superseded code, will be restored):")
        for book, md5 in sorted(stale):
            print(f"  [{(md5 or 'no stamp')[:12]}] {book}")

    if "--restore" not in sys.argv:
        if stale:
            print(f"\n{len(stale)} book(s) to redo. Pass --restore to put the "
                  f"originals back so a normal run re-merges them.")
        return 0

    if not stale:
        print("\nnothing to restore")
        return 0

    print(f"\nrestoring {len(stale)} book(s):")
    failed = 0
    for book, _ in sorted(stale):
        r = subprocess.run([os.path.join(HERE, "restore-book.py"), book],
                           capture_output=True, text=True)
        out = (r.stdout.strip() or r.stderr.strip()).replace("\n", " ")
        if r.returncode != 0:
            failed += 1
            print(f"  FAILED {book}: {out[:200]}")
        else:
            print(f"  {out[:200]}")
    print(f"\nrestored {len(stale) - failed}, failed {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
