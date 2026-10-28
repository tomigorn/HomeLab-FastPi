import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
import waker as w


class ListenBacklog(unittest.TestCase):
    def test_backlog_absorbs_bursts(self):
        self.assertGreaterEqual(w.Server.request_queue_size, 64)


class NextcloudDecision(unittest.TestCase):
    def d(self, headers, up=False, starting=False):
        return w.nextcloud_decision(up, starting, headers)

    def test_up_passes(self):
        self.assertEqual(self.d({}, up=True), "pass")

    def test_starting_never_rewakes(self):
        self.assertEqual(self.d({"User-Agent": "curl/8"}, starting=True), "starting")

    def test_scanner_without_ua_refused(self):
        self.assertEqual(self.d({}), "refuse")

    def test_scanner_with_browser_ua_but_no_html_refused(self):
        self.assertEqual(self.d({"User-Agent": "Mozilla/5.0", "Accept": "*/*"}), "refuse")

    def test_anonymous_browser_gets_signin_not_wake(self):
        self.assertEqual(self.d({"User-Agent": "Mozilla/5.0 Firefox", "Accept": "text/html,*/*"}), "signin")

    def test_returning_browser_with_session_cookie_wakes(self):
        h = {"Accept": "text/html", "Cookie": "oc1x2=abc; nc_session_id=zzz"}
        self.assertEqual(self.d(h), "wake")

    def test_remember_me_cookie_wakes(self):
        self.assertEqual(self.d({"Cookie": "nc_token=abc; nc_username=t"}), "wake")

    def test_webdav_basic_auth_wakes(self):
        self.assertEqual(self.d({"Authorization": "Basic dXNlcjpwYXNz"}), "wake")

    def test_desktop_client_wakes(self):
        self.assertEqual(self.d({"User-Agent": "Mozilla/5.0 (Linux) mirall/3.14.1 (Nextcloud, fedora)"}), "wake")

    def test_android_client_wakes(self):
        self.assertEqual(self.d({"User-Agent": "Mozilla/5.0 (Android) Nextcloud-android/3.30.0"}), "wake")

    def test_ios_client_wakes(self):
        self.assertEqual(self.d({"User-Agent": "Mozilla/5.0 (iOS) Nextcloud-iOS/6.0"}), "wake")


if __name__ == "__main__":
    unittest.main()
