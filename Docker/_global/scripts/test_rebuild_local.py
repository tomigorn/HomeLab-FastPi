#!/usr/bin/env python3
"""Tests for rebuild_local.py's pure functions. Run: python3 test_rebuild_local.py"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rebuild_local import (  # noqa: E402
    DOCKER,
    alert_message,
    build_with_retry,
    bump_pins,
    commit_message,
    due,
    fingerprint,
    from_refs,
    guard_reason,
    image_env,
    old_fingerprint,
    pinned_tags,
    predates,
    parse_conf,
    project_dir,
    project_name,
    parse_env,
    run_test_step,
    render_prom,
    rollback_tag,
    sh,
    tar_content_digest,
    update_result,
)


def test_parse_conf_reads_entries_with_defaults():
    rows = parse_conf('[[image]]\nproject = "Tower-Waker"\nday = "Mon"\n\n'
                      '[[image]]\nproject = "/srv/Stonks"\nday = "sat"\nservices = ["stonks"]\n'
                      'build = "docker build -t stonks:latest /x"\ncontext = "/x"\nunittest = "python -m unittest"\ncheck = "curl -sf http://x/"\n')
    assert rows[0] == {"project": "Tower-Waker", "day": "Mon", "services": [], "build": "", "context": "",
                       "test": "", "unittest": "", "check": "", "backups": [], "guard": "", "test_timeout": 900}
    assert rows[1]["day"] == "Sat" and rows[1]["services"] == ["stonks"] and rows[1]["context"] == "/x"


def test_parse_conf_reads_test_timeout_and_refuses_non_positive_ints():
    assert parse_conf('[[image]]\nproject = "A"\nday = "Mon"\ntest_timeout = 2700\n')[0]["test_timeout"] == 2700
    for bad in ("0", "-5", '"900"', "1.5", "true"):
        try:
            parse_conf(f'[[image]]\nproject = "A"\nday = "Mon"\ntest_timeout = {bad}\n')
        except ValueError:
            continue
        raise AssertionError(bad)


def test_test_step_uses_the_entry_timeout():
    import rebuild_local
    seen = []
    orig = rebuild_local.sh
    rebuild_local.sh = lambda cmd, timeout=600, **kw: seen.append(timeout) or subprocess.CompletedProcess(cmd, 0, "", "")
    try:
        run_test_step({"test": "true", "test_timeout": 2700}, Path("/"), {})
        run_test_step(parse_conf('[[image]]\nproject = "A"\nday = "Mon"\n')[0] | {"test": "true"}, Path("/"), {})
    finally:
        rebuild_local.sh = orig
    assert seen == [2700, 900]


def test_stonks_test_step_has_a_long_timeout():
    rows = {r["project"]: r for r in parse_conf((Path(__file__).parent.parent / "rebuild-local.conf").read_text())}
    assert rows["Stonks"]["test_timeout"] == 2700


def test_repo_conf_parses_with_one_project_per_entry():
    rows = parse_conf((Path(__file__).parent.parent / "rebuild-local.conf").read_text())
    assert rows and all(r["project"] for r in rows)
    assert len({r["project"] for r in rows}) == len(rows)


def test_parse_conf_refuses_bad_day_and_unknown_keys():
    for bad in ('[[image]]\nproject = "A"\nday = "Monday"\n', '[[image]]\nproject = "A"\nday = "Mon"\ntypo = 1\n',
                '[[image]]\nday = "Mon"\n'):
        try:
            parse_conf(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_guard_reason_empty_when_ok_else_last_output_line():
    assert guard_reason("", Path("/")) == ""
    assert guard_reason("true", Path("/")) == ""
    assert guard_reason("echo checking; echo 1 playing now; exit 1", Path("/")) == "1 playing now"
    assert guard_reason("exit 3", Path("/")) == "guard failed (rc=3)"


def test_due_by_weekday_or_named():
    row = {"project": "Tower-Waker", "day": "Mon"}
    assert due(row, "Mon", set())
    assert not due(row, "Tue", set())
    assert due(row, "Tue", {"Tower-Waker"})
    assert not due(row, "Mon", {"Other"})


def test_project_dir_and_name():
    assert project_dir("Tower-Waker") == DOCKER / "Tower-Waker"
    assert project_dir("/home/pi/x/WG-Chores") == Path("/home/pi/x/WG-Chores")
    assert project_name("LanguageTool/Raspi") == "LanguageTool"
    assert project_name("/home/pi/x/WG-Chores") == "WG-Chores"


DOCKERFILE = """# syntax comment
ARG X=1
FROM python:3.13-alpine@sha256:aaaa AS thumbs
RUN true
FROM --platform=linux/arm64 python:3.13-alpine@sha256:aaaa
from alpine:3.24
FROM thumbs
FROM scratch
"""


def test_from_refs_skips_stages_and_scratch():
    assert from_refs(DOCKERFILE) == ["python:3.13-alpine@sha256:aaaa", "alpine:3.24"]


def test_pinned_tags_skips_digest_only_refs():
    text = DOCKERFILE + "FROM ghcr.io/linuxserver/mods@sha256:cccc AS opencl\nFROM registry:5000/x/y:1.2@sha256:dddd\n"
    assert pinned_tags(text) == {"python:3.13-alpine", "registry:5000/x/y:1.2"}


def test_bump_pins_rewrites_only_moved_digests():
    out, bumped = bump_pins(DOCKERFILE, {"python:3.13-alpine": "sha256:bbbb"})
    assert bumped == ["python:3.13-alpine"]
    assert out.count("python:3.13-alpine@sha256:bbbb") == 2 and "sha256:aaaa" not in out
    assert "from alpine:3.24" in out
    same, none = bump_pins(DOCKERFILE, {"python:3.13-alpine": "sha256:aaaa"})
    assert same == DOCKERFILE and none == []
    empty, none = bump_pins(DOCKERFILE, {"python:3.13-alpine": ""})
    assert empty == DOCKERFILE and none == []


def test_fingerprint_is_stable_and_sensitive():
    env = ["PATH=/usr/bin", "PYTHON_VERSION=3.13.8"]
    a = fingerprint(env, "P:musl\nV:1.2\n", "100644 abc 0\tapp.py\n")
    assert a == fingerprint(list(reversed(env)), "P:musl\nV:1.2\n", "100644 abc 0\tapp.py\n")
    assert a != fingerprint(["PATH=/usr/bin", "PYTHON_VERSION=3.13.9"], "P:musl\nV:1.2\n", "100644 abc 0\tapp.py\n")
    assert a != fingerprint(env, "P:musl\nV:1.3\n", "100644 abc 0\tapp.py\n")
    assert a != fingerprint(env, "P:musl\nV:1.2\n", "100644 abd 0\tapp.py\n")
    assert fingerprint(env, "", "x") == ""


def test_image_env_names_every_service_and_a_default():
    assert image_env({"clamav": "sha256:1", "port_updater": "sha256:2"}, "clamav") == {
        "IMAGE": "sha256:1", "IMAGE_CLAMAV": "sha256:1", "IMAGE_PORT_UPDATER": "sha256:2"}


def test_update_result_maps_exit_codes():
    assert [update_result(c) for c in (0, 1, 2, 3, 9)] == ["updated", "rolled_back", "error", "rollback_failed", "rollback_failed"]


def test_commit_message_is_one_short_line():
    m = commit_message("Tower-Waker", ["python:3.13-alpine"])
    assert m == "Tower-Waker: bump python:3.13-alpine base digest (weekly rebuild)"
    assert "\n" not in m and len(m.split()) <= 15


def test_alert_message_is_telegram_html_and_escaped():
    m = alert_message("fastpi", "Tower-Waker", "test_failed", "unittest <3 failures>")
    assert m.startswith("🔴 <b>Rebuild: Tower-Waker on fastpi</b>\n\n• ")
    assert "&lt;3 failures&gt;" in m and "test_failed" in m
    assert alert_message("fastpi", "X", "rolled_back", "").startswith("↩️ ")


def test_render_prom_lists_every_project_with_its_last_result():
    state = {"Tower-Waker": {"result": "updated", "time": 100, "ok_time": 100},
             "Stonks": {"result": "test_failed", "reason": 'a "b"', "time": 200, "ok_time": 50}}
    text = render_prom(state, 300, "fastpi")
    assert 'rebuild_local_result{host="fastpi",project="Stonks",result="test_failed",reason="a \\"b\\""} 1' in text
    assert 'rebuild_local_result{host="fastpi",project="Tower-Waker",result="updated",reason=""} 1' in text
    assert 'rebuild_local_last_ok_timestamp_seconds{host="fastpi",project="Stonks"} 50' in text
    assert 'rebuild_local_last_run_timestamp_seconds{host="fastpi"} 300' in text
    assert "# HELP" not in text


def test_rollback_tag_matches_update_project():
    assert rollback_tag("clamav-local:latest", "antivirus", "2026-11-02") == "rollback.invalid/clamav-local:2026-11-02-antivirus"
    assert rollback_tag("registry:5000/x/y:1.2@sha256:dd", "p", "2026-11-02") == "rollback.invalid/registry-5000/x/y:2026-11-02-p"
    assert rollback_tag("lscr.io/linuxserver/jellyfin", "jellyfin", "2026-11-07") == "rollback.invalid/lscr.io/linuxserver/jellyfin:2026-11-07-jellyfin"


def test_parse_env_tolerates_missing_image_output():
    assert parse_env('["PATH=/usr/bin"]\n') == ["PATH=/usr/bin"]
    assert parse_env("\n") is None
    assert parse_env("") is None
    assert parse_env("null") is None



def test_old_fingerprint_is_remembered_so_a_context_change_shows_next_week():
    prints, calls = {}, []
    compute = lambda img: calls.append(img) or "fp-then"
    assert old_fingerprint(prints, "sha256:old", compute) == "fp-then"
    assert prints == {"sha256:old": "fp-then"}
    compute2 = lambda img: calls.append(img) or "fp-now"
    assert old_fingerprint(prints, "sha256:old", compute2) == "fp-then"
    assert calls == ["sha256:old"]
    assert old_fingerprint({}, "sha256:x", lambda img: "") == "" 


def test_build_is_retried_once_after_a_failure():
    from types import SimpleNamespace as R
    rcs, waits = [1, 0], []
    assert build_with_retry(lambda: R(returncode=rcs.pop(0)), waits.append).returncode == 0
    assert waits == [60]
    rcs, waits = [1, 1, 0], []
    assert build_with_retry(lambda: R(returncode=rcs.pop(0)), waits.append).returncode == 1
    assert rcs == [0]
    rcs, waits = [0], []
    assert build_with_retry(lambda: R(returncode=rcs.pop(0)), waits.append).returncode == 0 and waits == []


def test_sh_timeout_keeps_partial_output_as_text():
    r = sh(["bash", "-c", "echo partial; sleep 5"], timeout=1)
    assert r.returncode == 124
    assert isinstance(r.stdout, str) and isinstance(r.stderr, str)
    assert "partial" in r.stdout and "timeout after 1s" in (r.stdout + r.stderr)


def test_predates_compares_image_build_time_with_the_last_context_commit():
    assert predates("2026-10-31T08:43:15.123456789Z", 1793578889)
    assert not predates("2026-11-02T04:52:37.1Z", 1793578889)
    assert not predates("", 1793578889)
    assert not predates("2026-10-31T08:43:15Z", 0)

def _tar(files, mtime):
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in files:
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime, ti.mode = len(data), mtime, 0o755
            t.addfile(ti, io.BytesIO(data))
    buf.seek(0)
    return buf


def test_tar_content_digest_ignores_mtime_but_sees_content_and_names():
    a = tar_content_digest(_tar([("app", b"bin1"), ("etc/x", b"y")], 1000))
    assert a == tar_content_digest(_tar([("app", b"bin1"), ("etc/x", b"y")], 2000))
    assert a != tar_content_digest(_tar([("app", b"bin2"), ("etc/x", b"y")], 1000))
    assert a != tar_content_digest(_tar([("app2", b"bin1"), ("etc/x", b"y")], 1000))
    assert a



def _run_cli(script, args, env_paths):
    """Runs the script with stub docker/ssh/git/sudo on PATH that only record a call. -> (rc, output, calls, created paths)."""
    import os
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "bin").mkdir()
        for tool in ("docker", "ssh", "git", "sudo", "curl", "trivy", "gitleaks"):
            stub = tmp / "bin" / tool
            stub.write_text(f"#!/bin/sh\necho {tool} \"$@\" >> {tmp}/calls\nexit 1\n")
            stub.chmod(0o755)
        env = dict(os.environ, PATH=f"{tmp}/bin:/usr/bin:/bin", **{k: str(tmp / k) for k in env_paths})
        r = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=env, timeout=60)
        calls = (tmp / "calls").read_text() if (tmp / "calls").exists() else ""
        made = [k for k in env_paths if (tmp / k).exists()]
        return r.returncode, r.stdout + r.stderr, calls, made


def test_help_and_unknown_options_print_usage_and_do_nothing():
    script = Path(__file__).parent / "rebuild_local.py"
    for args, want in ((["--help"], 0), (["-h"], 0), (["--bogus"], 2), (["--dry-run", "--bogus"], 2), (["No-Such-Project"], 2)):
        rc, out, calls, made = _run_cli(script, args, ["REBUILD_STATE", "REBUILD_TEXTFILE"])
        assert rc == want, (args, rc, out)
        assert "Usage: rebuild_local.py" in out, args
        assert calls == "" and made == [], (args, calls, made)


def test_tech_radar_is_rebuilt_weekly_with_its_post_update_check():
    rows = {r["project"]: r for r in parse_conf((Path(__file__).parent.parent / "rebuild-local.conf").read_text())}
    if not (Path(__file__).parent.parent.parent / "Tech-Radar").exists():
        return
    assert "Tech-Radar" in rows and rows["Tech-Radar"]["check"]


def _fake_rebuild(tmp, update_rc=None, build_exc=None):
    """Runs rebuild() on a project with a moving digest pin; every docker call is faked. -> (result or exception, docker tag calls, Dockerfile text after)."""
    import rebuild_local as rl
    df = tmp / "Dockerfile"
    df.write_text("FROM alpine:3.20@sha256:aaa\n")
    tags = []

    def fake_run(cmd, **kw):
        cmd = list(cmd)
        if cmd[:2] == ["docker", "tag"]:
            tags.append(cmd[2:])
        if cmd[0].endswith("update-project.sh"):
            if update_rc is None:
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
            return subprocess.CompletedProcess(cmd, update_rc, "", "")
        if cmd[:3] == ["bash", "-c", "BUILD"]:
            if build_exc:
                raise build_exc
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:5] == ["docker", "image", "inspect", "-f", "{{.Id}}"]:
            return subprocess.CompletedProcess(cmd, 0, "sha256:new\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    patch = {"compose_config": lambda d: {"name": "x", "services": {"app": {"build": {"context": str(tmp)}}}},
             "running": lambda d, s: {"app": ("img:1", "sha256:old")},
             "dockerfiles": lambda row, c, s: [df],
             "tag_digest": lambda t: "sha256:bbb",
             "git": lambda f, *a: subprocess.CompletedProcess(a, 0, "", ""),
             "resources_ok": lambda: "",
             "context_listing": lambda f: "",
             "image_fingerprint": lambda i, c: "fp-" + i,
             "old_fingerprint": lambda p, i, c: "fp-old",
             "predates": lambda c, t: False,
             "project_dir": lambda p: tmp}
    saved = {k: getattr(rl, k) for k in patch}
    real_run = rl.subprocess.run
    for k, v in patch.items():
        setattr(rl, k, v)
    rl.subprocess.run = fake_run
    rl._docker[:] = ["docker"]
    row = dict(rl.KEYS, project="X", day="Mon", build="BUILD")
    try:
        out = rl.rebuild(row, {}, False)
    except BaseException as e:  # noqa: BLE001
        out = e
    finally:
        rl.subprocess.run = real_run
        for k, v in saved.items():
            setattr(rl, k, v)
    return out, tags, df.read_text()


def test_crash_after_the_pin_moved_reverts_the_pin_and_the_tag():
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        out, tags, text = _fake_rebuild(Path(t), build_exc=OSError("crash"))
    assert isinstance(out, OSError), out
    assert text == "FROM alpine:3.20@sha256:aaa\n", text
    assert tags and tags[-1] == ["sha256:old", "img:1"], tags


def test_update_project_timeout_is_a_failure_that_reverts_the_pin_and_the_tag():
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        out, tags, text = _fake_rebuild(Path(t))
    assert isinstance(out, tuple) and out[0] == "rollback_failed" and "timeout" in out[1], out
    assert text == "FROM alpine:3.20@sha256:aaa\n", text
    assert tags and tags[-1] == ["sha256:old", "img:1"], tags


def test_update_project_exit_2_moves_the_tag_back():
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        out, tags, text = _fake_rebuild(Path(t), update_rc=2)
    assert out[0] == "error", out
    assert text == "FROM alpine:3.20@sha256:aaa\n", text
    assert tags and tags[-1] == ["sha256:old", "img:1"], tags


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, repr(e))
    sys.exit(1 if fails else 0)

