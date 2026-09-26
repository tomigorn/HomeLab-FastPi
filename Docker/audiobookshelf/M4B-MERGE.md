# Merging multi-file books to M4B — analysis, and why it is NOT done on the Pi

## Why it is worth doing

Measured 2026-09-26, real downloads over the Cloudflare tunnel to a phone on 5G:

| Book | Shape | Throughput | 2.9 GB would take |
|---|---|---|---|
| Saint's Blood | 1 file | **50.6 MB/s** (424 Mbit) | ~58 s |
| Shōgun | 71 requests | **14.3 MB/s** (120 Mbit) | 206 s (actual) |

**Multi-file books download ~3.5x slower.** Two structural causes, from Traefik's logs:

- The app downloads files **strictly sequentially** - overlap factor 0.86, i.e. not
  only no parallelism but 29 s of dead time between files across the book.
- Every file **restarts TCP slow start**. Best single file hit 71.3 MB/s, median
  only 22.5 MB/s. Short files finish before the connection is up to speed.

The library is **265 multi-file vs 232 single-file** books, so this affects more
than half of it. Merging would also fix the VBR-MP3 seek bug.

## Why it is not run here

**Measured on this Pi:** one 360 MB / 76-file book took **over 12 minutes** at 100%
of one core, and was still going when it was stopped. Sources are 128 kbit MP3, so
this is a real AAC transcode, not a remux - there is no fast path.

Extrapolated across 265 books / 130.2 GB: **~74 hours of solid CPU**, on a machine
also running 53 containers.

**And it moves 130 GB onto the wrong disk.** `AbMergeManager` moves the original
tracks into `itemCachePath` = `/metadata/cache/items/<id>`, which is the bind mount
on the **NVMe root filesystem** (317 GB free), not the 1.8 TB Seagate the library
lives on. A bulk run would consume ~41% of the remaining OS-disk space. Filling the
root filesystem breaks everything on the host.

It is also **destructive to the library folder**: originals are moved out and
replaced by the single `.m4b`. Recoverable only from that cache, which is not a
backup.

## The plan

Do it as part of the **beefy migration**, where the CPU and the disk layout are
appropriate. When it happens:

1. Ensure the merge cache is on a disk with room - not the OS disk.
2. Batch it, do not run 265 at once. Verify playback and chapters on the first few.
3. Keep the originals until a merged book has been played end to end.
4. Expect hours even on better hardware; 128 kbit MP3 -> AAC is a real transcode.

Triggering: `POST /api/tools/item/{id}/encode-m4b` (admin only). Note that with
local password auth disabled, this needs an API key rather than a session.
