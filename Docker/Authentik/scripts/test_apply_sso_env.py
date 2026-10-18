"""Tests for apply-sso-env.py. Run: python3 -m unittest discover -s Docker/Authentik/scripts
(also collected by pytest when it is installed)."""
import importlib.util
import io
import os
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "apply_sso_env", Path(__file__).with_name("apply-sso-env.py"))
apply_sso_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_sso_env)


class ApplySsoEnvTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        (self.base / "App").mkdir()
        # The tool refuses anything outside a git work tree (fail closed), like the repo.
        subprocess.run(["git", "init", "-q", str(self.base)], check=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, text):
        out, err = io.StringIO(), io.StringIO()
        rc = apply_sso_env.main(io.StringIO(text), out, err, base=self.base)
        return rc, out.getvalue(), err.getvalue()

    def test_replaces_existing_key_in_place(self):
        env = self.base / "App" / ".env"
        env.write_text("# comment\nA=1\nOIDC_SECRET=old\nB=2\n")
        env.chmod(0o640)
        rc, out, err = self.run_tool("ENV App/.env OIDC_SECRET=n3w=val\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(env.read_text(), "# comment\nA=1\nOIDC_SECRET=n3w=val\nB=2\n")
        self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o640)
        self.assertEqual(out, "set App/.env OIDC_SECRET\n")
        self.assertNotIn("n3w", out + err)

    def test_appends_missing_key(self):
        env = self.base / "App" / ".env"
        env.write_text("A=1")  # no trailing newline
        rc, out, _ = self.run_tool("ENV App/.env CLIENT_ID=abc\n")
        self.assertEqual(rc, 0)
        self.assertEqual(env.read_text(), "A=1\nCLIENT_ID=abc\n")
        self.assertEqual(out, "set App/.env CLIENT_ID\n")

    def test_creates_missing_env_file_private(self):
        rc, _, _ = self.run_tool("ENV App/.env K=v\n")
        env = self.base / "App" / ".env"
        self.assertEqual(rc, 0)
        self.assertEqual(env.read_text(), "K=v\n")
        self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)

    def test_passes_through_and_redacts(self):
        rc, out, _ = self.run_tool(
            "OK provisioned\nclient_secret is x\nmy Token: y\npassword=z\nplain line\n")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "OK provisioned\n[redacted line]\n[redacted line]\n"
                              "[redacted line]\nplain line\n")

    def test_refuses_non_env_paths(self):
        bad = ["App/config.env", "App/.env.example", "../App/.env", "/etc/.env",
               ".env", "App/sub/.env", "../.env", "Missing/.env"]
        for path in bad:
            with self.subTest(path=path):
                rc, out, err = self.run_tool(f"ENV {path} K=secretvalue\n")
                self.assertNotEqual(rc, 0)
                self.assertIn("refused", err)
                self.assertNotIn("secretvalue", out + err)
        self.assertFalse((self.base / "App" / "config.env").exists())

    def test_refuses_symlink_escaping_base(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (self.base / "Link").symlink_to(outside.name)
        rc, _, err = self.run_tool("ENV Link/.env K=v\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("refused", err)
        self.assertIn("outside base", err)
        self.assertFalse((Path(outside.name) / ".env").exists())

    def test_refuses_env_file_that_is_symlink(self):
        target = self.base / "App" / "real.env"
        target.write_text("K=old\n")
        (self.base / "App" / ".env").symlink_to(target)
        rc, _, err = self.run_tool("ENV App/.env K=new\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("symlink", err)
        self.assertEqual(target.read_text(), "K=old\n")

    def test_replaces_all_duplicate_keys(self):
        env = self.base / "App" / ".env"
        env.write_text("K=1\nA=x\nK=2\nKEEP=y\nK=3\n")
        rc, _, err = self.run_tool("ENV App/.env K=new\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(env.read_text(), "K=new\nA=x\nKEEP=y\n")

    def test_refuses_outside_git_work_tree(self):
        nogit = tempfile.TemporaryDirectory()
        self.addCleanup(nogit.cleanup)
        (Path(nogit.name) / "App").mkdir()
        out, err = io.StringIO(), io.StringIO()
        rc = apply_sso_env.main(io.StringIO("ENV App/.env K=v\n"), out, err,
                                base=Path(nogit.name))
        self.assertNotEqual(rc, 0)
        self.assertIn("git tracking check failed", err.getvalue())
        self.assertFalse((Path(nogit.name) / "App" / ".env").exists())

    def test_refuses_when_git_missing(self):
        with mock.patch.object(apply_sso_env.subprocess, "run",
                               side_effect=FileNotFoundError("git")):
            rc, _, err = self.run_tool("ENV App/.env K=v\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("git not available", err)
        self.assertFalse((self.base / "App" / ".env").exists())

    def test_write_error_continues_without_echo(self):
        (self.base / "B").mkdir()
        real_upsert = apply_sso_env.upsert

        def flaky(path, key, value):
            if path.parent.name == "App":
                raise PermissionError(13, "denied", str(path))
            return real_upsert(path, key, value)

        with mock.patch.object(apply_sso_env, "upsert", side_effect=flaky):
            rc, out, err = self.run_tool(
                "ENV App/.env K=secretvalue\nENV B/.env K=v2\nOK provisioned\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("PermissionError", err)
        self.assertNotIn("secretvalue", out + err)
        self.assertEqual((self.base / "B" / ".env").read_text(), "K=v2\n")
        self.assertIn("OK provisioned\n", out)

    def test_refuses_git_tracked_file(self):
        env = self.base / "App" / ".env"
        env.write_text("K=old\n")
        git = ["git", "-C", str(self.base), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(git + ["add", "-f", "App/.env"], check=True)
        rc, _, err = self.run_tool("ENV App/.env K=new\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("tracked", err)
        self.assertEqual(env.read_text(), "K=old\n")

    def test_malformed_env_line_errors_without_echo(self):
        rc, out, err = self.run_tool("ENV App/.env not-a-key-secretvalue\n")
        self.assertNotEqual(rc, 0)
        self.assertNotIn("secretvalue", out + err)

    def test_continues_after_error(self):
        rc, out, _ = self.run_tool("ENV ../x/.env K=v\nENV App/.env K=v\nOK provisioned\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("set App/.env K\n", out)
        self.assertIn("OK provisioned\n", out)


if __name__ == "__main__":
    unittest.main()
