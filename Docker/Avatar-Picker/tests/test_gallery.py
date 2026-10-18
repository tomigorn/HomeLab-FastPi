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
        self.assertEqual(len(GROUPS), 6)
        self.assertEqual(len(GALLERY), 48)

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

    def test_files(self):
        for a in GALLERY:
            p = os.path.join(APP, "img", a["file"])
            self.assertTrue(os.path.isfile(p), p)
            self.assertEqual(png_size(p), (512, 512), a["id"])
            self.assertLess(os.path.getsize(p), 5 * 1024 * 1024, a["id"])

    def test_no_orphan_images(self):
        files = {a["file"] for a in GALLERY}
        self.assertEqual(set(os.listdir(os.path.join(APP, "img"))), files)

    def test_colors(self):
        for a in GALLERY:
            self.assertRegex(a["color"], r"^#[0-9A-Fa-f]{6}$")


if __name__ == "__main__":
    unittest.main()
