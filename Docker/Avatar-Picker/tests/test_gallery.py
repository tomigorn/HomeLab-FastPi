import json, os, re, struct, unittest
from PIL import Image

APP = os.path.join(os.path.dirname(__file__), "..", "app")
GALLERY = json.load(open(os.path.join(APP, "gallery.json")))
GROUPS = json.load(open(os.path.join(APP, "groups.json")))
# Rows whose avatars are third-party art kept out of git ("pack": "local",
# files in app/img-local/). A fresh clone has none of them; the tests below
# must pass with or without the local pack present.
LOCAL_GROUPS = {"classics", "disney", "animated", "movies", "lotr", "tvcartoons", "tvshows", "anime",
                "pokemon", "games", "mario", "lego", "dinosaurs", "memes",
                "harrypotter", "heroes", "muppets", "animals", "space", "mythology", "historic", "retro",
                "pirates"}
# Rows added in v1.9 (all in the local pack, even the free and public-domain ones)
NEW_ROWS = ["harrypotter", "heroes", "muppets", "animals", "space", "mythology", "historic", "retro", "pirates"]
# Rows exempt from the f-m-n interleave: memes (mostly animals/objects), colours (no
# people at all), Pokemon and Dinosaurs (creatures; every entry is "neutral") and Lord of
# the Rings (its major cast is mostly male; the row keeps its listed order). v1.9: Harry Potter,
# Marvel & DC and Muppets (casts mostly male), Animals, Space and Retro games (no people; all
# "neutral") and Historic figures (real people: women and men alternate, nobody is "neutral").
FREE_VIBE_GROUPS = {"memes", "colours", "pokemon", "lotr", "dinosaurs", "harrypotter", "heroes", "muppets",
                    "animals", "space", "historic", "retro"}
# Order the user asked for (v1.5): Disney & Pixar, other animated films, live-action
# movies, Lord of the Rings (v1.6), cartoons, live-action TV, anime, Pokemon, video games, Super Mario,
# LEGO and Dinosaurs (v1.7), then
# storybook, illustrated people, flat emoji, art classics, memes, cartoon & sketch,
# the rest, with the colours row last.
# v1.9: Harry Potter and Marvel & DC after Lord of the Rings, Muppets after TV series, Retro games
# after Video games, Animals and Space after Dinosaurs, Mythology, Historic figures and Pirates &
# knights after Art classics.
ORDER = ["disney", "animated", "movies", "lotr", "harrypotter", "heroes", "tvcartoons", "tvshows", "muppets",
         "anime", "pokemon", "games", "retro", "mario", "lego", "dinosaurs", "animals", "space", "storybook",
         "illustrated", "flatemoji", "paintings", "mythology", "historic", "pirates", "memes", "cartoon",
         "ukiyoe", "belleepoque", "fairytale", "comics", "swiss", "people3d", "pixel", "classics",
         "colours"]
LABELS = {"disney": "Disney & Pixar", "animated": "Animated films", "movies": "Movies",
          "lotr": "Lord of the Rings",
          "tvcartoons": "Cartoons", "tvshows": "TV series", "anime": "Anime", "pokemon": "Pokémon",
          "games": "Video games", "mario": "Super Mario", "lego": "LEGO", "dinosaurs": "Dinosaurs",
          "storybook": "Classic storybook",
          "illustrated": "Illustrated people", "flatemoji": "Flat emoji", "paintings": "Art classics",
          "memes": "Memes", "cartoon": "Cartoon & sketch", "colours": "Colours",
          "harrypotter": "Harry Potter", "heroes": "Marvel & DC", "muppets": "Muppets & Sesame Street",
          "animals": "Animals", "space": "Space", "mythology": "Mythology", "historic": "Historic figures",
          "retro": "Retro games", "pirates": "Pirates & knights"}
# Row sizes (every row is a multiple of 9)
SIZES = {"disney": 27, "animated": 27, "movies": 27, "lotr": 27, "tvcartoons": 36, "tvshows": 36, "anime": 36,
         "pokemon": 18, "games": 27, "mario": 18, "lego": 18, "dinosaurs": 18, "flatemoji": 18, "paintings": 18, "memes": 18,
         "colours": 18, "harrypotter": 18, "heroes": 18, "muppets": 18, "animals": 18, "space": 18,
         "mythology": 18, "historic": 18, "retro": 9, "pirates": 9}
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
    "thor": "thor (marvel)", "thor-norse": "thor (norse god)",
    "sauron": "sauron", "sauron-armour": "sauron",
}
# Deliberate exceptions to one character, one row: the owner wants both forms of Sauron (v1.9.1).
SAME_CHARACTER_PAIRS = {frozenset({"sauron", "sauron-armour"})}
# Rows of generic, unnamed figures (emoji, generated people, colours): not characters.
GENERIC_GROUPS = {"illustrated", "flatemoji", "cartoon", "people3d", "pixel", "colours"}
# Characters that must never appear because another entry already is that character.
FORBIDDEN_DUPLICATES = {"big chungus", "mickey", "minnie", "pluto", "winnie the pooh", "piglet",
                        "baby yoda", "the child", "sméagol", "smeagol", "strider", "elessar",
                        "mithrandir", "gandalf the grey", "gandalf the white"}
PACK_DIR = {None: "img", "local": "img-local"}
# Lord of the Rings row: the Fellowship, Bilbo, Arwen, Galadriel, Éowyn, Elrond, Théoden,
# Gollum, Saruman and Sauron; v1.9.1: Sauron's armoured form and eight more of the major cast.
LOTR_V191 = {"sauron-armour", "faramir", "mouth-of-sauron", "treebeard", "denethor", "shelob", "witch-king", "celeborn",
             "balrog"}
LOTR = {"frodo", "samwise", "merry", "pippin", "gandalf", "aragorn", "legolas", "gimli", "boromir",
        "bilbo", "arwen", "galadriel", "eowyn", "elrond", "theoden", "gollum", "saruman", "sauron"} | LOTR_V191
# LEGO row (v1.7): LEGO minifigures. LEGO versions of characters that also appear in another
# row are separate avatars, named "LEGO <character>" (their character key is namespaced).
LEGO = {"wyldstyle", "lego-hermione", "lego-leia", "lego-wonder-woman", "lego-batgirl", "lego-harley-quinn",
        "emmet", "lego-batman", "lego-legolas", "lego-gandalf", "lego-harry-potter", "lego-spider-man",
        "benny", "unikitty", "lego-darth-vader", "lego-yoda", "lego-stormtrooper", "lego-skeleton"}
# Dinosaurs row (v1.7): true dinosaurs only, including Spinosaurus and the biggest recent finds
# (Patagotitan, Nagatitan).
DINOSAURS = {"t-rex", "triceratops", "velociraptor", "stegosaurus", "brachiosaurus", "spinosaurus",
             "ankylosaurus", "parasaurolophus", "allosaurus", "therizinosaurus", "patagotitan", "nagatitan",
             "giganotosaurus", "carnotaurus", "pachycephalosaurus", "dilophosaurus", "styracosaurus",
             "iguanodon"}
# v1.9 rows. Moved avatars keep their ids (and colours), so users' picks survive the move.
HARRY_POTTER = {"harry-potter", "hermione", "ron-weasley", "dumbledore", "hagrid", "snape", "mcgonagall",
                "voldemort", "dobby", "luna-lovegood", "sirius-black", "draco-malfoy", "hedwig", "ginny-weasley",
                "bellatrix", "neville", "lupin", "umbridge"}
HEROES = {"spider-man", "wonder-woman", "iron-man", "black-widow", "batman", "groot", "captain-america",
          "harley-quinn", "superman", "thor", "scarlet-witch", "black-panther", "hulk", "captain-marvel",
          "deadpool", "joker", "catwoman", "wolverine"}
MUPPETS = {"kermit", "miss-piggy", "elmo", "fozzie", "cookie-monster", "animal-muppet", "big-bird", "gonzo",
           "oscar-grouch", "swedish-chef", "bert", "rosita", "count-von-count", "beaker", "grover", "rowlf",
           "statler", "waldorf"}
ANIMALS = {"red-fox", "red-panda", "snowy-owl", "sea-otter", "axolotl", "kitten", "puppy", "giant-panda",
           "seal-pup", "sloth", "hedgehog", "lion-cub", "fennec", "elephant", "highland-cow", "alpaca",
           "meerkat", "snow-leopard"}
SPACE = {"earth", "moon", "sun", "mars", "jupiter", "saturn", "neptune", "black-hole", "pillars-of-creation",
         "cosmic-cliffs", "crab-nebula", "whirlpool-galaxy", "comet", "iss", "hubble", "rocket-launch",
         "spacewalk", "moonwalk"}
MYTHOLOGY = {"athena", "zeus", "japanese-dragon", "medusa", "poseidon", "phoenix", "isis", "thor-norse", "sphinx",
             "freyja", "odin", "quetzalcoatl", "valkyrie", "anubis", "cyclops", "artemis", "ra", "pegasus"}
HISTORIC = {"marie-curie", "einstein", "cleopatra", "leonardo", "ada-lovelace", "newton", "frida-kahlo",
            "darwin", "elizabeth-i", "napoleon", "florence-nightingale", "mozart", "amelia-earhart", "tesla",
            "harriet-tubman", "gandhi", "marie-antoinette", "lincoln"}
# Retro games: Pac-Man, Blinky, Donkey Kong, Link and Sonic already live in Video games / Super Mario.
RETRO = {"space-invader", "ms-pac-man", "mega-man", "pinky", "frogger", "tetris", "pong", "clyde", "inky"}
PIRATES = {"anne-bonny", "blackbeard", "samurai", "mary-read", "long-john-silver", "knight", "joan-of-arc",
           "captain-kidd", "pirate-ship"}
NEW_ROW_IDS = {"harrypotter": HARRY_POTTER, "heroes": HEROES, "muppets": MUPPETS, "animals": ANIMALS,
               "space": SPACE, "mythology": MYTHOLOGY, "historic": HISTORIC, "retro": RETRO, "pirates": PIRATES}
# Moved in v1.9 from Movies / TV series; those rows got new avatars instead (never shrink a row).
MOVED = {"hermione": "harrypotter", "black-widow": "heroes", "spider-man": "heroes", "iron-man": "heroes",
         "groot": "heroes", "kermit": "muppets", "miss-piggy": "muppets", "elmo": "muppets", "fozzie": "muppets",
         "animal-muppet": "muppets", "big-bird": "muppets", "oscar-grouch": "muppets",
         "count-von-count": "muppets", "beaker": "muppets", "rowlf": "muppets"}
REFILLS = {"ripley": "movies", "amelie": "movies", "james-bond": "movies", "terminator": "movies",
           "chewbacca": "movies", "wednesday": "tvshows", "mr-bean": "tvshows", "thing": "tvshows",
           "kitt": "tvshows", "weeping-angel": "tvshows", "k9": "tvshows", "cylon": "tvshows",
           "tribble": "tvshows", "flipper": "tvshows", "cyberman": "tvshows"}
COLOURS_V18 = json.load(open(os.path.join(os.path.dirname(__file__), "colours-v1.8.0.json")))
COLOURS_V19 = json.load(open(os.path.join(os.path.dirname(__file__), "colours-v1.9.0.json")))
# Single additions (v1.7) and the row each one belongs to.
ADDED = {"dipper-pines": "tvcartoons", "patrick-jane": "tvshows", "pochita": "anime"}


def character_key(a):
    """One character, one key: aliases first, else the name without a "(...)" qualifier;
    the LEGO row has its own namespace, so "LEGO Batman" is not Batman."""
    if a["id"] in CHARACTER_ALIASES:
        k = CHARACTER_ALIASES[a["id"]]
    else:
        k = re.sub(r"\s*\(.*\)$", "", a["name"]).strip().lower()
    if a["group"] == "lego":
        return "lego:" + re.sub(r"^lego ", "", k)
    return k
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
        self.assertEqual(len(GROUPS), 36)
        self.assertEqual(len(GALLERY), 486 + 144)  # 630
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
        key = character_key
        seen = {}
        for a in GALLERY:
            if a["group"] in GENERIC_GROUPS:
                continue
            k = key(a)
            if k in seen and frozenset({a["id"], seen[k].split()[0]}) not in SAME_CHARACTER_PAIRS:
                self.fail(f"{a['id']} ({a['group']}) duplicates {seen[k]}")
            seen[k] = f"{a['id']} ({a['group']})"
            self.assertNotIn(a["name"].lower(), FORBIDDEN_DUPLICATES, a["id"])

    def test_lotr_row(self):
        """Lord of the Rings: the major film cast, one avatar each, right after the movies row
        (Gandalf and Gollum moved here from Movies, keeping their ids)."""
        row = [a for a in GALLERY if a["group"] == "lotr"]
        self.assertEqual({a["id"] for a in row}, LOTR)
        ids = [g["id"] for g in GROUPS]
        self.assertEqual(ids.index("lotr"), ids.index("movies") + 1)
        for a in row:
            self.assertEqual(a.get("pack"), "local", a["id"])
        local_dir = os.path.join(APP, "img-local")
        if not os.path.isdir(local_dir):
            self.skipTest("no local pack (fresh clone)")
        for a in row:
            self.assertTrue(os.path.isfile(os.path.join(local_dir, a["file"])), a["id"])

    def test_lego_row(self):
        """LEGO minifigures, right after Super Mario; LEGO versions of characters found in other
        rows are named "LEGO <name>" and do not clash with the original."""
        row = [a for a in GALLERY if a["group"] == "lego"]
        self.assertEqual({a["id"] for a in row}, LEGO)
        ids = [g["id"] for g in GROUPS]
        self.assertEqual(ids.index("lego"), ids.index("mario") + 1)
        others = {character_key(a) for a in GALLERY if a["group"] not in GENERIC_GROUPS | {"lego"}}
        for a in row:
            bare = character_key(a)[len("lego:"):]
            if bare in others:
                self.assertTrue(a["name"].startswith("LEGO "), a["id"])
        self.assertIn("legolas", others)
        self.assertIn("batman", {character_key(a)[len("lego:"):] for a in row})

    def test_lego_namespace_does_not_exempt_other_rows(self):
        """Only the LEGO row is namespaced: a second plain Legolas would still clash."""
        legolas = next(a for a in GALLERY if a["id"] == "legolas")
        fake = dict(legolas, id="legolas-2", group="movies")
        self.assertEqual(character_key(fake), character_key(legolas))
        lego = next(a for a in GALLERY if a["id"] == "lego-legolas")
        self.assertNotEqual(character_key(lego), character_key(legolas))

    def test_dinosaurs_row(self):
        """Dinosaurs: true dinosaurs only, all neutral, right after LEGO."""
        row = [a for a in GALLERY if a["group"] == "dinosaurs"]
        self.assertEqual({a["id"] for a in row}, DINOSAURS)
        self.assertNotIn("pteranodon", {a["id"] for a in row})  # a pterosaur, not a dinosaur
        self.assertTrue(all(a["vibe"] == "neutral" for a in row))
        ids = [g["id"] for g in GROUPS]
        self.assertEqual(ids.index("dinosaurs"), ids.index("lego") + 1)

    def test_new_rows(self):
        """v1.9 rows hold exactly their avatars, all in the local pack, every image present."""
        local_dir = os.path.join(APP, "img-local")
        for gid, ids in NEW_ROW_IDS.items():
            row = [a for a in GALLERY if a["group"] == gid]
            self.assertEqual({a["id"] for a in row}, ids, gid)
            for a in row:
                self.assertEqual(a.get("pack"), "local", a["id"])
                if os.path.isdir(local_dir):
                    self.assertTrue(os.path.isfile(os.path.join(local_dir, a["file"])), a["id"])

    def test_new_rows_placement(self):
        ids = [g["id"] for g in GROUPS]
        for before, row in (("lotr", "harrypotter"), ("harrypotter", "heroes"), ("tvshows", "muppets"),
                            ("games", "retro"), ("dinosaurs", "animals"), ("animals", "space"),
                            ("paintings", "mythology"), ("mythology", "historic"), ("historic", "pirates")):
            self.assertEqual(ids.index(row), ids.index(before) + 1, row)

    def test_moved_avatars_keep_ids(self):
        """Movie heroes, Hermione and the Muppets moved rows; their ids (users' picks) stay, and the
        rows they left got new avatars so no row shrank."""
        rows = {a["id"]: a["group"] for a in GALLERY}
        for aid, group in MOVED.items():
            self.assertEqual(rows.get(aid), group, aid)
        for aid, group in REFILLS.items():
            self.assertEqual(rows.get(aid), group, aid)
        tvshows = {a["id"] for a in GALLERY if a["group"] == "tvshows"}
        self.assertFalse(tvshows & MUPPETS)
        retro = {a["id"] for a in GALLERY if a["group"] == "retro"}
        self.assertFalse(retro & {"pac-man", "blinky", "donkey-kong", "link", "sonic"})

    def test_no_avatar_removed(self):
        """Adding never removes: every v1.8.0 avatar is still in the gallery."""
        ids = {a["id"] for a in GALLERY}
        self.assertEqual(set(COLOURS_V18) - ids, set())

    def test_existing_colours_unchanged(self):
        """New and moved avatars never change the colour of an avatar that already existed."""
        for a in GALLERY:
            if a["id"] in COLOURS_V18:
                self.assertEqual(a["color"], COLOURS_V18[a["id"]], a["id"])

    def test_sauron_twice_on_purpose(self):
        """The owner keeps the Eye of Sauron (same id) and adds the armoured Dark Lord; both are Sauron,
        allowed only as this one explicit pair, side by side in the Lord of the Rings row."""
        eye = next(a for a in GALLERY if a["id"] == "sauron")
        armour = next(a for a in GALLERY if a["id"] == "sauron-armour")
        self.assertEqual(eye["name"], "Eye of Sauron")
        self.assertEqual(armour["name"], "Sauron (armour)")
        self.assertEqual(character_key(eye), character_key(armour))
        self.assertEqual((eye["group"], armour["group"]), ("lotr", "lotr"))
        lotr = [a["id"] for a in GALLERY if a["group"] == "lotr"]
        self.assertEqual(lotr.index("sauron-armour"), lotr.index("sauron") + 1)
        third = dict(armour, id="sauron-3", name="Sauron (Annatar)")
        self.assertNotIn(frozenset({third["id"], eye["id"]}), SAME_CHARACTER_PAIRS)
        self.assertEqual(character_key(third), character_key(eye))

    def test_v191_lotr_additions(self):
        """v1.9.1 adds nine Lord of the Rings avatars at the end of the row; the first 18 keep their order."""
        lotr = [a["id"] for a in GALLERY if a["group"] == "lotr"]
        self.assertEqual(set(lotr[18:]), LOTR_V191)
        self.assertEqual(lotr[:18], ["frodo", "gandalf", "arwen", "samwise", "aragorn", "galadriel", "gollum",
                                     "legolas", "eowyn", "gimli", "boromir", "saruman", "merry", "pippin",
                                     "theoden", "elrond", "bilbo", "sauron"])

    def test_v19_colours_unchanged(self):
        """The v1.9.1 avatars take new colours; every v1.9.0 avatar keeps its colour, none disappears."""
        rows = {a["id"]: a["color"] for a in GALLERY}
        self.assertEqual(set(COLOURS_V19) - set(rows), set())
        for aid, colour in COLOURS_V19.items():
            self.assertEqual(rows[aid], colour, aid)
        new = [rows[aid] for aid in LOTR_V191]
        self.assertEqual(len(set(new)), len(new))

    def test_thor_twice_on_purpose(self):
        """Marvel's Thor and the Norse god are different characters; each has its own key."""
        thor = next(a for a in GALLERY if a["id"] == "thor")
        norse = next(a for a in GALLERY if a["id"] == "thor-norse")
        self.assertNotEqual(character_key(thor), character_key(norse))

    def test_single_additions(self):
        rows = {a["id"]: a["group"] for a in GALLERY}
        for aid, group in ADDED.items():
            self.assertEqual(rows.get(aid), group, aid)

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
