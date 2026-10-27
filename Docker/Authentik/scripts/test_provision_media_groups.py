"""Tests for provision-media-groups.py. Run: python3 -m unittest discover -s Docker/Authentik/scripts"""
import ast
import importlib.util
import re
import unittest
from pathlib import Path

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("provision_media_groups", HERE / "provision-media-groups.py")
pmg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pmg)


def app_for_groups(script):
    """slug -> group of every app_for("slug", name, host, "group", ...) call in a provisioning script."""
    found = {}
    for node in ast.walk(ast.parse((HERE / script).read_text())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "app_for":
            found[node.args[0].value] = node.args[3].value
    return found


class PlanTest(unittest.TestCase):
    def test_moves_requests_from_users_to_requesters(self):
        plan = pmg.plan({"requests": {"streaming-users"}})
        self.assertEqual(plan["requests"], ({"streaming-requesters"}, {"streaming-users"}))

    def test_target_state_needs_no_change(self):
        current = {slug: {group} for slug, group in pmg.APP_GROUP.items()}
        self.assertEqual(pmg.plan(current), {})

    def test_missing_app_gets_its_group(self):
        plan = pmg.plan({})
        self.assertEqual(plan["radarr"], ({"streaming-admins"}, set()))

    def test_unmanaged_groups_are_kept(self):
        plan = pmg.plan({"jellyfin": {"streaming-users", "cloud-users"}})
        self.assertNotIn("jellyfin", plan)

    def test_inherited_admin_binding_is_removed(self):
        plan = pmg.plan({"jellyfin": {"streaming-users", "streaming-admins"}})
        self.assertEqual(plan["jellyfin"], (set(), {"streaming-admins"}))

    def test_apps_outside_the_matrix_are_ignored(self):
        plan = pmg.plan({"audiobookshelf": {"streaming-users"}})
        self.assertNotIn("audiobookshelf", plan)


class UserBindingTest(unittest.TestCase):
    def test_owner_decision_homelab_users_apps(self):
        self.assertEqual(pmg.USER_APPS, {"home-assistant": "homelab-users", "grafana": "homelab-users"})

    def test_missing_user_binding_is_added(self):
        self.assertEqual(pmg.user_binding_plan({"home-assistant": {"homelab-admins"}, "grafana": {"homelab-admins"}}),
                         {"home-assistant", "grafana"})

    def test_bound_user_apps_need_no_change(self):
        self.assertEqual(pmg.user_binding_plan({s: {"homelab-admins", g} for s, g in pmg.USER_APPS.items()}), set())

    def test_user_apps_are_not_in_the_exclusive_matrix(self):
        self.assertFalse(set(pmg.USER_APPS) & set(pmg.APP_GROUP))


class MatrixTest(unittest.TestCase):
    def test_owner_wish(self):
        users = {s for s, g in pmg.APP_GROUP.items() if g == "streaming-users"}
        requesters = {s for s, g in pmg.APP_GROUP.items() if g == "streaming-requesters"}
        admins = {s for s, g in pmg.APP_GROUP.items() if g == "streaming-admins"}
        self.assertEqual(users, {"jellyfin", "jellyfin-wake", "tracker", "tracker-login"})
        self.assertEqual(requesters, {"requests", "requests-login", "books", "books-login"})
        self.assertEqual(admins, {"radarr", "sonarr", "prowlarr", "bazarr", "sabnzbd", "qbittorrent",
                                  "qbittorrent-audiobooks", "sabnzbd-audiobooks", "prowlarr-audiobooks"})

    def test_groups_are_independent(self):
        self.assertEqual(pmg.GROUPS, ("streaming-users", "streaming-requesters", "streaming-admins"))

    def test_other_provisioning_scripts_bind_the_same_groups(self):
        for script in ("provision-media-sso.py", "provision-tracker-sso.py", "provision-audiobook-downloads-sso.py",
                       "provision-books-sso.py"):
            for slug, group in app_for_groups(script).items():
                with self.subTest(script=script, slug=slug):
                    self.assertEqual(pmg.APP_GROUP[slug], group)


ALL_SIX = {"cloud-users", "cloud-admins", "streaming-users", "streaming-admins", "streaming-requesters", "homelab-admins"}


class MembershipTest(unittest.TestCase):
    def test_admin_split_design(self):
        self.assertEqual(pmg.MEMBERS["tomigorn"], {"streaming-users", "streaming-requesters", "homelab-users"})
        self.assertEqual(pmg.MEMBERS["tomigorn-admin"], {"homelab-admins", "streaming-admins", "streaming-users",
                                                         "streaming-requesters", "authentik Admins"})

    def test_phase_2a_is_add_only(self):
        self.assertFalse(pmg.REMOVE_EXTRA)

    def test_2a_adds_admin_and_takes_nothing_away(self):
        plan = pmg.membership_plan({"tomigorn": ALL_SIX, "tomigorn-admin": set()}, remove=False)
        self.assertEqual(plan["tomigorn-admin"], (pmg.MEMBERS["tomigorn-admin"], set()))
        self.assertEqual(plan["tomigorn"], ({"homelab-users"}, set()))

    def test_2b_removes_admin_groups_from_everyday(self):
        have = {"tomigorn": ALL_SIX | {"homelab-users"}, "tomigorn-admin": pmg.MEMBERS["tomigorn-admin"]}
        plan = pmg.membership_plan(have, remove=True)
        self.assertEqual(plan, {"tomigorn": (set(), {"streaming-admins", "homelab-admins"})})

    def test_everyday_joins_homelab_users_without_losing_anything_in_2a(self):
        plan = pmg.membership_plan({"tomigorn": ALL_SIX, "tomigorn-admin": pmg.MEMBERS["tomigorn-admin"]}, remove=False)
        self.assertEqual(plan, {"tomigorn": ({"homelab-users"}, set())})

    def test_admin_account_is_not_an_everyday_user(self):
        self.assertNotIn("homelab-users", pmg.MEMBERS["tomigorn-admin"])

    def test_cloud_groups_are_never_touched(self):
        plan = pmg.membership_plan({"tomigorn": {"cloud-admins", "cloud-users"}}, remove=True)
        self.assertEqual(plan["tomigorn"], ({"streaming-users", "streaming-requesters", "homelab-users"}, set()))

    def test_everyday_never_gets_superuser(self):
        plan = pmg.membership_plan({}, remove=False)
        self.assertNotIn("authentik Admins", plan["tomigorn"][0])

    def test_target_state_needs_no_change(self):
        self.assertEqual(pmg.membership_plan(dict(pmg.MEMBERS), remove=True), {})

    def test_only_listed_users_are_planned(self):
        plan = pmg.membership_plan({"invitee": {"streaming-users"}, **pmg.MEMBERS}, remove=True)
        self.assertEqual(plan, {})


def proxy_create_defaults():
    """(script, line) -> defaults dict source of every ProxyProvider.objects.update_or_create in a provisioning script."""
    found = {}
    for script in sorted(HERE.glob("provision-*.py")):
        for node in ast.walk(ast.parse(script.read_text())):
            if (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "update_or_create"
                    and ast.unparse(node.func.value) == "ProxyProvider.objects"):
                kw = {k.arg: k.value for k in node.keywords}
                found[(script.name, node.lineno)] = kw.get("defaults")
    return found


class ProxyValidityTest(unittest.TestCase):
    def test_new_proxy_providers_get_the_session_ttl_validity(self):
        validity = re.search(r'access_token_validity = "([^"]+)"', (HERE / "session-ttl.sh").read_text()).group(1)
        found = proxy_create_defaults()
        self.assertGreaterEqual(len(found), 8)
        for (script, line), defaults in found.items():
            with self.subTest(script=script, line=line):
                keys = {ast.literal_eval(k): v for k, v in zip(defaults.keys, defaults.values) if k is not None}
                self.assertIn("access_token_validity", keys)
                self.assertEqual(ast.literal_eval(keys["access_token_validity"]), validity)


if __name__ == "__main__":
    unittest.main()
