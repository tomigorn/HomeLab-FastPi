# Beefy waker customizations (Docker/CUSTOMIZATIONS.md "Beefy-Waker"): the app plus the host wake timers.
BWD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Beefy-Waker" && pwd)
if want waker; then
  check waker.status '"up"' "$(curl -s -m 5 http://192.168.1.2:9001/status)"
  check waker.version '^same$' "$(v=$(curl -s -m 5 http://192.168.1.2:9001/ | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1); [[ $v == "v$(cat "$BWD/app/VERSION")" ]] && echo same || echo "page ${v:-none} repo $(cat "$BWD/app/VERSION")")"
fi
check waker.timers '^active active active active$' "$(systemctl is-active beefy-maintenance-wake.timer beefy-night-downloads-wake.timer beefy-night-downloads-poll.timer beefy-idle-pull.timer | xargs)"
check waker.units-installed '^same same same$' "$(for u in maintenance-wake/beefy-maintenance-wake night-downloads-wake/beefy-night-downloads-poll night-downloads-wake/beefy-night-downloads-wake; do cmp -s "$BWD/$u.service" /etc/systemd/system/${u#*/}.service && echo same || echo "${u#*/} differs"; done | xargs)"
check waker.night-wake-user '^pi$' "$(systemctl show -p User --value beefy-night-downloads-wake.service)"   # S-08: not root, the script is pi-writable
check waker.ssh-hooks '^2$' "$(grep -cE '^Match host (beefy|tower) exec' /home/pi/.ssh/config)"
