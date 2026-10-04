# Runaway merge loop — beefy awake 6 days 15 hours

**Found** 2026-10-05 01:00 · **Fixed** 2026-10-05 · **Power wasted** ~6.6 days of a
machine that should have been asleep, most of it under full `ffmpeg` load.

## Symptom

beefy never powered off. Its boot journal shows the idle watcher working
perfectly for months, then stopping dead:

| Session | Duration |
|---|---|
| Aug 2 – Aug 21 (6 sessions) | 2m – 45m each — the watcher doing its job |
| Sep 27 16:10 → Sep 28 00:30 | 8h 20m — the big 263-book batch, expected |
| **Sep 28 09:07 → Oct 5 00:39** | **6 days 15h 32m** — the runaway |

Grafana was no help: telegraf has no beefy input, and neither `fastpi-resources`
nor `languagetool-watch` references it. `journalctl --list-boots` on beefy (which
is what the Beefy-Waker wake page's history panel reads) is the real record.

## Root cause — two bugs, compounding

### 1. `find_books()` had no memory of failure

`main()` has always refused to wake beefy for nothing:

```python
# Return BEFORE touching beefy. [...] an idle trigger must not power a
# machine on to discover there is nothing to do.
if not books:
    print("nothing to merge")
    return 0
```

That guard is right, and it never fired. Four books could not merge, so they
stayed candidates forever, so `books` was never empty. **Every** library event —
ours or Audiobookshelf rewriting metadata — therefore became a full ~20-minute
grind on beefy. Runs restarted in the *same second* they exited:

```
2026-10-04T23:39:11  orchestrator exited 2 (some books failed)
2026-10-04T23:39:11  trigger: 4 candidate folder(s) - starting merge
```

`run.jsonl` grew to 4.4 MB recording **~480 attempts per book**.

### 2. The output decode gate contradicted the pre-flight

`build()` deliberately sorts sources into `damaged` (measured loss > `max_loss`
→ refuse to merge) and `minor_glitches` (decoder complained, nothing measurably
lost → **merge anyway, on purpose**). But `verify()` gated the output on:

```python
checks["decode"] = {"ok": not errs and covered, ...}
```

Any decoder error failed it. A stream copy carries a source's complaints into the
output verbatim, so **every `minor_glitches` book was guaranteed to fail
verification** — designed to proceed, designed to be rejected. Unwinnable.

*Op Center 06 State Of Seige* is the proof, with the identical error string on
both sides:

```
pre-flight  minor_glitches: [{001-004.m4b, held 7933.59, decoded 7933.72,
                              lost -0.12, errors ["Input buffer exhausted
                              before END element found", ...]}]   -> TOLERATED
output      decode ok=false "decoded 16333.46s of 16333.46s; 2 error(s):
                            ['Input buffer exhausted before END element', ...]"
```

Zero measured loss. `content` passed at 2/2 chapters, 100% coverage, r=1.000.
All seven other checks passed. Rejected 481 times on a cosmetic signal — and it
violated the project's own rule, *"verification must MEASURE, never read back."*

## The four books

| Book | Verdict |
|---|---|
| `Op Center/06 - State Of Seige` | **Gate bug.** Zero loss, r=1.000. Merged fine once fixed |
| `Night Angel/01 - The Way of Shadows` | **Gate bug.** Zero loss (−0.02s), r=0.998 over 14/14 chapters |
| `Jack Ryan/01 - Patriot Games` | **Genuinely damaged source** — parked |
| `Jack Ryan/04 - Cardinal Of The Kremlin` | **Genuinely damaged source** — parked |

## Needs a human: two damaged books

These are **not** script bugs — the pre-flight is correct to refuse them, and
merging would bake a silent hole and shifted chapters into the result. One source
part in each is essentially entirely undecodable:

| Book | File | Lost |
|---|---|---|
| `EN/Tom Clancy/Jack Ryan/01 - Patriot Games` | `...Patriot Games 1987 001-010.m4b` | 25867.43s of 25874.72s |
| `EN/Tom Clancy/Jack Ryan/04 - Cardinal Of The Kremlin` | `...Cardinal Of The Kremlin 1988 010-019.m4b` | 23293.05s of 23308.0s |

**That audio is already unplayable in the library today, merge or no merge** —
roughly 7.2 h and 6.5 h respectively. ffmpeg cannot decode those parts, so
Audiobookshelf cannot play them either. This predates the merge tooling; the
merge only surfaced it.

Both are parked in `runs/failures.json` with their real history (480 attempts
each, first seen 2026-09-27). Originals are **untouched** — nothing was deleted
or quarantined. To act:

* **Re-download** the broken part, or the book. Dropping a replacement file in
  changes the fingerprint, which un-parks the book automatically — no cleanup.
* **Or accept it** and leave it parked. It will never be retried and never wake
  beefy again.
* **Or verify by hand**: `ffmpeg -v error -i "<part>" -f null -` on beefy.

## Fixes applied

1. `merge-book.py` — new `decode_verdict()`; the output is judged by **measured
   loss** against `max(max_loss, tol)`, never stricter than the pre-flight that
   let the book through nor than the `duration` check reading the same
   measurement. Decoder errors are reported, and labelled as carried over from a
   glitched source or not, but never fatal alone. `max_loss` is now carried in
   the plan so `verify()` uses the same value `build()` did.
   Pinned by `tests/test_decode_verdict.py` (12 cases, both real books included).
2. `orchestrate.py` — failure ledger `runs/failures.json`. Three failures on
   unchanged sources parks a book; `process_retry()` already tries 3× per run, so
   that is ~9 real attempts. Keyed by a fingerprint of the audio files' name,
   size and mtime, so it **expires itself** when sources change. Cover art and
   metadata excluded, since Audiobookshelf rewrites those. A success clears the
   entry. Every run prints what it parked — never silent. `--retry-failed`
   overrides. Pinned by `tests/test_failure_ledger.py`.

With `books` finally able to reach empty, the existing guard does the rest:
beefy is never contacted, so it idles off after `IDLE_MINUTES=15` as designed.

## Do NOT re-merge the library over this

`stale-verification.py` marks a book stale when its `merger_md5` is not the md5 of
the current `merge-book.py`, so editing the merger makes **all 495 merged books
report as stale**. Ignore it here.

The new gate is **strictly more permissive** than the old one: the old test was
`not errs and decoded >= expected - tol`, the new one is
`expected - decoded <= max(max_loss, tol)`, and `max(max_loss, tol) >= tol`. Every
book that passed the old gate therefore passes the new one — verified
exhaustively over 200,000 randomised cases, zero counterexamples. Nothing that
was accepted before is now in question, so there is no reason to restore and
re-merge anything. Doing so would cost days of beefy time for no gain.

## Still open

* **`/usr/local/sbin/beefy-keep-awake` is not installed on beefy**, so every run
  logs `holding beefy awake with an interactive session (... not available)` and
  falls back to an interactive SSH session. That works, but it is the wrong lever:
  an interactive session is precisely the signal the idle watcher uses for "a
  human is present", which is why its log reads `BUSY (ssh)` with nobody there,
  and a leaked session would pin beefy awake with no visible inhibit file. The
  helper exists in this folder and needs one sudo install + one sudoers line.
  **Requires the user at the keyboard** — see [`beefy-keep-awake`](../beefy-keep-awake).
* **An aborted run leaks work that holds beefy awake — deliberately left alone.**
  Stopping the auto-merge container killed the orchestrator on fastpi but left its
  `ffmpeg` running on beefy (observed tonight: PID 13671, still re-encoding after
  its parent was gone). Worse, SIGTERM kills the orchestrator without running the
  `finally` that calls `KeepAwake.__exit__`, so **once the helper below is
  installed, a `docker stop` mid-run would leave `/run/beefy-keep-awake` in place
  and beefy would never sleep again** until someone removed it by hand.

  The obvious fix — trap SIGTERM and let the existing `finally` run — is *not*
  safe as a one-liner: `_run()` exits through a `ThreadPoolExecutor` context
  manager, which waits for in-flight futures, so a clean shutdown would block
  `docker stop` for up to ~20 minutes and then be SIGKILLed anyway, leaving the
  same orphans. Doing this properly needs a way to abort an in-flight book
  (cancel the futures and kill the remote `ffmpeg`), which is a design decision,
  not a patch. Left for a deliberate change rather than bundled in at 02:00.

  Mitigation until then: prefer letting a run finish; after any forced stop, check
  `ssh beefy 'pgrep -af "[f]fmpeg"'` and `ls /run/beefy-keep-awake`.
* The watcher's `candidates()` keeps its own cheap rule and does not read the
  ledger, so it still starts the orchestrator on a library event. That is now
  harmless — the orchestrator exits in seconds without contacting beefy — but the
  container log line `trigger: N candidate folder(s)` overstates what will happen.
* Nothing surfaces parked books on the dashboard at `http://192.168.1.2:8099/`;
  `runs/failures.json` has to be read directly.
