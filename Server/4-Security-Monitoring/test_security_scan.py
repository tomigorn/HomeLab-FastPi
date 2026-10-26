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
import security_scan  # noqa: E402
from security_scan import (  # noqa: E402
    NoData,
    classify_secret_file,
    collect_av,
    collect_media,
    collect_updates,
    audit_samples,
    count_failed_logins,
    classify_source,
    parse_ssh_logins,
    integrity_samples,
    integrity_diff,
    integrity_targets,
    hash_file,
    new_findings,
    parse_audit_output,
    parse_chkrootkit,
    parse_chkrootkit_detail,
    parse_cup,
    cup_missing_reason,
    parse_lynis_report,
    parse_rkhunter,
    filter_exposition,
    parse_infected_list,
    parse_quarantine_index,
    hit_title,
    hit_mode,
    count_fixable,
    is_template,
    looks_like_secret_file,
    parse_apt_upgradable,
    parse_trivy,
    image_only_local,
    dockerfile_bases,
    parse_local_bases,
    parse_unraid_check,
    scan_all_images,
    unraid_samples,
    render_metrics,
    triage_findings,
    parse_env,
    resolve_vars,
    compose_images,
    code_image_refs,
    fixable_findings,
    diff_findings,
    sbom_refresh_order,
    new_vuln_samples,
    baseline_new_images,
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


def test_fixable_counts_only_vulns_with_a_fixed_version():
    # The distinction that makes the number honest: a CVE with no FixedVersion
    # cannot be resolved by ANY image update, so counting it in a backlog
    # implies work that does not exist. fastpi's 315 CRITICAL is only a to-do
    # list to the extent that it is fixable.
    rep = {"Results": [{"Vulnerabilities": [
        {"Severity": "CRITICAL", "FixedVersion": "1.2.3"},
        {"Severity": "CRITICAL"},                     # upstream has no fix yet
        {"Severity": "CRITICAL", "FixedVersion": ""},  # present but empty
        {"Severity": "HIGH", "FixedVersion": "2.0"},
    ]}]}
    # CRITICAL is 1, not 2: of the three criticals only one carries a usable
    # FixedVersion. The empty string must be treated as "no fix", because that
    # is what Trivy emits for a vulnerability whose fix is not yet released.
    assert count_fixable(rep) == {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 0,
                                  "LOW": 0, "UNKNOWN": 0}


def test_fixable_on_a_clean_report_is_all_zero():
    assert count_fixable({})["CRITICAL"] == 0
    assert count_fixable({"Results": [{"Vulnerabilities": None}]})["HIGH"] == 0


def test_fixable_never_exceeds_total():
    rep = {"Results": [{"Vulnerabilities": [
        {"Severity": "CRITICAL", "FixedVersion": "1"},
        {"Severity": "CRITICAL"},
    ]}]}
    tot = parse_trivy(rep)
    fix = count_fixable(rep)
    for sev in tot:
        assert fix[sev] <= tot[sev], sev


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


# --- av: remote clamav.prom pull --------------------------------------------

CLAMAV_PROM = """# TYPE clamav_infected_last_run gauge
clamav_infected_last_run{host="beefy",mode="new"} 0
# TYPE clamav_last_run_timestamp_seconds gauge
clamav_last_run_timestamp_seconds{host="beefy",mode="new"} 1792440055
clamav_signature_age_seconds{host="beefy"} 4.8895e4
"""


def test_exposition_keeps_valid_clamav_lines_verbatim():
    assert filter_exposition(CLAMAV_PROM) == CLAMAV_PROM


def test_exposition_drops_metrics_without_clamav_prefix():
    out = filter_exposition(CLAMAV_PROM + "# TYPE node_load1 gauge\nnode_load1 3\nsecurity_scan_errors{subject=\"x\"} 1\n")
    assert "node_load1" not in out and "security_" not in out
    assert "clamav_infected_last_run" in out


def test_exposition_drops_malformed_lines():
    bad = ("clamav_x{host=\"beefy\" 1\n"       # unclosed label set
           "clamav_y{host=beefy} 1\n"           # unquoted label value
           "clamav_z{host=\"b\"} notanumber\n"
           "clamav_w\n"
           "garbage line here\n"
           "clamav_ok{host=\"b\"} 1 1792440055000\n")
    assert filter_exposition(bad) == "clamav_ok{host=\"b\"} 1 1792440055000\n"


def test_exposition_accepts_special_float_values():
    for v in ("NaN", "+Inf", "-Inf", "-1.5", "1e3"):
        assert filter_exposition(f"clamav_a {v}\n") == f"clamav_a {v}\n", v


def test_exposition_drops_duplicate_or_late_type_lines():
    # node-exporter rejects the whole file when TYPE repeats or follows a sample.
    text = ("clamav_a 1\n# TYPE clamav_a gauge\n"
            "# TYPE clamav_b gauge\n# TYPE clamav_b gauge\nclamav_b 2\n")
    assert filter_exposition(text) == "clamav_a 1\n# TYPE clamav_b gauge\nclamav_b 2\n"


def test_exposition_of_empty_or_foreign_file_is_empty():
    assert filter_exposition("") == ""
    assert filter_exposition("# just a comment\nfoo 1\n") == ""


def test_infected_list_parses_path_tab_signature():
    text = "/scan/dl/a.exe\tWin.Test.EICAR_HDB-1\n\n/scan/b b.zip\tPUA.Foo\n"
    assert parse_infected_list(text) == [("/scan/dl/a.exe", "Win.Test.EICAR_HDB-1"), ("/scan/b b.zip", "PUA.Foo")]


def test_infected_list_without_signature_is_kept():
    assert parse_infected_list("/scan/x\n") == [("/scan/x", "unknown")]


def test_infected_list_empty_is_no_hits():
    assert parse_infected_list("") == []


def _tmp_dirs():
    import tempfile
    d = Path(tempfile.mkdtemp())
    security_scan.TEXTFILE = d / "textfile"
    security_scan.STATE = d / "state"
    security_scan.TEXTFILE.mkdir()
    security_scan.STATE.mkdir()
    return d


def test_av_publishes_clamav_file_and_hit_list():
    d = _tmp_dirs()
    files = {"prom": CLAMAV_PROM, "hook": None, "infected": "/scan/a.exe\tEICAR\n"}
    samples = collect_av("beefy", lambda what: files[what])
    assert (d / "textfile" / "clamav_beefy.prom").read_text() == CLAMAV_PROM
    assert (d / "state" / "last-infected-beefy.txt").read_text() == "/scan/a.exe\tEICAR\n"
    assert ("security_av_infected_info", {"host": "beefy", "path": "/scan/a.exe", "signature": "EICAR"}, 1) in samples


def test_av_missing_remote_file_is_no_data_and_keeps_old_file():
    # The scanners on beefy/tower may not have run yet: missing means stale, not zero and not an error.
    d = _tmp_dirs()
    (d / "textfile" / "clamav_tower.prom").write_text("old\n")
    try:
        collect_av("tower", lambda what: None)
        raise AssertionError("expected NoData")
    except NoData:
        pass
    assert (d / "textfile" / "clamav_tower.prom").read_text() == "old\n"


def test_av_file_without_any_clamav_sample_is_no_data():
    d = _tmp_dirs()
    try:
        collect_av("tower", lambda what: "# TYPE x gauge\nfoo 1\n" if what == "prom" else "")
        raise AssertionError("expected NoData")
    except NoData:
        pass
    assert not (d / "textfile" / "clamav_tower.prom").exists()


def test_av_hit_list_is_capped():
    _tmp_dirs()
    many = "".join(f"/scan/f{i}\tSig\n" for i in range(100))
    samples = collect_av("beefy", lambda what: CLAMAV_PROM if what == "prom" else many)
    assert len([s for s in samples if s[0] == "security_av_infected_info"]) == security_scan.AV_HIT_LIMIT


def test_av_also_publishes_the_beefy_hook_file():
    d = _tmp_dirs()
    hook = 'clamav_infected_last_run{host="beefy",mode="hook"} 0\nclamav_infected_total{host="beefy",mode="hook"} 2\n'
    files = {"prom": CLAMAV_PROM, "hook": hook, "infected": ""}
    collect_av("beefy", lambda what: files[what])
    assert (d / "textfile" / "clamav_hook_beefy.prom").read_text() == hook


def test_av_missing_hook_file_is_skipped_not_no_data():
    d = _tmp_dirs()
    (d / "textfile" / "clamav_hook_beefy.prom").write_text("old\n")
    files = {"prom": CLAMAV_PROM, "hook": None, "infected": ""}
    collect_av("beefy", lambda what: files[what])
    assert (d / "textfile" / "clamav_beefy.prom").exists()
    assert (d / "textfile" / "clamav_hook_beefy.prom").read_text() == "old\n"


INDEX = ("2026-10-26T20:48:49+01:00\t/scan/ssd-hot/usenet/complete/clamav-test-sync/Clamav.Test.Sync.exe\tEicar-Test-Signature\n"
         "2026-10-26T19:53:44+00:00\t/scan/ssd-hot/usenet/complete/clamav-test-imported/media/Clamav Test Bg - S01E01.mkv\tEicar-Test-Signature\n")
NEW_HIT = "2026-10-27T10:00:00+01:00\t/scan/ssd-hot/torrents/complete/Some.Show.S01/Some.Show.S01E01.mkv\tWin.Trojan.X-1\n"
LATER = 1793091600.0   # 2026-10-27T10:00:00+01:00


def _hits(host, index, infected="", now=LATER, hits=None):
    return security_scan.collect_av_hits(host, lambda what: {"index": index, "infected": infected, "hits": hits}[what], now=now)


def _hit_series(samples):
    return [s for s in samples if s[0] == "clamav_quarantine_hit_first_seen_timestamp_seconds"]


def test_quarantine_index_parses_lines_and_marks_restored():
    hits = parse_quarantine_index("2026-10-26T20:48:49+01:00\t/scan/a.exe\tEICAR\n"
                                  "2026-10-26T21:00:00+01:00\t/scan/b.exe\tEICAR\trestored 2026-10-26T22:00:00+01:00\n"
                                  "garbage line\n\n")
    assert [(h["path"], h["signature"], h["restored"]) for h in hits] == [("/scan/a.exe", "EICAR", False), ("/scan/b.exe", "EICAR", True)]
    assert hits[0]["ts"] == 1793044129.0


def test_hit_title_is_the_download_folder_else_the_parent():
    assert hit_title("/scan/ssd-hot/usenet/complete/clamav-test-imported/media/x.mkv") == "clamav-test-imported"
    assert hit_title("/scan/seagate-red/qbittorrent/downloads/Some.Album/a.exe") == "Some.Album"
    assert hit_title("/scan/appdata/nextcloud/data/a.exe") == "data"


def test_hit_mode_scan_when_in_the_nightly_list_else_hook_or_queue_by_media_name():
    assert hit_mode("beefy", "/scan/x/a.mkv", {"/scan/x/a.mkv"}) == "scan"
    assert hit_mode("beefy", "/scan/x/a.mkv", set()) == "queue"
    assert hit_mode("beefy", "/scan/x/a.exe", set()) == "hook"
    assert hit_mode("fastpi", "/scan/x/a.exe", set()) == "scan"
    assert hit_mode("tower", "/scan/x/a.mkv", set()) == "scan"


def test_av_hits_first_run_baselines_lines_before_the_cutoff():
    # The EICAR tests of 2026-10-26 were in index.txt before this alert existed: no alert for them.
    _tmp_dirs()
    assert _hit_series(_hits("beefy", INDEX)) == []


def test_av_hits_new_line_gives_one_series_with_its_details():
    d = _tmp_dirs()
    import os, time as _t
    os.environ["TZ"] = "Europe/Zurich"
    _t.tzset()
    _hits("beefy", INDEX, now=LATER - 600)
    series = _hit_series(_hits("beefy", INDEX + NEW_HIT))
    assert series == [("clamav_quarantine_hit_first_seen_timestamp_seconds",
                       {"host": "beefy", "mode": "queue", "title": "Some.Show.S01", "file": "Some.Show.S01E01.mkv",
                        "path": "/scan/ssd-hot/torrents/complete/Some.Show.S01/Some.Show.S01E01.mkv",
                        "signature": "Win.Trojan.X-1", "time": "Tue, 27 Oct 2026 10:00"}, LATER)]
    assert (d / "state" / "av-hits-seen-beefy.json").exists()


def test_av_hits_keep_first_seen_time_and_end_after_24h():
    _tmp_dirs()
    _hits("beefy", INDEX, now=LATER - 600)
    _hits("beefy", INDEX + NEW_HIT, now=LATER)
    assert _hit_series(_hits("beefy", INDEX + NEW_HIT, now=LATER + 3600))[0][2] == LATER
    assert _hit_series(_hits("beefy", INDEX + NEW_HIT, now=LATER + 86401)) == []


def test_av_hits_counted_per_mode_in_24h():
    _tmp_dirs()
    _hits("beefy", INDEX, now=LATER - 600)
    samples = _hits("beefy", INDEX + NEW_HIT)
    counts = {s[1]["mode"]: s[2] for s in samples if s[0] == "clamav_quarantine_hits_24h"}
    assert counts == {"scan": 0, "hook": 0, "queue": 1}


def test_av_hits_after_the_cutoff_alert_even_on_the_first_run():
    # tower may first answer days after deployment: a real hit by then is not swallowed by the baseline.
    _tmp_dirs()
    assert len(_hit_series(_hits("tower", NEW_HIT))) == 1


def test_av_hits_restored_line_stops_alerting():
    _tmp_dirs()
    _hits("beefy", INDEX, now=LATER - 600)
    _hits("beefy", INDEX + NEW_HIT)
    restored = INDEX + NEW_HIT.rstrip("\n") + "\trestored 2026-10-27T11:00:00+01:00\n"
    assert _hit_series(_hits("beefy", restored, now=LATER + 60)) == []


def test_av_hits_series_capped_newest_first():
    _tmp_dirs()
    _hits("fastpi", "", now=LATER - 600)
    many = "".join(f"2026-10-27T09:{i:02d}:00+01:00\t/scan/r/dl/f{i}.exe\tSig\n" for i in range(30))
    series = _hit_series(_hits("fastpi", many))
    assert len(series) == security_scan.AV_HIT_LIMIT
    assert series[0][1]["file"] == "f29.exe"


def test_av_hits_missing_index_is_no_data():
    _tmp_dirs()
    try:
        _hits("tower", None)
        raise AssertionError("expected NoData")
    except NoData:
        pass


def test_av_hits_nightly_hit_is_mode_scan():
    _tmp_dirs()
    _hits("beefy", INDEX, now=LATER - 600)
    infected = "/scan/ssd-hot/torrents/complete/Some.Show.S01/Some.Show.S01E01.mkv\tWin.Trojan.X-1\n"
    assert _hit_series(_hits("beefy", INDEX + NEW_HIT, infected))[0][1]["mode"] == "scan"


# beefy's clamav-hook.py logs who quarantined a file (time, mode, title, path, signature) to clamav-hits.tsv.
HITS_LOG = "2026-10-27T10:00:00+01:00\thook\tSome Show S01 Pack\t/scan/ssd-hot/torrents/complete/Some.Show.S01/Some.Show.S01E01.mkv\tWin.Trojan.X-1\n"


def test_av_hits_mode_and_title_from_the_hook_log_beat_the_guess():
    _tmp_dirs()
    _hits("beefy", INDEX, now=LATER - 600)
    labels = _hit_series(_hits("beefy", INDEX + NEW_HIT, hits=HITS_LOG))[0][1]
    assert (labels["mode"], labels["title"]) == ("hook", "Some Show S01 Pack")


def test_av_hits_hook_log_counts_per_logged_mode():
    _tmp_dirs()
    _hits("beefy", INDEX, now=LATER - 600)
    samples = _hits("beefy", INDEX + NEW_HIT, hits=HITS_LOG)
    assert {s[1]["mode"]: s[2] for s in samples if s[0] == "clamav_quarantine_hits_24h"} == {"scan": 0, "hook": 1, "queue": 0}


def test_av_hits_log_line_of_another_hit_is_ignored():
    _tmp_dirs()
    _hits("beefy", INDEX, now=LATER - 600)
    other = HITS_LOG.replace("10:00:00", "09:59:59")
    labels = _hit_series(_hits("beefy", INDEX + NEW_HIT, hits=other))[0][1]
    assert (labels["mode"], labels["title"]) == ("queue", "Some.Show.S01")


def test_av_hits_empty_title_or_malformed_log_falls_back_to_the_guess():
    _tmp_dirs()
    _hits("beefy", INDEX, now=LATER - 600)
    log = HITS_LOG.replace("Some Show S01 Pack", "") + "garbage\n\tqueue\n"
    labels = _hit_series(_hits("beefy", INDEX + NEW_HIT, hits=log))[0][1]
    assert (labels["mode"], labels["title"]) == ("hook", "Some.Show.S01")


def test_av_hits_beefy_reads_the_hook_log_next_to_the_hook_metrics():
    assert security_scan.AV_PATHS["beefy"]["hits"] == "/var/lib/clamav-scan/textfile/clamav-hits.tsv"


def test_ssh_alias_never_wakes_when_asked_not_to():
    import datetime
    at = datetime.datetime(2026, 10, 27, 4, 20)
    assert security_scan.ssh_alias("beefy", at, wake=False) == "beefy-direct"
    assert security_scan.ssh_alias("tower", at, wake=False) == "tower-direct"


MEDIA_PROM = ('# HELP media_language_missing_since_timestamp_seconds x\n# TYPE media_language_missing_since_timestamp_seconds gauge\n'
              'media_language_missing_since_timestamp_seconds{app="radarr",failed="0",language="Swiss German",title="The Ring Thing (2004)"} 1792753017\n'
              '# TYPE media_language_missing_last_run_timestamp_seconds gauge\nmedia_language_missing_last_run_timestamp_seconds 1792771822\n')


def test_media_republishes_only_media_language_samples():
    d = _tmp_dirs()
    assert collect_media("beefy", lambda: MEDIA_PROM + "node_load1 3\nmedia_language_bad{x=\"1\"} nope\n") == []
    assert (d / "textfile" / "media_language_beefy.prom").read_text() == MEDIA_PROM


def test_media_without_waiting_titles_still_publishes_the_run():
    d = _tmp_dirs()
    run_only = "# TYPE media_language_missing_last_run_timestamp_seconds gauge\nmedia_language_missing_last_run_timestamp_seconds 1\n"
    collect_media("beefy", lambda: run_only)
    assert (d / "textfile" / "media_language_beefy.prom").read_text() == run_only


def test_media_missing_or_empty_file_is_no_data_and_keeps_old_file():
    d = _tmp_dirs()
    (d / "textfile" / "media_language_beefy.prom").write_text("old\n")
    for text in (None, "foo 1\n"):
        try:
            collect_media("beefy", lambda: text)
            raise AssertionError("expected NoData")
        except NoData:
            pass
    assert (d / "textfile" / "media_language_beefy.prom").read_text() == "old\n"


def test_guarded_no_data_is_neither_error_nor_unreachable():
    d = _tmp_dirs()
    def _raise():
        raise NoData("not there yet")
    security_scan.guarded("av-tower", _raise, host="tower")
    status = (d / "textfile" / "security_av_tower_status.prom").read_text()
    assert 'security_scan_errors{subject="av-tower"} 0' in status
    assert 'security_scan_host_unreachable{subject="av-tower"} 0' in status
    assert not (d / "textfile" / "security_av_tower.prom").exists()


# --- failed logins -----------------------------------------------------------

import calendar  # noqa: E402

NOW = calendar.timegm((2026, 10, 19, 20, 0, 0))   # 22:00 CEST

AUTH_LOG = """2026-10-19T21:47:53.452034+02:00 beefy sshd-session[1]: Invalid user admin from 203.0.113.9 port 4000
2026-10-19T21:47:55.000000+02:00 beefy sshd-session[1]: Failed password for invalid user admin from 203.0.113.9 port 4000 ssh2
2026-10-19T21:48:00.000000+02:00 beefy sshd-session[2]: pam_unix(sshd:auth): authentication failure; logname= uid=0 rhost=203.0.113.9
2026-10-19T21:49:00.000000+02:00 beefy sshd-session[3]: Accepted publickey for buntu from 192.168.1.2 port 1 ssh2
2026-10-19T21:50:00.000000+02:00 beefy sudo: pam_unix(sudo:auth): authentication failure; logname=buntu
2026-10-17T21:47:53.000000+02:00 beefy sshd-session[9]: Failed password for root from 203.0.113.9 port 4000 ssh2
"""


def test_failed_logins_counts_the_three_patterns_in_window():
    assert count_failed_logins(AUTH_LOG, NOW) == 3


def test_failed_logins_ignores_accepted_and_non_sshd_lines():
    assert count_failed_logins(AUTH_LOG.splitlines()[3] + "\n" + AUTH_LOG.splitlines()[4], NOW) == 0


def test_failed_logins_ignores_lines_older_than_24h():
    assert count_failed_logins(AUTH_LOG.splitlines()[5], NOW) == 0


def test_failed_logins_reads_journal_short_iso():
    line = "2026-10-19T21:00:01+0200 fastpi sshd[77]: Failed password for pi from 192.168.1.50 port 2 ssh2"
    assert count_failed_logins(line, NOW) == 1


def test_failed_logins_reads_classic_syslog_in_local_time():
    import time as _t
    stamp = _t.strftime("%b %d %H:%M:%S", _t.localtime(NOW - 3600))
    old = _t.strftime("%b %d %H:%M:%S", _t.localtime(NOW - 2 * 86400))
    text = (f"{stamp} Tower sshd-session[5]: Invalid user test from 192.168.1.60 port 3\n"
            f"{old} Tower sshd-session[5]: Invalid user test from 192.168.1.60 port 3\n")
    assert count_failed_logins(text, NOW) == 1


def test_failed_logins_syslog_year_rollover():
    # On 1 January a "Dec 31" line belongs to last year, not to a date eleven months ahead.
    import time as _t
    new_year = _t.mktime((2027, 1, 1, 0, 30, 0, 0, 0, -1))
    assert count_failed_logins("Dec 31 23:50:00 Tower sshd[1]: Invalid user x from 1.2.3.4", new_year) == 1


def test_failed_logins_skips_unparseable_lines():
    assert count_failed_logins("-- No entries --\nsshd Failed password garbage\n", NOW) == 0


# --- successful SSH logins and file integrity ---------------------------------

def _ts_for(iso: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(iso).timestamp()


def test_classify_source_lan_vpn_tunnel_other():
    assert classify_source("192.168.1.102") == "lan"
    assert classify_source("10.24.5.5") == "vpn"
    assert classify_source("172.24.255.5") == "other"
    assert classify_source("10.8.0.4") == "vpn"
    assert classify_source("172.20.0.2") == "tunnel"
    assert classify_source("84.226.182.197") == "other"
    assert classify_source("172.18.0.9") == "other"
    assert classify_source("fe80::1") == "other"
    assert classify_source("not-an-ip") == "other"


SSH_OK = """2026-10-23T09:00:00+0200 fastpi sshd-session[1]: Accepted publickey for pi from 192.168.1.102 port 5 ssh2: ED25519 SHA256:abc
2026-10-23T09:10:00+0200 fastpi sshd-session[2]: Accepted publickey for pi from 192.168.1.102 port 6 ssh2: ED25519 SHA256:abc
2026-10-23T10:00:00+0200 fastpi sshd-session[3]: Accepted publickey for deploy from 172.20.0.2 port 7 ssh2: ED25519 SHA256:def
2026-10-23T10:01:00+0200 fastpi sshd-session[4]: Failed password for pi from 192.168.1.5 port 8 ssh2
2026-10-21T10:01:00+0200 fastpi sshd-session[5]: Accepted publickey for pi from 1.2.3.4 port 8 ssh2: ED25519 SHA256:old
"""
SSH_NOW = _ts_for("2026-10-23T12:00:00+02:00")


def test_parse_ssh_logins_groups_by_user_and_class():
    assert parse_ssh_logins(SSH_OK, SSH_NOW) == {
        ("pi", "lan"): (2, _ts_for("2026-10-23T09:10:00+02:00")),
        ("deploy", "tunnel"): (1, _ts_for("2026-10-23T10:00:00+02:00")),
    }


def test_parse_ssh_logins_ignores_failures_and_old_lines():
    assert parse_ssh_logins("\n".join(SSH_OK.splitlines()[3:]), SSH_NOW) == {}


def test_parse_ssh_logins_counts_password_logins_too():
    line = "2026-10-23T11:00:00+0200 fastpi sshd[1]: Accepted password for pi from 8.8.8.8 port 1 ssh2"
    assert list(parse_ssh_logins(line, SSH_NOW)) == [("pi", "other")]


def test_hash_file_is_sha256_hex():
    import tempfile
    with tempfile.NamedTemporaryFile() as f:
        f.write(b"abc")
        f.flush()
        assert hash_file(Path(f.name)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_integrity_diff_states():
    base = {"/a": "1", "/b": "2", "/gone": "3"}
    cur = {"/a": "1", "/b": "changed", "/new": "4"}
    assert integrity_diff(base, cur) == {"/a": "ok", "/b": "changed", "/new": "new", "/gone": "missing"}


def test_integrity_samples_export_only_a_hash_prefix():
    cur = {"/a": "f" * 64, "/b": "e" * 64}
    out = integrity_samples("fastpi", {"/a": "ok", "/b": "changed", "/gone": "missing"}, cur)
    changed = {l["path"]: v for n, l, v in out if n == "security_integrity_changed"}
    assert changed == {"/a": 0, "/b": 1, "/gone": 1}
    info = [l for n, l, v in out if n == "security_integrity_file_info"]
    assert {"host": "fastpi", "path": "/a", "sha256_prefix": "f" * 12} in info
    assert not any("f" * 13 in str(l) for _, l, _ in out)
    assert ("security_integrity_files", {"host": "fastpi"}, 2) in out


def test_integrity_targets_expands_globs():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "x").mkdir()
        (Path(d) / "x" / "k").write_text("1")
        (Path(d) / "y").write_text("2")
        got = integrity_targets([f"{d}/*/k", f"{d}/*/nope", f"{d}/y", f"{d}/missing"])
        assert got == sorted([f"{d}/x/k", f"{d}/y"])


# --- audit: rkhunter, chkrootkit, Lynis --------------------------------------

RKHUNTER = """Warning: The command '/usr/bin/lwp-request' has been replaced by a script: /usr/bin/lwp-request: Perl script text executable
Warning: The SSH configuration option 'PermitRootLogin' has not been set.
         The default value may be 'yes', to allow root access.
Warning: Suspicious file types found in /dev:
         /dev/shm/lttng-ust-wait-8: data
Warning: Hidden file found: /etc/.fstab: ASCII text
"""

CHKROOTKIT = """Checking `date'... INFECTED
WARNING: The following suspicious files and directories were found:
/usr/lib/debug/.build-id

WARNING: Possible Linux BPFDoor Malware installed:
/proc/1341/stack
chkproc: Warning: Possible LKM Trojan installed
"""


def test_rkhunter_one_finding_per_warning_line():
    assert parse_rkhunter(RKHUNTER) == [
        "Warning: The command '/usr/bin/lwp-request' has been replaced by a script: /usr/bin/lwp-request: Perl script text executable",
        "Warning: The SSH configuration option 'PermitRootLogin' has not been set.",
        "Warning: Suspicious file types found in /dev:",
        "Warning: Hidden file found: /etc/.fstab: ASCII text",
    ]


def test_rkhunter_clean_run_is_empty():
    assert parse_rkhunter("") == []


def test_chkrootkit_findings_are_headers_and_infected_lines_not_the_listed_paths():
    # Listed paths change every run (/proc/<pid>, files in /tmp); the header is the stable identity.
    assert parse_chkrootkit(CHKROOTKIT) == [
        "Checking `date'... INFECTED",
        "WARNING: The following suspicious files and directories were found:",
        "WARNING: Possible Linux BPFDoor Malware installed:",
        "chkproc: Warning: Possible LKM Trojan installed",
    ]


CHK_SCRATCH = """WARNING: Possible Linux.Xor.DDoS installed:
/tmp/beefy-boot-test.sh
/tmp/claude-1000/x/scratchpad/run.py

WARNING: The following suspicious PHP files were found:
/tmp/claude-1000/x/scratchpad/page.php

WARNING: output from chkwtmp:
deleted 3 entries 2025-01-01

WARNING: Output from ifpromisc:
eth0: PACKET SNIFFER(/usr/sbin/dhcpcd[512])
"""


def test_chkrootkit_detail_keeps_the_listed_paths_per_category():
    detail = parse_chkrootkit_detail(CHK_SCRATCH)
    assert detail[0] == ("WARNING: Possible Linux.Xor.DDoS installed:",
                         ["/tmp/beefy-boot-test.sh", "/tmp/claude-1000/x/scratchpad/run.py"])
    assert detail[2] == ("WARNING: output from chkwtmp:", ["deleted 3 entries 2025-01-01"])


def test_chkrootkit_scratch_files_alone_do_not_make_a_xor_or_php_finding():
    # Scratch scripts in /tmp/claude-* and /tmp/*.sh change daily and are not malware.
    assert parse_chkrootkit(CHK_SCRATCH) == [
        "WARNING: output from chkwtmp:",
        "WARNING: Output from ifpromisc:",
    ]


def test_chkrootkit_xor_finding_stays_when_another_path_is_listed():
    text = "WARNING: Possible Linux.Xor.DDoS installed:\n/tmp/claude-1000/a.sh\n/var/tmp/evil\n"
    assert parse_chkrootkit(text) == ["WARNING: Possible Linux.Xor.DDoS installed:"]


def test_chkrootkit_ignore_list_does_not_apply_to_other_categories():
    text = "WARNING: The following suspicious files and directories were found:\n/tmp/claude-1000/.x\n"
    assert parse_chkrootkit(text) == ["WARNING: The following suspicious files and directories were found:"]


def test_audit_report_lists_paths_under_each_finding():
    d = _tmp_dirs()
    audit_samples("fastpi", AUDIT_OUT.replace(CHKROOTKIT, CHK_SCRATCH))
    rep = (d / "state" / "audit-fastpi.txt").read_text()
    assert "        /tmp/claude-1000/x/scratchpad/page.php" in rep
    assert "ignored  WARNING: The following suspicious PHP files were found:" in rep


def test_new_findings_are_the_ones_not_accepted():
    assert new_findings(["a", "b", "c"], {"a", "c"}) == ["b"]
    assert new_findings(["a"], {"a", "gone"}) == []


def test_lynis_report_gives_index_and_warning_count():
    rep = "report_version=1.0\nhardening_index=64\nwarning[]=KRNL-5830|Reboot|-|-|\nwarning[]=DBS-1828|x|y|z|\nsuggestion[]=A|b|\n"
    assert parse_lynis_report(rep) == (64, 2)


def test_lynis_report_without_index_is_an_error():
    try:
        parse_lynis_report("warning[]=X|y|\n")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_audit_output_splits_tool_sections_and_return_codes():
    text = ("### rkhunter\nWarning: x\n### rc 1\n"
            "### chkrootkit\n### rc 0\n"
            "### lynis\n### rc 0\nhardening_index=60\n")
    assert parse_audit_output(text) == {
        "rkhunter": ("Warning: x\n", 1),
        "chkrootkit": ("", 0),
        "lynis": ("hardening_index=60\n", 0),
    }


AUDIT_OUT = ("### rkhunter\n" + RKHUNTER + "### rc 1\n### chkrootkit\n" + CHKROOTKIT +
             "### rc 0\n### lynis\n### rc 0\nhardening_index=64\nwarning[]=KRNL-5830|Reboot|-|-|\n")


def _metric(samples, name, **labels):
    return [v for n, lab, v in samples if n == name and all(lab.get(k) == x for k, x in labels.items())]


def test_audit_first_run_accepts_current_findings_as_baseline():
    d = _tmp_dirs()
    samples = audit_samples("beefy", AUDIT_OUT)
    assert _metric(samples, "security_rootkit_warnings", host="beefy", tool="rkhunter") == [0]
    assert _metric(samples, "security_rootkit_findings", host="beefy", tool="rkhunter") == [4]
    assert _metric(samples, "security_rootkit_findings", host="beefy", tool="chkrootkit") == [4]
    assert _metric(samples, "security_lynis_hardening_index", host="beefy") == [64]
    assert _metric(samples, "security_lynis_warnings", host="beefy") == [1]
    assert (d / "state" / "audit-accepted-beefy-rkhunter.txt").exists()


def test_audit_later_run_counts_only_new_findings():
    d = _tmp_dirs()
    audit_samples("beefy", AUDIT_OUT)
    out = AUDIT_OUT.replace("### rc 0\n### lynis", "Checking `ls'... INFECTED\n### rc 0\n### lynis")
    samples = audit_samples("beefy", out)
    assert _metric(samples, "security_rootkit_warnings", host="beefy", tool="chkrootkit") == [1]
    assert _metric(samples, "security_rootkit_warnings", host="beefy", tool="rkhunter") == [0]
    assert "NEW      Checking `ls'... INFECTED" in (d / "state" / "audit-beefy.txt").read_text()


def test_audit_tool_failure_raises():
    _tmp_dirs()
    try:
        audit_samples("beefy", AUDIT_OUT.replace("### rc 1", "### rc 127"))
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


# --- Unraid OS / plugin updates ----------------------------------------------

UNRAID_OUT = """version="7.3.2"
### plugins
/var/log/plugins/community.applications.plg:<!ENTITY version   "2026.07.21">
/var/log/plugins/fix.common.problems.plg:<!ENTITY version "2026.05.16">
/var/log/plugins/tips.and.tweaks.plg:<!ENTITY version\t"2025.03.06">
/var/log/plugins/unRAIDServer.plg:<!ENTITY version   "7.3.2">
/var/log/plugins/user.scripts.plg:<!ENTITY version "2025.06.21">
/tmp/plugins/community.applications.plg:<!ENTITY version   "2026.07.21">
/tmp/plugins/fix.common.problems.plg:<!ENTITY version   "2026.10.12">
/tmp/plugins/tips.and.tweaks.plg:<!ENTITY version\t"2025.03.06">
### os
{
  "version": "7.3.3",
  "name": "Unraid 7.3.3",
  "isNewer": true,
  "isEligible": true
}
"""


def test_unraid_check_reads_os_and_plugin_versions():
    r = parse_unraid_check(UNRAID_OUT)
    assert r["os"] == ("7.3.2", "7.3.3", True)
    assert r["plugins"] == {
        "community.applications": ("2026.07.21", "2026.07.21"),
        "fix.common.problems": ("2026.05.16", "2026.10.12"),
        "tips.and.tweaks": ("2025.03.06", "2025.03.06"),
        "user.scripts": ("2025.06.21", None),
    }


def test_unraid_os_plugin_is_not_a_plugin_update():
    assert "unRAIDServer" not in parse_unraid_check(UNRAID_OUT)["plugins"]


def test_unraid_samples_flag_only_newer_versions():
    samples = unraid_samples(parse_unraid_check(UNRAID_OUT))
    assert ("security_unraid_os_update", {"installed": "7.3.2", "available": "7.3.3"}, 1) in samples
    assert ("security_unraid_plugin_update", {"plugin": "fix.common.problems"}, 1) in samples
    assert ("security_unraid_plugin_update", {"plugin": "community.applications"}, 0) in samples
    assert ("security_unraid_plugin_update", {"plugin": "user.scripts"}, 0) in samples


def test_unraid_os_current_has_available_equal_installed():
    out = UNRAID_OUT.replace('"isNewer": true', '"isNewer": false').replace('"version": "7.3.3"', '"version": "7.3.2"')
    samples = unraid_samples(parse_unraid_check(out))
    assert ("security_unraid_os_update", {"installed": "7.3.2", "available": "7.3.2"}, 0) in samples


def test_unraid_check_error_response_raises():
    try:
        parse_unraid_check(UNRAID_OUT.split("### os")[0] + '### os\n{"error": "Could not resolve host"}\n')
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


# --- Cup per-server image updates --------------------------------------------

def _img(server, ref, result):
    return {"server": server, "reference": ref, "result": result}


CUP = {"images": [
    _img("beefy", "lscr.io/linuxserver/qbittorrent:5.2.4", {"error": None, "has_update": True,
         "info": {"type": "version", "version_update_type": "major"}}),
    _img(None, "caddy:2.10-alpine", {"error": None, "has_update": True,
         "info": {"type": "version", "version_update_type": "minor"}}),
    _img(None, "traefik:latest", {"error": None, "has_update": True, "info": {"type": "digest"}}),
    _img(None, "postgres:16", {"error": None, "has_update": False, "info": None}),
    _img(None, "wg-easy:rollback-v14", {"error": "Unauthorized", "has_update": None, "info": None}),
    _img("tower", "ghcr.io/sergi0g/cup:v3.5.1", {"error": None, "has_update": False, "info": None}),
]}


def test_cup_counts_updates_per_server_and_type():
    hosts, _ = parse_cup(CUP)
    assert hosts["fastpi"] == {"all": 2, "major": 0, "minor": 1, "patch": 0, "digest": 1, "unknown": 1}
    assert hosts["beefy"] == {"all": 1, "major": 1, "minor": 0, "patch": 0, "digest": 0, "unknown": 0}
    assert hosts["tower"]["all"] == 0


def test_cup_lists_each_image_with_an_update():
    _, info = parse_cup(CUP)
    assert sorted(info) == [
        ("beefy", "lscr.io/linuxserver/qbittorrent:5.2.4", "major"),
        ("fastpi", "caddy:2.10-alpine", "minor"),
        ("fastpi", "traefik:latest", "digest"),
    ]


def test_cup_server_missing_from_json_is_absent_not_zero():
    # A host asleep at Cup's refresh is left out of the JSON; zero would claim it is up to date.
    hosts, _ = parse_cup({"images": [i for i in CUP["images"] if i["server"] != "tower"]})
    assert "tower" not in hosts


def test_cup_same_reference_on_two_hosts_counts_on_both():
    hosts, info = parse_cup({"images": [
        _img(None, "alpine/socat:latest", {"has_update": True, "info": {"type": "digest"}}),
        _img("beefy", "alpine/socat:latest", {"has_update": True, "info": {"type": "digest"}})]})
    assert hosts["fastpi"]["digest"] == 1 and hosts["beefy"]["digest"] == 1
    assert len(info) == 2



# --- images: lists first, Trivy afterwards -----------------------------------

def test_image_lists_of_all_hosts_are_read_before_any_scan():
    # beefy powers off around 04:26: its list (ssh) must be in hand before the long Trivy part starts.
    calls = []
    def lister(h):
        calls.append(("list", h))
        return [f"{h}-img"]
    def scan(h, images):
        calls.append(("scan", h, tuple(images)))
    scan_all_images(("fastpi", "beefy", "tower"), lister, scan)
    assert [c[0] for c in calls] == ["list", "list", "list", "scan", "scan", "scan"]
    assert ("scan", "beefy", ("beefy-img",)) in calls


def test_image_list_failure_reaches_that_hosts_scan_only():
    got = {}
    def lister(h):
        if h == "tower":
            raise RuntimeError("tower asleep")
        return [h]
    def scan(h, images):
        got[h] = images
    scan_all_images(("fastpi", "tower"), lister, scan)
    assert got["fastpi"] == ["fastpi"]
    assert isinstance(got["tower"], RuntimeError)


def test_beefy_and_tower_are_scanned_from_fastpi():
    # Trivy for these runs on fastpi against the registry: no ssh after the list is read.
    assert set(security_scan.REMOTE_SCAN_HOSTS) == {"beefy", "tower"}


def test_remote_docker_needs_sudo_on_beefy_only():
    # buntu is not in beefy's docker group (2026-10-23); tower's ssh user is root.
    assert security_scan.docker_cmd("beefy") == "sudo docker"
    assert security_scan.docker_cmd("tower") == "docker"


def test_image_without_repo_digest_is_local_only():
    assert image_only_local("clamav-local:latest")
    assert not image_only_local("lscr.io/linuxserver/radarr@sha256:ea68")


def test_registry_refusal_means_local_only():
    # clamav-local carries a repo digest but exists in no registry: Docker Hub answers UNAUTHORIZED.
    err = "clamav-local/manifests/sha256:a06: UNAUTHORIZED: authentication required; [map[Action:pull Name:library/clamav-local]]"
    assert image_only_local("clamav-local@sha256:a06", err)
    assert image_only_local("x@sha256:1", "MANIFEST_UNKNOWN: manifest unknown")
    assert image_only_local("x@sha256:1", "NAME_UNKNOWN: repository name not known to registry")


def test_other_trivy_failures_stay_unscannable():
    assert not image_only_local("x@sha256:1", "context deadline exceeded")
    assert not image_only_local("x@sha256:1", "")

def test_cup_missing_host_asleep_is_skipped():
    r = cup_missing_reason("tower", {"tower": False})
    assert r.startswith("tower not reachable") and "skipped" in r


def test_cup_missing_host_awake_names_the_agent():
    r = cup_missing_reason("beefy", {"beefy": True})
    assert r.startswith("beefy") and "agent" in r and "skipped" not in r


def test_cup_missing_fastpi_has_no_awake_entry():
    assert "agent" in cup_missing_reason("fastpi", {"beefy": False})


# --- local images: base images from Dockerfiles ----------------------------

def test_dockerfile_bases_plain_and_aliased():
    text = "FROM golang:1.25-alpine AS build\nRUN x\nFROM alpine:3.20\nCOPY --from=build /a /a\n"
    assert dockerfile_bases(text) == ["golang:1.25-alpine", "alpine:3.20"]


def test_dockerfile_bases_skip_scratch_stage_refs_and_variables():
    text = "FROM --platform=linux/amd64 python:3.13-alpine AS base\nFROM base AS build\nFROM scratch\nFROM ${IMG}\n"
    assert dockerfile_bases(text) == ["python:3.13-alpine"]


def test_dockerfile_bases_keep_digest_pin_and_dedupe():
    text = "FROM ghcr.io/linuxserver/mods@sha256:693f AS opencl\nfrom lscr.io/linuxserver/jellyfin:12.2\nFROM lscr.io/linuxserver/jellyfin:12.2\n"
    assert dockerfile_bases(text) == ["ghcr.io/linuxserver/mods@sha256:693f", "lscr.io/linuxserver/jellyfin:12.2"]


def test_parse_local_bases_maps_image_to_bases():
    out = "## clamav-local:latest\nFROM alpine:latest\n## ryot-go:local\nFROM docker.io/library/python:3.13-alpine\n## orphan:local\n"
    assert parse_local_bases(out) == {
        "clamav-local:latest": ["alpine:latest"],
        "ryot-go:local": ["docker.io/library/python:3.13-alpine"],
    }


# --- code scan: image references from the repo -----------------------------

def test_parse_env_ignores_comments_and_quotes():
    assert parse_env("# c\nA=1\nB='x y'\nexport C=\"z\"\n\nbad line\n") == {"A": "1", "B": "x y", "C": "z"}


def test_resolve_vars_defaults_and_required():
    env = {"TAG": "v1", "EMPTY": ""}
    assert resolve_vars("img:${TAG}", env) == "img:v1"
    assert resolve_vars("${IMG:-ghcr.io/a/b}:${TAG:?set TAG}", env) == "ghcr.io/a/b:v1"
    assert resolve_vars("x:${EMPTY:-d}", env) == "x:d"
    assert resolve_vars("x:$TAG", env) == "x:v1"
    assert resolve_vars("x:${MISSING}", env) is None
    assert resolve_vars("x:${MISSING:?set it}", env) is None


def test_compose_images_skips_built_services_and_comments():
    text = (
        "services:\n"
        "# #### banner\n"
        "  web:\n"
        "    image: caddy:${CADDY_TAG}   # pinned\n"
        "  app:\n"
        "    build: .\n"
        "    image: app:local\n"
        "  db:\n"
        "    # image: old:1\n"
        "    image: \"postgres:18-alpine\"\n"
        "networks:\n"
        "  default:\n"
    )
    assert compose_images(text, {"CADDY_TAG": "2.11-alpine"}) == (["caddy:2.11-alpine", "postgres:18-alpine"], 0)


def test_compose_images_counts_unresolved():
    assert compose_images("services:\n  a:\n    image: x:${NOPE}\n", {}) == ([], 1)


def test_trivy_image_is_pinned_by_digest_everywhere():
    import re
    assert re.fullmatch(r"aquasec/trivy:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", security_scan.TRIVY_IMAGE)
    for host in security_scan.TRIVY_HOSTS:
        assert security_scan.TRIVY_IMAGE in security_scan._trivy_cmd(host, ["x"], attach_proxy=False)
    assert security_scan.TRIVY_IMAGE in security_scan._trivy_cmd("beefy", ["x"], attach_proxy=False)
    assert ":latest" not in " ".join(security_scan._trivy_cmd("fastpi", ["x"], attach_proxy=True))
    assert "aquasec/trivy:latest" not in Path(security_scan.__file__).read_text()


def test_code_image_refs_uses_env_then_example_and_dockerfile_bases():
    files = {
        "Docker/A/docker-compose.yaml": "services:\n  a:\n    image: a/b:${T}\n",
        "Docker/A/.env": "T=1.2\n",
        "Docker/A/.env.example": "T=9.9\n",
        "Docker/B/docker-compose.yaml": "services:\n  b:\n    image: c:${T}\n",
        "Docker/B/.env.example": "T=3\n",
        "Docker/B/Dockerfile": "FROM python:3.13-alpine AS build\nFROM build\n",
        "Docker/C/docker-compose.yaml": "services:\n  c1:\n    build: ./c\n    image: c-local:latest\n  c2:\n    image: c-local:latest\n",
        "Docker/C/d/Dockerfile": "FROM c-local:latest\n",
        "Docker/_Deprecated/X/docker-compose.yaml": "services:\n  x:\n    image: old:1\n",
        "Docker/docker-compose.yaml": "services:\n  s:\n    image: sample/image:latest\n",
    }
    refs, unresolved = code_image_refs(files)
    assert refs == ["a/b:1.2", "c:3", "python:3.13-alpine"] and unresolved == 0


def _report(*vulns):
    return {"Results": [{"Target": "t", "Vulnerabilities": [
        {"VulnerabilityID": i, "PkgName": p, "Severity": s, "FixedVersion": f} for i, p, s, f in vulns]}]}


def test_fixable_findings_only_critical_high_with_fix():
    r = _report(("CVE-1", "openssl", "CRITICAL", "3.1"), ("CVE-2", "zlib", "HIGH", ""),
                ("CVE-3", "curl", "MEDIUM", "8"), ("CVE-4", "glibc", "HIGH", "2.40"))
    assert fixable_findings(r) == {("CVE-1", "openssl", "CRITICAL"), ("CVE-4", "glibc", "HIGH")}


def test_diff_findings_first_run_is_baseline():
    seen, new = diff_findings(None, {"img|CVE-1|openssl": "CRITICAL"}, now=100)
    assert new == [] and seen == {"img|CVE-1|openssl": {"severity": "CRITICAL", "first_seen": 0}}


def test_diff_findings_new_then_known_and_pruned():
    seen = {"img|CVE-1|openssl": {"severity": "CRITICAL", "first_seen": 0},
            "gone|CVE-9|x": {"severity": "HIGH", "first_seen": 0}}
    seen2, new = diff_findings(seen, {"img|CVE-1|openssl": "CRITICAL", "img|CVE-5|curl": "HIGH"}, now=500)
    assert new == ["img|CVE-5|curl"]
    assert seen2 == {"img|CVE-1|openssl": {"severity": "CRITICAL", "first_seen": 0},
                     "img|CVE-5|curl": {"severity": "HIGH", "first_seen": 500}}
    assert diff_findings(seen2, {"img|CVE-1|openssl": "CRITICAL", "img|CVE-5|curl": "HIGH"}, now=900)[1] == []


def test_diff_findings_keeps_images_not_scanned_this_run():
    seen = {"down|CVE-1|x": {"severity": "HIGH", "first_seen": 0}}
    seen2, new = diff_findings(seen, {}, now=5, scanned={"other"})
    assert seen2 == seen and new == []
    assert diff_findings(seen, {}, now=5, scanned={"down"})[0] == {}


def test_baseline_new_images_accepts_the_backlog_of_an_image_new_to_the_scan():
    seen = {"old|CVE-1|a": {"severity": "HIGH", "first_seen": 0}}
    current = {"old|CVE-1|a": "HIGH", "old|CVE-2|b": "HIGH", "fresh|CVE-3|c": "CRITICAL"}
    out = baseline_new_images(seen, current, known={"old"})
    assert out == {"old|CVE-1|a": {"severity": "HIGH", "first_seen": 0},
                   "fresh|CVE-3|c": {"severity": "CRITICAL", "first_seen": 0}}
    assert diff_findings(out, current, now=7)[1] == ["old|CVE-2|b"]
    assert baseline_new_images(None, current, known=set()) is None


def test_new_vuln_samples_window_and_cap():
    seen = {f"img|CVE-{i}|p": {"severity": "HIGH", "first_seen": 1000 + i} for i in range(30)}
    seen["old|CVE-0|q"] = {"severity": "CRITICAL", "first_seen": 0}
    out = new_vuln_samples("code-fastpi", seen, now=1000 + 86400 + 4, cap=20)
    total = [s for s in out if s[0] == "security_new_vulns"]
    info = [s for s in out if s[0] == "security_new_vuln_info"]
    assert total == [("security_new_vulns", {"scope": "code-fastpi"}, 25)]
    assert len(info) == 20 and info[0][1] == {"scope": "code-fastpi", "image": "img", "id": "CVE-29", "pkg": "p", "severity": "HIGH"}


def test_sbom_refresh_order_missing_first_then_oldest_stale():
    index = {"a": 0, "b": 100, "c": 90000}
    assert sbom_refresh_order(["a", "b", "c", "d"], index, now=90000, max_age=86400, budget=2) == ["d", "a"]
    assert sbom_refresh_order(["c"], index, now=90000, max_age=86400, budget=4) == []


def test_refresh_sboms_marks_registry_missing_ref_local_not_failed():
    import contextlib, io, subprocess, tempfile
    saved = (security_scan._trivy_mounted, security_scan.SBOM_DIR)
    try:
        security_scan.SBOM_DIR = Path(tempfile.mkdtemp())
        security_scan._trivy_mounted = lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "UNAUTHORIZED: authentication required")
        index, err = {}, io.StringIO()
        with contextlib.redirect_stderr(err):
            security_scan.refresh_sboms("linux/arm64", ["stonks:latest"], index)
        assert index["linux/arm64|stonks:latest"]["local"] is True
        assert "sbom failed" not in err.getvalue() and "local-only" in err.getvalue()
    finally:
        security_scan._trivy_mounted, security_scan.SBOM_DIR = saved

def test_ssh_alias_wakes_beefy_only_inside_its_window():
    import datetime as dt
    at = lambda h, m: dt.datetime(2026, 10, 24, h, m)
    assert security_scan.ssh_alias("beefy", at(4, 20)) == "beefy"
    assert security_scan.ssh_alias("beefy", at(5, 40)) == "beefy-direct"
    assert security_scan.ssh_alias("beefy", at(3, 59)) == "beefy-direct"
    assert security_scan.ssh_alias("tower", at(4, 20)) == "tower-direct"
    assert security_scan.ssh_alias("fastpi", at(5, 40)) == "fastpi"

UPDATES_PROM = ('# HELP auto_update_result x\n# TYPE auto_update_result gauge\n'
                'auto_update_result{host="beefy",project="Cup-Agent",tier="auto",ref="alpine/socat:latest",result="updated",from="a",to="b"} 1\n'
                '# HELP auto_update_omitted y\n# TYPE auto_update_omitted gauge\nauto_update_omitted{host="beefy"} 0\n'
                '# TYPE auto_update_last_run_timestamp_seconds gauge\nauto_update_last_run_timestamp_seconds{host="beefy"} 1792771822\n')


def test_updates_republishes_only_this_hosts_samples_without_help():
    d = _tmp_dirs()
    foreign = 'auto_update_result{host="fastpi",project="X",result="updated"} 1\nauto_update_omitted 3\nnode_load1 2\n'
    assert collect_updates("beefy", lambda: UPDATES_PROM + foreign) == []
    out = (d / "textfile" / "auto_update_beefy.prom").read_text()
    assert "# HELP" not in out and 'host="fastpi"' not in out and "auto_update_omitted 3" not in out and "node_load1" not in out
    assert 'auto_update_result{host="beefy",project="Cup-Agent"' in out
    assert 'auto_update_omitted{host="beefy"} 0' in out and 'auto_update_last_run_timestamp_seconds{host="beefy"} 1792771822' in out
    assert out.count("# TYPE auto_update_result gauge") == 1


def test_updates_missing_or_foreign_only_file_is_no_data_and_keeps_old_file():
    d = _tmp_dirs()
    (d / "textfile" / "auto_update_beefy.prom").write_text("old\n")
    for text in (None, "auto_update_omitted 1\n", 'auto_update_result{host="fastpi"} 1\n'):
        try:
            collect_updates("beefy", lambda: text)
            raise AssertionError("expected NoData")
        except NoData:
            pass
    assert (d / "textfile" / "auto_update_beefy.prom").read_text() == "old\n"


# --- Cup snapshots -----------------------------------------------------------

CUP_FULL = {"last_updated": "2026-10-25T09:38:45Z", "images": [
    {"server": None, "reference": "caddy:2.10", "in_use": True,
     "result": {"has_update": True, "info": {"type": "version", "version_update_type": "minor",
                                             "current_version": "2.10", "new_version": "2.11"}}},
    {"server": "beefy", "reference": "x:1", "in_use": False, "result": {"has_update": False, "info": None}},
]}


def test_cup_snapshot_rows_per_host_with_taken_at():
    from security_scan import cup_snapshots
    s = cup_snapshots(CUP_FULL)
    assert s["fastpi"]["taken_at"] == "2026-10-25T09:38:45Z"
    assert s["fastpi"]["images"] == [{"reference": "caddy:2.10", "in_use": True, "has_update": True, "type": "minor",
                                      "current": "2.10", "latest": "2.11"}]
    assert s["beefy"]["images"][0]["has_update"] is False and s["beefy"]["images"][0]["type"] == ""


def test_cup_snapshot_kept_when_host_missing_replaced_when_present():
    from security_scan import store_cup_snapshots
    d = _tmp_dirs()
    store_cup_snapshots(CUP_FULL)
    old = (d / "state" / "cup-snapshot-beefy.json").read_text()
    newer = {"last_updated": "2026-10-26T09:00:00Z", "images": [CUP_FULL["images"][0]]}
    present = store_cup_snapshots(newer)
    assert present == {"fastpi"}
    assert (d / "state" / "cup-snapshot-beefy.json").read_text() == old
    import json
    assert json.loads((d / "state" / "cup-snapshot-fastpi.json").read_text())["taken_at"] == "2026-10-26T09:00:00Z"


# --- Dependency-Track feed ------------------------------------------------------

def test_dt_project_name_is_host_and_repo_version_is_tag():
    from security_scan import dt_project
    assert dt_project("fastpi", "traefik:v3.7.16") == ("fastpi/traefik", "v3.7.16")
    assert dt_project("beefy", "docker.io/library/postgres:18.6-alpine") == ("beefy/postgres", "18.6-alpine")
    assert dt_project("fastpi", "ghcr.io/goauthentik/server:2026.8.1") == ("fastpi/goauthentik/server", "2026.8.1")
    assert dt_project("fastpi", "aquasec/trivy:0.75.0@sha256:" + "a" * 64) == ("fastpi/aquasec/trivy", "0.75.0")
    assert dt_project("beefy", "lscr.io/linuxserver/qbittorrent@sha256:0123456789abcdef" + "0" * 48) == ("beefy/linuxserver/qbittorrent", "sha256:0123456789ab")
    assert dt_project("fastpi", "localhost:5000/x:1") == ("fastpi/x", "1")
    assert dt_project("fastpi", "beefy-waker") == ("fastpi/beefy-waker", "latest")


def test_parse_image_lines_ref_digest_id():
    from security_scan import parse_image_lines
    text = "traefik:v3|traefik@sha256:aa|sha256:11\nwaker:local||sha256:22\n\n"
    assert parse_image_lines(text) == [
        {"ref": "traefik:v3", "digest": "traefik@sha256:aa", "id": "sha256:11"},
        {"ref": "waker:local", "digest": "", "id": "sha256:22"},
    ]


def test_dt_plan_local_host_keys_by_image_id():
    from security_scan import dt_plan
    imgs = [{"ref": "traefik:v3", "digest": "traefik@sha256:aa", "id": "sha256:11"},
            {"ref": "waker:local", "digest": "", "id": "sha256:22"}]
    plan, skipped = dt_plan("fastpi", imgs, {})
    assert plan == [("fastpi/traefik", "v3", "sha256:11", "traefik:v3"),
                    ("fastpi/waker", "local", "sha256:22", "waker:local")]
    assert skipped == []


def test_dt_plan_remote_host_keys_by_digest_and_falls_back_to_base_image():
    from security_scan import dt_plan
    imgs = [{"ref": "postgres:18", "digest": "postgres@sha256:aa", "id": "sha256:11"},
            {"ref": "jellyfin-local:latest", "digest": "", "id": "sha256:22"},
            {"ref": "mystery:1", "digest": "", "id": "sha256:33"},
            {"ref": "0123456789ab", "digest": "x/y@sha256:bb", "id": "sha256:44"}]
    plan, skipped = dt_plan("beefy", imgs, {"jellyfin-local": ["build:1", "jellyfin/jellyfin:10.11.2"]})
    assert plan == [
        ("beefy/postgres", "18", "postgres@sha256:aa", "postgres@sha256:aa"),
        ("beefy/jellyfin-local", "latest (base jellyfin/jellyfin:10.11.2)", "base:jellyfin/jellyfin:10.11.2", "jellyfin/jellyfin:10.11.2"),
        ("beefy/x/y", "sha256:bb", "x/y@sha256:bb", "x/y@sha256:bb"),
    ]
    assert skipped == ["mystery:1"]


def test_dt_os_project_from_os_release():
    from security_scan import dt_os_project
    assert dt_os_project("beefy", 'PRETTY_NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="26.04"\n') == ("beefy/os", "ubuntu 26.04")


def test_dt_stale_only_projects_of_the_given_hosts_not_kept():
    from security_scan import dt_stale
    projects = [{"name": "fastpi", "version": None, "uuid": "p"},
                {"name": "fastpi/traefik", "version": "v3", "uuid": "a"},
                {"name": "fastpi/traefik", "version": "v2", "uuid": "b"},
                {"name": "beefy/postgres", "version": "17", "uuid": "c"},
                {"name": "other", "version": "1", "uuid": "d"}]
    assert [p["uuid"] for p in dt_stale(projects, {("fastpi/traefik", "v3")}, {"fastpi"})] == ["b"]


def test_dt_bom_payload_base64_with_parent_and_autocreate():
    import base64
    from security_scan import dt_bom_payload
    p = dt_bom_payload("fastpi/traefik", "v3", "parent-uuid", b'{"bomFormat":"CycloneDX"}')
    assert p["projectName"] == "fastpi/traefik" and p["projectVersion"] == "v3" and p["parentUUID"] == "parent-uuid"
    assert p["autoCreate"] is True and p["isLatest"] is True
    assert base64.b64decode(p["bom"]) == b'{"bomFormat":"CycloneDX"}'


class FakeDt:
    def __init__(self, projects):
        self.list, self.uploads, self.deleted, self.parents = projects, [], [], []

    def projects(self):
        return self.list

    def ensure_parent(self, name, projects):
        self.parents.append(name)
        return "parent-uuid"

    def upload(self, payload):
        assert payload["parentUUID"] == "parent-uuid"
        self.uploads.append((payload["projectName"], payload["projectVersion"]))

    def delete(self, uuid):
        self.deleted.append(uuid)


def test_collect_dt_uploads_changed_skips_unchanged_and_deletes_stale():
    import json
    from security_scan import collect_dt
    d = _tmp_dirs()
    (d / "state" / "dt-index.json").write_text(json.dumps({"fastpi/a|1": "k1", "fastpi/b|1": "old"}))
    dt = FakeDt([{"name": "fastpi/a", "version": "1", "uuid": "ua"}, {"name": "fastpi/b", "version": "1", "uuid": "ub"},
                 {"name": "fastpi/gone", "version": "1", "uuid": "ug"}, {"name": "beefy/x", "version": "1", "uuid": "ux"}])
    plan = [("fastpi/a", "1", "k1", "a:1"), ("fastpi/b", "1", "k2", "b:1"), ("fastpi/c", "1", "k3", "c:1"), ("fastpi/bad", "1", "k4", "bad:1")]
    built = []

    def sbom(key, src):
        built.append(src)
        return None if src == "bad:1" else b"{}"
    samples = collect_dt("fastpi", dt, plan, sbom, ("fastpi/os", "debian 12", "os-k", lambda: b"{}"))
    assert built == ["b:1", "c:1", "bad:1"]
    assert dt.uploads == [("fastpi/b", "1"), ("fastpi/c", "1"), ("fastpi/os", "debian 12")]
    assert dt.deleted == ["ug"] and dt.parents == ["fastpi"]
    assert ("security_dt_projects", {"host": "fastpi"}, 5) in samples
    assert ("security_dt_sbom_failed", {"host": "fastpi"}, 1) in samples
    idx = json.loads((d / "state" / "dt-index.json").read_text())
    assert idx["fastpi/b|1"] == "k2" and idx["fastpi/os|debian 12"] == "os-k" and "fastpi/bad|1" not in idx


def test_collect_dt_reuploads_when_project_vanished_from_dt():
    import json
    from security_scan import collect_dt
    d = _tmp_dirs()
    (d / "state" / "dt-index.json").write_text(json.dumps({"fastpi/a|1": "k1"}))
    dt = FakeDt([])
    collect_dt("fastpi", dt, [("fastpi/a", "1", "k1", "a:1")], lambda k, s: b"{}", None)
    assert dt.uploads == [("fastpi/a", "1")]


def test_trivy_sbom_cmd_own_cache_and_read_only_java_db_of_the_image_scan():
    from security_scan import _trivy_sbom_cmd
    cmd = _trivy_sbom_cmd(["image", "--image-src", "docker", "x:1"], socket_proxy=True)
    joined = " ".join(cmd)
    assert "/var/lib/security-scan/trivy-cache-dt:/root/.cache/trivy " in joined
    assert "/var/lib/security-scan/trivy-cache/java-db:/root/.cache/trivy/java-db:ro" in joined
    assert "--skip-java-db-update" in cmd and "--skip-db-update" in cmd and cmd[-1] == "x:1"
    assert "--network" in cmd and "--network" not in _trivy_sbom_cmd(["rootfs", "/rootfs"], rootfs=Path("/t"))

def test_dt_plan_digest_the_registry_refused_uses_the_base_image():
    from security_scan import dt_plan
    imgs = [{"ref": "clamav-local:latest", "digest": "clamav-local@sha256:cc", "id": "sha256:55"}]
    plan, _ = dt_plan("beefy", imgs, {"clamav-local": ["alpine:3.22"]}, local={"clamav-local@sha256:cc"})
    assert plan == [("beefy/clamav-local", "latest (base alpine:3.22)", "base:alpine:3.22", "alpine:3.22")]
    plan, _ = dt_plan("beefy", imgs, {"clamav-local": ["alpine:3.22"]})
    assert plan[0][2] == "clamav-local@sha256:cc"


def test_parse_os_dump_splits_files_and_drops_missing_ones():
    from security_scan import parse_os_dump
    text = "=== /etc/os-release\nID=ubuntu\n=== /etc/lsb-release\nDISTRIB_ID=Ubuntu\n=== /etc/missing\n=== /var/lib/dpkg/status\nPackage: a\n\nPackage: b\n"
    assert parse_os_dump(text) == {"etc/os-release": "ID=ubuntu\n", "etc/lsb-release": "DISTRIB_ID=Ubuntu\n",
                                   "var/lib/dpkg/status": "Package: a\n\nPackage: b\n"}


def _finding(purl, vid, state, detail="why", aliases=None, suppressed=True):
    f = {"component": {"purl": purl, "name": "x", "version": "1"},
         "vulnerability": {"vulnId": vid, "aliases": aliases or []}}
    if state:
        f["analysis"] = {"state": state, "isSuppressed": suppressed, "detail": detail}
    return f


def test_vex_statements_only_triage_decisions_with_purl():
    from security_scan import vex_statements
    st = vex_statements([
        _finding("pkg:deb/debian/a@1", "CVE-1", "NOT_AFFECTED", "not reachable"),
        _finding("pkg:deb/debian/b@1", "CVE-2", "FALSE_POSITIVE"),
        _finding("pkg:deb/debian/c@1", "CVE-3", "RESOLVED"),
        _finding("pkg:deb/debian/d@1", "CVE-4", "EXPLOITABLE"),
        _finding("pkg:deb/debian/e@1", "CVE-5", "IN_TRIAGE"),
        _finding("pkg:deb/debian/f@1", "CVE-6", None),
        _finding(None, "CVE-7", "NOT_AFFECTED"),
    ])
    got = {(s["vulnerability"]["name"], s["products"][0]["@id"], s["status"]) for s in st}
    assert got == {("CVE-1", "pkg:deb/debian/a@1", "not_affected"), ("CVE-2", "pkg:deb/debian/b@1", "not_affected"),
                   ("CVE-3", "pkg:deb/debian/c@1", "fixed")}
    assert all(s["justification"] for s in st if s["status"] == "not_affected")
    assert next(s for s in st if s["vulnerability"]["name"] == "CVE-1")["impact_statement"] == "not reachable"


def test_vex_statements_one_per_alias_id():
    from security_scan import vex_statements
    st = vex_statements([_finding("pkg:golang/x@1", "GHSA-1", "NOT_AFFECTED",
                                  aliases=[{"cveId": "CVE-9", "ghsaId": "GHSA-1"}, {"ghsaId": "GHSA-2"}])])
    assert sorted(s["vulnerability"]["name"] for s in st) == ["CVE-9", "GHSA-1", "GHSA-2"]


def test_build_openvex_document():
    from security_scan import build_openvex
    doc = build_openvex([{"vulnerability": {"name": "CVE-1"}}], 0)
    assert doc["@context"].startswith("https://openvex.dev/ns/") and doc["version"] == 1
    assert doc["timestamp"] == "1970-01-01T00:00:00Z" and doc["statements"] == [{"vulnerability": {"name": "CVE-1"}}]


class FakeVexDt:
    def __init__(self, by_uuid, broken=()):
        self.by_uuid, self.broken = by_uuid, set(broken)

    def findings(self, uuid):
        if uuid in self.broken:
            raise OSError("boom")
        return self.by_uuid[uuid]


def test_export_dt_vex_writes_per_project_file_and_cleans_up():
    import json
    from security_scan import export_dt_vex, vex_dir, vex_filename
    d = _tmp_dirs()
    vex_dir().mkdir()
    (vex_dir() / vex_filename("fastpi/old", "1")).write_text("{}")
    projects = [{"name": "fastpi/a", "version": "1", "uuid": "ua"}, {"name": "fastpi/b", "version": "1", "uuid": "ub"},
                {"name": "fastpi", "uuid": "parent"}]
    dt = FakeVexDt({"ua": [_finding("pkg:deb/a@1", "CVE-1", "NOT_AFFECTED")], "ub": [_finding("pkg:deb/b@1", "CVE-2", "IN_TRIAGE")]})
    samples = export_dt_vex(dt, projects)
    doc = json.loads((vex_dir() / vex_filename("fastpi/a", "1")).read_text())
    assert doc["statements"][0]["vulnerability"]["name"] == "CVE-1"
    assert not (vex_dir() / vex_filename("fastpi/b", "1")).exists()
    assert not (vex_dir() / vex_filename("fastpi/old", "1")).exists()
    assert ("security_dt_vex_statements", {}, 1) in samples and ("security_dt_vex_projects", {}, 1) in samples


def test_export_dt_vex_keeps_cached_file_of_a_failing_project():
    from security_scan import export_dt_vex, vex_dir, vex_filename
    _tmp_dirs()
    vex_dir().mkdir()
    keep = vex_dir() / vex_filename("fastpi/a", "1")
    keep.write_text('{"cached": true}')
    export_dt_vex(FakeVexDt({}, broken={"ua"}), [{"name": "fastpi/a", "version": "1", "uuid": "ua"}])
    assert keep.read_text() == '{"cached": true}'


def test_export_dt_vex_revoked_decision_removes_file():
    from security_scan import export_dt_vex, vex_dir, vex_filename
    _tmp_dirs()
    vex_dir().mkdir()
    f = vex_dir() / vex_filename("fastpi/a", "1")
    f.write_text("{}")
    export_dt_vex(FakeVexDt({"ua": [_finding("pkg:deb/a@1", "CVE-1", "IN_TRIAGE")]}),
                  [{"name": "fastpi/a", "version": "1", "uuid": "ua"}])
    assert not f.exists()


def test_vex_args_no_decisions_no_flag_and_cache_used_when_dt_is_gone():
    from security_scan import vex_args, vex_dir, vex_filename
    _tmp_dirs()
    assert vex_args("fastpi", "grafana/grafana:13.2.4") == []
    vex_dir().mkdir()
    (vex_dir() / vex_filename("fastpi/grafana/grafana", "13.2.4")).write_text("{}")
    assert vex_args("fastpi", "docker.io/grafana/grafana:13.2.4") == ["--vex", "/vex/" + vex_filename("fastpi/grafana/grafana", "13.2.4")]
    assert vex_args("beefy", "grafana/grafana:13.2.4") == []


def test_vex_args_digest_ref_found_through_dt_index():
    import json
    from security_scan import vex_args, vex_dir, vex_filename
    d = _tmp_dirs()
    vex_dir().mkdir()
    (d / "state" / "dt-index.json").write_text(json.dumps({"beefy/linuxserver/radarr|6.1.0": "linuxserver/radarr@sha256:abc"}))
    (vex_dir() / vex_filename("beefy/linuxserver/radarr", "6.1.0")).write_text("{}")
    assert vex_args("beefy", "linuxserver/radarr@sha256:abc") == ["--vex", "/vex/" + vex_filename("beefy/linuxserver/radarr", "6.1.0")]


def test_trivy_cmd_mounts_vex_dir_read_only():
    from security_scan import _trivy_cmd
    for host in ("fastpi", "beefy"):
        assert any(a.endswith(":/vex:ro") for a in _trivy_cmd(host, ["image", "x"], attach_proxy=False))


def test_sbom_match_script_passes_vex_only_for_images_with_decisions():
    from security_scan import match_script, vex_dir, vex_filename
    _tmp_dirs()
    vex_dir().mkdir()
    (vex_dir() / vex_filename("fastpi/grafana/grafana", "13.2.4")).write_text("{}")
    script = match_script({"n1": "grafana/grafana:13.2.4", "n2": "caddy:2"}, "fastpi")
    assert script.count("--vex") == 1 and "/vex/" + vex_filename("fastpi/grafana/grafana", "13.2.4") in script


def test_cup_asof_samples_read_the_cached_snapshot_of_each_host():
    import json
    from security_scan import cup_asof_samples
    d = _tmp_dirs()
    (d / "state" / "cup-snapshot-beefy.json").write_text(json.dumps({"taken_at": "2026-10-25T18:15:51Z", "images": []}))
    (d / "state" / "cup-snapshot-tower.json").write_text(json.dumps({"taken_at": "garbage", "images": []}))
    out = cup_asof_samples(("fastpi", "beefy", "tower"))
    assert out == [("security_cup_snapshot_timestamp_seconds", {"host": "beefy"}, 1792952151.0)]


def test_cup_asof_publishes_per_host_file_without_touching_the_data_file():
    import json
    from security_scan import publish_cup_asof
    d = _tmp_dirs()
    (d / "textfile" / "security_cup_beefy.prom").write_text("keep\n")
    (d / "state" / "cup-snapshot-beefy.json").write_text(json.dumps({"taken_at": "2026-10-25T18:15:51Z", "images": []}))
    publish_cup_asof(("fastpi", "beefy"))
    text = (d / "textfile" / "security_cup_asof_beefy.prom").read_text()
    assert 'security_cup_snapshot_timestamp_seconds{host="beefy"} 1792952151' in text
    assert (d / "textfile" / "security_cup_beefy.prom").read_text() == "keep\n"
    assert not (d / "textfile" / "security_cup_asof_fastpi.prom").exists()


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
