#!/usr/bin/env bash
# Black-box suite runner: fake Authentik + the picker in a private network namespace (port 8080 is fixed in the legacy server).
# Usage: run.sh old            legacy Python server (app/*.py)
#        run.sh new BINARY     Rust binary
#        run.sh image IMAGE    the binary inside a built image (weekly rebuild: rebuild-local.conf `test`)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJ=$(cd "$HERE/../.." && pwd)
MODE=${1:?old or new}
BIN=${2:-}
mkdir -p "${BB_TMP:=$HOME/.cache/claude-work}"
WORK=$(mktemp -d "$BB_TMP/avatar-blackbox.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
if [[ $MODE == image ]]; then
  c=$(docker create "${BIN:?image}") && docker cp -q "$c:/avatar-picker" "$WORK/bin" && docker rm "$c" >/dev/null
  MODE=new BIN=$WORK/bin
fi
[[ $MODE == old || -x $BIN ]] || { echo "usage: run.sh old | new BINARY | image IMAGE" >&2; exit 2; }

python3 - "$WORK" <<'PY'
import json, os, pathlib, sys
w = pathlib.Path(sys.argv[1]); a = w / "app"
for d in ("img", "img-local", "static", "thumbs"):
    (a / d).mkdir(parents=True)
gallery = [{"id": "alpha", "name": "Alpha", "file": "alpha.png", "color": "#111111", "group": "g1"},
           {"id": "beta", "name": "Beta", "file": "beta.png", "color": "#222222", "group": "g1"},
           {"id": "gamma", "name": "Gamma", "file": "gamma.png", "color": "#333333", "group": "g2", "pack": "local"},
           {"id": "delta", "name": "Delta", "file": "delta.png", "color": "#444444", "group": "g2"},
           {"id": "eps", "name": "Eps", "file": "eps.png", "color": "#555555", "group": "g3"}]
gallery += [{"id": f"a{i:02d}", "name": f"Avatar number {i} with a longer name", "file": f"a{i:02d}.png",
             "color": f"#{i:02d}{i:02d}{i:02d}", "group": "g1", "vibe": "neutral"} for i in range(1, 10)]
gallery.append({"id": "a10", "name": "Avatar ten", "file": "a10.png", "color": "#101010", "group": None})
(a / "gallery.json").write_text(json.dumps(gallery))
(a / "groups.json").write_text(json.dumps([{"id": g, "label": f"Group {n}"} for g, n in
                                           [("g1", "one"), ("g2", "two"), ("g3", "three"), ("g4", "four")]]))
for g in gallery:
    if g["id"] in ("delta", "eps"):
        continue
    (a / ("img-local" if g.get("pack") else "img") / f"{g['id']}.png").write_bytes(b"\x89PNG" + os.urandom(3000))
thumbs = {"alpha": "0123456789", "gamma": "abcdef0123", "beta": "1111111111", "delta": "2222222222"}
(a / "thumbs" / "thumbs.json").write_text(json.dumps(thumbs))
for n in ("alpha.0123456789.160", "alpha.0123456789.320", "gamma.abcdef0123.160", "gamma.abcdef0123.320",
          "beta.1111111111.320", "delta.2222222222.160"):
    (a / "thumbs" / f"{n}.webp").write_bytes(b"RIFF" + os.urandom(500))
(a / "static" / "index.html").write_text("<!doctype html><title>Avatars</title>\n" + "<p>gallery filler line</p>\n" * 200)
(a / "static" / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
(a / "static" / "favicon-32.png").write_bytes(b"\x89PNG32" + os.urandom(100))
(a / "static" / "apple-touch-icon.png").write_bytes(b"\x89PNGat" + os.urandom(100))
(a / "VERSION").write_text("9.9.9-test\n")
(w / "token").write_text("tok-123\n")
(w / "secret").write_text("s3cret-header\n")
(w / "data").mkdir()
(w / "data" / "queue.json").write_text(json.dumps({"carol": {"avatar": "beta", "at": "2026-01-01T00:00:00Z"}}))
PY
[[ $MODE == old ]] && cp "$PROJ"/app/*.py "$WORK/app/"

export WORK MODE BIN HERE
unshare -rn bash -c '
set -uo pipefail
ip link set lo up
python3 "$HERE/mock_authentik.py" 9999 tok-123 & MOCKPID=$!
export AUTHENTIK_TOKEN_FILE=$WORK/token PICKER_SECRET_FILE=$WORK/secret QUEUE_FILE=$WORK/data/queue.json \
       AUTHENTIK_URL=http://127.0.0.1:9999 AUTHENTIK_ALLOW_HTTP=1 PUBLIC_BASE_URL=https://sso.example.com/avatar-img APP_DIR=$WORK/app
for _ in $(seq 50); do curl -s -o /dev/null http://127.0.0.1:9999/_mock/state && break; sleep 0.1; done
if [[ $MODE == old ]]; then python3 -u "$WORK/app/server.py" >"$WORK/sut.log" 2>&1 & else "$BIN" >"$WORK/sut.log" 2>&1 & fi
SUTPID=$!
for _ in $(seq 100); do curl -s -o /dev/null http://127.0.0.1:8080/healthz && break; sleep 0.1; done
SUT=http://127.0.0.1:8080 MOCK=http://127.0.0.1:9999 APP=$WORK/app QUEUE=$WORK/data/queue.json SECRET=s3cret-header \
  python3 "$HERE/test_blackbox.py" -v 2>&1 | tail -n "${TAIL:-400}"
rc=${PIPESTATUS[0]}
kill $SUTPID $MOCKPID 2>/dev/null
[[ $rc == 0 ]] || { echo "--- SUT log"; tail -n 30 "$WORK/sut.log"; }
exit $rc'
