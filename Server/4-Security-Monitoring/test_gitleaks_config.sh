#!/usr/bin/env bash
# Checks the repo's .gitleaks.toml allowlists: known public values are silenced only where they belong.
# Run: bash Server/4-Security-Monitoring/test_gitleaks_config.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CONFIG=${CONFIG:-$HERE/../../.gitleaks.toml}
mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}"
T=$(mktemp -d "${XDG_CACHE_HOME:-$HOME/.cache}/gitleaks-config-test.XXXXXX")
trap 'rm -rf "$T"' EXIT
fail=0

# Google's web-push sample VAPID public key, in halves so this file is not itself a finding.
SAMPLE="BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkr""xZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U"
OTHER="BKq93hVrRtZpXe0fWm4sLcN8gD2yJ7uAaQoE1iTbSvHkPj""6nMwYxCzR5dF3lG9hU0oI2pK4qL8eV1bZ7tNcXsWy"

findings() {
    local dir=$1
    gitleaks dir "$dir" -c "$CONFIG" --report-format json --report-path "$dir.json" --exit-code 0 --log-level error --no-banner >/dev/null
    python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])) or []))' "$dir.json"
}
case_() {
    local name=$1 path=$2 key=$3 want=$4 dir="$T/$1"
    mkdir -p "$dir/$(dirname "$path")"
    printf "const KEY = '%s';\n" "$key" > "$dir/$path"
    local got; got=$(findings "$dir")
    if { [[ $want == 0 ]] && [[ $got == 0 ]]; } || { [[ $want == some ]] && ((got > 0)); }; then
        echo "ok   $name"
    else
        echo "FAIL $name: $got finding(s), want $want"; fail=1
    fi
}

case_ sample-key-in-wg-chores-push-test web/src/lib/push.test.ts "$SAMPLE" 0
case_ sample-key-elsewhere-still-found web/src/lib/push.ts "$SAMPLE" some
case_ other-key-in-push-test-still-found web/src/lib/push.test.ts "$OTHER" some

EXPORT=Docker/Authentik/authentik-config-export.yaml
REPO=$(cd "$HERE/../.." && pwd)
d="$T/export-real"; mkdir -p "$d/$(dirname "$EXPORT")"; cp "$REPO/$EXPORT" "$d/$EXPORT"
got=$(findings "$d")
[[ $got == 0 ]] && echo "ok   export-real-file" || { echo "FAIL export-real-file: $got finding(s), want 0"; fail=1; }
d="$T/export-planted"; mkdir -p "$d/$(dirname "$EXPORT")"; cp "$REPO/$EXPORT" "$d/$EXPORT"
printf 'api_key: %s\n' "xK9vQ2mZpL7wR4tY8nB3cF6hJ1dS5gA0" >> "$d/$EXPORT"
got=$(findings "$d")
((got > 0)) && echo "ok   export-planted-secret-found" || { echo "FAIL export-planted-secret-found: $got finding(s), want some"; fail=1; }

((fail)) && { echo "next: fix the allowlist in .gitleaks.toml"; exit 1; }
echo "all passed"
