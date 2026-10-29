#!/usr/bin/env python3
"""Pushes queued avatar picks to every app that can take a user picture: Jellyfin + Seerr (beefy, woken through the Waker for a pending pick, at most WAKE_LIMIT times per pick), Home Assistant (fastpi, once secrets/ha_token exists), Nextcloud (tower, prepared, inactive until secrets/nextcloud_users.json exists, never wakes tower).
Each app is a target with its own synced state: one app down never blocks the others, a failed push stays pending.
Exit 0 = every active target has every pick, 75 = something pending (avatar-sync.service then starts the 5-min avatar-sync.timer, and stops it again on 0), 1 = error.
Usage: avatar-sync.py [--reconcile | --status | --check ha]"""
import base64
import collections
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shlex
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT = pathlib.Path(__file__).resolve().parent.parent
SECRETS = PROJECT / "secrets"
QUEUE = pathlib.Path(os.environ.get("AVATAR_QUEUE", PROJECT / "data" / "queue.json"))
STATE = pathlib.Path(os.environ.get("AVATAR_STATE", "/var/lib/avatar-sync/synced.json"))
KEY_FILE = pathlib.Path(os.environ.get("JELLYFIN_KEY_FILE", SECRETS / "jellyfin_api_key"))
HA_TOKEN_FILE = pathlib.Path(os.environ.get("HA_TOKEN_FILE", SECRETS / "ha_token"))
NEXTCLOUD_USERS_FILE = pathlib.Path(os.environ.get("NEXTCLOUD_USERS_FILE", SECRETS / "nextcloud_users.json"))
BEEFY_STATUS = os.environ.get("WAKER_STATUS", "http://192.168.1.2:9001/status")
BEEFY_WAKE = os.environ.get("WAKER_WAKE", "http://192.168.1.2:9001/wake")
BEEFY_READY = os.environ.get("WAKER_READY", "http://192.168.1.2:9001/jf/status")
TOWER_STATUS = os.environ.get("TOWER_WAKER_STATUS", "http://192.168.1.2:9002/status")
BEEFY = os.environ.get("BEEFY_SSH", "beefy-direct")
TOWER = os.environ.get("TOWER_SSH", "tower-direct")
HA_HOST, HA_PORT = "127.0.0.1", 8123
JELLYFIN_PORT = 8096
IMAGE_DIRS = [PROJECT / "app" / "img", PROJECT / "app" / "img-local"]
SEERR_SCRIPT = PROJECT / "scripts" / "seerr-avatar.py"
SAFE_USER = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
SAFE_ID = re.compile(r"^[a-z0-9-]{1,64}$")
LEGACY_TARGETS = ("jellyfin", "seerr")
PENDING = 75
WAKE_LIMIT = 3
WAKE_TIMEOUT = 180


class SyncError(Exception):
    pass


# active: None or why the target is switched off (not pending); gate: None or why it is unreachable now (pending); wake: makes it reachable.
Target = collections.namedtuple("Target", "name gate session needs active wake", defaults=(None, None, None))


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


def load_state(path):
    state = {}
    for user, entry in load(path).items():
        if not isinstance(entry, dict):
            continue
        if not isinstance(entry.get("targets"), dict):
            entry = {"targets": {t: entry["avatar"] for t in LEGACY_TARGETS} if isinstance(entry.get("avatar"), str) else {},
                     "synced": entry.get("synced")}
        state[user] = entry
    return state


def picks(queue):
    good, bad = {}, []
    for user, entry in queue.items():
        aid = entry.get("avatar") if isinstance(entry, dict) else None
        if isinstance(aid, str) and SAFE_USER.match(user) and SAFE_ID.match(aid):
            good[user] = aid
        else:
            bad.append(user)
    return good, bad


def is_done(synced, wanted, user, name):
    return synced.get(user, {}).get("targets", {}).get(name) == wanted[user]


def inactive_targets(targets):
    off = {}
    for t in targets:
        reason = off.get(t.needs) and f"inactive: needs {t.needs}" or (t.active() if t.active else None)
        if reason:
            off[t.name] = reason
    return off


def pending(wanted, synced, targets, off):
    return {(u, t.name) for t in targets if t.name not in off for u in wanted if not is_done(synced, wanted, u, t.name)}


def status(queue_path, state_path, targets):
    wanted, _ = picks(load(queue_path))
    left = pending(wanted, load_state(state_path), targets, inactive_targets(targets))
    return f"pending {len({u for u, _ in left})}" if left else "in sync"


def run(queue_path, state_path, targets, now, reconcile=False):
    synced = load_state(state_path)
    wanted, bad = picks(load(queue_path))
    wakes_path = pathlib.Path(state_path).with_name("wakes.json")
    wakes = load(wakes_path)
    rc = 0
    if bad:
        print(f"{len(bad)} malformed or unsafe queue entr(y/ies) ignored", file=sys.stderr)
        rc = 1
    off = inactive_targets(targets)
    woken = {}
    not_done = set()
    for t in targets:
        def done(user, name):
            return (user, name) not in not_done and is_done(synced, wanted, user, name)
        waiting = [u for u in wanted if not done(u, t.name)]
        if t.name in off:
            if waiting:
                print(f"{t.name}: {len(waiting)} not pushed, {off[t.name]}")
            continue
        todo = list(wanted) if reconcile else waiting
        if t.needs:
            todo = [u for u in todo if done(u, t.needs)]
        not_done.update((u, t.name) for u in waiting + todo)
        if not todo:
            continue
        reason = t.gate()
        if reason and t.wake:
            due = [u for u in todo if u in waiting and not (wakes.get(u, {}).get("avatar") == wanted[u] and wakes[u].get("count", 0) >= WAKE_LIMIT)]
            if due and t.wake not in woken:
                for u in due:
                    count = wakes.get(u, {}).get("count", 0) if wakes.get(u, {}).get("avatar") == wanted[u] else 0
                    wakes[u] = {"avatar": wanted[u], "count": count + 1}
                save(wakes_path, wakes)
                print(f"{t.name}: {len(due)} pending, {reason}, waking it")
                woken[t.wake] = t.wake()
            if t.wake in woken:
                reason = woken[t.wake] or t.gate()
        if reason:
            print(f"{t.name}: {len(todo)} pending, {reason}")
            continue
        try:
            with t.session() as push:
                for user in todo:
                    aid = wanted[user]
                    try:
                        note = push(user, aid)
                    except SyncError as e:
                        print(f"{user} -> {aid}: {t.name} failed, stays pending: {e}", file=sys.stderr)
                        continue
                    entry = synced.setdefault(user, {"targets": {}})
                    entry["targets"][t.name] = aid
                    entry["synced"] = now()
                    save(state_path, synced)
                    not_done.discard((user, t.name))
                    print(f"{user} -> {aid}: {t.name}: {note}")
        except SyncError as e:
            print(f"{t.name} not reachable, picks stay pending: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"{t.name} crashed, picks stay pending: {type(e).__name__}", file=sys.stderr)
    left = pending(wanted, synced, targets, off)
    kept = {u: w for u, w in wakes.items() if isinstance(w, dict) and w.get("avatar") == wanted.get(u) and any(p[0] == u for p in left)}
    if kept != wakes and (kept or wakes_path.exists()):
        save(wakes_path, kept)
    if left:
        print(f"pending: {len({u for u, _ in left})} pick(s), retry timer stays on")
        return PENDING
    return rc


def find_image(avatar_id, dirs):
    for d in dirs:
        p = pathlib.Path(d) / f"{avatar_id}.png"
        if p.is_file():
            return p.read_bytes()
    raise SyncError(f"no image file for {avatar_id}")


def picker_url(base, avatar_id):
    return f"{base.rstrip('/')}/img/{avatar_id}.png"


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


def jellyfin_push(jellyfin, image_dirs):
    def push(user, avatar_id):
        png = find_image(avatar_id, image_dirs)
        jf_id = jellyfin.user_id(user)
        if not jf_id:
            return "no user"
        jellyfin.set_image(jf_id, png)
        return "image set"
    return push


def seerr_push(seerr, base):
    def push(user, avatar_id):
        return seerr(user, picker_url(base, avatar_id)).get("status", "?")
    return push


def _ssh(cmd, stdin):
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")


def _ssh_cmd(host, remote):
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote]


def seerr_runner(host, script, runner=_ssh):
    """Runs seerr-avatar.py on beefy as Seerr's uid (the script travels on stdin, nothing is installed there)."""
    def call(user, url):
        remote = f"sudo -n setpriv --reuid=65109 --regid=65109 --clear-groups python3 - {shlex.quote(user)} {shlex.quote(url)}"
        rc, out, err = runner(_ssh_cmd(host, remote), script)
        if rc:
            raise SyncError(f"seerr: rc={rc} {err.strip()[:200]}")
        try:
            return json.loads(out)
        except ValueError as e:
            raise SyncError(f"seerr: bad output {out.strip()[:200]!r}") from e
    return call


# Home Assistant has no REST call for a person: its websocket API (person/list, person/update) needs a long-lived admin token.
def ws_frame(opcode, payload, mask):
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


class WebSocket:
    def __init__(self, host, port, path, timeout=15):
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as e:
            raise SyncError(f"ha: {e}") from e
        try:
            self._handshake(host, port, path)
        except BaseException:
            self.sock.close()
            raise

    def _handshake(self, host, port, path):
        key = base64.b64encode(os.urandom(16)).decode()
        self.send_raw((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self._exact(1)
            if len(head) > 8192:
                raise SyncError("ha: oversized handshake")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if not head.startswith(b"HTTP/1.1 101") or accept not in head:
            raise SyncError(f"ha: websocket refused: {head.split(b'\r\n')[0].decode(errors='replace')[:80]}")

    def _exact(self, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = self.sock.recv(n - len(buf))
            except OSError as e:
                raise SyncError(f"ha: {e}") from e
            if not chunk:
                raise SyncError("ha: connection closed")
            buf += chunk
        return buf

    def send_raw(self, data):
        try:
            self.sock.sendall(data)
        except OSError as e:
            raise SyncError(f"ha: {e}") from e

    def send(self, opcode, payload):
        self.send_raw(ws_frame(opcode, payload, os.urandom(4)))

    def send_json(self, msg):
        self.send(1, json.dumps(msg).encode())

    def recv_json(self):
        data = b""
        while True:
            b0, b1 = self._exact(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._exact(8))[0]
            mask = self._exact(4) if b1 & 0x80 else None
            payload = self._exact(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            op = b0 & 0x0F
            if op == 9:
                self.send(10, payload)
            elif op == 8:
                raise SyncError("ha: websocket closed")
            elif op in (0, 1, 2):
                data += payload
                if b0 & 0x80:
                    return json.loads(data)

    def close(self):
        with contextlib.suppress(OSError, SyncError):
            self.send(8, b"")
        self.sock.close()


class HomeAssistant:
    def __init__(self, ws, token):
        self.ws, self.n = ws, 0
        if ws.recv_json().get("type") != "auth_required":
            raise SyncError("ha: unexpected greeting")
        ws.send_json({"type": "auth", "access_token": token})
        if ws.recv_json().get("type") != "auth_ok":
            raise SyncError("ha: token refused")

    def _call(self, **msg):
        self.n += 1
        self.ws.send_json({"id": self.n, **msg})
        while True:
            r = self.ws.recv_json()
            if r.get("id") == self.n and r.get("type") == "result":
                break
        if not r.get("success"):
            raise SyncError(f"ha {msg['type']}: {(r.get('error') or {}).get('code', '?')}")
        return r.get("result")

    def persons(self):
        return (self._call(type="person/list") or {}).get("storage", [])

    def set_picture(self, person_id, url):
        self._call(type="person/update", person_id=person_id, picture=url)


@contextlib.contextmanager
def ha_client(host, port, token):
    ws = WebSocket(host, port, "/api/websocket")
    try:
        yield HomeAssistant(ws, token)
    finally:
        ws.close()


def ha_person(persons, user):
    slug = re.sub(r"[^a-z0-9]+", "_", user.casefold()).strip("_")
    for p in persons:
        if p.get("id") == slug or (p.get("name") or "").casefold() == user.casefold():
            return p
    return None


def ha_push(ha, base, image_dirs):
    persons = []
    def push(user, avatar_id):
        find_image(avatar_id, image_dirs)
        if not persons:
            persons.extend(ha.persons())
        p = ha_person(persons, user)
        if not p:
            return "no person"
        url = picker_url(base, avatar_id)
        if p.get("picture") == url:
            return "unchanged"
        ha.set_picture(p["id"], url)
        p["picture"] = url
        return "picture set"
    return push


def ha_check(persons, wanted, base):
    found, wrong = 0, []
    for user, aid in sorted(wanted.items()):
        p = ha_person(persons, user)
        if not p:
            continue
        found += 1
        if p.get("picture") != picker_url(base, aid):
            wrong.append(user)
    return f"mismatch {' '.join(wrong)}" if wrong else f"ok {found}/{found}"


NEXTCLOUD_PHP = ('require "/var/www/html/lib/base.php"; $u = $argv[1]; '
                 'if (!\\OC::$server->getUserManager()->userExists($u)) { echo "no-user"; exit(0); } '
                 '\\OC::$server->get(\\OCP\\IAvatarManager::class)->getAvatar($u)->set(stream_get_contents(STDIN)); echo "set";')


def nextcloud_runner(host, runner=_ssh):
    """Sets the avatar inside tower's Nextcloud container (IAvatarManager, same as an upload in the UI); the PNG travels on stdin."""
    def call(uid, png):
        remote = f"docker exec -i -u www-data nextcloud php -r {shlex.quote(NEXTCLOUD_PHP)} {shlex.quote(uid)}"
        rc, out, err = runner(_ssh_cmd(host, remote), png)
        if rc:
            raise SyncError(f"nextcloud: rc={rc} {err.strip()[:200]}")
        result = out.strip().splitlines()[-1:] or [""]
        if result[0] not in ("set", "no-user"):
            raise SyncError(f"nextcloud: bad output {out.strip()[:200]!r}")
        return result[0]
    return call


def nextcloud_push(runner, users, image_dirs):
    def push(user, avatar_id):
        png = find_image(avatar_id, image_dirs)
        uid = users.get(user)
        if not uid:
            return "no user"
        if not isinstance(uid, str) or not SAFE_USER.match(uid):
            raise SyncError("unsafe nextcloud uid")
        return runner(uid, png)
    return push


def read_map(path):
    return {k: v for k, v in load(path).items() if isinstance(v, str)}


def file_gate(path, missing):
    def gate():
        try:
            return None if pathlib.Path(path).read_text().strip() else f"inactive: {missing}"
        except OSError:
            return f"inactive: {missing}"
    return gate


def http_post_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST", headers={"X-Wake": "1"}), timeout=10) as r:
        return json.load(r)


def waker_wake(url, ready, timeout=WAKE_TIMEOUT, interval=5, post=http_post_json, sleep=time.sleep, clock=time.monotonic):
    """Asks the fastpi Waker (POST /wake, it resends the WoL until beefy answers), then waits until ready() or the timeout."""
    def wake():
        try:
            sent = post(url)
        except Exception as e:  # noqa: BLE001
            return f"wake failed: {type(e).__name__}"
        if not isinstance(sent, dict) or sent.get("sent") is not True:
            return "wake failed: packet not sent"
        deadline = clock() + timeout
        while not ready():
            if clock() >= deadline:
                return f"beefy not ready after {timeout} s"
            sleep(interval)
        return None
    return wake


def waker_gate(url, host):
    def gate():
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if json.load(r).get("up") is True:
                    return None
        except Exception:  # noqa: BLE001
            pass
        return f"{host} asleep"
    return gate


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


def public_base():
    if os.environ.get("PUBLIC_BASE_URL"):
        return os.environ["PUBLIC_BASE_URL"]
    for line in (PROJECT / ".env.example").read_text().splitlines():
        if line.startswith("PUBLIC_BASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SyncError("PUBLIC_BASE_URL not set")


@contextlib.contextmanager
def jellyfin_session():
    key = KEY_FILE.read_text().strip()
    with tunnel(BEEFY, JELLYFIN_PORT) as url:
        yield jellyfin_push(Jellyfin(url, key), IMAGE_DIRS)


@contextlib.contextmanager
def seerr_session():
    yield seerr_push(seerr_runner(BEEFY, SEERR_SCRIPT.read_bytes()), public_base())


@contextlib.contextmanager
def ha_session():
    with ha_client(HA_HOST, HA_PORT, HA_TOKEN_FILE.read_text().strip()) as ha:
        yield ha_push(ha, public_base(), IMAGE_DIRS)


@contextlib.contextmanager
def nextcloud_session():
    yield nextcloud_push(nextcloud_runner(TOWER), read_map(NEXTCLOUD_USERS_FILE), IMAGE_DIRS)


def targets():
    beefy = waker_gate(BEEFY_STATUS, "beefy")
    jellyfin_ready = waker_gate(BEEFY_READY, "jellyfin")
    wake_beefy = waker_wake(BEEFY_WAKE, lambda: jellyfin_ready() is None)
    return [
        Target("jellyfin", beefy, jellyfin_session, wake=wake_beefy),
        Target("seerr", beefy, seerr_session, "jellyfin", wake=wake_beefy),
        Target("ha", lambda: None, ha_session, active=file_gate(HA_TOKEN_FILE, "no secrets/ha_token")),
        Target("nextcloud", waker_gate(TOWER_STATUS, "tower"), nextcloud_session,
               active=file_gate(NEXTCLOUD_USERS_FILE, "no secrets/nextcloud_users.json")),
    ]


def check_ha():
    if file_gate(HA_TOKEN_FILE, "no token")():
        return "inactive no token"
    wanted, _ = picks(load(QUEUE))
    try:
        with ha_client(HA_HOST, HA_PORT, HA_TOKEN_FILE.read_text().strip()) as ha:
            return ha_check(ha.persons(), wanted, public_base())
    except SyncError as e:
        return f"error {e}"


def main(argv):
    if argv == ["--check", "ha"]:
        print(check_ha())
        return 0
    if argv == ["--status"]:
        print(status(QUEUE, STATE, targets()))
        return 0
    if argv not in ([], ["--reconcile"]):
        print(__doc__, file=sys.stderr)
        return 2
    now = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())  # noqa: E731
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE.with_name("sync.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for _ in range(3):
            seen = queue_stamp()
            rc = run(QUEUE, STATE, targets(), now, reconcile=bool(argv))
            if queue_stamp() == seen:
                return rc
            print("queue changed during the run, running again")
        return rc


def queue_stamp():
    try:
        st = QUEUE.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
