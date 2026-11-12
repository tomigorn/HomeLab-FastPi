#!/usr/bin/env bash
# Offline test for scripts/tower-flash-backup.sh: fake ssh/rsync on PATH, temp DEST.
set -uo pipefail
script="$(cd "$(dirname "$0")/.." && pwd)/scripts/tower-flash-backup.sh"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/src" "$work/tf"
printf 'ssh_ok=1\n' > "$work/ssh_mode"
cat > "$work/bin/ssh" <<EOS
#!/usr/bin/env bash
[[ \$(cat "$work/ssh_mode") == ok ]]
EOS
cat > "$work/bin/rsync" <<EOS
#!/usr/bin/env bash
dest="\${@: -1}"
for f in "$work"/src/*; do cmp -s "\$f" "\$dest/\$(basename "\$f")" || cp -a --remove-destination "\$f" "\$dest/"; done
exit 0
EOS
chmod +x "$work/bin/"*
echo ok > "$work/ssh_mode"
echo same > "$work/src/same.txt"; echo v1 > "$work/src/changing.txt"

run() { PATH="$work/bin:$PATH" DEST="$work/dest" TODAY="$1" TEXTFILE_DIR="$work/tf" HOME="$work" bash "$script" >/dev/null 2>&1; }
fail=0
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }

run 2026-01-01; r1=$?
echo v2 > "$work/src/changing.txt"
run 2026-01-02; r2=$?
d="$work/dest"
check "both runs exit 0" '[[ $r1 == 0 && $r2 == 0 ]]'
check "day 1 is a real dir" '[[ -d $d/2026-01-01 && ! -L $d/2026-01-01 ]]'
check "day 2 is a real dir" '[[ -d $d/2026-01-02 && ! -L $d/2026-01-02 ]]'
check "latest -> day 2" '[[ $(readlink $d/latest) == 2026-01-02 ]]'
check "unchanged file hard-linked" '[[ $(stat -c %h $d/2026-01-02/same.txt) -gt 1 ]]'
check "day 1 content untouched" '[[ $(cat $d/2026-01-01/changing.txt) == v1 ]]'
check "metric written" 'grep -q "^tower_flash_backup_last_success_timestamp_seconds [0-9]" "$work/tf/tower_flash_backup.prom"'

echo down > "$work/ssh_mode"
rm -f "$work/tf/tower_flash_backup.prom"
run 2026-01-03; r3=$?
check "ssh down: exit 0" '[[ $r3 == 0 ]]'
check "ssh down: no snapshot" '[[ ! -e $d/2026-01-03 ]]'
check "ssh down: no metric" '[[ ! -e $work/tf/tower_flash_backup.prom ]]'
exit $fail
