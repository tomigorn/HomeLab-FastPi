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



class ApplySsoFileTest(unittest.TestCase):
    """FILE <dir>/secrets/<name> <uid>:<gid> <mode> <value>: the secret goes into a gitignored file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        (self.base / "App" / "secrets").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.base)], check=True)
        (self.base / ".gitignore").write_text("secrets/\n")
        self.me = f"{os.getuid()}:{os.getgid()}"

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, text, **kw):
        out, err = io.StringIO(), io.StringIO()
        rc = apply_sso_env.main(io.StringIO(text), out, err, base=self.base, **kw)
        return rc, out.getvalue(), err.getvalue()

    def test_writes_bare_value_with_owner_and_mode(self):
        rc, out, err = self.run_tool(f"FILE App/secrets/oidc {self.me} 0400 s3cr=et\n")
        f = self.base / "App" / "secrets" / "oidc"
        self.assertEqual(rc, 0, err)
        self.assertEqual(f.read_text(), "s3cr=et")
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o400)
        self.assertEqual(out, "set App/secrets/oidc\n")
        self.assertNotIn("s3cr", out + err)

    def test_replaces_existing_read_only_file(self):
        f = self.base / "App" / "secrets" / "oidc"
        f.write_text("old")
        f.chmod(0o400)
        rc, _, err = self.run_tool(f"FILE App/secrets/oidc {self.me} 0440 new\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(f.read_text(), "new")
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o440)

    def test_foreign_owner_goes_through_sudo_install_on_stdin(self):
        calls = []
        real_run = subprocess.run

        def fake(argv, *a, **kw):
            if argv[0] == "sudo":
                calls.append((argv, kw.get("input")))
                return subprocess.CompletedProcess(argv, 0)
            return real_run(argv, *a, **kw)

        with mock.patch.object(apply_sso_env.subprocess, "run", side_effect=fake):
            rc, out, err = self.run_tool("FILE App/secrets/oidc 65050:65051 0400 secretvalue\n")
        self.assertEqual(rc, 0, err)
        path = str(self.base.resolve() / "App" / "secrets" / "oidc")
        self.assertEqual(calls, [(["sudo", "-n", "install", "-o", "65050", "-g", "65051",
                                   "-m", "0400", "/dev/stdin", path], "secretvalue")])
        self.assertNotIn("secretvalue", out + err)

    def test_sudo_failure_is_reported_without_value_and_continues(self):
        real_run = subprocess.run

        def fake(argv, *a, **kw):
            if argv[0] == "sudo":
                return subprocess.CompletedProcess(argv, 1)
            return real_run(argv, *a, **kw)

        with mock.patch.object(apply_sso_env.subprocess, "run", side_effect=fake):
            rc, out, err = self.run_tool(
                f"FILE App/secrets/a 0:0 0400 secretvalue\nFILE App/secrets/b {self.me} 0400 v\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("App/secrets/a", err)
        self.assertNotIn("secretvalue", out + err)
        self.assertEqual((self.base / "App" / "secrets" / "b").read_text(), "v")

    def test_refuses_bad_paths(self):
        (self.base / "Bare").mkdir()
        bad = ["App/.env", "App/secrets/../x", "../App/secrets/x", "App/secrets/sub/x",
               "Missing/secrets/x", "Bare/secrets/x", "/etc/secrets/x", "App/secrets/.hidden",
               "App/other/x"]
        for path in bad:
            with self.subTest(path=path):
                rc, out, err = self.run_tool(f"FILE {path} {self.me} 0400 secretvalue\n")
                self.assertNotEqual(rc, 0)
                self.assertIn("refused", err)
                self.assertNotIn("secretvalue", out + err)

    def test_refuses_path_git_does_not_ignore(self):
        (self.base / ".gitignore").write_text("")
        rc, _, err = self.run_tool(f"FILE App/secrets/oidc {self.me} 0400 v\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("not ignored", err)
        self.assertFalse((self.base / "App" / "secrets" / "oidc").exists())

    def test_refuses_symlinked_file_or_dir(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (self.base / "Link").mkdir()
        (self.base / "Link" / "secrets").symlink_to(outside.name)
        (self.base / "App" / "secrets" / "ln").symlink_to(Path(outside.name) / "t")
        for path in ("Link/secrets/x", "App/secrets/ln"):
            with self.subTest(path=path):
                rc, _, err = self.run_tool(f"FILE {path} {self.me} 0400 v\n")
                self.assertNotEqual(rc, 0)
                self.assertIn("refused", err)
        self.assertEqual(list(Path(outside.name).iterdir()), [])

    def test_refuses_bad_owner_or_mode(self):
        for owner, mode in (("pi:pi", "0400"), ("1", "0400"), ("-1:0", "0400"),
                            (self.me, "0644"), (self.me, "0777"), (self.me, "400x"), (self.me, "0402")):
            with self.subTest(owner=owner, mode=mode):
                rc, out, err = self.run_tool(f"FILE App/secrets/oidc {owner} {mode} secretvalue\n")
                self.assertNotEqual(rc, 0)
                self.assertNotIn("secretvalue", out + err)
        self.assertFalse((self.base / "App" / "secrets" / "oidc").exists())

    def test_malformed_file_line_errors_without_echo(self):
        rc, out, err = self.run_tool("FILE App/secrets/oidc secretvalue\n")
        self.assertNotEqual(rc, 0)
        self.assertNotIn("secretvalue", out + err)

    def test_dry_run_writes_nothing_and_says_where(self):
        (self.base / "App" / ".env").write_text("A=1\n")
        rc, out, err = self.run_tool(
            f"ENV App/.env CLIENT_ID=abc\nFILE App/secrets/oidc 65050:65050 0400 secretvalue\n",
            dry_run=True)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "would set App/.env CLIENT_ID\n"
                              "would write App/secrets/oidc (65050:65050 0400)\n")
        self.assertEqual((self.base / "App" / ".env").read_text(), "A=1\n")
        self.assertFalse((self.base / "App" / "secrets" / "oidc").exists())


class ProvisionScriptsTest(unittest.TestCase):
    """Secrets of apps that read them from a file leave the provisioning only as FILE lines.
    Portainer and Seerr keep theirs in .env: no container reads it, only their configure step."""

    def test_no_file_backed_secret_goes_to_env(self):
        here = Path(__file__).parent
        text = "".join((here / n).read_text() for n in
                       ("provision-admin-sso.py", "provision-tracker-sso.py", "provision-media-sso.py"))
        for key in ("GRAFANA_OAUTH_CLIENT_SECRET", "WG_EASY_OIDC_CLIENT_SECRET", "SERVER_OIDC_CLIENT_SECRET"):
            with self.subTest(key=key):
                self.assertNotIn(key, text)

    def test_secret_files_for_grafana_wg_easy_ryot(self):
        here = Path(__file__).parent
        admin = (here / "provision-admin-sso.py").read_text()
        tracker = (here / "provision-tracker-sso.py").read_text()
        self.assertIn('"grafana/secrets/grafana_oauth_client_secret", "65050:65050", "0400"', admin)
        self.assertIn('"WireguardVPN/secrets/oidc_client_secret", "0:0", "0400"', admin)
        self.assertIn('"Ryot/secrets/ryot_oidc_client_secret", "1001:1001", "0400"', tracker)


if __name__ == "__main__":
    unittest.main()
