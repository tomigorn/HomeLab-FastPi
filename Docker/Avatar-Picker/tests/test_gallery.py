import json, os, re, struct, unittest
from PIL import Image

APP = os.path.join(os.path.dirname(__file__), "..", "app")
GALLERY = json.load(open(os.path.join(APP, "gallery.json")))
GROUPS = json.load(open(os.path.join(APP, "groups.json")))
# Rows whose avatars are third-party art kept out of git ("pack": "local",
# files in app/img-local/). A fresh clone has none of them; the tests below
# must pass with or without the local pack present.
LOCAL_GROUPS = {"classics", "disney", "animated", "movies", "tvcartoons", "tvshows", "anime",
                "pokemon", "games", "mario", "memes"}
# Rows exempt from the f-m-n interleave: memes (mostly animals/objects), colours (no
# people at all) and Pokemon (creatures; every entry is "neutral").
FREE_VIBE_GROUPS = {"memes", "colours", "pokemon"}
# Order the user asked for (v1.5): Disney & Pixar, other animated films, live-action
# movies, cartoons, live-action TV, anime, Pokemon, video games, Super Mario, then
# storybook, illustrated people, flat emoji, art classics, memes, cartoon & sketch,
# the rest, with the colours row last.
ORDER = ["disney", "animated", "movies", "tvcartoons", "tvshows", "anime", "pokemon", "games",
         "mario", "storybook", "illustrated", "flatemoji", "paintings", "memes", "cartoon",
         "ukiyoe", "belleepoque", "fairytale", "comics", "swiss", "people3d", "pixel", "classics",
         "colours"]
LABELS = {"disney": "Disney & Pixar", "animated": "Animated films", "movies": "Movies",
          "tvcartoons": "Cartoons", "tvshows": "TV series", "anime": "Anime", "pokemon": "Pokémon",
          "games": "Video games", "mario": "Super Mario", "storybook": "Classic storybook",
          "illustrated": "Illustrated people", "flatemoji": "Flat emoji", "paintings": "Art classics",
          "memes": "Memes", "cartoon": "Cartoon & sketch", "colours": "Colours"}
# Row sizes (every row is a multiple of 9)
SIZES = {"disney": 27, "animated": 27, "movies": 27, "tvcartoons": 27, "tvshows": 27, "anime": 27,
         "pokemon": 18, "games": 27, "mario": 18, "flatemoji": 18, "paintings": 18, "memes": 18,
         "colours": 18}
# One character, one row: entries that show the same character under a different
# name or id map to a shared key here (e.g. the meme "Big Chungus" is Bugs Bunny);
# every other entry's key is its name without a "(...)" qualifier. No two entries
# may share a key, so a character can never appear in two rows (or twice in one).
CHARACTER_ALIASES = {
    "big-chungus": "bugs bunny", "mickey-1930": "mickey mouse", "minnie-1928": "minnie mouse",
    "pluto-1930": "pluto", "pooh-1926": "winnie-the-pooh", "piglet-1926": "piglet",
    "betty-boop-1930": "betty boop", "oswald-1927": "oswald the lucky rabbit",
    "felix-1925": "felix the cat", "clarabelle-1930": "clarabelle cow",
    "powerpuff-girls": "blossom (powerpuff girls)", "meme-man": "meme man",
    "spider-man": "spider-man (peter parker)", "miles-morales": "spider-man (miles morales)",
    "gwen-stacy": "spider-woman (gwen stacy)", "mandalorian": "din djarin",
    "doge": "kabosu", "cheems": "balltze", "smudge": "smudge the cat", "e-t": "e.t.",
    "kermit": "kermit the frog", "oscar-grouch": "oscar the grouch", "count-von-count": "count von count",
    "white-rabbit": "white rabbit (alice)", "peter-rabbit": "peter rabbit",
}
# Rows of generic, unnamed figures (emoji, generated people, colours): not characters.
GENERIC_GROUPS = {"illustrated", "flatemoji", "cartoon", "people3d", "pixel", "colours"}
# Characters that must never appear because another entry already is that character.
FORBIDDEN_DUPLICATES = {"big chungus", "mickey", "minnie", "pluto", "winnie the pooh", "piglet",
                        "baby yoda", "the child"}
PACK_DIR = {None: "img", "local": "img-local"}
# Rows whose tiles are an emoji, a generated figure or a swatch on a plain square:
# the tile colour showing at the edges is the design. Elsewhere a uniform edge in
# the tile colour means the crop box ran past the source image (a "band"), unless
# the entry is flagged "square" (transparent source art on its colour).
SQUARE_GROUPS = {"people3d", "flatemoji", "illustrated", "pixel", "cartoon", "colours"}


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    assert head[12:16] == b"IHDR"
    return struct.unpack(">II", head[16:24])


class GalleryTest(unittest.TestCase):
    def test_flat_list_and_counts(self):
        self.assertIsInstance(GALLERY, list)
        self.assertEqual(len(GROUPS), 24)
        self.assertEqual(len(GALLERY), 11 * 9 + 7 * 27 + 6 * 18)  # 396
        for gid, n in SIZES.items():
            self.assertEqual(sum(a["group"] == gid for a in GALLERY), n, gid)

    def test_group_order_and_labels(self):
        self.assertEqual([g["id"] for g in GROUPS], ORDER)
        for g in GROUPS:
            if g["id"] in LABELS:
                self.assertEqual(g["label"], LABELS[g["id"]])

    def test_gallery_follows_group_order_and_interleaves(self):
        """The flat list is grouped row by row, each row ordered f, m, n, f, m, n, ..."""
        gids = [g["id"] for g in GROUPS]
        order = [a["group"] for a in GALLERY]
        self.assertEqual(order, sorted(order, key=gids.index))
        pos = {}
        for a in GALLERY:
            i = pos[a["group"]] = pos.get(a["group"], -1) + 1
            if a["group"] in FREE_VIBE_GROUPS:
                continue
            self.assertEqual(a["vibe"], ("feminine", "masculine", "neutral")[i % 3], a["id"])

    def test_colours_row(self):
        """Generated locally, committed, plain names, solid 'color' swatches."""
        row = [a for a in GALLERY if a["group"] == "colours"]
        self.assertEqual(len(row), 18)
        for a in row:
            self.assertTrue(a["id"].startswith("colour-"), a["id"])
            self.assertIsNone(a.get("pack"), a["id"])
            self.assertEqual(a["vibe"], "neutral", a["id"])
            self.assertRegex(a["name"], r"^[A-Z][a-z]+$", a["id"])
        self.assertEqual(GROUPS[-1]["id"], "colours")

    def test_one_row_per_character(self):
        """No character appears in more than one row (or twice in a row)."""
        def key(a):
            if a["id"] in CHARACTER_ALIASES:
                return CHARACTER_ALIASES[a["id"]]
            return re.sub(r"\s*\(.*\)$", "", a["name"]).strip().lower()
        seen = {}
        for a in GALLERY:
            if a["group"] in GENERIC_GROUPS:
                continue
            k = key(a)
            if k in seen:
                self.fail(f"{a['id']} ({a['group']}) duplicates {seen[k]}")
            seen[k] = f"{a['id']} ({a['group']})"
            self.assertNotIn(a["name"].lower(), FORBIDDEN_DUPLICATES, a["id"])

    def test_pokemon_row_is_neutral(self):
        """The Pokemon row is vibe-exempt; every entry is marked neutral."""
        row = [a for a in GALLERY if a["group"] == "pokemon"]
        self.assertEqual(len(row), 18)
        self.assertTrue(all(a["vibe"] == "neutral" for a in row))

    def test_file_matches_id(self):
        for a in GALLERY:
            self.assertEqual(a["file"], a["id"] + ".png")

    def test_unique_ids_and_names(self):
        ids = [g["id"] for g in GALLERY]; names = [g["name"] for g in GALLERY]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))

    def test_id_format(self):
        for g in GALLERY:
            self.assertRegex(g["id"], r"^[a-z0-9-]+$")

    def test_groups(self):
        gids = [g["id"] for g in GROUPS]
        self.assertEqual(len(gids), len(set(gids)))
        for g in GROUPS:
            self.assertTrue(g["label"])
        for a in GALLERY:
            self.assertIn(a["group"], gids)
        for gid in gids:
            self.assertTrue(any(a["group"] == gid for a in GALLERY), gid)

    def test_rows_are_mixed(self):
        """Every row holds a multiple of 9 avatars (at least 9), a third of each vibe."""
        for grp in GROUPS:
            row = [a for a in GALLERY if a["group"] == grp["id"]]
            self.assertGreaterEqual(len(row), 9, grp["id"])
            self.assertEqual(len(row) % 9, 0, grp["id"])
            if grp["id"] in FREE_VIBE_GROUPS:
                continue
            for vibe in ("feminine", "masculine", "neutral"):
                self.assertEqual(sum(a["vibe"] == vibe for a in row), len(row) // 3, (grp["id"], vibe))

    def test_vibe_values(self):
        for a in GALLERY:
            self.assertIn(a["vibe"], ("feminine", "masculine", "neutral"), a["id"])

    def test_pack(self):
        """Local-pack rows are exactly the copyrighted pop-culture rows plus the
        classics (US public domain only, still protected in CH/EU); everything else
        is committed."""
        for a in GALLERY:
            self.assertIn(a.get("pack"), PACK_DIR, a["id"])
            self.assertEqual(a.get("pack") == "local", a["group"] in LOCAL_GROUPS, a["id"])

    def check_png(self, p, aid):
        self.assertEqual(png_size(p), (512, 512), aid)
        self.assertLess(os.path.getsize(p), 500 * 1024, aid)
        with open(p, "rb") as f:
            self.assertEqual(f.read()[-8:-4], b"IEND", aid)  # not truncated

    def test_files(self):
        """Committed images must exist; local-pack images are checked if present."""
        for a in GALLERY:
            p = os.path.join(APP, PACK_DIR[a.get("pack")], a["file"])
            if a.get("pack") == "local" and not os.path.exists(p):
                continue
            self.assertTrue(os.path.isfile(p), p)
            self.check_png(p, a["id"])

    def test_no_orphan_images(self):
        committed = {a["file"] for a in GALLERY if a.get("pack") is None}
        self.assertEqual(set(os.listdir(os.path.join(APP, "img"))), committed)
        local_dir = os.path.join(APP, "img-local")
        if os.path.isdir(local_dir):
            local = {a["file"] for a in GALLERY if a.get("pack") == "local"}
            self.assertLessEqual(set(os.listdir(local_dir)), local)

    def test_local_pack_is_gitignored(self):
        """Copyrighted art must never be committed to the public repo."""
        ignore = open(os.path.join(APP, "..", ".gitignore")).read().split("\n")
        self.assertIn("app/img-local/", ignore)
        dockerignore = open(os.path.join(APP, "..", ".dockerignore")).read()
        self.assertNotIn("img-local", dockerignore)  # but it is baked into the image

    def test_no_edge_band(self):
        """No tile shows its background colour as a band along an edge (the crop
        box must lie inside the source image); squares are exempt."""
        for a in GALLERY:
            if a["group"] in SQUARE_GROUPS or a.get("square"):
                continue
            p = os.path.join(APP, PACK_DIR[a.get("pack")], a["file"])
            if not os.path.exists(p):
                continue
            px = Image.open(p).convert("RGB").load()
            col = tuple(int(a["color"][i:i + 2], 16) for i in (1, 3, 5))
            edges = {"top": [(x, 0) for x in range(512)], "bottom": [(x, 511) for x in range(512)],
                     "left": [(0, y) for y in range(512)], "right": [(511, y) for y in range(512)]}
            for edge, pts in edges.items():
                same = sum(max(abs(px[pt][k] - col[k]) for k in range(3)) <= 8 for pt in pts)
                self.assertLess(same / 512, 0.95, f"{a['id']}: {edge} edge is a band of the tile colour")

    def test_square_flag(self):
        """`square` marks local-pack tiles whose transparent source shows the tile colour."""
        for a in GALLERY:
            if "square" in a:
                self.assertIs(a["square"], True, a["id"])
                self.assertEqual(a.get("pack"), "local", a["id"])

    def test_colors(self):
        for a in GALLERY:
            self.assertRegex(a["color"], r"^#[0-9A-Fa-f]{6}$")


if __name__ == "__main__":
    unittest.main()
