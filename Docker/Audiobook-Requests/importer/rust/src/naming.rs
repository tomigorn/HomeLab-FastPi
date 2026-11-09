//! Library path of a book: LANG/Author/[Series]/NN - Title (see the project README).
use regex::Regex;
use std::sync::LazyLock;
use unicode_normalization::UnicodeNormalization;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Book {
    pub title: String,
    pub authors: Vec<String>,
    pub series: Option<String>,
    pub position: Option<String>,
    pub language: String,
}

impl Book {
    pub fn new(title: &str, authors: Vec<String>, series: Option<String>, position: Option<String>, language: &str) -> Book {
        Book { title: title.to_string(), authors, series, position, language: language.to_string() }
    }
}

static CONTROLS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[\x00-\x1f\x7f]").unwrap());
static SPACES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s+").unwrap());
static NUMBER: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\d+(?:\.\d+)?").unwrap());
static SERIES_SUFFIX: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)\s+Series$").unwrap());
static MAM_FLAG: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\[([A-Z]{3}) /").unwrap());

pub fn mam_code(code: &str) -> &'static str {
    match code {
        "ENG" => "EN",
        "GER" | "DEU" => "DE",
        _ => "Other",
    }
}

pub fn clean(text: &str) -> String {
    let text: String = text.nfc().collect();
    let text = text.replace(['/', '\\'], "-");
    let text = CONTROLS.replace_all(&text, " ");
    let text = SPACES.replace_all(&text, " ").trim().to_string();
    if text.chars().all(|c| c == '.') {
        String::new()
    } else {
        text
    }
}

pub fn number(position: Option<&str>) -> Option<String> {
    let m = NUMBER.find(position.unwrap_or(""))?;
    let (whole, frac) = match m.as_str().split_once('.') {
        Some((w, f)) => (w, Some(f)),
        None => (m.as_str(), None),
    };
    let digits = whole.trim_start_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };
    let padded = format!("{:0>2}", digits);
    Some(match frac {
        Some(f) => format!("{padded}.{f}"),
        None => padded,
    })
}

pub fn book_dir(book: &Book) -> String {
    let author = book.authors.first().map(|a| clean(a)).unwrap_or_default();
    let mut title = clean(&book.title);
    if title.is_empty() {
        title = "Unknown Title".to_string();
    }
    let mut parts = vec![book.language.clone(), if author.is_empty() { "Unknown Author".to_string() } else { author }];
    let series = SERIES_SUFFIX.replace(&clean(book.series.as_deref().unwrap_or("")), "").to_string();
    if !series.is_empty() {
        parts.push(series);
        if let Some(n) = number(book.position.as_deref()) {
            title = format!("{n} - {title}");
        }
    }
    parts.push(title);
    parts.join("/")
}

pub fn language_folder(name: Option<&str>) -> Option<String> {
    let name = name?;
    if name.is_empty() {
        return None;
    }
    Some(match name.trim().to_lowercase().as_str() {
        "english" => "EN",
        "german" | "deutsch" => "DE",
        _ => "Other",
    }
    .to_string())
}

pub fn mam_language(source_title: Option<&str>) -> Option<String> {
    let m = MAM_FLAG.captures(source_title.unwrap_or(""))?;
    Some(mam_code(&m[1]).to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn b(title: &str, authors: &[&str], series: Option<&str>, position: Option<&str>, lang: &str) -> Book {
        Book::new(title, authors.iter().map(|a| a.to_string()).collect(), series.map(String::from), position.map(String::from), lang)
    }

    #[test]
    fn series_book_gets_zero_padded_number() {
        assert_eq!(book_dir(&b("The Final Empire", &["Brandon Sanderson"], Some("Mistborn"), Some("1"), "EN")), "EN/Brandon Sanderson/Mistborn/01 - The Final Empire");
        assert_eq!(book_dir(&b("Project Hail Mary", &["Andy Weir"], None, None, "EN")), "EN/Andy Weir/Project Hail Mary");
        assert_eq!(book_dir(&b("Tales", &["Jane Doe"], Some("Collected"), None, "EN")), "EN/Jane Doe/Collected/Tales");
    }

    #[test]
    fn prequel_half_and_messy_numbers() {
        assert_eq!(book_dir(&b("Prequel", &["A B"], Some("S"), Some("0"), "EN")), "EN/A B/S/00 - Prequel");
        assert_eq!(book_dir(&b("Novella", &["A B"], Some("S"), Some("2.5"), "EN")), "EN/A B/S/02.5 - Novella");
        assert_eq!(book_dir(&b("T", &["A B"], Some("S"), Some("12"), "EN")), "EN/A B/S/12 - T");
        assert_eq!(book_dir(&b("T", &["A B"], Some("S"), Some("Book 3"), "EN")), "EN/A B/S/03 - T");
        assert_eq!(book_dir(&b("T", &["A B"], Some("S"), Some("103"), "EN")), "EN/A B/S/103 - T");
    }

    #[test]
    fn first_author_series_suffix_umlauts_and_slashes() {
        assert_eq!(book_dir(&b("Good Omens", &["Terry Pratchett", "Neil Gaiman"], None, None, "EN")), "EN/Terry Pratchett/Good Omens");
        assert_eq!(book_dir(&b("The Eye of the World", &["Robert Jordan"], Some("The Wheel of Time Series"), Some("1"), "EN")), "EN/Robert Jordan/The Wheel of Time/01 - The Eye of the World");
        assert_eq!(book_dir(&b("Über Nacht", &["Jörg Müßig"], Some("Grüße"), Some("1"), "DE")), "DE/Jörg Müßig/Grüße/01 - Über Nacht");
        assert_eq!(book_dir(&b("Mistborn: The Final Empire", &["Brandon Sanderson"], None, None, "EN")), "EN/Brandon Sanderson/Mistborn: The Final Empire");
        assert_eq!(book_dir(&b("AC/DC\tStory ", &[" Jane  Doe "], None, None, "EN")), "EN/Jane Doe/AC-DC Story");
    }

    #[test]
    fn dots_and_missing_names_cannot_escape() {
        assert_eq!(book_dir(&b("..", &[".."], None, None, "EN")), "EN/Unknown Author/Unknown Title");
        assert_eq!(book_dir(&b("T", &[], None, None, "EN")), "EN/Unknown Author/T");
    }

    #[test]
    fn languages() {
        assert_eq!(language_folder(Some("english")).as_deref(), Some("EN"));
        assert_eq!(language_folder(Some("German")).as_deref(), Some("DE"));
        assert_eq!(language_folder(Some("french")).as_deref(), Some("Other"));
        assert_eq!(language_folder(None), None);
        assert_eq!(mam_language(Some("The Hobbit by J.R.R. Tolkien [ENG / M4B]")).as_deref(), Some("EN"));
        assert_eq!(mam_language(Some("Der Hobbit by J.R.R. Tolkien [GER / MP3]")).as_deref(), Some("DE"));
        assert_eq!(mam_language(Some("Le Hobbit by J.R.R. Tolkien [FRE / MP3] [VIP]")).as_deref(), Some("Other"));
        assert_eq!(mam_language(Some("no flags here")), None);
    }
}
