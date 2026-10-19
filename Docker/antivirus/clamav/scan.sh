#!/bin/sh
# Same file on fastpi, beefy and tower: Docker/antivirus/README.md in the fastpi repo.

STATE=${STATE:-/state}
TEXTFILE=${TEXTFILE:-/textfile}
DB_DIR=${DB_DIR:-/var/lib/clamav}
HOST=${HOST:-$(hostname)}
SCAN_HOST=${SCAN_HOST:-1}
LIMITS="--max-filesize=4000M --max-scansize=4000M"
TAB=$(printf '\t')

usage() {
	cat >&2 <<EOF
usage: scan.sh new        files under \$SCAN_ROOTS changed since the last good run, infected ones to \$QUARANTINE
       scan.sh all        everything under \$SCAN_ROOTS and /host (SCAN_HOST=0 skips it), report only
       scan.sh <path>...  quarantined when under \$SCAN_ROOTS, else report only
exit:  0 clean, 1 infected, 2 errors
EOF
	exit 2
}

[ $# -gt 0 ] || usage
if [ -z "$SCAN_ROOTS" ] || [ -z "$QUARANTINE" ]; then
	echo "scan.sh: SCAN_ROOTS and QUARANTINE must be set" >&2
	exit 2
fi
mkdir -p "$STATE" "$TEXTFILE"

case $1 in
	new) MODE=new ;;
	all) MODE=all ;;
	*) MODE=path ;;
esac
LOG=$STATE/last-$MODE.log
START=$(date +%s)
RC=0
: > "$LOG"

clam() {
	clamscan "$@" >> "$LOG" 2>&1
	r=$?
	[ "$r" -gt "$RC" ] && RC=$r
}

under_roots() {
	for root in $SCAN_ROOTS; do
		case $1 in "$root" | "$root"/*) return 0 ;; esac
	done
	return 1
}

list_find() {
	if [ -e "$STATE/last-run" ]; then newer="-newer $STATE/last-run"; else newer="-mmin -1440"; fi
	find $SCAN_ROOTS -xdev \
		\( -path "$QUARANTINE" -o -path '*/quarantine' -o -path '*/.snapshots' -o -path '*/incomplete' \) -prune -o \
		-type f ! -name '*.part' ! -name '*.!qB' $newer -print 2>> "$LOG"
}

list_btrfs() {
	: > "$STATE/last-gen.next"
	: > "$STATE/find-new.list"
	for root in $SCAN_ROOTS; do
		gen=$(awk -v r="$root" '$2 == r { print $1 }' "$STATE/last-gen" 2>/dev/null)
		btrfs subvolume find-new "$root" "${gen:-0}" > "$STATE/find-new.out" 2>> "$LOG" || return 1
		awk -v r="$root" '/^transid marker was/ { print $4, r }' "$STATE/find-new.out" >> "$STATE/last-gen.next"
		awk -v r="$root" '/^inode / { sub(/^.* flags [^ ]+ /, ""); print r "/" $0 }' "$STATE/find-new.out" >> "$STATE/find-new.list"
	done
	sort -u "$STATE/find-new.list" | while IFS= read -r f; do
		case $f in
			"$QUARANTINE"/* | */quarantine/* | */.snapshots/* | */incomplete/* | *.part | *.!qB) ;;
			*) [ -f "$f" ] && printf '%s\n' "$f" ;;
		esac
	done
	return 0
}

run_new() {
	list=$STATE/new.list
	touch "$STATE/last-run.next"
	sleep 1  # busybox find -newer compares whole seconds
	if [ "$SCAN_BTRFS" = 1 ]; then list_btrfs > "$list" || RC=2; else list_find > "$list" || RC=2; fi
	LISTED=$(wc -l < "$list" | tr -d ' ')
	[ "$LISTED" -gt 0 ] && clam --file-list="$list" -i --move="$QUARANTINE" $LIMITS
}

run_all() {
	targets=$SCAN_ROOTS
	[ "$SCAN_HOST" = 1 ] && targets="$targets /host"
	clam -r -i --cross-fs=no --exclude-dir="^$QUARANTINE" $LIMITS $targets
}

run_paths() {
	: > "$STATE/path-move.list"
	: > "$STATE/path-report.list"
	for p in "$@"; do
		if under_roots "$p"; then
			printf '%s\n' "$p" >> "$STATE/path-move.list"
		else
			printf '%s\n' "$p" >> "$STATE/path-report.list"
		fi
	done
	[ -s "$STATE/path-move.list" ] && clam --file-list="$STATE/path-move.list" -r -i --exclude-dir="^$QUARANTINE" --move="$QUARANTINE" $LIMITS
	[ -s "$STATE/path-report.list" ] && clam --file-list="$STATE/path-report.list" -r -i --cross-fs=no $LIMITS
}

LISTED=
if [ ! -d "$QUARANTINE" ]; then
	echo "ERROR: $QUARANTINE missing (disk not mounted?)" >> "$LOG"
	RC=2
	LISTED=0
else
	case $MODE in
		new) run_new ;;
		all) run_all ;;
		path) run_paths "$@" ;;
	esac
fi
cat "$LOG"

HITS=$STATE/hits.tsv
awk '/ FOUND$/ { sub(/ FOUND$/, ""); i = match($0, /: [^:]*$/); print substr($0, 1, i - 1) "\t" substr($0, i + 2) }' "$LOG" > "$HITS"
INFECTED=$(wc -l < "$HITS" | tr -d ' ')
SCANNED=$(awk -F': ' '/^Scanned files:/ { s += $2 } END { print s + 0 }' "$LOG")
[ -n "$LISTED" ] || LISTED=$SCANNED
ERRORS=0
if [ "$RC" -ge 2 ]; then
	ERRORS=$(grep -cE '^(ERROR|WARNING): ' "$LOG")
	[ "$ERRORS" -gt 0 ] || ERRORS=1
fi

if [ "$INFECTED" -gt 0 ]; then
	cp "$HITS" "$STATE/last-infected.txt"
	now=$(date -Iseconds)
	while IFS="$TAB" read -r path sig; do
		grep -qF "$path: moved to " "$LOG" && printf '%s\t%s\t%s\n' "$now" "$path" "$sig" >> "$QUARANTINE/index.txt"
	done < "$HITS"
fi
TOTAL=$(( $(cat "$STATE/infected-total" 2>/dev/null || echo 0) + INFECTED ))
echo "$TOTAL" > "$STATE/infected-total"

if [ "$MODE" = new ] && [ "$ERRORS" -eq 0 ]; then
	mv "$STATE/last-run.next" "$STATE/last-run"
	[ -e "$STATE/last-gen.next" ] && mv "$STATE/last-gen.next" "$STATE/last-gen"
fi

L="host=\"$HOST\",mode=\"$MODE\""
cat > "$STATE/metrics-$MODE" <<EOF
clamav_last_run_timestamp_seconds{$L} $(date +%s)
clamav_run_duration_seconds{$L} $(( $(date +%s) - START ))
clamav_files_listed{$L} $LISTED
clamav_files_scanned{$L} $SCANNED
clamav_scan_errors{$L} $ERRORS
clamav_infected_last_run{$L} $INFECTED
EOF

db=$(ls "$DB_DIR"/daily.cld "$DB_DIR"/daily.cvd 2>/dev/null | head -1)
if [ -n "$db" ] && info=$(sigtool --info "$db" 2>/dev/null); then
	built=$(printf '%s\n' "$info" | awk '/^Build time:/ {
		m = index("JanFebMarAprMayJunJulAugSepOctNovDec", $4); printf "%s-%02d-%02d %s", $5, (m + 2) / 3, $3, $6 }')
	built=$(TZ=UTC date -d "$built" +%s 2>/dev/null)
	DB_VERSION=$(printf '%s\n' "$info" | awk '/^Version:/ { print $2 }')
	[ -n "$built" ] && SIG_AGE=$(( $(date +%s) - built ))
fi

{
	cat "$STATE"/metrics-*
	echo "clamav_infected_total{host=\"$HOST\"} $TOTAL"
	[ -n "$SIG_AGE" ] && echo "clamav_signature_age_seconds{host=\"$HOST\"} $SIG_AGE"
	[ -n "$DB_VERSION" ] && echo "clamav_db_version{host=\"$HOST\"} $DB_VERSION"
} | sort | awk '
	{ name = $1; sub(/\{.*/, "", name) }
	name != prev { type = (name == "clamav_infected_total") ? "counter" : "gauge"; print "# TYPE " name " " type; prev = name }
	{ print }' > "$TEXTFILE/.clamav.prom.tmp"
mv "$TEXTFILE/.clamav.prom.tmp" "$TEXTFILE/clamav.prom"

echo "scan.sh $MODE: listed=$LISTED scanned=$SCANNED infected=$INFECTED errors=$ERRORS"
[ "$ERRORS" -gt 0 ] && exit 2
[ "$INFECTED" -gt 0 ] && exit 1
exit 0
