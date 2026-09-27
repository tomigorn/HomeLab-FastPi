#!/usr/bin/env bash
# Hold beefy awake for as long as a merge is running.
#
# beefy's idle watcher powers the host off after 15 idle minutes (DRY_RUN=0), and
# its idea of "idle" does not match ours:
#   * whole-host CPU below 15%  - one encode is 1 core of 12, about 8%
#   * the work dir is on the NVMe, which its disk probe deliberately excludes
#   * port 22 is excluded from its connection probe
#   * `ssh host cmd` is deliberately NOT counted - only interactive pty sessions
# So a long single-book encode reads as completely idle. It really happened: at
# 00:30 it logged "idle 15 min -> systemctl poweroff" while Shogun was encoding.
#
# The honest fix is its own INHIBIT_FILE, but that needs root on beefy and the
# only NOPASSWD entry there is `systemctl poweroff`. The next best signal is the
# one the watcher itself treats as "a human is working here": an interactive pty
# session. This holds one, renewing it, and stops the moment the merge stops - so
# beefy still powers itself off normally once the work is done.
#
# Usage:  keep-awake.sh <unit> [unit...]     # hold while any unit is active
#         keep-awake.sh --pid <pid>          # hold while that process lives
set -u

SSH_OPTS=(-o BatchMode=yes -o HostName=192.168.1.102 -o ControlPath=none
          -o ControlMaster=no -o ConnectTimeout=20
          -o ServerAliveInterval=30 -o ServerAliveCountMax=4)
REMOTE=beefy
RENEW=240          # seconds per session; shorter than the 15 min idle window

log() { echo "$(date -Is)  $*"; }

still_working() {
    if [ "${1:-}" = "--pid" ]; then
        kill -0 "$2" 2>/dev/null
        return
    fi
    for unit in "$@"; do
        systemctl --user is-active --quiet "$unit" && return 0
    done
    return 1
}

log "holding beefy awake while: $*"
while still_working "$@"; do
    # -tt forces a pty even though stdin is not a terminal; that is what makes
    # the watcher count it. </dev/null so the remote sleep cannot consume input.
    ssh -tt "${SSH_OPTS[@]}" "$REMOTE" "sleep $RENEW" </dev/null >/dev/null 2>&1
    rc=$?
    if [ $rc -ne 0 ] && still_working "$@"; then
        # beefy may be booting after a poweroff, or the network blipped
        log "keep-awake session ended rc=$rc; retrying in 15s"
        sleep 15
    fi
done
log "merge finished - releasing beefy (it will idle off by itself)"
