import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sub", HERE.parent / "scripts" / "subscribe.py")
sub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sub)


class LoadFeedsTest(unittest.TestCase):
    def test_feed_and_github_shorthand(self):
        text = ('[[feed]]\ncategory = "KEV"\nurl = "http://vl-web:10001/kev.atom"\n'
                '[[github]]\ncategory = "Releases"\nrepos = ["traefik/traefik"]\n'
                '[[github]]\ncategory = "Releases"\nrepos = ["postgres/postgres"]\nkind = "tags"\n')
        self.assertEqual(sub.load_feeds(text, {}), [
            ("KEV", "http://vl-web:10001/kev.atom"),
            ("Releases", "https://github.com/postgres/postgres/tags.atom"),
            ("Releases", "https://github.com/traefik/traefik/releases.atom"),
        ])

    def test_placeholders_come_from_secrets(self):
        text = '[[feed]]\ncategory = "Watchlist"\nurl = "http://vl-web:10001/w.atom?X-FEED-KEY={feed_key}"\n'
        self.assertEqual(sub.load_feeds(text, {"feed_key": "k1"}), [("Watchlist", "http://vl-web:10001/w.atom?X-FEED-KEY=k1")])

    def test_missing_placeholder_value_is_an_error(self):
        with self.assertRaises(KeyError):
            sub.load_feeds('[[feed]]\ncategory = "W"\nurl = "http://x/?k={feed_key}"\n', {})

    def test_bad_repo_name_is_an_error(self):
        with self.assertRaises(ValueError):
            sub.load_feeds('[[github]]\ncategory = "R"\nrepos = ["traefik"]\n', {})

    def test_the_committed_list_loads(self):
        feeds = sub.load_feeds((HERE.parent / "feeds.toml").read_text(), {"feed_key": "k"})
        cats = {c for c, _ in feeds}
        self.assertTrue({"Watchlist", "KEV", "Releases"} <= cats)
        self.assertIn(("Releases", "https://github.com/traefik/traefik/releases.atom"), feeds)


class MaskTest(unittest.TestCase):
    def test_feed_key_is_hidden_in_urls_and_error_text(self):
        self.assertEqual(sub.masked('Get "http://vl-web:10001/w.atom?X-FEED-KEY=abc-_1": context'),
                         'Get "http://vl-web:10001/w.atom?X-FEED-KEY=***": context')


class PlanTest(unittest.TestCase):
    def test_new_feeds_are_created_and_moved_ones_recategorised(self):
        existing = {"https://a/x.atom": (1, "Old"), "https://b/y.atom": (2, "Releases")}
        wanted = [("Releases", "https://a/x.atom"), ("Releases", "https://b/y.atom"), ("KEV", "https://c/z.atom")]
        create, move = sub.plan(existing, wanted)
        self.assertEqual(create, [("KEV", "https://c/z.atom")])
        self.assertEqual(move, [(1, "Releases")])

    def test_unlisted_feeds_are_left_alone(self):
        self.assertEqual(sub.plan({"https://own/feed": (9, "Mine")}, []), ([], []))


if __name__ == "__main__":
    unittest.main()
