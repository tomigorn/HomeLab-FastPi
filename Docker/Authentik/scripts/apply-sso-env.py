#!/usr/bin/env python3
"""Write secrets from provision-admin-sso.py into gitignored .env files.

Reads stdin. Each line "ENV <dir>/.env KEY=value" upserts KEY in <base>/<dir>/.env
(replace the existing KEY= line in place, else append) and prints "set <path> KEY"
- never the value. Any other line is passed through, except lines mentioning
SECRET / TOKEN / PASSWORD, which print "[redacted line]".

Refused (error on stderr, nonzero exit after all lines are processed): any path that
is not exactly <dir>/.env directly under base, that resolves outside base, whose
directory does not exist, or that git tracks.

base defaults to /home/pi/Projects/Docker; override with --base for tests.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_BASE = Path("/home/pi/Projects/Docker")
PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*/\.env$")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SENSITIVE_RE = re.compile(r"secret|token|password", re.IGNORECASE)


class Refused(Exception):
    pass


def resolve_target(base: Path, rel: str) -> Path:
    if not PATH_RE.match(rel) or rel.split("/")[0] in (".", ".."):
        raise Refused(f"refused path {rel!r}: must be <dir>/.env directly under base")
    base_real = base.resolve()
    target = (base / rel)
    if not target.parent.is_dir():
        raise Refused(f"refused path {rel!r}: directory does not exist")
    real = target.parent.resolve() / ".env"
    if real.parent.parent != base_real:
        raise Refused(f"refused path {rel!r}: resolves outside base")
    if real.is_symlink():
        raise Refused(f"refused path {rel!r}: .env is a symlink")
    tracked = subprocess.run(
        ["git", "-C", str(real.parent), "ls-files", "--error-unmatch", ".env"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if tracked.returncode == 0:
        raise Refused(f"refused path {rel!r}: file is tracked by git")
    return real


def upsert(path: Path, key: str, value: str) -> None:
    if path.exists():
        text = path.read_text()
        mode = path.stat().st_mode & 0o7777
    else:
        text, mode = "", 0o600
    lines = text.splitlines()
    new = f"{key}={value}"
    for i, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[i] = new
            break
    else:
        lines.append(new)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(stdin, stdout, stderr, base: Path = DEFAULT_BASE) -> int:
    failed = False
    for raw in stdin:
        line = raw.rstrip("\n")
        if line.startswith("ENV "):
            parts = line.split(" ", 2)
            kv = parts[2] if len(parts) == 3 else ""
            key, sep, value = kv.partition("=")
            if not sep or not KEY_RE.match(key):
                print("error: malformed ENV line (content not shown)", file=stderr)
                failed = True
                continue
            rel = parts[1]
            try:
                upsert(resolve_target(base, rel), key, value)
            except Refused as exc:
                print(f"error: {exc} (key {key})", file=stderr)
                failed = True
                continue
            print(f"set {rel} {key}", file=stdout)
        elif SENSITIVE_RE.search(line):
            print("[redacted line]", file=stdout)
        else:
            print(line, file=stdout)
    return 1 if failed else 0


if __name__ == "__main__":
    base = DEFAULT_BASE
    if len(sys.argv) == 3 and sys.argv[1] == "--base":
        base = Path(sys.argv[2])
    elif len(sys.argv) != 1:
        sys.exit("usage: apply-sso-env.py [--base DIR] < input")
    sys.exit(main(sys.stdin, sys.stdout, sys.stderr, base))
