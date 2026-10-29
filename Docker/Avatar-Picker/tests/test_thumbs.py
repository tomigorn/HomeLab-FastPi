import importlib.util, json, os, pathlib, shutil, tempfile, unittest
from PIL import Image

SPEC = importlib.util.spec_from_file_location(
    "build_thumbs", os.path.join(os.path.dirname(__file__), "..", "scripts", "build_thumbs.py"))
bt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bt)


class BuildThumbsTest(unittest.TestCase):
    def setUp(self):
        self.app = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.app)
        (self.app / "img").mkdir(); (self.app / "img-local").mkdir()
        Image.new("RGB", (512, 512), (200, 40, 40)).save(self.app / "img" / "red.png")
        Image.new("RGBA", (512, 512), (0, 0, 255, 128)).save(self.app / "img-local" / "blue.png")
        (self.app / "gallery.json").write_text(json.dumps([
            {"id": "red", "file": "red.png"},
            {"id": "blue", "file": "blue.png", "pack": "local"},
            {"id": "gone", "file": "gone.png", "pack": "local"}]))
        self.out = self.app / "thumbs"

    def build(self):
        return bt.build(self.app, self.out)

    def test_webp_per_width_and_manifest(self):
        manifest = self.build()
        self.assertEqual(set(manifest), {"red", "blue"})
        self.assertEqual(json.loads((self.out / "thumbs.json").read_text()), manifest)
        for aid, h in manifest.items():
            self.assertRegex(h, r"^[0-9a-f]{10}$")
            for w in bt.WIDTHS:
                with Image.open(self.out / f"{aid}.{h}.{w}.webp") as im:
                    self.assertEqual((im.format, im.size), ("WEBP", (w, w)))
        self.assertEqual(bt.WIDTHS, (160, 320))

    def test_thumbs_are_small(self):
        manifest = self.build()
        for w in bt.WIDTHS:
            self.assertLess((self.out / f"red.{manifest['red']}.{w}.webp").stat().st_size, 20_000)

    def test_hash_follows_the_image(self):
        before = self.build()["red"]
        self.assertEqual(self.build()["red"], before)
        Image.new("RGB", (512, 512), (10, 200, 10)).save(self.app / "img" / "red.png")
        after = self.build()["red"]
        self.assertNotEqual(after, before)
        self.assertFalse(list(self.out.glob(f"red.{before}.*")), "stale thumbs removed")
        self.assertTrue((self.out / f"red.{after}.160.webp").exists())

    def test_only_thumbs_and_manifest_written(self):
        manifest = self.build()
        expected = {"thumbs.json"} | {f"{a}.{h}.{w}.webp" for a, h in manifest.items() for w in bt.WIDTHS}
        self.assertEqual({p.name for p in self.out.iterdir()}, expected)


if __name__ == "__main__":
    unittest.main()
