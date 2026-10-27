# Authentik customizations (Docker/CUSTOMIZATIONS.md "Authentik"): one read-only ak shell pass, then file and host checks.
AKD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Authentik" && pwd)
if want server worker; then
  AKSPEC=$(python3 - "$AKD/scripts/dashboard-look.py" <<'PY'
import ast, hashlib, json, sys
ns = {}
for n in ast.parse(open(sys.argv[1]).read()).body:
    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) in {"BEEFY", "TOWER", "APPS", "HIDDEN", "CUSTOM_CSS"}:
        ns[n.targets[0].id] = eval(compile(ast.Expression(n.value), "x", "eval"), {"__builtins__": {}}, ns)
print(repr(json.dumps({"css": hashlib.md5(ns["CUSTOM_CSS"].encode()).hexdigest(), "apps": {k: v[:2] for k, v in ns["APPS"].items()}, "hidden": ns["HIDDEN"]})))
PY
)
  AK=$({ echo "SPEC = $AKSPEC"; cat <<'PY'; } | docker exec -i authentik-server ak shell 2>/dev/null | sed -n 's/^@//p'
import hashlib, json
from authentik.brands.models import Brand
from authentik.core.models import Application, Group, User
from authentik.events.models import NotificationRule
from authentik.flows.models import Flow, FlowStageBinding
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.oauth2.models import OAuth2Provider, ScopeMapping
from authentik.providers.proxy.models import ProxyProvider
from authentik.rbac.models import Role
from authentik.stages.user_login.models import UserLoginStage
from authentik.stages.user_write.models import UserWriteStage
from authentik.tenants.models import Tenant
want = json.loads(SPEC)
def out(k, v): print(f"@{k}={v}")
b = Brand.objects.get(default=True)
out("brand", f"{b.branding_title}|logo={'holy-grail' in str(b.branding_logo)}|favicon={'holy-grail' in str(b.branding_favicon)}")
out("css", "match" if hashlib.md5((b.branding_custom_css or "").encode()).hexdigest() == want["css"] else "differs")
bad = [s for s, (g, d) in want["apps"].items() if not Application.objects.filter(slug=s, group=g, meta_description=d, meta_publisher="", meta_hide=False).exclude(meta_icon="").exists()]
out("apps", f"{len(want['apps']) - len(bad)}/{len(want['apps'])} {' '.join(bad)}")
bad = [s for s in want["hidden"] if not Application.objects.filter(slug=s, meta_hide=True).exists()]
out("hidden", f"{len(want['hidden']) - len(bad)}/{len(want['hidden'])} {' '.join(bad)}")
t = Flow.objects.filter(slug__in=["default-authentication-flow", "default-source-authentication", "default-source-enrollment", "initial-setup"])
out("flows", f"{t.count()} flows, authentik in title: {sum('authentik' in (f.title or '').lower() for f in t)}")
tn = Tenant.objects.get(schema_name="public")
out("footer", any("holy-grail.ch" in (l.get("href") or "") for l in (tn.footer_links or [])))
out("avatars", tn.avatars)
G = ["authentik Admins", "homelab-admins", "streaming-users", "streaming-requesters", "streaming-admins", "cloud-users", "cloud-admins"]
out("groups", f"{Group.objects.filter(name__in=G).count()}/{len(G)}")
BIND = {"homelab-admins": ["traefik-dashboard", "grafana", "portainer", "adguard", "wg-easy", "home-assistant", "claude-mockups", "vpn-status-beefy", "vpn-status-mouse", "cup", "dt", "dt-login"],
        "streaming-admins": ["qbittorrent-audiobooks", "sabnzbd-audiobooks", "prowlarr-audiobooks", "radarr", "sonarr", "prowlarr", "sabnzbd", "qbittorrent", "bazarr"],
        "streaming-requesters": ["books", "books-login", "requests", "requests-login"],
        "streaming-users": ["tracker", "tracker-login", "jellyfin"]}
for g, slugs in BIND.items():
    miss = [s for s in slugs if not PolicyBinding.objects.filter(target__in=Application.objects.filter(slug=s).values("pk"), group__name=g, enabled=True).exists()]
    out("bind-" + g, f"{len(slugs) - len(miss)}/{len(slugs)} {' '.join(miss)}")
def mapped(prov, name): return OAuth2Provider.objects.filter(name=prov, property_mappings__name=name).exists()
m = ScopeMapping.objects.filter(name="AudioBookRequest groups").first()
out("abr-groups", f"attached={mapped('books-login', 'AudioBookRequest groups')} claim={bool(m) and 'abr_groups' in m.expression and 'streaming-admins' in m.expression}")
out("wg-email", f"attached={mapped('wg-easy', 'wg-easy email (verified)')}")
a = Application.objects.filter(slug="audiobookshelf").first()
out("abs", f"profile={ScopeMapping.objects.filter(name='Audiobookshelf Profile').exists()} bound={bool(a) and PolicyBinding.objects.filter(target=a.pk, enabled=True).exists()}")
s = UserLoginStage.objects.get(name="default-authentication-login")
out("session", f"{s.session_duration} {s.remember_me_offset}")
short = sorted(p.name for p in ProxyProvider.objects.exclude(access_token_validity="hours=24"))
out("proxy-ttl", f"{ProxyProvider.objects.count() - len(short)}/{ProxyProvider.objects.count()} at 24h {' '.join(short)}")
w = UserWriteStage.objects.filter(name="invitation-enrollment-user-write-enrollment").first()
out("enroll", w.create_users_group.name if w and w.create_users_group else None)
out("notify", NotificationRule.objects.filter(name="notify-admins-user-created").exists())
f = FlowStageBinding.objects.filter(target__slug="enrollment", stage__name="enrollment-invite-warning").first()
out("invite", f"order={f.order if f else None}")
op = Outpost.objects.get(name="authentik Embedded Outpost")
miss = [p.name for p in ProxyProvider.objects.exclude(pk__in=op.providers.values("pk"))]
out("outpost", f"missing={len(miss)} {' '.join(miss)}")
u = User.objects.filter(username="avatar-picker").first()
out("avatar-sa", bool(u) and Role.objects.filter(name="avatar-picker", users=u).exists())
out("admin", User.objects.filter(username="tomigorn-admin", is_active=True).exists())
out("canary", ",".join(f"{x.is_active}" for x in User.objects.filter(username="canary-test")) or "none")
PY
)
  akv() { sed -n "s/^$1=//p" <<<"$AK" | head -1; }
  check authentik.image-pin '/server:2026\.[0-9]+\.[0-9]+$' "$(docker inspect -f '{{.Config.Image}}' authentik-server)"
  check authentik.brand '^Holy Grail\|logo=True\|favicon=True$' "$(akv brand)"
  check authentik.dashboard-css '^match$' "$(akv css)"
  check authentik.dashboard-apps '^([0-9]+)/\1 $' "$(akv apps)"
  check authentik.dashboard-hidden '^([0-9]+)/\1 $' "$(akv hidden)"
  check authentik.flow-titles '^[1-9] flows, authentik in title: 0$' "$(akv flows)"
  check authentik.footer '^True$' "$(akv footer)"
  check authentik.avatar-source '^attributes\.avatar,initials$' "$(akv avatars)"
  check authentik.groups '^7/7$' "$(akv groups)"
  check authentik.bind-homelab-admins '^([0-9]+)/\1 $' "$(akv bind-homelab-admins)"
  check authentik.bind-streaming-admins '^([0-9]+)/\1 $' "$(akv bind-streaming-admins)"
  check authentik.bind-streaming-requesters '^([0-9]+)/\1 $' "$(akv bind-streaming-requesters)"
  check authentik.bind-streaming-users '^([0-9]+)/\1 $' "$(akv bind-streaming-users)"
  check authentik.abr-groups '^attached=True claim=True$' "$(akv abr-groups)"
  check authentik.wg-easy-email '^attached=True$' "$(akv wg-email)"
  check authentik.abs-oidc '^profile=True bound=True$' "$(akv abs)"
  check authentik.session-ttl '^days=1 days=29$' "$(akv session)"
  check authentik.proxy-ttl '^([0-9]+)/\1 at 24h $' "$(akv proxy-ttl)"
  check authentik.enroll-group '^streaming-users$' "$(akv enroll)"
  check authentik.notify-new-user '^True$' "$(akv notify)"
  check authentik.invite-warning '^order=1$' "$(akv invite)"
  check authentik.outpost-providers '^missing=0 $' "$(akv outpost)"
  check authentik.avatar-picker-sa '^True$' "$(akv avatar-sa)"
  check authentik.admin-account '^True$' "$(akv admin)"
  check authentik.canary-off '^False$' "$(akv canary)"
  check authentik.trusted-proxy '^127\.0\.0\.0/8,::1/128,10\.24\.15\.3/32$' "$(docker exec authentik-server printenv AUTHENTIK_LISTEN__TRUSTED_PROXY_CIDRS)"
  check authentik.email-templates '^ok$' "$(docker exec authentik-server sh -c 'test -s /templates/email/base.html && test -s /templates/email/new_account.html && test -s /templates/email/password_reset.html' && echo ok)"
  check authentik.brand-mounts '^ok ok$' "$(for c in authentik-server authentik-worker; do docker exec $c sh -c 'test -s /web/icons/icon_left_brand.png && test -n "$(ls /home/pi/Projects/HolyGrail-Branding/icons)"' && echo ok; done | xargs)"
  check authentik.app-icons '^[1-9][0-9]+$' "$(ls "$AKD/data/media/public/apps" 2>/dev/null | grep -c '\.svg$')"
  check authentik.login-page '^200$' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' https://sso.holy-grail.ch/if/flow/default-authentication-flow/)"
fi
check authentik.app-cache-timer '^active$' "$(systemctl is-active authentik-app-cache.timer)"
