#!/usr/bin/env python3
"""One-off: build the avatar gallery (18 rows x 9, human-made art only, no AI art).

Rows, in order (every row holds 3 feminine, 3 masculine and 3 neutral avatars;
the `vibe` field is only used to interleave them so each row looks mixed):

  storybook   original period storybook art (Tenniel, Potter, Busch, Hoffmann)
  paintings   famous public-domain paintings, cropped to the face/subject
  people3d    Microsoft Fluent Emoji 3D (MIT), centred on a soft square
  illustrated DiceBear "adventurer" / "lorelei"
  pixel       DiceBear "pixel-art"
  cartoon     DiceBear "avataaars" / "open-peeps" / "notionists"
  ukiyoe      Japanese woodblock prints (Utamaro, Sharaku, Hokusai, Hiroshige)
  belleepoque Belle Epoque posters (Mucha, Toulouse-Lautrec, Steinlen, Cheret)
  fairytale   fairy-tale illustration (Rackham, Dulac, Bilibin)
  comics      early newspaper comics (Segar, Herriman, Outcault, Fisher)
  flatemoji   Google Noto Emoji (Apache 2.0), centred on a soft square
  swiss       Swiss masters (Anker, Hodler, Segantini, Vallotton)
  classics    classic cartoons in the US public domain (Mickey, Felix, Pooh, ...)
  movies, tvcartoons, anime, games, memes
              pop culture - LOCAL PACK (see below)

Local pack: the pop-culture rows are third-party copyrighted character art.
They are written to app/img-local/ (gitignored: the repo is public) and marked
"pack": "local" in gallery.json; the picker hides any entry whose image is
missing, so a fresh clone works without them. Re-fetch them with
`--only movies,tvcartoons,anime,games,memes`. Their source URLs are listed in
LOCAL below and in LICENSES.md.

All Commons rows except `classics` use original period artwork whose artist
died before 1956 (public domain in Switzerland: life + 70 years). The `classics`
row is public domain in the US only (works published 1919-1930; their artists
died after 1956), see LICENSES.md. Commons images are fetched
through the Commons API (imageinfo, thumbnail at most 1920 px wide -> smaller
originals come back unscaled). The script refuses any file whose extmetadata
licence is not "Public domain". Each crop box is (x, y, size) in pixels of that
fetched image, chosen by hand so the face or subject is well framed; the square
is resized to 512x512 full-bleed (no background added). Licence tags/artist
death years were checked on each file page on 2026-10-18 and are recorded in
LICENSES.md.

Requests send only a generic User-Agent (no personal data). Set GALLERY_CACHE
to a directory to cache downloads between runs (be gentle with Wikimedia).

Writes app/img/<id>.png (+ app/img-local/<id>.png), app/gallery.json (flat list) and app/groups.json
(ordered rows), and deletes images no longer in the gallery. Re-run only to
change the gallery; the output is committed. `--only g1,g2` re-renders just
those rows' images (the JSON is always rewritten; other committed rows' images
must already exist, missing local-pack images are only reported). Needs Pillow (dev only).
"""
import colorsys, hashlib, io, json, os, pathlib, sys, time
import urllib.error, urllib.parse, urllib.request
from PIL import Image, ImageChops

ROOT = pathlib.Path(__file__).resolve().parents[1]
UA = "HomelabAvatarGallery/1.3 (private non-commercial gallery build)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FLUENT = "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/"
# Pinned to the last commit whose LICENSE is Apache 2.0 (the repo switched its
# LICENSE file to OFL 1.1 in commit 254596e5, 2024-07-29; images are unchanged).
NOTO = ("https://raw.githubusercontent.com/googlefonts/noto-emoji/"
        "41e31b110b4eb929dffb410264694a06205b7ad7/png/512/emoji_u{}.png")
DICEBEAR = "https://api.dicebear.com/9.x/{style}/png?size=512&backgroundColor={bg}&{opts}"
SIZE, EMOJI, MAX_BYTES = 512, 360, 500 * 1024
VIBES = ("feminine", "masculine", "neutral")
CACHE = pathlib.Path(os.environ["GALLERY_CACHE"]) if os.environ.get("GALLERY_CACHE") else None

GROUPS = [
    ("storybook", "Classic storybook"),
    ("paintings", "Art classics"),
    ("people3d", "3D characters"),
    ("illustrated", "Illustrated people"),
    ("pixel", "Pixel art"),
    ("cartoon", "Cartoon & sketch"),
    ("ukiyoe", "Japanese woodblock"),
    ("belleepoque", "Belle Époque posters"),
    ("fairytale", "Fairy-tale illustration"),
    ("comics", "Early comics"),
    ("flatemoji", "Flat emoji"),
    ("swiss", "Swiss masters"),
    ("classics", "Classic cartoons (public domain)"),
    ("movies", "Movies & animated films"),
    ("tvcartoons", "TV & cartoons"),
    ("anime", "Anime"),
    ("games", "Video games"),
    ("memes", "Memes"),
]

# Commons rows: (id, name, vibe, "File:..." title, (x, y, size) crop box)
COMMONS = {
    "storybook": [
        # John Tenniel (d. 1914), The Nursery "Alice" (colour), 1890 - {{PD-old-auto-expired}}
        ("alice", "Alice", "feminine",
         "File:John Tenniel - Illustration from The Nursery Alice (1890) - c03757 07.jpg",
         (340, 370, 300)),
        # Wilhelm Busch (d. 1908), Max und Moritz title image, 1865 - {{PD-Art|PD-old-auto-expired}}
        ("moritz", "Moritz", "masculine",
         "File:Max und Moritz.JPG", (320, 0, 310)),
        # John Tenniel (d. 1914), Alice's Adventures in Wonderland, 1865 - {{PD-old-100-1923}}
        ("cheshire-cat", "Cheshire", "neutral",
         "File:Cheshire Cat appearing (detail).jpg", (60, 40, 480)),
        # Beatrix Potter (d. 1943), The Tale of Jemima Puddle-Duck cover, 1908 - {{PD/1923}}
        ("jemima", "Jemima", "feminine",
         "File:The Tale of Jemima Puddle-Duck cover.jpg", (170, 245, 230)),
        # Heinrich Hoffmann (d. 1894), Der Struwwelpeter - {{PD-old-100}}
        ("struwwelpeter", "Struwwelpeter", "masculine",
         "File:Struwwelpeter 1.jpg", (135, 0, 420)),
        # John Tenniel (d. 1914), Alice's Adventures in Wonderland, 1865 - {{PD-old}}
        ("white-rabbit", "White Rabbit", "neutral",
         "File:Alice par John Tenniel 02.png", (100, 0, 440)),
        # John Tenniel (d. 1914), The Nursery "Alice" (colour), 1890 - {{PD-old-auto-expired}}
        ("queen-of-hearts", "Queen of Hearts", "feminine",
         "File:John Tenniel - Illustration from The Nursery Alice (1890) - c06544 02.jpg",
         (680, 330, 330)),
        # John Tenniel (d. 1914), The Nursery "Alice" (colour), 1890 - {{PD-old-auto-expired}}
        ("mad-hatter", "Mad Hatter", "masculine",
         "File:John Tenniel - Illustration from The Nursery Alice (1890) - c03757 07.jpg",
         (1200, 110, 520)),
        # Beatrix Potter (d. 1943), The Tale of Peter Rabbit, 1902 - {{PD-old-auto-expired}}
        ("peter-rabbit", "Peter", "neutral",
         "File:An-Original-Illustration-Of-Peter-Rabbit-From-1902-Author-Beatrix-Potter.jpg",
         (125, 50, 200)),
    ],
    "paintings": [
        # Leonardo da Vinci (d. 1519), c. 1503-06 - {{PD-art|PD-old-100-expired}}
        ("mona-lisa", "Mona", "feminine",
         "File:Mona Lisa, by Leonardo da Vinci, from C2RMF retouched.jpg", (300, 180, 1050)),
        # Vincent van Gogh (d. 1890), Self-Portrait 1887 - {{PD-Art|PD-old-100-expired}}
        ("van-gogh", "Vincent", "masculine",
         "File:Vincent van Gogh - Self-Portrait - Google Art Project (454045).jpg",
         (390, 440, 1150)),
        # Katsushika Hokusai (d. 1849), c. 1830-32 - {{PD-Art|PD-old-auto-expired}}
        ("great-wave", "Wave", "neutral",
         "File:Tsunami by hokusai 19th century.jpg", (300, 150, 1100)),
        # Johannes Vermeer (d. 1675), c. 1665 - {{PD-Art-two-auto}}
        ("pearl-earring", "Pearl", "feminine",
         "File:1665 Girl with a Pearl Earring.jpg", (330, 330, 1000)),
        # Rembrandt (d. 1669), Self-Portrait 1659 - {{PD-Art|PD-old-100-1923}}
        ("rembrandt", "Rembrandt", "masculine",
         "File:Rembrandt van Rijn - Self-Portrait - Google Art Project.jpg", (560, 160, 1000)),
        # Vincent van Gogh (d. 1890), The Starry Night 1889 - {{PD-Art|PD-old-100-expired}}
        ("starry-night", "Starry", "neutral",
         "File:Van Gogh - Starry Night - Google Art Project.jpg", (800, 0, 1120)),
        # Gustav Klimt (d. 1918), Adele Bloch-Bauer I 1907 - {{PD-Art|PD-old-auto-1923}}
        ("klimt-adele", "Adele", "feminine",
         "File:Gustav Klimt, 1907, Adele Bloch-Bauer I, Neue Galerie New York.jpg",
         (910, 0, 500)),
        # Albrecht Duerer (d. 1528), Self-Portrait 1500 - {{Licensed-PD-art|PD-old-auto-expired|cc-zero}}
        ("durer", "Albrecht", "masculine",
         "File:Albrecht Dürer - 1500 self-portrait (High resolution and detail).jpg",
         (380, 200, 1150)),
        # Claude Monet (d. 1926), Impression, Sunrise 1872 - {{PD-old-auto-1996}}
        ("monet-sunrise", "Sunrise", "neutral",
         "File:Monet - Impression, Sunrise.jpg", (500, 200, 1100)),
    ],
    "ukiyoe": [
        # Kitagawa Utamaro (d. 1806), Naniwaya Okita, c. 1793 - PD-Art
        ("utamaro-okita", "Okita", "feminine",
         "File:Utamaro Naniwaya Okita.JPG", (400, 235, 730)),
        # Toshusai Sharaku (fl. 1794-95), Otani Oniji as Yakko Edobei, 1794 - PD-Art (TNM)
        ("sharaku-oniji", "Oniji", "masculine",
         "File:The actor Otani Oniji II as Yakko Edobei - Sharaku - TNM.jpg", (350, 250, 1500)),
        # Katsushika Hokusai (d. 1849), Tiger in the Snow, 1849 - PD-Art
        ("hokusai-tiger", "Snow Tiger", "neutral",
         "File:Hokusai, Tiger in the Snow.jpg", (80, 400, 450)),
        # Kitagawa Utamaro (d. 1806), the courtesan Hanaogi, c. 1794 - PD-Art
        ("utamaro-hanaogi", "Hanaogi", "feminine",
         "File:Utamaro L'oiran Hanaogi.JPG", (220, 90, 900)),
        # Toshusai Sharaku (fl. 1794-95), Sawamura Sojuro III, 1794 - PD-Art
        ("sharaku-sojuro", "Sojuro", "masculine",
         "File:Sharaku - Sawamura Sojurō III.png", (480, 280, 1250)),
        # Katsushika Hokusai (d. 1849), Fine Wind, Clear Morning (Red Fuji), c. 1830-32 - PD-Art
        ("hokusai-red-fuji", "Red Fuji", "neutral",
         "File:Katsushika Hokusai - Fine Wind, Clear Morning (Gaifū kaisei) - Google Art Project.jpg",
         (680, 200, 1080)),
        # Kitagawa Utamaro (d. 1806), Three Beauties of the Present Day, c. 1793 - PD-Art
        ("utamaro-bijin", "Bijin", "feminine",
         "File:Utamaro1.jpg", (330, 250, 950)),
        # Toshusai Sharaku (fl. 1794-95), Ichikawa Yaozo III, 1794 - PD-Art (Rijksmuseum)
        ("sharaku-yaozo", "Yaozo", "masculine",
         "File:Busteportret van Ichikawa Yaozo III-Rijksmuseum RP-P-1956-590.jpeg",
         (380, 450, 1200)),
        # Utagawa Hiroshige (d. 1858), Asakusa Ricefields and Torinomachi Festival, 1857 - PD-Art
        ("hiroshige-cat", "Neko", "neutral",
         "File:Hiroshige, Asakusa ricefields and torinomachi festival, 1857.jpg", (430, 1350, 650)),
    ],
    "belleepoque": [
        # Alphonse Mucha (d. 1939), Zodiac (La Plume calendar), 1896 - PD-Art
        ("mucha-zodiac", "Zodiac", "feminine",
         "File:Alphonse Mucha - Zodiac, 1869.jpg", (380, 540, 650)),
        # Henri de Toulouse-Lautrec (d. 1901), Ambassadeurs: Aristide Bruant, 1892 - PD-Art
        ("lautrec-bruant", "Aristide", "masculine",
         "File:Lautrec Ambassadeurs Aristide Bruant.jpg", (60, 180, 480)),
        # Theophile-Alexandre Steinlen (d. 1923), Tournee du Chat Noir, 1896 - PD-Art
        ("steinlen-chat-noir", "Chat Noir", "neutral",
         "File:Théophile Alexandre Steinlen - Tournée du Chat Noir - Google Art Project.jpg",
         (550, 120, 650)),
        # Henri de Toulouse-Lautrec (d. 1901), Jane Avril, 1899 - PD-Art
        ("lautrec-jane-avril", "Jane", "feminine",
         "File:Lautrec jane avril (poster) 1899.jpg", (200, 90, 280)),
        # Henri de Toulouse-Lautrec (d. 1901), Divan Japonais (Edouard Dujardin), 1893 - PD-Art
        ("lautrec-dujardin", "Edouard", "masculine",
         "File:1893 color lithograph by de Toulouse-Lautrec - Divan Japonais.jpg", (1350, 600, 500)),
        # Theophile-Alexandre Steinlen (d. 1923), 2e Exposition des artistes animaliers, 1909 - PD-Art
        ("steinlen-tabby", "Minou", "neutral",
         "File:2e Exposition des artistes animaliers au Cercle International des Arts, affiche, estampe, Steinlen monogr..jpg",
         (960, 0, 440)),
        # Jules Cheret (d. 1932), Yvette Guilbert au Concert Parisien, 1891 - PD-Art
        ("cheret-yvette", "Yvette", "feminine",
         "File:Cheret-Yvette-Guilbert.jpg", (430, 280, 450)),
        # Henri de Toulouse-Lautrec (d. 1901), Moulin Rouge - La Goulue (Valentin le Desosse), 1891 - PD-Art
        ("lautrec-valentin", "Valentin", "masculine",
         "File:Henri de Toulouse-Lautrec, Moulin Rouge - La Goulue, 1891 - The Metropolitan Museum of Art.jpg",
         (1200, 1250, 700)),
        # Theophile-Alexandre Steinlen (d. 1923), Calico cat, before 1923 - PD-old-auto-expired
        ("steinlen-calico", "Calico", "neutral",
         "File:Calico cat (Steinlen).jpg", (250, 230, 450)),
    ],
    "fairytale": [
        # Ivan Bilibin (d. 1942), Vasilisa the Beautiful, 1899 - PD-old
        ("bilibin-vasilisa", "Vasilisa", "feminine",
         "File:Russian Wonder Tales 081.jpg", (660, 660, 340)),
        # Ivan Bilibin (d. 1942), Ivan Tsarevich and the Firebird, 1899 - PD-old
        ("bilibin-ivan", "Ivan", "masculine",
         "File:Сказка об Иване-царевиче, Жар-птице и Сером Волке 2.jpg", (1080, 780, 360)),
        # Ivan Bilibin (d. 1942), the Firebird (same plate), 1899 - PD-old
        ("bilibin-firebird", "Firebird", "neutral",
         "File:Сказка об Иване-царевиче, Жар-птице и Сером Волке 2.jpg", (60, 100, 450)),
        # Edmund Dulac (d. 1953), The Snow Queen, 1911 - PD-old
        ("dulac-snow-queen", "Snow Queen", "feminine",
         "File:Edmund Dulac - The Snow Queen.jpg", (380, 90, 260)),
        # Arthur Rackham (d. 1939), Rip Van Winkle, 1905 - PD-old
        ("rackham-rip", "Rip", "masculine",
         "File:Rip Van Winkle-125.jpg", (430, 930, 560)),
        # Edmund Dulac (d. 1953), Stories from Hans Andersen (The Snow Queen, goblins), 1911 - PD-old
        ("dulac-imp", "Imp", "neutral",
         "File:Stories from Hans Andersen - Edmund Dulac color plate at page 005.jpg",
         (550, 1150, 350)),
        # Ivan Bilibin (d. 1942), Baba Yaga, 1900 - PD-old
        ("bilibin-baba-yaga", "Baba Yaga", "feminine",
         "File:Bilibin. Baba Yaga.jpg", (440, 400, 340)),
        # Edmund Dulac (d. 1953), The Sleeping Beauty and Other Fairy Tales, plate p. 81, 1910 - PD-old
        ("dulac-sultan", "Sultan", "masculine",
         "File:The sleeping beauty and other fairy tales - color plate facing page 081.jpg",
         (1150, 1080, 380)),
        # Edmund Dulac (d. 1953), Stories from Hans Andersen (The Snow Queen, reindeer), 1911 - PD-old
        ("dulac-reindeer", "Reindeer", "neutral",
         "File:Stories from Hans Andersen - Edmund Dulac color plate at page 063.jpg",
         (480, 1050, 550)),
    ],
    "comics": [
        # E. C. Segar (d. 1938), Thimble Theatre, 24 Jan 1929 - {{PD-old-auto-expired}}
        ("olive", "Olive", "feminine",
         "File:Popeye and Olive Oyl - First shared panel.png", (540, 70, 220)),
        # E. C. Segar (d. 1938), Thimble Theatre, 26 Dec 1929
        ("popeye", "Popeye", "masculine",
         "File:Sea Hag from Thimble Theatre (December 26, 1929).png", (700, 330, 330)),
        # George Herriman (d. 1944), Krazy Kat, 17 Dec 1918
        ("krazy-kat", "Krazy", "neutral",
         "File:Krazy Kat 1.png", (0, 0, 250)),
        # R. F. Outcault (d. 1928), "Hully Gee" - The Yellow Kid meets Tige and Mary Jane, 1907 (LOC)
        ("mary-jane", "Mary Jane", "feminine",
         "File:“HULLY GEE” - The Yellow Kid, he meets Tige and Mary Jane and LCCN2001698002 (cropped).jpg",
         (40, 380, 280)),
        # R. F. Outcault (d. 1928), same drawing, 1907 (LOC)
        ("yellow-kid", "Yellow Kid", "masculine",
         "File:“HULLY GEE” - The Yellow Kid, he meets Tige and Mary Jane and LCCN2001698002 (cropped).jpg",
         (840, 400, 260)),
        # R. F. Outcault (d. 1928), same drawing, 1907 (LOC)
        ("tige", "Tige", "neutral",
         "File:“HULLY GEE” - The Yellow Kid, he meets Tige and Mary Jane and LCCN2001698002 (cropped).jpg",
         (150, 590, 240)),
        # George McManus (d. 1954), Maggie, Jiggs and a hotel bellhop (Bringing Up Father), 1921
        ("maggie", "Maggie", "feminine",
         "File:Maggie, Jiggs, and a hotel bellhop (original art).jpg", (200, 440, 380)),
        # Bud Fisher (d. 1954), Mutt and Jeff Book 7 cover, 1920
        ("mutt", "Mutt", "masculine",
         "File:Mutt and Jeff Book 7 Cover.jpg", (1180, 820, 360)),
        # E. C. Segar (d. 1938), Thimble Theatre, Eugene the Jeep debut, 1936
        ("jeep", "Jeep", "neutral",
         "File:Eugene The Jeep debut.jpg", (700, 120, 230)),
    ],
    "swiss": [
        # Albert Anker (d. 1910), Maedchenbildnis, 1885 - PD-Art
        ("anker-girl", "Anker Girl", "feminine",
         "File:Albert Anker - Mädchenbildnis.jpg", (300, 100, 1350)),
        # Albert Anker (d. 1910), Knabe mit roter Weste, 1885 - PD-Art
        ("anker-boy", "Anker Boy", "masculine",
         "File:Albert Anker - Knabe mit roter Weste (1885).jpg", (250, 50, 1350)),
        # Ferdinand Hodler (d. 1918), Eiger, Moench und Jungfrau in der Morgensonne, 1908 - PD-Art
        ("hodler-jungfrau", "Jungfrau", "neutral",
         "File:Hodler - Eiger, Mönch und Jungfrau in der Morgensonne - 1908.jpg", (200, 0, 1300)),
        # Ferdinand Hodler (d. 1918), Giulia Leonardi, 1910 - PD-Art
        ("hodler-giulia", "Giulia", "feminine",
         "File:Ferdinand Hodler Giulia Leonardi.jpg", (50, 200, 1300)),
        # Felix Vallotton (d. 1925), Self-Portrait, 1914 - PD-Art
        ("vallotton-self", "Felix", "masculine",
         "File:Félix Vallotton, 1914 - Self Portrait.jpg", (250, 80, 620)),
        # Giovanni Segantini (d. 1899), Midday in the Alps (sheep detail), 1891 - PD-Art
        ("segantini-sheep", "Alp Sheep", "neutral",
         "File:Segantini - Midday in the Alps, 1891.jpg", (600, 640, 480)),
        # Felix Vallotton (d. 1925), Portrait of the actress Marthe Mellot, 1898 - PD-Art
        ("vallotton-mellot", "Marthe", "feminine",
         "File:Félix Vallotton, 1898 - Portrait de l'actrice Marthe Mellot.jpg", (130, 80, 600)),
        # Giovanni Segantini (d. 1899), Self-portrait (charcoal), 1893 - PD-Art
        ("segantini-self", "Giovanni", "masculine",
         "File:Segantini Selbstportrait1893.jpg", (250, 350, 1300)),
        # Ferdinand Hodler (d. 1918), Thunersee mit symmetrischer Spiegelung, 1905 - PD-Art
        ("hodler-thunersee", "Thunersee", "neutral",
         "File:Hodler - Thunersee mit symmetrischer Spiegelung - 1905.jpg", (380, 250, 1200)),
    ],
    # Classic cartoons: public domain in the US only (published 1919-1930, 95-year
    # term expired; NOT yet PD in Switzerland/EU, life + 70). Early designs only.
    # Optional 6th field True = tint the white paper with the avatar colour.
    "classics": [
        # Walt Disney & Ub Iwerks, Steamboat Willie (frame), 1928 - {{PD-old-50-expired}}, US PD since 2024
        ("minnie-1928", "Minnie (1928)", "feminine",
         "File:Minnie Mouse (Steamboat Willie).png", (90, 20, 300)),
        # Walt Disney Productions, The Chain Gang poster, 1930 - {{PD-US-expired}}, US PD since 2026
        ("mickey-1930", "Mickey (1930)", "masculine",
         "File:The Chain Gang.jpg", (120, 10, 230)),
        # Pat Sullivan / Educational Pictures, Exhibitors Herald ad, June 1925 - {{PD-US-expired}}
        ("felix-1925", "Felix the Cat", "neutral",
         "File:Felix the Cat - June 1925 EH.jpg", (0, 410, 210)),
        # Dave Fleischer, Dizzy Dishes (first Betty Boop), 1930 - {{PD-US-expired}}, US PD since 2026
        ("betty-boop-1930", "Betty (1930)", "feminine",
         "File:Betty Boop First Version.png", (160, 0, 340)),
        # E. H. Shepard, Winnie-the-Pooh (1926), p. 115 - {{PD-US-expired}}, US PD since 2022
        ("pooh-1926", "Pooh (1926)", "masculine",
         "File:Winnie-the-Pooh 115.png", (660, 70, 320), True),
        # Walt Disney, The Chain Gang (unnamed bloodhound, later Pluto), 1930 - {{PD-US-expired}}
        ("pluto-1930", "Pluto (1930)", "neutral",
         "File:Disney's Pluto first and second appearances in 1930.jpg", (40, 20, 250)),
        # Floyd Gottfredson, Mickey Mouse comic strip, 14 May 1930 - {{PD-US-expired}}
        ("clarabelle-1930", "Clarabelle (1930)", "feminine",
         "File:Clarabelle Cow, 1930.jpg", (10, 0, 200)),
        # Walt Disney & Ub Iwerks, Trolley Troubles (frame), 1927 - {{PD-US-expired}}, US PD since 2023
        ("oswald-1927", "Oswald (1927)", "masculine",
         "File:Oswald1927.png", (40, 10, 300)),
        # E. H. Shepard, Winnie-the-Pooh (1926) - {{PD-US-expired}}, US PD since 2022
        ("piglet-1926", "Piglet (1926)", "neutral",
         "File:Piglet EHShepard.jpg", (640, 120, 420), True),
    ],
}

# Local pack: third-party copyrighted character art. Rendered into app/img-local/
# (gitignored, never committed; baked into the private Docker image only) and
# marked "pack": "local" in gallery.json. Sources are the low-resolution infobox
# images of the character's English Wikipedia article (non-free, fetched straight
# from upload.wikimedia.org), Wikimedia Commons photos for the meme animals, and
# Studio Ghibli's official free-to-use stills (ghibli.jp/info/013344).
# (id, name, vibe, image URL, (x, y, size) crop box - may exceed the image; any
# transparent or outside area becomes the avatar colour)
WP = "https://upload.wikimedia.org/wikipedia/"
LOCAL = {
    "movies": [
        ("elsa", "Elsa", "feminine", WP + "en/5/5e/Elsa_from_Disney%27s_Frozen.png", (10, 0, 100)),
        ("shrek", "Shrek", "masculine", WP + "en/4/4d/Shrek_%28character%29.png", (35, 0, 150)),
        ("wall-e", "WALL-E", "neutral", WP + "en/6/68/WALL-E_%28character%29.png", (25, 0, 230)),
        ("moana", "Moana", "feminine", WP + "en/5/56/Moana_%28character%29.png", (40, 0, 120)),
        ("darth-vader", "Darth Vader", "masculine",
         WP + "en/0/0b/Darth_Vader_in_The_Empire_Strikes_Back.jpg", (95, 0, 120)),
        ("grogu", "Grogu", "neutral", WP + "en/a/a0/Grogu_%28Star_Wars%29.jpg", (70, 0, 200)),
        ("fiona", "Fiona", "feminine", WP + "en/b/b9/Princess_Fiona.png", (52, 0, 85)),
        ("mike-wazowski", "Mike Wazowski", "masculine", WP + "en/6/6a/Mike_Wazowski.png", (10, 0, 240)),
        ("stitch", "Stitch", "neutral",
         WP + "en/thumb/d/d2/Stitch_%28Lilo_%26_Stitch%29.svg/960px-Stitch_%28Lilo_%26_Stitch%29.svg.png",
         (40, 30, 880)),
    ],
    "tvcartoons": [
        ("lisa-simpson", "Lisa", "feminine", WP + "en/e/ec/Lisa_Simpson.png", (20, 0, 210)),
        ("homer-simpson", "Homer", "masculine", WP + "en/0/02/Homer_Simpson_2006.png", (50, 0, 135)),
        ("spongebob", "SpongeBob", "neutral",
         WP + "commons/thumb/a/a2/SpongeBob_character.svg/960px-SpongeBob_character.svg.png",
         (80, 50, 800)),
        ("velma", "Velma", "feminine", WP + "en/9/9d/Velma_Dinkley.png", (40, 0, 110)),
        ("fred-flintstone", "Fred", "masculine", WP + "en/a/ad/Fred_Flintstone.png", (55, 0, 125)),
        ("scooby-doo", "Scooby-Doo", "neutral", WP + "en/5/53/Scooby-Doo.png", (35, 20, 120)),
        ("leela", "Leela", "feminine", WP + "en/d/d4/Turanga_Leela.png", (60, 20, 105)),
        ("rick-sanchez", "Rick", "masculine", WP + "en/a/a6/Rick_Sanchez.png", (25, 0, 105)),
        ("garfield", "Garfield", "neutral",
         WP + "en/thumb/b/bc/Garfield_the_Cat.svg/960px-Garfield_the_Cat.svg.png", (20, 0, 330)),
    ],
    "anime": [
        ("sailor-moon", "Sailor Moon", "feminine", WP + "en/2/2b/Sailor_Moon_01.jpg", (40, 40, 125)),
        ("goku", "Goku", "masculine", WP + "en/4/4c/GokumangaToriyama.png", (25, 0, 120)),
        ("pikachu", "Pikachu", "neutral", WP + "en/a/a6/Pok%C3%A9mon_Pikachu_art.png", (10, 20, 280)),
        ("nezuko", "Nezuko", "feminine", WP + "en/c/c0/NezukoKamado.png", (70, 30, 130)),
        ("naruto", "Naruto", "masculine", WP + "en/9/9a/NarutoUzumaki.png", (190, 15, 100)),
        ("totoro", "Totoro", "neutral", "https://www.ghibli.jp/gallery/totoro034.jpg", (400, 200, 838)),
        ("chihiro", "Chihiro", "feminine", "https://www.ghibli.jp/gallery/chihiro001.jpg", (800, 40, 340)),
        ("luffy", "Luffy", "masculine", WP + "en/c/cb/Monkey_D_Luffy.png", (20, 0, 140)),
        ("jiji", "Jiji", "neutral", "https://www.ghibli.jp/gallery/majo050.jpg", (1120, 470, 200)),
    ],
    "games": [
        ("princess-peach", "Peach", "feminine", WP + "en/1/16/Princess_Peach_Stock_Art.png", (40, 0, 140)),
        ("mario", "Mario", "masculine", WP + "en/5/5c/Mario_by_Shigehisa_Nakaue.png", (50, 0, 190)),
        ("pac-man", "Pac-Man", "neutral",
         WP + "commons/f/fb/Pac-Man_ingame_and_2D_alternative_design.png", (360, 10, 375)),
        ("zelda", "Zelda", "feminine", WP + "en/6/6e/Link_to_the_Past_Zelda.png", (50, 0, 110)),
        ("sonic", "Sonic", "masculine", WP + "en/f/f4/Sonic_modern_and_classic_designs.png", (15, 0, 140)),
        ("kirby", "Kirby", "neutral", WP + "en/4/4e/Kirby_Nintendo.png", (20, 0, 300)),
        ("lara-croft", "Lara", "feminine", WP + "en/a/a8/LaraCroftInfobox.png", (98, 10, 80)),
        ("master-chief", "Master Chief", "masculine", WP + "en/4/42/Master_chief_halo_infinite.png",
         (75, 20, 100)),
        ("yoshi", "Yoshi", "neutral", WP + "en/d/db/Yoshi_%28Nintendo_character%29.png", (10, 0, 220)),
    ],
    # Memes: animals and drawn/rendered characters only (no real people's faces).
    "memes": [
        ("doge", "Doge", "feminine",  # Kabosu; crop excludes her owner
         WP + "commons/c/cb/Kabosu_and_Atsuko_Sato_2023-11-02_%281%29.jpg", (650, 600, 600)),
        ("cheems", "Cheems", "masculine", WP + "en/1/14/Balltze_%28Cheems%29.jpg", (115, 70, 170)),
        ("nyan-cat", "Nyan Cat", "neutral", WP + "en/e/ed/Nyan_cat_250px_frame.PNG", (100, 60, 150)),
        ("grumpy-cat", "Grumpy Cat", "feminine",
         WP + "commons/d/dc/Grumpy_Cat_%2814556024763%29_%28cropped%29.jpg", (40, 130, 560)),
        ("meme-man", "Stonks", "masculine",
         WP + "en/9/96/Meme_Man_on_transparent_background.webp", (40, 0, 300)),
        ("bongo-cat", "Bongo Cat", "neutral", WP + "en/7/7a/Bongo_cat.png", (50, 30, 170)),
        ("lil-bub", "Lil Bub", "feminine", WP + "commons/b/b8/Lil-Bub-2013_%28cropped%29.jpg", (60, 0, 330)),
        ("smudge", "Smudge", "masculine",  # the table cat only, no people
         WP + "en/1/1f/WomanYellingAtACat_meme.jpg", (285, 30, 150)),
        ("pesto", "Pesto", "neutral", WP + "commons/4/4a/Pesto_%28penguin%29_%28cropped%29.png",
         (400, 100, 1300)),
    ],
}

# Fluent Emoji 3D: (id, name, vibe, upstream folder, skin tone or None, background)
FLUENT_ITEMS = [
    ("astronaut", "Astronaut", "feminine", "Woman astronaut", "Medium-Dark", "#CFE0FA"),
    ("firefighter", "Firefighter", "masculine", "Man firefighter", "Medium-Light", "#FFD6CC"),
    ("fox", "Fox", "neutral", "Fox", None, "#FFD8B5"),
    ("artist", "Artist", "feminine", "Woman artist", "Light", "#F6D9F0"),
    ("scientist", "Scientist", "masculine", "Man scientist", "Dark", "#D4F0E8"),
    ("panda", "Panda", "neutral", "Panda", None, "#D9F2D0"),
    ("technologist", "Coder", "feminine", "Woman technologist", "Medium", "#E3DCFA"),
    ("mage", "Wizard", "masculine", "Man mage", "Light", "#E0D4F5"),
    ("owl", "Owl", "neutral", "Owl", None, "#E3D5C3"),
]

# Noto Emoji (flat): (id, name, vibe, codepoint sequence as in the file name, background)
NOTO_ITEMS = [
    ("noto-detective", "Detective", "feminine", "1f575_1f3fb_200d_2640", "#DDE3EA"),
    ("noto-pilot", "Pilot", "masculine", "1f468_1f3fc_200d_2708", "#CFE8F7"),
    ("noto-tiger", "Tiger", "neutral", "1f42f", "#FFE2BF"),
    ("noto-farmer", "Farmer", "feminine", "1f469_1f3fe_200d_1f33e", "#DCEFC9"),
    ("noto-vampire", "Vampire", "masculine", "1f9db_1f3fb_200d_2642", "#EED3DA"),
    ("noto-octopus", "Octopus", "neutral", "1f419", "#D3EEF0"),
    ("noto-princess", "Princess", "feminine", "1f478_1f3fd", "#F7D9EC"),
    ("noto-prince", "Prince", "masculine", "1f934_1f3ff", "#E2DCF6"),
    ("noto-robot", "Robot", "neutral", "1f916", "#F4E6C4"),
]

# DiceBear: group -> [(id, name, vibe, style, options query)]
DICE = {
    "illustrated": [
        ("adventurer-flora", "Flora", "feminine", "adventurer",
         "seed=Felicity&hair=long03&earringsProbability=100&mouth=variant01&eyes=variant01"),
        ("adventurer-oscar", "Oscar", "masculine", "adventurer",
         "seed=Oscar&hair=short04&features=mustache&featuresProbability=100&mouth=variant02&skinColor=f2d3b1"),
        ("adventurer-kai", "Kai", "neutral", "adventurer",
         "seed=Kai&hair=short01&hairColor=3eac2c&glassesProbability=100&mouth=variant02&skinColor=ecad80"),
        ("adventurer-ruby", "Ruby", "feminine", "adventurer",
         "seed=Amelia&hair=long14&hairColor=ab2a18&mouth=variant02"),
        ("adventurer-leo", "Leo", "masculine", "adventurer",
         "seed=Leo&hair=short09&skinColor=763900&hairColor=0e0e0e&mouth=variant01"),
        ("adventurer-robin", "Robin", "neutral", "adventurer",
         "seed=Robin&hair=short06&hairColor=85c2c6&mouth=variant01"),
        ("lorelei-blossom", "Blossom", "feminine", "lorelei",
         "seed=Ella&hair=variant35&hairAccessoriesProbability=100&mouth=happy02"),
        ("lorelei-jack", "Jack", "masculine", "lorelei",
         "seed=Jack&hair=variant02&beard=variant02&beardProbability=100&mouth=happy02"),
        ("lorelei-river", "River", "neutral", "lorelei",
         "seed=River&hair=variant18&glassesProbability=0&beardProbability=0&mouth=happy02"),
    ],
    "pixel": [
        ("pixel-lily", "Lily", "feminine", "pixel-art",
         "seed=Lily&hair=long02&mouth=happy01&beardProbability=0&hatProbability=0"),
        ("pixel-bram", "Bram", "masculine", "pixel-art",
         "seed=Bram&hair=short03&beard=variant02&beardProbability=100&mouth=happy01&hatProbability=0"),
        ("pixel-nova", "Nova", "neutral", "pixel-art",
         "seed=Nova&hat=variant02&hatProbability=100&mouth=happy01&beardProbability=0"),
        ("pixel-scarlet", "Scarlet", "feminine", "pixel-art",
         "seed=Daisy&hair=long08&hairColor=bd1700&mouth=happy03&beardProbability=0&hatProbability=0"),
        ("pixel-tom", "Tom", "masculine", "pixel-art",
         "seed=Tom&hair=short10&beard=variant05&beardProbability=100&mouth=happy02"
         "&hatProbability=0&skinColor=8d5524"),
        ("pixel-shades", "Shades", "neutral", "pixel-art",
         "seed=Bit&hat=variant05&hatProbability=100&mouth=happy03&beardProbability=0"
         "&glassesProbability=100"),
        ("pixel-mae", "Mae", "feminine", "pixel-art",
         "seed=Mae&hair=long12&mouth=happy09&beardProbability=0&hatProbability=0&glassesProbability=0"),
        ("pixel-gus", "Gus", "masculine", "pixel-art",
         "seed=Gus&hair=short20&beard=variant07&beardProbability=100&mouth=happy01&hatProbability=0"),
        ("pixel-quest", "Quest", "neutral", "pixel-art",
         "seed=Quest&hat=variant08&hatProbability=100&mouth=happy02&beardProbability=0"),
    ],
    "cartoon": [
        ("avataaars-ava", "Ava", "feminine", "avataaars",
         "seed=Ava&top=longButNotTooLong&mouth=smile&eyes=happy&facialHairProbability=0"
         "&accessoriesProbability=0"),
        ("avataaars-ben", "Ben", "masculine", "avataaars",
         "seed=Ben&top=shortFlat&facialHair=beardMedium&facialHairProbability=100&mouth=smile"
         "&eyes=default&eyebrows=defaultNatural"),
        ("avataaars-pat", "Pat", "neutral", "avataaars",
         "seed=Pat&top=hat&mouth=twinkle&eyes=default&facialHairProbability=0&accessories=round"
         "&accessoriesProbability=100"),
        ("peep-bea", "Bea", "feminine", "open-peeps",
         "seed=Bea&head=bun&face=smileBig&facialHairProbability=0"),
        ("peep-hugo", "Hugo", "masculine", "open-peeps",
         "seed=Hugo&head=short1&facialHair=full&facialHairProbability=100&face=calm"),
        ("peep-jo", "Jo", "neutral", "open-peeps",
         "seed=Jo&head=hatBeanie&face=cute&facialHairProbability=0"),
        ("notion-lena", "Lena", "feminine", "notionists",
         "seed=Lena&hair=variant45&beardProbability=0&glassesProbability=0&gestureProbability=0"),
        ("notion-ned", "Ned", "masculine", "notionists",
         "seed=Ned&hair=variant10&beard=variant03&beardProbability=100"),
        ("notion-ash", "Ash", "neutral", "notionists",
         "seed=Ash&hair=variant05&beardProbability=0&glassesProbability=100"),
    ],
}

# Colour-index order: the original rows keep their colours (and DiceBear
# backgrounds) from v1.1; rows added later continue the sequence.
COLOR_ORDER = ["storybook", "paintings", "illustrated", "pixel", "cartoon",
               "ukiyoe", "belleepoque", "fairytale", "comics", "swiss",
               "classics", "movies", "tvcartoons", "anime", "games", "memes"]
# Rows whose f/m/n order is not enforced (kept in the order listed above).
FREE_VIBE = {"memes"}


def pastel(i):
    """Distinct soft colour: hue stepped around the wheel."""
    r, g, b = colorsys.hls_to_rgb((i * 0.381966) % 1.0, 0.86, 0.6)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))

def get(url, tries=7):
    """GET (generic User-Agent only) with polite back-off on HTTP 429/503."""
    cached = CACHE / hashlib.sha1(url.encode()).hexdigest() if CACHE else None
    if cached and cached.exists():
        return cached.read_bytes()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if cached:
                cached.parent.mkdir(parents=True, exist_ok=True); cached.write_bytes(data)
            return data
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == tries - 1:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 0) or 10 * 2 ** attempt)

def commons(title):
    """Fetch a Commons file (<=1920 px wide) after checking it is public domain."""
    q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "imageinfo",
                                "iiprop": "url|extmetadata", "iiurlwidth": 1920, "format": "json"})
    page = next(iter(json.loads(get(f"{COMMONS_API}?{q}"))["query"]["pages"].values()))
    info = page["imageinfo"][0]
    lic = info["extmetadata"].get("LicenseShortName", {}).get("value", "")
    if lic != "Public domain":
        raise SystemExit(f"{title}: licence is {lic!r}, not public domain")
    return Image.open(io.BytesIO(get(info.get("thumburl") or info["url"]))).convert("RGB")

def save(img, path):
    """Save a 512 PNG; quantise photo-like content if it would exceed MAX_BYTES."""
    buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
    if buf.tell() > MAX_BYTES:
        buf = io.BytesIO()
        img.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG) \
           .save(buf, "PNG", optimize=True)
    path.write_bytes(buf.getvalue())

def fluent(folder, tone):
    if tone:
        rel = f"{folder}/{tone}/3D/{folder.lower().replace(' ', '_')}_3d_{tone.lower()}.png"
    else:
        rel = f"{folder}/3D/{folder.lower().replace(' ', '_')}_3d.png"
    return Image.open(io.BytesIO(get(FLUENT + urllib.parse.quote(rel)))).convert("RGBA")

def noto(seq):
    return Image.open(io.BytesIO(get(NOTO.format(seq)))).convert("RGBA")

def on_square(emoji, color):
    """Centre an RGBA emoji on a solid soft-coloured 512 square."""
    emoji = emoji.resize((EMOJI, EMOJI), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), color)
    off = (SIZE - EMOJI) // 2
    canvas.alpha_composite(emoji, (off, off))
    return canvas.convert("RGB")

def interleave(items):
    """Order a row f, m, n, f, m, n, ... so every row looks mixed."""
    if items and items[0]["group"] in FREE_VIBE:
        return items
    by = {v: [i for i in items if i["vibe"] == v] for v in VIBES}
    return [by[v][k] for k in range(3) for v in VIBES]

def local_image(url, color, box):
    """Fetch a local-pack image and crop it; transparent/outside areas take `color`."""
    x, y, s = box
    src = Image.open(io.BytesIO(get(url))).convert("RGBA")
    canvas = Image.new("RGBA", (s, s), color)
    canvas.alpha_composite(src.crop((x, y, x + s, y + s)))
    return canvas.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)

def tint(img, color):
    """Multiply line art on white paper with a soft colour."""
    return ImageChops.multiply(img, Image.new("RGB", img.size, color))

def main():
    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--only":
        only = set(sys.argv[2].split(","))
        unknown = only - {g for g, _ in GROUPS}
        if unknown:
            raise SystemExit(f"unknown groups: {sorted(unknown)}")
    out = ROOT / "app" / "img"; out.mkdir(parents=True, exist_ok=True)
    out_local = ROOT / "app" / "img-local"; out_local.mkdir(parents=True, exist_ok=True)
    rows = {}
    colors = iter(pastel(i) for i in range(1000))
    color_of = {}
    for gid in COLOR_ORDER:
        for item in COMMONS.get(gid, []) + DICE.get(gid, []) + LOCAL.get(gid, []):
            color_of[item[0]] = next(colors)

    def add(group, aid, name, vibe, color, render, pack=None):
        path = (out_local if pack else out) / f"{aid}.png"
        if only is None or group in only:
            save(render(), path); print("ok", group, aid)
        elif not path.exists():
            if not pack:
                raise SystemExit(f"{aid}.png missing; rebuild group {group!r}")
            print("missing (local pack, hidden by the picker):", aid)
        entry = {"id": aid, "name": name, "file": f"{aid}.png", "color": color,
                 "group": group, "vibe": vibe}
        if pack:
            entry["pack"] = pack
        rows.setdefault(group, []).append(entry)

    for group, items in COMMONS.items():
        for aid, name, vibe, title, (x, y, s), *opt in items:
            def render(title=title, x=x, y=y, s=s, aid=aid, tinted=bool(opt and opt[0])):
                src = commons(title)
                if not CACHE:
                    time.sleep(2)  # be gentle with upload.wikimedia.org
                if x + s > src.width or y + s > src.height:
                    raise SystemExit(f"{aid}: crop box exceeds {src.size}")
                img = src.crop((x, y, x + s, y + s)).resize((SIZE, SIZE), Image.LANCZOS)
                return tint(img, color_of[aid]) if tinted else img
            add(group, aid, name, vibe, color_of[aid], render)
    for group, items in LOCAL.items():
        for aid, name, vibe, url, box in items:
            def render(url=url, color=color_of[aid], box=box):
                img = local_image(url, color, box)
                if not CACHE:
                    time.sleep(2)
                return img
            add(group, aid, name, vibe, color_of[aid], render, pack="local")
    for aid, name, vibe, folder, tone, color in FLUENT_ITEMS:
        add("people3d", aid, name, vibe, color,
            lambda folder=folder, tone=tone, color=color: on_square(fluent(folder, tone), color))
    for aid, name, vibe, seq, color in NOTO_ITEMS:
        add("flatemoji", aid, name, vibe, color,
            lambda seq=seq, color=color: on_square(noto(seq), color))
    for group, items in DICE.items():
        for aid, name, vibe, style, opts in items:
            color = color_of[aid]
            def render(style=style, opts=opts, color=color):
                img = Image.open(io.BytesIO(get(DICEBEAR.format(
                    style=style, bg=color[1:], opts=opts)))).convert("RGB")
                return img if img.size == (SIZE, SIZE) else img.resize((SIZE, SIZE), Image.LANCZOS)
            add(group, aid, name, vibe, color, render)
    gallery = [a for gid, _ in GROUPS for a in interleave(rows[gid])]
    for d, pack in ((out, None), (out_local, "local")):
        keep = {g["file"] for g in gallery if g.get("pack") == pack}
        for f in d.iterdir():
            if f.suffix == ".png" and f.name not in keep:
                f.unlink(); print("removed", f.name)
    (ROOT / "app" / "gallery.json").write_text(json.dumps(gallery, indent=2) + "\n")
    (ROOT / "app" / "groups.json").write_text(
        json.dumps([{"id": i, "label": l} for i, l in GROUPS], indent=2) + "\n")

if __name__ == "__main__":
    main()
