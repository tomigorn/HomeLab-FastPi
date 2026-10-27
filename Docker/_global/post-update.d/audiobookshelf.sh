# Audiobookshelf customizations (Docker/CUSTOMIZATIONS.md "audiobookshelf"): auth settings and service users live in ABS's DB, read read-only.
ABSD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../audiobookshelf" && pwd)
absq() { python3 - "$ABSD/audiobookshelf/config/absdatabase.sqlite" "$1" <<'PY' 2>&1 | tail -1
import json, sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
s = json.loads(c.execute("select value from settings where key='server-settings'").fetchone()[0])
u = {r[0]: (r[1], r[2], json.loads(r[3])) for r in c.execute("select username, type, isActive, permissions from users")}
p = lambda n: " ".join(f"{k}={u[n][2][k]}" for k in ("download", "update", "delete", "upload")) if n in u else "missing"
print(eval(sys.argv[2]))
PY
}
if want audiobookshelf; then
  check abs.oidc-only '^\[.openid.\] Login with Holy Grail$' "$(curl -s -m 8 https://audiobookshelf.holy-grail.ch/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["authMethods"], d["authFormData"]["authOpenIDButtonText"])' 2>&1)"
  check abs.oidc-settings '^True email groups https://sso\.holy-grail\.ch/application/o/audiobookshelf/$' "$(absq '" ".join(map(str, (s["authOpenIDAutoRegister"], s["authOpenIDMatchExistingBy"], s["authOpenIDGroupClaim"], s["authOpenIDIssuerURL"])))')"
  check abs.user-abr '^user True download=False update=False delete=False upload=False$' "$(absq '" ".join([u["abr"][0], str(bool(u["abr"][1])), p("abr")]) if "abr" in u else "missing"')"
  check abs.user-importer '^admin True download=False update=True delete=False upload=False$' "$(absq '" ".join([u["audiobook-importer"][0], str(bool(u["audiobook-importer"][1])), p("audiobook-importer")]) if "audiobook-importer" in u else "missing"')"
  check abs.root-single '^1$' "$(absq 'sum(1 for v in u.values() if v[0] == "root")')"
  check abs.libraries '^[3-9]$' "$(absq 'c.execute("select count(*) from libraries").fetchone()[0]')"
fi
