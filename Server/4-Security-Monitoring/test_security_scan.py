#!/usr/bin/env python3
"""Tests for security_scan.py's pure functions.

Only the pure seams are tested. The I/O shell (git fetch, gitleaks, apt, Trivy)
is verified by running the real thing once at install time - mocking a git
mirror would test the mock.

Run: python3 -m pytest test_security_scan.py -q
  or: python3 test_security_scan.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from security_scan import (  # noqa: E402
    classify_secret_file,
    is_template,
    looks_like_secret_file,
    parse_apt_upgradable,
    parse_trivy,
    render_metrics,
    triage_findings,
)


# --- is_template / looks_like_secret_file ----------------------------------

def test_env_is_a_secret_file():
    assert looks_like_secret_file("Docker/Jellyfin/.env")


def test_pem_and_key_are_secret_files():
    assert looks_like_secret_file("Docker/Jenkins/app.private-key.pem")
    assert looks_like_secret_file("certs/tls.key")


def test_home_assistant_secrets_yaml_is_a_secret_file():
    # Named by convention rather than extension, so it needs its own case.
    assert looks_like_secret_file("Docker/Home-Assistant/config/secrets.yaml")


def test_backup_copies_of_secret_files_are_still_secret_files():
    # The classic accident: a .env copied aside while debugging. `.gitignore`
    # entries for `.env` do NOT match `.env.bak`, so these are genuinely
    # committable, which makes them the highest-value case here - and the
    # original suffix-only matcher missed every one of them.
    for p in (".env.bak", ".env.old", ".env.save", "Docker/X/.env.orig",
              "config/secrets.yaml.backup", "certs/tls.key.old"):
        assert looks_like_secret_file(p), p


def test_backup_copies_are_not_treated_as_templates():
    assert not is_template(".env.bak")
    assert classify_secret_file(".env.bak", tracked=False, ignored=False) == "at_risk"


def test_template_suffix_after_the_secret_name_is_recognised():
    # secrets.yaml.example: the template marker trails the secret name, so a
    # final-suffix test sees ".example" and nothing else.
    assert looks_like_secret_file("Docker/Home-Assistant/config/secrets.yaml.example")
    assert is_template("Docker/Home-Assistant/config/secrets.yaml.example")


def test_stacked_suffixes_still_resolve():
    assert looks_like_secret_file(".env.example.old")


def test_key_material_with_a_format_suffix_is_recognised():
    # Found unchecked on fastpi on 2026-10-09: an RSA private key named
    # ...private-key.pem.PKCS8. A final-suffix test sees ".PKCS8", which is not
    # in any list, so the actual key material went unexamined.
    assert looks_like_secret_file("Docker/Jenkins/secrets/ci.2025-10-24.private-key.pem.PKCS8")
    assert looks_like_secret_file("certs/server.pem.der")


def test_terraform_state_is_a_secret_file():
    # tfstate stores provider credentials, generated passwords and private keys
    # in PLAINTEXT. Found untracked AND unignored in this repo on 2026-10-09
    # (Terraform/HelloWorld/terraform.tfstate), i.e. one `git add -A` from a
    # public push.
    assert looks_like_secret_file("Terraform/HelloWorld/terraform.tfstate")
    assert looks_like_secret_file("infra/terraform.tfstate.backup")
    assert looks_like_secret_file("env/prod.tfvars")


def test_other_key_container_formats_are_recognised():
    for p in ("a.jks", "a.keystore", "a.p8", "a.ppk", "vault.kdbx",
              "client.ovpn", "backup.gpg", "msg.asc", "store.p12"):
        assert looks_like_secret_file(p), p


def test_ssh_private_keys_by_conventional_name():
    assert looks_like_secret_file(".ssh/id_rsa")
    assert looks_like_secret_file("deploy/id_ed25519")
    # The .pub half is public by definition and must not be flagged.
    assert not looks_like_secret_file(".ssh/id_rsa.pub")


def test_certificates_are_not_secrets():
    # A certificate is public; flagging it is noise that buries the key beside it.
    for p in ("tls.crt", "chain.cer", "ca-bundle.crt"):
        assert not looks_like_secret_file(p), p


def test_words_merely_containing_key_are_not_secret_files():
    # Guard against the obvious over-correction.
    for p in ("docs/keyboard-layout.md", "src/monkey.py", "notes/keynote.txt",
              "Docker/X/keys-howto.md", "conda/environment.yml", "lib/pemdas.js",
              "docs/secretary-notes.md", "Docker/X/docker-compose.yaml"):
        assert not looks_like_secret_file(p), p


def test_ordinary_files_are_not_secret_files():
    assert not looks_like_secret_file("docker-compose.yaml")
    assert not looks_like_secret_file("README.md")
    assert not looks_like_secret_file("Docker/Cup/cup.json")


def test_example_and_sample_are_templates():
    assert is_template("Docker/Jellyfin/.env.example")
    assert is_template("Docker/cloudflared/secrets.example/tunnel_token.secret")
    assert is_template("config/secrets.yaml.sample")


def test_real_env_is_not_a_template():
    assert not is_template("Docker/Jellyfin/.env")


# --- classify_secret_file --------------------------------------------------

def test_ignored_env_is_ok():
    assert classify_secret_file(".env", tracked=False, ignored=True) == "ok"


def test_tracked_real_secret_is_exposed():
    # The worst case: it is in the public repo right now.
    assert classify_secret_file("Docker/X/.env", tracked=True, ignored=False) == "exposed"


def test_tracked_template_is_a_template_not_exposed():
    # The four .example files found on 2026-10-09 must not read as leaks.
    assert classify_secret_file(".env.example", tracked=True, ignored=False) == "template"
    assert classify_secret_file(
        "Docker/Jenkins/secrets.example/ci.private-key.pem", tracked=True, ignored=False
    ) == "template"


def test_untracked_and_unignored_is_at_risk():
    # `git add -A` would commit this. The gap that actually bites.
    assert classify_secret_file("Docker/New/.env", tracked=False, ignored=False) == "at_risk"


def test_ignored_beats_tracked_only_for_templates():
    # A tracked file is exposed even if a later .gitignore rule matches it:
    # gitignore does not apply to already-tracked files, a classic trap.
    assert classify_secret_file("Docker/X/.env", tracked=True, ignored=True) == "exposed"


# --- triage_findings -------------------------------------------------------

def test_triage_counts_by_rule():
    got = triage_findings([
        {"RuleID": "oidc-client-secret"},
        {"RuleID": "oidc-client-secret"},
        {"RuleID": "bcrypt-hash"},
    ])
    assert got == {"oidc-client-secret": 2, "bcrypt-hash": 1}


def test_triage_of_clean_report_is_empty():
    assert triage_findings([]) == {}


def test_triage_handles_missing_ruleid():
    assert triage_findings([{}]) == {"unknown": 1}


# --- parse_apt_upgradable --------------------------------------------------

APT = """Listing...
libc6/noble-updates 2.39-0ubuntu8.3 arm64 [upgradable from: 2.39-0ubuntu8.2]
openssl/noble-security 3.0.13-0ubuntu3.4 arm64 [upgradable from: 3.0.13-0ubuntu3.3]
curl/noble-security 8.5.0-2ubuntu10.6 arm64 [upgradable from: 8.5.0-2ubuntu10.5]
"""


def test_apt_counts_total_and_security():
    assert parse_apt_upgradable(APT) == {"total": 3, "security": 2}


def test_apt_empty_list_is_zero_not_an_error():
    assert parse_apt_upgradable("Listing...\n") == {"total": 0, "security": 0}


def test_apt_ignores_warning_noise():
    # apt writes WARNING/N: lines to stdout in some configurations.
    noisy = "WARNING: apt does not have a stable CLI interface.\n" + APT
    assert parse_apt_upgradable(noisy) == {"total": 3, "security": 2}


# --- parse_trivy -----------------------------------------------------------

def test_trivy_counts_by_severity():
    got = parse_trivy({"Results": [
        {"Vulnerabilities": [{"Severity": "CRITICAL"}, {"Severity": "HIGH"}]},
        {"Vulnerabilities": [{"Severity": "high"}]},
    ]})
    assert got["CRITICAL"] == 1 and got["HIGH"] == 2


def test_trivy_clean_image_has_no_results_key():
    # Trivy omits Results entirely for an image with nothing found, and emits
    # Vulnerabilities: null for a scanned-but-clean target. Both mean zero.
    assert parse_trivy({})["CRITICAL"] == 0
    assert parse_trivy({"Results": [{"Vulnerabilities": None}]})["HIGH"] == 0


def test_trivy_unknown_severity_is_not_dropped():
    assert parse_trivy({"Results": [{"Vulnerabilities": [{}]}]})["UNKNOWN"] == 1


# --- render_metrics --------------------------------------------------------

def test_render_emits_help_and_type_once_per_metric():
    out = render_metrics(
        [("m", {"a": "1"}, 1), ("m", {"a": "2"}, 2)], {"m": "a help string"}
    )
    assert out.count("# HELP m ") == 1
    assert out.count("# TYPE m gauge") == 1
    assert 'm{a="1"} 1' in out and 'm{a="2"} 2' in out


def test_render_puts_help_before_first_sample():
    # node-exporter discards the entire file if HELP follows a sample, which
    # would silently drop every metric here, not just the malformed one.
    out = render_metrics([("m", {}, 1)], {"m": "h"}).splitlines()
    assert out.index("# HELP m h") < out.index("m 1")


def test_render_sorts_labels_for_stable_output():
    out = render_metrics([("m", {"b": "2", "a": "1"}, 1)], {})
    assert 'm{a="1",b="2"} 1' in out


def test_render_escapes_quotes_in_label_values():
    out = render_metrics([("m", {"f": 'a"b'}, 1)], {})
    assert 'f="a\\"b"' in out


def test_render_formats_integers_without_decimal_point():
    assert "m 1\n" in render_metrics([("m", {}, 1.0)], {})


def test_render_keeps_timestamp_precision():
    # Staleness alerts compare this against time(), so it must not be truncated.
    out = render_metrics([("t", {}, 1791530508.342)], {})
    assert "1791530508.342" in out


def test_render_ends_with_newline():
    # A file without a trailing newline makes node-exporter log a parse error.
    assert render_metrics([("m", {}, 1)], {}).endswith("\n")


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for n, f in fns:
        try:
            f()
        except Exception:  # noqa: BLE001
            bad += 1
            print(f"FAIL {n}")
            traceback.print_exc()
    print(f"\n{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
