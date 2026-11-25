#!/usr/bin/env bash
# Runs userns-rollback.sh panic against a fake sudo/systemctl/docker and a scratch daemon.json. Usage: scripts/test_userns_rollback.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
mkdir -p "$T/bin" "$T/etc"
# fake sudo refuses anything outside the scratch dir, so the real /etc/docker is never touched
printf '#!/usr/bin/env bash\n[[ $1 == -n ]] && shift\nfor a in "$@"; do [[ $a == /* && $a != %s/* && $a != /usr/* && $a != /bin/* ]] && { echo "fake sudo: refused $a" >&2; exit 97; }; done\nexec "$@"\n' "$T" > "$T/bin/sudo"
printf '#!/usr/bin/env bash\necho "$*" >> "%s/systemctl.log"\n' "$T" > "$T/bin/systemctl"
cat > "$T/bin/docker" <<'STUB'
#!/usr/bin/env bash
case $1 in
  info) if [[ " $* " == *" --format "* ]]; then cat "$FAKE_SECOPTS"; else seq 1 5000; cat "$FAKE_SECOPTS"; fi ;;
  ps) echo c1; echo c2 ;;
esac
STUB
chmod +x "$T/bin/"*
export RESTART_WAIT=0 PATH="$T/bin:$PATH" DAEMON_JSON="$T/etc/daemon.json" FAKE_SECOPTS="$T/secopts"
[[ $(command -v sudo) == "$T/bin/sudo" && $(command -v systemctl) == "$T/bin/systemctl" ]] || { echo "fakes not first in PATH, refusing to run"; exit 1; }

echo "panic removes only the userns-remap key, keeps the rest of daemon.json"
printf '{"dns":["192.168.1.2"],"log-opts":{"max-size":"10m"},"live-restore":true,"userns-remap":"default"}\n' > "$DAEMON_JSON"
echo "[name=seccomp,profile=builtin name=cgroupns]" > "$FAKE_SECOPTS"
out=$(bash "$HERE/userns-rollback.sh" panic 2>&1); rc=$?
[[ $rc == 0 ]] && ok "exit 0" || bad "exit 0" "rc=$rc $out"
[[ -f $DAEMON_JSON ]] && ok "daemon.json kept" || bad "daemon.json kept"
[[ $(jq -c . "$DAEMON_JSON" 2>/dev/null) == '{"dns":["192.168.1.2"],"log-opts":{"max-size":"10m"},"live-restore":true}' ]] && ok "only userns-remap removed" || bad "only userns-remap removed" "$(cat "$DAEMON_JSON" 2>&1)"
[[ -n $(ls "$T"/etc/daemon.json.bak-* 2>/dev/null) ]] && grep -q userns-remap "$T"/etc/daemon.json.bak-* && ok "original saved next to it before the change" || bad "backup of daemon.json" "$(ls "$T/etc")"
grep -q "restart docker" "$T/systemctl.log" && ok "docker restarted" || bad "docker restarted"
[[ $out == *"remap OFF"* ]] && ok "reports remap off" || bad "reports remap off" "$out"

echo "docker still reports userns: warning, even when docker info is long (pipefail)"
printf '{"userns-remap":"default"}\n' > "$DAEMON_JSON"; : > "$T/systemctl.log"
echo "[name=seccomp,profile=builtin name=userns]" > "$FAKE_SECOPTS"
out=$(bash "$HERE/userns-rollback.sh" panic 2>&1)
[[ $out == *"WARNING"*"userns"* ]] && ok "warns that userns is still on" || bad "warns that userns is still on" "$out"

echo "no daemon.json or no remap key: nothing written, docker still restarted"
rm -f "$DAEMON_JSON" "$T"/etc/daemon.json.bak-*; : > "$T/systemctl.log"; echo "[]" > "$FAKE_SECOPTS"
out=$(bash "$HERE/userns-rollback.sh" panic 2>&1); rc=$?
[[ $rc == 0 && ! -e $DAEMON_JSON ]] && ok "missing daemon.json not created" || bad "missing daemon.json" "rc=$rc $out"
printf '{"dns":["192.168.1.2"]}\n' > "$DAEMON_JSON"
out=$(bash "$HERE/userns-rollback.sh" panic 2>&1)
[[ $(jq -c . "$DAEMON_JSON") == '{"dns":["192.168.1.2"]}' && -z $(ls "$T"/etc/daemon.json.bak-* 2>/dev/null) ]] && ok "no remap key: file untouched, no backup" || bad "no remap key: untouched" "$(ls "$T/etc") $out"

echo "broken daemon.json: aborts before the restart"
echo '{"dns": [' > "$DAEMON_JSON"; : > "$T/systemctl.log"
out=$(bash "$HERE/userns-rollback.sh" panic 2>&1); rc=$?
[[ $rc != 0 && ! -s $T/systemctl.log && $(cat "$DAEMON_JSON") == '{"dns": [' ]] && ok "exit non-zero, file and docker untouched" || bad "broken json aborts" "rc=$rc $(cat "$T/systemctl.log") $out"

echo "$PASS passed, $FAIL failed"; [[ $FAIL == 0 ]]
