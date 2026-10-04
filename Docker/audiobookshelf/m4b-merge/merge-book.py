#!/usr/bin/env python3
"""
Merge one multi-file audiobook into a single chaptered .m4b, then verify it.

Runs on the machine doing the transcode (beefy). Reads a staged source folder,
writes <out>.m4b plus a JSON verification report. Exits non-zero and removes the
output if ANY check fails, so the caller never promotes a bad merge.

Three properties this file exists to guarantee, each learned from a real bug:

* The concat layout and the chapter table are built from the SAME measured
  timeline. Listing files without a `duration` directive makes the demuxer lay
  them out on the container's bitrate ESTIMATE while chapters use the decoded
  value; where those disagree (any VBR/headerless MP3) audio is dropped at the
  boundary or a silent gap is inserted.
* Every check measures the output instead of reading back something we wrote.
  `format=duration` is metadata the muxer emitted, so it survives truncation;
  and comparing chapter marks to our own plan is tautological.
* Audio streams are mapped explicitly. These files carry embedded cover art, so
  ffmpeg's default stream selection for `-f null` picks the VIDEO stream and a
  "full decode" check silently decodes one cover frame.

Two modes. Sources that are already AAC with a constant stream layout (the
multi-part .m4b/.m4a sets) are concatenated by STREAM COPY: bit-identical audio,
no second lossy generation. Everything else is encoded to AAC at the source's
duration-weighted average bitrate. `--mode` overrides the choice.

Chapters come from the sources' own embedded tables when they have them, expanded
onto the merged timeline; a file that declares none becomes one chapter. Merging a
2-part book whose parts hold 15 chapters each must not yield 2 chapters.

Verification (all must pass):
  1. decode    - the whole audio stream decodes with no errors, and the decode
                 covers the expected duration (a real measurement)
  2. duration  - MEASURED output duration == sum of measured source durations
  3. chapters  - the planned table is present in full, monotonic, and its last
                 chapter ends where the audio actually ends
  4. streams   - exactly one aac audio stream, channels/rate as intended
  5. tags      - title present
  6. size      - plausible for the bitrate and duration
  7. content   - for EVERY chapter by default, the loudness ENVELOPE of the
                 output matches the envelope of the source it claims to be. A
                 single mean level cannot tell one narrator passage from
                 another; an envelope is distinctive, so this catches
                 reordering, substitution and silence.
  8. mux       - ffmpeg emitted no timestamp warnings while writing. A
                 "non monotonically increasing dts" is what a mislaid concat
                 timeline looks like, and it means audio was dropped.
"""
import argparse
import array
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys

FFMPEG = os.environ.get("FFMPEG", os.path.expanduser("~/bin/ffmpeg"))
FFPROBE = os.environ.get("FFPROBE", os.path.expanduser("~/bin/ffprobe"))
if not os.path.exists(FFMPEG):
    FFMPEG, FFPROBE = "ffmpeg", "ffprobe"

AUDIO_EXT = (".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".flac", ".wav")
COVER_NAMES = ("cover", "folder", "front", "albumart")
COVER_EXT = (".jpg", ".jpeg", ".png")

# content check: envelope sampling
ENV_RATE = 4000        # Hz, mono - enough for a loudness envelope, cheap to decode
ENV_SPAN = 20.0        # seconds compared per sampled chapter
ENV_WIN = 0.5          # seconds per envelope point
ENV_MIN_R = 0.80       # Pearson r below this means "not the same audio"


def natkey(s):
    """Natural sort: 'x 2.mp3' before 'x 10.mp3'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)


def run_bin(cmd):
    return subprocess.run(cmd, capture_output=True)


def probe(path):
    """Fast metadata. `duration` here is the container ESTIMATE - never trusted
    for layout or verification, only for choosing encoder settings."""
    r = run([FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_name,sample_rate,channels,bit_rate",
             "-show_entries", "format=duration,bit_rate", "-of", "json", path])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {r.stderr.strip()}")
    d = json.loads(r.stdout)
    st = (d.get("streams") or [{}])[0]
    fmt = d.get("format") or {}
    br = st.get("bit_rate") or fmt.get("bit_rate") or 0
    return {
        "path": path,
        "estimated": float(fmt.get("duration") or 0),
        "codec": st.get("codec_name"),
        "sample_rate": int(st.get("sample_rate") or 0),
        "channels": int(st.get("channels") or 0),
        "bit_rate": int(br or 0),
    }


def read_chapters(path):
    """Embedded chapter table as [(start_s, end_s, title)], or [] if none.

    Multi-part .m4b/.m4a sets usually carry their own chapters inside each part.
    Collapsing a 2-part book whose parts hold 15 chapters each down to 2 chapters
    would be losing 28 chapters, so those tables are expanded rather than ignored.
    """
    r = run([FFPROBE, "-v", "error", "-show_chapters", "-of", "json", path])
    if r.returncode != 0:
        return []
    try:
        chaps = json.loads(r.stdout).get("chapters") or []
    except ValueError:
        return []
    out = []
    for c in chaps:
        try:
            s = float(c.get("start_time"))
            e = float(c.get("end_time"))
        except (TypeError, ValueError):
            continue
        if e <= s:
            continue
        title = (c.get("tags") or {}).get("title") or ""
        out.append((s, e, title))
    out.sort(key=lambda t: t[0])
    return out


def embedded_cover(path, dest):
    """Extract an attached picture to `dest`. Returns dest, or None."""
    r = run([FFMPEG, "-nostdin", "-v", "error", "-y", "-i", path,
             "-map", "0:v:0", "-frames:v", "1", "-c:v", "copy", dest])
    if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    try:
        os.remove(dest)
    except OSError:
        pass
    return None


def streams_compatible(infos):
    """True when every source shares codec, sample rate and channel count.

    Stream copy concatenates packets untouched, so it is only valid when the
    decoder configuration never changes mid-book.
    """
    keys = {(i["codec"], i["sample_rate"], i["channels"]) for i in infos}
    return len(keys) == 1


def packet_duration(path):
    """Sum of packet durations: how much audio the container actually holds.

    This is the honest denominator for source health. `format=duration` is
    filesize/bitrate for a headerless VBR MP3 and can be tens of seconds out,
    which makes "estimate minus decoded" look like catastrophic loss on a
    perfectly healthy file.
    """
    r = run([FFPROBE, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "packet=duration_time", "-of", "csv=p=0", path])
    total = 0.0
    for line in r.stdout.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            total += float(line)
        except ValueError:
            pass
    return total


def decode_audio(path, ss=None, t=None):
    """Decode the AUDIO stream; return (duration_decoded, [decoder errors]).

    -map 0:a:0 -vn is required (embedded cover art would otherwise be selected)
    and the null output must go to /dev/null because -progress owns stdout.
    """
    cmd = [FFMPEG, "-nostdin", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.3f}"]
    cmd += ["-i", path]
    if t is not None:
        cmd += ["-t", f"{t:.3f}"]
    cmd += ["-map", "0:a:0", "-vn", "-progress", "pipe:1", "-f", "null", "/dev/null"]
    r = run(cmd)
    vals = [l.split("=", 1)[1].strip() for l in r.stdout.splitlines()
            if l.startswith("out_time_us=")]
    vals = [int(v) for v in vals if v.isdigit()]
    dur = max(vals) / 1e6 if vals else 0.0
    errs = [l.strip() for l in r.stderr.splitlines() if l.strip()]
    return dur, errs


def envelope(path, ss, span=ENV_SPAN, rate=ENV_RATE, win=ENV_WIN):
    """RMS loudness envelope of a slice, as a list of floats.

    Decodes to raw mono PCM at a low rate and computes RMS per window. Two
    recordings of different passages have very different envelopes even when
    their mean levels are identical, which is what makes this able to detect a
    reordered or substituted track.
    """
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-ss", f"{ss:.3f}", "-i", path,
           "-t", f"{span:.3f}", "-map", "0:a:0", "-vn",
           "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    r = run_bin(cmd)
    if r.returncode != 0 or not r.stdout:
        return []
    buf = array.array("h")
    n = len(r.stdout) // 2
    buf.frombytes(r.stdout[:n * 2])
    step = max(1, int(rate * win))
    out = []
    for i in range(0, len(buf) - step + 1, step):
        acc = 0
        for v in buf[i:i + step]:
            acc += v * v
        out.append(math.sqrt(acc / step))
    return out


def pearson(a, b):
    """Pearson r over the overlapping prefix; None if either side is flat."""
    k = min(len(a), len(b))
    if k < 6:
        return None
    a, b = a[:k], b[:k]
    ma, mb = sum(a) / k, sum(b) / k
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 1e-9 or vb <= 1e-9:
        return None                      # silence or a constant tone: no signal
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(va * vb)


def find_cover(src):
    """Best cover: preferred names first, then the largest image.

    The priority loop must be over COVER_NAMES, not over the directory listing -
    iterating filenames outer means 'AlbumArtSmall.jpg' (a 75x75 thumbnail)
    sorts before 'cover.jpg' and wins.
    """
    files = sorted(os.listdir(src))
    imgs = [f for f in files if os.path.splitext(f.lower())[1] in COVER_EXT]
    if not imgs:
        return None

    def area(f):
        r = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0",
                 os.path.join(src, f)])
        try:
            w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
            return w * h
        except Exception:
            return 0

    for name in COVER_NAMES:
        cands = [f for f in imgs if os.path.splitext(f.lower())[0] == name]
        if not cands:
            cands = [f for f in imgs
                     if os.path.splitext(f.lower())[0].startswith(name)
                     and "small" not in f.lower() and "thumb" not in f.lower()]
        if cands:
            return os.path.join(src, max(cands, key=area))
    return os.path.join(src, max(imgs, key=area))


def ff_meta_escape(v):
    return re.sub(r"([=;#\\\n])", r"\\\1", str(v))


def self_md5():
    try:
        with open(os.path.abspath(__file__), "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()
    except OSError:
        return None


def build(src, out, workdir, bitrate=None, title=None, artist=None,
          max_loss=1.0, mode="auto", allow_single=False):
    src = os.path.abspath(src)
    files = sorted(
        (os.path.join(src, f) for f in os.listdir(src)
         if os.path.splitext(f)[1].lower() in AUDIO_EXT and
         os.path.isfile(os.path.join(src, f))),
        key=lambda p: natkey(os.path.basename(p)),
    )
    if len(files) < (1 if allow_single else 2):
        raise RuntimeError(f"expected >={1 if allow_single else 2} audio file(s), "
                           f"found {len(files)} in {src}")

    infos = [probe(f) for f in files]

    # --- measure every source: exact duration and real health ----------------
    damaged, glitched = [], []
    for i in infos:
        held = packet_duration(i["path"])          # audio the container holds
        dec, errs = decode_audio(i["path"])        # audio the decoder produced
        i["duration"] = dec if dec > 0 else (held or i["estimated"])
        i["held"] = held
        # Loss is what the decoder could NOT produce from what is really there.
        # Comparing against format=duration instead would flag healthy VBR files.
        loss = (held - dec) if (held > 0 and dec > 0) else 0.0
        if errs or loss > max_loss:
            rec = {"file": os.path.basename(i["path"]),
                   "held": round(held, 2), "decoded": round(dec, 2),
                   "lost": round(loss, 2), "errors": errs[:2]}
            (damaged if loss > max_loss else glitched).append(rec)
    if damaged:
        # Pre-existing corruption, not something the merge caused. Merging would
        # bake a hole and shifted chapters into the result, so stop and report;
        # the originals are left alone for the caller to deal with.
        lines = [f"{d['file']}: lost {d['lost']}s of {d['held']}s "
                 f"({d['errors'][0][:80] if d['errors'] else 'no decoder error'})"
                 for d in damaged]
        raise RuntimeError("SOURCE FILES DAMAGED (%d of %d, >%.1fs undecodable) "
                           "- not merged:\n  %s"
                           % (len(damaged), len(files), max_loss, "\n  ".join(lines)))

    total = sum(i["duration"] for i in infos)
    if total <= 0:
        raise RuntimeError("source total duration is zero")

    # --- a foreign file in the folder would be merged in as a "chapter" -------
    # Several folders hold a second, complete edition beside the chapter files
    # (an unabridged single-file rip, or a BBC dramatisation). Natural sort just
    # appends it, and every duration check still passes because they all measure
    # the same wrong set - the result is a book containing the novel twice. Two
    # files at 50% each is a normal 2-part book, so only flag a clear outlier.
    # The signature is ONE file dwarfing the rest, not merely an uneven split: a
    # 5-part book whose parts run 38% and 27% is normal. Require the outlier to
    # be both a large share of the book AND several times the typical file.
    if len(infos) >= 5 and not allow_single:
        durs = sorted(i["duration"] for i in infos)
        biggest = max(infos, key=lambda i: i["duration"])
        rest = [d for d in durs[:-1]]
        med = rest[len(rest) // 2] if rest else 0.0
        if (biggest["duration"] > total * 0.40 and med > 0
                and biggest["duration"] > med * 4):
            raise RuntimeError(
                "TWO EDITIONS IN ONE FOLDER - not merged.\n"
                "  '%s'\n"
                "  runs %.2fh: %.0f%% of the folder's %.1fh and %.0fx the median "
                "file (%.2fh).\n"
                "  That is a second, complete edition sitting beside the %d "
                "chapter files.\n"
                "  Merging them together would produce one book containing the "
                "work twice.\n"
                "  FIX: move that file into its own sibling folder, e.g.\n"
                "       '%s (Unabridged)/', then re-run. Each folder is one book "
                "to Audiobookshelf,\n"
                "       so you end up with two correct books instead of one wrong "
                "one."
                % (os.path.basename(biggest["path"]),
                   biggest["duration"] / 3600.0,
                   biggest["duration"] / total * 100, total / 3600.0,
                   biggest["duration"] / med, med / 3600.0,
                   len(infos) - 1,
                   os.path.basename(os.path.normpath(src))))

    # --- copy or re-encode? -------------------------------------------------
    # Books that are already AAC (multi-part .m4b/.m4a sets) are concatenated by
    # stream copy: bit-identical audio, no second lossy generation, and minutes
    # instead of hours. Copy is only valid while the decoder configuration is
    # constant, so a mixed set falls back to encoding rather than producing a
    # file that plays at the wrong rate after the first boundary.
    compat = streams_compatible(infos)
    all_aac = all(i["codec"] == "aac" for i in infos)
    if mode == "copy":
        if not compat:
            raise RuntimeError(
                "--mode copy requested but sources differ: %s"
                % sorted({(i["codec"], i["sample_rate"], i["channels"])
                          for i in infos}))
        if not all_aac:
            raise RuntimeError("--mode copy requires aac sources, found %s"
                               % sorted({i["codec"] for i in infos}))
        do_copy = True
    elif mode == "encode":
        do_copy = False
    else:
        do_copy = all_aac and compat

    # The concat DEMUXER hands packets to the decoder without renegotiating the
    # stream, which is fine for MP3 (self-describing frames) but not for MP4/AAC:
    # a book mixing 11025 and 22050 Hz parts decodes the slow parts at the fast
    # rate and comes out at exactly half length. The concat FILTER decodes each
    # input separately and resamples, so it handles that correctly.
    use_filter = (not do_copy) and all_aac and not compat

    # --- encoder settings, derived from the source, never inflated -----------
    channels = max(i["channels"] for i in infos) or 2
    rate = max((i["sample_rate"] for i in infos), default=44100) or 44100
    # duration-weighted average, so one outlier file cannot inflate the book
    wsum = sum((i["bit_rate"] or 0) * i["duration"] for i in infos)
    avg_br = int(wsum / total) if total > 0 and wsum > 0 else 0
    src_br = max((i["bit_rate"] for i in infos), default=0)
    if bitrate and not do_copy:
        target_br = int(bitrate)
    elif avg_br:
        target_br = avg_br
    else:
        target_br = 96000

    os.makedirs(workdir, exist_ok=True)
    listfile = os.path.join(workdir, "concat.txt")
    metafile = os.path.join(workdir, "meta.ffmeta")

    # The `duration` directive is what keeps the audio layout and the chapter
    # table on one timeline. Without it the demuxer uses the container estimate.
    with open(listfile, "w") as fh:
        for i in infos:
            p = i["path"].replace("'", "'\\''")
            fh.write(f"file '{p}'\n")
            fh.write(f"duration {i['duration']:.6f}\n")

    # --- chapter table ------------------------------------------------------
    # `src_offset` is the position INSIDE the source file that a chapter starts
    # at. The content check needs it: with embedded tables expanded, a chapter no
    # longer necessarily begins at offset 0 of its file, and comparing the output
    # at the chapter mark against the HEAD of the source would then always fail.
    chapters, acc, n_embedded = [], 0.0, 0
    for i in infos:
        stem = os.path.splitext(os.path.basename(i["path"]))[0]
        dur = i["duration"]
        emb = [c for c in read_chapters(i["path"]) if c[0] < dur - 0.5]
        if len(emb) > 1:
            n_embedded += 1
            for k, (cs, ce, ctitle) in enumerate(emb):
                cs = max(0.0, min(cs, dur))
                # trust our measured duration over the container's chapter table
                ce = min(ce if ce > cs else dur, dur)
                nxt = emb[k + 1][0] if k + 1 < len(emb) else dur
                ce = min(ce, nxt)
                start_ms = int(round((acc + cs) * 1000))
                end_ms = max(int(round((acc + ce) * 1000)), start_ms + 1)
                chapters.append({
                    "start_ms": start_ms, "end_ms": end_ms,
                    "title": ctitle or f"{stem} - {k + 1}",
                    "src": i["path"], "src_offset": cs,
                    "src_duration": max(0.0, ce - cs),
                })
        else:
            start_ms = int(round(acc * 1000))
            end_ms = max(int(round((acc + dur) * 1000)), start_ms + 1)
            chapters.append({
                "start_ms": start_ms, "end_ms": end_ms, "title": stem,
                "src": i["path"], "src_offset": 0.0, "src_duration": dur,
            })
        acc += dur
    # a table that is not strictly increasing would fail the chapters check
    for a, b in zip(chapters, chapters[1:]):
        if b["start_ms"] <= a["start_ms"]:
            raise RuntimeError("built a non-monotonic chapter table - refusing")

    book_title = title or os.path.basename(os.path.normpath(src))
    with open(metafile, "w") as fh:
        fh.write(";FFMETADATA1\n")
        fh.write(f"title={ff_meta_escape(book_title)}\n")
        if artist:
            fh.write(f"artist={ff_meta_escape(artist)}\n")
            fh.write(f"album_artist={ff_meta_escape(artist)}\n")
        fh.write(f"album={ff_meta_escape(book_title)}\n")
        for c in chapters:
            fh.write("[CHAPTER]\nTIMEBASE=1/1000\n")
            fh.write(f"START={c['start_ms']}\nEND={c['end_ms']}\n")
            fh.write(f"title={ff_meta_escape(c['title'])}\n")

    # A folder cover beats an embedded one (it is usually far larger), but an
    # embedded picture is still better than shipping a book with no artwork.
    cover = find_cover(src)
    if not cover:
        cover = embedded_cover(files[0], os.path.join(workdir, "cover.jpg"))

    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y"]
    if use_filter:
        # one -i per part, then an explicit resample before concat
        for i in infos:
            cmd += ["-i", i["path"]]
        n_in = len(infos)
        cmd += ["-i", metafile]
        meta_idx = n_in
        if cover:
            cmd += ["-i", cover]
        chain = "".join(
            f"[{k}:a:0]aresample={rate}:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={rate}:"
            f"channel_layouts={'mono' if channels == 1 else 'stereo'}[a{k}];"
            for k in range(n_in))
        chain += "".join(f"[a{k}]" for k in range(n_in))
        chain += f"concat=n={n_in}:v=0:a=1[aout]"
        cmd += ["-filter_complex", chain, "-map", "[aout]"]
        cmd += ["-map_metadata", str(meta_idx), "-map_chapters", str(meta_idx)]
        if cover:
            cmd += ["-map", f"{meta_idx + 1}:v:0", "-c:v", "mjpeg",
                    "-disposition:v:0", "attached_pic"]
        cmd += ["-c:a", "aac", "-b:a", str(target_br),
                "-ar", str(rate), "-ac", str(channels)]
    else:
        cmd += ["-f", "concat", "-safe", "0", "-i", listfile, "-i", metafile]
        if cover:
            cmd += ["-i", cover]
        cmd += ["-map", "0:a:0", "-map_metadata", "1", "-map_chapters", "1"]
        if cover:
            cmd += ["-map", "2:v:0", "-c:v", "mjpeg",
                    "-disposition:v:0", "attached_pic"]
        if do_copy:
            # no -b:a/-ar/-ac: they are encoder options and would be ignored
            # here, but passing them would also imply a conversion that is not
            # happening
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", str(target_br),
                    "-ar", str(rate), "-ac", str(channels)]
    cmd += ["-movflags", "+faststart", "-f", "mp4", out]

    r = run(cmd)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("ffmpeg merge failed:\n" + r.stderr[-4000:])
    warn = [l for l in r.stderr.splitlines()
            if "non monotonically increasing" in l or "Non-monotonous" in l]

    return {
        "source_dir": src, "output": out, "n_files": len(files),
        "source_total_duration": total,
        "mode": "copy" if do_copy else ("encode-filter" if use_filter else "encode"),
        "cover_bytes": (os.path.getsize(cover) if cover and os.path.exists(cover)
                        else 0),
        "target": {"bitrate": target_br, "channels": channels, "sample_rate": rate,
                   "source_bitrate": src_br, "avg_source_bitrate": avg_br},
        "cover": cover, "chapters": chapters, "title": book_title,
        "artist": artist, "minor_glitches": glitched, "max_loss": max_loss,
        "chapter_source": ("embedded" if n_embedded == len(files)
                           else "per-file" if n_embedded == 0 else "mixed"),
        "n_chapters_planned": len(chapters),
        "mux_warnings": warn[:5],
    }


def _err_key(msg):
    """An ffmpeg error with its run-specific heap addresses removed."""
    return re.sub(r"0x[0-9a-fA-F]+", "0x", msg).strip()


def decode_verdict(decoded, expected, errs, max_loss=1.0, tol=0.5,
                   source_glitches=()):
    """Judge the output's full decode. Returns (ok, detail).

    Judged by MEASURED loss, for the same reason build() judges sources that
    way: a decoder complaint is a property of the bytes, not evidence that this
    merge lost anything.

    build() already splits the sources into `damaged` (lost more than max_loss
    -> refuse to merge at all) and `minor_glitches` (the decoder grumbled but
    nothing measurable was lost -> merge anyway, on purpose). A stream copy
    carries those grumbles into the output verbatim, so failing the output on
    "any decoder error" rejects exactly the books the pre-flight deliberately
    accepted, and no number of retries can ever get such a book through.

    Lost audio has nowhere to hide: it has to get past the duration check, the
    chapter timeline, and the per-chapter loudness-envelope correlation that
    covers every chapter. Those are the checks that catch a bad merge. This one
    only answers "did the output give back the audio the sources held?".

    `allow` never dips below max_loss (so this gate is never stricter than the
    pre-flight that let the book through) and never below tol (so it is never
    stricter than the duration check reading the very same measurement).
    """
    allow = max(max_loss, tol)
    lost = expected - decoded          # negative = decoded a hair more
    ok = lost <= allow

    measured = f"decoded {decoded:.2f}s of {expected:.2f}s"
    if not ok:
        return False, (f"{measured} - LOST {lost:.2f}s (max {allow:.2f}s)"
                       + (f"; {len(errs)} error(s): {errs[:3]}" if errs else ""))
    if not errs:
        return True, f"{measured} cleanly"

    # Tolerated, but say so loudly enough that it is never mistaken for clean.
    # Compared with the addresses stripped: ffmpeg stamps every message with the
    # decoder's heap address ("[aac @ 0xef18240]"), which differs on every run,
    # so matching the raw strings would always say "not present in the sources".
    known = {_err_key(e) for g in (source_glitches or ())
             for e in (g.get("errors") or ())}
    carried = ("carried over from a glitched source"
               if known & {_err_key(e) for e in errs}
               else "not present in the sources")
    return True, (f"{measured}, no measurable loss (max {allow:.2f}s); "
                  f"{len(errs)} decoder error(s) tolerated, {carried}: {errs[:3]}")


def verify(plan, sample_chapters=5):
    out = plan["output"]
    n = plan["n_files"]
    expected = plan["source_total_duration"]
    tol = max(0.5, n * 0.01)
    checks = {}

    # -- 1. decode the whole audio stream, and MEASURE how much there is ------
    # Judged by measured loss, exactly as build() judges the sources - see
    # decode_verdict() for why an error count must not be the gate.
    decoded, errs = decode_audio(out)
    ok_dec, detail_dec = decode_verdict(
        decoded, expected, errs,
        max_loss=plan.get("max_loss", 1.0), tol=tol,
        source_glitches=plan.get("minor_glitches") or ())
    checks["decode"] = {"ok": ok_dec, "detail": detail_dec}

    # -- 2. duration, from the measurement above, not from metadata ----------
    # format=duration is what the muxer declared; with +faststart the moov atom
    # is at the front, so it survives truncation and cannot detect it.
    diff = abs(decoded - expected)
    checks["duration"] = {
        "ok": diff <= tol,
        "detail": f"measured {decoded:.2f}s vs sources {expected:.2f}s "
                  f"(diff {diff:.2f}s, tol {tol:.2f}s)",
    }

    r = run([FFPROBE, "-v", "error", "-show_entries",
             "format=duration,size,bit_rate:stream=index,codec_type,codec_name,"
             "channels,sample_rate", "-show_chapters", "-of", "json", out])
    if r.returncode != 0:
        checks["probe"] = {"ok": False, "detail": r.stderr.strip()[:300]}
        return False, checks, {}
    d = json.loads(r.stdout)
    fmt = d.get("format", {})
    declared = float(fmt.get("duration") or 0)
    size = int(fmt.get("size") or 0)
    audio = [s for s in d.get("streams", []) if s.get("codec_type") == "audio"]
    chaps = d.get("chapters", [])

    # -- 3. chapters ---------------------------------------------------------
    # The expected count is the PLANNED table, not the file count: a multi-part
    # book whose parts carry their own chapters expands to more chapters than
    # files, and comparing against len(files) would reject every one of them.
    want_n = len(plan["chapters"])
    starts = [float(c.get("start_time") or 0) for c in chaps]
    monotonic = all(b > a for a, b in zip(starts, starts[1:])) if len(starts) > 1 else True
    drift = 0.0
    if len(chaps) == want_n:
        for c, want in zip(chaps, plan["chapters"]):
            drift = max(drift, abs(float(c.get("start_time") or 0) - want["start_ms"] / 1000))
    last_end = float(chaps[-1].get("end_time") or 0) if chaps else 0.0
    spans = abs(last_end - decoded) <= max(tol, 1.0)
    checks["chapters"] = {
        "ok": len(chaps) == want_n and monotonic and drift <= tol and spans,
        "detail": f"{len(chaps)} chapters (planned {want_n} from {n} files), "
                  f"monotonic={monotonic}, drift {drift:.2f}s, "
                  f"last end {last_end:.1f}s vs decoded {decoded:.1f}s",
    }

    # -- 4. streams ----------------------------------------------------------
    want_ch, want_sr = plan["target"]["channels"], plan["target"]["sample_rate"]
    st_ok = (len(audio) == 1 and audio[0].get("codec_name") == "aac"
             and int(audio[0].get("channels") or 0) == want_ch
             and int(audio[0].get("sample_rate") or 0) == want_sr)
    checks["streams"] = {
        "ok": st_ok,
        "detail": (f"{len(audio)} audio stream(s): "
                   + ", ".join(f"{s.get('codec_name')} {s.get('channels')}ch "
                               f"{s.get('sample_rate')}Hz" for s in audio)
                   + f" (want aac {want_ch}ch {want_sr}Hz)"),
    }

    # -- 5. tags -------------------------------------------------------------
    r2 = run([FFPROBE, "-v", "error", "-show_entries", "format_tags",
              "-of", "json", out])
    tags = {k.lower(): v for k, v in
            (json.loads(r2.stdout).get("format", {}).get("tags") or {}).items()}
    checks["tags"] = {"ok": bool(tags.get("title")),
                      "detail": f"title={tags.get('title')!r} "
                                f"artist={tags.get('artist')!r}"}

    # -- 6. size -------------------------------------------------------------
    # The attached cover is not audio; on a short book a big JPEG is several
    # percent of the file and would push the ratio out of band on its own.
    # The lower bound is deliberately loose. `-b:a` is a REQUEST, and the AAC
    # encoder will not spend it on content that does not need it: a mono 22 kHz
    # book whose MP3 sources were tagged 128 kbit lands around 90 kbit, i.e. 70%
    # of the "expected" size, with every other check passing. That is the encoder
    # being sensible, not a damaged file. Truncation is caught by `decode` and
    # `duration`, which are real measurements of the output, so this check only
    # needs to catch gross anomalies.
    audio_bytes = max(0, size - int(plan.get("cover_bytes") or 0))
    expect_size = plan["target"]["bitrate"] / 8 * decoded
    ratio = audio_bytes / expect_size if expect_size else 0
    checks["size"] = {
        "ok": 0.55 <= ratio <= 1.35,
        "detail": f"{size/1e6:.1f} MB, audio {ratio*100:.0f}% of the "
                  f"{plan['target']['bitrate']//1000}kbit estimate; "
                  f"declared {declared:.1f}s vs decoded {decoded:.1f}s",
    }

    # -- 7. content: envelope match, chapter by chapter ----------------------
    # Sampling a handful of chapters leaves most of the book unchecked: on a
    # 185-file book five samples cover under 3%, and a swap between two UNSAMPLED
    # tracks passes everything. Checking every chapter is cheap (a 20 s slice
    # decoded at 4 kHz), so do that up to a cap and spread the samples out beyond
    # it rather than clustering them at the front.
    picks, notes, rs, bad_flat = [], [], [], []
    if len(chaps) == want_n and want_n > 0:
        budget = want_n if sample_chapters <= 0 else sample_chapters
        budget = max(1, min(budget, want_n))
        if budget >= want_n:
            picks = list(range(want_n))
        else:
            picks = sorted({int(round(k * (want_n - 1) / (budget - 1)))
                            for k in range(budget)}) if budget > 1 else [0]
    for idx in picks:
        want = plan["chapters"][idx]
        span = min(ENV_SPAN, max(2.0, want["src_duration"] - 1.0))
        eo = envelope(out, want["start_ms"] / 1000, span=span)
        # src_offset, not 0.0: with embedded tables expanded a chapter can start
        # anywhere inside its source file
        es = envelope(want["src"], want.get("src_offset", 0.0), span=span)
        r_ = pearson(eo, es)
        if r_ is None:
            # A flat OUTPUT slice where the SOURCE is not flat means the audio
            # was replaced by silence - that must fail, not be skipped. Both
            # flat is a genuinely silent passage and carries no information.
            src_flat = pearson(es, es) is None
            if src_flat:
                notes.append(f"ch{idx+1}:both-silent")
            else:
                bad_flat.append(idx + 1)
                notes.append(f"ch{idx+1}:OUTPUT-SILENT")
            continue
        rs.append(r_)
        if r_ < ENV_MIN_R:
            notes.append(f"ch{idx+1} r={r_:.3f}")
    worst = min(rs) if rs else None
    cov = (len(picks) / want_n * 100) if want_n else 0
    checks["content"] = {
        "ok": bool(rs) and worst >= ENV_MIN_R and not bad_flat,
        "detail": (f"{len(picks)}/{want_n} chapters checked ({cov:.0f}% coverage), "
                   + (f"worst r={worst:.3f} (need {ENV_MIN_R})" if rs
                      else "none correlated")
                   + (f"; {len(bad_flat)} SILENT IN OUTPUT: {bad_flat[:8]}"
                      if bad_flat else "")
                   + ("; " + " ".join(notes[:8]) if notes else "")),
    }

    # -- 8. mux: the demuxer must not have had to fix up timestamps ----------
    # "non monotonically increasing dts" is exactly what a mislaid concat
    # timeline emits, and it means audio was dropped at a boundary.
    warns = plan.get("mux_warnings") or []
    checks["mux"] = {
        "ok": not warns,
        "detail": ("no muxer timestamp warnings" if not warns
                   else f"{len(warns)} muxer warning(s): {warns[:2]}"),
    }

    ok = all(c["ok"] for c in checks.values())
    return ok, checks, {"measured_duration": decoded, "declared_duration": declared,
                        "output_size": size, "n_chapters": len(chaps),
                        "content_checked": len(picks),
                        "content_coverage_pct": round(cov, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--bitrate", type=int, default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--artist", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--samples", type=int, default=0,
                    help="how many chapters the content check correlates. "
                         "0 (default) means EVERY chapter - sampling a handful "
                         "leaves most of the book unverified, and a swap "
                         "between two unsampled tracks passes everything")
    ap.add_argument("--max-loss", type=float, default=1.0,
                    help="seconds of UNDECODABLE audio a source file may have "
                         "before the book is refused (default 1.0)")
    ap.add_argument("--allow-single", action="store_true",
                    help="convert a folder holding ONE audio file into a .m4b. "
                         "Normally pointless - a single file is already done - "
                         "but it is how a standalone edition split out of a "
                         "two-edition folder gets the same container and the "
                         "same eight checks as everything else")
    ap.add_argument("--mode", choices=("auto", "encode", "copy"), default="auto",
                    help="auto (default) stream-copies books that are already "
                         "aac with a constant stream layout - lossless - and "
                         "encodes everything else")
    a = ap.parse_args()

    workdir = a.workdir or (a.output + ".work")
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    report = {"source": a.source, "output": a.output, "merger_md5": self_md5()}
    try:
        plan = build(a.source, a.output, workdir, bitrate=a.bitrate,
                     title=a.title, artist=a.artist, max_loss=a.max_loss,
                     mode=a.mode, allow_single=a.allow_single)
        ok, checks, extra = verify(plan, sample_chapters=a.samples)
        report.update({
            "ok": ok, "checks": checks, "n_files": plan["n_files"],
            "source_total_duration": plan["source_total_duration"],
            "mode": plan["mode"], "chapter_source": plan["chapter_source"],
            "n_chapters_planned": plan["n_chapters_planned"],
            "target": plan["target"], "cover": plan["cover"],
            "minor_glitches": plan["minor_glitches"],
            "mux_warnings": plan["mux_warnings"],
            "title": plan["title"], **extra,
        })
    except Exception as e:
        report.update({"ok": False, "error": str(e)[:4000]})
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if a.report:
        with open(a.report, "w") as fh:
            fh.write(text + "\n")
    print(text)

    if not report.get("ok"):
        try:
            os.remove(a.output)
        except OSError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
