import json, os, re, struct, unittest

APP = os.path.join(os.path.dirname(__file__), "..", "app")
GALLERY = json.load(open(os.path.join(APP, "gallery.json")))
GROUPS = json.load(open(os.path.join(APP, "groups.json")))
# Rows whose avatars are third-party art kept out of git ("pack": "local",
# files in app/img-local/). A fresh clone has none of them; the tests below
# must pass with or without the local pack present.
LOCAL_GROUPS = {"movies", "tvcartoons", "anime", "games", "memes"}
# Meme row: mostly animals/objects, so the 3/3/3 f-m-n rule does not apply.
FREE_VIBE_GROUPS = {"memes"}
PACK_DIR = {None: "img", "local": "img-local"}


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    assert head[12:16] == b"IHDR"
    return struct.unpack(">II", head[16:24])


class GalleryTest(unittest.TestCase):
    def test_flat_list_and_counts(self):
        self.assertIsInstance(GALLERY, list)
        self.assertEqual(len(GROUPS), 18)
        self.assertEqual(len(GALLERY), 18 * 9)

    def test_group_order(self):
        self.assertEqual([g["id"] for g in GROUPS],
                         ["storybook", "paintings", "people3d", "illustrated", "pixel", "cartoon",
                          "ukiyoe", "belleepoque", "fairytale", "comics", "flatemoji", "swiss",
                          "classics", "movies", "tvcartoons", "anime", "games", "memes"])

    def test_gallery_follows_group_order_and_interleaves(self):
        """The flat list is grouped row by row, each row ordered f, m, n, f, m, n, ..."""
        gids = [g["id"] for g in GROUPS]
        self.assertEqual([a["group"] for a in GALLERY], [g for g in gids for _ in range(9)])
        for i, a in enumerate(GALLERY):
            if a["group"] in FREE_VIBE_GROUPS:
                continue
            self.assertEqual(a["vibe"], ("feminine", "masculine", "neutral")[i % 3], a["id"])

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
        """Every row holds exactly 9 avatars: 3 feminine, 3 masculine, 3 neutral."""
        for grp in GROUPS:
            row = [a for a in GALLERY if a["group"] == grp["id"]]
            self.assertEqual(len(row), 9, grp["id"])
            if grp["id"] in FREE_VIBE_GROUPS:
                continue
            for vibe in ("feminine", "masculine", "neutral"):
                self.assertEqual(sum(a["vibe"] == vibe for a in row), 3, (grp["id"], vibe))

    def test_vibe_values(self):
        for a in GALLERY:
            self.assertIn(a["vibe"], ("feminine", "masculine", "neutral"), a["id"])

    def test_pack(self):
        """Local-pack rows are exactly the copyrighted pop-culture rows; everything
        else (incl. the public-domain classics) is committed."""
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

    def test_colors(self):
        for a in GALLERY:
            self.assertRegex(a["color"], r"^#[0-9A-Fa-f]{6}$")


if __name__ == "__main__":
    unittest.main()
