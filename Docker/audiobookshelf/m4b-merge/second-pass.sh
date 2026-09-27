#!/usr/bin/env bash
# Wait for the main batch to finish, then run again to pick up anything that
# failed. The run is idempotent - a folder that is already a single audio file is
# skipped - so a second pass merges exactly the books the first one could not,
# using whatever merge-book.py is current (it is redeployed to beefy each run).
#
# Launched as a lingering systemd user unit so it survives logout:
#   systemd-run --user --unit=m4b-merge-pass2 ... second-pass.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "pass 2: waiting for m4b-merge.service to finish..."
while systemctl --user is-active --quiet m4b-merge.service; do
    sleep 60
done
echo "pass 2: main batch finished at $(date -Is), starting retry pass"

# Books that failed the first time keep their originals, so they are still
# multi-file and will simply be found again.
exec ./orchestrate.py --jobs 10 --include-multipart \
     --progress "$HERE/runs/progress-pass2.json"
