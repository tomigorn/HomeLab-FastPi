#!/usr/bin/env bash
# crowdsec-autoupdate.sh - keep CrowdSec (engine image + hub content) current, safely.
#
# Run daily by crowdsec-autoupdate.timer. Same procedure as
# _global/UPDATE-RUNBOOK.md (snapshot -> backup -> pull -> recreate -> verify ->
# rollback), plus CrowdSec-specific checks and a rollback that also restores the
# data volumes (a new CrowdSec may migrate its SQLite schema forward only).
#
#   1. newest STABLE release from GitHub (/releases/latest skips -rc), must exist
#      on Docker Hub. Patch/minor -> install. A new MAJOR is never installed
#      automatically: it is reported (result=major_available) and waits for a human.
#   2. update:  back up both volumes, set CROWDSEC_TAG in .env (+ .env.example),
#      pull, recreate, then verify:
#        container running, 0 restarts | LAPI answers | bouncer re-pulled after
#        the restart | a TEST-NET ban (203.0.113.x) is enforced by Traefik and a
#        clean TEST-NET IP is not | public route not 404/5xx
#   3. any check fails -> rollback: old tag in .env, old image id re-tagged,
#      volumes restored from the backup just taken, recreate, re-verify.
#      The bad version is remembered and skipped until a newer one appears.
#   4. no new version -> `cscli hub update` + `cscli hub upgrade`; when items
#      changed, reload CrowdSec (SIGHUP) and verify the same way.
#   5. result -> node-exporter textfile -> Prometheus rules
#      (grafana/prometheus/rules/crowdsec.yml) -> Alertmanager -> Telegram/email.
#
# Pause:  CROWDSEC_AUTOUPDATE=off in .env   (or: sudo systemctl disable --now crowdsec-autoupdate.timer)
# Manual: sudo systemctl start crowdsec-autoupdate.service ; journalctl -u crowdsec-autoupdate
# Dry run: DRY_RUN=1 crowdsec-autoupdate.sh   (decides, changes nothing)
# Rollback drill: TEST_FORCE_FAIL=1 crowdsec-autoupdate.sh (first verification fails)
#
# Safety net while CrowdSec restarts: the Traefik bouncer runs in stream mode with
# updateMaxFailure -1 (Traefik/traefik/dynamic/crowdsec.yml), so an unreachable
# LAPI means "keep the last ban list", never "403 for everyone".
set -uo pipefail

DIR=/home/pi/Projects/Docker/CrowdSec
ENVF=$DIR/.env
STATE=${STATE_DIR:-/var/lib/crowdsec-autoupdate}
PROM=${TEXTFILE_DIR:-/var/lib/node-exporter/textfile}/crowdsec_autoupdate.prom
IMAGE=crowdsecurity/crowdsec
VOLUMES=(crowdsec_crowdsec_config crowdsec_crowdsec_data)
TRAEFIK_HOST=home.holy-grail.ch      # any public route; probed via Traefik's container IP
BAN_TEST_IP=203.0.113.250             # TEST-NET-3: never a real client
CLEAN_TEST_IP=203.0.113.251
DRY_RUN=${DRY_RUN:-0}

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
envget() { sed -n "s/^$1=//p" "$ENVF" | tail -1; }
envset() { # envset KEY VALUE FILE
  if grep -q "^$1=" "$3"; then sed -i "s|^$1=.*|$1=$2|" "$3"; else echo "$1=$2" >> "$3"; fi; }
cs() { docker exec crowdsec cscli "$@"; }

FROM=$(envget CROWDSEC_TAG); TO=$FROM; RESULT=error; DETAIL=""
write_prom() {
  local now; now=$(date +%s)
  local last_change; last_change=$(cat "$STATE/last_change" 2>/dev/null || echo 0)
  local tmp; tmp=$(mktemp "$(dirname "$PROM")/.tmp-XXXXXX")
  cat > "$tmp" <<EOF
# HELP crowdsec_autoupdate_last_run_timestamp_seconds Last run of crowdsec-autoupdate.
# TYPE crowdsec_autoupdate_last_run_timestamp_seconds gauge
crowdsec_autoupdate_last_run_timestamp_seconds $now
# HELP crowdsec_autoupdate_last_change_timestamp_seconds Last time the image or hub content actually changed.
# TYPE crowdsec_autoupdate_last_change_timestamp_seconds gauge
crowdsec_autoupdate_last_change_timestamp_seconds $last_change
# HELP crowdsec_autoupdate_result Outcome of the last run (exactly one series is 1).
# TYPE crowdsec_autoupdate_result gauge
EOF
  for r in current updated hub_updated rolled_back rollback_failed held_back major_available paused error; do
    printf 'crowdsec_autoupdate_result{result="%s",from="%s",to="%s"} %d\n' "$r" "$FROM" "$TO" "$([[ $r == "$RESULT" ]] && echo 1 || echo 0)" >> "$tmp"
  done
  chmod 644 "$tmp"; mv "$tmp" "$PROM"
}
finish() { log "RESULT $RESULT ($FROM -> $TO) $DETAIL"; [[ $DRY_RUN == 1 ]] || write_prom; exit "${1:-0}"; }

# ---------------------------------------------------------------- verification
bouncer_last_pull() { cs bouncers list -o json 2>/dev/null | python3 -c '
import json,sys,datetime as d
ts=[d.datetime.fromisoformat(b["last_pull"].replace("Z","+00:00")).timestamp() for b in json.load(sys.stdin) if b.get("last_pull")]
print(int(max(ts)) if ts else 0)'; }
probe() { # probe <client-ip> -> HTTP code as Traefik answers that (forwarded) client
  local tip; tip=$(docker inspect traefik -f '{{(index .NetworkSettings.Networks "traefik_proxy").IPAddress}}')
  curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve "$TRAEFIK_HOST:443:$tip" -H "X-Forwarded-For: $1" "https://$TRAEFIK_HOST/"; }

verify() { # verify <since-epoch>; prints failures, returns non-zero on any
  local since=$1 bad=0 st i
  for i in $(seq 1 30); do st=$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' crowdsec 2>/dev/null); cs lapi status >/dev/null 2>&1 && break; sleep 5; done
  [[ $st == "running 0" ]]                      || { log "  check FAIL container: $st"; bad=1; }
  cs lapi status >/dev/null 2>&1                || { log "  check FAIL LAPI not answering"; bad=1; }
  # The bouncer syncs every 60 s; give it three cycles to re-pull after the restart.
  for i in $(seq 1 36); do (( $(bouncer_last_pull) > since )) && break; sleep 5; done
  (( $(bouncer_last_pull) > since ))            || { log "  check FAIL bouncer has not pulled since the restart"; bad=1; }
  cs decisions add -i "$BAN_TEST_IP" -d 5m -R "autoupdate self-test" >/dev/null 2>&1
  local code=""; for i in $(seq 1 30); do code=$(probe "$BAN_TEST_IP"); [[ $code == 403 ]] && break; sleep 5; done
  cs decisions delete -i "$BAN_TEST_IP" >/dev/null 2>&1
  [[ $code == 403 ]]                            || { log "  check FAIL test ban not enforced (got $code)"; bad=1; }
  code=$(probe "$CLEAN_TEST_IP")
  [[ $code =~ ^(200|30[1-8]|401)$ ]]            || { log "  check FAIL clean client refused (got $code)"; bad=1; }
  code=$(curl -s -m 15 -o /dev/null -w '%{http_code}' -A 'crowdsec-autoupdate' "https://$TRAEFIK_HOST/")
  [[ $code =~ ^(200|30[1-8]|401|403)$ ]]        || { log "  check FAIL public route answered $code"; bad=1; }
  # TEST_FORCE_FAIL=1 fails the first verification of a run - the only way to
  # exercise the rollback path for real (used 2026-10-19; see README).
  if [[ ${TEST_FORCE_FAIL:-0} == 1 && ! -e $STATE/.forced ]]; then touch "$STATE/.forced"; log "  check FAIL (forced by TEST_FORCE_FAIL)"; bad=1; fi
  (( bad == 0 )) && log "  checks OK (container, LAPI, bouncer pull, ban enforced, clean passes, public route)"
  return $bad
}

# ---------------------------------------------------------------- main
mkdir -p "$STATE"; rm -f "$STATE/.forced"
exec 9>"$STATE/lock"; flock -n 9 || { log "another run is active"; exit 0; }
cd "$DIR" || exit 2

if [[ $(envget CROWDSEC_AUTOUPDATE) == off ]]; then RESULT=paused; DETAIL="CROWDSEC_AUTOUPDATE=off in .env"; finish 0; fi

LATEST=$(curl -fsS -m 20 https://api.github.com/repos/crowdsecurity/crowdsec/releases/latest | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])' 2>/dev/null)
[[ $LATEST =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { DETAIL="could not read latest release (got '$LATEST')"; finish 1; }
TO=$LATEST
ver() { echo "${1#v}" | awk -F. '{printf "%05d%05d%05d", $1, $2, $3}'; }
major() { echo "${1#v}" | cut -d. -f1; }

if [[ $(ver "$LATEST") > $(ver "$FROM") ]]; then
  if [[ $(major "$LATEST") != $(major "$FROM") ]]; then
    RESULT=major_available; DETAIL="new major $LATEST: read the release notes, then set CROWDSEC_TAG by hand"; finish 0; fi
  if grep -qxF "$LATEST" "$STATE/bad_versions" 2>/dev/null; then
    RESULT=held_back; DETAIL="$LATEST failed verification before and was rolled back; waiting for a newer release"; finish 0; fi
  curl -fsS -m 20 -o /dev/null "https://hub.docker.com/v2/repositories/$IMAGE/tags/$LATEST" \
    || { RESULT=current; TO=$FROM; DETAIL="$LATEST released but not on Docker Hub yet"; finish 0; }
  [[ $DRY_RUN == 1 ]] && { RESULT=updated; DETAIL="(dry run) would update"; finish 0; }

  # ---- update
  log "updating $FROM -> $LATEST"
  OLD_ID=$(docker inspect -f '{{.Image}}' crowdsec)
  BK="$HOME/backups/pre-update/$(date +%F)/crowdsec-autoupdate"; mkdir -p "$BK"
  # Pull BEFORE stopping, so the only downtime is backup + start (~15 s).
  envset CROWDSEC_TAG "$LATEST" "$ENVF"
  if ! docker compose pull -q crowdsec; then
    envset CROWDSEC_TAG "$FROM" "$ENVF"; TO=$FROM; DETAIL="pull of $LATEST failed, nothing changed"; finish 1; fi
  # Stopped for the backup: the SQLite DB (no WAL) must not be copied mid-write.
  docker compose stop crowdsec >/dev/null 2>&1
  for v in "${VOLUMES[@]}"; do
    if ! docker run --rm -v "$v":/from:ro -v "$BK":/to alpine tar czf "/to/vol-$v.tgz" -C /from .; then
      envset CROWDSEC_TAG "$FROM" "$ENVF"; docker compose up -d crowdsec >/dev/null 2>&1
      TO=$FROM; DETAIL="backup of $v failed, nothing changed"; finish 1; fi
  done
  log "  backup: ${VOLUMES[*]} -> $BK"
  START=$(date +%s)
  docker compose up -d crowdsec 2>&1 | tail -2
  if verify "$START"; then
    envset CROWDSEC_TAG "$LATEST" "$DIR/.env.example"
    date +%s > "$STATE/last_change"; RESULT=updated
    DETAIL="backup in $BK; .env.example bumped (commit it: CrowdSec: update to $LATEST)"
    finish 0
  fi

  # ---- rollback
  log "ROLLBACK to $FROM (restoring volumes from $BK)"
  echo "$LATEST" >> "$STATE/bad_versions"
  envset CROWDSEC_TAG "$FROM" "$ENVF"
  docker tag "$OLD_ID" "$IMAGE:$FROM"
  docker compose stop crowdsec
  for v in "${VOLUMES[@]}"; do
    docker run --rm -v "$v":/to -v "$BK":/from:ro alpine sh -c "find /to -mindepth 1 -delete && tar xzf /from/vol-$v.tgz -C /to"
  done
  START=$(date +%s)
  docker compose up -d --force-recreate crowdsec 2>&1 | tail -2
  if verify "$START"; then RESULT=rolled_back; DETAIL="$LATEST failed checks; back on $FROM with restored volumes"; finish 1; fi
  RESULT=rollback_failed; DETAIL="$LATEST failed AND rollback to $FROM failed verification - check now (bouncer is fail-open, so the edge is up but new bans may not apply)"
  finish 2
fi

# ---- no new release: hub content (parsers, scenarios, collections)
[[ $DRY_RUN == 1 ]] && { RESULT=current; DETAIL="(dry run) $FROM is latest; would run hub update/upgrade"; finish 0; }
hub_snapshot() { # installed item versions + data files (GeoIP, lists) - any change needs a reload
  cs hub list -o json 2>/dev/null | python3 -c 'import json,sys; [print(k, i["name"], i.get("local_version")) for k, v in sorted(json.load(sys.stdin).items()) for i in (v or [])]'
  docker exec crowdsec sh -c 'find /var/lib/crowdsec/data -maxdepth 1 -type f ! -name "crowdsec.db*" -exec md5sum {} +' 2>/dev/null | sort; }
BEFORE=$(hub_snapshot)
cs hub update >/dev/null 2>&1 || { TO=$FROM; DETAIL="hub update failed (network?)"; finish 1; }
UP=$(cs hub upgrade 2>&1) || { TO=$FROM; DETAIL="hub upgrade failed: $(tail -1 <<<"$UP")"; finish 1; }
AFTER=$(hub_snapshot)
TO=$FROM
if [[ $BEFORE != "$AFTER" ]]; then
  log "hub content changed:"; diff <(echo "$BEFORE") <(echo "$AFTER") | grep '^>' | cut -c1-120 | head -20
  START=$(date +%s)
  docker kill -s HUP crowdsec >/dev/null    # CrowdSec reloads parsers/scenarios on SIGHUP
  sleep 10
  if verify "$START"; then date +%s > "$STATE/last_change"; RESULT=hub_updated; finish 0; fi
  # A reload that broke something: a full restart re-reads everything cleanly.
  docker restart crowdsec >/dev/null; START=$(date +%s)
  if verify "$START"; then date +%s > "$STATE/last_change"; RESULT=hub_updated; DETAIL="needed a restart after reload"; finish 0; fi
  DETAIL="hub upgrade left CrowdSec failing its checks"; finish 1
fi
RESULT=current; DETAIL="$FROM is the latest release, hub content current"; finish 0
