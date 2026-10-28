"""Minimal Authentik REST client (stdlib only)."""
import json
import urllib.error
import urllib.request


MAX_PAGES = 100


class AuthentikError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


# A redirect to the login page answers 200; only Authentik's own 200 counts.
_session_opener = urllib.request.build_opener(_NoRedirect)


class Client:
    def __init__(self, base_url, token, timeout=10, opener=urllib.request.urlopen, session_opener=None):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._open = opener  # injectable for tests
        self._open_session = session_opener or _session_opener.open

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
            nxt = (data.get("pagination") or {}).get("next") or 0
            page = nxt if nxt > page and nxt <= MAX_PAGES else 0
        return users

    def get_user(self, pk):
        return self._call("GET", f"/api/v3/core/users/{int(pk)}/")

    def set_attributes(self, pk, attributes):
        self._call("PATCH", f"/api/v3/core/users/{int(pk)}/", {"attributes": attributes})

    def session_valid(self, session_cookie):
        """Is this authentik_session cookie a live login? Asks as the browser, never with our token."""
        if not session_cookie:
            return False
        req = urllib.request.Request(self.base + "/api/v3/core/users/me/", method="GET", headers={
            "Cookie": f"authentik_session={session_cookie}", "Accept": "application/json"})
        try:
            with self._open_session(req, timeout=self.timeout) as r:
                return getattr(r, "status", 200) == 200
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308, 401, 403):
                return False
            raise AuthentikError(f"GET users/me: HTTP {e.code}") from None
        except Exception as e:
            raise AuthentikError(f"GET users/me: {type(e).__name__}") from None
