# M4b-Auto-Merge (Docker/CUSTOMIZATIONS.md "M4b-Auto-Merge").
if want m4b-auto-merge; then
  # library and quarantine must share one bind mount, else the promote rename fails with EXDEV
  check m4b.one-mount '^disk=1 lib=0 quarantine=0$' "$(m=$(docker inspect -f '{{range .Mounts}}{{.Destination}} {{end}}' m4b-auto-merge 2>&1); c() { grep -cx -- "$1" <<<"${m// /$'\n'}"; }; echo "disk=$(c /mnt/seagate-black) lib=$(c /mnt/seagate-black/library/audiobooks) quarantine=$(c /mnt/seagate-black/m4b-originals-quarantine)")"
fi
