#!/usr/bin/env bash
# Snapshot the current Authentik configuration (flows, stages, policies, prompts,
# brands, property mappings, etc.) to a git-committable blueprint YAML.
#
# This file is a RECORD / BACKUP only — it is NOT mounted into the stack and is
# NOT auto-applied. Re-run this after changing config in the Authentik UI to refresh
# the snapshot, then `git add authentik-config-export.yaml && git commit`.
#
# The export contains NO secrets (no certificate private keys, password hashes,
# API token values, or SMTP credentials). It DOES include user objects
# (usernames/emails, but no passwords).
#
# To restore config onto a fresh instance you could feed this file to
# `ak apply_blueprint`, but treat that as a manual, reviewed operation.
set -euo pipefail
cd "$(dirname "$0")"
docker compose exec -T server ak export_blueprint 2>/dev/null > authentik-config-export.yaml
echo "Wrote authentik-config-export.yaml ($(wc -l < authentik-config-export.yaml) lines)"
