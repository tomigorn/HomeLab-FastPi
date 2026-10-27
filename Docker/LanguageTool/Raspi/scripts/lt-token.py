#!/usr/bin/env python3
"""Personal LanguageTool access links (README "Install and new users").
  lt-token.py add <Person-Device>   create a link, prints the URL once
  lt-token.py list                  labels only, never tokens
  lt-token.py remove <Person-Device>
Edits the gitignored Traefik/traefik/dynamic/languagetool-token.yml (Traefik reloads it by itself)."""
import os
import re
import secrets
import shutil
import sys
import time

FILE = os.environ.get("LT_TOKEN_FILE", "/home/pi/Projects/Docker/Traefik/traefik/dynamic/languagetool-token.yml")
HOST = os.environ.get("LT_HOST", "lang-tool.ddns.net")
BACKUP_DIR = os.environ.get("LT_BACKUP_DIR", "/home/pi/backups/languagetool-token")
LABEL_RE = re.compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)+$")
MW_HEADER = "\n  middlewares:\n"


def router(label, token):
    return f"""
    languagetool-token-{label}:
      rule: "Host(`{HOST}`) && PathPrefix(`/lt-{token}`)"
      entryPoints: ["langtool"]
      priority: 5
      service: languagetool
      middlewares:
        - languagetool-token-strip-{label}
        - languagetool-secure-headers
      tls:
        certResolver: le
"""


def middleware(label, token):
    return f"""    languagetool-token-strip-{label}:
      replacePathRegex:
        regex: "^/lt-{token}/(?:api/)?(?:v2/)?(.*)"
        replacement: "/v2/$1"
"""


def labels(text):
    return re.findall(r"^    languagetool-token-(?!strip-)([A-Za-z0-9-]+):$", text, re.M)


def _write(text):
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    bak = os.path.join(BACKUP_DIR, f"languagetool-token.yml.{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(FILE, bak)
    os.chmod(bak, 0o600)
    tmp = os.path.join(os.path.dirname(FILE), ".languagetool-token.tmp")
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, os.stat(FILE).st_mode & 0o777)
    os.replace(tmp, FILE)


def add(label):
    if not LABEL_RE.match(label):
        raise SystemExit(f"label must look like Person-Device or Person-Device-Client, got {label!r}")
    text = open(FILE).read()
    if label in labels(text):
        raise SystemExit(f"{label} already has a link (remove it first to replace it)")
    if MW_HEADER not in text:
        raise SystemExit(f"{FILE}: no 'middlewares:' section found")
    token = secrets.token_hex(32)
    text = text.replace(MW_HEADER, router(label, token) + MW_HEADER, 1).rstrip("\n") + "\n" + middleware(label, token)
    _write(text)
    return f"https://{HOST}/lt-{token}"


def remove(label):
    text = open(FILE).read()
    if label not in labels(text):
        raise SystemExit(f"{label}: no such link")
    block = r"^    languagetool-token-{}{}:\n(?:      .*\n)+"
    text = re.sub(block.format("", re.escape(label)), "", text, flags=re.M)
    text = re.sub(block.format("strip-", re.escape(label)), "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    _write(text)


def main(argv):
    if argv[:1] == ["list"]:
        print("\n".join(labels(open(FILE).read())))
    elif argv[:1] == ["add"] and len(argv) == 2:
        print(add(argv[1]))
    elif argv[:1] == ["remove"] and len(argv) == 2:
        remove(argv[1])
        print(f"removed {argv[1]}")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
