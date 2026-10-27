# Idempotent separate admin account for the owner (least privilege: everyday account tomigorn, admin account tomigorn-admin).
# Run (twice is fine):
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-admin-account.py
# Email = the everyday account's address as plus-address (+admin): same inbox, but unique, so apps that match users by email never mix the two.
# Creates the account active, without a usable password; the owner sets password + MFA via a one-time recovery link:
#   docker compose exec -T server ak create_recovery_key 60 tomigorn-admin
# Group memberships are never changed here (phase 2 of the admin split, Docker/Authentik/docs/admin-split-plan.md).
EVERYDAY = "tomigorn"
ADMIN = "tomigorn-admin"
ADMIN_NAME = "Tomigorn (admin)"


def admin_email(everyday):
    local, at, domain = everyday.rpartition("@")
    if not at or not local or not domain:
        raise ValueError("everyday account has no usable email address")
    return f"{local.split('+', 1)[0]}+admin@{domain.lower()}"


def diff(have, want):
    return {k: v for k, v in want.items() if have.get(k) != v}


def main():
    from authentik.core.models import User, UserTypes

    everyday = User.objects.get(username=EVERYDAY)
    want = {"name": ADMIN_NAME, "email": admin_email(everyday.email), "is_active": True}
    user = User.objects.filter(username=ADMIN).first()
    if user is None:
        user = User(username=ADMIN, type=UserTypes.INTERNAL, **want)
        user.set_unusable_password()
        user.save()
        print(f"CHANGE {ADMIN} created (no password, no groups)")
    else:
        changes = diff({k: getattr(user, k) for k in want}, want)
        for k, v in changes.items():
            setattr(user, k, v)
        if changes:
            user.save()
            print(f"CHANGE {ADMIN}: {sorted(changes)} updated")
    if User.objects.filter(email__iexact=want["email"]).exclude(pk=user.pk).exists():
        raise SystemExit(f"FAIL another account uses the {ADMIN} email address")
    print(f"INFO {ADMIN} groups: {sorted(g.name for g in user.groups.all())}, superuser: {user.is_superuser}")
    print("OK admin account")


try:
    import authentik  # noqa: F401  (absent in the unit tests)
except ImportError:
    pass
else:
    main()
