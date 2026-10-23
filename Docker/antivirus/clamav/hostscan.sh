#!/bin/sh
# Whole-host scan: root with DAC_READ_SEARCH (a non-root uid gets no effective caps in Docker), results handed back to the uids that own the shared state.
/scan.sh all
rc=$?
chown -R 65039:65039 "${STATE:-/state}"
chown 65039:65046 "${TEXTFILE:-/textfile}/clamav.prom"
exit $rc
