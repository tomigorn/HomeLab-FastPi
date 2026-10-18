"""Minimal Authentik REST client (stdlib only)."""
import json
import urllib.request


MAX_PAGES = 100


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
            nxt = (data.get("pagination") or {}).get("next") or 0
            page = nxt if nxt > page and nxt <= MAX_PAGES else 0
        return users

    def get_user(self, pk):
        return self._call("GET", f"/api/v3/core/users/{int(pk)}/")

    def set_attributes(self, pk, attributes):
        self._call("PATCH", f"/api/v3/core/users/{int(pk)}/", {"attributes": attributes})
