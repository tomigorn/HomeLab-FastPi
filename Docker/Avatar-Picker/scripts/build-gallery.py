#!/usr/bin/env python3
"""One-off: build the avatar gallery (37 rows, each a multiple of 9 avatars,
human-made art only, no AI art).

Rows, in order (every row holds equal numbers of feminine, masculine and neutral
avatars; the `vibe` field is only used to interleave them f, m, n, ... so each
row looks mixed - the memes, colours, Pokemon, Lord of the Rings, Dinosaurs, Harry Potter, Marvel & DC,
Muppets, Animals, Space, Historic figures, Retro games and Vox Machina rows are exempt). One character
never appears in two rows (tests/test_gallery.py checks it):

  disney      Disney & Pixar (27)               - LOCAL PACK (see below)
  animated    Animated films, other studios (27) - LOCAL PACK
  movies      Movies, live action (27)          - LOCAL PACK (in-character stills/posters)
  lotr        Lord of the Rings, the films' major cast (27) - LOCAL PACK (film stills)
  harrypotter Harry Potter, the films' major cast (18) - LOCAL PACK
  heroes      Marvel & DC, live-action heroes (27) - LOCAL PACK
  tvcartoons  Cartoons, animated TV (36)        - LOCAL PACK
  voxmachina  The Legend of Vox Machina, main cast (9) - LOCAL PACK
  tvshows     TV series, live action (36)       - LOCAL PACK
  muppets     Muppets & Sesame Street (18)      - LOCAL PACK
  anime       Anime (63)                        - LOCAL PACK
  pokemon     Pokemon (18, all "neutral")       - LOCAL PACK
  games       Video games (36)                  - LOCAL PACK
  retro       Retro games (9, all "neutral")    - LOCAL PACK
  mario       Super Mario (18)                  - LOCAL PACK
  lego        LEGO minifigures (18)             - LOCAL PACK (BrickLink catalogue photos, cut out)
  dinosaurs   Dinosaurs (18, all "neutral")     - LOCAL PACK (TotalDino paleoart, Commons CC BY / CC BY-SA / CC0)
  animals     Animals, real photos (27, all "neutral") - LOCAL PACK (Commons)
  space       Space, NASA / ESA images (27, all "neutral") - LOCAL PACK (Commons)
  storybook   original period storybook art (Tenniel, Potter, Busch, Hoffmann)
  illustrated DiceBear "adventurer" / "lorelei"
  flatemoji   Google Noto Emoji (Apache 2.0), centred on a soft square (18)
  paintings   famous public-domain paintings, cropped to the face/subject (18)
  mythology   Mythology, public-domain art and sculpture (18) - LOCAL PACK (Commons)
  historic    Historic figures, period portraits and photos (18) - LOCAL PACK (Commons)
  pirates     Pirates & knights, period engravings and paintings (9) - LOCAL PACK (Commons)
  memes       Memes - animals and drawn characters only (18) - LOCAL PACK
  cartoon     DiceBear "avataaars" / "open-peeps" / "notionists"
  ukiyoe      Japanese woodblock prints (Utamaro, Sharaku, Hokusai, Hiroshige)
  belleepoque Belle Epoque posters (Mucha, Toulouse-Lautrec, Steinlen, Cheret)
  fairytale   fairy-tale illustration (Rackham, Dulac, Bilibin)
  comics      early newspaper comics (Segar, Herriman, Outcault, Fisher)
  swiss       Swiss masters (Anker, Hodler, Segantini, Vallotton)
  people3d    Microsoft Fluent Emoji 3D (MIT), centred on a soft square
  pixel       DiceBear "pixel-art"
  classics    classic cartoons in the US public domain (Mickey, Felix, Pooh, ...)
  colours     solid colours, gradients and rainbows generated here with Pillow
              (18, no downloads) - for people who do not want a picture

Local pack: the pop-culture rows are third-party copyrighted character art.
They are written to app/img-local/ (gitignored: the repo is public) and marked
"pack": "local" in gallery.json; the picker hides any entry whose image is
missing, so a fresh clone works without them. Re-fetch them with
`--only disney,animated,movies,lotr,harrypotter,heroes,tvcartoons,voxmachina,tvshows,muppets,anime,pokemon,games,retro,mario,lego,dinosaurs,animals,space,mythology,historic,pirates,memes`. Their source URLs are listed in
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
must already exist, missing local-pack images are only reported). `--missing` renders
only images that do not exist yet (delete one to re-render it). Needs Pillow (dev only).
"""
import colorsys, hashlib, io, json, os, pathlib, sys, time, zipfile
import urllib.error, urllib.parse, urllib.request
from PIL import Image, ImageChops, ImageFilter, ImageOps

ROOT = pathlib.Path(__file__).resolve().parents[1]
UA = "HomelabAvatarGallery/1.5 (private non-commercial gallery build)"
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
    ("disney", "Disney & Pixar"),
    ("animated", "Animated films"),
    ("movies", "Movies"),
    ("lotr", "Lord of the Rings"),
    ("harrypotter", "Harry Potter"),
    ("heroes", "Marvel & DC"),
    ("tvcartoons", "Cartoons"),
    ("voxmachina", "Vox Machina"),
    ("tvshows", "TV series"),
    ("muppets", "Muppets & Sesame Street"),
    ("anime", "Anime"),
    ("pokemon", "Pokémon"),
    ("games", "Video games"),
    ("retro", "Retro games"),
    ("mario", "Super Mario"),
    ("lego", "LEGO"),
    ("dinosaurs", "Dinosaurs"),
    ("animals", "Animals"),
    ("space", "Space"),
    ("storybook", "Classic storybook"),
    ("illustrated", "Illustrated people"),
    ("flatemoji", "Flat emoji"),
    ("paintings", "Art classics"),
    ("mythology", "Mythology"),
    ("historic", "Historic figures"),
    ("pirates", "Pirates & knights"),
    ("memes", "Memes"),
    ("cartoon", "Cartoon & sketch"),
    ("ukiyoe", "Japanese woodblock"),
    ("belleepoque", "Belle Époque posters"),
    ("fairytale", "Fairy-tale illustration"),
    ("comics", "Early comics"),
    ("swiss", "Swiss masters"),
    ("people3d", "3D characters"),
    ("pixel", "Pixel art"),
    ("classics", "Classic cartoons (public domain)"),
    ("colours", "Colours"),
]

# Commons rows: (id, name, vibe, "File:..." title, (x, y, size) crop box)
COMMONS = {
    "storybook": [
        # John Tenniel (d. 1914), The Nursery "Alice" (colour), 1890 - {{PD-old-auto-expired}}
        ("alice", "Alice", "feminine",
         "File:John Tenniel - Illustration from The Nursery Alice (1890) - 066110.jpg",
         (560, 0, 520)),
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
         (380, 300, 1200)),
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
        # --- v1.4: nine more (licence tags checked 2026-10-19) ---
        # Sandro Botticelli (d. 1510), The Birth of Venus c. 1485 - {{PD-Art|PD-old-100-expired}}
        ("botticelli-venus", "Venus", "feminine",
         "File:Sandro Botticelli - La nascita di Venere - Google Art Project - edited.jpg",
         (930, 60, 200)),  # v1.5: face and hair only (no nudity)
        # Giuseppe Arcimboldo (d. 1593), Vertumnus (Rudolf II) 1591 - {{PD-Art|PD-old-100-expired}}
        ("arcimboldo-vertumnus", "Vertumnus", "masculine",
         "File:Giuseppe Arcimboldo - Rudolf II of Habsburg as Vertumnus - Google Art Project.jpg",
         (350, 100, 1200)),
        # Vincent van Gogh (d. 1890), Sunflowers (fourth version) 1888 - {{PD-Art|PD-old-100-expired}}
        ("van-gogh-sunflowers", "Sunflowers", "neutral",
         "File:Vincent Willem van Gogh 127.jpg", (0, 150, 1920)),
        # Johannes Vermeer (d. 1675), The Milkmaid c. 1660 - {{PD-Art|PD-old-100-expired}}
        ("vermeer-milkmaid", "Milkmaid", "feminine",
         "File:Johannes Vermeer - Het melkmeisje - Google Art Project.jpg", (900, 180, 600)),
        # Jan van Eyck (d. 1441), Portrait of a Man (Self-Portrait?) 1433 - {{PD-Art|PD-old-100-expired}}
        ("van-eyck-turban", "Turban", "masculine",
         "File:Portrait of a Man in a Turban (Jan van Eyck).jpg", (330, 250, 1250)),
        # Edvard Munch (d. 1944), The Scream 1893 - {{PD-Art|PD-old-auto-expired}} (PD in CH/EU since 2015)
        ("munch-scream", "Scream", "neutral",
         "File:Edvard Munch, 1893, The Scream, oil, tempera and pastel on cardboard, 91 x 73 cm, National Gallery of Norway.jpg",
         (420, 800, 1050)),
        # Pierre-Auguste Renoir (d. 1919), Portrait of Irene Cahen d'Anvers 1880 - {{PD-Art|PD-old-auto-expired}}
        ("renoir-irene", "Irène", "feminine",
         "File:Pierre-Auguste Renoir, 1880, Portrait of Mademoiselle Irène Cahen d'Anvers, Sammlung E.G. Bührle.jpg",
         (650, 200, 750)),
        # Johannes Vermeer (d. 1675), The Astronomer c. 1668 - {{PD-Art|PD-old-100-expired}}
        ("vermeer-astronomer", "Astronomer", "masculine",
         "File:Johannes Vermeer - The Astronomer - WGA24685.jpg", (520, 360, 380)),
        # Gustav Klimt (d. 1918), The Kiss 1907-08 - {{PD-Art|PD-old-auto-expired}}
        ("klimt-kiss", "The Kiss", "neutral",
         "File:The Kiss - Gustav Klimt - Google Cultural Institute.jpg", (500, 150, 800)),
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
         (330, 560, 880)),
        # Utagawa Hiroshige (d. 1858), Asakusa Ricefields and Torinomachi Festival, 1857 - PD-Art
        ("hiroshige-cat", "Neko", "neutral",
         "File:Hiroshige, Asakusa ricefields and torinomachi festival, 1857.jpg", (480, 1400, 560)),
    ],
    "belleepoque": [
        # Alphonse Mucha (d. 1939), Zodiac (La Plume calendar), 1896 - PD-Art
        ("mucha-zodiac", "Zodiac", "feminine",
         "File:Alphonse Mucha - Zodiac, 1869.jpg", (380, 540, 650)),
        # Henri de Toulouse-Lautrec (d. 1901), Ambassadeurs: Aristide Bruant, 1892 - PD-Art
        ("lautrec-bruant", "Aristide", "masculine",
         "File:Lautrec Ambassadeurs Aristide Bruant.jpg", (120, 210, 420)),
        # Theophile-Alexandre Steinlen (d. 1923), Tournee du Chat Noir, 1896 - PD-Art
        ("steinlen-chat-noir", "Chat Noir", "neutral",
         "File:Théophile Alexandre Steinlen - Tournée du Chat Noir - Google Art Project.jpg",
         (615, 215, 520)),
        # Henri de Toulouse-Lautrec (d. 1901), Jane Avril, 1899 - PD-Art
        ("lautrec-jane-avril", "Jane", "feminine",
         "File:Lautrec jane avril (poster) 1899.jpg", (200, 90, 280)),
        # Henri de Toulouse-Lautrec (d. 1901), Divan Japonais (Edouard Dujardin), 1893 - PD-Art
        ("lautrec-dujardin", "Edouard", "masculine",
         "File:1893 color lithograph by de Toulouse-Lautrec - Divan Japonais.jpg", (1360, 520, 320)),
        # Theophile-Alexandre Steinlen (d. 1923), 2e Exposition des artistes animaliers, 1909 - PD-Art
        ("steinlen-tabby", "Minou", "neutral",
         "File:2e Exposition des artistes animaliers au Cercle International des Arts, affiche, estampe, Steinlen monogr..jpg",
         (960, 0, 440)),
        # Jules Cheret (d. 1932), Yvette Guilbert au Concert Parisien, 1891 - PD-Art
        ("cheret-yvette", "Yvette", "feminine",
         "File:Cheret-Yvette-Guilbert.jpg", (580, 340, 280)),
        # Henri de Toulouse-Lautrec (d. 1901), Moulin Rouge - La Goulue (Valentin le Desosse), 1891 - PD-Art
        ("lautrec-valentin", "Valentin", "masculine",
         "File:Henri de Toulouse-Lautrec, Moulin Rouge - La Goulue, 1891 - The Metropolitan Museum of Art.jpg",
         (1180, 1280, 640)),
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
         "File:Popeye and Olive Oyl - First shared panel.png", (520, 95, 240)),
        # E. C. Segar (d. 1938), Thimble Theatre, 26 Dec 1929
        ("popeye", "Popeye", "masculine",
         "File:Sea Hag from Thimble Theatre (December 26, 1929).png", (720, 270, 270)),
        # George Herriman (d. 1944), Krazy Kat, 17 Dec 1918
        ("krazy-kat", "Krazy", "neutral",
         "File:Krazy Kat 1.png", (0, 0, 240)),
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
         "File:Eugene The Jeep debut.jpg", (740, 150, 160)),
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
    # Classic cartoons: public domain in the US only (built into the local pack, see
    # LOCAL_COMMONS) (published 1919-1930, 95-year
    # term expired; NOT yet PD in Switzerland/EU, life + 70). Early designs only.
    # Optional 6th field True = tint the white paper with the avatar colour.
    "classics": [
        # Walt Disney & Ub Iwerks, Steamboat Willie (frame), 1928 - {{PD-old-50-expired}}, US PD since 2024
        ("minnie-1928", "Minnie (1928)", "feminine",
         "File:Minnie Mouse (Steamboat Willie).png", (90, 20, 300)),
        # Walt Disney Productions, The Chain Gang poster, 1930 - {{PD-US-expired}}, US PD since 2026
        ("mickey-1930", "Mickey (1930)", "masculine",
         "File:The Chain Gang.jpg", (150, 20, 200)),
        # Pat Sullivan / Educational Pictures, Exhibitors Herald ad, June 1925 - {{PD-US-expired}}
        ("felix-1925", "Felix the Cat", "neutral",
         "File:Felix the Cat - June 1925 EH.jpg", (0, 410, 210)),
        # Dave Fleischer, Dizzy Dishes (first Betty Boop), 1930 - {{PD-US-expired}}, US PD since 2026
        ("betty-boop-1930", "Betty (1930)", "feminine",
         "File:Betty Boop First Version.png", (160, 0, 340)),
        # E. H. Shepard, Winnie-the-Pooh (1926), p. 115 - {{PD-US-expired}}, US PD since 2022
        ("pooh-1926", "Pooh (1926)", "masculine",
         "File:Winnie-the-Pooh 115.png", (660, 10, 330), True),
        # Walt Disney, The Chain Gang (unnamed bloodhound, later Pluto), 1930 - {{PD-US-expired}}
        ("pluto-1930", "Pluto (1930)", "neutral",
         "File:Disney's Pluto first and second appearances in 1930.jpg", (40, 20, 250)),
        # Floyd Gottfredson, Mickey Mouse comic strip, 14 May 1930 - {{PD-US-expired}}
        ("clarabelle-1930", "Clarabelle (1930)", "feminine",
         "File:Clarabelle Cow, 1930.jpg", (10, 0, 200)),
        # Walt Disney & Ub Iwerks, Trolley Troubles (frame), 1927 - {{PD-US-expired}}, US PD since 2023
        ("oswald-1927", "Oswald (1927)", "masculine",
         "File:Oswald1927.png", (19, 0, 360)),
        # E. H. Shepard, Winnie-the-Pooh (1926) - {{PD-US-expired}}, US PD since 2022
        ("piglet-1926", "Piglet (1926)", "neutral",
         "File:Piglet EHShepard.jpg", (600, 80, 480), True),
    ],
}

# Commons rows that are public domain in the US but not in Switzerland/EU: built
# from Commons like the others, but written to the local-only pack (not in git).
LOCAL_COMMONS = {"classics"}

# Local pack: third-party copyrighted character art. Rendered into app/img-local/
# (gitignored, never committed; baked into the private Docker image only) and
# marked "pack": "local" in gallery.json. Sources are the low-resolution infobox
# images of the character's English (or Italian) Wikipedia article (non-free, fetched straight
# from upload.wikimedia.org), Wikimedia Commons photos for the meme animals, and
# Studio Ghibli's official free-to-use stills (ghibli.jp/info/013344).
# (id, name, vibe, image URL, (x, y, size) crop box). Transparent sources: the box
# may run past the image, the avatar colour fills the rest (gallery.json "square").
# Opaque sources: the box must lie inside the image (it is clamped, with a warning).
WP = "https://upload.wikimedia.org/wikipedia/"
# Disney's official character portraits (frozen.disney.com, princess.disney.com,
# characters.disney.com/toy-story, cars.disney.com, movies.disney.com/big-hero-6)
DISNEY = "https://lumiere-a.akamaihd.net/v1/images/"
# Illumination's official character renders (illumination.com/movie/...)
ILLUMINATION = "https://www.illumination.com/wp-content/uploads/"
# BrickLink catalogue minifigure photos (img.bricklink.com/ItemImage/MN/0/<item no>.png)
BRICKLINK = "https://img.bricklink.com/ItemImage/MN/0/"
CUT = {"cutout": 248}
# v1.10 sources: the KSP wiki, Steam store art, the Outer Wilds press kit (one file of the archive:
# "<zip>#<member>"), the official Frieren and Delicious in Dungeon sites, Behind The Voice Actors
KSP = "https://wiki.kerbalspaceprogram.com/images/"
STEAM = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/"
OUTER_WILDS_PRESS = "https://www.mobiusdigitalgames.com/uploads/4/7/3/2/47328935/outer_wilds_press.zip"
FRIEREN = "https://frieren-anime.jp/wp-content/uploads/"
DUNGEON = "https://delicious-in-dungeon.com/assets/character/"
VOXMACHINA = "https://www.behindthevoiceactors.com/_img/chars/"
LOCAL = {
    # Disney & Pixar (27): Disney Animation and Pixar characters, 1937-2021
    "disney": [
        ("elsa", "Elsa", "feminine", DISNEY + "ct_frozen_elsa_18466_22a50822_ad6090d1.jpeg", (40, 20, 520)),
        ("anna", "Anna", "feminine", DISNEY + "ct_frozen_anna_18466_6775584b_520ae44b.jpeg", (40, 20, 520)),
        ("moana", "Moana", "feminine", DISNEY + "ct_princess_moana_3497_0a28209c.jpeg", (90, 40, 620)),
        ("rapunzel", "Rapunzel", "feminine", DISNEY + "ct_princess_rapunzel_3497_5b2f90a4.jpeg", (130, 40, 600)),
        ("ariel", "Ariel", "feminine", DISNEY + "ct_princess_ariel_3497_d17c9d8a.jpeg", (40, 20, 620)),
        ("mirabel", "Mirabel", "feminine", WP + "en/e/e7/Mirabel_Madrigal.png", (28, 0, 155)),
        ("joy", "Joy", "feminine", WP + "en/3/30/Joy_-_Inside_Out.webp", (0, 0, 189)),
        ("merida", "Merida", "feminine", DISNEY + "ct_princess_merida_3497_7906fc57.jpeg", (60, 20, 680)),
        ("snow-white", "Snow White", "feminine", DISNEY + "ct_princess_snowwhite_3497_e41686e8.jpeg", (120, 20, 620)),
        ("mike-wazowski", "Mike Wazowski", "masculine", WP + "en/6/6a/Mike_Wazowski.png", (25, 4, 200)),
        ("simba", "Simba", "masculine",
         WP + "en/9/94/Simba_%28_Disney_character_-_adult%29.png",
         (22, -8, 178)),
        ("genie", "Genie", "masculine", WP + "en/0/0c/The_Genie_Aladdin.png", (55, -10, 170)),
        ("mr-incredible", "Mr. Incredible", "masculine", WP + "en/2/22/Mr._Incredible.png", (62, -2, 124)),
        ("carl", "Carl", "masculine", WP + "en/9/9f/Carl_from_Up_2009.png", (41, -10, 165)),
        ("donald-duck", "Donald Duck", "masculine",
         WP + "en/a/a5/Donald_Duck_angry_transparent_background.png",
         (27, 0, 170)),
        ("goofy", "Goofy", "masculine", WP + "en/5/50/Goofy_Duckipedia.png", (50, -6, 158)),
        ("sulley", "Sulley", "masculine", WP + "en/6/63/Monsters_Inc.JPG", (67, 36, 121)),
        ("buzz-lightyear", "Buzz Lightyear", "masculine",
         DISNEY + "b_toystory_characterbanner_buzz_desktop_gradient_v2_78f93ff8.jpeg", (870, 0, 280)),
        ("stitch", "Stitch", "neutral",
         WP + "en/thumb/d/d2/Stitch_%28Lilo_%26_Stitch%29.svg/960px-Stitch_%28Lilo_%26_Stitch%29.svg.png",
         (0, 0, 960)),
        ("olaf", "Olaf", "neutral", DISNEY + "ct_frozen_olaf_18466_eabe1344_2dd6212f.jpeg", (0, 0, 600)),
        ("wall-e", "WALL-E", "neutral", WP + "en/6/68/WALL-E_%28character%29.png", (0, 5, 271)),
        ("mater", "Mater", "neutral", DISNEY + "mater_characterimage_b6ea14ea.jpeg", (190, 40, 400)),
        ("dory", "Dory", "neutral", WP + "en/a/ae/Dory_%28Finding_Nemo%29.png", (-18, 0, 336)),
        ("baymax", "Baymax", "neutral", DISNEY + "character_bighero6_baymax_5aa2754b_14cc5b05.jpeg", (60, 40, 330)),
        ("thumper", "Thumper", "neutral", WP + "en/a/ab/Thumper_%28Bambi_character%29.png", (0, -19, 298)),
        ("sisu", "Sisu", "neutral", WP + "en/a/aa/Disney_Sisu.png", (31, -12, 217)),
        ("rex", "Rex", "neutral", DISNEY + "t_toystory_rex_characterimage_v3_646b6daa.jpeg", (120, 20, 400)),
    ],
    # Animated films (27): other studios - DreamWorks, Illumination, Sony, Warner, Aardman, Laika, Blue Sky, Fox/Don Bluth, Netflix, Cartoon Saloon
    "animated": [
        ("fiona", "Fiona", "feminine", WP + "en/b/b9/Princess_Fiona.png", (45, 0, 115)),
        ("gwen-stacy", "Spider-Gwen", "feminine",
         WP + "en/b/b1/Gwen_Stacy_%28Into_the_Spider-Verse%29.jpg",
         (71, 14, 174)),
        ("lola-bunny", "Lola Bunny", "feminine",
         WP + "en/thumb/3/3d/Lola_Bunny_Space_Jam_svg.svg/960px-Lola_Bunny_Space_Jam_svg.svg.png",
         (230, 0, 500)),
        ("anastasia", "Anastasia", "feminine", WP + "en/0/09/Anya_Anastasia.jpeg", (0, 24, 252)),
        ("nimona", "Nimona", "feminine", WP + "en/f/f5/Nimona_poster.png", (72, 108, 91)),
        ("agnes", "Agnes", "feminine", ILLUMINATION + "2019/11/A_P0170_SRGB.png", (300, 380, 560)),
        ("shrek-dragon", "Dragon (Shrek)", "feminine", WP + "en/c/cd/Shrek_Dragon_render.png", (-2, 20, 170)),
        ("fei-fei", "Fei Fei", "feminine", WP + "en/d/dc/Over_the_Moon_%282020%29.png", (82, 19, 92)),
        ("poppy", "Poppy", "feminine", WP + "en/b/bd/Trolls3film.jpg", (20, 255, 126)),
        ("shrek", "Shrek", "masculine", WP + "en/4/4d/Shrek_%28character%29.png", (45, -10, 185)),
        ("po", "Po", "masculine",
         WP + "en/3/3d/Po_from_DreamWorks_Animation%27s_Kung_Fu_Panda.png",
         (0, -20, 250)),
        ("gru", "Gru", "masculine", WP + "en/0/09/Gru_from_DM4.png", (45, -5, 125)),
        ("puss-in-boots", "Puss in Boots", "masculine",
         WP + "en/8/8a/Puss_in_Boots_from_Shrek.png",
         (34, -2, 136)),
        ("miles-morales", "Miles Morales", "masculine",
         WP + "en/5/50/Miles_Morales_%28Across_the_Spider-Verse%29.jpg",
         (88, 38, 190)),
        ("wallace", "Wallace", "masculine", WP + "en/e/ec/Wallace_and_gromit.jpg", (90, 0, 164)),
        ("megamind", "Megamind", "masculine",
         "https://www.dreamworks.com/storage/movies/megamind/megamind-about.jpg", (120, 60, 1200)),
        ("boss-baby", "Boss Baby", "masculine", WP + "en/0/0e/The_Boss_Baby_poster.jpg", (44, 58, 132)),
        ("mr-wolf", "Mr. Wolf", "masculine", WP + "en/0/00/The_Bad_Guys_poster.jpeg", (108, 27, 102)),
        ("scrat", "Scrat", "neutral", WP + "en/e/ec/Scrat_Ice_Age.png", (0, -68, 300)),
        ("minion", "Minion", "neutral", ILLUMINATION + "2019/11/Minions_Kevin2.png", (200, 100, 820)),
        ("donkey", "Donkey", "neutral", WP + "en/6/6c/Donkey_%28Shrek%29.png", (22, -9, 154)),
        ("toothless", "Toothless", "neutral",
         WP + "commons/thumb/4/48/Chimuelo_en_el_Parque_de_la_Amistad_%287%29.jpg/1920px-Chimuelo_en_el_Parque_de_la_Amistad_%287%29.jpg",
         (880, 700, 640)),
        ("shaun", "Shaun the Sheep", "neutral",
         "https://www.aardman.com/media/pkgdssav/beast_still_square.jpg", (505, 585, 380)),
        ("spirit", "Spirit", "neutral",
         WP + "en/3/3b/Spirit_Stallion_of_the_Cimarron_poster.jpg",
         (53, 100, 91)),
        ("max", "Max", "neutral", ILLUMINATION + "2019/11/Pets_Max.png", (240, 40, 720)),
        ("snowball", "Snowball", "neutral", ILLUMINATION + "2019/11/Pets_Snowball.png", (0, 0, 1188)),
        ("buster-moon", "Buster Moon", "neutral", ILLUMINATION + "2019/10/Sing_Buster_2.png", (250, 300, 700)),
    ],
    # Movies (27): live-action film characters, in-character stills/posters/infobox images (no candid photos)
    "movies": [
        ("mary-poppins", "Mary Poppins", "feminine",
         WP + "commons/8/84/Mary_Poppins_screen_2_%28cropped%29.jpg",
         (65, 154, 405)),
        ("dorothy", "Dorothy", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/98/The_Wizard_of_Oz_Judy_Garland_1939.jpg/1280px-The_Wizard_of_Oz_Judy_Garland_1939.jpg",
         (320, 130, 640)),
        ("leia", "Leia", "feminine",
         WP + "en/1/1b/Princess_Leia%27s_characteristic_hairstyle.jpg",
         (44, 6, 156)),
        ("trinity", "Trinity", "feminine", WP + "en/7/7a/MatrixTrinity.jpg", (62, 15, 100)),
        ("matilda", "Matilda", "feminine", WP + "en/3/39/Matilda-Mara-Wilson.webp", (75, 36, 201)),
        ("elle-woods", "Elle Woods", "feminine", WP + "en/0/00/Elle_Woods.jpg", (58, 17, 173)),
        ("katniss", "Katniss", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/74/Katniss_Everdeen_%28Jennifer_Lawrence%29_figure_at_Madame_Tussauds_London_%2831139647115%29.jpg/1280px-Katniss_Everdeen_%28Jennifer_Lawrence%29_figure_at_Madame_Tussauds_London_%2831139647115%29.jpg",
         (416, 32, 448)),
        ("darth-vader", "Darth Vader", "masculine",
         WP + "en/0/0b/Darth_Vader_in_The_Empire_Strikes_Back.jpg",
         (71, 0, 174)),
        ("yoda", "Yoda", "masculine", WP + "en/9/9b/Yoda_Empire_Strikes_Back.png", (0, 0, 250)),
        ("indiana-jones", "Indiana Jones", "masculine",
         WP + "en/1/10/Indiana_Jones_and_the_Temple_of_Doom_PosterB.jpg",
         (76, 86, 127)),
        ("marty-mcfly", "Marty McFly", "masculine",
         WP + "en/d/d8/Michael_J._Fox_as_Marty_McFly_in_Back_to_the_Future%2C_1985.jpg",
         (26, 0, 180)),
        ("willy-wonka", "Willy Wonka", "masculine",
         WP + "en/8/85/Gene_Wilder_as_Willy_Wonka.jpeg",
         (67, 33, 201)),
        ("han-solo", "Han Solo", "masculine", WP + "en/c/c9/Han_Solo_with_Blaster.jpg", (20, 0, 175)),
        ("neo", "Neo", "masculine", WP + "en/c/c6/NeoTheMatrix.jpg", (68, 38, 138)),
        ("slimer", "Slimer", "neutral",
         WP + "en/7/7c/Slimer_%28Ghostbusters_1984_film_character%29.png",
         (15, -32, 270)),
        ("r2-d2", "R2-D2", "neutral",
         WP + "commons/6/61/Parents_of_Earth%2C_are_your_children_fully_immunized_%284647268251%29_%28cropped%29_auto_color_%28cropped_to_R2-D2%29.jpg",
         (32, 8, 588)),
        ("e-t", "E.T.", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/ce/E.T._figure_at_Madame_Tussauds_London.jpg/1280px-E.T._figure_at_Madame_Tussauds_London.jpg",
         (224, 24, 704)),
        ("c-3po", "C-3PO", "neutral",
         WP + "commons/5/5b/Parents_of_Earth%2C_are_your_children_fully_immunized_%284647268251%29_%28cropped%29_auto_color_%28cropped_to_C-3PO%29.jpg",
         (60, 0, 500)),
        ("godzilla", "Godzilla", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/99/Godzilla_%281954%29_%28cropped%29.jpg/1280px-Godzilla_%281954%29_%28cropped%29.jpg",
         (371, 92, 384)),
        ("king-kong", "King Kong", "neutral",
         WP + "commons/3/30/King_Kong_1933_Promotional_Image.png",
         (284, 20, 230)),
        ("stay-puft", "Stay Puft", "neutral",
         WP + "en/0/01/Mr._Stay-Puft_Marshmallow_Man.png",
         (40, -1, 188)),
        ("lassie", "Lassie", "neutral", WP + "commons/4/4e/Lassie.jpg", (222, 144, 300)),
        # v1.9: Hermione and the heroes moved to their own rows; these keep the row at 27
        ("ripley", "Ripley", "feminine", WP + "en/1/17/Ellen_ripley.jpg", (75, 0, 115)),
        ("amelie", "Amélie", "feminine", WP + "en/5/53/Amelie_poster.jpg", (36, 43, 213)),
        ("james-bond", "James Bond", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/d9/Sean_Connery_as_James_Bond_at_Switzerland_1964_%28two_thirds_crop%29.jpg/1280px-Sean_Connery_as_James_Bond_at_Switzerland_1964_%28two_thirds_crop%29.jpg",
         (0, 244, 1280)),
        ("terminator", "Terminator", "masculine",
         WP + "en/d/d6/T-800_Model_101_%28Arnold_Schwarzenegger%29_T2_1991_cutout.png",
         (40, -10, 95)),
        ("chewbacca", "Chewbacca", "neutral", WP + "en/f/f1/Chewbacca.png", (72, -20, 95)),
    ],
    # Lord of the Rings (18): the major cast of Peter Jackson's films (2001-2003), film stills
    # from the characters' English or Italian Wikipedia articles; listed order is the row order
    # (vibe-exempt). Gandalf is the Grey (hat and staff), the look of most of the story. Sauron twice on
    # purpose (v1.9.1): the Eye on Barad-dur and the armoured Dark Lord (the only armoured film still is
    # 352x199 and too dark, so a sharp Commons photo of a film-accurate armour costume); then eight more
    # of the major cast (Italian Wikipedia film frames).
    "lotr": [
        ("frodo", "Frodo", "masculine", WP + "it/d/d6/Il_Signore_degli_Anelli_341.jpg", (281, 0, 530)),
        ("gandalf", "Gandalf", "masculine", WP + "it/f/fb/Gandalf_film.png", (569, 0, 440)),
        ("arwen", "Arwen", "feminine", WP + "it/f/fd/Il_Signore_degli_Anelli_039.jpg", (321, 0, 525)),
        ("samwise", "Sam", "masculine", WP + "it/f/f5/Il_Signore_degli_Anelli_288.jpg", (136, 0, 480)),
        ("aragorn", "Aragorn", "masculine", WP + "it/c/cd/ISDA_Elessar.PNG", (125, 3, 261)),
        ("galadriel", "Galadriel", "feminine",
         WP + "it/0/00/Galadriel_%28Cate_Blanchett%29.png", (238, 0, 480)),
        ("gollum", "Gollum", "neutral", WP + "en/e/e0/Gollum.PNG", (18, 10, 190)),
        ("legolas", "Legolas", "masculine", WP + "en/2/2b/Legolas600ppx.jpg", (66, 20, 200)),
        ("eowyn", "Éowyn", "feminine",
         WP + "it/2/2d/LOTR_-_Return_of_the_King_-_%C3%89owyn.png", (306, 10, 430)),
        ("gimli", "Gimli", "masculine", WP + "it/9/93/GimliMoria.JPG", (302, 17, 420)),
        ("boromir", "Boromir", "masculine", WP + "it/3/3d/Il_Signore_degli_Anelli_064.JPG", (601, 20, 440)),
        ("saruman", "Saruman", "masculine", WP + "en/a/aa/Christopher_Lee_as_Saruman_LOTR.jpg", (88, 3, 177)),
        ("merry", "Merry", "masculine", WP + "en/4/4a/Meriadoc_Brandybuck_screenshot.jpg", (26, 10, 200)),
        ("pippin", "Pippin", "masculine", WP + "it/1/1a/Il_Signore_degli_Anelli_336.jpg", (283, 0, 530)),
        ("theoden", "Théoden", "masculine", WP + "en/3/3a/Th%C3%A9oden600ppx.png", (56, 0, 260)),
        ("elrond", "Elrond", "masculine", WP + "it/0/0e/Il_Signore_degli_Anelli_058.jpg", (263, 0, 526)),
        ("bilbo", "Bilbo", "masculine", WP + "en/7/78/Bilbo_Baggins.jpg", (22, 5, 150)),
        ("sauron", "Eye of Sauron", "neutral", WP + "it/c/c3/Il_Signore_degli_Anelli_132.JPG", (255, 35, 330)),
        ("sauron-armour", "Sauron (armour)", "neutral",
         "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d0/"
         "Sauron_Tolkien_2015_Calgary_Expo_%E2%80%93_Calgary_Comic_%26_Entertainment_Expo_%2816599548683%29.jpg/"
         "1280px-Sauron_Tolkien_2015_Calgary_Expo_%E2%80%93_Calgary_Comic_%26_Entertainment_Expo_%2816599548683%29.jpg",
         (128, 0, 1152)),
        ("faramir", "Faramir", "masculine", WP + "it/c/c0/Il_Signore_degli_Anelli_244.jpg", (560, 0, 460)),
        ("mouth-of-sauron", "Mouth of Sauron", "masculine", WP + "it/a/a2/Il_Signore_degli_Anelli_317.JPG", (380, 0, 528)),
        ("treebeard", "Treebeard", "neutral", WP + "it/0/0d/Il_Signore_degli_Anelli_157.jpg", (210, 0, 529)),
        ("denethor", "Denethor", "masculine", WP + "it/4/45/Il_Signore_degli_Anelli_245.JPG", (335, 0, 529)),
        ("shelob", "Shelob", "neutral", WP + "it/4/43/Il_Signore_degli_Anelli_291.jpg", (470, 0, 520)),
        ("witch-king", "Witch-king", "masculine", WP + "it/8/8e/Il_Signore_degli_Anelli_298.jpg", (680, 0, 400)),
        ("celeborn", "Celeborn", "masculine", WP + "it/d/d6/Il_Signore_degli_Anelli_107.jpg", (400, 0, 480)),
        ("balrog", "Balrog", "neutral", WP + "it/4/4c/Il_Signore_degli_Anelli_096.JPG", (560, 60, 700)),
    ],
    # Cartoons (27): animated TV characters across eras and studios
    "tvcartoons": [
        ("lisa-simpson", "Lisa", "feminine", WP + "en/e/ec/Lisa_Simpson.png", (19, -20, 185)),
        ("velma", "Velma", "feminine", WP + "en/9/9d/Velma_Dinkley.png", (38, -12, 125)),
        ("leela", "Leela", "feminine", WP + "en/d/d4/Turanga_Leela.png", (14, -4, 135)),
        ("marge-simpson", "Marge", "feminine", WP + "en/0/0b/Marge_Simpson.png", (-45, 0, 220)),
        ("daphne", "Daphne", "feminine", WP + "en/1/1d/Daphne_Blake.png", (48, -6, 117)),
        ("mabel-pines", "Mabel", "feminine", WP + "en/4/4b/Mabel_Pines.png", (45, -6, 179)),
        ("powerpuff-girls", "Blossom (Powerpuff)", "feminine",
         WP + "en/7/7b/Blossom_PPG_98_Art.png",
         (-20, -20, 280)),
        ("smurfette", "Smurfette", "feminine", WP + "en/f/fe/Smurfette-comics_version.png", (33, 9, 178)),
        ("dora", "Dora", "feminine", WP + "en/9/99/Dora_the_Explorer_%28character%29.webp", (24, -2, 124)),
        ("homer-simpson", "Homer", "masculine", WP + "en/0/02/Homer_Simpson_2006.png", (40, -5, 150)),
        ("fred-flintstone", "Fred", "masculine", WP + "en/a/ad/Fred_Flintstone.png", (53, -7, 127)),
        ("rick-sanchez", "Rick", "masculine", WP + "en/a/a6/Rick_Sanchez.png", (18, -11, 131)),
        ("bart-simpson", "Bart", "masculine", WP + "en/a/aa/Bart_Simpson_200px.png", (14, 19, 140)),
        ("peter-griffin", "Peter Griffin", "masculine", WP + "en/c/c2/Peter_Griffin.png", (62, -2, 148)),
        ("cartman", "Cartman", "masculine", WP + "en/7/77/EricCartman.png", (0, -28, 329)),
        ("bugs-bunny", "Bugs Bunny", "masculine",
         WP + "en/thumb/1/17/Bugs_Bunny.svg/960px-Bugs_Bunny.svg.png",
         (120, 0, 800)),
        ("aang", "Aang", "masculine", WP + "en/8/86/Avatar_Aang.png", (84, 24, 138)),
        ("finn", "Finn", "masculine",
         WP + "commons/thumb/a/a6/Finn_the_Human_character.svg/960px-Finn_the_Human_character.svg.png",
         (86, 3, 403)),
        ("spongebob", "SpongeBob", "neutral",
         WP + "commons/thumb/a/a2/SpongeBob_character.svg/960px-SpongeBob_character.svg.png",
         (96, -11, 768)),
        ("scooby-doo", "Scooby-Doo", "neutral", WP + "en/5/53/Scooby-Doo.png", (53, -11, 127)),
        ("garfield", "Garfield", "neutral",
         WP + "en/thumb/b/bc/Garfield_the_Cat.svg/960px-Garfield_the_Cat.svg.png",
         (0, -57, 480)),
        ("snoopy", "Snoopy", "neutral", WP + "en/5/53/Snoopy_Peanuts.png", (-6, -38, 294)),
        ("patrick-star", "Patrick", "neutral", WP + "commons/2/28/Patrick_Star_character.png", (47, 4, 284)),
        ("pink-panther", "Pink Panther", "neutral", WP + "en/9/96/Pink_Panther.png", (33, 4, 130)),
        ("gromit", "Gromit", "neutral", WP + "en/e/ec/Wallace_and_gromit.jpg", (192, 68, 164)),
        ("jerry-mouse", "Jerry", "neutral", WP + "en/2/2f/Jerry_Mouse.png", (20, -2, 162)),
        ("tweety", "Tweety", "neutral", WP + "en/thumb/0/02/Tweety.svg/960px-Tweety.svg.png", (-40, 60, 1040)),
        # v1.7: Dipper (asked for) plus fillers up to 36
        ("katara", "Katara", "feminine", WP + "commons/5/57/Katara_character.png", (250, 40, 480)),
        ("bluey", "Bluey", "feminine", WP + "en/f/fe/Bluey_the_puppy.png", (47, -15, 250)),
        ("kim-possible", "Kim Possible", "feminine",
         WP + "en/2/2b/Kim_Possible_%28character_design%29.png", (15, 0, 125)),
        ("dipper-pines", "Dipper", "masculine", WP + "en/1/15/Dipper_Pines.png", (5, 0, 210)),
        ("stewie-griffin", "Stewie", "masculine", WP + "en/0/02/Stewie_Griffin.png", (10, -15, 215)),
        ("morty-smith", "Morty", "masculine", WP + "en/c/c3/Morty_Smith.png", (-5, -15, 175)),
        ("jake-the-dog", "Jake", "neutral",
         WP + "commons/thumb/d/d8/Jake_the_Dog_character.svg/960px-Jake_the_Dog_character.svg.png",
         (50, -230, 1000)),
        ("tom-cat", "Tom (Tom & Jerry)", "neutral", WP + "en/f/f6/Tom_Tom_and_Jerry.png", (25, 15, 150)),
        ("perry", "Perry", "neutral", WP + "en/3/3d/Perry_Platypus.png", (0, 35, 105)),
    ],
    # Vox Machina (9, v1.10): The Legend of Vox Machina's seven heroes, Vex'ahlia's bear Trinket and Lady Kima;
    # character stills from Behind The Voice Actors. Listed order is the row order (vibe-exempt).
    "voxmachina": [
        ("vexahlia", "Vex'ahlia", "feminine", VOXMACHINA + "vexahlia-the-legend-of-vox-machina-37.jpg", (0, 10, 210)),
        ("trinket", "Trinket", "neutral", VOXMACHINA + "trinket-the-legend-of-vox-machina-15.7.jpg", (0, 10, 210)),
        ("vaxildan", "Vax'ildan", "masculine", VOXMACHINA + "vaxildan-the-legend-of-vox-machina-6.94.jpg", (0, 10, 210)),
        ("keyleth", "Keyleth", "feminine", VOXMACHINA + "keyleth-the-legend-of-vox-machina-6.2.jpg", (0, 10, 210)),
        ("percy", "Percy", "masculine", VOXMACHINA + "percival-de-rolo-iii-the-legend-of-vox-machina-2.33.jpg", (0, 10, 210)),
        ("pike", "Pike", "feminine", VOXMACHINA + "pike-trickfoot-the-legend-of-vox-machina-7.05.jpg", (0, 10, 210)),
        ("grog", "Grog", "masculine", VOXMACHINA + "grog-strongjaw-the-legend-of-vox-machina-2.75.jpg", (0, 10, 210)),
        ("scanlan", "Scanlan", "masculine", VOXMACHINA + "scanlan-shorthalt-the-legend-of-vox-machina-8.51.jpg", (0, 10, 210)),
        ("lady-kima", "Lady Kima", "feminine", VOXMACHINA + "lady-kima-of-vord-the-legend-of-vox-machina-1.5.jpg", (0, 10, 210)),
    ],
    # TV series (27): live-action TV characters and TV puppets (Muppets, Sesame Street)
    "tvshows": [
        ("jessica-fletcher", "Jessica Fletcher", "feminine",
         WP + "en/a/a6/Jessicaflecther.jpg",
         (40, 50, 110)),
        ("rachel-green", "Rachel", "feminine",
         WP + "en/e/ec/Jennifer_Aniston_as_Rachel_Green.jpg",
         (60, 0, 140)),
        ("leslie-knope", "Leslie Knope", "feminine",
         WP + "en/3/34/Leslie_Knope_%28played_by_Amy_Poehler%29.png",
         (62, 3, 152)),
        ("daenerys", "Daenerys", "feminine",
         WP + "en/0/0d/Daenerys_Targaryen_with_Dragon-Emilia_Clarke.jpg",
         (173, 17, 151)),
        ("buffy", "Buffy", "feminine", WP + "en/a/a2/S514_Buffy.png", (56, 15, 187)),
        ("scully", "Scully", "feminine", WP + "en/7/7c/Scully2016.png", (60, 18, 148)),
        ("janeway", "Janeway", "feminine",
         WP + "en/4/43/Kathryn_Janeway_season_7_publicity_photo.jpg",
         (71, 24, 142)),
        ("lorelai", "Lorelai", "feminine", WP + "en/c/c6/LorelaiGilmore.jpg", (73, 20, 147)),
        ("walter-white", "Walter White", "masculine", WP + "en/0/03/Walter_White_S5B.png", (34, 7, 205)),
        ("sheldon-cooper", "Sheldon", "masculine",
         WP + "en/f/f7/Sheldon_and_Young_Sheldon.jpg",
         (30, 14, 105)),
        ("joey-tribbiani", "Joey", "masculine",
         WP + "en/d/da/Matt_LeBlanc_as_Joey_Tribbiani.jpg",
         (14, 0, 243)),
        ("spock", "Spock", "masculine", WP + "commons/f/fa/Leonard_Nimoy_as_Spock_1967.jpg", (155, 138, 397)),
        ("picard", "Picard", "masculine",
         WP + "en/8/8e/Patrick_Steward_as_Jean-Luc_Picard_in_1996%27s_Star_Trek_First_Contact.jpg",
         (62, 0, 153)),
        ("ted-lasso", "Ted Lasso", "masculine", WP + "en/2/21/Jason_Sudeikis_as_Ted_Lasso.jpg", (53, 1, 133)),
        ("jon-snow", "Jon Snow", "masculine", WP + "en/3/30/Jon_Snow_Season_8.png", (55, 30, 150)),
        ("mandalorian", "The Mandalorian", "masculine", WP + "en/a/a1/TheMandalorian.jpg", (90, 15, 130)),
        ("grogu", "Grogu", "neutral", WP + "en/a/a0/Grogu_%28Star_Wars%29.jpg", (25, 0, 260)),
        ("tardis", "TARDIS", "neutral", WP + "commons/1/1a/Tardis_in_Snow.jpg", (30, 31, 543)),
        ("uss-enterprise", "USS Enterprise", "neutral", WP + "it/c/c6/USS_Enterprise_NCC-1701-D.jpg", (330, 0, 1080)),
        ("alf", "ALF", "neutral", WP + "en/8/89/GordonShumway.png", (34, 17, 178)),
        # v1.7: The Mentalist (asked for) plus fillers up to 36
        ("eleven", "Eleven", "feminine", WP + "en/3/3f/Eleven_%28Stranger_Things_5%29.png", (25, 10, 175)),
        ("arya-stark", "Arya", "feminine", WP + "en/3/39/Arya_Stark-Maisie_Williams.jpg", (60, 0, 170)),
        ("phoebe-buffay", "Phoebe", "feminine", WP + "en/f/f6/Friendsphoebe.jpg", (55, 25, 160)),
        ("patrick-jane", "Patrick Jane", "masculine", WP + "en/3/37/Patrick_Jane.jpg", (40, 15, 170)),
        ("sherlock", "Sherlock", "masculine", WP + "commons/0/0f/Benedict_Cumberbatch_filming_Sherlock_cropped2.jpg",
         (140, 0, 440)),
        ("michael-scott", "Michael Scott", "masculine", WP + "en/d/dc/MichaelScott.png", (65, 10, 135)),
        # v1.9: the Muppets moved to their own row; these keep the row at 36
        ("wednesday", "Wednesday", "feminine", WP + "en/d/d1/Wednesday_Addams_%282022%29.png", (20, 0, 252)),
        ("mr-bean", "Mr. Bean", "masculine", WP + "commons/e/e0/Atkinson_Rowan_crop.jpg", (90, 20, 770)),
        ("thing", "Thing", "neutral", WP + "en/d/d0/Thing_%28The_Addams_Family%29.gif", (100, 0, 224)),
        ("kitt", "KITT", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/fb/KITT_at_Universal_Studios%2C_original_uncropped_version.jpg/1920px-KITT_at_Universal_Studios%2C_original_uncropped_version.jpg",
         (377, 129, 1166)),
        ("young-hee", "Young-hee", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8a/Mu%C3%B1eca_Young-hee%2C_El_juego_de_Calamar_A74000620250204.jpg/1920px-Mu%C3%B1eca_Young-hee%2C_El_juego_de_Calamar_A74000620250204.jpg",
         (530, 120, 340)),
        ("barney", "Barney", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/f8/Barney_show_in_Qatar_%284340543390%29.jpg/1920px-Barney_show_in_Qatar_%284340543390%29.jpg",
         (600, 10, 560)),
        ("cylon", "Cylon", "neutral", WP + "en/3/3f/BSG_-_Cylon_Centurion_%282004_series%29.jpg", (0, 0, 280)),
        ("squid-game-guard", "Squid Game guard", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/21/Cosplay_of_Squid_Game_Guards_at_Sutera_Cosplay_Fest_2021.jpg/1280px-Cosplay_of_Squid_Game_Guards_at_Sutera_Cosplay_Fest_2021.jpg",
         (260, 170, 420)),
        ("flipper", "Flipper", "neutral", WP + "commons/4/4d/Flipper_The_Dolphin_1968.jpg", (159, 135, 410)),
        ("money-heist", "Money Heist", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/45/Money_Heist_Berlin_character.jpg/1280px-Money_Heist_Berlin_character.jpg",
         (350, 230, 360)),
    ],
    # Anime (27)
    "anime": [
        ("sailor-moon", "Sailor Moon", "feminine", WP + "en/2/2b/Sailor_Moon_01.jpg", (18, 5, 180)),
        ("nezuko", "Nezuko", "feminine", WP + "en/c/c0/NezukoKamado.png", (52, 28, 140)),
        ("chihiro", "Chihiro", "feminine", "https://www.ghibli.jp/gallery/chihiro021.jpg", (442, 127, 576)),
        ("anya", "Anya", "feminine", WP + "en/e/ec/AnyaForger.png", (46, 17, 139)),
        ("hello-kitty", "Hello Kitty", "feminine",
         WP + "en/0/05/Hello_kitty_character_portrait.png",
         (12, 0, 222)),
        ("kuromi", "Kuromi", "feminine", WP + "en/0/04/Kuromi_render.png", (22, -9, 252)),
        ("kiki", "Kiki", "feminine", "https://www.ghibli.jp/gallery/majo044.jpg", (288, 31, 768)),
        ("ponyo", "Ponyo", "feminine", "https://www.ghibli.jp/gallery/ponyo016.jpg", (576, 135, 768)),
        ("asuka", "Asuka", "feminine", WP + "en/2/2f/Asukka13.jpg", (126, 42, 120)),
        ("goku", "Goku", "masculine", WP + "en/4/4c/GokumangaToriyama.png", (37, 8, 116)),
        ("naruto", "Naruto", "masculine", WP + "en/9/9a/NarutoUzumaki.png", (96, -5, 104)),
        ("luffy", "Luffy", "masculine", WP + "en/c/cb/Monkey_D_Luffy.png", (28, -8, 143)),
        ("vegeta", "Vegeta", "masculine", WP + "en/8/88/Vegeta_Dragon_Ball.jpg", (75, 15, 135)),
        ("tanjiro", "Tanjiro", "masculine", WP + "en/e/ea/Tanjirou_manga.png", (50, 15, 155)),
        ("deku", "Deku", "masculine",
         WP + "en/d/db/Izuku_Midoriya_%28My_Hero_Academia_character%29.png",
         (35, -5, 115)),
        ("edward-elric", "Edward Elric", "masculine", WP + "en/b/b5/Edward85as.JPG", (61, 61, 122)),
        ("ichigo", "Ichigo", "masculine", WP + "en/1/1e/IchigoKurosakiBleach.jpg", (85, 0, 125)),
        ("astro-boy", "Astro Boy", "masculine", WP + "en/f/f2/Astro_Boy_anime_version.png", (51, -3, 170)),
        ("totoro", "Totoro", "neutral", "https://www.ghibli.jp/gallery/totoro030.jpg", (420, 0, 1038)),
        ("jiji", "Jiji", "neutral", "https://www.ghibli.jp/gallery/majo018.jpg", (547, 406, 288)),
        ("doraemon", "Doraemon", "neutral", WP + "en/b/bd/Doraemon_character.png", (14, -7, 257)),
        ("no-face", "No-Face", "neutral", "https://www.ghibli.jp/gallery/chihiro041.jpg", (720, 71, 480)),
        ("calcifer", "Calcifer", "neutral", "https://www.ghibli.jp/gallery/howl012.jpg", (576, 83, 768)),
        ("gundam", "Gundam", "neutral", WP + "en/d/d6/RX-78-2_Gundam_illustration.gif", (66, 9, 132)),
        ("chopper", "Chopper", "neutral", WP + "en/f/f6/Tony_Tony_Chopper.jpg", (73, 64, 178)),
        ("jibanyan", "Jibanyan", "neutral",
         WP + "en/2/28/Jibanyan_artwork_for_Yo-kai_Watch_3.png",
         (15, -10, 280)),
        ("luna", "Luna", "neutral", WP + "en/4/4d/Luna_Sailor_Moon.jpg", (50, 8, 120)),
        # v1.7: Pochita (asked for) plus fillers up to 36
        ("mei", "Mei", "feminine", "https://www.ghibli.jp/gallery/totoro021.jpg", (700, 120, 620)),
        ("san", "San", "feminine", "https://www.ghibli.jp/gallery/mononoke049.jpg", (740, 160, 620)),
        ("satsuki", "Satsuki", "feminine", "https://www.ghibli.jp/gallery/totoro008.jpg", (630, 0, 560)),
        ("saitama", "Saitama", "masculine", WP + "en/9/98/SaitamaWikipediapage.png", (65, 0, 140)),
        ("ashitaka", "Ashitaka", "masculine", "https://www.ghibli.jp/gallery/mononoke030.jpg", (660, 40, 620)),
        ("light-yagami", "Light Yagami", "masculine", WP + "en/0/0c/Light_from_Death_Note.jpg", (20, 5, 170)),
        # MyAnimeList character image (no Wikipedia/Commons image shows Pochita at a usable size)
        ("pochita", "Pochita", "neutral", "https://cdn.myanimelist.net/images/characters/7/391655.jpg", (0, 75, 225)),
        ("catbus", "Catbus", "neutral", "https://www.ghibli.jp/gallery/totoro044.jpg", (200, 230, 560)),
        ("happy", "Happy", "neutral", WP + "en/5/52/HappyFairyTail.png", (0, 40, 190)),
        # v1.10: Frieren (official character sheets, frieren-anime.jp) and Delicious in Dungeon (official
        # character art, delicious-in-dungeon.com), plus Studio Ghibli creatures as the neutral third
        ("frieren", "Frieren", "feminine", FRIEREN + "2023/08/chara1_face1.jpg", (0, 0, 248)),
        ("fern", "Fern", "feminine", FRIEREN + "2023/08/chara2_face1.jpg", (0, 0, 248)),
        ("ubel", "Übel", "feminine", FRIEREN + "2024/01/chara04_face2.jpg", (0, 0, 248)),
        ("flamme", "Flamme", "feminine", FRIEREN + "2023/09/chara7_face1.jpg", (0, 0, 248)),
        ("serie", "Serie", "feminine", FRIEREN + "2024/02/chara15_face1.jpg", (0, 0, 248)),
        ("marcille", "Marcille", "feminine", DUNGEON + "2c.png", (340, 100, 300)),
        ("falin", "Falin", "feminine", DUNGEON + "5c.png", (245, 40, 340)),
        ("izutsumi", "Izutsumi", "feminine", DUNGEON + "14c.png", (250, 0, 340)),
        ("namari", "Namari", "feminine", DUNGEON + "6c.png", (315, 125, 330)),
        ("stark", "Stark", "masculine", FRIEREN + "2023/08/chara3_face1.jpg", (0, 0, 248)),
        ("himmel", "Himmel", "masculine", FRIEREN + "2023/08/chara4_face1.jpg", (0, 0, 248)),
        ("heiter", "Heiter", "masculine", FRIEREN + "2023/08/chara5_face1.jpg", (0, 0, 248)),
        ("eisen", "Eisen", "masculine", FRIEREN + "2023/08/chara6_face2.jpg", (0, 0, 248)),
        ("sein", "Sein", "masculine", FRIEREN + "2023/11/chara17_face1.jpg", (0, 0, 248)),
        ("laios", "Laios", "masculine", DUNGEON + "1c.png", (200, -20, 360)),
        ("chilchuck", "Chilchuck", "masculine", DUNGEON + "3c.png", (340, 160, 320)),
        ("senshi", "Senshi", "masculine", DUNGEON + "4c.png", (240, 150, 400)),
        ("kabru", "Kabru", "masculine", DUNGEON + "8c.png", (230, 10, 340)),
        ("kuro", "Kuro", "neutral", DUNGEON + "11c.png", (269, 66, 360)),
        ("teto", "Teto", "neutral", "https://www.ghibli.jp/gallery/nausicaa045.jpg", (264, 150, 480)),
        ("ohmu", "Ohmu", "neutral", "https://www.ghibli.jp/gallery/nausicaa009.jpg", (600, 0, 950)),
        ("robot-soldier", "Robot soldier", "neutral", "https://www.ghibli.jp/gallery/laputa040.jpg", (740, 40, 480)),
        ("kodama", "Kodama", "neutral", "https://www.ghibli.jp/gallery/mononoke008.jpg", (1335, 110, 360)),
        ("forest-spirit", "Forest Spirit", "neutral", "https://www.ghibli.jp/gallery/mononoke041.jpg", (230, 150, 800)),
        ("yakul", "Yakul", "neutral", "https://www.ghibli.jp/gallery/mononoke048.jpg", (1400, 80, 520)),
        ("soot-sprites", "Soot sprites", "neutral", "https://www.ghibli.jp/gallery/chihiro014.jpg", (900, 100, 600)),
        ("moro", "Moro", "neutral", "https://www.ghibli.jp/gallery/mononoke029.jpg", (525, 120, 900)),
    ],
    # Pokemon (18): official artwork; vibe-exempt row (all neutral)
    "pokemon": [
        ("pikachu", "Pikachu", "neutral", WP + "en/a/a6/Pok%C3%A9mon_Pikachu_art.png", (0, 0, 316)),
        ("eevee", "Eevee", "neutral", WP + "en/a/a9/Pok%C3%A9mon_Eevee_art.png", (-12, -5, 280)),
        ("charizard", "Charizard", "neutral", WP + "en/1/1f/Pok%C3%A9mon_Charizard_art.png", (0, -35, 326)),
        ("bulbasaur", "Bulbasaur", "neutral", WP + "en/2/28/Pok%C3%A9mon_Bulbasaur_art.png", (0, -10, 275)),
        ("squirtle", "Squirtle", "neutral", WP + "en/5/59/Pok%C3%A9mon_Squirtle_art.png", (-5, -2, 207)),
        ("charmander", "Charmander", "neutral", WP + "en/5/56/Charmander.png", (-15, -3, 303)),
        ("jigglypuff", "Jigglypuff", "neutral", WP + "en/2/22/Pok%C3%A9mon_Jigglypuff_art.png", (0, 0, 316)),
        ("psyduck", "Psyduck", "neutral", WP + "en/2/2d/Pok%C3%A9mon_Psyduck_art.png", (0, -4, 180)),
        ("snorlax", "Snorlax", "neutral", WP + "en/3/3f/Pok%C3%A9mon_Snorlax_art.png", (0, -36, 354)),
        ("mewtwo", "Mewtwo", "neutral", WP + "en/4/43/Pok%C3%A9mon_Mewtwo_art.png", (0, -5, 285)),
        ("mew", "Mew", "neutral", WP + "en/4/4b/Pok%C3%A9mon_Mew_art.png", (28, -1, 225)),
        ("gengar", "Gengar", "neutral", WP + "en/b/bf/Pok%C3%A9mon_Gengar_art.png", (-4, 0, 320)),
        ("meowth", "Meowth", "neutral", WP + "en/9/99/Meowth.png", (33, -11, 237)),
        ("lucario", "Lucario", "neutral", WP + "en/9/95/Pok%C3%A9mon_Lucario_art.png", (26, -23, 203)),
        ("mimikyu", "Mimikyu", "neutral", WP + "en/2/23/Pok%C3%A9mon_Mimikyu_art.png", (-25, 1, 250)),
        ("gardevoir", "Gardevoir", "neutral", WP + "en/e/e5/Gardevoir_artwork.png", (51, -5, 248)),
        ("ditto", "Ditto", "neutral", WP + "en/d/d4/Pokemon-Ditto-Artwork.png", (-8, -35, 360)),
        ("cubone", "Cubone", "neutral", WP + "en/6/65/Cubone.png", (40, -5, 238)),
    ],
    # Video games (27): Nintendo (non-Mario), Sega, PlayStation, Xbox, PC, Square Enix, Capcom, indie, mobile
    "games": [
        ("zelda", "Zelda", "feminine", WP + "en/6/6e/Link_to_the_Past_Zelda.png", (41, -23, 130)),
        ("lara-croft", "Lara", "feminine", WP + "en/a/a8/LaraCroftInfobox.png", (85, -7, 96)),
        ("samus", "Samus", "feminine", WP + "en/d/d6/Samus_Aran.png", (70, -11, 96)),
        ("isabelle", "Isabelle", "feminine", WP + "en/2/26/Isabelle_AF.png", (-10, 0, 200)),
        ("jinx", "Jinx", "feminine", WP + "en/a/ad/Jinx-artwork-lol.png", (55, 15, 115)),
        ("tifa", "Tifa", "feminine", WP + "en/6/61/Tifa_Lockhart_art.png", (53, -3, 98)),
        ("madeline", "Madeline", "feminine",
         WP + "commons/4/42/Celeste_character_Madeline.png",
         (330, 60, 680)),
        ("tracer", "Tracer", "feminine", WP + "en/3/30/Tracer_Overwatch_2_portrait.png", (50, 5, 85)),
        ("chun-li", "Chun-Li", "feminine", WP + "en/5/53/Chun-Li.png", (36, -4, 76)),
        ("sonic", "Sonic", "masculine", WP + "en/f/f4/Sonic_modern_and_classic_designs.png", (-9, 0, 164)),
        ("master-chief", "Master Chief", "masculine",
         WP + "en/4/42/Master_chief_halo_infinite.png",
         (61, 1, 98)),
        ("link", "Link", "masculine", WP + "en/2/21/Link_of_the_Wild.png", (70, 25, 105)),
        ("crash-bandicoot", "Crash", "masculine", WP + "en/a/a3/IAT_Crash_Bandicoot.png", (68, -8, 163)),
        ("steve", "Steve", "masculine", WP + "en/e/e7/Steve_%28Minecraft%29.png", (86, -11, 142)),
        ("ratchet", "Ratchet", "masculine", WP + "en/c/c0/Ratchet_%26_Clank_%282021%29.png", (66, -13, 162)),
        ("rayman", "Rayman", "masculine",
         WP + "en/1/19/Rayman_Legends_Title_Character_Art.png",
         (92, 8, 172)),
        ("cuphead", "Cuphead", "masculine", WP + "en/e/eb/Cuphead_%28artwork%29.png", (15, 135, 144)),
        ("cloud-strife", "Cloud Strife", "masculine", WP + "en/9/9e/Cloud_Strife.png", (63, -12, 115)),
        ("pac-man", "Pac-Man", "neutral",
         WP + "commons/f/fb/Pac-Man_ingame_and_2D_alternative_design.png",
         (362, -19, 384)),
        ("kirby", "Kirby", "neutral", WP + "en/4/4e/Kirby_Nintendo.png", (0, -20, 336)),
        ("creeper", "Creeper", "neutral", WP + "commons/a/a9/Minecraft_Creeper_%28Crop%29.png", (7, 32, 167)),
        ("crewmate", "Crewmate", "neutral", WP + "en/9/9a/Among_Us_cover_art.jpg", (39, 116, 155)),
        ("angry-bird", "Angry Bird", "neutral", WP + "en/2/2d/Angry_Birds_promo_art.png", (47, 47, 253)),
        ("blinky", "Blinky", "neutral",
         WP + "commons/thumb/b/be/Blinky%2C_Pinky%2C_Inky_and_Clyde.svg/1280px-Blinky%2C_Pinky%2C_Inky_and_Clyde.svg.png",
         (-13, -2, 290)),
        ("slime", "Slime", "neutral", WP + "en/9/9d/Slime_%28Dragon_Quest%29.png", (0, -8, 324)),
        ("hollow-knight", "Knight", "neutral",
         WP + "en/d/de/Hollow_Knight_2026_cover_art.jpg",
         (79, 41, 158)),
        ("sackboy", "Sackboy", "neutral", WP + "en/1/19/SackboySony.png", (37, -9, 221)),
        # v1.10: Kerbal Space Program (KSP wiki), Outer Wilds (Mobius press kit, Steam screenshot), We Were
        # Here Together, The Last of Us and Horizon Zero Dawn (Steam library art)
        ("valentina-kerman", "Valentina Kerman", "feminine", KSP + "7/76/Valentina_Kerman_portrait.01.png", (5, 10, 310)),
        ("ellie", "Ellie", "feminine", STEAM + "1888930/library_600x900_2x.jpg", (210, 90, 320)),
        ("aloy", "Aloy", "feminine", STEAM + "1151640/library_hero.jpg", (1288, 0, 300)),
        ("jebediah-kerman", "Jebediah Kerman", "masculine", KSP + "5/5d/Jeb_global_selfie.jpg", (325, 0, 560)),
        ("bill-kerman", "Bill Kerman", "masculine", KSP + "d/dd/BillArtwork.jpg", (680, 110, 560)),
        ("bob-kerman", "Bob Kerman", "masculine", KSP + "0/04/Bob.jpg", (925, 180, 420)),
        ("riebeck", "Riebeck", "neutral", OUTER_WILDS_PRESS + "#Outer Wilds/OW_Riebeck.png", (600, 125, 300)),
        ("anglerfish", "Anglerfish", "neutral",
         STEAM + "753640/ss_c624a6b8edca0d451605592edd927dbcc14917a8.1920x1080.jpg", (560, 150, 900)),
        ("we-were-here-explorer", "Explorer (We Were Here)", "neutral", STEAM + "865360/library_hero.jpg",
         (345, 0, 420)),
    ],
    # Super Mario (18): Nintendo's Super Mario world (moved out of Video games)
    "mario": [
        ("princess-peach", "Peach", "feminine", WP + "en/1/16/Princess_Peach_Stock_Art.png", (40, 0, 140)),
        ("princess-daisy", "Daisy", "feminine",
         WP + "en/e/eb/Princess_Daisy_by_Shigehisa_Nakaue.png",
         (37, -4, 140)),
        ("toadette", "Toadette", "feminine",
         WP + "en/6/6a/Toadette_Artwork_by_Shigehisa_Nakaue.png",
         (20, -13, 202)),
        ("rosalina", "Rosalina", "feminine", WP + "en/5/5e/Rosalina_by_Shigehisa_Nakaue.png", (16, -14, 156)),
        ("pauline", "Pauline", "feminine", WP + "en/2/28/Pauline_Super_Mario_Odyssey.png", (44, -6, 118)),
        ("birdo", "Birdo", "feminine", WP + "en/f/f9/Birdo-MP9.png", (0, -33, 212)),
        ("mario", "Mario", "masculine", WP + "en/5/5c/Mario_by_Shigehisa_Nakaue.png", (34, -17, 179)),
        ("luigi", "Luigi", "masculine", WP + "en/b/be/Luigi_by_Shigehisa_Nakaue.png", (26, 0, 160)),
        ("bowser", "Bowser", "masculine", WP + "en/d/d1/Bowser_by_Shigehisa_Nakaue.png", (54, -41, 250)),
        ("donkey-kong", "Donkey Kong", "masculine", WP + "en/d/d4/Donkey_Kong_character.png", (48, -16, 221)),
        ("wario", "Wario", "masculine", WP + "en/8/81/Wario.png", (23, -18, 230)),
        ("waluigi", "Waluigi", "masculine", WP + "en/c/c1/Waluigi_by_Shigehisa_Nakaue.png", (73, -19, 175)),
        ("yoshi", "Yoshi", "neutral", WP + "en/d/db/Yoshi_%28Nintendo_character%29.png", (6, -28, 214)),
        ("toad", "Toad", "neutral", WP + "en/b/b9/Toad_by_Shigehisa_Nakaue.png", (14, -12, 244)),
        ("goomba", "Goomba", "neutral", WP + "en/f/fb/Goomba_by_Shigehisa_Nakaue.png", (-8, -24, 332)),
        ("koopa-troopa", "Koopa Troopa", "neutral",
         WP + "en/5/5f/Koopa_Troopa_by_Shigehisa_Nakaue.png",
         (-10, -6, 157)),
        ("piranha-plant", "Piranha Plant", "neutral",
         WP + "en/7/75/Piranha_Plant_by_Shigehisa_Nakaue.png",
         (12, 0, 232)),
        ("luma", "Luma", "neutral", WP + "en/5/5e/Rosalina_by_Shigehisa_Nakaue.png", (171, 17, 94)),
    ],
    # Dinosaurs (18): true dinosaurs only (no pterosaurs), one consistent paleoart series: TotalDino's
    # side-view life reconstructions on Commons (CC BY 4.0 / CC BY-SA 4.0 / CC0, see LICENSES.md),
    # transparent, cropped to head and neck. Patagotitan (2017) is the largest dinosaur known from good
    # remains; Nagatitan (May 2026) is the newest giant. Listed order is the row order (all "neutral").
    "dinosaurs": [
        ("t-rex", "T. rex", "neutral", WP + "commons/c/c2/Tyrannosaurus_TD.png", (2253, -87, 681)),
        ("triceratops", "Triceratops", "neutral", WP + "commons/4/45/Triceratops_TD.png", (1800, -130, 1100)),
        ("velociraptor", "Velociraptor", "neutral", WP + "commons/c/cc/Velociraptor_TD.png", (2285, -74, 634)),
        ("stegosaurus", "Stegosaurus", "neutral", WP + "commons/0/09/Stegosaurus_TD.png", (2150, 330, 560)),
        ("spinosaurus", "Spinosaurus", "neutral", WP + "commons/5/56/Spinosaurus_TD.png", (2100, -3, 820)),
        ("brachiosaurus", "Brachiosaurus", "neutral", WP + "commons/4/4d/Brachiosaurus_TD.png", (1912, -93, 371)),
        ("ankylosaurus", "Ankylosaurus", "neutral", WP + "commons/5/5a/Ankylosaurus_TD.png", (2090, 90, 504)),
        ("parasaurolophus", "Parasaurolophus", "neutral", WP + "commons/e/e6/Parasaurolophus_TD.png", (2091, -22, 678)),
        ("patagotitan", "Patagotitan", "neutral", WP + "commons/1/1c/Patagotitan_TD.png", (2329, -39, 345)),
        ("nagatitan", "Nagatitan", "neutral", WP + "commons/9/9b/Nagatitan_TD.png", (2238, -83, 365)),
        ("allosaurus", "Allosaurus", "neutral", WP + "commons/5/50/Allosaurus_TD.png", (2116, -53, 607)),
        ("therizinosaurus", "Therizinosaurus", "neutral", WP + "commons/5/53/Therizinosaurus_TD.png", (1600, -20, 600)),
        ("giganotosaurus", "Giganotosaurus", "neutral", WP + "commons/c/c1/Giganotosaurus_TD.png", (2172, -70, 630)),
        ("carnotaurus", "Carnotaurus", "neutral", WP + "commons/4/48/Carnotaurus_TD.png", (2195, -135, 723)),
        ("pachycephalosaurus", "Pachycephalosaurus", "neutral", WP + "commons/a/a5/Pachycephalosaurus_TD.png", (1831, -21, 596)),
        ("dilophosaurus", "Dilophosaurus", "neutral", WP + "commons/c/cd/Dilophosaurus_TD.png", (1994, -62, 581)),
        ("styracosaurus", "Styracosaurus", "neutral", WP + "commons/a/a7/Styracosaurus_TD.png", (1550, 90, 1000)),
        ("iguanodon", "Iguanodon", "neutral", WP + "commons/7/7b/Iguanodon_TD.png", (2108, -110, 635)),
    ],
    # LEGO (18): official LEGO minifigures, BrickLink catalogue photos (white studio background,
    # cut out so the figure sits on the tile colour; the cut-out also drops the small inset
    # face shots). LEGO versions of characters found in other rows are named "LEGO <name>".
    "lego": [
        ("wyldstyle", "Wyldstyle", "feminine", BRICKLINK + "tlm083.png", (12, -6, 215), CUT),
        ("lego-hermione", "LEGO Hermione", "feminine", BRICKLINK + "colhp02.png", (32, 6, 196), CUT),
        ("lego-leia", "LEGO Leia", "feminine", BRICKLINK + "sw0779.png", (22, -2, 202), CUT),
        ("lego-wonder-woman", "LEGO Wonder Woman", "feminine", BRICKLINK + "colsh02.png", (18, -5, 205), CUT),
        ("lego-batgirl", "LEGO Batgirl", "feminine", BRICKLINK + "sh0305.png", (53, 7, 194), CUT),
        ("lego-harley-quinn", "LEGO Harley Quinn", "feminine", BRICKLINK + "coltlbm13.png", (21, -1, 201), CUT),
        ("emmet", "Emmet", "masculine", BRICKLINK + "tlm066.png", (50, -6, 203), CUT),
        ("lego-batman", "LEGO Batman", "masculine", BRICKLINK + "sh0312.png", (57, -4, 196), CUT),
        ("lego-legolas", "LEGO Legolas", "masculine", BRICKLINK + "lor015.png", (19, 2, 199), CUT),
        ("lego-gandalf", "LEGO Gandalf", "masculine", BRICKLINK + "lor001.png", (38, -3, 184), CUT),
        ("lego-harry-potter", "LEGO Harry Potter", "masculine", BRICKLINK + "colhp01.png", (32, 2, 199), CUT),
        ("lego-spider-man", "LEGO Spider-Man", "masculine", BRICKLINK + "sh0536.png", (39, -1, 201), CUT),
        ("benny", "Benny", "neutral", BRICKLINK + "tlm057.png", (37, -2, 162), CUT),
        ("unikitty", "Unikitty", "neutral", BRICKLINK + "tlm126.png", (-48, -5, 290), CUT),
        ("lego-darth-vader", "LEGO Darth Vader", "neutral", BRICKLINK + "sw0636.png", (42, 8, 150), CUT),
        ("lego-yoda", "LEGO Yoda", "neutral", BRICKLINK + "sw0707.png", (20, -4, 200), CUT),
        ("lego-stormtrooper", "LEGO Stormtrooper", "neutral", BRICKLINK + "sw0585.png", (41, 0, 159), CUT),
        ("lego-skeleton", "LEGO Skeleton", "neutral", BRICKLINK + "gen004.png", (28, -6, 206), CUT),
    ],
    # Harry Potter (18): the films' major cast, film stills from the characters' English or Italian
    # Wikipedia articles; Dobby (studio prop) and Hedwig (studio owl) from Commons photos. Hermione
    # moved here from Movies. Listed order is the row order (vibe-exempt: the cast is mostly male).
    "harrypotter": [
        ("harry-potter", "Harry Potter", "masculine", WP + "it/5/5b/Harry_Potter_PMS.jpg", (160, 0, 403)),
        ("hermione", "Hermione", "feminine", WP + "en/d/d3/Hermione_Granger_poster.jpg", (55, 1, 136)),
        ("ron-weasley", "Ron", "masculine", WP + "en/5/5e/Ron_Weasley_poster.jpg", (7, 0, 266)),
        ("dumbledore", "Dumbledore", "masculine", WP + "en/e/e8/Dumbledore_-_Prisoner_of_Azkaban.jpg", (0, 16, 232)),
        ("hagrid", "Hagrid", "masculine", WP + "it/c/cd/Rubeus_Hagrid.jpg", (470, 0, 549)),
        ("snape", "Snape", "masculine", WP + "en/b/b9/Ootp076.jpg", (34, 0, 170)),
        ("mcgonagall", "McGonagall", "feminine", WP + "en/e/ea/McGonagall_%28screenshot%29.jpg", (38, 8, 197)),
        ("voldemort", "Voldemort", "masculine", WP + "en/2/2a/Voldemort_book_and_film.jpg", (268, 0, 199)),
        ("dobby", "Dobby", "neutral", WP + "commons/9/9b/Dobby_2.jpg", (80, 0, 800)),
        ("luna-lovegood", "Luna Lovegood", "feminine", WP + "en/c/c2/LunaLovegood.jpeg", (54, 0, 258)),
        ("sirius-black", "Sirius", "masculine", WP + "en/6/6b/Sirius_Black.jpeg", (0, 22, 184)),
        ("draco-malfoy", "Draco", "masculine", WP + "en/1/16/Draco_Mal.JPG", (25, 0, 170)),
        ("hedwig", "Hedwig", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ae/The_Making_of_Harry_Potter_29-05-2012_%28Hedwig%29.jpg/1280px-The_Making_of_Harry_Potter_29-05-2012_%28Hedwig%29.jpg",
         (243, 346, 844)),
        ("ginny-weasley", "Ginny", "feminine", WP + "en/e/e7/Ginny_Weasley_poster.jpg", (68, 0, 190)),
        ("bellatrix", "Bellatrix", "feminine", WP + "en/d/d8/Bellatrix.jpeg", (40, 10, 138)),
        ("neville", "Neville", "masculine", WP + "en/7/75/Neville_Longbottom.jpeg", (0, 0, 273)),
        ("lupin", "Lupin", "masculine", WP + "en/2/2f/Remus_Lupin.jpeg", (34, 12, 133)),
        ("umbridge", "Umbridge", "feminine", WP + "en/b/b9/Umbridge.jpeg", (133, 1, 156)),
    ],
    # Marvel & DC (18): live-action heroes and villains, film stills (Wikipedia) and Madame Tussauds /
    # exhibition photos (Commons) for the masked ones; Spider-Man, Iron Man, Black Widow and Groot moved
    # here from Movies. Listed order is the row order (vibe-exempt).
    "heroes": [
        ("spider-man", "Spider-Man (Tom Holland)", "masculine",
         WP + "en/0/0f/Tom_Holland_as_Spider-Man.jpg",
         (62, 10, 115)),
        # v1.10: all three live-action Spider-Men (owner's request), film frames from the Italian articles
        ("spider-man-tobey", "Spider-Man (Tobey Maguire)", "masculine",
         WP + "it/5/5b/Spider-Man_%28Tobey_Maguire%29.jpeg", (240, 40, 1150)),
        ("spider-man-andrew", "Spider-Man (Andrew Garfield)", "masculine",
         WP + "it/2/25/Peter_Parker_%28Garfield%29.jpeg", (1100, 0, 800)),
        ("wonder-woman", "Wonder Woman", "feminine", WP + "en/e/e1/Gal_Gadot_as_Wonder_Woman.jpg", (84, 0, 90)),
        ("iron-man", "Iron Man", "masculine",
         WP + "en/0/02/Iron_Man_%282008_film%29_poster.jpg",
         (0, 3, 156)),
        ("black-widow", "Black Widow", "feminine",
         WP + "en/f/f6/Scarlett_Johansson_as_Black_Widow.jpg",
         (65, 5, 135)),
        ("batman", "Batman", "masculine", WP + "it/4/41/BatmanilritornoMichaelKeaton4k.png", (360, 96, 700)),
        ("groot", "Groot", "neutral", WP + "en/3/3b/Groot.png", (26, 0, 203)),
        ("captain-america", "Captain America", "masculine", WP + "it/f/f0/Captain_America_Civil_War.png",
         (985, 0, 340)),
        ("harley-quinn", "Harley Quinn", "feminine", WP + "it/f/f3/Harley_Quinn_%28DCEU%29.png", (840, 20, 640)),
        ("superman", "Superman", "masculine", WP + "en/d/d6/Superman_Man_of_Steel.jpg", (79, 0, 131)),
        ("thor", "Thor", "masculine", WP + "en/3/3c/Chris_Hemsworth_as_Thor.jpg", (90, 2, 124)),
        ("scarlet-witch", "Scarlet Witch", "feminine",
         WP + "en/d/d9/Elizabeth_Olsen_as_Wanda_Maximoff.jpg",
         (58, 8, 142)),
        ("black-panther", "Black Panther", "masculine",
         WP + "en/1/1a/Chadwick_Boseman_as_T%27Challa.jpg",
         (50, 0, 103)),
        ("hulk", "Hulk", "neutral", WP + "it/4/45/Hulk_%28film%29.jpg", (300, 20, 440)),
        ("captain-marvel", "Captain Marvel", "feminine",
         WP + "en/f/f1/Brie_Larson_as_Carol_Danvers.jpeg",
         (30, 5, 124)),
        ("deadpool", "Deadpool", "masculine", WP + "en/f/fb/Ryan_Reynolds_as_Deadpool_2016.jpg", (75, 15, 90)),
        ("joker", "Joker", "masculine",
         WP + "en/2/2b/Heath_Ledger_as_the_Joker_in_The_Dark_Knight.png",
         (47, 13, 151)),
        ("catwoman", "Catwoman", "feminine",
         WP + "en/d/d7/Michelle_Pfeiffer_as_Catwoman_in_Batman_Returns.jpg",
         (240, 0, 150)),
        ("wolverine", "Wolverine", "masculine", WP + "it/8/8d/Wolverine_-_Le_origini.jpg", (375, 0, 533)),
        # v1.10: fillers up to 27 (film frames from the Italian articles)
        ("gamora", "Gamora", "feminine", WP + "it/d/d4/GamoraGuardianiDellaGalassiaVol2.jpeg", (330, 20, 450)),
        ("the-flash", "The Flash", "masculine", WP + "it/b/b4/Barry_Allen_%28DCEU%29.png", (740, 120, 520)),
        ("nick-fury", "Nick Fury", "masculine", WP + "it/1/13/Nick_Fury_%28MCU%29.png", (1360, 80, 900)),
        ("wasp", "Wasp", "feminine", WP + "it/2/27/Ant-Man%26WaspMovie.png", (760, 60, 560)),
        ("ant-man", "Ant-Man", "masculine", WP + "it/e/e4/Ant-Man_film.jpg", (360, 10, 320)),
        ("shazam", "Shazam", "masculine", WP + "it/5/50/Shazam%21.jpg", (390, 0, 360)),
        ("hawkeye", "Hawkeye", "masculine", WP + "it/e/eb/Occhio_di_Falco.png", (620, 0, 330)),
    ],
    # Muppets & Sesame Street (18): the ten Muppets moved here from TV series plus eight more puppets.
    # Listed order is the row order (vibe-exempt).
    "muppets": [
        ("kermit", "Kermit", "masculine",
         WP + "commons/thumb/7/74/Kermit_puppet.jpg/1280px-Kermit_puppet.jpg",
         (384, 85, 512)),
        ("miss-piggy", "Miss Piggy", "feminine", WP + "it/9/9f/Miss_Piggy.jpeg", (430, 0, 560)),
        ("elmo", "Elmo", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a2/Season_3_introduces_one_of_Sesame_Street%27s_original_character_Elmo_%284313578924%29.jpg/1920px-Season_3_introduces_one_of_Sesame_Street%27s_original_character_Elmo_%284313578924%29.jpg",
         (682, 288, 576)),
        ("fozzie", "Fozzie", "neutral", WP + "commons/0/09/Fozzie_Bear_puppet_in_1979.jpg", (150, 50, 300)),
        ("cookie-monster", "Cookie Monster", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/95/Cookie_Monster_and_Gingerbread_Man_vending_machine_%2818807184852%29.jpg/1920px-Cookie_Monster_and_Gingerbread_Man_vending_machine_%2818807184852%29.jpg",
         (760, 240, 440)),
        ("animal-muppet", "Animal", "neutral", WP + "en/e/e7/Animal_%28Muppet%29.jpg", (17, 0, 173)),
        ("big-bird", "Big Bird", "neutral",
         WP + "commons/5/5a/LBJ_Foundation_DIG14086-057_%2835105588940%29.jpg",
         (70, 0, 1257)),
        ("gonzo", "Gonzo", "neutral", WP + "commons/4/41/Gonzo.png", (0, 0, 239)),
        ("oscar-grouch", "Oscar the Grouch", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/d4/LBJ_Foundation_DIG14086-069_%2834650875314%29.jpg/1280px-LBJ_Foundation_DIG14086-069_%2834650875314%29.jpg",
         (330, 60, 620)),
        ("swedish-chef", "Swedish Chef", "neutral", WP + "commons/c/c1/Swedish_Chef_%28cropped%29.png", (0, 0, 396)),
        ("bert", "Bert", "neutral", WP + "commons/a/aa/Bert_and_Ernie_from_Sesame_Street.jpg", (10, 20, 380)),
        ("rosita", "Rosita", "feminine", WP + "commons/b/b0/Rosita_%282009%29.jpg", (26, 0, 380)),
        ("count-von-count", "The Count", "neutral",
         WP + "en/2/29/Count_von_Count_kneeling.png",
         (66, -3, 162)),
        ("beaker", "Beaker", "neutral", WP + "commons/6/67/Beaker_Muppets.png", (20, 0, 280)),
        ("grover", "Grover", "neutral", WP + "en/b/be/Grover.JPG", (20, 0, 223)),
        ("rowlf", "Rowlf", "neutral", WP + "commons/9/91/Rowlf_the_Dog.png", (55, 0, 360)),
        ("statler", "Statler", "neutral", WP + "commons/b/b2/Statler_and_waldorf_muppet.png", (30, 0, 330)),
        ("waldorf", "Waldorf", "neutral", WP + "commons/b/b2/Statler_and_waldorf_muppet.png", (347, 0, 347)),
    ],
    # Animals (18): real photos from Commons, head-centred; listed order is the row order (all "neutral").
    "animals": [
        ("red-fox", "Red fox", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8e/Alaska_Red_Fox_%28Vulpes_vulpes%29.jpg/1920px-Alaska_Red_Fox_%28Vulpes_vulpes%29.jpg",
         (558, 166, 1110)),
        ("red-panda", "Red panda", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/71/Red_Panda_Portrait_%2831625024560%29.jpg/1920px-Red_Panda_Portrait_%2831625024560%29.jpg",
         (419, 31, 1081)),
        ("snowy-owl", "Snowy owl", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/09/Female_Snowy_Owl_Portrait_-_24937699785.jpg/1920px-Female_Snowy_Owl_Portrait_-_24937699785.jpg",
         (320, 0, 1280)),
        ("sea-otter", "Sea otter", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/be/Sea_Otter_%28Enhydra_lutris%29_%2825169790524%29.jpg/1280px-Sea_Otter_%28Enhydra_lutris%29_%2825169790524%29.jpg",
         (318, 21, 644)),
        ("axolotl", "Axolotl", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/f3/Leucistic_Axolotl_front_2010-02-24.JPG/1920px-Leucistic_Axolotl_front_2010-02-24.JPG",
         (640, 0, 1280)),
        ("kitten", "Kitten", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/ef/A_kitten_in_the_hand_%28Flickr%29.jpg/1920px-A_kitten_in_the_hand_%28Flickr%29.jpg",
         (537, 57, 960)),
        ("puppy", "Puppy", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/33/Callie_the_golden_retriever_puppy.jpg/1920px-Callie_the_golden_retriever_puppy.jpg",
         (348, 36, 1224)),
        ("giant-panda", "Giant panda", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/74/Panda_g%C3%A9ant_-_t%C3%AAte_%28Ailuropoda_melanoleuca%29_%282%29.jpg/1920px-Panda_g%C3%A9ant_-_t%C3%AAte_%28Ailuropoda_melanoleuca%29_%282%29.jpg",
         (0, 32, 1216)),
        ("seal-pup", "Seal pup", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5b/Weaned_harp_seal_pup_%28cropped%29.jpg/1920px-Weaned_harp_seal_pup_%28cropped%29.jpg",
         (933, 230, 987)),
        ("sloth", "Sloth", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/18/Bradypus.jpg/1280px-Bradypus.jpg",
         (448, 235, 793)),
        ("hedgehog", "Hedgehog", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/cb/Erinaceus_europaeus_%28Linnaeus%2C_1758%29.jpg/1920px-Erinaceus_europaeus_%28Linnaeus%2C_1758%29.jpg",
         (443, 185, 1263)),
        ("lion-cub", "Lion cub", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/44/Lion_cub_with_mother_-_cropped.jpg/1920px-Lion_cub_with_mother_-_cropped.jpg",
         (38, 114, 960)),
        ("fennec", "Fennec", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/be/Sleeping_Vulpes_zerda_at_Happy_Hollow%2C_closeup.jpg/1920px-Sleeping_Vulpes_zerda_at_Happy_Hollow%2C_closeup.jpg",
         (262, 0, 1280)),
        ("elephant", "Elephant", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/46/African_elephant_side_view_portrait.jpg/1920px-African_elephant_side_view_portrait.jpg",
         (0, 0, 1217)),
        ("highland-cow", "Highland cow", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/97/2011-05-30_008_Young_Highland_cow%2C_Denmark.jpg/1920px-2011-05-30_008_Young_Highland_cow%2C_Denmark.jpg",
         (619, 13, 797)),
        ("alpaca", "Alpaca", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/81/Alpaca_Portrait_%2826631626457%29.jpg/1920px-Alpaca_Portrait_%2826631626457%29.jpg",
         (166, 0, 1280)),
        ("meerkat", "Meerkat", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/f0/Meerkat_portrait_looking_sunset.jpg/1920px-Meerkat_portrait_looking_sunset.jpg",
         (320, 0, 1280)),
        ("snow-leopard", "Snow leopard", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/19/Snow_leopard_portrait.jpg/1920px-Snow_leopard_portrait.jpg",
         (55, 0, 1809)),
        # v1.10: nine more cute and iconic animals (Commons, the articles' lead photos)
        ("arctic-fox", "Arctic fox", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/dc/Vulpes_lagopus_in_Iceland_%28cropped_3%29.jpg/1920px-Vulpes_lagopus_in_Iceland_%28cropped_3%29.jpg",
         (450, 200, 1000)),
        ("quokka", "Quokka", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3b/Setonix_brachyurus_on_Rottnest_Island_1.jpg/1920px-Setonix_brachyurus_on_Rottnest_Island_1.jpg",
         (250, 850, 1000)),
        ("koala", "Cuddly koala", "neutral",
         WP + "commons/4/49/Koala_climbing_tree.jpg",
         (240, 0, 640)),
        ("penguin-chick", "Penguin chick", "neutral",
         WP + "commons/a/a3/Aptenodytes_forsteri_-Snow_Hill_Island%2C_Antarctica_-adults_and_juvenile-8.jpg",
         (180, 580, 520)),
        ("hamster", "Hamster", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/6b/Golden_hamster_front_1.jpg/1920px-Golden_hamster_front_1.jpg",
         (100, 250, 1100)),
        ("red-squirrel", "Red squirrel", "neutral",
         WP + "commons/1/1c/Squirrel_posing.jpg",
         (500, 50, 1000)),
        ("raccoon", "Raccoon", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3e/Raccoon_in_Central_Park_%2835264%29.jpg/1920px-Raccoon_in_Central_Park_%2835264%29.jpg",
         (710, 100, 800)),
        ("bunny", "Bunny", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/1f/Oryctolagus_cuniculus_Rcdo.jpg/1920px-Oryctolagus_cuniculus_Rcdo.jpg",
         (650, 400, 1000)),
        ("clownfish", "Clownfish", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ad/Amphiprion_ocellaris_%28Clown_anemonefish%29_by_Nick_Hobgood.jpg/1920px-Amphiprion_ocellaris_%28Clown_anemonefish%29_by_Nick_Hobgood.jpg",
         (250, 150, 1000)),
    ],
    # Space (18): NASA / ESA / EHT images from Commons; listed order is the row order (all "neutral").
    "space": [
        ("earth", "Earth", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/97/The_Earth_seen_from_Apollo_17.jpg/1920px-The_Earth_seen_from_Apollo_17.jpg",
         (0, 0, 1920)),
        ("moon", "Moon", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e1/FullMoon2010.jpg/1920px-FullMoon2010.jpg",
         (47, 0, 1825)),
        ("sun", "Sun", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/b4/The_Sun_by_the_Atmospheric_Imaging_Assembly_of_NASA%27s_Solar_Dynamics_Observatory_-_20100819.jpg/1920px-The_Sun_by_the_Atmospheric_Imaging_Assembly_of_NASA%27s_Solar_Dynamics_Observatory_-_20100819.jpg",
         (43, 0, 1833)),
        ("mars", "Mars", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/02/OSIRIS_Mars_true_color.jpg/1920px-OSIRIS_Mars_true_color.jpg",
         (0, 0, 1920)),
        ("jupiter", "Jupiter", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2b/Jupiter_and_its_shrunken_Great_Red_Spot.jpg/960px-Jupiter_and_its_shrunken_Great_Red_Spot.jpg",
         (0, 0, 960)),
        ("saturn", "Saturn", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/ca/Top_view_of_the_rings_of_Saturn_by_Cassini_-_October_10%2C_2013.jpg/1920px-Top_view_of_the_rings_of_Saturn_by_Cassini_-_October_10%2C_2013.jpg",
         (240, 0, 1440)),
        ("neptune", "Neptune", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/63/Neptune_-_Voyager_2_%2829347980845%29_flatten_crop.jpg/960px-Neptune_-_Voyager_2_%2829347980845%29_flatten_crop.jpg",
         (0, 0, 960)),
        ("black-hole", "Black hole", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/4f/Black_hole_-_Messier_87_crop_max_res.jpg/1920px-Black_hole_-_Messier_87_crop_max_res.jpg",
         (269, 269, 1382)),
        ("pillars-of-creation", "Pillars of Creation", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/f1/Pillars_of_Creation_%28NIRCam_Image%29.jpg/1920px-Pillars_of_Creation_%28NIRCam_Image%29.jpg",
         (0, 703, 1920)),
        ("cosmic-cliffs", "Cosmic Cliffs", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/44/NASA%E2%80%99s_Webb_Reveals_Cosmic_Cliffs%2C_Glittering_Landscape_of_Star_Birth.jpg/1920px-NASA%E2%80%99s_Webb_Reveals_Cosmic_Cliffs%2C_Glittering_Landscape_of_Star_Birth.jpg",
         (212, 0, 1112)),
        ("crab-nebula", "Crab Nebula", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/00/Crab_Nebula.jpg/1920px-Crab_Nebula.jpg",
         (0, 0, 1920)),
        ("whirlpool-galaxy", "Whirlpool Galaxy", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/db/Messier51_sRGB.jpg/1920px-Messier51_sRGB.jpg",
         (193, 33, 1265)),
        ("comet", "Comet Hale-Bopp", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/ba/Comet_Hale-Bopp_1995O1.jpg/1280px-Comet_Hale-Bopp_1995O1.jpg",
         (0, 0, 1280)),
        ("iss", "ISS", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/04/International_Space_Station_after_undocking_of_STS-132.jpg/1920px-International_Space_Station_after_undocking_of_STS-132.jpg",
         (348, 0, 1224)),
        ("hubble", "Hubble", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3f/HST-SM4.jpeg/1920px-HST-SM4.jpeg",
         (239, 0, 1441)),
        ("rocket-launch", "Saturn V launch", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/16/Apollo_11_Launch_-_GPN-2000-000630.jpg/1920px-Apollo_11_Launch_-_GPN-2000-000630.jpg",
         (0, 0, 1920)),
        ("spacewalk", "Spacewalk", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/91/Bruce_McCandless_II_during_EVA_in_1984.jpg/1920px-Bruce_McCandless_II_during_EVA_in_1984.jpg",
         (403, 211, 1190)),
        ("moonwalk", "Moonwalk", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/98/Aldrin_Apollo_11_original.jpg/1920px-Aldrin_Apollo_11_original.jpg",
         (269, 23, 1382)),
        # v1.10: Apollo 8 and 11, and the crewed Artemis II lunar flyby (1-10 April 2026; Reid Wiseman, Victor
        # Glover, Christina Koch, Jeremy Hansen): crew, launch, Orion, and the views from Orion
        ("earthrise", "Earthrise", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a8/NASA-Apollo8-Dec24-Earthrise.jpg/1920px-NASA-Apollo8-Dec24-Earthrise.jpg",
         (680, 760, 820)),
        ("apollo-11-crew", "Apollo 11 crew", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3d/Apollo_11_Crew.jpg/1920px-Apollo_11_Crew.jpg",
         (220, 0, 1480)),
        ("artemis-ii-crew", "Artemis II crew", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/1b/Artemis_2_Crew_Portrait_%28cropped%29.jpg/1920px-Artemis_2_Crew_Portrait_%28cropped%29.jpg",
         (0, 60, 1920)),
        ("artemis-ii-launch", "Artemis II launch", "neutral",
         WP + "commons/6/66/Artemis_II_Launch_%28cropped%29.jpg",
         (0, 360, 1548)),
        ("orion", "Orion", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/25/Orion_Snaps_a_Selfie_During_External_Inspection.jpg/1920px-Orion_Snaps_a_Selfie_During_External_Inspection.jpg",
         (690, 100, 1150)),
        ("earth-from-orion", "Earth from Orion", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e3/Earth_From_the_Perspective_of_Artemis_II_%28cropped%29.jpg/1920px-Earth_From_the_Perspective_of_Artemis_II_%28cropped%29.jpg",
         (0, 0, 1905)),
        ("earthset", "Earthset", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/15/Earthset_%28art002e009288%29.jpg/1920px-Earthset_%28art002e009288%29.jpg",
         (390, 280, 1000)),
        ("far-side-of-the-moon", "Far side of the Moon", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/9d/A_New_View_of_the_Moon.jpg/1920px-A_New_View_of_the_Moon.jpg",
         (370, 100, 1180)),
        ("eclipse-from-orion", "Eclipse from Orion", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3f/Solar_eclipse_taken_from_Artemis_II_-_April_2026.jpg/1920px-Solar_eclipse_taken_from_Artemis_II_-_April_2026.jpg",
         (227, 94, 1100)),
    ],
    # Mythology (18): public-domain paintings, prints, codices, tomb paintings and classical sculpture
    # (Commons), cropped to the god or creature.
    "mythology": [
        ("athena", "Athena", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/63/Klimt_-_Pallas_Athene.jpeg/1920px-Klimt_-_Pallas_Athene.jpeg",
         (406, 133, 570)),
        ("zeus", "Zeus", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/86/Jupiter_Smyrna_Louvre_Ma13%2C_Ausschnitt.jpg/1280px-Jupiter_Smyrna_Louvre_Ma13%2C_Ausschnitt.jpg",
         (582, 348, 576)),
        ("japanese-dragon", "Japanese dragon", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/fc/Hokusai_Dragon.jpg/1280px-Hokusai_Dragon.jpg",
         (665, 262, 320)),
        ("medusa", "Medusa", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/36/Caravaggio_-_Medusa_Uffizi_-_High_quality.jpg/1920px-Caravaggio_-_Medusa_Uffizi_-_High_quality.jpg",
         (365, 462, 1190)),
        ("poseidon", "Poseidon", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/dc/Parian_Marble_Statue_of_Poseidon%2C_from_Melos%2C_Cyclades%2C_125-100_BC_%2827884076403%29.jpg/1920px-Parian_Marble_Statue_of_Poseidon%2C_from_Melos%2C_Cyclades%2C_125-100_BC_%2827884076403%29.jpg",
         (712, 310, 380)),
        ("phoenix", "Phoenix", "neutral",
         WP + "commons/6/61/Phoenix_detail_from_Aberdeen_Bestiary.jpg",
         (133, 227, 618)),
        ("isis", "Isis", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/39/Queen_Nefertari_being_led_by_Isis_MET_DP167142.jpg/1920px-Queen_Nefertari_being_led_by_Isis_MET_DP167142.jpg",
         (980, 420, 720)),
        ("thor-norse", "Thor (Norse)", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/c5/M%C3%A5rten_Eskil_Winge_-_Tor%27s_Fight_with_the_Giants_-_Google_Art_Project.jpg/1920px-M%C3%A5rten_Eskil_Winge_-_Tor%27s_Fight_with_the_Giants_-_Google_Art_Project.jpg",
         (528, 40, 864)),
        ("sphinx", "Sphinx", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a2/Great_Sphinx_of_Giza_and_Pyramid_of_Cheops.jpg/1920px-Great_Sphinx_of_Giza_and_Pyramid_of_Cheops.jpg",
         (1101, 115, 793)),
        ("freyja", "Freyja", "feminine",
         WP + "commons/e/ec/Freyja_and_the_Necklace_by_James_Doyle_Penrose%2C_1890.jpg",
         (148, 16, 212)),
        ("odin", "Odin", "masculine",
         WP + "commons/1/1d/Georg_von_Rosen_-_Oden_som_vandringsman%2C_1886_%28Odin%2C_the_Wanderer%29.jpg",
         (72, 69, 375)),
        ("quetzalcoatl", "Quetzalcoatl", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/1a/Quetzalcoatl_telleriano2.jpg/960px-Quetzalcoatl_telleriano2.jpg",
         (290, 280, 345)),
        ("valkyrie", "Valkyrie", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/68/Peter_Nicolai_Arbo_-_The_Valkyrie_-_NG.M.00259_-_National_Museum_of_Art%2C_Architecture_and_Design.jpg/1920px-Peter_Nicolai_Arbo_-_The_Valkyrie_-_NG.M.00259_-_National_Museum_of_Art%2C_Architecture_and_Design.jpg",
         (739, 310, 480)),
        ("anubis", "Anubis", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5f/Roman_statue_of_Anubis%2C_Gregorian_Egyptian_Museum%2C_Vatican_Museums.jpg/1920px-Roman_statue_of_Anubis%2C_Gregorian_Egyptian_Museum%2C_Vatican_Museums.jpg",
         (506, 100, 600)),
        ("cyclops", "Cyclops", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/be/Odilon_Redon_-_The_Cyclops%2C_c._1914.jpg/1920px-Odilon_Redon_-_The_Cyclops%2C_c._1914.jpg",
         (384, 148, 1152)),
        ("artemis", "Artemis", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/32/Detail_Diana_Versailles_Louvre_Ma589.jpg/1920px-Detail_Diana_Versailles_Louvre_Ma589.jpg",
         (606, 0, 1092)),
        ("ra", "Ra", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e7/Maler_der_Grabkammer_der_Nefertari_001.jpg/1920px-Maler_der_Grabkammer_der_Nefertari_001.jpg",
         (609, 335, 650)),
        ("pegasus", "Pegasus", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/f4/Jacob_Jordaens_-_Pegasus.jpg/1920px-Jacob_Jordaens_-_Pegasus.jpg",
         (700, 0, 700)),
    ],
    # Historic figures (18): period portraits and photographs (Commons, public domain); women and men
    # alternate (vibe-exempt: nobody is "neutral").
    "historic": [
        ("marie-curie", "Marie Curie", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/c8/Marie_Curie_c._1920s.jpg/1280px-Marie_Curie_c._1920s.jpg",
         (0, 99, 1280)),
        ("einstein", "Einstein", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3e/Einstein_1921_by_F_Schmutzer_-_restoration.jpg/1920px-Einstein_1921_by_F_Schmutzer_-_restoration.jpg",
         (547, 225, 1009)),
        ("cleopatra", "Cleopatra", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/bb/Bust_of_Cleopatra_VII_-_Altes_Museum_-_Berlin_-_Germany_2017.jpg/1920px-Bust_of_Cleopatra_VII_-_Altes_Museum_-_Berlin_-_Germany_2017.jpg",
         (0, 456, 1920)),
        ("leonardo", "Leonardo da Vinci", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/38/Leonardo_da_Vinci_-_presumed_self-portrait_-_WGA12798.jpg/1920px-Leonardo_da_Vinci_-_presumed_self-portrait_-_WGA12798.jpg",
         (310, 300, 1300)),
        ("ada-lovelace", "Ada Lovelace", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a4/Ada_Lovelace_portrait.jpg/1920px-Ada_Lovelace_portrait.jpg",
         (573, 326, 825)),
        ("newton", "Isaac Newton", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3b/Portrait_of_Sir_Isaac_Newton%2C_1689.jpg/1920px-Portrait_of_Sir_Isaac_Newton%2C_1689.jpg",
         (576, 45, 1071)),
        ("frida-kahlo", "Frida Kahlo", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/06/Frida_Kahlo%2C_by_Guillermo_Kahlo.jpg/960px-Frida_Kahlo%2C_by_Guillermo_Kahlo.jpg",
         (0, 26, 960)),
        ("darwin", "Charles Darwin", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a0/Charles_Darwin_photograph_by_Julia_Margaret_Cameron%2C_1868.jpg/1920px-Charles_Darwin_photograph_by_Julia_Margaret_Cameron%2C_1868.jpg",
         (138, 175, 1610)),
        ("elizabeth-i", "Elizabeth I", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/fe/Elizabeth_I_Armada_Portrait_British_School.jpg/1920px-Elizabeth_I_Armada_Portrait_British_School.jpg",
         (755, 173, 473)),
        ("napoleon", "Napoleon", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/50/Jacques-Louis_David_-_The_Emperor_Napoleon_in_His_Study_at_the_Tuileries_-_Google_Art_Project.jpg/1920px-Jacques-Louis_David_-_The_Emperor_Napoleon_in_His_Study_at_the_Tuileries_-_Google_Art_Project.jpg",
         (637, 270, 568)),
        ("florence-nightingale", "Florence Nightingale", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/58/Florence_Nightingale_by_Henry_Hering%2C_1858.jpg/1280px-Florence_Nightingale_by_Henry_Hering%2C_1858.jpg",
         (451, 70, 381)),
        ("mozart", "Mozart", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/fc/Barbara_Krafft_-_Portr%C3%A4t_Wolfgang_Amadeus_Mozart_%281819%29.jpg/1280px-Barbara_Krafft_-_Portr%C3%A4t_Wolfgang_Amadeus_Mozart_%281819%29.jpg",
         (114, 68, 1166)),
        ("amelia-earhart", "Amelia Earhart", "feminine", WP + "commons/d/d2/Amelia_Earhart_1935.jpg", (0, 63, 560)),
        ("tesla", "Nikola Tesla", "masculine", WP + "commons/7/79/Tesla_circa_1890.jpeg", (0, 16, 940)),
        ("harriet-tubman", "Harriet Tubman", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/96/Harriet_Tubman_by_Squyer%2C_NPG%2C_c1885.jpg/1920px-Harriet_Tubman_by_Squyer%2C_NPG%2C_c1885.jpg",
         (631, 181, 473)),
        ("gandhi", "Gandhi", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7a/Mahatma-Gandhi%2C_studio%2C_1931.jpg/1920px-Mahatma-Gandhi%2C_studio%2C_1931.jpg",
         (451, 0, 1216)),
        ("marie-antoinette", "Marie Antoinette", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5f/Louise_Elisabeth_Vig%C3%A9e-Lebrun_-_Marie-Antoinette_dit_%C2%AB_%C3%A0_la_Rose_%C2%BB_-_Google_Art_Project.jpg/1920px-Louise_Elisabeth_Vig%C3%A9e-Lebrun_-_Marie-Antoinette_dit_%C2%AB_%C3%A0_la_Rose_%C2%BB_-_Google_Art_Project.jpg",
         (558, 323, 772)),
        ("lincoln", "Abraham Lincoln", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/44/Abraham_Lincoln_head_on_shoulders_photo_portrait.jpg/1920px-Abraham_Lincoln_head_on_shoulders_photo_portrait.jpg",
         (0, 0, 1920)),
    ],
    # Retro games (9): arcade sprites and period art; Pac-Man, Blinky, Donkey Kong, Link and Sonic are in
    # Video games / Super Mario already. Listed order is the row order (all "neutral").
    "retro": [
        ("space-invader", "Space Invader", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/b9/Pixel_invader_Pinhead_icon.svg/500px-Pixel_invader_Pinhead_icon.svg.png",
         (-70, -70, 640)),
        ("ms-pac-man", "Ms. Pac-Man", "neutral",
         WP + "commons/e/eb/Ms._Pac-Man_ingame_and_2D_alternative_design.png",
         (53, 54, 280), {"pixel": True}),
        ("tetris", "Tetris", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/41/Tetromino_T.svg/960px-Tetromino_T.svg.png",
         (-60, -188, 1080)),
        ("pong", "Pong", "neutral", WP + "commons/6/6c/Pong_game.png", (0, 0, 218), {"pixel": True}),
        ("mega-man", "Mega Man", "neutral", WP + "en/7/7e/Mega_Man_11_Artwork.png", (40, -10, 210)),
        ("pinky", "Pinky", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/be/Blinky%2C_Pinky%2C_Inky_and_Clyde.svg/1280px-Blinky%2C_Pinky%2C_Inky_and_Clyde.svg.png",
         (950, -40, 370)),
        ("frogger", "Frogger", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/9f/Sega_-_Gremlin_-_Frogger_-_December_1st_1981_Play_Meter_advert.jpg/1920px-Sega_-_Gremlin_-_Frogger_-_December_1st_1981_Play_Meter_advert.jpg",
         (240, 85, 1248)),
        ("clyde", "Clyde", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/be/Blinky%2C_Pinky%2C_Inky_and_Clyde.svg/1280px-Blinky%2C_Pinky%2C_Inky_and_Clyde.svg.png",
         (290, -40, 370)),
        ("inky", "Inky", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/be/Blinky%2C_Pinky%2C_Inky_and_Clyde.svg/1280px-Blinky%2C_Pinky%2C_Inky_and_Clyde.svg.png",
         (620, -40, 370)),
    ],
    # Pirates & knights (9): period engravings and paintings (Commons, public domain) plus Felice Beato's
    # 1860s samurai photograph.
    "pirates": [
        ("anne-bonny", "Anne Bonny", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5d/Ann_Bonny%2C_Cole_1724.jpg/1280px-Ann_Bonny%2C_Cole_1724.jpg",
         (319, 100, 400)),
        ("blackbeard", "Blackbeard", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7c/Teach_alias_Blackbeard%2C_colored.jpg/1280px-Teach_alias_Blackbeard%2C_colored.jpg",
         (250, 160, 400)),
        ("samurai", "Samurai", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/09/Samurai.png/1280px-Samurai.png",
         (516, 120, 420)),
        ("mary-read", "Mary Read", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/9f/Mary_Read%2C_Cole_1724.jpg/960px-Mary_Read%2C_Cole_1724.jpg",
         (362, 50, 300)),
        ("long-john-silver", "Long John Silver", "masculine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/73/TI-parrot.jpg/1920px-TI-parrot.jpg",
         (1050, 250, 700)),
        ("knight", "Knight in armour", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/41/Aleksander_Lesser_-_Knight_in_armour_-_MP_2240_MNW_-_National_Museum_in_Warsaw.jpg/1920px-Aleksander_Lesser_-_Knight_in_armour_-_MP_2240_MNW_-_National_Museum_in_Warsaw.jpg",
         (634, 197, 650)),
        ("joan-of-arc", "Joan of Arc", "feminine",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2b/Ingres_coronation_charles_vii.jpg/1920px-Ingres_coronation_charles_vii.jpg",
         (603, 190, 560)),
        ("captain-kidd", "Captain Kidd", "masculine",
         WP + "commons/e/ee/Captain_Kidd_%28Pyle_painting%29.gif",
         (212, 125, 330)),
        ("pirate-ship", "Pirate ship", "neutral",
         "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/84/Painting_of_a_pirate_ship_%28after_1852%29%2C_after_Ambroise_Louis_Garneray.jpg/960px-Painting_of_a_pirate_ship_%28after_1852%29%2C_after_Ambroise_Louis_Garneray.jpg",
         (112, 0, 640)),
    ],
    # Memes: animals and drawn/rendered characters only (no real people's faces).
    "memes": [
        ("doge", "Doge", "feminine",
         WP + "commons/c/cb/Kabosu_and_Atsuko_Sato_2023-11-02_%281%29.jpg",
         (684, 662, 684)),
        ("cheems", "Cheems", "masculine", WP + "en/1/14/Balltze_%28Cheems%29.jpg", (57, 38, 190)),
        ("nyan-cat", "Nyan Cat", "neutral", WP + "en/e/ed/Nyan_cat_250px_frame.PNG", (75, 38, 175)),
        ("grumpy-cat", "Grumpy Cat", "feminine",
         WP + "commons/d/dc/Grumpy_Cat_%2814556024763%29_%28cropped%29.jpg",
         (168, 30, 559)),
        ("meme-man", "Stonks", "masculine",
         WP + "en/9/96/Meme_Man_on_transparent_background.webp",
         (32, 0, 284)),
        ("bongo-cat", "Bongo Cat", "neutral", WP + "en/7/7a/Bongo_cat.png", (25, 50, 140)),
        ("lil-bub", "Lil Bub", "feminine", WP + "commons/b/b8/Lil-Bub-2013_%28cropped%29.jpg", (34, 1, 390)),
        ("smudge", "Smudge", "masculine", WP + "en/1/1f/WomanYellingAtACat_meme.jpg", (295, 47, 107)),
        ("pesto", "Pesto", "neutral",
         WP + "commons/4/4a/Pesto_%28penguin%29_%28cropped%29.png",
         (700, 0, 1200)),
        ("moo-deng", "Moo Deng", "neutral",
         WP + "commons/5/5b/Moo_deng_%E0%B8%AB%E0%B8%A1%E0%B8%B9%E0%B9%80%E0%B8%94%E0%B9%89%E0%B8%87_%282024-09-10%29_-_img_01.jpg",
         (260, 90, 990)),
        ("maru", "Maru", "neutral", WP + "en/f/fb/IamMaruBookCover.jpg", (118, 8, 188)),
        ("dat-boi", "Dat Boi", "neutral", WP + "en/f/f9/Dat_Boi_%28resized_50%25%29.jpg", (0, 0, 201)),
        ("capybara", "Capybara", "neutral",
         WP + "commons/thumb/7/71/Capybaracropped.jpg/1280px-Capybaracropped.jpg",
         (224, 139, 576)),
        ("duo", "Duo", "neutral",
         WP + "en/thumb/6/64/Duo_from_Duolingo.svg/960px-Duo_from_Duolingo.svg.png",
         (0, -48, 960)),
        ("big-floppa", "Big Floppa", "neutral",
         WP + "commons/thumb/b/bf/Big_Floppa_and_Justin_2_%28cropped%29.jpg/1280px-Big_Floppa_and_Justin_2_%28cropped%29.jpg",
         (256, 75, 896)),
        ("serious-cat", "Serious Cat", "neutral",
         WP + "commons/thumb/4/44/CatLolCatExample.jpg/1280px-CatLolCatExample.jpg",
         (440, 410, 400)),
        ("keyboard-cat", "Keyboard Cat", "neutral", WP + "en/8/87/Keyboard_cat.jpg", (20, 0, 160)),
        ("jorts", "Jorts", "neutral", WP + "en/0/06/Jorts_the_Cat.jpg", (130, 15, 120)),
    ],
}

# Colours row: generated locally (no downloads). (id, name, kind, colours)
# kind: "solid" (one colour), "linear" (two/three-stop diagonal gradient),
# "stripes" (horizontal bands), "diagonal" (diagonal bands).
RAINBOW = ["#E5484D", "#F5A524", "#F5D90A", "#46A758", "#3E63DD", "#8E4EC6"]
COLOURS = [
    ("colour-red", "Red", "solid", ["#E5484D"]),
    ("colour-orange", "Orange", "solid", ["#F5A524"]),
    ("colour-yellow", "Yellow", "solid", ["#F5D90A"]),
    ("colour-green", "Green", "solid", ["#46A758"]),
    ("colour-teal", "Teal", "solid", ["#12A594"]),
    ("colour-blue", "Blue", "solid", ["#3E63DD"]),
    ("colour-violet", "Violet", "solid", ["#8E4EC6"]),
    ("colour-pink", "Pink", "solid", ["#E93D82"]),
    ("colour-brown", "Brown", "solid", ["#AD7F58"]),
    ("colour-grey", "Grey", "solid", ["#8B8D98"]),
    ("colour-charcoal", "Charcoal", "solid", ["#2B2B30"]),
    ("colour-cloud", "Cloud", "solid", ["#E9E6DF"]),
    ("colour-sunset", "Sunset", "linear", ["#F9B44C", "#E5484D", "#5B2A86"]),
    ("colour-ocean", "Ocean", "linear", ["#5AC8E0", "#1F5FA8", "#0C2D5B"]),
    ("colour-forest", "Forest", "linear", ["#9CCF6B", "#2E7D32", "#1B4D1E"]),
    ("colour-dusk", "Dusk", "linear", ["#F2A7C5", "#8E4EC6", "#2E2A6B"]),
    ("colour-rainbow", "Rainbow", "stripes", RAINBOW),
    ("colour-prism", "Prism", "diagonal", RAINBOW),
]

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
    # v1.4: animals (the vibe only spreads them over the row)
    ("noto-cat", "Cat", "feminine", "1f431", "#FFE0CC"),
    ("noto-dog", "Dog", "masculine", "1f436", "#E8DCC8"),
    ("noto-frog", "Frog", "neutral", "1f438", "#D9EBD9"),
    ("noto-unicorn", "Unicorn", "feminine", "1f984", "#EBD9F5"),
    ("noto-lion", "Lion", "masculine", "1f981", "#FFE6B8"),
    ("noto-whale", "Whale", "neutral", "1f433", "#D8ECE4"),
    ("noto-koala", "Koala", "feminine", "1f428", "#DDE8F0"),
    ("noto-dragon", "Dragon", "masculine", "1f432", "#D4ECD0"),
    ("noto-penguin", "Penguin", "neutral", "1f427", "#D6E4F2"),
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
               "classics", "movies", "tvcartoons", "anime", "games", "memes",
               "disney", "animated", "tvshows", "pokemon", "mario", "lotr", "lego", "dinosaurs"]
# Entries added to existing rows later take their colours after all rows, so the
# colours (and transparent tiles) of everything already built stay the same.
LATER = ["katara", "bluey", "kim-possible", "dipper-pines", "stewie-griffin", "morty-smith", "jake-the-dog",
         "tom-cat", "perry", "eleven", "arya-stark", "phoebe-buffay", "patrick-jane", "tenth-doctor",
         "michael-scott", "fozzie", "beaker", "rowlf", "mei", "san", "satsuki", "saitama", "ashitaka",
         "light-yagami", "pochita", "catbus", "happy"]
# v1.9 rows take their colours after all of the above; LATER_V19 are the avatars added to
# existing rows in v1.9.
COLOR_ORDER_V19 = ["harrypotter", "heroes", "muppets", "animals", "space", "mythology", "historic", "retro",
                   "pirates"]
LATER_V19 = ["ripley", "amelie", "james-bond", "terminator", "chewbacca", "wednesday", "mr-bean", "thing",
             "kitt", "weeping-angel", "k9", "cylon", "tribble", "flipper", "cyberman"]
# v1.9.1: added to the Lord of the Rings row, colours after all of the above.
LATER_V191 = ["sauron-armour", "faramir", "mouth-of-sauron", "treebeard", "denethor", "shelob", "witch-king", "celeborn",
              "balrog"]
# v1.10: avatars added to existing rows and the new Vox Machina row, colours after all of the above.
LATER_V110 = ["spider-man-tobey", "spider-man-andrew", "gamora", "the-flash", "nick-fury", "wasp", "ant-man", "shazam",
              "hawkeye", "vexahlia", "trinket", "vaxildan", "keyleth", "percy", "pike", "grog", "scanlan", "lady-kima",
              "frieren", "fern", "ubel", "flamme", "serie", "marcille", "falin", "izutsumi", "namari", "stark", "himmel",
              "heiter", "eisen", "sein", "laios", "chilchuck", "senshi", "kabru", "kuro", "teto", "ohmu",
              "robot-soldier", "kodama", "forest-spirit", "yakul", "soot-sprites", "moro", "valentina-kerman", "ellie",
              "aloy", "jebediah-kerman", "bill-kerman", "bob-kerman", "riebeck", "anglerfish", "we-were-here-explorer",
              "arctic-fox", "quokka", "koala", "penguin-chick", "hamster", "red-squirrel", "raccoon", "bunny",
              "clownfish", "earthrise", "apollo-11-crew", "artemis-ii-crew", "artemis-ii-launch", "orion",
              "earth-from-orion", "earthset", "far-side-of-the-moon", "eclipse-from-orion"]
# v1.10: removed on the owner's request; each replacement takes the removed avatar's place and colour
# (replacement -> removed id).
REPLACES = {"sherlock": "tenth-doctor", "uss-enterprise": "dalek", "young-hee": "weeping-angel", "barney": "k9",
            "squid-game-guard": "tribble", "money-heist": "cyberman"}
# Avatars moved to a v1.9 row keep the colour slot of the row they came from: (old row, index there).
MOVED = {"hermione": ("movies", 0), "black-widow": ("movies", 7), "spider-man": ("movies", 11),
         "iron-man": ("movies", 17), "groot": ("movies", 24), "miss-piggy": ("tvshows", 6),
         "kermit": ("tvshows", 9), "elmo": ("tvshows", 18), "animal-muppet": ("tvshows", 20),
         "big-bird": ("tvshows", 21), "oscar-grouch": ("tvshows", 22), "count-von-count": ("tvshows", 23)}
# Rows whose f/m/n order is not enforced (kept in the order listed above): memes and
# colours (no people), Pokémon (creatures; every entry is "neutral"), Lord of the Rings
# (the major cast is mostly male), Dinosaurs (animals; every entry is "neutral"); v1.9: Harry
# Potter, Marvel & DC and Muppets (casts mostly male), Animals, Space and Retro games (all
# "neutral"), Historic figures (real people, women and men alternate); v1.10: Vox Machina (the cast).
FREE_VIBE = {"memes", "colours", "pokemon", "lotr", "dinosaurs", "harrypotter", "heroes", "muppets", "animals",
             "space", "historic", "retro", "voxmachina"}


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
    """Order a row f, m, n, f, m, n, ... so every row looks mixed (rows may be
    any multiple of 9; the original nine keep their places)."""
    if items and items[0]["group"] in FREE_VIBE:
        return items
    by = {v: [i for i in items if i["vibe"] == v] for v in VIBES}
    if len({len(l) for l in by.values()}) != 1:
        raise SystemExit(f"{items[0]['group']}: unbalanced vibes {[len(by[v]) for v in VIBES]}")
    return [by[v][k] for k in range(len(by["feminine"])) for v in VIBES]


def colour_tile(kind, cols):
    """Render one entry of the colours row (512x512, no downloads)."""
    rgb = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in cols]
    if kind == "solid":
        return Image.new("RGB", (SIZE, SIZE), rgb[0])
    if kind == "linear":  # diagonal gradient, top-left -> bottom-right
        n = len(rgb) - 1
        img = Image.new("RGB", (SIZE, SIZE))
        px = img.load()
        for y in range(SIZE):
            for x in range(SIZE):
                t = (x + y) / (2 * (SIZE - 1)) * n
                i = min(int(t), n - 1); f = t - i
                px[x, y] = tuple(round(rgb[i][k] * (1 - f) + rgb[i + 1][k] * f) for k in range(3))
        return img
    img = Image.new("RGB", (SIZE, SIZE)); px = img.load()
    for y in range(SIZE):
        for x in range(SIZE):
            t = y / SIZE if kind == "stripes" else (x + y) / (2 * SIZE)
            px[x, y] = rgb[min(int(t * len(rgb)), len(rgb) - 1)]
    return img

def clamp(box, size):
    """Move a crop box inside the image, shrinking it if it is larger than the image."""
    x, y, s = box; w, h = size
    s = min(s, w, h)
    return (min(max(x, 0), w - s), min(max(y, 0), h - s), s)

def cutout(src, white=248):
    """Studio photo on white -> transparent background (flood fill from the border), keeping
    only the largest figure, which drops the small inset face shots of catalogue photos."""
    rgb = src.convert("RGB"); w, h = rgb.size; px = rgb.load()
    bg = bytearray(w * h)
    todo = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    while todo:
        x, y = todo.pop()
        if 0 <= x < w and 0 <= y < h and not bg[y * w + x] and min(px[x, y]) >= white:
            bg[y * w + x] = 1
            todo += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    seen, best = bytearray(bg), []
    for start in range(w * h):
        if seen[start]:
            continue
        seen[start] = 1; comp = [start]; i = 0
        while i < len(comp):
            p = comp[i]; i += 1; x, y = p % w, p // w
            for q, ok in ((p + 1, x + 1 < w), (p - 1, x > 0), (p + w, y + 1 < h), (p - w, y > 0)):
                if ok and not seen[q]:
                    seen[q] = 1; comp.append(q)
        if len(comp) > len(best):
            best = comp
    mask = bytearray(w * h)
    for p in best:
        mask[p] = 255
    alpha = Image.frombytes("L", (w, h), bytes(mask)).filter(ImageFilter.MinFilter(3)) \
                 .filter(ImageFilter.GaussianBlur(0.6))
    out = rgb.convert("RGBA"); out.putalpha(alpha)
    return out

def source(url):
    """Bytes of a local-pack source; "<archive>.zip#<member>" is one file of a downloaded archive."""
    archive, _, member = url.partition("#")
    if member and archive.endswith(".zip"):
        return zipfile.ZipFile(io.BytesIO(get(archive))).read(member)
    return get(url)

def local_image(aid, url, color, box, opts=None):
    """Fetch a local-pack image and crop it. Returns (tile, square): a source with
    transparency is laid on `color` like an emoji on its square and its box may run
    past the edges (square=True); an opaque source's box is clamped inside the
    image so the tile colour can never show as a band. opts {"cutout": n} first
    turns a white studio background (channels >= n) transparent, {"exif": True} turns a
    camera photo upright, {"pixel": True} keeps pixel-art sprites sharp."""
    src = Image.open(io.BytesIO(source(url)))
    if opts and opts.get("exif"):
        src = ImageOps.exif_transpose(src)
    src = src.convert("RGBA")
    if opts and "cutout" in opts:
        src = cutout(src, opts["cutout"])
    x, y, s = box
    alpha = src.getchannel("A")
    square = alpha.getextrema()[0] < 250
    if not square and clamp(box, src.size) != box:
        x, y, s = clamp(box, src.size)
        print(f"warning: {aid}: box {box} clamped to {(x, y, s)} in {src.size}")
    canvas = Image.new("RGBA", (s, s), color)
    canvas.alpha_composite(src.crop((x, y, x + s, y + s)))
    tile = canvas.convert("RGB")
    if opts and opts.get("pixel"):
        k = -(-2 * SIZE // s)
        tile = tile.resize((s * k, s * k), Image.NEAREST)
    return tile.resize((SIZE, SIZE), Image.LANCZOS), square

def tint(img, color):
    """Multiply line art on white paper with a soft colour."""
    return ImageChops.multiply(img, Image.new("RGB", img.size, color))

def main():
    only = None
    missing_only = "--missing" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--missing"]
    if len(args) > 1 and args[0] == "--only":
        only = set(args[1].split(","))
        unknown = only - {g for g, _ in GROUPS}
        if unknown:
            raise SystemExit(f"unknown groups: {sorted(unknown)}")
    out = ROOT / "app" / "img"; out.mkdir(parents=True, exist_ok=True)
    out_local = ROOT / "app" / "img-local"; out_local.mkdir(parents=True, exist_ok=True)
    rows = {}
    colors = iter(pastel(i) for i in range(1000))
    color_of = {}

    def colour_ids(gid):
        ids = [REPLACES.get(i[0], i[0]) for i in COMMONS.get(gid, []) + DICE.get(gid, []) + LOCAL.get(gid, [])
               if i[0] not in MOVED]
        for aid, (old, k) in sorted(MOVED.items(), key=lambda m: m[1][1]):
            if old == gid:
                ids.insert(k, aid)
        return ids
    later_all = LATER + LATER_V19 + LATER_V191 + LATER_V110
    for order, later in ((COLOR_ORDER, LATER), (COLOR_ORDER_V19, LATER_V19), ([], LATER_V191), ([], LATER_V110)):
        for gid in order:
            for aid in colour_ids(gid):
                if aid not in later_all and aid not in color_of:
                    color_of[aid] = next(colors)
        for aid in later:
            color_of[aid] = next(colors)
    for new, old in REPLACES.items():
        color_of[new] = color_of[old]

    gallery_json = ROOT / "app" / "gallery.json"
    previous = {e["id"]: e for e in json.loads(gallery_json.read_text())} if gallery_json.exists() else {}

    def add(group, aid, name, vibe, color, render, pack=None, square=False):
        """`square`: the tile colour shows around the subject by design (emoji rows,
        tinted line art, transparent source art); True/False, or None to take it
        from the render (local sources), kept from the last build when not rebuilt."""
        path = (out_local if pack else out) / f"{aid}.png"
        if (only is None or group in only) and not (missing_only and path.exists()):
            img = render()
            if isinstance(img, tuple):
                img, square = img
            save(img, path); print("ok", group, aid)
        else:
            if square is None:
                square = previous.get(aid, {}).get("square", False)
            if not path.exists():
                if not pack:
                    raise SystemExit(f"{aid}.png missing; rebuild group {group!r}")
                print("missing (local pack, hidden by the picker):", aid)
        entry = {"id": aid, "name": name, "file": f"{aid}.png", "color": color,
                 "group": group, "vibe": vibe}
        if pack:
            entry["pack"] = pack
        if square and pack:
            entry["square"] = True
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
            # classics: US public domain only, still protected in CH/EU -> local pack
            add(group, aid, name, vibe, color_of[aid], render,
                pack="local" if group in LOCAL_COMMONS else None, square=bool(opt and opt[0]))
    for group, items in LOCAL.items():
        for aid, name, vibe, url, box, *opts in items:
            def render(aid=aid, url=url, color=color_of[aid], box=box, opts=opts[0] if opts else None):
                img = local_image(aid, url, color, box, opts)
                if not CACHE:
                    time.sleep(2)
                return img
            add(group, aid, name, vibe, color_of[aid], render, pack="local", square=None)
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
    for aid, name, kind, cols in COLOURS:
        add("colours", aid, name, "neutral", cols[0] if kind == "solid" else cols[1],
            lambda kind=kind, cols=cols: colour_tile(kind, cols))
    gallery = [a for gid, _ in GROUPS for a in interleave(rows[gid])]
    for gid, _ in GROUPS:
        if len(rows[gid]) % 9:
            raise SystemExit(f"{gid}: {len(rows[gid])} avatars, not a multiple of 9")
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
