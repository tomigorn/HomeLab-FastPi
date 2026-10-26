"""Run: python3 -m unittest discover -s Docker/Audiobook-Requests/importer"""
import unittest

from ranking import Prefs, apply_policy, for_abr, prefs_from_product


def release(title, date="2024-01-01T00:00:00Z", seeders=5, **extra):
    return dict({"guid": title + date, "title": title, "publishDate": date, "seeders": seeders, "indexerFlags": []}, **extra)


def titles(results):
    return [r["title"] for r in results]


class PolicyTest(unittest.TestCase):
    def test_m4b_beats_mp3(self):
        out = apply_policy([release("B by A [ENG / MP3]", "2025-01-01T00:00:00Z"), release("B by A [ENG / M4B]")], Prefs())
        self.assertEqual(titles(out)[0], "B by A [ENG / M4B]")

    def test_english_beats_german_by_default(self):
        out = apply_policy([release("B by A [GER / M4B]", "2026-01-01T00:00:00Z"), release("B by A [ENG / MP3]")], Prefs())
        self.assertEqual(titles(out), ["B by A [ENG / MP3]"])

    def test_german_request_prefers_german(self):
        out = apply_policy([release("B by A [ENG / M4B]"), release("B by A [GER / M4B]")], Prefs(language="DE"))
        self.assertEqual(titles(out), ["B by A [GER / M4B]"])

    def test_abridged_is_kept_when_the_request_is_abridged(self):
        out = apply_policy([release("B (Abridged) by A [ENG / M4B]")], Prefs(unabridged=False))
        self.assertEqual(len(out), 1)

    def test_newer_beats_older_when_the_rest_is_equal(self):
        out = apply_policy([release("B by A [ENG / M4B]", "2019-05-01T00:00:00Z", seeders=50),
                            release("B by A [ENG / M4B]", "2025-05-01T00:00:00Z", seeders=2)], Prefs())
        self.assertEqual(out[0]["publishDate"], "2025-05-01T00:00:00Z")
        self.assertIn("abr-newest-1", out[0]["indexerFlags"])
        self.assertIn("abr-newest-2", out[1]["indexerFlags"])

    def test_min_one_seeder(self):
        out = apply_policy([release("B by A [ENG / M4B]", seeders=0), release("B by A [ENG / MP3]", seeders=1)], Prefs())
        self.assertEqual(titles(out), ["B by A [ENG / MP3]"])

class PrefsFromProductTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(prefs_from_product(None), Prefs(language="EN", unabridged=True))

    def test_german_abridged_edition(self):
        self.assertEqual(prefs_from_product({"language": "german", "format_type": "abridged"}),
                         Prefs(language="DE", unabridged=False))

    def test_english_unabridged_edition(self):
        self.assertEqual(prefs_from_product({"language": "english", "format_type": "unabridged"}), Prefs())


if __name__ == "__main__":
    unittest.main()


class VipTest(unittest.TestCase):
    def test_vip_beats_non_vip_when_the_rest_is_equal(self):
        out = apply_policy([release("B by A [ENG / M4B]", "2026-01-01T00:00:00Z"),
                            release("B by A [ENG / M4B] [VIP]", "2020-01-01T00:00:00Z")], Prefs())
        self.assertEqual(titles(out)[0], "B by A [ENG / M4B] [VIP]")
        self.assertIn("abr-vip", out[0]["indexerFlags"])

    def test_freeleech_counts_like_vip(self):
        out = apply_policy([release("B by A [ENG / M4B]", "2026-01-01T00:00:00Z"),
                            release("B by A [ENG / M4B]", "2020-01-01T00:00:00Z", indexerFlags=["freeleech"])], Prefs())
        self.assertEqual(out[0]["publishDate"], "2020-01-01T00:00:00Z")

    def test_m4b_non_vip_still_beats_mp3_vip(self):
        out = apply_policy([release("B by A [ENG / MP3] [VIP]"), release("B by A [ENG / M4B]")], Prefs())
        self.assertEqual(titles(out)[0], "B by A [ENG / M4B]")

    def test_newest_still_decides_among_vip(self):
        out = apply_policy([release("B by A [ENG / M4B] [VIP]", "2019-01-01T00:00:00Z"),
                            release("B by A [ENG / M4B] [VIP]", "2024-01-01T00:00:00Z")], Prefs())
        self.assertEqual(out[0]["publishDate"], "2024-01-01T00:00:00Z")


class DownloadUrlTest(unittest.TestCase):
    def test_download_links_go_through_the_pass_through(self):
        out = apply_policy([release("B by A [ENG / M4B]", downloadUrl="http://10.24.25.2:9697/1/download?apikey=k&link=x")],
                           Prefs(), proxy_base="http://audiobook-importer:8000/prowlarr")
        self.assertTrue(out[0]["downloadUrl"].startswith("http://audiobook-importer:8000/prowlarr/torrent?guid="))


class FinalOrderTest(unittest.TestCase):
    def test_english_only_and_the_request_stays_open(self):
        out = apply_policy([release("B by A [GER / M4B] [VIP]")], Prefs())
        self.assertEqual(out, [])
        self.assertEqual(for_abr([release("B by A [GER / M4B]")], Prefs()), [])

    def test_results_without_a_language_are_dropped(self):
        self.assertEqual(apply_policy([release("Some Other Release")], Prefs()), [])

    def test_unabridged_mp3_beats_abridged_m4b(self):
        out = apply_policy([release("B (Abridged) by A [ENG / M4B] [VIP]", "2026-01-01T00:00:00Z"),
                            release("B by A [ENG / MP3]", "2010-01-01T00:00:00Z")], Prefs())
        self.assertEqual(titles(out)[0], "B by A [ENG / MP3]")

    def test_abridged_when_it_is_the_only_option(self):
        out = apply_policy([release("B (Abridged) by A [ENG / MP3]")], Prefs())
        self.assertEqual(titles(out), ["B (Abridged) by A [ENG / MP3]"])

    def test_m4b_beats_mp3_and_flac_among_unabridged(self):
        out = apply_policy([release("B by A [ENG / FLAC]", "2026-01-01T00:00:00Z"), release("B by A [ENG / MP3]", "2025-01-01T00:00:00Z"),
                            release("B by A [ENG / M4B]", "2010-01-01T00:00:00Z")], Prefs())
        self.assertEqual(titles(out)[0], "B by A [ENG / M4B]")

    def test_abr_gets_only_the_winner(self):
        out = for_abr([release("B by A [ENG / MP3]"), release("B by A [ENG / M4B]")], Prefs())
        self.assertEqual(titles(out), ["B by A [ENG / M4B]"])
