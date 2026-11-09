# M4b-Auto-Merge (Docker/CUSTOMIZATIONS.md "M4b-Auto-Merge").
if want m4b-auto-merge; then
  # library and quarantine must share one bind mount, else the promote rename fails with EXDEV
  check m4b.one-mount '^disk=1 lib=0 quarantine=0$' "$(m=$(docker inspect -f '{{range .Mounts}}{{.Destination}} {{end}}' m4b-auto-merge 2>&1); c() { grep -cx -- "$1" <<<"${m// /$'\n'}"; }; echo "disk=$(c /mnt/seagate-black) lib=$(c /mnt/seagate-black/library/audiobooks) quarantine=$(c /mnt/seagate-black/m4b-originals-quarantine)")"
  # the Rust watcher (not the legacy Python one) on a read-only root with tini as PID 1
  check m4b.rust-watcher '^/usr/local/bin/m4b-auto-merge ro=true init=true$' "$(docker inspect -f '{{index .Config.Entrypoint 0}} ro={{.HostConfig.ReadonlyRootfs}} init={{.HostConfig.Init}}' m4b-auto-merge 2>&1)"
  check m4b.rest-read-only '^lost\+found=false podcasts=false$' "$(docker inspect -f '{{range .Mounts}}{{.Destination}}={{.RW}} {{end}}' m4b-auto-merge 2>&1 | tr ' ' '\n' | grep -oE '(podcasts|lost\+found)=(true|false)$' | sort | xargs)"
fi
