#!/usr/bin/env bash
# Checks the repo's .gitleaks.toml allowlists: known public values are silenced only where they belong.
# Run: bash Server/4-Security-Monitoring/test_gitleaks_config.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CONFIG=${CONFIG:-$HERE/../../.gitleaks.toml}
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

((fail)) && { echo "next: fix the allowlist in .gitleaks.toml"; exit 1; }
echo "all passed"
