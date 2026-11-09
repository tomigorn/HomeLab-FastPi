#!/usr/bin/env bash
# Black-box suite runner.
# Usage: run.sh old            legacy Python app (venv with requirements.txt in $VENV, default ~/.cache/claude-work/rust-bd/venv)
#        run.sh new [BINARY]   Rust binary (default: target/release/backdrop-carousel)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJ=$(cd "$HERE/../.." && pwd)
MODE=${1:?old or new}
WORK=$(mktemp -d "${TMPDIR_WORK:-$HOME/.cache/claude-work}/bd-blackbox.XXXXXX")
PIDS=()
trap 'kill "${PIDS[@]}" 2>/dev/null; wait 2>/dev/null; rm -rf "$WORK"' EXIT

mkdir -p "$WORK/photos/sub" "$WORK/empty"
python3 - "$WORK" <<'PY'
import os, pathlib, sys
w = pathlib.Path(sys.argv[1]); p = w / "photos"
for i, n in enumerate(["a.jpg", "b.PNG", "c.webp", "d.jpeg", "e.bmp", "f.gif", "g h.jpg"]):
    (p / n).write_bytes(os.urandom(2000 + i * 100))
(p / "notes.txt").write_text("not an image")
(p / "sub" / "inner.jpg").write_bytes(b"inner")
(w / "secret.jpg").write_bytes(b"TOPSECRET")
(w / "outside.jpg").write_bytes(b"TOPSECRET-outside")
(p / "outside.jpg").symlink_to(w / "outside.jpg")
PY

port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }
start() { # start <photos dir> [binary] -> sets URL
  local p; p=$(port)
  case $MODE in
    old)
      local app=$PROJ; [[ -f $PROJ/legacy/app.py ]] && app=$PROJ/legacy
      PHOTOS_DIR=$1 "${VENV:-$HOME/.cache/claude-work/rust-bd/venv}/bin/uvicorn" app:app --app-dir "$app" --host 127.0.0.1 --port "$p" --log-level warning >"$WORK/log-$p" 2>&1 & ;;
    new)
      PHOTOS_DIR=$1 LISTEN=127.0.0.1:$p "${2:-$PROJ/target/release/backdrop-carousel}" >"$WORK/log-$p" 2>&1 & ;;
  esac
  PIDS+=($!)
  for _ in $(seq 100); do curl -s -o /dev/null "http://127.0.0.1:$p/" && break; sleep 0.1; done
  URL="http://127.0.0.1:$p"
}
start "$WORK/photos" "${2:-}"; BASE=$URL
start "$WORK/empty" "${2:-}"; BASE_EMPTY=$URL
BASE=$BASE BASE_EMPTY=$BASE_EMPTY PHOTOS=$WORK/photos python3 "$HERE/test_blackbox.py" -v 2>&1 | tail -n "${TAIL:-200}"
exit "${PIPESTATUS[0]}"
