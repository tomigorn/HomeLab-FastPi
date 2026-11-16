#!/usr/bin/env python3
"""Size and item count of fastpi's media libraries for the Grafana dashboard "Storage" (Docker/grafana/README.md "Storage trends").
Categories and their folders: libraries.toml. A category whose folders do not exist reports fastpi_library_present 0 (dashboard: "no library yet").
Item = a folder that holds files directly; "CD 1", "Disc2", "Part 3" folders count as their parent. Reads directory metadata only (no file contents).
Writes /var/lib/node-exporter/textfile/library_fastpi.prom. Run daily by systemd/library-exporter.timer.
Usage: library_exporter.py [config] [out]"""
import os
import pathlib
import re
import sys
import time
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path("/var/lib/node-exporter/textfile/library_fastpi.prom")
DISC = re.compile(r"^(cd|disc|disk|part)\s*\d+$", re.I)


def load(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def scan(root):
    total, items = 0, set()
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        seen = False
        for f in files:
            if f.startswith("."):
                continue
            try:
                total += os.lstat(os.path.join(d, f)).st_size
                seen = True
            except OSError:
                pass
        if seen and os.path.abspath(d) != os.path.abspath(root):
            p = pathlib.Path(d)
            items.add(str(p.parent if DISC.match(p.name) else p))
    return total, len(items)


def lines(cfg, now=None):
    out = []
    for cat in sorted(cfg):
        paths = [p for p in cfg[cat].get("paths", []) if os.path.isdir(p)]
        out.append(f'fastpi_library_present{{category="{cat}"}} {1 if paths else 0}')
        if paths:
            size, items = map(sum, zip(*(scan(p) for p in paths)))
            out.append(f'fastpi_library_bytes{{category="{cat}"}} {size}')
            out.append(f'fastpi_library_items{{category="{cat}"}} {items}')
    out.append(f"fastpi_library_updated_timestamp_seconds {int(time.time() if now is None else now)}")
    return "\n".join(out) + "\n"


def write(out, text):
    tmp = out.with_name("." + out.name + ".tmp")
    tmp.write_text(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, out)


def main(argv):
    if argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    cfg = load(argv[1] if len(argv) > 1 else HERE / "libraries.toml")
    out = pathlib.Path(argv[2]) if len(argv) > 2 else OUT
    write(out, lines(cfg))
    print(f"wrote {out}; check: grep fastpi_library {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
