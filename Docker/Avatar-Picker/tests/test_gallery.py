import json, os, re, struct, unittest

APP = os.path.join(os.path.dirname(__file__), "..", "app")
GALLERY = json.load(open(os.path.join(APP, "gallery.json")))
GROUPS = json.load(open(os.path.join(APP, "groups.json")))


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    assert head[12:16] == b"IHDR"
    return struct.unpack(">II", head[16:24])


class GalleryTest(unittest.TestCase):
    def test_flat_list_and_counts(self):
        self.assertIsInstance(GALLERY, list)
        self.assertEqual(len(GROUPS), 12)
        self.assertEqual(len(GALLERY), 12 * 9)

    def test_group_order(self):
        self.assertEqual([g["id"] for g in GROUPS],
                         ["storybook", "paintings", "people3d", "illustrated", "pixel", "cartoon",
                          "ukiyoe", "belleepoque", "fairytale", "comics", "flatemoji", "swiss"])

    def test_gallery_follows_group_order_and_interleaves(self):
        """The flat list is grouped row by row, each row ordered f, m, n, f, m, n, ..."""
        gids = [g["id"] for g in GROUPS]
        self.assertEqual([a["group"] for a in GALLERY], [g for g in gids for _ in range(9)])
        for i, a in enumerate(GALLERY):
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
            for vibe in ("feminine", "masculine", "neutral"):
                self.assertEqual(sum(a["vibe"] == vibe for a in row), 3, (grp["id"], vibe))

    def test_vibe_values(self):
        for a in GALLERY:
            self.assertIn(a["vibe"], ("feminine", "masculine", "neutral"), a["id"])

    def test_files(self):
        for a in GALLERY:
            p = os.path.join(APP, "img", a["file"])
            self.assertTrue(os.path.isfile(p), p)
            self.assertEqual(png_size(p), (512, 512), a["id"])
            self.assertLess(os.path.getsize(p), 500 * 1024, a["id"])
            with open(p, "rb") as f:
                self.assertEqual(f.read()[-8:-4], b"IEND", a["id"])  # not truncated

    def test_no_orphan_images(self):
        files = {a["file"] for a in GALLERY}
        self.assertEqual(set(os.listdir(os.path.join(APP, "img"))), files)

    def test_colors(self):
        for a in GALLERY:
            self.assertRegex(a["color"], r"^#[0-9A-Fa-f]{6}$")


if __name__ == "__main__":
    unittest.main()
