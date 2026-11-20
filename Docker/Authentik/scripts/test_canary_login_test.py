"""Tests for canary_login_test.py. Run: python3 -m unittest discover -s Docker/Authentik/scripts"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("canary_login_test", HERE / "canary_login_test.py")
clt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clt)


class FreshCounterTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = Path(self.dir.name) / "sub" / "canary-totp-counter"

    def tearDown(self):
        self.dir.cleanup()

    def test_first_run_uses_the_current_window_without_waiting(self):
        self.assertEqual(clt.fresh_counter(self.state, now=3000.0), (100, 0))
        self.assertEqual(self.state.read_text(), "100")

    def test_code_of_the_current_window_already_used_waits_for_the_next(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("100")
        counter, wait = clt.fresh_counter(self.state, now=3010.0)
        self.assertEqual(counter, 101)
        self.assertAlmostEqual(wait, 20.5)
        self.assertEqual(self.state.read_text(), "101")

    def test_older_code_used_no_wait(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("99")
        self.assertEqual(clt.fresh_counter(self.state, now=3010.0), (100, 0))

    def test_shares_the_state_file_with_the_screenshot_tool(self):
        self.assertEqual(clt.TOTP_STATE, Path.home() / ".local/state/canary-totp-counter")

    def test_totp_known_vector(self):
        # RFC 6238 SHA-1 secret "12345678901234567890", T=59 -> 94287082 (last 6 digits)
        self.assertEqual(clt.totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", at=59), "287082")


if __name__ == "__main__":
    unittest.main()
