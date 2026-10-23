#!/usr/bin/env python3
"""Write what the provision-*-sso.py scripts print into gitignored files.

Reads stdin. Each line "ENV <dir>/.env KEY=value" upserts KEY in <base>/<dir>/.env
(replace the existing KEY= line in place, else append) and prints "set <path> KEY"
- never the value. Non-secret values only (client ids). Secrets come as
"FILE <dir>/secrets/<name> <uid>:<gid> <mode> value": the bare value (no newline) is
written to that file with that owner and mode (0400/0440/0600/0640), directly when
the owner is us, else via `sudo -n install ... /dev/stdin <path>` (value on stdin,
never in argv); prints "set <path>". The path must be gitignored (git check-ignore). Any other line is passed through, except lines mentioning
SECRET / TOKEN / PASSWORD, which print "[redacted line]".

Refused (error on stderr, nonzero exit after all lines are processed): any path that
is not exactly <dir>/.env directly under base, that resolves outside base, whose
directory does not exist, or that git tracks - or whose tracking git cannot
confirm (not a work tree, git missing): fail closed. Write errors skip that
line only, so later secrets in the pipe are still written.

base defaults to /home/pi/Projects/Docker; override with --base. --dry-run writes
nothing and prints "would set <path> KEY" / "would write <path> (<owner> <mode>)".
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
FILE_PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*/secrets/[A-Za-z0-9_][A-Za-z0-9._-]*$")
OWNER_RE = re.compile(r"^(\d+):(\d+)$")
MODE_RE = re.compile(r"^0[46][40]0$")


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
    # Fail closed: only exit 1 ("did not match any file") counts as untracked. 0 is
    # tracked; anything else (not a git repo, git error) or git missing is refused.
    try:
        tracked = subprocess.run(
            ["git", "-C", str(real.parent), "ls-files", "--error-unmatch", ".env"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise Refused(f"refused path {rel!r}: git not available to check tracking")
    if tracked.returncode == 0:
        raise Refused(f"refused path {rel!r}: file is tracked by git")
    if tracked.returncode != 1:
        raise Refused(f"refused path {rel!r}: git tracking check failed "
                      f"(exit {tracked.returncode})")
    return real


def resolve_file(base: Path, rel: str) -> Path:
    if not FILE_PATH_RE.match(rel) or ".." in rel.split("/"):
        raise Refused(f"refused path {rel!r}: must be <dir>/secrets/<name> directly under base")
    target = base / rel
    if not target.parent.is_dir():
        raise Refused(f"refused path {rel!r}: directory does not exist")
    if target.parent.is_symlink() or target.is_symlink():
        raise Refused(f"refused path {rel!r}: symlink")
    real = target.parent.resolve() / target.name
    if real.parent.parent.parent != base.resolve():
        raise Refused(f"refused path {rel!r}: resolves outside base")
    # exit 0 = ignored and untracked; 1 = not ignored (or tracked); else git broke: fail closed
    try:
        ignored = subprocess.run(["git", "-C", str(real.parent), "check-ignore", "-q", real.name],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise Refused(f"refused path {rel!r}: git not available to check ignore rules")
    if ignored.returncode == 1:
        raise Refused(f"refused path {rel!r}: not ignored by git")
    if ignored.returncode != 0:
        raise Refused(f"refused path {rel!r}: git ignore check failed (exit {ignored.returncode})")
    return real


def write_file(path: Path, value: str, uid: int, gid: int, mode: int) -> None:
    if os.geteuid() == 0 or (uid, gid) == (os.getuid(), os.getgid()):
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secret.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(value)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, mode)
            if os.geteuid() == 0:
                os.chown(tmp, uid, gid)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return
    done = subprocess.run(["sudo", "-n", "install", "-o", str(uid), "-g", str(gid),
                           "-m", f"{mode:04o}", "/dev/stdin", str(path)],
                          input=value, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if done.returncode != 0:
        raise OSError(f"sudo install exit {done.returncode}")


def apply_file(line: str, base: Path, stdout, stderr, dry_run: bool) -> bool:
    parts = line.split(" ", 4)
    if len(parts) != 5 or not parts[4]:
        print("error: malformed FILE line (content not shown)", file=stderr)
        return False
    _, rel, owner, mode, value = parts
    m = OWNER_RE.match(owner)
    if not m or not MODE_RE.match(mode):
        print(f"error: refused owner/mode for {rel!r}: need <uid>:<gid> and 0400/0440/0600/0640",
              file=stderr)
        return False
    try:
        path = resolve_file(base, rel)
        if dry_run:
            print(f"would write {rel} ({owner} {mode})", file=stdout)
            return True
        write_file(path, value, int(m.group(1)), int(m.group(2)), int(mode, 8))
    except Refused as exc:
        print(f"error: {exc}", file=stderr)
        return False
    except OSError as exc:
        print(f"error: could not write {rel!r}: {type(exc).__name__}", file=stderr)
        return False
    print(f"set {rel}", file=stdout)
    return True


def upsert(path: Path, key: str, value: str) -> None:
    owner = None
    if path.exists():
        text = path.read_text()
        st = path.stat()
        mode, owner = st.st_mode & 0o7777, (st.st_uid, st.st_gid)
    else:
        text, mode = "", 0o600
    new = f"{key}={value}"
    lines, replaced = [], False
    for line in text.splitlines():
        if line.startswith(key + "="):
            if not replaced:  # first occurrence keeps its position
                lines.append(new)
                replaced = True
            continue  # later duplicates are dropped
        lines.append(line)
    if not replaced:
        lines.append(new)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        if owner is not None:
            try:
                os.chown(tmp, *owner)
            except PermissionError:
                pass  # not root and not the owner: keep our own ownership
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(stdin, stdout, stderr, base: Path = DEFAULT_BASE, dry_run: bool = False) -> int:
    failed = False
    for raw in stdin:
        line = raw.rstrip("\n")
        if line.startswith("FILE "):
            failed |= not apply_file(line, base, stdout, stderr, dry_run)
        elif line.startswith("ENV "):
            parts = line.split(" ", 2)
            kv = parts[2] if len(parts) == 3 else ""
            key, sep, value = kv.partition("=")
            if not sep or not KEY_RE.match(key):
                print("error: malformed ENV line (content not shown)", file=stderr)
                failed = True
                continue
            rel = parts[1]
            try:
                target = resolve_target(base, rel)
                if dry_run:
                    print(f"would set {rel} {key}", file=stdout)
                    continue
                upsert(target, key, value)
            except Refused as exc:
                print(f"error: {exc} (key {key})", file=stderr)
                failed = True
                continue
            except (OSError, UnicodeDecodeError) as exc:
                # Keep going: later lines may carry secrets that exist only in this pipe.
                print(f"error: could not write {key} to {rel!r}: {type(exc).__name__}",
                      file=stderr)
                failed = True
                continue
            print(f"set {rel} {key}", file=stdout)
        elif SENSITIVE_RE.search(line):
            print("[redacted line]", file=stdout)
        else:
            print(line, file=stdout)
    return 1 if failed else 0


if __name__ == "__main__":
    args, base = sys.argv[1:], DEFAULT_BASE
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    if len(args) == 2 and args[0] == "--base":
        base = Path(args[1])
    elif args:
        sys.exit("usage: apply-sso-env.py [--base DIR] [--dry-run] < input")
    sys.exit(main(sys.stdin, sys.stdout, sys.stderr, base, dry_run))
