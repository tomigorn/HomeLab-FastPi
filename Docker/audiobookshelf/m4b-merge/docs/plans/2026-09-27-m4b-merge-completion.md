# M4B Merge Completion Plan

**Goal:** A reviewed, independently-tested pipeline that merges every multi-file
audiobook in the Audiobookshelf library into one chaptered `.m4b` — beefy doing all
transcoding — with no loss of audio time, chapters, or quality, plus a LAN-only
progress dashboard, then run it across the whole library.

**Architecture:** `orchestrate.py` on fastpi walks the library, rsyncs each book to
beefy, beefy's `merge-book.py` merges + self-verifies (7 measured checks), the result
is pulled back md5-verified, and only then do the originals move to quarantine. A
`progress.json` written by the orchestrator is served read-only by a caddy container
bound to the LAN.

**Tech stack:** Python 3 stdlib only, ffmpeg/ffprobe, rsync over ssh, caddy:alpine.

---

## Context: state inherited from the previous session

Verified against the live filesystem on 2026-09-27:

- 59 books were merged and promoted, then a review found the merge was laying audio
  out on ffprobe's *estimated* timeline while building chapters on the *decoded*
  timeline. Audio was silently dropped at file boundaries. Those 59 are unsafe and
  their originals are all still in quarantine (2920 files).
- The blockers were fixed and validated: the previously-172s-short book now merges
  with `diff 0.01s`, and 5 adversarial tests (reorder, 70%/95% truncation, payload
  corruption) are all rejected. A reordered book is caught at `r=-0.318`.
- Library integrity confirmed clean: 0 folders contain both an `.m4b` and loose
  tracks, 0 orphan `.part` files, so no promote was ever interrupted.
- Not yet done: the health-gate false-positive check, the multipart books, the
  dashboard, the fresh review, the restore of the 59, and the full run.

## Scope decisions (made without the user, who is offline)

1. **Multipart `.m4b`/`.m4a` sets (69 books, 38.9 GB) merge by stream copy, not
   re-encode.** They are "not yet single file audiobooks" so they are in scope, but
   re-encoding AAC→AAC is a second lossy generation, which the goal forbids. Stream
   copy is lossless and fast. If parts are codec-incompatible the book is refused
   for manual review rather than silently re-encoded.
2. **Chapters are taken from the parts' embedded chapter tables when they have
   them**, offset by cumulative duration, falling back to one chapter per file.
   Collapsing a 2-part book with 15 internal chapters each into 2 chapters would be
   "loss in chapters", which the goal forbids.
3. **Executed inline, not via subagents**, because the remaining work is a set of
   interdependent changes to two files whose failure modes are known in this
   session's context. The independent verification the user asked for is supplied by
   a fresh review agent given a clean brief, per Task 7.

---

## File structure

| File | Responsibility |
|---|---|
| `merge-book.py` | Runs on beefy. Merge one book + self-verify. Gains a lossless stream-copy path and embedded-chapter preservation. |
| `orchestrate.py` | Runs on fastpi. Library walk, staging, promote, logging. Gains `.part`-guard, progress output, multipart routing. |
| `restore-book.py` | Reverse a merge. Unchanged. |
| `stale-verification.py` | Find books verified by superseded code. Rewritten to key off `merger_md5`. |
| `../../M4b-Merge-Dashboard/` | New Docker project: caddy serving the static progress page, LAN-only. |

---

### Task 1: Close the open health-gate verification

The damage gate was refusing two healthy books because it compared ffprobe's
bitrate *estimate* against the decoded duration. It now compares the *packet*
timeline against the decoded duration. This was never confirmed on the books it
wrongly refused.

**Files:** none modified — this is a verification task.

- [ ] Run the gate's own measurement over every source file of
      `1994 - The Commodore (Aubrey-Maturin 17)` and `1981 - The Ionian Mission
      (Aubrey-Maturin 8)` on beefy
- [ ] Expected: `held - decoded` under 1.0 s for every file, i.e. 0 damaged. The old
      gate reported a suspiciously uniform 16.42 s on 6 files and ~39.6 s on 8,
      which is the signature of estimate error, not damage
- [ ] If any file is genuinely damaged, record which and let the book fail honestly

### Task 2: Guard against interrupted promotes in `find_books`

**Files:** Modify `orchestrate.py`

A promote that dies between moving originals and installing the `.m4b` would leave a
subset of tracks. The next run would merge the subset, pass every check against it,
and promote a truncated book — silent loss that looks verified. The `.part` file is
the marker that this happened.

- [ ] In `find_books`, skip any folder containing a `*.m4b.part` and collect them
- [ ] In `main`, print those folders loudly as needing manual attention
- [ ] Verify: create `/tmp/fakebook/.x.m4b.part` + 2 mp3s, point `find_books` at it,
      confirm it is excluded and reported

### Task 3: Lossless stream-copy path for multipart books

**Files:** Modify `merge-book.py`

- [ ] Add `streams_compatible(infos)`: true when every part shares codec, sample
      rate and channel count
- [ ] Add `--mode {auto,encode,copy}`; `auto` picks copy when every input is already
      `aac` and compatible, else encode
- [ ] In copy mode, build the concat list as today but run with `-c:a copy` and no
      `-b:a`/`-ar`/`-ac`
- [ ] Refuse with a clear error when copy was requested but parts are incompatible
- [ ] Verify on the smallest multipart book, output to `/tmp`, library untouched

### Task 4: Preserve embedded chapters

**Files:** Modify `merge-book.py`

- [ ] Add `read_chapters(path)` returning `[(start_s, end_s, title)]` from
      `ffprobe -show_chapters`
- [ ] When building the chapter table, expand each source file into its own
      chapters offset by the cumulative start; fall back to one chapter per file
      when a file declares none
- [ ] Keep the `content` check anchored to a chapter whose source offset is known,
      so the envelope comparison stays valid
- [ ] Verify: a 2-part book with internal chapters yields the sum of both tables,
      and a plain mp3 book still yields one chapter per file

### Task 5: Rewrite `stale-verification.py` around `merger_md5`

**Files:** Rewrite `stale-verification.py`

Its current marker is "the report has a `minor_glitches` key", which was already true
before the real fixes landed, so it under-reports. All 59 promoted books are stale.

- [ ] Compare each report's `merger_md5` against the current `merge-book.py` md5
- [ ] Treat a missing `merger_md5` as stale
- [ ] `--restore` restores every stale book so a normal re-run re-merges it
- [ ] Verify: it lists exactly 59 before any restore

### Task 6: Progress dashboard

**Files:** Create `../../M4b-Merge-Dashboard/{docker-compose.yaml,.env,.env.example,.gitignore,README.md,Caddyfile,www/index.html}`, modify `orchestrate.py`

- [ ] Orchestrator writes `runs/progress.json` after every completed book: totals,
      counts, bytes, per-book rows, current in-flight books, start time, ETA
- [ ] Static page polls it every 5 s and renders progress, throughput and failures
- [ ] caddy:alpine, bound to the LAN address only, no Traefik route, no auth
- [ ] Verify: `curl` the page and the JSON from fastpi, confirm the port is not
      reachable from outside the LAN and not routed publicly

### Task 7: Fresh-eyes review and test

- [ ] Dispatch a review agent with a clean brief: the goal, the code, the library,
      and permission to test on the smallest book. It is told nothing about which
      bugs existed before, so its findings are independent
- [ ] It must build a deliberately broken output and confirm the checks reject it
- [ ] Triage every finding; fix real ones; re-verify

### Task 8: Smallest-book end-to-end test

- [ ] Restore one small book from quarantine, merge it through the real orchestrator
      with `--only`, confirm promote, chapters, duration and playability
- [ ] Confirm `restore-book.py` puts it back exactly

### Task 9: Restore the 59 and launch the full run

- [ ] `stale-verification.py --restore`
- [ ] Commit everything
- [ ] Launch the full run under `setsid`/`nohup` so it survives the session ending
- [ ] Confirm from fresh process state that it is running and the dashboard advances
