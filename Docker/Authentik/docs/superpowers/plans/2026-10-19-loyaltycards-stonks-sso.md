# Holy Grail Login for LoyaltyCards and Stonks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the own username/password logins of LoyaltyCards (PocketBase + PWA) and Stonks (FastAPI) with "Sign in with Holy Grail" (Authentik OIDC at `https://sso.holy-grail.ch`, Authentik 2026.8.4), and make the old logins unreachable, with shell-only recovery.

**Architecture:** One Authentik OIDC provider + application per app, created by the idempotent `provision-admin-sso.py`; secrets flow into gitignored `.env` files through `apply-sso-env.py`. PocketBase uses its built-in `oidc` provider (config reconciled from env in Go on every start); the PWA reuses its existing redirect-based OAuth code path. Stonks gets native OIDC (Authlib) beside its existing password mode, selected by `AUTH_MODE`. PocketBase superuser endpoints are denied at Traefik.

**Tech Stack:** Authentik (python `ak shell`), PocketBase 0.39.1 (Go 1.25, tested in `golang:1.25-alpine`), Svelte 5 + Vite + vitest + Playwright, FastAPI + Authlib + pytest, Traefik file provider, Docker Compose.

**Spec:** `Docker/Authentik/docs/superpowers/specs/2026-10-19-loyaltycards-stonks-sso-design.md` (read it first; its open questions Q1-Q7 must be answered before Task 1).

**Conventions (from the user's global instructions):**
- Commit messages: `Project Name: short description`, e.g. `Authentik: ...`, `LoyaltyCards-Sync: ...`, `LoyaltyCards: ...`, `Stonks: ...`, `Traefik: ...`. **Never** add `Co-Authored-By` or any AI attribution line. Add files explicitly (never `git add -A` / `.`).
- Repos: infra `/home/pi/Projects` (all `Docker/*`); PWA `/home/pi/Documents/development/LoyaltyCards` (push-to-main allowed); Stonks `/home/pi/Documents/development/Stonks`.
- `/home/pi/Projects` has other people's uncommitted edits (e.g. `Docker/Authentik/scripts/provision-admin-sso.py`). Stage only your own hunks (`git add -p <file>`) and check `git diff --cached --stat` before each commit. Never `git reset --hard`.
- Never print `.env` contents or secrets. Never probe from the public side (CrowdSec bans the home IP): test with `docker exec`, container-to-container requests, or `curl --resolve host:443:127.0.0.1` against local Traefik.
- `UID` is a read-only bash variable: do not use it in shell snippets.
- Phases that need the user are marked **USER**. Do not mark anything in `Docker/_global/checklist.md` as checked.

## File structure

| File | Repo | Responsibility |
|---|---|---|
| `Docker/Authentik/scripts/provision-admin-sso.py` | infra | `app_for(group=)`, `loyalty-users` group, providers/apps `loyalty-cards` and `stonks` |
| `Docker/LoyaltyCards-Sync/oidc.go` | infra | `oidcConfig`, `loadOIDCConfig()`, `configureUsersAuth()` |
| `Docker/LoyaltyCards-Sync/oidc_test.go` | infra | tests for the above |
| `Docker/LoyaltyCards-Sync/main.go` | infra | call the reconcile from `OnServe` |
| `Docker/LoyaltyCards-Sync/docker-compose.yaml`, `.env.example` | infra | env + `extra_hosts` |
| `Docker/Traefik/traefik/dynamic/loyalty-sync.yml` | infra | superuser deny router |
| `src/lib/auth/store.ts`, `store.test.ts`, `src/components/AccountSection.svelte`, `AccountSection.test.ts`, `src/App.svelte`, `e2e/auth.spec.ts` | PWA | Holy Grail button, redirect flow |
| `app/config.py`, `app/oidc.py` (new), `app/web/routes.py`, `app/web/deps.py`, `app/main.py`, `app/web/templates/login.html`, `requirements.txt`, `tests/test_oidc.py` (new) | Stonks | native OIDC |
| `Docker/Stonks/docker-compose.yaml`, `.env.example` | infra | env + `extra_hosts` |

---

## Task 0: Preflight and backups (no behaviour change)

**Files:** none changed.

- [ ] **Step 1: Confirm the spec questions are answered** (Q1 group, Q3 second user, Q4 invalidate sessions, Q5 admin exposure, Q7 Stonks approach). If Q1 differs from `loyalty-users`, substitute the group name in Task 1 and Task 8.

- [ ] **Step 2: Back up PocketBase data**

```bash
cd /home/pi/Projects/Docker/LoyaltyCards-Sync
mkdir -p /home/pi/backups
docker run --rm -v loyaltycards-sync_pb_data:/d:ro -v /home/pi/backups:/b alpine \
  tar czf /b/pb_data-$(date +%Y%m%d-%H%M%S).tgz -C /d .
ls -l /home/pi/backups | tail -2
```
Expected: a `pb_data-*.tgz` of a few hundred KB or more. (If the volume name differs, `docker volume ls | grep pb_data`.)

- [ ] **Step 3: Back up Stonks data and tag current images for rollback**

```bash
cd /home/pi/Projects/Docker/Stonks && ./redeploy.sh --help >/dev/null 2>&1 || true
docker exec stonks sh -c 'mkdir -p /data/backups && cp -p /data/stonks.db /data/backups/stonks-pre-sso.db' && echo ok
docker tag stonks:latest stonks:pre-sso
docker tag loyaltycards-sync:local loyaltycards-sync:pre-sso
grep -n IMAGE_TAG /home/pi/Projects/Docker/LoyaltyCards/.env | sed 's/=.*/=<value>/'
```
Expected: `ok`; both tags created. Write the current PWA tag down (`IMAGE_TAG` value, read it with `grep IMAGE_TAG .env`; it is not secret) for rollback.

- [ ] **Step 4: Record the current state of the endpoints (baseline)**

```bash
docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -w '%{http_code}\n' http://loyalty-sync:8090/api/health
docker run --rm --network traefik_proxy curlimages/curl -s http://loyalty-sync:8090/api/collections/users/auth-methods | head -c 400
docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -w '%{http_code}\n' http://stonks:8000/healthz
```
Expected: `200`; auth-methods JSON containing `"password":{"enabled":true` and a `google` provider; `200`.

## Task 1: Authentik provisioning (config as code)

**Files:**
- Modify: `Docker/Authentik/scripts/provision-admin-sso.py` (`app_for`, new block before `outpost.save()`)

- [ ] **Step 1: Make `app_for` take an optional group**

Replace

```python
def bind_admins(app):
    PolicyBinding.objects.get_or_create(target=app, group=admins, defaults={"order": 0})


def app_for(slug, name, provider, url):
    app, _ = Application.objects.update_or_create(
        slug=slug, defaults={"name": name, "provider": provider, "meta_launch_url": url})
    bind_admins(app)
    return app
```
with

```python
def bind_group(app, group):
    PolicyBinding.objects.get_or_create(target=app, group=group, defaults={"order": 0})


def bind_admins(app):
    bind_group(app, admins)


def app_for(slug, name, provider, url, group=None):
    """group: the Authentik group allowed in (default homelab-admins)."""
    app, _ = Application.objects.update_or_create(
        slug=slug, defaults={"name": name, "provider": provider, "meta_launch_url": url})
    bind_group(app, group or admins)
    return app
```

- [ ] **Step 2: Add the two apps** before the final `outpost.save()`:

```python
# 7. LoyaltyCards (PocketBase's built-in OIDC provider "oidc"; the PWA returns to its own origin,
# see Docker/LoyaltyCards-Sync/oidc.go). PocketBase links an existing user by email only when
# email_verified is true, so this provider reuses the wg-easy "verified" email mapping
# (enrolment is invite-only). Group loyalty-users; the current homelab-admins members are the
# initial members (add others in the Authentik UI).
loyalty_users, _ = Group.objects.get_or_create(name="loyalty-users")
for u in admins.users.all():
    loyalty_users.users.add(u)
lc = oidc("loyalty-cards", ["https://loyalty-cards.holy-grail.ch/"],
          mappings=[m for m in oidc_mappings if not m.managed.endswith("scope-email")] + [wg_email])
app_for("loyalty-cards", "LoyaltyCards", lc, "https://loyalty-cards.holy-grail.ch",
        group=loyalty_users)
env("LoyaltyCards-Sync/.env", OIDC_CLIENT_ID=lc.client_id, OIDC_CLIENT_SECRET=lc.client_secret)

# 8. Stonks (native OIDC in the app, Authlib; redirect /auth/callback). Single user -> homelab-admins.
# Default scope mappings are enough: the app reads preferred_username / email from userinfo.
stonks = oidc("stonks", ["https://stonks.holy-grail.ch/auth/callback"])
app_for("stonks", "Stonks", stonks, "https://stonks.holy-grail.ch")
env("Stonks/.env", OIDC_CLIENT_ID=stonks.client_id, OIDC_CLIENT_SECRET=stonks.client_secret)
```

- [ ] **Step 3: Syntax check (no Authentik change)**

Run: `python3 -I -c "import ast,sys; ast.parse(open('/home/pi/Projects/Docker/Authentik/scripts/provision-admin-sso.py').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 4: Run the provisioning (this changes Authentik; only after Q1/Q4 are settled)**

```bash
cd /home/pi/Projects/Docker/Authentik
docker compose exec -T server ak shell < scripts/provision-admin-sso.py | python3 scripts/apply-sso-env.py 2>&1 | grep -v '^{'
```
Expected output contains `set LoyaltyCards-Sync/.env OIDC_CLIENT_ID`, `... OIDC_CLIENT_SECRET`, `set Stonks/.env OIDC_CLIENT_ID`, `... OIDC_CLIENT_SECRET` (key names only, never values) and `OK provisioned`. Wait ~30 s for the embedded outpost.

- [ ] **Step 5: Verify by a read-only query**

```bash
cd /home/pi/Projects/Docker/Authentik && docker compose exec -T server ak shell 2>&1 <<'EOF' | grep '^RESULT'
from authentik.core.models import Application, Group
from authentik.providers.oauth2.models import OAuth2Provider
for s in ("loyalty-cards", "stonks"):
    a = Application.objects.get(slug=s)
    p = a.provider.oauth2provider
    print("RESULT", s, "redirects", [r.url for r in p.redirect_uris],
          "bound", [b.group.name for b in a.policybindings.all()],
          "email_mapping", sorted(m.name for m in p.property_mappings.all() if m.scope_name == "email"))
print("RESULT loyalty-users members", Group.objects.get(name="loyalty-users").users.count())
EOF
```
Expected: `loyalty-cards` redirects `['https://loyalty-cards.holy-grail.ch/']`, bound `['loyalty-users']`, email mapping `['wg-easy email (verified)']`; `stonks` redirects `['https://stonks.holy-grail.ch/auth/callback']`, bound `['homelab-admins']`; `loyalty-users members 1`.

- [ ] **Step 6: Commit (own hunks only)**

```bash
cd /home/pi/Projects
git add -p Docker/Authentik/scripts/provision-admin-sso.py   # accept only the hunks from Steps 1-2
git diff --cached --stat
git commit -m "Authentik: add LoyaltyCards and Stonks OIDC apps, per-app group binding"
```

## Task 2: Stonks native OIDC (TDD, code repo, nothing deployed)

Work in `/home/pi/Documents/development/Stonks` (`.venv` per README: `.venv/bin/pytest`).

**Files:**
- Modify: `requirements.txt`, `app/config.py`, `app/web/deps.py`, `app/web/routes.py`, `app/main.py`, `app/web/templates/login.html`
- Create: `app/oidc.py`, `tests/test_oidc.py`

- [ ] **Step 1: Add the dependency**

```bash
cd /home/pi/Documents/development/Stonks
.venv/bin/pip index versions authlib 2>&1 | head -2      # note the newest 1.x version, e.g. 1.6.x
```
Append `authlib==<that version>` to `requirements.txt` (httpx and itsdangerous are already pinned there; Authlib's Starlette client needs both), then `.venv/bin/pip install -r requirements-dev.txt`.

- [ ] **Step 2: Write the failing tests**: `tests/test_oidc.py`

```python
import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from authlib.integrations.base_client.errors import OAuthError

from app.auth import SESSION_COOKIE, read_session, make_session
from app.config import settings
from app.main import app
from app.oidc import oauth, username_from_userinfo


@pytest.fixture
def oidc_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "public_url", "https://stonks.example")


def test_username_prefers_preferred_username():
    assert username_from_userinfo({"preferred_username": "tom", "email": "t@x"}) == "tom"
    assert username_from_userinfo({"email": "t@x"}) == "t@x"
    assert username_from_userinfo({}) is None


def test_login_page_shows_button_in_oidc_mode(oidc_mode):
    r = TestClient(app, follow_redirects=False).get("/login")
    assert r.status_code == 200
    assert "/auth/login" in r.text
    assert 'name="password"' not in r.text


def test_post_login_is_404_in_oidc_mode(oidc_mode):
    r = TestClient(app, follow_redirects=False).post("/login", data={"username": "a", "password": "b"})
    assert r.status_code == 404


def test_unauthenticated_redirects_to_oidc_login(oidc_mode):
    r = TestClient(app, follow_redirects=False).get("/holdings")
    assert r.status_code == 303
    assert r.headers["location"] == "/auth/login"


def test_auth_login_starts_flow_with_public_callback(oidc_mode, monkeypatch):
    seen = {}

    async def fake_redirect(request, redirect_uri, **kw):
        seen["redirect_uri"] = redirect_uri
        return RedirectResponse("https://sso.example/authorize", status_code=302)

    monkeypatch.setattr(oauth.holygrail, "authorize_redirect", fake_redirect)
    r = TestClient(app, follow_redirects=False).get("/auth/login")
    assert r.status_code == 302
    assert seen["redirect_uri"] == "https://stonks.example/auth/callback"


def test_callback_sets_session_cookie(oidc_mode, monkeypatch):
    async def fake_token(request):
        return {"userinfo": {"preferred_username": "tom"}}

    monkeypatch.setattr(oauth.holygrail, "authorize_access_token", fake_token)
    r = TestClient(app, follow_redirects=False).get("/auth/callback?code=c&state=s")
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert read_session(r.cookies[SESSION_COOKIE]) == "tom"


def test_callback_without_username_is_rejected(oidc_mode, monkeypatch):
    async def fake_token(request):
        return {"userinfo": {}}

    monkeypatch.setattr(oauth.holygrail, "authorize_access_token", fake_token)
    r = TestClient(app, follow_redirects=False).get("/auth/callback?code=c&state=s")
    assert r.status_code == 401
    assert SESSION_COOKIE not in r.cookies


def test_callback_oauth_error_is_rejected(oidc_mode, monkeypatch):
    async def boom(request):
        raise OAuthError(error="access_denied")

    monkeypatch.setattr(oauth.holygrail, "authorize_access_token", boom)
    r = TestClient(app, follow_redirects=False).get("/auth/callback?code=c&state=s")
    assert r.status_code == 401


def test_auth_routes_404_in_password_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "password")
    c = TestClient(app, follow_redirects=False)
    assert c.get("/auth/login").status_code == 404
    assert c.get("/auth/callback").status_code == 404


def test_logout_clears_cookie_and_goes_to_login_page(oidc_mode):
    c = TestClient(app, follow_redirects=False)
    c.cookies.set(SESSION_COOKIE, make_session("tom"))
    r = c.post("/logout")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
```

- [ ] **Step 3: Run to confirm failure**

Run: `.venv/bin/pytest tests/test_oidc.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'app.oidc'`.

- [ ] **Step 4: Settings**: add to `Settings` in `app/config.py` (after `session_secret`):

```python
    # "password" (own form login, default so the code can ship first) or "oidc" (Authentik).
    auth_mode: str = "password"
    oidc_issuer: str = "https://sso.holy-grail.ch/application/o/stonks/"
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    public_url: str = "https://stonks.holy-grail.ch"
```

- [ ] **Step 5: `app/oidc.py`**

```python
from authlib.integrations.starlette_client import OAuth

from app.config import settings

oauth = OAuth()
# Registered lazily-evaluated: discovery is fetched on first use, so importing this module
# needs no network and no client id (tests, password mode).
oauth.register(
    name="holygrail",
    client_id=settings.oidc_client_id,
    client_secret=settings.oidc_client_secret,
    server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
)


def callback_url() -> str:
    return settings.public_url.rstrip("/") + "/auth/callback"


def username_from_userinfo(info: dict) -> str | None:
    return info.get("preferred_username") or info.get("email")
```

- [ ] **Step 6: `current_user` target** in `app/web/deps.py`: replace the `raise` with

```python
    if not user:
        from app.config import settings
        target = "/auth/login" if settings.auth_mode == "oidc" else "/login"
        raise HTTPException(status_code=303, headers={"Location": target})
```
(move the `settings` import to the top of the file, it is shown inline only for brevity: `from app.config import settings`).

- [ ] **Step 7: Routes**: in `app/web/routes.py` add imports `from authlib.integrations.base_client.errors import OAuthError` and `from app.oidc import oauth, callback_url, username_from_userinfo`, then replace `login_form`, the first lines of `login_submit`, and add the two OIDC routes:

```python
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        request, "login.html", {"user": None, "oidc": settings.auth_mode == "oidc"})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if settings.auth_mode == "oidc":
        raise HTTPException(status_code=404)
    ip = request.client.host if request.client else "unknown"
    # ... rest of the function unchanged ...


@router.get("/auth/login")
async def oidc_login(request: Request):
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=404)
    return await oauth.holygrail.authorize_redirect(request, callback_url())


@router.get("/auth/callback")
async def oidc_callback(request: Request):
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=404)
    try:
        token = await oauth.holygrail.authorize_access_token(request)
    except OAuthError:
        token = None
    username = username_from_userinfo((token or {}).get("userinfo") or {})
    if not username:
        return templates.TemplateResponse(
            request, "login.html",
            {"user": None, "oidc": True, "error": "Sign-in failed. Try again."},
            status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(SESSION_COOKIE, make_session(username), httponly=True,
                    samesite="lax", secure=True, max_age=60 * 60 * 24 * 30)
    return resp
```

- [ ] **Step 8: Session middleware** (Authlib keeps `state`/PKCE verifier in the Starlette session) in `app/main.py`, right after `app = FastAPI(...)`:

```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                   session_cookie="stonks_oidc", https_only=True, same_site="lax", max_age=600)
```
(`from app.config import settings` if not already imported in `main.py`.)

- [ ] **Step 9: Template** `app/web/templates/login.html`: replace the `<form>` block with

```html
    {% if oidc %}
    <a class="btn" href="/auth/login"><button type="button">Sign in with Holy Grail</button></a>
    {% else %}
    <form method="post" action="/login">
      <input name="username" placeholder="username" autofocus>
      <input name="password" type="password" placeholder="password">
      <button type="submit">Log in</button>
    </form>
    {% endif %}
```
(Invalid nesting of `<button>` in `<a>` is avoided if you prefer: `<a class="button" href="/auth/login">Sign in with Holy Grail</a>`; reuse the existing button CSS class from `static/`, check with `grep -n "button" app/web/static/*.css`.)

- [ ] **Step 10: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: all pass (the existing `test_web.py` password tests still pass: default `auth_mode` is `password`).

- [ ] **Step 11: Commit (code repo)**

```bash
git add requirements.txt app/config.py app/oidc.py app/web/deps.py app/web/routes.py app/main.py app/web/templates/login.html tests/test_oidc.py
git commit -m "Stonks: native OIDC login (Authentik) behind AUTH_MODE, password mode kept for recovery"
```

## Task 3: Stonks deploy and verification

**Files:**
- Modify: `Docker/Stonks/docker-compose.yaml`, `Docker/Stonks/.env.example`, `Docker/Stonks/.env` (gitignored)

- [ ] **Step 1: Compose `extra_hosts`** in the `stonks` service (the container resolves the SSO host to the Pi, per the Authentik README gotcha):

```yaml
    extra_hosts:
      - "sso.holy-grail.ch:192.168.1.2"
```

- [ ] **Step 2: Env.** `.env.example` (same order/comments as `.env`; secret blank), add after the web-auth block:

```
# Web login: "oidc" = Sign in with Holy Grail (Authentik); "password" = own form login
# (shell recovery only: set to password, then `docker compose up -d`).
AUTH_MODE=password
OIDC_ISSUER=https://sso.holy-grail.ch/application/o/stonks/
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
PUBLIC_URL=https://stonks.holy-grail.ch
```
In `.env` (already holds `OIDC_CLIENT_ID/SECRET` from Task 1) append only the three non-secret lines with `sed`/`printf >>`; keep `AUTH_MODE=password` for now. Do not `cat` `.env`.

- [ ] **Step 3: Rebuild and redeploy in password mode** (no behaviour change yet)

```bash
cd /home/pi/Projects/Docker/Stonks && ./redeploy.sh
```
Expected: backup line, build ok, health check prints `{"status":"ok"}`.

- [ ] **Step 4: Verify password mode unchanged**

```bash
docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://stonks:8000/holdings
```
Expected: `303 http://stonks:8000/login`.

- [ ] **Step 5: Flip to oidc and verify the redirect to Authentik**

```bash
cd /home/pi/Projects/Docker/Stonks
sed -i 's/^AUTH_MODE=.*/AUTH_MODE=oidc/' .env && docker compose up -d
sleep 6
docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://stonks:8000/holdings
docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -w '%{http_code}\n' -X POST -d 'username=a&password=b' http://stonks:8000/login
docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -D - http://stonks:8000/auth/login | grep -i '^location' | sed 's/client_id=[^&]*/client_id=<id>/; s/state=[^&]*/state=<s>/; s/code_challenge=[^&]*/code_challenge=<c>/'
docker logs stonks 2>&1 | tail -5
```
Expected: `303 http://stonks:8000/auth/login`; `404`; a `location:` starting `https://sso.holy-grail.ch/application/o/authorize/?response_type=code&client_id=<id>&redirect_uri=https%3A%2F%2Fstonks.holy-grail.ch%2Fauth%2Fcallback&scope=openid+profile+email&state=<s>&code_challenge=<c>&code_challenge_method=S256`. If `/auth/login` is 500, the log shows a discovery fetch error: check `extra_hosts` (`docker exec stonks python -c "import urllib.request as u;print(u.urlopen('https://sso.holy-grail.ch/application/o/stonks/.well-known/openid-configuration').status)"` must print 200).

- [ ] **Step 6: USER: first real login.** Ask the user to open `https://stonks.holy-grail.ch/`, press "Sign in with Holy Grail", pass Authentik (MFA), and confirm the dashboard and holdings load, then log out and confirm the button page shows (no loop). Confirm Telegram still answers `/portfolio` (separate code path). **Stop here until the user confirms**; if it fails: `sed -i 's/^AUTH_MODE=.*/AUTH_MODE=password/' .env && docker compose up -d`.

- [ ] **Step 7: Commit (infra repo)**

```bash
cd /home/pi/Projects
git add Docker/Stonks/docker-compose.yaml Docker/Stonks/.env.example
git commit -m "Stonks: Sign in with Holy Grail (AUTH_MODE=oidc), sso extra_hosts"
```

## Task 4: PocketBase OIDC reconcile (TDD, Go)

Run Go in Docker (the host has no Go): define once

```bash
cd /home/pi/Projects/Docker/LoyaltyCards-Sync
GOTEST='docker run --rm -v '"$PWD"':/src -w /src golang:1.25-alpine go test ./... -count=1'
```

**Files:**
- Create: `Docker/LoyaltyCards-Sync/oidc.go`, `Docker/LoyaltyCards-Sync/oidc_test.go`
- Modify: `Docker/LoyaltyCards-Sync/main.go`

- [ ] **Step 1: Baseline**

Run: `eval "$GOTEST" 2>&1 | tail -5`
Expected: `ok  loyaltycards-sync` (existing rules/TOTP tests green).

- [ ] **Step 2: Write the failing tests**: `oidc_test.go`

```go
package main

import (
	"net/http"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/tests"
)

func goodCfg() oidcConfig {
	return oidcConfig{Enable: true, Only: true, BaseURL: "https://sso.example",
		ClientID: "cid", ClientSecret: "sec"}
}

func TestOIDCOnlyConfiguresProviderAndLocksPassword(t *testing.T) {
	app := setupApp(t)
	defer app.Cleanup()

	if err := configureUsersAuth(app, goodCfg()); err != nil {
		t.Fatal(err)
	}
	users, _ := app.FindCollectionByNameOrId("users")
	if !users.OAuth2.Enabled || len(users.OAuth2.Providers) != 1 {
		t.Fatalf("oauth2 not configured: %+v", users.OAuth2)
	}
	p := users.OAuth2.Providers[0]
	if p.Name != "oidc" || p.ClientId != "cid" || p.AuthURL != "https://sso.example/application/o/authorize/" ||
		p.TokenURL != "https://sso.example/application/o/token/" ||
		p.UserInfoURL != "https://sso.example/application/o/userinfo/" || p.PKCE == nil || !*p.PKCE {
		t.Fatalf("unexpected provider: %+v", p)
	}
	if users.PasswordAuth.Enabled {
		t.Fatal("password auth should be disabled")
	}
	if users.CreateRule == nil || *users.CreateRule != `@request.context = "oauth2"` {
		t.Fatalf("create rule: %v", users.CreateRule)
	}
}

func TestOIDCEnableOnlyKeepsPasswordLogin(t *testing.T) {
	app := setupApp(t)
	defer app.Cleanup()

	cfg := goodCfg()
	cfg.Only = false
	if err := configureUsersAuth(app, cfg); err != nil {
		t.Fatal(err)
	}
	users, _ := app.FindCollectionByNameOrId("users")
	if !users.PasswordAuth.Enabled || len(users.OAuth2.Providers) != 1 {
		t.Fatalf("phase-2 state wrong: password=%v providers=%d",
			users.PasswordAuth.Enabled, len(users.OAuth2.Providers))
	}
}

func TestOIDCMissingSecretChangesNothing(t *testing.T) {
	app := setupApp(t)
	defer app.Cleanup()

	cfg := goodCfg()
	cfg.ClientSecret = ""
	if err := configureUsersAuth(app, cfg); err != nil {
		t.Fatal(err)
	}
	users, _ := app.FindCollectionByNameOrId("users")
	if !users.PasswordAuth.Enabled {
		t.Fatal("must not lock out when the client secret is missing")
	}
}

func TestOIDCRollbackRestoresPassword(t *testing.T) {
	app := setupApp(t)
	defer app.Cleanup()

	_ = configureUsersAuth(app, goodCfg())
	cfg := goodCfg()
	cfg.Only = false
	if err := configureUsersAuth(app, cfg); err != nil {
		t.Fatal(err)
	}
	users, _ := app.FindCollectionByNameOrId("users")
	if !users.PasswordAuth.Enabled || users.CreateRule == nil || *users.CreateRule != "" {
		t.Fatalf("rollback failed: %v %v", users.PasswordAuth.Enabled, users.CreateRule)
	}
}

func TestPasswordEndpointForbiddenWhenOIDCOnly(t *testing.T) {
	(&tests.ApiScenario{
		Name:   "auth-with-password is refused",
		Method: http.MethodPost,
		URL:    "/api/collections/users/auth-with-password",
		Body:   strings.NewReader(`{"identity":"a@example.com","password":"password123"}`),
		Headers: map[string]string{"Content-Type": "application/json"},
		TestAppFactory: func(tb testing.TB) *tests.TestApp {
			app := setupApp(t)
			makeUser(t, app, "a@example.com")
			if err := configureUsersAuth(app, goodCfg()); err != nil {
				t.Fatal(err)
			}
			return app
		},
		ExpectedStatus:  403,
		ExpectedContent: []string{`"status":403`},
	}).Test(t)
}

func TestSignupByRestIsRefusedWhenOIDCOnly(t *testing.T) {
	(&tests.ApiScenario{
		Name:   "REST signup is refused",
		Method: http.MethodPost,
		URL:    "/api/collections/users/records",
		Body:   strings.NewReader(`{"email":"x@example.com","password":"password123","passwordConfirm":"password123"}`),
		Headers: map[string]string{"Content-Type": "application/json"},
		TestAppFactory: func(tb testing.TB) *tests.TestApp {
			app := setupApp(t)
			if err := configureUsersAuth(app, goodCfg()); err != nil {
				t.Fatal(err)
			}
			return app
		},
		ExpectedStatus:  400,
		ExpectedContent: []string{`"status":400`},
	}).Test(t)
}
```
(If PocketBase answers the signup with 403 instead of 400, change the expected status; the point is "not 200". Record the real value in the test.)

- [ ] **Step 3: Run to confirm failure**

Run: `eval "$GOTEST" 2>&1 | tail -8`
Expected: build failure `undefined: oidcConfig` / `undefined: configureUsersAuth`.

- [ ] **Step 4: Implement** `oidc.go`

```go
package main

import (
	"log"
	"os"
	"strings"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/types"
)

// oidcConfig drives configureUsersAuth.
//   Enable (OIDC_ENABLED=true): the Holy Grail (Authentik) provider "oidc" is configured,
//     password login is left as it is (phase 2: both work, used for the first real login).
//   Only (OIDC_ONLY=true, needs Enable): password login off, signup only via OAuth2.
//   Both false: untouched except password login/signup restored (rollback).
type oidcConfig struct {
	Enable       bool
	Only         bool
	BaseURL      string
	ClientID     string
	ClientSecret string
}

func loadOIDCConfig() oidcConfig {
	base := os.Getenv("OIDC_BASE_URL")
	if base == "" {
		base = "https://sso.holy-grail.ch"
	}
	return oidcConfig{
		Enable:       os.Getenv("OIDC_ENABLED") == "true",
		Only:         os.Getenv("OIDC_ONLY") == "true",
		BaseURL:      strings.TrimRight(base, "/"),
		ClientID:     os.Getenv("OIDC_CLIENT_ID"),
		ClientSecret: os.Getenv("OIDC_CLIENT_SECRET"),
	}
}

// configureUsersAuth reconciles the users collection auth options with the env config. It is
// idempotent and safe to run on every start. It never disables password login unless the
// provider is fully configured, so a typo cannot lock everyone out.
func configureUsersAuth(app core.App, c oidcConfig) error {
	users, err := app.FindCollectionByNameOrId("users")
	if err != nil {
		return err
	}
	ready := c.Enable && c.ClientID != "" && c.ClientSecret != ""
	if (c.Enable || c.Only) && !ready {
		log.Print("oidc: OIDC_ENABLED/OIDC_ONLY set but client id/secret missing; leaving auth settings unchanged")
		return nil
	}
	if ready {
		users.OAuth2.Enabled = true
		users.OAuth2.Providers = []core.OAuth2ProviderConfig{{
			Name:         "oidc",
			DisplayName:  "Holy Grail",
			ClientId:     c.ClientID,
			ClientSecret: c.ClientSecret,
			AuthURL:      c.BaseURL + "/application/o/authorize/",
			TokenURL:     c.BaseURL + "/application/o/token/",
			UserInfoURL:  c.BaseURL + "/application/o/userinfo/",
			PKCE:         types.Pointer(true),
		}}
		users.OAuth2.MappedFields = core.OAuth2KnownFields{Name: "name"}
	}
	if ready && c.Only {
		users.PasswordAuth.Enabled = false
		users.CreateRule = types.Pointer(`@request.context = "oauth2"`)
	} else {
		users.PasswordAuth.Enabled = true
		users.CreateRule = types.Pointer("")
	}
	return app.Save(users)
}
```
Note: with neither flag set the function also resets `PasswordAuth` to enabled and `CreateRule` to open, which is the pre-change state; if that surprises on the very first deploy (nothing set yet) it is a no-op against the current DB. The compiler confirms the `core.OAuth2ProviderConfig` / `core.OAuth2KnownFields` field names for v0.39.1; fix names there if they differ.

- [ ] **Step 5: Wire it** in `main.go` inside `OnServe`, directly before the `uc` token-duration block:

```go
		if err := configureUsersAuth(app, loadOIDCConfig()); err != nil {
			log.Printf("oidc: %v", err)
		}
```

- [ ] **Step 6: Run all tests**

Run: `eval "$GOTEST" 2>&1 | tail -8`
Expected: `ok  loyaltycards-sync`. Fix expected status codes in the two API tests to what PocketBase really returns (not 200) if they differ.

- [ ] **Step 7: Commit**

```bash
cd /home/pi/Projects
git add Docker/LoyaltyCards-Sync/oidc.go Docker/LoyaltyCards-Sync/oidc_test.go Docker/LoyaltyCards-Sync/main.go
git commit -m "LoyaltyCards-Sync: reconcile Holy Grail OIDC provider and OIDC-only mode from env"
```

## Task 5: Deploy the backend in phase 2 (OIDC on, password still on)

**Files:**
- Modify: `Docker/LoyaltyCards-Sync/docker-compose.yaml`, `.env.example`, `.env` (gitignored)

- [ ] **Step 1: Compose**: under `loyalty-sync`, add to `environment:` and add `extra_hosts`:

```yaml
    environment:
      - PB_ADMIN_EMAIL=${PB_ADMIN_EMAIL}
      - PB_ADMIN_PASSWORD=${PB_ADMIN_PASSWORD}
      - PB_PUBLIC_URL=${PB_PUBLIC_URL}
      - OIDC_ENABLED=${OIDC_ENABLED:-false}
      - OIDC_ONLY=${OIDC_ONLY:-false}
      - OIDC_CLIENT_ID=${OIDC_CLIENT_ID}
      - OIDC_CLIENT_SECRET=${OIDC_CLIENT_SECRET}
    extra_hosts:
      - "sso.holy-grail.ch:192.168.1.2"
```

- [ ] **Step 2: Env.** `.env.example`: replace the `GOOGLE_CLIENT_ID=` line and its comment with

```
# Holy Grail (Authentik) sign-in. Client id/secret are written by Authentik/scripts/provision-admin-sso.py.
# OIDC_ENABLED=true adds the "oidc" provider (password login still works).
# OIDC_ONLY=true (needs OIDC_ENABLED) turns password login and open signup off.
# Shell recovery: set OIDC_ONLY=false, then `docker compose up -d`.
OIDC_ENABLED=false
OIDC_ONLY=false
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
```
In `.env`: remove the unused `GOOGLE_CLIENT_ID` line (`sed -i '/^GOOGLE_CLIENT_ID=/d' .env`), append `OIDC_ENABLED=true` and `OIDC_ONLY=false` (`printf 'OIDC_ENABLED=true\nOIDC_ONLY=false\n' >> .env`; the client id/secret lines are already there from Task 1).

- [ ] **Step 3: Rebuild and start**

```bash
cd /home/pi/Projects/Docker/LoyaltyCards-Sync && docker compose up -d --build 2>&1 | tail -3
sleep 5; docker logs loyalty-sync 2>&1 | tail -5
```
Expected: container running, no `oidc:` error line.

- [ ] **Step 4: Verify auth methods and Authentik reachability**

```bash
docker run --rm --network traefik_proxy curlimages/curl -s http://loyalty-sync:8090/api/collections/users/auth-methods \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('password',d['password']['enabled'],'providers',[p['name'] for p in d['oauth2']['providers']])"
docker exec loyalty-sync wget -qO- https://sso.holy-grail.ch/application/o/authorize/ -S 2>&1 | head -2
```
Expected: `password True providers ['oidc']` (Google gone); the wget shows an HTTP response from Authentik (any status, a TLS/DNS error means `extra_hosts` is wrong).

- [ ] **Step 5: Throwaway linking test is NOT possible without a browser login, so test the link logic with the Go suite**: add, in `oidc_test.go`, nothing more; instead rely on the user's first login (Task 7 step 3) and the backup from Task 0. (PocketBase's email auto-link and `email_verified` rule are upstream behaviour documented in the spec, section 2.2.)

- [ ] **Step 6: Commit**

```bash
cd /home/pi/Projects
git add Docker/LoyaltyCards-Sync/docker-compose.yaml Docker/LoyaltyCards-Sync/.env.example
git commit -m "LoyaltyCards-Sync: OIDC env wiring and sso extra_hosts (password login still on)"
```

## Task 6: PWA changes (TDD, PWA repo)

Work in `/home/pi/Documents/development/LoyaltyCards`; test: `npx vitest run`.

**Files:**
- Modify: `src/lib/auth/store.ts`, `src/lib/auth/store.test.ts`, `src/components/AccountSection.svelte`, `src/components/AccountSection.test.ts`, `src/App.svelte`, `e2e/auth.spec.ts`
- Check: `src/components/BackupBanner.svelte` (uses `isLoggedIn` only)

- [ ] **Step 1: Failing store tests.** In `src/lib/auth/store.test.ts` replace the import line and the `describe('auth store — login', ...)` block (and delete the `TOTP management` describe) with:

```ts
import { loginHolyGrail, completeOAuthLogin, oidcEnabled } from './store';

describe('auth store — Holy Grail login', () => {
  beforeEach(() => {
    authStore.clear(); authWithOAuth2Code.mockClear(); listAuthMethods.mockReset(); localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  const provider = { name: 'oidc', state: 'st', authURL: 'https://sso.example/authorize?x=1&redirect_uri=', codeVerifier: 'ver' };

  it('oidcEnabled is true only when the oidc provider is listed', async () => {
    listAuthMethods.mockResolvedValueOnce({ oauth2: { providers: [provider] } });
    expect(await oidcEnabled()).toBe(true);
    listAuthMethods.mockResolvedValueOnce({ oauth2: { providers: [{ name: 'google' }] } });
    expect(await oidcEnabled()).toBe(false);
    listAuthMethods.mockRejectedValueOnce(new Error('offline'));
    expect(await oidcEnabled()).toBe(false);
  });

  it('loginHolyGrail stores PKCE state and redirect url before leaving', async () => {
    listAuthMethods.mockResolvedValueOnce({ oauth2: { providers: [provider] } });
    const assign = vi.fn();
    vi.stubGlobal('location', { origin: 'https://app.example', search: '', pathname: '/', set href(v: string) { assign(v); } });
    await loginHolyGrail();
    vi.unstubAllGlobals();
    const pending = JSON.parse(localStorage.getItem('pb_oauth_pending')!);
    expect(pending).toMatchObject({ provider: 'oidc', codeVerifier: 'ver', state: 'st', redirectUrl: 'https://app.example/' });
    expect(assign).toHaveBeenCalledWith('https://sso.example/authorize?x=1&redirect_uri=https://app.example/');
  });

  it('loginHolyGrail throws when the provider is not configured', async () => {
    listAuthMethods.mockResolvedValueOnce({ oauth2: { providers: [] } });
    await expect(loginHolyGrail()).rejects.toThrow(/not available/i);
  });

  it('completeOAuthLogin exchanges the code and strips the params', async () => {
    localStorage.setItem('pb_oauth_pending', JSON.stringify({ provider: 'oidc', codeVerifier: 'ver', state: 'st', redirectUrl: 'https://app.example/' }));
    window.history.replaceState({}, '', '/?code=abc&state=st');
    expect(await completeOAuthLogin()).toBe(true);
    expect(authWithOAuth2Code).toHaveBeenCalledWith('oidc', 'abc', 'ver', 'https://app.example/');
    expect(window.location.search).toBe('');
    expect(localStorage.getItem('pb_oauth_pending')).toBeNull();
  });

  it('completeOAuthLogin rejects a state mismatch without exchanging', async () => {
    localStorage.setItem('pb_oauth_pending', JSON.stringify({ provider: 'oidc', codeVerifier: 'ver', state: 'st', redirectUrl: 'https://app.example/' }));
    window.history.replaceState({}, '', '/?code=abc&state=OTHER');
    await expect(completeOAuthLogin()).rejects.toThrow(/state/i);
    expect(authWithOAuth2Code).not.toHaveBeenCalled();
  });

  it('completeOAuthLogin does nothing without a code', async () => {
    expect(await completeOAuthLogin()).toBe(false);
  });
});
```
Keep the existing `refreshSession` / `logout` / `account` tests that are above line 70 (inspect the file; remove only Google/password/TOTP ones).

- [ ] **Step 2: Run to confirm failure**

Run: `npx vitest run src/lib/auth/store.test.ts 2>&1 | tail -15`
Expected: failures: `loginHolyGrail is not a function` (and similar).

- [ ] **Step 3: Implement in `store.ts`.** Replace the whole file body below `refreshSession`/`logout` as follows (keep `Account`, `account`, `isLoggedIn`, `refreshSession`, `logout`, but drop `totpEnabled` from `Account` and `currentRecord`):

```ts
export interface Account { id: string; email: string; username?: string; }

function currentRecord(): Account | null {
  const r = pb.authStore.record as any;
  return r ? { id: r.id, email: r.email, username: r.username } : null;
}
```
and after `logout()`:

```ts
const OAUTH_PENDING = 'pb_oauth_pending';
const PROVIDER = 'oidc'; // PocketBase provider name for Holy Grail (Authentik)

type ProviderInfo = { name: string; state: string; authURL: string; codeVerifier: string };

async function listProviders(): Promise<ProviderInfo[]> {
  const m = await pb.collection(USERS).listAuthMethods();
  return ((m as { oauth2?: { providers?: ProviderInfo[] } }).oauth2?.providers) ?? [];
}

// The callback Authentik returns the user to: the PWA origin. Must exactly match the redirect
// URI registered on the Authentik application (https://loyalty-cards.holy-grail.ch/).
function oauthRedirectUrl(): string {
  return window.location.origin + '/';
}

/** Whether the Holy Grail provider is configured on the backend (UI hides the button if not). */
export async function oidcEnabled(): Promise<boolean> {
  try { return (await listProviders()).some((p) => p?.name === PROVIDER); } catch { return false; }
}

/** Start Holy Grail sign-in with a full-page redirect (reliable in installed PWAs, unlike
 *  popups). PKCE verifier + state go to localStorage so whichever context the redirect returns
 *  to can complete the exchange. */
export async function loginHolyGrail(): Promise<void> {
  const provider = (await listProviders()).find((p) => p.name === PROVIDER);
  if (!provider) throw new Error('Holy Grail sign-in is not available');
  const redirectUrl = oauthRedirectUrl();
  localStorage.setItem(OAUTH_PENDING, JSON.stringify({
    provider: provider.name, codeVerifier: provider.codeVerifier, state: provider.state, redirectUrl,
  }));
  // PocketBase's authURL ends with `redirect_uri=`; append our callback.
  window.location.href = provider.authURL + redirectUrl;
}

/** If the current URL carries an OAuth `code`, complete the login. Returns true if it handled a
 *  callback. Call once at app startup. */
export async function completeOAuthLogin(): Promise<boolean> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const state = params.get('state');
  const raw = localStorage.getItem(OAUTH_PENDING);
  if (!code || !raw) return false;
  localStorage.removeItem(OAUTH_PENDING);
  const saved = JSON.parse(raw) as { provider: string; codeVerifier: string; state: string; redirectUrl: string };
  try {
    if (state !== saved.state) throw new Error('OAuth state mismatch');
    await pb.collection(USERS).authWithOAuth2Code(saved.provider, code, saved.codeVerifier, saved.redirectUrl);
  } finally {
    // strip the OAuth params so a refresh doesn't retry a consumed code
    window.history.replaceState({}, '', window.location.pathname);
  }
  return true;
}
```
Delete `totpRequired`, `loginPassword`, `loginGoogle`, `completeGoogleLogin`, `googleLinked`, `refreshAccount`, `googleEnabled`, `signup`, `TotpSetup`, `startTotp`, `confirmTotp`, `disableTotp`. Check other users: `grep -rn "refreshAccount\|googleLinked\|totpEnabled" src` and fix any leftovers (`sync/*` import only `pb`/`USERS`/`account` per the earlier grep; verify).

- [ ] **Step 4: Run store tests**

Run: `npx vitest run src/lib/auth/store.test.ts 2>&1 | tail -8`
Expected: all pass.

- [ ] **Step 5: Failing component tests.** Replace `src/components/AccountSection.test.ts` with:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';

const { mockAccount, mockIsLoggedIn, mockLoginHolyGrail, mockLogout, mockOidcEnabled } = vi.hoisted(() => {
  function makeStore<T>(init: T) {
    let val = init;
    const subs: Array<(v: T) => void> = [];
    return {
      subscribe(fn: (v: T) => void) { fn(val); subs.push(fn); return () => { subs.splice(subs.indexOf(fn), 1); }; },
      set(v: T) { val = v; subs.forEach(fn => fn(v)); },
    };
  }
  return {
    mockAccount: makeStore<any>(null),
    mockIsLoggedIn: makeStore<boolean>(false),
    mockLoginHolyGrail: vi.fn().mockResolvedValue(undefined),
    mockLogout: vi.fn(),
    mockOidcEnabled: vi.fn().mockResolvedValue(true),
  };
});

vi.mock('../lib/auth/store', () => ({
  account: mockAccount, isLoggedIn: mockIsLoggedIn,
  loginHolyGrail: mockLoginHolyGrail, logout: mockLogout, oidcEnabled: mockOidcEnabled,
}));

import AccountSection from './AccountSection.svelte';

beforeEach(() => {
  mockAccount.set(null); mockIsLoggedIn.set(false);
  mockLoginHolyGrail.mockClear(); mockLogout.mockClear();
  mockOidcEnabled.mockResolvedValue(true);
});

describe('AccountSection', () => {
  it('shows only the Holy Grail button when logged out (no password form)', async () => {
    render(AccountSection);
    expect(await screen.findByText(/Sign in with Holy Grail/i)).toBeTruthy();
    expect(screen.queryByPlaceholderText(/password/i)).toBeNull();
    expect(screen.queryByPlaceholderText(/email/i)).toBeNull();
    expect(screen.queryByText(/Create an account/i)).toBeNull();
  });

  it('starts the redirect login on click', async () => {
    render(AccountSection);
    await fireEvent.click(await screen.findByText(/Sign in with Holy Grail/i));
    expect(mockLoginHolyGrail).toHaveBeenCalledTimes(1);
  });

  it('shows an error when the provider is unavailable', async () => {
    mockOidcEnabled.mockResolvedValue(false);
    render(AccountSection);
    expect(await screen.findByText(/unavailable/i)).toBeTruthy();
  });

  it('shows the account and logs out when signed in', async () => {
    mockAccount.set({ id: 'u1', email: 'me@example.com' });
    mockIsLoggedIn.set(true);
    render(AccountSection);
    expect(screen.getByText('me@example.com')).toBeTruthy();
    await fireEvent.click(screen.getByText(/Log out/i));
    expect(mockLogout).toHaveBeenCalled();
  });
});
```

- [ ] **Step 6: Run to confirm failure**

Run: `npx vitest run src/components/AccountSection.test.ts 2>&1 | tail -12`
Expected: FAIL (old component still imports removed store members).

- [ ] **Step 7: Implement `AccountSection.svelte`** (replace the file; keep the existing style rules for `.lbl .btn .btn.primary .who .hint .err` and drop the unused ones):

```svelte
<script lang="ts">
  import { account, isLoggedIn, loginHolyGrail, logout, oidcEnabled } from '../lib/auth/store';

  let err = $state('');
  let available = $state<boolean | null>(null); // null = checking
  oidcEnabled().then((v) => { available = v; });

  async function signIn() {
    err = '';
    try { await loginHolyGrail(); }
    catch (e) { err = 'Sign-in failed: ' + ((e as Error).message || 'unavailable'); }
  }
</script>

<section>
  <span class="lbl">Account</span>

  {#if $isLoggedIn}
    <div class="who">{$account?.email}</div>
    <p class="hint">Signed in with Holy Grail. Two-factor authentication is handled there.</p>
    <button class="btn" onclick={logout}>Log out</button>
  {:else}
    {#if available === false}<p class="err">Sign-in is unavailable right now (offline or server down).</p>{/if}
    {#if err}<p class="err">{err}</p>{/if}
    <button class="btn primary" onclick={signIn} disabled={available === false}>Sign in with Holy Grail</button>
  {/if}
</section>

<style>
  section{display:flex;flex-direction:column;gap:8px}
  .lbl{color:#9a9aa6;font-size:13px;margin:0 2px 2px}
  .btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:13px;border-radius:12px;
    border:1px solid #33333a;background:#1a1a20;color:#e6e6ec;font-size:15px;cursor:pointer}
  .btn.primary{background:#2a6df4;border-color:#2a6df4;color:#fff;font-weight:600}
  .btn.primary:disabled{opacity:.5;cursor:default}
  .who{font-size:16px;font-weight:600}
  .hint{color:#9a9aa6;font-size:13px;margin:0}
  .err{color:#ff6b6b;font-size:14px;margin:0}
</style>
```
The click handler is not `async`-first in Safari terms because the redirect is a plain navigation, not a popup.

- [ ] **Step 8: App startup** in `src/App.svelte`: change the import to `import { refreshSession, completeOAuthLogin } from './lib/auth/store';` and the call to `await completeOAuthLogin();` (update the comment "Google" -> "Holy Grail").

- [ ] **Step 9: Update the e2e spec** `e2e/auth.spec.ts` to the new flow: mock `**/api/collections/users/auth-methods` returning `{password:{enabled:false},oauth2:{enabled:true,providers:[{name:'oidc',state:'st',authURL:'http://localhost:4173/__sso?redirect_uri=',codeVerifier:'v'}]}}`, route `**/__sso*` to fulfil a 302 back to `/?code=abc&state=st`, route `**/api/collections/users/auth-with-oauth2` to return `{token:'tok',record:{id:'u1',email:'me@example.com'}}`, then: open Settings, click "Sign in with Holy Grail", expect `me@example.com` and "Log out" visible, expect no password field. Also add an assertion `await expect(page.getByPlaceholder('password')).toHaveCount(0)`.

- [ ] **Step 10: Full suite and build**

```bash
npx vitest run 2>&1 | tail -6
npx playwright test e2e/auth.spec.ts 2>&1 | tail -6
VITE_LOGODEV_TOKEN=$(grep -h VITE_LOGODEV_TOKEN .env 2>/dev/null | cut -d= -f2) npm run build 2>&1 | tail -3
grep -c "index.html" dist/sw.js
```
Expected: all green; build ok; `dist/sw.js` mentions `index.html` (precache + navigation fallback, so `/?code=...` loads the shell). If the logo token is in a different place, follow `docs/RELEASING.md`.

- [ ] **Step 11: Commit**

```bash
git add src/lib/auth/store.ts src/lib/auth/store.test.ts src/components/AccountSection.svelte src/components/AccountSection.test.ts src/App.svelte e2e/auth.spec.ts
git commit -m "LoyaltyCards: Sign in with Holy Grail replaces email/password/TOTP/Google UI"
```

## Task 7: Release the PWA and the first real login (USER)

- [ ] **Step 1: Release per `docs/RELEASING.md`** (version bump commit `LoyaltyCards: bump version to X.Y.Z`, tag `vX.Y.Z`, push, Docker build with the logo.dev build arg, push image tag).

- [ ] **Step 2: Deploy**: set `IMAGE_TAG=X.Y.Z` in `/home/pi/Projects/Docker/LoyaltyCards/.env`, then `cd /home/pi/Projects/Docker/LoyaltyCards && docker compose up -d --pull always`. Check: `docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -w '%{http_code}\n' http://loyalty-cards:80/` -> `200`.

- [ ] **Step 3: USER does the first real login on the phone and on a desktop browser:** open the PWA, Settings, "Sign in with Holy Grail", pass Authentik MFA, return to the app. Check: the 5 existing cards are present (the owner's record was linked by email) and a new card syncs to a second device. In the installed PWA (Android) confirm the return lands in the app, not a browser tab. If the cards are missing: the user was created as a new empty record (linking failed). Stop, restore from the Task 0 backup (`docker compose down; restore tar into the volume; up -d`) and check the `email_verified` mapping on the `loyalty-cards` provider (Task 1 Step 5).

- [ ] **Step 4: Confirm to the agent that it worked.** Do not continue before this.

## Task 8: Turn password login off (OIDC only)

- [ ] **Step 1:** `cd /home/pi/Projects/Docker/LoyaltyCards-Sync && sed -i 's/^OIDC_ONLY=.*/OIDC_ONLY=true/' .env && docker compose up -d`

- [ ] **Step 2: Verify**

```bash
docker run --rm --network traefik_proxy curlimages/curl -s http://loyalty-sync:8090/api/collections/users/auth-methods \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('password',d['password']['enabled'],'providers',[p['name'] for p in d['oauth2']['providers']])"
docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' \
  -d '{"identity":"x@example.com","password":"x"}' http://loyalty-sync:8090/api/collections/users/auth-with-password
docker run --rm --network traefik_proxy curlimages/curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' \
  -d '{"email":"x@example.com","password":"password123","passwordConfirm":"password123"}' http://loyalty-sync:8090/api/collections/users/records
```
Expected: `password False providers ['oidc']`; `403`; a 4xx (not 200). USER: reopen the app (existing session still valid) and log out/in once to confirm Holy Grail still works.

- [ ] **Step 3 (Q3):** if the user said delete the unverified, data-less second user: in a one-off shell, `docker exec loyalty-sync /pb/loyaltycards-sync` has no user-delete command, so use the dashboard during Task 9's maintenance window, or leave it (it cannot log in).

- [ ] **Step 4: Rollback if needed:** `sed -i 's/^OIDC_ONLY=.*/OIDC_ONLY=false/' .env && docker compose up -d` (password login and open signup rule return; verified by `TestOIDCRollbackRestoresPassword`).

## Task 9: Lock down the PocketBase superuser

**Files:**
- Modify: `Docker/Traefik/traefik/dynamic/loyalty-sync.yml` (and the copy kept in `Docker/LoyaltyCards-Sync/deploy/loyalty-sync.yml` if it is meant to mirror it; keep both identical)

- [ ] **Step 1: Add the deny router and middleware**

```yaml
    # PocketBase superusers can only use a password, so they must not be reachable from any
    # network (SSO-only policy). Everything under these paths is 403. Admin work: see
    # Docker/LoyaltyCards-Sync/README.md "Admin access". ID pbc_3142635823 is the fixed
    # _superusers collection id.
    loyalty-sync-admin-denied:
      rule: >-
        Host(`loyalty-sync.holy-grail.ch`) && (PathPrefix(`/_/`) ||
        PathPrefix(`/api/collections/_superusers`) ||
        PathPrefix(`/api/collections/pbc_3142635823`))
      priority: 100
      entryPoints: ["websecure"]
      service: loyalty-sync
      middlewares:
        - loyalty-sync-deny
      tls:
        certResolver: cloudflare
```
under `routers:` and, under `middlewares:`:

```yaml
    loyalty-sync-deny:
      ipAllowList:
        sourceRange:
          - "192.0.2.1/32"   # TEST-NET-1: matches nobody, so every request gets 403
```
(same trick as `nextcloud-deny`). Traefik hot-reloads file-provider changes.

- [ ] **Step 2: Verify locally through Traefik** (never from the public side):

```bash
for p in '/_/' '/api/collections/_superusers/auth-with-password' '/api/collections/pbc_3142635823/auth-with-password' '/api/health' '/api/collections/users/auth-methods'; do
  printf '%s ' "$p"; curl -sk --resolve loyalty-sync.holy-grail.ch:443:127.0.0.1 -o /dev/null -w '%{http_code}\n' "https://loyalty-sync.holy-grail.ch$p"
done
```
Expected: `/_/` 403, both superuser paths 403, `/api/health` 200, `auth-methods` 200. (POST variants of the superuser path also 403 by the same router.)

- [ ] **Step 3: Defence in depth: `superuser ips`**

```bash
docker exec loyalty-sync /pb/loyaltycards-sync superuser ips 127.0.0.1/32
docker exec loyalty-sync /pb/loyaltycards-sync superuser ips
```
Expected: the second call prints the configured list `127.0.0.1/32`. (Clear it with the call `superuser ips` and no address when the dashboard is needed; syntax per `pocketbase superuser --help`, confirm with `docker exec loyalty-sync /pb/loyaltycards-sync superuser ips --help`.)

- [ ] **Step 4: Document the admin procedure** in `Docker/LoyaltyCards-Sync/README.md` ("Admin access"): (a) reset or create a superuser: `docker exec loyalty-sync /pb/loyaltycards-sync superuser upsert <email> <password>`; (b) dashboard: comment the `loyalty-sync-admin-denied` router out (Traefik reloads), `docker exec loyalty-sync /pb/loyaltycards-sync superuser ips` (clear) and use it from LAN/VPN only for the minutes needed, then restore both; or use an ssh tunnel to the container IP (`ssh -L 8090:$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' loyalty-sync):8090 fastpi`) while the Traefik router is irrelevant (it is bypassed), after clearing `superuser ips`. Also change the stored superuser password in `.env` to a long random value (`openssl rand -base64 33`, written with a heredoc, never echoed).

- [ ] **Step 5: Commit**

```bash
cd /home/pi/Projects
git add Docker/Traefik/traefik/dynamic/loyalty-sync.yml Docker/LoyaltyCards-Sync/deploy/loyalty-sync.yml Docker/LoyaltyCards-Sync/README.md
git commit -m "Traefik: deny PocketBase superuser endpoints and dashboard for loyalty-sync"
```
Rollback: delete the router and middleware; `superuser ips` with no address.

## Task 10: Old sessions and Google leftovers (Q4)

- [ ] **Step 1 (only if the user chose to invalidate sessions):** rotate the users collection token secret, which makes every existing PWA token invalid; devices then show the Holy Grail button once. In the dashboard (Task 9 Step 4 (b) window): Collections, users, Options, Tokens, "Invalidate all auth tokens", or the CLI-less alternative of a one-off Go migration; prefer the dashboard. Verify: an old token returns 401 on `/api/collections/users/auth-refresh`.
- [ ] **Step 2: USER:** delete or rotate the Google Cloud OAuth client whose secret was previously stored in PocketBase (the provider was already removed by Task 5, but the secret was exposed in tool output). Nothing in this repo references it any more (`grep -rn GOOGLE Docker/LoyaltyCards-Sync` must be empty).
- [ ] **Step 3: Rotate the Stonks `SESSION_SECRET`** only if the user wants to end all existing 30-day Stonks sessions (they must sign in again).

## Task 11: Remove the dead TOTP code (after a few days of stable use)

**Files:**
- Delete: `Docker/LoyaltyCards-Sync/totp.go`, `totp_test.go`, `guards.go`
- Modify: `Docker/LoyaltyCards-Sync/main.go` (remove `registerAuthGuards(app)`, `registerTOTPRoutes(se)`, the two rate-limit rules), `go.mod`/`go.sum` (`go mod tidy` inside the Docker image)

- [ ] **Step 1:** `git rm` the three files; edit `main.go` to drop the calls and keep only `Rules` entries still needed (none). Keep `rules_test.go`.
- [ ] **Step 2:** `docker run --rm -v "$PWD":/src -w /src golang:1.25-alpine sh -c 'go mod tidy && go test ./... -count=1'` -> `ok`.
- [ ] **Step 3:** `docker compose up -d --build`; re-run the Task 8 Step 2 checks; `docker run ... http://loyalty-sync:8090/api/loyalty/totp/required` returns `404`.
- [ ] **Step 4:** Commit `LoyaltyCards-Sync: remove unused TOTP routes and password guard (SSO only)`. The `totp*` fields stay in the schema (Q6).

## Task 12: Documentation

- [ ] `Docker/Authentik/README.md`: add the two apps to the SSO table (URLs, method, shell recovery: `OIDC_ONLY=false` for LoyaltyCards; `AUTH_MODE=password` for Stonks; superuser via CLI); mention group `loyalty-users`.
- [ ] `Docker/Authentik/docs/superpowers/specs/2026-10-19-sso-only-inventory.md`: update the LoyaltyCards and Stonks rows to "done" with the date.
- [ ] `Docker/LoyaltyCards-Sync/README.md` and `deploy/DEPLOY.md`/`SECURITY-FOLLOWUPS.md`: remove the "open signup" and "public `/_/`" items (resolved); `Docker/Stonks/README.md` and the code repo `README.md`: replace the "Single-user login (argon2...)" line with the AUTH_MODE description.
- [ ] `Docker/_global/checklist.md`: no checkmark changes (user-owned).
- [ ] Commit: `Authentik: document Holy Grail login for LoyaltyCards and Stonks` (own hunks only).

## Final verification checklist

- [ ] Stonks: `POST /login` 404, `/holdings` redirects to `/auth/login`, user logged in via Holy Grail, Telegram `/portfolio` answers.
- [ ] LoyaltyCards: auth-methods shows `password False`, only `oidc`; password endpoint 403; REST signup refused; superuser paths 403 via Traefik; `superuser ips` set; 5 cards present after SSO login; offline open of the installed PWA still shows cards.
- [ ] Recovery tested once on the shell: Stonks `AUTH_MODE=password` (then back to `oidc`), LoyaltyCards `OIDC_ONLY=false` (then back to `true`).
- [ ] `git status` in all three repos shows only unrelated, pre-existing changes; no `.env` in any commit (`git log -p --all -S'OIDC_CLIENT_SECRET=' -- '*.example'` shows only blank values).
