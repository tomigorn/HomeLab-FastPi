import os, pathlib, stat, subprocess, tempfile, unittest

UNIT = pathlib.Path(__file__).resolve().parent.parent / "systemd" / "avatar-sync.service"


def settings(section):
    out, cur = {}, None
    for line in UNIT.read_text().splitlines():
        if line.startswith("["):
            cur = line.strip("[]")
        elif cur == section and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k] = v
    return out


class RetryUnit(unittest.TestCase):
    def test_any_failure_restarts_with_backoff(self):
        s = settings("Service")
        self.assertEqual(s.get("Restart"), "on-failure")
        self.assertIn("RestartSteps", s)
        self.assertIn("RestartMaxDelaySec", s)
        self.assertEqual(s.get("SuccessExitStatus"), "75")

    def test_restarts_never_hit_the_start_limit(self):
        self.assertEqual(settings("Unit").get("StartLimitIntervalSec"), "0")

    def test_runs_at_boot(self):
        self.assertEqual(settings("Install").get("WantedBy"), "multi-user.target")

    def stop_post(self, exit_status, result):
        cmd = settings("Service")["ExecStopPost"]
        self.assertTrue(cmd.startswith("+/bin/sh -c '") and cmd.endswith("'"))
        script = cmd[len("+/bin/sh -c '"):-1].replace("$$", "$")
        with tempfile.TemporaryDirectory() as d:
            fake = pathlib.Path(d) / "systemctl"
            fake.write_text('#!/bin/sh\necho "$*" >> "$LOG"\n')
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            log = pathlib.Path(d) / "log"
            env = dict(os.environ, PATH=f"{d}:/usr/bin:/bin", LOG=str(log), EXIT_STATUS=exit_status, SERVICE_RESULT=result)
            subprocess.run(["/bin/sh", "-c", script], env=env, check=True)
            return log.read_text().strip() if log.exists() else ""

    def test_pending_starts_the_retry_timer(self):
        self.assertEqual(self.stop_post("75", "success"), "start avatar-sync.timer")

    def test_in_sync_stops_the_retry_timer(self):
        self.assertEqual(self.stop_post("0", "success"), "stop avatar-sync.timer")

    def test_error_or_timeout_leaves_the_timer_alone(self):
        self.assertEqual(self.stop_post("1", "exit-code"), "")
        self.assertEqual(self.stop_post("", "timeout"), "")
        self.assertEqual(self.stop_post("TERM", "signal"), "")


if __name__ == "__main__":
    unittest.main()
