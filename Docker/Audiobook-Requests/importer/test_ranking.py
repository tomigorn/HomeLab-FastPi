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


def mam(tid, title, date, seeders):
    return release(title, date + "T00:00:00Z", seeders, guid=f"https://www.myanonamouse.net/t/{tid}")


# Real MAM answer to "Sense and Sensibility" (2026-11-02): t/472825 + t/1039841 = Karen Savage, t/1277153 = Rosamund Pike (Audible Exclusive).
SENSE = [mam(572126, "Sense & Sensibility by Joanna Trollope [ENG / MP3]", "2019-12-02", 10),
         mam(51512, "Sense & Sensibility & Sea Monsters by Ben H Winters [ENG / MP3]", "2010-08-11", 5),
         mam(1039841, "Sense and Sensibility by Jane Austen [ENG / M4B]", "2024-05-29", 26),
         mam(472825, "Sense and Sensibility by Jane Austen [ENG / MP3]", "2018-11-06", 16),
         mam(804228, "Sense and Sensibility by Jane Austen [ENG / M4B]", "2022-02-22", 138),
         mam(1277153, "Sense and Sensibility by Jane Austen [ENG / M4B]", "2026-10-17", 27),
         mam(1167215, "Sense and Sensibility by Jane Austen [ENG / M4B]", "2025-07-23", 59),
         mam(220942, "BBC R4 CS - Sense and Sensibility by Jane Austen (Aug 2013) by Jane Austen, BBC Radio 4 [ENG / MP3]", "2014-12-06", 5),
         mam(942700, "Women, Work, and the Art of Savoir Faire: Business Sense and Sensibility by Mireille Guiliano [ENG / M4B]", "2023-06-28", 3)]
SAVAGE = frozenset({"https://www.myanonamouse.net/t/1039841", "https://www.myanonamouse.net/t/472825"})


class AuthorFilterTest(unittest.TestCase):
    def test_other_authors_with_the_same_title_are_dropped(self):
        out = apply_policy(SENSE, Prefs(authors=("Jane Austen",)))
        self.assertTrue(all("by Jane Austen" in r["title"] for r in out))
        self.assertNotIn("Sense & Sensibility by Joanna Trollope [ENG / MP3]", titles(out))
        self.assertEqual(len(out), 6)

    def test_case_accents_and_punctuation_are_ignored(self):
        self.assertEqual(len(apply_policy([release("B by JO NESBØ [ENG / M4B]")], Prefs(authors=("Jo Nesbo",)))), 1)
        self.assertEqual(len(apply_policy([release("B by J.R.R. Tolkien [ENG / M4B]")], Prefs(authors=("J. R. R. Tolkien",)))), 1)
        self.assertEqual(len(apply_policy([release("B by Émile Zola [ENG / M4B]")], Prefs(authors=("Emile Zola",)))), 1)

    def test_any_author_of_the_book_or_the_release_counts(self):
        out = apply_policy([release("B by Douglas Preston, Lincoln Child [ENG / M4B]")], Prefs(authors=("Lincoln Child", "Douglas Preston")))
        self.assertEqual(len(out), 1)
        out = apply_policy([release("B by Lincoln Child [ENG / M4B]")], Prefs(authors=("Douglas Preston", "Lincoln Child")))
        self.assertEqual(len(out), 1)

    def test_a_name_that_only_contains_the_author_does_not_match(self):
        self.assertEqual(apply_policy([release("B by Jane Austenford [ENG / M4B]")], Prefs(authors=("Jane Austen",))), [])

    def test_no_author_match_means_no_automatic_grab(self):
        self.assertEqual(for_abr([release("Sense & Sensibility by Joanna Trollope [ENG / M4B]")], Prefs(authors=("Jane Austen",))), [])

    def test_unknown_authors_keep_the_old_behaviour(self):
        self.assertEqual(len(apply_policy([release("B by Anyone [ENG / M4B]")], Prefs())), 1)


class NarratorTest(unittest.TestCase):
    def test_requested_narrator_wins_over_newer_m4b(self):
        out = for_abr(SENSE, Prefs(authors=("Jane Austen",), narrators=("Karen Savage",)), narrated=SAVAGE)
        self.assertEqual(out[0]["guid"], "https://www.myanonamouse.net/t/1039841")

    def test_narrator_beats_format(self):
        out = apply_policy([release("B by A [ENG / M4B]", "2026-01-01T00:00:00Z"), release("B by A [ENG / MP3]", guid="n")],
                           Prefs(authors=("A",), narrators=("N",)), narrated=frozenset({"n"}))
        self.assertEqual(out[0]["guid"], "n")

    def test_narrator_is_a_preference_not_a_filter(self):
        out = for_abr(SENSE, Prefs(authors=("Jane Austen",), narrators=("Nobody Known",)), narrated=frozenset())
        self.assertEqual(out[0]["guid"], "https://www.myanonamouse.net/t/1277153")

    def test_unabridged_still_beats_an_abridged_narrator_match(self):
        out = apply_policy([release("B (Abridged) by A [ENG / M4B]", guid="n"), release("B by A [ENG / MP3]")],
                           Prefs(authors=("A",)), narrated=frozenset({"n"}))
        self.assertEqual(titles(out)[0], "B by A [ENG / MP3]")


class BookPrefsTest(unittest.TestCase):
    def test_authors_and_narrators_from_the_audible_product(self):
        p = prefs_from_product({"language": "english", "authors": [{"name": "Jane Austen"}], "narrators": [{"name": "Karen Savage"}]})
        self.assertEqual((p.authors, p.narrators), (("Jane Austen",), ("Karen Savage",)))
