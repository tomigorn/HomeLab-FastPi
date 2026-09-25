#!/usr/bin/env bash
# Snapshot the current Authentik configuration (flows, stages, policies, prompts,
# brands, property mappings, etc.) to a git-committable blueprint YAML.
#
# This file is a RECORD / BACKUP only - it is NOT mounted into the stack and is
# NOT auto-applied. Re-run this after changing config in the Authentik UI to refresh
# the snapshot, then `git add authentik-config-export.yaml && git commit`.
#
# SECRETS: `ak export_blueprint` DOES emit live OAuth2 client secrets, and it
# exports invitation objects whose primary key IS the redeemable ?itoken= value.
# Both were committed to this PUBLIC repo before sanitize-export.py existed
# (client secrets from 2026-08-16, an invite token on 2026-09-25). Every export
# is therefore piped through sanitize-export.py, which drops invitation entries
# and replaces secrets and user email addresses with a placeholder. A guard at
# the end of this script refuses to write the file if anything secret-shaped
# survives. Do not bypass either step.
#
# The sanitised file still contains usernames, group names, flow/stage/policy
# config and OAuth2 client_ids. It is NOT a DR backup - for that, back up the
# `database` volume and `.env`.
#
# To restore config onto a fresh instance you could feed this file to
# `ak apply_blueprint`, but treat that as a manual, reviewed operation, and note
# that redacted values must be re-entered by hand.
set -euo pipefail
cd "$(dirname "$0")"

OUT=authentik-config-export.yaml
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

docker compose exec -T server sh -c 'ak export_blueprint 2>/dev/null > /tmp/raw-export.yaml'
docker cp sanitize-export.py authentik-server:/tmp/sanitize-export.py >/dev/null
docker compose exec -T server python3 /tmp/sanitize-export.py /tmp/raw-export.yaml > "$TMP"
docker compose exec -T server rm -f /tmp/raw-export.yaml /tmp/sanitize-export.py

# Guard: refuse to publish anything that still looks like a credential.
if grep -qE '[A-Za-z0-9]{64,}' "$TMP"; then
  echo "REFUSING TO WRITE: a 64+ char token-like string survived sanitising." >&2
  grep -nE '[A-Za-z0-9]{64,}' "$TMP" | cut -c1-80 >&2
  exit 1
fi
# NB: the value class must exclude whitespace too -- with a bare [^<], the
# preceding [[:space:]]* can match zero chars and [^<] then matches the space,
# firing on correctly-redacted lines.
if grep -qiE '^[[:space:]]*(client_secret|key_data|private_key):[[:space:]]*[^<[:space:]]' "$TMP"; then
  echo "REFUSING TO WRITE: an unredacted secret key survived sanitising." >&2
  exit 1
fi

mv "$TMP" "$OUT"
trap - EXIT
echo "Wrote $OUT ($(wc -l < "$OUT") lines)"
