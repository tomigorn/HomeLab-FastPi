#!/bin/sh
# Stand-in for m4b-merge/orchestrate.py: records the call, optionally sleeps, promotes, and exits with the scripted code.
d="$FAKE_DIR"
echo "FAKE-ORCHESTRATOR-OUTPUT"
printf 'cwd=%s args=%s env=%s\n' "$(pwd)" "$*" "$FAKE_MARK" >> "$d/calls"
[ -f "$d/sleep" ] && sleep "$(cat "$d/sleep")"
if [ -f "$d/promote" ]; then
  book="$LIB_DIR/$(cat "$d/promote")"
  mkdir -p "$d/quarantine"
  find "$book" -maxdepth 1 -type f -name '*.mp3' -exec mv {} "$d/quarantine/" \;
  echo merged > "$book/merged.m4b"
fi
rc=0
if [ -s "$d/rcseq" ]; then
  rc=$(head -n 1 "$d/rcseq")
  sed -i 1d "$d/rcseq"
fi
exit "$rc"
