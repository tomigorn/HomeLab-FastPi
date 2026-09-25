#!/usr/bin/env python3
"""Strip secrets and personal data out of an `ak export_blueprint` dump.

Runs INSIDE the authentik container (it needs PyYAML, which the Pi host lacks).
Reads a raw export, writes a sanitised one to stdout, and reports to stderr.

Why this exists: `ak export_blueprint` emits live OAuth2 client secrets and
invitation objects. An invitation's primary key IS its `itoken` -- see
InvitationStageView.get_invite(), which does Invitation.objects.filter(pk=token)
-- so exporting one publishes a working invite URL. Both were committed to a
PUBLIC repo before this existed (secrets since 2026-08-16); do not remove this
step without replacing it.
"""
import re
import sys

import yaml

# Entire entries dropped: the pk is the redeemable token.
DROP_MODELS = {"authentik_stages_invitation.invitation"}

# Value replaced when the key matches and the value looks like real material.
SECRET_KEYS = re.compile(
    r"(client_secret|_secret$|^secret$|key_data|private_key|password|"
    r"^key$|api_key|smtp_pass)",
    re.IGNORECASE,
)
# Keys that merely *contain* a secret-ish word but hold config, not secrets.
SAFE_KEYS = {
    "token_expiry", "token_length", "token_count", "password_stage",
    "password_field", "passwordless_flow", "secret_key_field",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PLACEHOLDER = "<redacted-by-sanitize-export>"

counts = {"entries_dropped": 0, "secrets_redacted": 0, "emails_redacted": 0}


def scrub(node):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in SAFE_KEYS:
                out[k] = scrub(v)
            elif SECRET_KEYS.search(str(k)) and isinstance(v, str) and len(v) >= 8:
                out[k] = PLACEHOLDER
                counts["secrets_redacted"] += 1
            elif isinstance(v, str) and EMAIL_RE.match(v) and not v.endswith("@authentik.local"):
                out[k] = PLACEHOLDER
                counts["emails_redacted"] += 1
            else:
                out[k] = scrub(v)
        return out
    if isinstance(node, list):
        return [scrub(x) for x in node]
    return node


def main(path):
    with open(path) as fh:
        doc = yaml.safe_load(fh)

    kept = []
    for entry in doc.get("entries", []):
        if isinstance(entry, dict) and entry.get("model") in DROP_MODELS:
            counts["entries_dropped"] += 1
            continue
        kept.append(scrub(entry))
    doc["entries"] = kept

    yaml.safe_dump(doc, sys.stdout, default_flow_style=False, sort_keys=False, width=100)
    print(
        "sanitised: {entries_dropped} entries dropped, "
        "{secrets_redacted} secrets redacted, {emails_redacted} emails redacted".format(**counts),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main(sys.argv[1])
