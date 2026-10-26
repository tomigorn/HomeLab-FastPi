"""Tests for provision-media-groups.py. Run: python3 -m unittest discover -s Docker/Authentik/scripts"""
import ast
import importlib.util
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


class MatrixTest(unittest.TestCase):
    def test_owner_wish(self):
        users = {s for s, g in pmg.APP_GROUP.items() if g == "streaming-users"}
        requesters = {s for s, g in pmg.APP_GROUP.items() if g == "streaming-requesters"}
        admins = {s for s, g in pmg.APP_GROUP.items() if g == "streaming-admins"}
        self.assertEqual(users, {"jellyfin", "jellyfin-wake", "tracker", "tracker-login"})
        self.assertEqual(requesters, {"requests", "requests-login", "books", "books-login"})
        self.assertEqual(admins, {"radarr", "sonarr", "prowlarr", "bazarr", "sabnzbd", "qbittorrent",
                                  "qbittorrent-audiobooks", "sabnzbd-audiobooks", "prowlarr-audiobooks"})

    def test_groups_are_independent_and_owner_is_in_all(self):
        self.assertEqual(pmg.GROUPS, ("streaming-users", "streaming-requesters", "streaming-admins"))
        self.assertEqual(pmg.OWNER, "tomigorn")

    def test_other_provisioning_scripts_bind_the_same_groups(self):
        for script in ("provision-media-sso.py", "provision-tracker-sso.py", "provision-audiobook-downloads-sso.py",
                       "provision-books-sso.py"):
            for slug, group in app_for_groups(script).items():
                with self.subTest(script=script, slug=slug):
                    self.assertEqual(pmg.APP_GROUP[slug], group)


if __name__ == "__main__":
    unittest.main()
