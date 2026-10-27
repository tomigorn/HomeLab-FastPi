"""Tests for provision-admin-account.py. Run: python3 -m unittest discover -s Docker/Authentik/scripts"""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("provision_admin_account", HERE / "provision-admin-account.py")
paa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paa)


class AdminEmailTest(unittest.TestCase):
    def test_plus_address_of_the_everyday_mailbox(self):
        self.assertEqual(paa.admin_email("jane.doe@example.com"), "jane.doe+admin@example.com")

    def test_existing_plus_tag_is_replaced(self):
        self.assertEqual(paa.admin_email("jane+news@example.com"), "jane+admin@example.com")

    def test_domain_is_lowercased_local_part_kept(self):
        self.assertEqual(paa.admin_email("Jane@Example.COM"), "Jane+admin@example.com")

    def test_refuses_an_address_without_a_domain(self):
        for bad in ("", "jane", "@example.com", "jane@"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                paa.admin_email(bad)


class AccountTest(unittest.TestCase):
    def test_owner_wish(self):
        self.assertEqual(paa.EVERYDAY, "tomigorn")
        self.assertEqual(paa.ADMIN, "tomigorn-admin")
        self.assertEqual(paa.ADMIN_NAME, "Tomigorn (admin)")

    def test_diff_of_a_matching_account_is_empty(self):
        want = {"name": "Tomigorn (admin)", "email": "jane+admin@example.com", "is_active": True}
        self.assertEqual(paa.diff(dict(want), want), {})

    def test_diff_lists_only_changed_fields(self):
        want = {"name": "Tomigorn (admin)", "email": "jane+admin@example.com", "is_active": True}
        have = dict(want, is_active=False, name="old")
        self.assertEqual(paa.diff(have, want), {"is_active": True, "name": "Tomigorn (admin)"})


if __name__ == "__main__":
    unittest.main()
