#!/usr/bin/env bash
# Start/stop Jenkins on demand. Jenkins runs on-demand to save ~313 MB RAM;
# automatic webhook/SCM builds only run while it is up. Start it when working
# on LoyaltyCards, stop it when done.
set -euo pipefail
C=jenkins-jdk-21
case "${1:-}" in
  start)  docker start "$C"  && echo "Jenkins starting — wait ~30-60s, then open the Jenkins URL." ;;
  stop)   docker stop  "$C"  && echo "Jenkins stopped (RAM freed)." ;;
  status) docker ps -a --filter "name=^/${C}$" --format 'table {{.Names}}\t{{.Status}}' ;;
  *) echo "usage: $0 {start|stop|status}"; exit 1 ;;
esac
