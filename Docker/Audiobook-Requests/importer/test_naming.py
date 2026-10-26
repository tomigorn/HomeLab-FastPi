"""Run: python3 -m unittest discover -s Docker/Audiobook-Requests/importer"""
import unittest

from naming import Book, book_dir, language_folder, mam_language


class BookDirTest(unittest.TestCase):
    def test_series_book_gets_zero_padded_number(self):
        b = Book("The Final Empire", ["Brandon Sanderson"], "Mistborn", "1", "EN")
        self.assertEqual(book_dir(b), "EN/Brandon Sanderson/Mistborn/01 - The Final Empire")

    def test_no_series_goes_straight_under_the_author(self):
        b = Book("Project Hail Mary", ["Andy Weir"], None, None, "EN")
        self.assertEqual(book_dir(b), "EN/Andy Weir/Project Hail Mary")

    def test_series_without_position_has_no_number(self):
        b = Book("Tales", ["Jane Doe"], "Collected", None, "EN")
        self.assertEqual(book_dir(b), "EN/Jane Doe/Collected/Tales")

    def test_prequel_and_half_numbers(self):
        self.assertEqual(book_dir(Book("Prequel", ["A B"], "S", "0", "EN")), "EN/A B/S/00 - Prequel")
        self.assertEqual(book_dir(Book("Novella", ["A B"], "S", "2.5", "EN")), "EN/A B/S/02.5 - Novella")

    def test_large_and_messy_numbers(self):
        self.assertEqual(book_dir(Book("T", ["A B"], "S", "12", "EN")), "EN/A B/S/12 - T")
        self.assertEqual(book_dir(Book("T", ["A B"], "S", "Book 3", "EN")), "EN/A B/S/03 - T")
        self.assertEqual(book_dir(Book("T", ["A B"], "S", "103", "EN")), "EN/A B/S/103 - T")

    def test_multi_author_uses_the_first(self):
        b = Book("Good Omens", ["Terry Pratchett", "Neil Gaiman"], None, None, "EN")
        self.assertEqual(book_dir(b), "EN/Terry Pratchett/Good Omens")

    def test_series_suffix_is_dropped(self):
        b = Book("The Eye of the World", ["Robert Jordan"], "The Wheel of Time Series", "1", "EN")
        self.assertEqual(book_dir(b), "EN/Robert Jordan/The Wheel of Time/01 - The Eye of the World")

    def test_german_umlauts_are_kept_and_composed(self):
        b = Book("Die Abenteuer des braven Soldaten Schwejk", ["Jaroslav Hašek"], None, None, "DE")
        self.assertEqual(book_dir(b), "DE/Jaroslav Hašek/Die Abenteuer des braven Soldaten Schwejk")
        b = Book("Über Nacht", ["Jörg Müßig"], "Grüße", "1", "DE")
        self.assertEqual(book_dir(b), "DE/Jörg Müßig/Grüße/01 - Über Nacht")

    def test_colon_is_kept_but_slashes_and_controls_go(self):
        b = Book("Mistborn: The Final Empire", ["Brandon Sanderson"], None, None, "EN")
        self.assertEqual(book_dir(b), "EN/Brandon Sanderson/Mistborn: The Final Empire")
        b = Book("AC/DC\tStory ", [" Jane  Doe "], None, None, "EN")
        self.assertEqual(book_dir(b), "EN/Jane Doe/AC-DC Story")

    def test_dot_names_cannot_escape(self):
        b = Book("..", [".."], None, None, "EN")
        self.assertEqual(book_dir(b), "EN/Unknown Author/Unknown Title")

    def test_missing_author(self):
        self.assertEqual(book_dir(Book("T", [], None, None, "EN")), "EN/Unknown Author/T")


class LanguageTest(unittest.TestCase):
    def test_audible_language(self):
        self.assertEqual(language_folder("english"), "EN")
        self.assertEqual(language_folder("German"), "DE")
        self.assertEqual(language_folder("french"), "Other")
        self.assertEqual(language_folder(None), None)

    def test_mam_flags_in_the_prowlarr_title(self):
        self.assertEqual(mam_language("The Hobbit by J.R.R. Tolkien [ENG / M4B]"), "EN")
        self.assertEqual(mam_language("Der Hobbit by J.R.R. Tolkien [GER / MP3]"), "DE")
        self.assertEqual(mam_language("Le Hobbit by J.R.R. Tolkien [FRE / MP3] [VIP]"), "Other")
        self.assertEqual(mam_language("no flags here"), None)


if __name__ == "__main__":
    unittest.main()
