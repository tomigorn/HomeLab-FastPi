# m4b-merge — merge multi-file audiobooks into one chaptered `.m4b`

Multi-file books download ~3.5x slower than single-file ones (measured
2026-09-26: 14.3 MB/s across 71 requests vs 50.6 MB/s for one file), because the
app fetches tracks strictly sequentially and every track restarts TCP slow
start. Merging each book into a single chaptered `.m4b` removes that, and fixes
the VBR-MP3 seek bug at the same time.

**All transcoding runs on beefy. fastpi only orchestrates and never encodes.**

## How to run

```bash
./orchestrate.py --dry-run --include-multipart   # list what would be merged
./orchestrate.py --jobs 10 --include-multipart   # the real run
./orchestrate.py --only "Shogun"                 # a single book, by substring
./restore-book.py --list                         # what can be undone
./restore-book.py "Diamond Dogs"                 # undo one book
./stale-verification.py                          # books verified by old code
./tests/test_find_books.py                       # crash-state classification
```

Progress is visible at **http://192.168.1.2:8099/** (LAN only) while a run is
going; `runs/progress.json` is what it reads.

The run is **resumable and idempotent**: a folder that is already a single audio
file is skipped, so re-running picks up wherever it stopped. A folder left in a
half-promoted state is *never* re-merged — see "Crash safety" below.

## What happens to each book

1. fastpi rsyncs the book's audio files and cover to `beefy:~/m4b-work/staging/`.
2. beefy concatenates them into one `.m4b`, cover art attached, `+faststart` so
   the moov atom is at the front (better for streaming). Chapters come from the
   sources' **own embedded chapter tables** where they have them, expanded onto
   the merged timeline; a source that declares none becomes one chapter titled
   from its filename. Merging a 2-part book whose parts hold 9 chapters each
   yields 18 chapters, not 2.
3. beefy runs the full verification below.
4. fastpi md5s the result on beefy, pulls it, and md5s it locally — the bytes
   kept are provably the bytes that passed verification.
5. Only then are the originals **moved** to
   `/mnt/seagate-black/m4b-originals-quarantine/<same relative path>` and the
   `.m4b` put in their place.

Nothing is ever deleted. Any failure at any step leaves the book completely
untouched and the run moves on to the next one.

## Merge modes

| Mode | When | Why |
|---|---|---|
| `copy` | every source is AAC with the same rate/channels (the multi-part `.m4b`/`.m4a` sets) | stream copy: **bit-identical audio**, no second lossy generation, seconds instead of hours |
| `encode` | MP3 and friends | AAC at the sources' duration-weighted average bitrate |
| `encode-filter` | AAC sources whose rates differ | the concat *demuxer* would hand 11 kHz packets to a 22 kHz decoder and produce a file half the right length; the concat *filter* decodes and resamples each part instead |

`--mode` overrides the choice. Copy mode was verified by decoding the sources and
the output to raw PCM and comparing md5 — identical.

## Verification — all eight must pass

| Check | What it proves |
|---|---|
| `decode` | a complete decode of the output emits no ffmpeg errors and *measures* the audio present — catches truncation and corruption |
| `duration` | measured output length equals the sum of the measured source lengths, within `max(0.5s, 0.01s x files)` |
| `chapters` | the planned chapter table is present in full, monotonic, and its last chapter ends where the audio actually ends |
| `streams` | exactly one AAC audio stream, channel count and sample rate as intended |
| `tags` | a title is present |
| `size` | audio bytes (excluding the cover) are plausible for the bitrate and duration |
| `content` | **every chapter by default**: the loudness *envelope* of the output at that chapter matches the envelope of the source slice it claims to be (Pearson r >= 0.8). Catches reordering, substitution and silence. A slice that is silent in the output but not in the source fails |
| `mux` | ffmpeg emitted no timestamp warnings. "non monotonically increasing dts" is what a mislaid concat timeline looks like, and it means audio was dropped |

`duration` and `decode` are real measurements, not metadata: with `+faststart`
the declared duration survives truncation, so reading it back would prove
nothing. `chapters` compares against the planned table rather than the file
count, because embedded tables expand to more chapters than files.

Sampling only a handful of chapters was a real weakness — on a 185-file book
five samples cover under 3%, and a swap between two *unsampled* tracks passed
everything. `--samples 0` (the default) checks them all.

Per-book JSON reports land in `runs/run.jsonl`; live progress in
`runs/progress.json`.

## Crash safety

The promote is the only destructive step, and only ever a `rename(2)` within one
filesystem. Two guards make an interrupted promote impossible to mistake for a
normal book:

- a `.m4b-merge-promoting` marker exists for the duration of the promote, and
- `find_books()` refuses any folder holding that marker, any `*.m4b.part`
  (including rsync's own `..slug.m4b.part.XXXXXX` temp), or **both an `.m4b` and
  loose tracks** — the state a crash leaves between installing the `.m4b` and
  moving the last original out.

That last one matters: without it, such a folder looks exactly like a legitimate
multi-part book, and re-merging it produces a book containing all of its audio
**twice** while every check passes, because they all measure the same doubled
set. `tests/test_find_books.py` covers all of these.

The orchestrator also refuses to promote when beefy merged a different number of
files than the Pi is about to quarantine. Every check on beefy measures its own
set against itself, so this is the only thing that compares what was merged with
what is about to be moved away.

Books whose folder mixes two editions (a complete unabridged rip, or a separate
dramatisation, sitting beside the chapter files) are refused rather than merged
into a book containing the novel twice: any single file holding more than 25% of
a >=5-file book's runtime trips it.

## Encoder settings

Bitrate, channel count and sample rate are **read from each book and matched,
never upscaled** — the library mixes 32, 64, 96 and 128 kbit and both mono and
stereo. AAC at a given bitrate beats MP3 at the same one, so matching keeps the
added generational loss small while never inflating the file.

The default `twoloop` AAC coder is kept deliberately. `-aac_coder fast` measured
2.8x quicker (163x vs 59x realtime) for 4% more size, but this is a permanent
replacement for the library copy, so quality wins over a few hours of unattended
runtime. `-threads` makes no difference — ffmpeg's AAC encoder is
single-threaded, which is why throughput comes from running many books at once
rather than from threading one.

## Notes and gotchas

- **ffmpeg on beefy is a static build in `~/bin`.** beefy has no ffmpeg package,
  no passwordless sudo and `buntu` is not in the `docker` group, so a static
  binary in the home directory is the zero-privilege way in.
- **SSH is deliberately not multiplexed.** One shared connection caps out at
  sshd's `MaxSessions` (10), which is fewer than the jobs we run. Separate
  connections have no such ceiling. `HostName` is pinned to `192.168.1.102`
  because parallel lookups of `beefy.homelab` fail intermittently under load —
  that, not multiplexing, was the actual fix.
- **beefy's idle watcher runs with `DRY_RUN=0`** and powers the host off after
  15 minutes idle. Do not rely on a run holding it awake: its probes ignore
  port 22 *and* the NVMe the work dir lives on, so only CPU >15% counts, and it
  really has powered off mid-job. The orchestrator therefore *recovers* rather
  than prevents — `wake_remote()` detects an unreachable host, POSTs to
  Beefy-Waker and retries the book. To prevent it outright you need root on
  beefy (`buntu`'s only NOPASSWD entry is `systemctl poweroff`), so before a
  long unattended run, by hand:

      ssh beefy 'sudo touch /run/beefy-keep-awake'   # and rm it afterwards
- **ABS's file watcher is disabled** (`scannerDisableWatcher: 1`), so merged
  books do not appear until a library scan is triggered from the ABS UI
  (Settings -> Libraries -> scan). API keys are JWTs and are not recoverable
  from the database, so this step needs a human or a freshly created key.
- **Seeding is unaffected.** The torrents seed from
  `/mnt/seagate-red/qbittorrent/downloads/complete` on a different physical
  disk, with no hardlinks into the library, and qBittorrent has no mount for
  the library disk at all. Merging the library copy cannot touch them.

## Quarantine

`/mnt/seagate-black/m4b-originals-quarantine` holds every original track, under
the same relative path as in the library. It is not inside the ABS library root,
so ABS never scans it. Delete it only once the merged books have been played and
you are happy — `restore-book.py` needs it.
