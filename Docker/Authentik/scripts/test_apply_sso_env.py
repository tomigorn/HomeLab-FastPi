"""Tests for apply-sso-env.py. Run: python3 -m unittest discover -s Docker/Authentik/scripts
(also collected by pytest when it is installed)."""
import importlib.util
import io
import os
import stat
import subprocess
import tempfile
import unittest
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
        self.assertFalse((Path(outside.name) / ".env").exists())

    def test_refuses_git_tracked_file(self):
        env = self.base / "App" / ".env"
        env.write_text("K=old\n")
        git = ["git", "-C", str(self.base), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(git + ["init", "-q"], check=True)
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
