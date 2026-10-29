import http.client, io, json, os, sys, threading, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
os.environ.setdefault("TARGET_MAC", "00:11:22:33:44:55")
os.environ.setdefault("TARGET_PROBE_HOST", "127.0.0.1")
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


class WakeCsrf(unittest.TestCase):
    """POST /wake and /nc/wake need the X-Wake header, and a browser Origin must be this host."""
    @classmethod
    def setUpClass(cls):
        cls.srv = w.Server(("127.0.0.1", 0), w.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        w._campaign_running = False
        mock.patch("sys.stdout", io.StringIO()).start()
        self.send_wol = mock.patch.object(w, "send_wol").start()
        mock.patch.object(w, "_wake_campaign").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(setattr, w, "_campaign_running", False)

    def req(self, method, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def test_get_never_wakes(self):
        for p in ("/wake", "/nc/wake"):
            self.assertEqual(self.req("GET", p, {"X-Wake": "1"})[0], 405, p)
        self.send_wol.assert_not_called()

    def test_post_without_header_refused(self):
        for p in ("/wake", "/nc/wake"):
            self.assertEqual(self.req("POST", p)[0], 403, p)
        self.send_wol.assert_not_called()

    def test_cross_site_post_refused(self):
        for p in ("/wake", "/nc/wake"):
            self.assertEqual(self.req("POST", p, {"Origin": "https://evil.example.com"})[0], 403, p)
            self.assertEqual(self.req("POST", p, {"X-Wake": "1", "Origin": "https://evil.example.com",
                                                  "Host": "tower-wol.fastpi.homelab"})[0], 403, p)
        self.send_wol.assert_not_called()

    def test_script_with_header_wakes(self):
        status, body = self.req("POST", "/wake", {"X-Wake": "1"})
        self.assertEqual((status, json.loads(body)), (200, {"sent": True}))
        self.send_wol.assert_called_once()

    def test_same_origin_page_wakes(self):
        self.assertEqual(self.req("POST", "/wake", {"X-Wake": "1", "Host": "tower-wol.fastpi.homelab",
                                                    "Origin": "https://tower-wol.fastpi.homelab"})[0], 200)
        self.assertEqual(self.req("POST", "/nc/wake", {"X-Wake": "1", "Host": "cloud.holy-grail.ch",
                                                       "Origin": "https://cloud.holy-grail.ch"})[0], 200)

    def test_pages_send_the_header(self):
        self.assertIn("'X-Wake': '1'", self.req("GET", "/")[1])
        self.assertIn('"X-Wake": "1"', self.req("GET", "/nc")[1])


if __name__ == "__main__":
    unittest.main()
