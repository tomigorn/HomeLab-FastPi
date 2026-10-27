#!/usr/bin/env python3
"""Pushes queued avatar picks to Jellyfin and Seerr on beefy, only while beefy is up (never wakes it).
Run by avatar-sync.service: on every queue change (avatar-sync.path) and every 5 min (avatar-sync.timer).
Usage: avatar-sync.py"""
import base64
import contextlib
import json
import os
import pathlib
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT = pathlib.Path(__file__).resolve().parent.parent
QUEUE = pathlib.Path(os.environ.get("AVATAR_QUEUE", PROJECT / "data" / "queue.json"))
STATE = pathlib.Path(os.environ.get("AVATAR_STATE", "/var/lib/avatar-sync/synced.json"))
KEY_FILE = pathlib.Path(os.environ.get("JELLYFIN_KEY_FILE", PROJECT / "secrets" / "jellyfin_api_key"))
WAKER_STATUS = os.environ.get("WAKER_STATUS", "http://192.168.1.2:9001/status")
BEEFY = os.environ.get("BEEFY_SSH", "beefy-direct")
JELLYFIN_PORT = 8096
IMAGE_DIRS = [PROJECT / "app" / "img", PROJECT / "app" / "img-local"]
SEERR_SCRIPT = PROJECT / "scripts" / "seerr-avatar.py"
SAFE_USER = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
SAFE_ID = re.compile(r"^[a-z0-9-]{1,64}$")


class SyncError(Exception):
    pass


def load(path):
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def pending(queue, synced):
    out = []
    for user, entry in queue.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("avatar"), str):
            continue
        if (synced.get(user) or {}).get("avatar") != entry["avatar"]:
            out.append((user, entry))
    return out


def run(queue_path, state_path, is_up, session, now):
    synced = load(state_path)
    todo = pending(load(queue_path), synced)
    if not todo:
        return 0
    if not is_up():
        print(f"{len(todo)} pick(s) queued, beefy asleep: kept for later")
        return 0
    rc = 0
    try:
        with session() as push:
            for user, entry in todo:
                try:
                    notes = push(user, entry["avatar"])
                except SyncError as e:
                    print(f"{user} -> {entry['avatar']}: failed, stays queued: {e}", file=sys.stderr)
                    rc = 1
                    continue
                synced[user] = dict(entry, synced=now())
                save(state_path, synced)
                print(f"{user} -> {entry['avatar']}: " + ", ".join(notes))
    except SyncError as e:
        print(f"beefy not reachable, picks stay queued: {e}", file=sys.stderr)
        return 1
    return rc


class Jellyfin:
    def __init__(self, base, key, timeout=20):
        self.base, self.key, self.timeout = base.rstrip("/"), key, timeout

    def _call(self, method, path, body=None, ctype=None):
        headers = {"Authorization": f'MediaBrowser Token="{self.key}"', "Accept": "application/json"}
        if ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except (OSError, urllib.error.URLError) as e:
            raise SyncError(f"jellyfin {method} {path.split('?')[0]}: {e}") from e
        return json.loads(raw) if raw else None

    def user_id(self, name):
        for u in self._call("GET", "/Users") or []:
            if u.get("Name", "").casefold() == name.casefold():
                return u["Id"]
        return None

    def set_image(self, user_id, png):
        self._call("POST", f"/UserImage?userId={user_id}", base64.b64encode(png), "image/png")


def find_image(avatar_id, dirs):
    for d in dirs:
        p = pathlib.Path(d) / f"{avatar_id}.png"
        if p.is_file():
            return p.read_bytes()
    raise SyncError(f"no image file for {avatar_id}")


def push(user, avatar_id, jellyfin, seerr, image_dirs, base):
    if not SAFE_USER.match(user) or not SAFE_ID.match(avatar_id):
        raise SyncError("unsafe username or avatar id")
    png = find_image(avatar_id, image_dirs)
    notes = []
    jf_id = jellyfin.user_id(user)
    if jf_id:
        jellyfin.set_image(jf_id, png)
        notes.append("jellyfin: image set")
    else:
        notes.append("jellyfin: no user")
    result = seerr(user, f"{base.rstrip('/')}/img/{avatar_id}.png")
    notes.append(f"seerr: {result.get('status', '?')}")
    return notes


def _ssh(cmd, stdin):
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")


def seerr_runner(host, script, runner=_ssh):
    """Runs seerr-avatar.py on beefy as Seerr's uid (the script travels on stdin, nothing is installed there)."""
    def call(user, url):
        remote = f"sudo -n setpriv --reuid=65109 --regid=65109 --clear-groups python3 - {shlex.quote(user)} {shlex.quote(url)}"
        rc, out, err = runner(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote], script)
        if rc:
            raise SyncError(f"seerr: rc={rc} {err.strip()[:200]}")
        try:
            return json.loads(out)
        except ValueError as e:
            raise SyncError(f"seerr: bad output {out.strip()[:200]!r}") from e
    return call


@contextlib.contextmanager
def tunnel(host, remote_port):
    """ssh -L to beefy's 127.0.0.1:<port>: rides the allowed ssh path, no firewall change."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(["ssh", "-N", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ExitOnForwardFailure=yes",
                             "-L", f"127.0.0.1:{port}:127.0.0.1:{remote_port}", host],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 20
        while True:
            if proc.poll() is not None:
                raise SyncError(f"ssh tunnel: {proc.stderr.read().decode(errors='replace').strip()[:200]}")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise SyncError("ssh tunnel: timeout")
                time.sleep(0.3)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def waker_up():
    try:
        with urllib.request.urlopen(WAKER_STATUS, timeout=5) as r:
            return json.load(r).get("up") is True
    except Exception:  # noqa: BLE001
        return False


def public_base():
    if os.environ.get("PUBLIC_BASE_URL"):
        return os.environ["PUBLIC_BASE_URL"]
    for line in (PROJECT / ".env.example").read_text().splitlines():
        if line.startswith("PUBLIC_BASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SyncError("PUBLIC_BASE_URL not set")


@contextlib.contextmanager
def beefy_session():
    key = KEY_FILE.read_text().strip()
    base = public_base()
    seerr = seerr_runner(BEEFY, SEERR_SCRIPT.read_bytes())
    with tunnel(BEEFY, JELLYFIN_PORT) as url:
        jf = Jellyfin(url, key)
        yield lambda user, aid: push(user, aid, jf, seerr, IMAGE_DIRS, base)


def main():
    now = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())  # noqa: E731
    return run(QUEUE, STATE, waker_up, beefy_session, now)


if __name__ == "__main__":
    sys.exit(main())
