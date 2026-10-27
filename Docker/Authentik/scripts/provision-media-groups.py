# Idempotent media-stack groups and which group may open which app (Application group bindings).
# Run (twice is fine):
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-media-groups.py
#
# Three independent groups, no parent nesting (a parent would let streaming-admins inherit Jellyfin,
# while Jellyfin's OIDC plugin only sees direct groups in the token, so the two would disagree):
#   streaming-users      Jellyfin (+ wake page) and Tracker   (every invitee, enrollment stage)
#   streaming-requesters Requests (Seerr), Audiobook requests  (by hand)
#   streaming-admins     download apps + Jellyfin admin       (by hand)
# Only bindings of MANAGED groups on the apps below are changed; other groups, policies and apps stay.
# Owner memberships follow the admin split (docs/admin-split-plan.md): only the users in MEMBERS and only MEMBER_MANAGED groups; cloud-* stay by hand (phase 3).
# REMOVE_EXTRA = False (phase 2a) only adds; True (phase 2b) also takes MEMBER_MANAGED groups not listed away.
# homelab-users (owner 2026-10-27): the everyday account's Home Assistant (user role) and Grafana (Viewer); bound next to homelab-admins, add-only.
GROUPS = ("streaming-users", "streaming-requesters", "streaming-admins")
MANAGED = set(GROUPS) | {"homelab-admins"}
HOMELAB_USERS = "homelab-users"
MEMBERS = {
    "tomigorn": {"streaming-users", "streaming-requesters", HOMELAB_USERS},
    "tomigorn-admin": {"homelab-admins", "streaming-admins", "streaming-users", "streaming-requesters", "authentik Admins"},
}
MEMBER_MANAGED = set(GROUPS) | {"homelab-admins", "authentik Admins", HOMELAB_USERS}
REMOVE_EXTRA = False

APP_GROUP = {
    "jellyfin": "streaming-users",
    "jellyfin-wake": "streaming-users",
    "tracker": "streaming-users",
    "tracker-login": "streaming-users",
    "requests": "streaming-requesters",
    "requests-login": "streaming-requesters",
    "radarr": "streaming-admins",
    "sonarr": "streaming-admins",
    "prowlarr": "streaming-admins",
    "bazarr": "streaming-admins",
    "sabnzbd": "streaming-admins",
    "qbittorrent": "streaming-admins",
    # fastpi audiobook downloaders (provision-audiobook-downloads-sso.py).
    "qbittorrent-audiobooks": "streaming-admins",
    "sabnzbd-audiobooks": "streaming-admins",
    "prowlarr-audiobooks": "streaming-admins",
    # AudioBookRequest (provision-books-sso.py).
    "books": "streaming-requesters",
    "books-login": "streaming-requesters",
    # Image versions of every host: homelab inventory, not a media tool.
    "cup": "homelab-admins",
}
USER_APPS = {"home-assistant": HOMELAB_USERS, "grafana": HOMELAB_USERS}


def plan(current):
    """current: slug -> bound group names. Returns slug -> (groups to bind, managed groups to unbind) for apps that differ."""
    changes = {}
    for slug, group in APP_GROUP.items():
        bound = current.get(slug, set()) & MANAGED
        add, remove = {group} - bound, bound - {group}
        if add or remove:
            changes[slug] = (add, remove)
    return changes


def user_binding_plan(current):
    """current: slug -> bound group names. Returns the USER_APPS slugs still missing their group binding."""
    return {slug for slug, group in USER_APPS.items() if group not in current.get(slug, set())}


def membership_plan(current, remove):
    """current: username -> group names. Returns username -> (groups to add, groups to remove) for MEMBERS that differ."""
    changes = {}
    for user, want in MEMBERS.items():
        have = current.get(user, set()) & MEMBER_MANAGED
        add, extra = want - have, (have - want if remove else set())
        if add or extra:
            changes[user] = (add, extra)
    return changes


def main():
    from authentik.core.models import Application, Group, User
    from authentik.policies.models import PolicyBinding

    for name in (*GROUPS, HOMELAB_USERS):
        group, created = Group.objects.get_or_create(name=name)
        if group.parents.exists():
            print(f"CHANGE {name}: parents {[p.name for p in group.parents.all()]} removed")
            group.parents.clear()
        if created:
            print(f"CHANGE group {name} created")

    if missing := MEMBER_MANAGED - set(Group.objects.filter(name__in=MEMBER_MANAGED).values_list("name", flat=True)):
        raise SystemExit(f"missing groups: {sorted(missing)}")
    users = {u.username: u for u in User.objects.filter(username__in=MEMBERS)}
    if set(MEMBERS) - set(users):
        raise SystemExit(f"missing users: {sorted(set(MEMBERS) - set(users))} (run provision-admin-account.py first)")
    current = {name: {g.name for g in u.groups.all()} for name, u in users.items()}
    for name, (add, extra) in sorted(membership_plan(current, REMOVE_EXTRA).items()):
        user = users[name]
        for group in Group.objects.filter(name__in=add):
            group.users.add(user)
        for group in Group.objects.filter(name__in=extra):
            group.users.remove(user)
        print(f"CHANGE {name}: +{sorted(add)} -{sorted(extra)}")

    apps = {a.slug: a for a in Application.objects.filter(slug__in={*APP_GROUP, *USER_APPS})}
    missing = {*APP_GROUP, *USER_APPS} - set(apps)
    if missing:
        raise SystemExit(f"missing applications: {sorted(missing)} (run the other provisioning scripts first)")
    current = {slug: {b.group.name for b in PolicyBinding.objects.filter(target=app, group__isnull=False)}
               for slug, app in apps.items()}
    for slug in sorted(user_binding_plan(current)):
        PolicyBinding.objects.create(target=apps[slug], group=Group.objects.get(name=USER_APPS[slug]), order=10)
        print(f"CHANGE {slug}: +['{USER_APPS[slug]}']")
    for slug, (add, remove) in sorted(plan(current).items()):
        app = apps[slug]
        for name in add:
            PolicyBinding.objects.create(target=app, group=Group.objects.get(name=name), order=0)
        PolicyBinding.objects.filter(target=app, group__name__in=remove).delete()
        print(f"CHANGE {slug}: +{sorted(add)} -{sorted(remove)}")
    print("OK media groups")


try:
    import authentik  # noqa: F401  (absent in the unit tests)
except ImportError:
    pass
else:
    main()
