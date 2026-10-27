import importlib.util, io, os, unittest, zipfile
from PIL import Image

SPEC = importlib.util.spec_from_file_location(
    "build_gallery", os.path.join(os.path.dirname(__file__), "..", "scripts", "build-gallery.py"))
bg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bg)


def png(colour, size=(40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return buf.getvalue()


class ZipSourceTest(unittest.TestCase):
    """A press-kit archive can be a local-pack source: "<url of the .zip>#<member path>"."""

    def setUp(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Kit/red.png", png((255, 0, 0)))
            z.writestr("Kit/blue.png", png((0, 0, 255)))
        self.zip_bytes = buf.getvalue()
        self.fetched = []
        self.real_get = bg.get
        bg.get = lambda url: self.fetched.append(url) or (self.zip_bytes if url.endswith(".zip") else png((0, 255, 0)))

    def tearDown(self):
        bg.get = self.real_get

    def test_member_of_a_zip(self):
        tile, square = bg.local_image("x", "https://example.com/press.zip#Kit/blue.png", "#FFFFFF", (0, 0, 40))
        self.assertEqual(tile.size, (512, 512))
        self.assertEqual(tile.getpixel((256, 256)), (0, 0, 255))
        self.assertFalse(square)
        self.assertEqual(self.fetched, ["https://example.com/press.zip"])

    def test_plain_url_unchanged(self):
        tile, _ = bg.local_image("x", "https://example.com/a.png", "#FFFFFF", (0, 0, 40))
        self.assertEqual(tile.getpixel((10, 10)), (0, 255, 0))
        self.assertEqual(self.fetched, ["https://example.com/a.png"])


if __name__ == "__main__":
    unittest.main()
