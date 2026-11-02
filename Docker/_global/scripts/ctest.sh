#!/usr/bin/env bash
# Throwaway test container that cannot change anything: no network, read-only fs and mounts, nobody user, no caps, no pull.
# Usage: ctest.sh [-v HOST_DIR[:CONTAINER_DIR]]... [-w DIR] [-e NAME=VALUE]... [--entrypoint CMD] IMAGE [ARG...]
# Mounts must lie under ~/Projects or ~/Documents/development; CTEST_ROOTS (colon-separated) only counts for a copy the caller owns (tests), never for the root-owned installed one. CTEST_TIMEOUT in seconds (default 600, max 900).
set -uo pipefail

die() { echo "ctest: $*" >&2; exit 2; }
H=$(getent passwd "$(id -u)" | cut -d: -f6)
DEFAULT_ROOTS="$H/Projects:$H/Documents/development"
[[ $(stat -c %u -- "$0") == "$(id -u)" ]] || unset CTEST_ROOTS
IFS=: read -r -a ROOTS <<< "${CTEST_ROOTS:-$DEFAULT_ROOTS}"
TIMEOUT=${CTEST_TIMEOUT:-600}
[[ $TIMEOUT =~ ^[0-9]+$ ]] && ((TIMEOUT <= 900)) || die "CTEST_TIMEOUT must be seconds, at most 900"

under_root() {
    local r rr
    for r in "${ROOTS[@]}"; do
        rr=$(realpath -e -- "$r" 2>/dev/null) || continue
        [[ $1 == "$rr" || $1 == "$rr"/* ]] && return 0
    done
    return 1
}
safe_path() { [[ $1 == /* && $1 != *[,:=]* && $1 =~ ^[A-Za-z0-9._/@+-]+$ ]]; }

ARGS=()
while (($#)); do
    case $1 in
        -v)
            (($# >= 2)) || die "-v needs a value"
            host=${2%%:*}; dst=${2#*:}; [[ $2 == *:* ]] || dst=
            real=$(realpath -e -- "$host" 2>/dev/null) || die "no such path: $host"
            under_root "$real" || die "mount outside the allowed roots: $host"
            safe_path "$real" || die "unsupported characters in path: $real"
            [[ -n $dst ]] || dst=$real
            safe_path "$dst" || die "container path must be absolute and plain: $dst"
            ARGS+=("--mount=type=bind,src=$real,dst=$dst,readonly")
            shift 2 ;;
        -w)
            (($# >= 2)) && safe_path "$2" || die "-w needs an absolute path"
            ARGS+=("--workdir=$2"); shift 2 ;;
        -e)
            (($# >= 2)) && [[ $2 =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || die "-e needs NAME=VALUE"
            ARGS+=("--env=$2"); shift 2 ;;
        --entrypoint)
            (($# >= 2)) && [[ $2 != -* && -n $2 ]] || die "--entrypoint needs a command"
            ARGS+=("--entrypoint=$2"); shift 2 ;;
        -*) die "unknown option: $1" ;;
        *) break ;;
    esac
done
(($#)) || die "missing image"
[[ $1 =~ ^[a-z0-9][a-z0-9._/:@-]*$ ]] || die "invalid image: $1"

name=ctest-$$-$RANDOM
trap 'docker kill "$name" >/dev/null 2>&1' INT TERM HUP
timeout --foreground "$TIMEOUT" docker run --rm --interactive --name="$name" --label=ctest=1 \
    --pull=never --network=none --read-only --tmpfs=/tmp:rw,size=256m --user=65534:65534 \
    --cap-drop=ALL --security-opt=no-new-privileges \
    --pids-limit=256 --memory=1g --cpus=2 \
    "${ARGS[@]}" "$@"
rc=$?
if ((rc == 124)); then
    docker kill "$name" >/dev/null 2>&1
    echo "ctest: timed out after ${TIMEOUT}s" >&2
fi
exit "$rc"
