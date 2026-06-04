#!/usr/bin/env bash
#
# Interactively set the basic-auth password for the Claude-Mockups site.
# The plaintext is typed at a silent prompt — it never appears in shell
# history, in process arguments, or on disk. Only the bcrypt hash is stored
# (in .env, gitignored). Re-applies the change by recreating the container.
#
set -euo pipefail
cd "$(dirname "$0")"

read -rsp "New password:     " PW;  echo
read -rsp "Confirm password: " PW2; echo
if [ -z "$PW" ] || [ "$PW" != "$PW2" ]; then
  echo "Passwords empty or do not match — aborting." >&2
  exit 1
fi

# Hash via stdin (no --plaintext, so the password is never an argument),
# then double every $ to $$ for docker-compose .env escaping.
HASH="$(printf '%s\n' "$PW" | docker run --rm -i caddy:alpine caddy hash-password | sed 's/\$/$$/g')"
unset PW PW2

# Replace (or append) the BASIC_AUTH_HASH line in .env, preserving order.
tmp="$(mktemp)"
awk -v h="$HASH" '
  /^BASIC_AUTH_HASH=/ { print "BASIC_AUTH_HASH=" h; found=1; next }
  { print }
  END { if (!found) print "BASIC_AUTH_HASH=" h }
' .env > "$tmp"
mv "$tmp" .env

echo "Updated .env. Recreating container…"
docker compose up -d --force-recreate
echo "Done. New password is live at https://claude-mockups.holy-grail.ch"
