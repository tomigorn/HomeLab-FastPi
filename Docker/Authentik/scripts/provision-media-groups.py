# Idempotent media-stack groups and which group may open which app (Application group bindings).
# Run (twice is fine):
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-media-groups.py
#
# Three independent groups, no parent nesting (a parent would let streaming-admins inherit Jellyfin,
# while Jellyfin's OIDC plugin only sees direct groups in the token, so the two would disagree):
#   streaming-users      Jellyfin (+ wake page) and Tracker   (every invitee, enrollment stage)
#   streaming-requesters Requests (Seerr)                     (by hand)
#   streaming-admins     download apps + Jellyfin admin       (by hand)
# Only bindings of MANAGED groups on the apps below are changed; other groups, policies and apps stay.
GROUPS = ("streaming-users", "streaming-requesters", "streaming-admins")
OWNER = "tomigorn"
MANAGED = set(GROUPS) | {"homelab-admins"}

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
    # Image versions of every host: homelab inventory, not a media tool.
    "cup": "homelab-admins",
}


def plan(current):
    """current: slug -> bound group names. Returns slug -> (groups to bind, managed groups to unbind) for apps that differ."""
    changes = {}
    for slug, group in APP_GROUP.items():
        bound = current.get(slug, set()) & MANAGED
        add, remove = {group} - bound, bound - {group}
        if add or remove:
            changes[slug] = (add, remove)
    return changes


def main():
    from authentik.core.models import Application, Group, User
    from authentik.policies.models import PolicyBinding

    owner = User.objects.get(username=OWNER)
    for name in GROUPS:
        group, created = Group.objects.get_or_create(name=name)
        if group.parents.exists():
            print(f"CHANGE {name}: parents {[p.name for p in group.parents.all()]} removed")
            group.parents.clear()
        if not group.users.filter(pk=owner.pk).exists():
            group.users.add(owner)
            print(f"CHANGE {OWNER} added to {name}")
        if created:
            print(f"CHANGE group {name} created")

    apps = {a.slug: a for a in Application.objects.filter(slug__in=APP_GROUP)}
    missing = set(APP_GROUP) - set(apps)
    if missing:
        raise SystemExit(f"missing applications: {sorted(missing)} (run the other provisioning scripts first)")
    current = {slug: {b.group.name for b in PolicyBinding.objects.filter(target=app, group__isnull=False)}
               for slug, app in apps.items()}
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
