#!/usr/bin/env python3
"""
Regression tests for decode_verdict() - the output's full-decode gate.

THE BUG THESE EXIST TO PREVENT
------------------------------
build() sorts every SOURCE file into one of two buckets by MEASURED loss:

  * `damaged`        - lost more than max_loss seconds. The merge stops dead,
                       because merging would bake a hole and shifted chapters
                       into the result.
  * `minor_glitches` - the decoder complained but essentially nothing was lost.
                       The merge DELIBERATELY PROCEEDS and records the file.

A decoder complaint is a property of the bytes in the source, and a stream copy
carries it into the output verbatim. So an output gate of "no decoder errors at
all" rejects precisely the books the pre-flight deliberately accepted - such a
book can never merge, no matter how many times it is retried.

That is not hypothetical. "Tom Clancy - Op Center 06 State Of Seige" was retried
481 times between 2026-09-28 and 2026-10-05, each attempt holding beefy awake,
and every attempt failed like this:

  pre-flight  minor_glitches: [{001-004.m4b, held 7933.59, decoded 7933.72,
                                lost -0.12, errors ["Input buffer exhausted
                                before END element found", ...]}]   -> TOLERATED
  output      decode: ok=false "decoded 16333.46s of 16333.46s; 2 error(s):
                      ['Input buffer exhausted before END element found', ...]"

Identical error. Zero measured loss. Tolerated on the way in, fatal on the way
out, forever.

So the output is judged the way the sources are judged: by MEASURED loss.
Decoder errors are reported, never fatal on their own - lost audio cannot hide
from the duration, chapter and per-chapter content-correlation checks, which is
where it is actually caught.

Run: ./tests/test_decode_verdict.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AAC_ERRS = [
    "[aac @ 0xf48d240] Input buffer exhausted before END element found",
    "[aist#0:0/aac @ 0xf3ee800] [dec:aac @ 0xf48c780] Error submitting packet "
    "to decoder: Invalid data found when processing input",
]
TNS_ERRS = [
    "[aac @ 0x13e99f40] TNS filter order 23 is greater than maximum 12.",
    "[aist#0:0/aac @ 0x13d962c0] [dec:aac @ 0x13d98f80] Error submitting packet "
    "to decoder: Invalid data found when processing input",
]
GLITCH = [{"file": "Tom Clancy - Op Center 06 State Of Seige 1999 001-004.m4b",
           "held": 7933.59, "decoded": 7933.72, "lost": -0.12,
           "errors": AAC_ERRS}]


def load_merge_book():
    spec = importlib.util.spec_from_file_location(
        "mb", os.path.join(HERE, "merge-book.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# (name, decoded, expected, errs, source_glitches, tol, expect_ok)
CASES = [
    # --- the two real books that looped ~480 times each -------------------
    # Carried-over source glitch: pre-flight tolerated the identical error.
    ("state-of-seige-real",   16333.46, 16333.46, AAC_ERRS, GLITCH, 0.5,  True),
    # Clean MP3 sources, one bad frame in the encoded output, zero loss,
    # content correlation 0.998 over 14/14 chapters.
    ("way-of-shadows-real",   56513.77, 56513.75, TNS_ERRS, [],     0.5,  True),

    # --- the happy path ---------------------------------------------------
    ("clean",                 16333.46, 16333.46, [],       [],     0.5,  True),
    ("clean-decoded-a-hair-more", 100.02, 100.00, [],       [],     0.5,  True),

    # --- real loss MUST still be caught, errors or not --------------------
    ("truncated-hard",         1000.0,  16333.46, [],       [],     0.5,  False),
    ("truncated-with-errors",  1000.0,  16333.46, AAC_ERRS, [],     0.5,  False),
    ("decoded-nothing",            0.0,  16333.46, AAC_ERRS, [],     0.5,  False),
    # A glitched source does NOT buy a free pass on real loss.
    ("glitched-but-truncated", 8000.0,  16333.46, AAC_ERRS, GLITCH, 0.5,  False),

    # --- the max_loss boundary, which must match the pre-flight's ---------
    # build() rejects on `loss > max_loss`, so exactly max_loss passes.
    ("loss-just-under",      16332.76, 16333.46, [],       [],     0.5,  True),
    ("loss-exactly-max",     16332.46, 16333.46, [],       [],     0.5,  True),
    ("loss-just-over",       16332.26, 16333.46, [],       [],     0.5,  False),

    # --- a many-file book's duration tolerance must not be undercut -------
    # tol = max(0.5, n*0.01); a 185-file book gets 1.85s, so the decode gate
    # must not fail at 1.5s while the duration check happily passes it.
    ("big-book-within-tol",  56512.25, 56513.75, [],       [],     1.85, True),
]


def check_carried_label(m):
    """The 'carried over from a glitched source' label must actually fire.

    ffmpeg stamps every message with the decoder's heap address, and that
    address differs on every run - the real source glitch was logged as
    `[aac @ 0x1760ed00] ...` and the real output error as `[aac @ 0xef18240] ...`.
    Comparing the raw strings would therefore always claim the error was "not
    present in the sources", which is the opposite of the truth.
    """
    bad = 0
    src_errs = ["[aac @ 0x1760ed00] Input buffer exhausted before END element found"]
    out_errs = ["[aac @ 0xef18240] Input buffer exhausted before END element found"]
    glitch = [{"file": "part1.m4b", "lost": -0.12, "errors": src_errs}]

    ok, detail = m.decode_verdict(100.0, 100.0, out_errs, max_loss=1.0, tol=0.5,
                                 source_glitches=glitch)
    if ok and "carried over from a glitched source" in detail:
        print("  ok   same error at a different heap address reads as carried over")
    else:
        print(f"  FAIL heap address defeated the carried-over label: {detail}")
        bad += 1

    # A genuinely new error must NOT be excused by an unrelated source glitch.
    ok, detail = m.decode_verdict(
        100.0, 100.0, ["[aac @ 0xdeadbeef] TNS filter order 23 is greater than "
                       "maximum 12."],
        max_loss=1.0, tol=0.5, source_glitches=glitch)
    if ok and "not present in the sources" in detail:
        print("  ok   an unrelated error is not excused by a source glitch")
    else:
        print(f"  FAIL wrongly blamed the sources: {detail}")
        bad += 1
    return bad


def main():
    m = load_merge_book()
    if not hasattr(m, "decode_verdict"):
        print("FAIL: merge-book.py has no decode_verdict()")
        return 1

    bad = 0
    for name, decoded, expected, errs, glitches, tol, want in CASES:
        ok, detail = m.decode_verdict(decoded, expected, errs,
                                      max_loss=1.0, tol=tol,
                                      source_glitches=glitches)
        status = "ok " if ok == want else "FAIL"
        if ok != want:
            bad += 1
        print(f"  {status} {name:28s} want_ok={str(want):5s} got_ok={str(ok):5s}"
              f"  {detail}")

        # The detail must always state the measurement, so a human reading
        # run.jsonl can see WHY without re-running anything.
        if f"{decoded:.2f}" not in detail or f"{expected:.2f}" not in detail:
            print(f"       FAIL {name}: detail omits the measured numbers")
            bad += 1
        # An error that was tolerated must still be visible, never swallowed.
        if errs and ok and "error" not in detail.lower():
            print(f"       FAIL {name}: tolerated errors are not reported")
            bad += 1

    bad += check_carried_label(m)

    print()
    if bad:
        print(f"{bad} failure(s)")
        return 1
    print(f"all {len(CASES)} case(s) + the carried-over label pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
