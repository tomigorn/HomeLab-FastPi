#!/usr/bin/env bash
# scripts/sync-bar.sh with a fake ssh: same, differs, copy, beefy asleep. Usage: bash scripts/test_sync_bar.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/remote/indexer-bar/www" "$T/abr/books-proxy/www/bar" "$T/abr/abr-bar"
cat > "$T/bin/ssh" <<'SH'
#!/usr/bin/env bash
[[ -n ${FAKE_ASLEEP:-} ]] && exit 255
for a; do last=$a; done
f=${last##*HEAD:Docker/Seerr/}; f=${f%% *}
cat "$FAKE_REMOTE/$f"
SH
chmod +x "$T/bin/ssh"
echo js > "$T/remote/indexer-bar/www/bar.js"; echo css > "$T/remote/indexer-bar/www/bar.css"; echo md > "$T/remote/indexer-bar/schema.md"
run() { PATH="$T/bin:$PATH" FAKE_REMOTE="$T/remote" ABR_DIR="$T/abr" bash "$HERE/sync-bar.sh" "$@"; }
fail=0
expect() { if [[ $2 == "$3" ]]; then echo "ok   $1"; else echo "FAIL $1: want [$2] got [$3]"; fail=1; fi; }
out=$(run --check); expect "missing copy differs" "1" "$?"
run >/dev/null; expect "copy writes all three" "js css md" "$(cat "$T/abr/books-proxy/www/bar/bar.js" "$T/abr/books-proxy/www/bar/bar.css" "$T/abr/abr-bar/indexer-bar-schema.md" | xargs)"
out=$(run --check); expect "after copy same" "0 same" "$? $out"
echo changed > "$T/abr/books-proxy/www/bar/bar.css"
out=$(run --check); expect "local edit differs" "1 differs: bar.css" "$? $out"
out=$(FAKE_ASLEEP=1 run --check); expect "beefy asleep skips" "3 skipped: beefy not reachable (not woken)" "$? $out"
exit $fail
