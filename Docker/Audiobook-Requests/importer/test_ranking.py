"""Run: python3 -m unittest discover -s Docker/Audiobook-Requests/importer"""
import unittest

from ranking import Prefs, apply_policy, prefs_from_product


def release(title, date="2024-01-01T00:00:00Z", seeders=5, **extra):
    return dict({"guid": title + date, "title": title, "publishDate": date, "seeders": seeders, "indexerFlags": []}, **extra)


def titles(results):
    return [r["title"] for r in results]


class PolicyTest(unittest.TestCase):
    def test_m4b_beats_mp3(self):
        out = apply_policy([release("B by A [ENG / MP3]", "2025-01-01T00:00:00Z"), release("B by A [ENG / M4B]")], Prefs())
        self.assertEqual(titles(out)[0], "B by A [ENG / M4B]")

    def test_flac_is_dropped_when_an_m4b_exists(self):
        out = apply_policy([release("B by A [ENG / FLAC]"), release("B by A [ENG / M4B]")], Prefs())
        self.assertEqual(titles(out), ["B by A [ENG / M4B]"])

    def test_english_beats_german_by_default(self):
        out = apply_policy([release("B by A [GER / M4B]", "2026-01-01T00:00:00Z"), release("B by A [ENG / MP3]")], Prefs())
        self.assertEqual(titles(out), ["B by A [ENG / MP3]"])

    def test_other_language_is_the_fallback_when_none_matches(self):
        out = apply_policy([release("B by A [GER / M4B]")], Prefs())
        self.assertEqual(titles(out), ["B by A [GER / M4B]"])

    def test_german_request_prefers_german(self):
        out = apply_policy([release("B by A [ENG / M4B]"), release("B by A [GER / M4B]")], Prefs(language="DE"))
        self.assertEqual(titles(out), ["B by A [GER / M4B]"])

    def test_abridged_is_rejected_when_unabridged_is_on(self):
        out = apply_policy([release("B (Abridged) by A [ENG / M4B]"), release("B by A [ENG / MP3]"),
                            release("B (Unabridged) by A [ENG / MP3]", "2023-01-01T00:00:00Z")], Prefs())
        self.assertEqual(sorted(titles(out)), ["B (Unabridged) by A [ENG / MP3]", "B by A [ENG / MP3]"])

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

    def test_non_mam_results_without_flags_are_kept(self):
        out = apply_policy([release("Some Other Release")], Prefs())
        self.assertEqual(len(out), 1)


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
