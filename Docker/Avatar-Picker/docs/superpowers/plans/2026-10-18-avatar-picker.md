# Avatar Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Netflix-style picker at `https://avatars.holy-grail.ch` where each Authentik user picks one unique avatar from a fixed gallery; Authentik, Jellyfin and Nextcloud show it.

**Architecture:** One stdlib-Python container on fastpi serves public gallery images (`/img/`) and an Authentik-forward-auth-protected picker page + JSON API. Choices are written to the user's `attributes.avatar` (an https URL) through Authentik's API with a least-privilege service-account token; Authentik's Avatars setting and default `profile` scope then emit it as the OIDC `picture` claim, which Jellyfin's OIDC plugin and Nextcloud user_oidc consume.

**Tech Stack:** Python 3.13 stdlib (`http.server`, `urllib`, `json`, `threading`, `unittest`), vanilla HTML/JS, Docker Compose, Traefik v3 file provider, Authentik 2026.8 (`ak shell`), Pillow only for the one-off gallery build.

Spec: `Docker/Avatar-Picker/docs/superpowers/specs/2026-10-18-avatar-picker-design.md`

Repo root: `/home/pi/Projects` (git, remote HomeLab-FastPi, PUBLIC repo → never commit secrets).
Commit format: `Avatar-Picker: <description>` (or `Traefik: …` etc. for other projects), **no Co-Authored-By / AI trailer** (user rule overrides any default).

---

## File structure

```
Docker/Avatar-Picker/
  docker-compose.yaml        # sample sectioned layout
  .env / .env.example        # COMPOSE_PROJECT_NAME=avatar-picker, PUBLIC_BASE_URL, AUTHENTIK_URL
  .gitignore                 # sample + secrets/
  Dockerfile                 # python:3.13-alpine, non-root user 1000
  README.md
  LICENSES.md                # Fluent Emoji MIT notice
  secrets/authentik_token    # gitignored, created in Task 6
  scripts/build-gallery.py   # one-off: download Fluent Emoji 3D PNGs, compose 512x512 squares
  scripts/provision-authentik.py  # run via `ak shell` stdin: service account, role, token, proxy app
  app/
    VERSION
    gallery.json             # [{id, name, file, color}]
    img/<id>.png             # 512x512 square PNGs (committed)
    core.py                  # pure logic: gallery, URLs, uniqueness, attribute merge
    authentik_api.py         # tiny Authentik REST client (urllib)
    server.py                # HTTP handler + main()
    static/index.html        # picker UI
  tests/
    test_core.py
    test_server.py
```

Python files are imported as top-level modules with `app/` on `sys.path` (tests add it).

---

### Task 1: Scaffold the project (sample structure)

**Files:**
- Create: `Docker/Avatar-Picker/docker-compose.yaml`, `.env.example`, `.env`, `.gitignore`, `Dockerfile`, `app/VERSION`

- [ ] **Step 1: Create `.gitignore`** — copy `/home/pi/Projects/Docker/.gitignore` verbatim (it already ignores `secrets/`, `.env`, keys).

```bash
cp /home/pi/Projects/Docker/.gitignore /home/pi/Projects/Docker/Avatar-Picker/.gitignore
```

- [ ] **Step 2: Create `.env.example` and `.env`** (identical; no secrets in either — the token is a file):

```
COMPOSE_PROJECT_NAME=avatar-picker

# Public base URL of this service; avatar URLs stored in Authentik start with it.
PUBLIC_BASE_URL=https://avatars.holy-grail.ch

# Authentik API, reached over the docker network (traefik_proxy).
AUTHENTIK_URL=http://authentik-server:9000

# Image tag of the locally built picker image.
AVATAR_PICKER_TAG=local
```

- [ ] **Step 3: Create `Dockerfile`**

```dockerfile
FROM python:3.13-alpine
RUN adduser -D -u 1000 picker
WORKDIR /app
COPY app/ /app/
USER 1000
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]
```

- [ ] **Step 4: Create `docker-compose.yaml`** (sample banner layout)

```yaml
# =========================================================
# Services ================================================
# =========================================================
services:
# #########################################################
# AVATAR-PICKER ###########################################
# #########################################################
  avatar-picker:
    build: .
    image: avatar-picker:${AVATAR_PICKER_TAG:-local}
    container_name: avatar-picker
    restart: unless-stopped
    env_file: .env
    environment:
      AUTHENTIK_TOKEN_FILE: /run/secrets/authentik_token
    volumes:
      - ./secrets/authentik_token:/run/secrets/authentik_token:ro
    networks:
      - traefik_proxy
    user: "1000:1000"
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    mem_limit: 64m
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3

# =========================================================
# Networks ================================================
# =========================================================
networks:
  traefik_proxy:
    external: true

# =========================================================
# Volumes =================================================
# =========================================================
```

- [ ] **Step 5: `app/VERSION`** containing `1.0.0`.

- [ ] **Step 6: Commit**

```bash
cd /home/pi/Projects && git add Docker/Avatar-Picker/{docker-compose.yaml,.env.example,.gitignore,Dockerfile,app/VERSION}
git status --short Docker/Avatar-Picker   # .env must NOT be listed
git commit -m "Avatar-Picker: scaffold project (compose, Dockerfile, env template)"
```

---

### Task 2: Build the gallery

**Files:**
- Create: `Docker/Avatar-Picker/scripts/build-gallery.py`, `app/gallery.json`, `app/img/*.png`, `LICENSES.md`

Source: https://github.com/microsoft/fluentui-emoji (MIT). 3D PNGs live at
`assets/<Folder Name>/3D/<folder_name_lowercase_underscored>_3d.png`, e.g.
`assets/Fox/3D/fox_3d.png`. **First verify the licence file at
https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/LICENSE says MIT;
if it does not, stop and report.**

- [ ] **Step 1: Write `scripts/build-gallery.py`**

```python
#!/usr/bin/env python3
"""One-off: build the avatar gallery from Microsoft Fluent Emoji (MIT).

Downloads the 3D PNG of each animal, centres it on a 512x512 soft-coloured
square and writes app/img/<id>.png plus app/gallery.json. Re-run only to change
the gallery; the output is committed. Needs Pillow (dev only).
"""
import io, json, pathlib, urllib.parse, urllib.request
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/"
SIZE, EMOJI = 512, 360

# (id, display name, upstream folder, background colour)
ANIMALS = [
    ("fox", "Fox", "Fox", "#FFD8B5"), ("owl", "Owl", "Owl", "#E3D5C3"),
    ("panda", "Panda", "Panda", "#D9F2D0"), ("tiger", "Tiger", "Tiger face", "#FFE3A3"),
    ("lion", "Lion", "Lion", "#FBE0B0"), ("koala", "Koala", "Koala", "#D6E4F0"),
    ("rabbit", "Rabbit", "Rabbit face", "#F8D7E3"), ("cat", "Cat", "Cat face", "#FFE9C7"),
    ("dog", "Dog", "Dog face", "#E8DCCB"), ("penguin", "Penguin", "Penguin", "#CFE8F7"),
    ("frog", "Frog", "Frog", "#D3F0C2"), ("monkey", "Monkey", "Monkey face", "#EAD7C2"),
    ("unicorn", "Unicorn", "Unicorn", "#EBD9FA"), ("dragon", "Dragon", "Dragon face", "#CDEFD9"),
    ("octopus", "Octopus", "Octopus", "#FAD3D3"), ("turtle", "Turtle", "Turtle", "#D7F0E4"),
    ("hedgehog", "Hedgehog", "Hedgehog", "#EFE2D2"), ("bear", "Bear", "Bear", "#E6D3C3"),
    ("wolf", "Wolf", "Wolf", "#DDE3EA"), ("raccoon", "Raccoon", "Raccoon", "#E1E1E8"),
    ("sloth", "Sloth", "Sloth", "#E9E2CF"), ("otter", "Otter", "Otter", "#D8E8EC"),
    ("whale", "Whale", "Spouting whale", "#CFE3FA"), ("butterfly", "Butterfly", "Butterfly", "#F3DDF7"),
]

def fetch(folder):
    name = folder.lower().replace(" ", "_") + "_3d.png"
    url = BASE + urllib.parse.quote(f"{folder}/3D/{name}")
    with urllib.request.urlopen(url, timeout=30) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGBA")

def main():
    out = ROOT / "app" / "img"; out.mkdir(parents=True, exist_ok=True)
    gallery = []
    for aid, label, folder, color in ANIMALS:
        emoji = fetch(folder).resize((EMOJI, EMOJI), Image.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), color)
        off = (SIZE - EMOJI) // 2
        canvas.alpha_composite(emoji, (off, off))
        canvas.convert("RGB").save(out / f"{aid}.png", optimize=True)
        gallery.append({"id": aid, "name": label, "file": f"{aid}.png", "color": color})
        print("ok", aid)
    (ROOT / "app" / "gallery.json").write_text(json.dumps(gallery, indent=2) + "\n")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it** (fastpi has Pillow 9.4)

Run: `cd /home/pi/Projects/Docker/Avatar-Picker && python3 scripts/build-gallery.py`
Expected: 24 lines `ok <id>`. If a folder 404s, look up the exact folder name in the repo
(`https://github.com/microsoft/fluentui-emoji/tree/main/assets`) and fix that entry only.

- [ ] **Step 3: Verify output**

```bash
python3 - <<'EOF'
import json, pathlib
from PIL import Image
g = json.load(open("app/gallery.json"))
assert len(g) == 24 and len({x["id"] for x in g}) == 24
for x in g:
    p = pathlib.Path("app/img") / x["file"]; im = Image.open(p)
    assert im.size == (512, 512) and im.format == "PNG" and p.stat().st_size < 5_000_000, x
print("gallery ok", sum((pathlib.Path("app/img")/x["file"]).stat().st_size for x in g) // 1024, "KiB")
EOF
```
Expected: `gallery ok <n> KiB`.

- [ ] **Step 4: Write `LICENSES.md`**

```markdown
# Third-party assets

The avatar images in `app/img/` are derived from **Fluent Emoji** by Microsoft
(https://github.com/microsoft/fluentui-emoji), used under the MIT License:

Copyright (c) Microsoft Corporation.
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```
(Replace the text with the exact upstream LICENSE text if it differs.)

- [ ] **Step 5: Commit**

```bash
cd /home/pi/Projects && git add Docker/Avatar-Picker/{scripts/build-gallery.py,app/gallery.json,app/img,LICENSES.md}
git commit -m "Avatar-Picker: add 24-avatar gallery built from Fluent Emoji (MIT)"
```

---

### Task 3: Core logic (TDD)

**Files:**
- Create: `Docker/Avatar-Picker/app/core.py`
- Test: `Docker/Avatar-Picker/tests/test_core.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_core.py`

```python
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import core

GALLERY = [{"id": "fox", "name": "Fox", "file": "fox.png", "color": "#fff"},
           {"id": "owl", "name": "Owl", "file": "owl.png", "color": "#fff"}]
BASE = "https://avatars.example"

def user(pk, username, avatar=None, **attrs):
    if avatar: attrs["avatar"] = avatar
    return {"pk": pk, "username": username, "attributes": attrs}

class Urls(unittest.TestCase):
    def test_avatar_url(self):
        self.assertEqual(core.avatar_url(BASE, "fox"), "https://avatars.example/img/fox.png")

    def test_id_from_url(self):
        self.assertEqual(core.id_from_url(BASE, BASE + "/img/owl.png"), "owl")
        self.assertIsNone(core.id_from_url(BASE, "https://gravatar.com/x"))
        self.assertIsNone(core.id_from_url(BASE, None))

class State(unittest.TestCase):
    def test_marks_taken_and_mine(self):
        users = [user(1, "me", BASE + "/img/fox.png"), user(2, "other", BASE + "/img/owl.png")]
        st = core.gallery_state(GALLERY, users, BASE, "me")
        self.assertEqual({x["id"]: x["status"] for x in st}, {"fox": "mine", "owl": "taken"})
        self.assertTrue(all("username" not in x for x in st))  # never leak who

    def test_free_when_nobody_holds(self):
        st = core.gallery_state(GALLERY, [user(1, "me")], BASE, "me")
        self.assertEqual({x["status"] for x in st}, {"free"})

class Pick(unittest.TestCase):
    def test_unknown_id(self):
        with self.assertRaises(core.UnknownAvatar):
            core.check_pick(GALLERY, [], BASE, "me", "nope")

    def test_taken_by_other(self):
        users = [user(1, "me"), user(2, "other", BASE + "/img/fox.png")]
        with self.assertRaises(core.AvatarTaken):
            core.check_pick(GALLERY, users, BASE, "me", "fox")

    def test_repick_own_is_fine(self):
        users = [user(1, "me", BASE + "/img/fox.png")]
        self.assertEqual(core.check_pick(GALLERY, users, BASE, "me", "fox"), 1)

    def test_returns_caller_pk(self):
        users = [user(7, "me"), user(2, "other", BASE + "/img/fox.png")]
        self.assertEqual(core.check_pick(GALLERY, users, BASE, "me", "owl"), 7)

    def test_unknown_caller(self):
        with self.assertRaises(core.UnknownUser):
            core.check_pick(GALLERY, [user(2, "other")], BASE, "me", "owl")

class Merge(unittest.TestCase):
    def test_keeps_other_attributes(self):
        merged = core.merged_attributes({"theme": "dark", "avatar": "old"}, BASE, "owl")
        self.assertEqual(merged, {"theme": "dark", "avatar": BASE + "/img/owl.png"})

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, expect failure**

Run: `cd /home/pi/Projects/Docker/Avatar-Picker && python3 -m unittest tests.test_core -v`
Expected: `ModuleNotFoundError: No module named 'core'`

- [ ] **Step 3: Implement `app/core.py`**

```python
"""Pure avatar-picker logic: no I/O, so it is fully unit-testable."""


class UnknownAvatar(ValueError):
    pass


class AvatarTaken(ValueError):
    pass


class UnknownUser(LookupError):
    pass


def avatar_url(base, avatar_id):
    return f"{base.rstrip('/')}/img/{avatar_id}.png"


def id_from_url(base, url):
    prefix = f"{base.rstrip('/')}/img/"
    if not url or not url.startswith(prefix) or not url.endswith(".png"):
        return None
    return url[len(prefix):-len(".png")]


def _holders(users, base):
    """avatar id -> username of the user holding it."""
    held = {}
    for u in users:
        aid = id_from_url(base, (u.get("attributes") or {}).get("avatar"))
        if aid:
            held[aid] = u["username"]
    return held


def gallery_state(gallery, users, base, caller):
    """Gallery entries with status free / taken / mine. Never exposes who."""
    held = _holders(users, base)
    out = []
    for g in gallery:
        holder = held.get(g["id"])
        status = "free" if holder is None else ("mine" if holder == caller else "taken")
        out.append({"id": g["id"], "name": g["name"], "url": avatar_url(base, g["id"]),
                    "color": g["color"], "status": status})
    return out


def check_pick(gallery, users, base, caller, avatar_id):
    """Validate a pick; return the caller's user pk. Raises on any conflict."""
    if avatar_id not in {g["id"] for g in gallery}:
        raise UnknownAvatar(avatar_id)
    holder = _holders(users, base).get(avatar_id)
    if holder is not None and holder != caller:
        raise AvatarTaken(avatar_id)
    for u in users:
        if u["username"] == caller:
            return u["pk"]
    raise UnknownUser(caller)


def merged_attributes(current, base, avatar_id):
    merged = dict(current or {})
    merged["avatar"] = avatar_url(base, avatar_id)
    return merged
```

- [ ] **Step 4: Run, expect pass**

Run: `python3 -m unittest tests.test_core -v` → `OK` (10 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/pi/Projects && git add Docker/Avatar-Picker/app/core.py Docker/Avatar-Picker/tests/test_core.py
git commit -m "Avatar-Picker: add core uniqueness and attribute logic with tests"
```

---

### Task 4: Authentik API client

**Files:**
- Create: `Docker/Avatar-Picker/app/authentik_api.py`

Authentik API facts: `GET /api/v3/core/users/?page=N&page_size=100` returns
`{"pagination": {"next": <int|0>}, "results": [{pk, username, attributes, is_active, type}, ...]}`;
`PATCH /api/v3/core/users/{pk}/` with `{"attributes": {...}}` **replaces** the whole
attributes dict (so send the merged dict). Auth: `Authorization: Bearer <token>`.

- [ ] **Step 1: Implement `app/authentik_api.py`**

```python
"""Minimal Authentik REST client (stdlib only)."""
import json
import urllib.request


class AuthentikError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url, token, timeout=10, opener=urllib.request.urlopen):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._open = opener  # injectable for tests

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        try:
            with self._open(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except Exception as e:  # network, HTTP error, bad JSON
            raise AuthentikError(f"{method} {path}: {e}") from e

    def list_users(self):
        """All human users (service accounts excluded)."""
        users, page = [], 1
        while page:
            data = self._call("GET", f"/api/v3/core/users/?page={page}&page_size=100")
            users += [u for u in data.get("results", [])
                      if u.get("type") in ("internal", "external")]
            page = (data.get("pagination") or {}).get("next") or 0
        return users

    def set_attributes(self, pk, attributes):
        self._call("PATCH", f"/api/v3/core/users/{int(pk)}/", {"attributes": attributes})
```

- [ ] **Step 2: Sanity-import**

Run: `cd /home/pi/Projects/Docker/Avatar-Picker && python3 -c "import sys; sys.path.insert(0,'app'); import authentik_api; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
cd /home/pi/Projects && git add Docker/Avatar-Picker/app/authentik_api.py
git commit -m "Avatar-Picker: add minimal Authentik API client"
```

---

### Task 5: HTTP server + picker page (TDD)

**Files:**
- Create: `Docker/Avatar-Picker/app/server.py`, `app/static/index.html`
- Test: `Docker/Avatar-Picker/tests/test_server.py`

Behaviour:
- `GET /healthz` → 200 `ok`
- `GET /img/<id>.png` → the PNG (only ids in gallery.json), `Cache-Control: public, max-age=86400`
- `GET /` → `static/index.html` (requires `X-authentik-username`, else 401)
- `GET /api/state` → `{"user": <username>, "avatars": gallery_state(...)}`; 401 without header; 503 if Authentik fails
- `POST /api/pick` body `{"id": "<id>"}` → under a global lock: list users, `check_pick`, `set_attributes(merged)`; 200 `{"ok": true, "url": ...}`; 409 taken; 400 unknown id/bad body; 401 no header; 503 Authentik error.

- [ ] **Step 1: Write failing tests** — `tests/test_server.py`

```python
import io, json, os, sys, threading, unittest, urllib.request
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import server
from authentik_api import AuthentikError

BASE = "https://avatars.example"

class FakeClient:
    def __init__(self, users, fail=False):
        self.users, self.fail, self.writes = users, fail, []
    def list_users(self):
        if self.fail: raise AuthentikError("down")
        return [dict(u, attributes=dict(u["attributes"])) for u in self.users]
    def set_attributes(self, pk, attrs):
        self.writes.append((pk, attrs))
        for u in self.users:
            if u["pk"] == pk: u["attributes"] = attrs

class ServerTest(unittest.TestCase):
    def start(self, client):
        server.configure(client=client, base=BASE)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
    def tearDown(self):
        self.httpd.shutdown()
    def req(self, path, user=None, body=None):
        h = {"X-authentik-username": user} if user else {}
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.url + path, data=data, headers=h, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def users(self):
        return [{"pk": 1, "username": "me", "attributes": {"theme": "x"}},
                {"pk": 2, "username": "other", "attributes": {"avatar": BASE + "/img/fox.png"}}]

    def test_health_and_image_public(self):
        self.start(FakeClient(self.users()))
        self.assertEqual(self.req("/healthz")[0], 200)
        code, body = self.req("/img/owl.png")
        self.assertEqual(code, 200); self.assertTrue(body.startswith(b"\x89PNG"))
        self.assertEqual(self.req("/img/../server.py")[0], 404)
        self.assertEqual(self.req("/img/nope.png")[0], 404)

    def test_page_and_state_need_identity(self):
        self.start(FakeClient(self.users()))
        self.assertEqual(self.req("/")[0], 401)
        self.assertEqual(self.req("/api/state")[0], 401)
        self.assertEqual(self.req("/", user="me")[0], 200)

    def test_state(self):
        self.start(FakeClient(self.users()))
        code, body = self.req("/api/state", user="me")
        st = {a["id"]: a["status"] for a in json.loads(body)["avatars"]}
        self.assertEqual(code, 200); self.assertEqual(st["fox"], "taken"); self.assertEqual(st["owl"], "free")

    def test_pick_free_writes_merged(self):
        c = FakeClient(self.users()); self.start(c)
        code, _ = self.req("/api/pick", user="me", body={"id": "owl"})
        self.assertEqual(code, 200)
        self.assertEqual(c.writes, [(1, {"theme": "x", "avatar": BASE + "/img/owl.png"})])

    def test_pick_taken_409_no_write(self):
        c = FakeClient(self.users()); self.start(c)
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "fox"})[0], 409)
        self.assertEqual(c.writes, [])

    def test_pick_bad_input(self):
        c = FakeClient(self.users()); self.start(c)
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "nope"})[0], 400)
        self.assertEqual(self.req("/api/pick", user="me", body={"x": 1})[0], 400)
        self.assertEqual(self.req("/api/pick", body={"id": "owl"})[0], 401)

    def test_authentik_down_503(self):
        self.start(FakeClient(self.users(), fail=True))
        self.assertEqual(self.req("/api/state", user="me")[0], 503)
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "owl"})[0], 503)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_server -v` → `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: Implement `app/server.py`**

```python
"""Avatar picker: public gallery images + forward-auth protected picker/API."""
import json, os, pathlib, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import core
from authentik_api import AuthentikError, Client

APP = pathlib.Path(__file__).resolve().parent
GALLERY = json.loads((APP / "gallery.json").read_text())
IDS = {g["id"] for g in GALLERY}
INDEX = (APP / "static" / "index.html").read_bytes()
VERSION = (APP / "VERSION").read_text().strip() if (APP / "VERSION").exists() else "dev"

_cfg = {"client": None, "base": None}
_pick_lock = threading.Lock()  # serialises check+write => uniqueness holds


def configure(client, base):
    _cfg["client"], _cfg["base"] = client, base.rstrip("/")


class Handler(BaseHTTPRequestHandler):
    timeout = 10
    server_version = "avatar-picker"
    sys_version = ""

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", cache=None):
        if isinstance(body, (dict, list)):
            body, ctype = json.dumps(body).encode(), "application/json"
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache or "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _caller(self):
        return (self.headers.get("X-authentik-username") or "").strip() or None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._send(200, "ok")
        if path.startswith("/img/") and path.endswith(".png"):
            aid = path[len("/img/"):-len(".png")]
            if aid not in IDS:
                return self._send(404, "not found")
            return self._send(200, (APP / "img" / f"{aid}.png").read_bytes(),
                              "image/png", cache="public, max-age=86400")
        caller = self._caller()
        if path in ("/", "/index.html"):
            return self._send(200, INDEX, "text/html; charset=utf-8") if caller else self._send(401, "login required")
        if path == "/api/state":
            if not caller:
                return self._send(401, {"error": "login required"})
            try:
                users = _cfg["client"].list_users()
            except AuthentikError:
                return self._send(503, {"error": "Authentik unreachable"})
            return self._send(200, {"user": caller, "version": VERSION,
                                    "avatars": core.gallery_state(GALLERY, users, _cfg["base"], caller)})
        return self._send(404, "not found")

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/pick":
            return self._send(404, "not found")
        caller = self._caller()
        if not caller:
            return self._send(401, {"error": "login required"})
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 1024)
            aid = json.loads(self.rfile.read(n) or b"{}").get("id")
        except (ValueError, AttributeError):
            aid = None
        if not isinstance(aid, str) or aid not in IDS:
            return self._send(400, {"error": "unknown avatar"})
        with _pick_lock:
            try:
                users = _cfg["client"].list_users()
                pk = core.check_pick(GALLERY, users, _cfg["base"], caller, aid)
                current = next(u for u in users if u["pk"] == pk).get("attributes") or {}
                _cfg["client"].set_attributes(pk, core.merged_attributes(current, _cfg["base"], aid))
            except core.AvatarTaken:
                return self._send(409, {"error": "just taken - pick another"})
            except core.UnknownUser:
                return self._send(403, {"error": "unknown user"})
            except AuthentikError:
                return self._send(503, {"error": "Authentik unreachable"})
        self.log_message("pick %s -> %s", caller, aid)
        return self._send(200, {"ok": True, "url": core.avatar_url(_cfg["base"], aid)})


def main():
    token = pathlib.Path(os.environ["AUTHENTIK_TOKEN_FILE"]).read_text().strip()
    configure(Client(os.environ["AUTHENTIK_URL"], token), os.environ["PUBLIC_BASE_URL"])
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Implement `app/static/index.html`** (Netflix-style grid; fetches `/api/state`, posts `/api/pick`)

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Choose your avatar</title>
<style>
  :root{color-scheme:dark}
  body{margin:0;background:#141414;color:#e5e5e5;font-family:system-ui,sans-serif}
  main{max-width:960px;margin:0 auto;padding:2rem 1rem;text-align:center}
  h1{font-weight:500;font-size:2rem;margin:.5rem 0}
  p.sub{color:#999;margin:0 0 2rem}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:1.4rem}
  button.av{background:none;border:0;padding:0;color:inherit;cursor:pointer;font:inherit}
  button.av img{width:100%;aspect-ratio:1;border-radius:.5rem;border:3px solid transparent;
    transition:transform .15s,border-color .15s}
  button.av:hover:not(:disabled) img{transform:scale(1.06);border-color:#fff}
  button.av.mine img{border-color:#e50914}
  button.av:disabled{cursor:not-allowed}
  button.av:disabled img{filter:grayscale(1) brightness(.45)}
  .name{display:block;margin-top:.4rem;color:#b3b3b3;font-size:.9rem}
  .mine .name{color:#fff;font-weight:600}
  #msg{min-height:1.5rem;margin:1rem 0;color:#e87c03}
  footer{color:#555;font-size:.75rem;margin-top:3rem}
</style></head>
<body><main>
  <h1>Choose your avatar</h1>
  <p class="sub" id="who">Loading&hellip;</p>
  <div id="msg" role="status"></div>
  <div class="grid" id="grid"></div>
  <footer>Shown in Authentik, Jellyfin and Nextcloud (after your next sign-in there).
    Images: Fluent Emoji &copy; Microsoft, MIT. <span id="ver"></span></footer>
</main>
<script>
const $ = id => document.getElementById(id);
async function load() {
  const r = await fetch("api/state", {cache: "no-store"});
  if (!r.ok) { $("msg").textContent = "Can't load right now - try again in a minute."; return; }
  const s = await r.json();
  $("who").textContent = "Signed in as " + s.user + ". Each avatar can only belong to one person.";
  $("ver").textContent = "v" + s.version;
  const g = $("grid"); g.textContent = "";
  for (const a of s.avatars) {
    const b = document.createElement("button");
    b.className = "av" + (a.status === "mine" ? " mine" : "");
    b.disabled = a.status === "taken";
    b.title = a.status === "taken" ? a.name + " (taken)" : a.name;
    b.innerHTML = '<img alt=""><span class="name"></span>';
    b.querySelector("img").src = a.url; b.querySelector("img").alt = a.name;
    b.querySelector(".name").textContent = a.status === "taken" ? a.name + " · taken" : a.name;
    b.onclick = () => pick(a.id, a.name);
    g.appendChild(b);
  }
}
async function pick(id, name) {
  $("msg").textContent = "Saving " + name + "…";
  const r = await fetch("api/pick", {method: "POST", headers: {"Content-Type": "application/json"},
                                     body: JSON.stringify({id})});
  const j = await r.json().catch(() => ({}));
  $("msg").textContent = r.ok ? name + " is yours." : (j.error || "Couldn't save - try again.");
  load();
}
load();
</script></body></html>
```

- [ ] **Step 5: Run all tests**

Run: `cd /home/pi/Projects/Docker/Avatar-Picker && python3 -m unittest discover -s tests -v`
Expected: `OK` (17 tests)

- [ ] **Step 6: Commit**

```bash
cd /home/pi/Projects && git add Docker/Avatar-Picker/app/server.py Docker/Avatar-Picker/app/static Docker/Avatar-Picker/tests/test_server.py
git commit -m "Avatar-Picker: add HTTP server, picker page and server tests"
```

---

### Task 6: Authentik objects (service account, token, forward-auth app, avatar setting)

**Files:**
- Create: `Docker/Avatar-Picker/scripts/provision-authentik.py`
- Create (gitignored): `Docker/Avatar-Picker/secrets/authentik_token`

- [ ] **Step 1: Write `scripts/provision-authentik.py`** (idempotent; run inside `ak shell`; prints the token only to stdout, which the caller redirects into the secrets file)

```python
# Run: docker compose -f Docker/Authentik/docker-compose.yaml exec -T server ak shell < this file
from authentik.core.models import User, Token, TokenIntents, Application, UserTypes
from authentik.rbac.models import Role
from authentik.providers.proxy.models import ProxyProvider, ProxyMode
from authentik.outposts.models import Outpost
from authentik.flows.models import Flow
from authentik.tenants.models import Tenant
from django.contrib.auth.models import Permission

# 1. service account + least-privilege role (view/change users only)
sa, _ = User.objects.get_or_create(username="avatar-picker",
        defaults={"name": "Avatar picker (service)", "type": UserTypes.INTERNAL_SERVICE_ACCOUNT})
role, _ = Role.objects.get_or_create(name="avatar-picker")
for codename in ("view_user", "change_user"):
    role.assign_perms(f"authentik_core.{codename}")
role.group.users.add(sa) if hasattr(role, "group") and role.group else None
# 2026.x roles are bound to groups; ensure the service account is in a group carrying the role
from authentik.core.models import Group
grp, _ = Group.objects.get_or_create(name="avatar-picker-service")
grp.users.add(sa)
grp.roles.add(role) if hasattr(grp, "roles") else None

# 2. non-expiring API token
tok, _ = Token.objects.get_or_create(identifier="avatar-picker-api",
        defaults={"user": sa, "intent": TokenIntents.INTENT_API, "expiring": False,
                  "description": "Avatar picker - writes attributes.avatar"})

# 3. forward-auth proxy provider + application for avatars.holy-grail.ch
src = ProxyProvider.objects.get(name="cup-proxy")
prov, _ = ProxyProvider.objects.get_or_create(name="avatar-picker-proxy", defaults={
    "mode": ProxyMode.FORWARD_SINGLE, "external_host": "https://avatars.holy-grail.ch",
    "authorization_flow": src.authorization_flow, "invalidation_flow": src.invalidation_flow})
Application.objects.get_or_create(slug="avatar-picker", defaults={
    "name": "Avatar picker", "provider": prov, "meta_launch_url": "https://avatars.holy-grail.ch"})
op = Outpost.objects.get(name="authentik Embedded Outpost"); op.providers.add(prov); op.save()

# 4. avatar source: picker choice first, initials fallback (drops gravatar)
t = Tenant.objects.get(schema_name="public"); t.avatars = "attributes.avatar,initials"; t.save()

print("TOKEN=" + tok.key)
```

> Note for the implementer: the exact RBAC API differs between Authentik versions. Before running, check in `ak shell` how 2026.8 binds roles (`Role.assign_perms`, role↔group or role↔user). Adjust only that block so the service account ends up with exactly `view_user` + `change_user`, and remove the two speculative lines. Verify in Step 3.

- [ ] **Step 2: Run it and store the token**

```bash
cd /home/pi/Projects/Docker && mkdir -p Avatar-Picker/secrets && chmod 700 Avatar-Picker/secrets
docker compose -f Authentik/docker-compose.yaml exec -T server ak shell < Avatar-Picker/scripts/provision-authentik.py 2>/dev/null \
  | grep -oP '^TOKEN=\K.+' > Avatar-Picker/secrets/authentik_token
chmod 600 Avatar-Picker/secrets/authentik_token; test -s Avatar-Picker/secrets/authentik_token && echo token-saved
```
Expected: `token-saved`

- [ ] **Step 3: Verify least privilege**

```bash
T=$(cat Avatar-Picker/secrets/authentik_token)
curl -s -o /dev/null -w "list users: %{http_code}\n" -H "Authorization: Bearer $T" https://sso.holy-grail.ch/api/v3/core/users/?page_size=1
curl -s -o /dev/null -w "list groups (must be 403): %{http_code}\n" -H "Authorization: Bearer $T" https://sso.holy-grail.ch/api/v3/core/groups/?page_size=1
```
Expected: `200` and `403`.

- [ ] **Step 4: Commit** (script only; `secrets/` is gitignored)

```bash
cd /home/pi/Projects && git add Docker/Avatar-Picker/scripts/provision-authentik.py && git status --short Docker/Avatar-Picker
git commit -m "Avatar-Picker: add Authentik provisioning script (service account, forward-auth app, avatar setting)"
```

---

### Task 7: Deploy container + Traefik + local DNS

**Files:**
- Create: `Docker/Traefik/traefik/dynamic/avatar-picker.yml`
- Modify: `Docker/adguard/conf/AdGuardHome.yaml` (rewrites)

- [ ] **Step 1: Traefik route** — `Docker/Traefik/traefik/dynamic/avatar-picker.yml`

```yaml
# Avatar picker (Docker/Avatar-Picker). /img/* is PUBLIC on purpose: Jellyfin and
# Nextcloud fetch the picture server-side without a login. Everything else is
# behind Authentik forward auth, which also supplies X-authentik-username.
http:
  routers:
    avatar-picker-img:
      rule: "Host(`avatars.holy-grail.ch`) && PathPrefix(`/img/`)"
      entryPoints: ["websecure"]
      priority: 20
      service: avatar-picker
      middlewares:
        - default-rate-limit@file
      tls:
        certResolver: cloudflare
    avatar-picker-outpost:
      rule: "Host(`avatars.holy-grail.ch`) && PathPrefix(`/outpost.goauthentik.io/`)"
      entryPoints: ["websecure"]
      priority: 10
      service: authentik@file
      tls:
        certResolver: cloudflare
    avatar-picker:
      rule: "Host(`avatars.holy-grail.ch`)"
      entryPoints: ["websecure"]
      priority: 1
      service: avatar-picker
      middlewares:
        - authentik@file
        - default-rate-limit@file
      tls:
        certResolver: cloudflare
  services:
    avatar-picker:
      loadBalancer:
        servers:
          - url: "http://avatar-picker:8080"
```

- [ ] **Step 2: Build and start**

```bash
cd /home/pi/Projects/Docker/Avatar-Picker && docker compose up -d --build && sleep 10 && docker compose ps
```
Expected: `avatar-picker ... (healthy)`.

- [ ] **Step 3: Local checks via Traefik (before Cloudflare exists)**

```bash
R="--resolve avatars.holy-grail.ch:443:192.168.1.2"
curl -s $R -o /dev/null -w "img: %{http_code} %{content_type}\n" https://avatars.holy-grail.ch/img/fox.png      # 200 image/png
curl -s $R -o /dev/null -w "page: %{http_code} %{redirect_url}\n" https://avatars.holy-grail.ch/                # 302 -> sso
curl -s $R -o /dev/null -w "spoof: %{http_code}\n" -H "X-authentik-username: akadmin" https://avatars.holy-grail.ch/api/state  # 302 (header ignored, auth first)
```

- [ ] **Step 4: AdGuard rewrite** (LAN/VPN go direct): add `avatars.holy-grail.ch -> 192.168.1.2` under `rewrites:` in `Docker/adguard/conf/AdGuardHome.yaml` (backup first), `docker restart adguardhome`, verify `dig +short @127.0.0.1 avatars.holy-grail.ch` → `192.168.1.2`. (The conf dir is gitignored — no commit.)

- [ ] **Step 5: Commit Traefik route**

```bash
cd /home/pi/Projects && git add Docker/Traefik/traefik/dynamic/avatar-picker.yml
git commit -m "Traefik: route avatars.holy-grail.ch (public /img, Authentik-gated picker)"
```

---

### Task 8: Consumers — Jellyfin and Nextcloud

- [ ] **Step 1: Jellyfin plugin sync** (beefy; container stopped while editing)

```bash
ssh beefy 'cd ~/Projects/Docker/Jellyfin && f=/srv/appdata/jellyfin/data/plugins/configurations/Jellyfin.Plugin.Oidc.xml && cp $f $f.bak-2026-10-18 && docker compose stop jellyfin && sed -i "s#<SynchronizeProfileImages>false</SynchronizeProfileImages>#<SynchronizeProfileImages>true</SynchronizeProfileImages>#" $f && grep SynchronizeProfileImages $f && docker compose start jellyfin'
```
Expected: `<SynchronizeProfileImages>true</SynchronizeProfileImages>`.

- [ ] **Step 2: Nextcloud avatar mapping** (tower; requires `occ` to work — it is blocked until the corrupted-file repair on tower is done, see `tower-unraid` memory)

```bash
ssh tower-direct 'docker exec -u www-data nextcloud php occ user_oidc:provider authentik --mapping-avatar=picture && docker exec -u www-data nextcloud php occ user_oidc:provider authentik | grep -i avatar'
```
Expected: mapping shows `picture`.

- [ ] **Step 3: Verify the claim end-to-end** — after a user picks an avatar (Task 9), an access token's userinfo must contain `"picture": "https://avatars.holy-grail.ch/img/<id>.png"`. Check via `ak shell`: `User.objects.get(username=...).avatar` returns that URL.

---

### Task 9: Docs, smoke test, checklist, end-to-end

- [ ] **Step 1: README.md** — what it is, URLs, how uniqueness works, how to add avatars (edit `ANIMALS`, rerun build script), secrets file, rollback (`docker compose down`, set Avatars back to `gravatar,initials`), and the consumer settings from Task 8. Commit `Avatar-Picker: add README`.

- [ ] **Step 2: Smoke test** — add to `Docker/_global/scripts/smoke-test.sh` a section:

```bash
echo "== Avatar picker"
running avatar-picker
check "avatar image public"       '^200$' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' --resolve avatars.holy-grail.ch:443:192.168.1.2 https://avatars.holy-grail.ch/img/fox.png)"
check "picker behind Authentik"   'sso\.holy-grail\.ch' "$(curl -s -m 10 -o /dev/null -w '%{redirect_url}' --resolve avatars.holy-grail.ch:443:192.168.1.2 https://avatars.holy-grail.ch/)"
```
Run it, commit `Global: smoke-test the avatar picker`.

- [ ] **Step 3: Checklist** — add row to `Docker/_global/checklist.md`: `| Avatar-Picker | ❌ | ❌ | | |  |` (never ✅). Commit.

- [ ] **Step 4: User step — Cloudflare** (dashboard): Zero Trust → Networks → Tunnels → fastpi → Published application routes → Add: subdomain `avatars`, domain `holy-grail.ch`, service `https://192.168.1.2:443` (same TLS settings as the other routes). Then verify `curl -s -o /dev/null -w '%{http_code}' https://avatars.holy-grail.ch/img/fox.png` → `200` from the internet path.

- [ ] **Step 5: End-to-end with the user**: user opens the page, picks an avatar → Authentik shows it → sign out/in of Jellyfin → avatar appears; Nextcloud after Task 8 Step 2.
