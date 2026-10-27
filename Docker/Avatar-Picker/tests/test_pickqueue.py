import json, os, pathlib, stat, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import pickqueue

BASE = "https://avatars.example"


class Queue(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.dir.name) / "queue.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_or_corrupt_file_is_empty(self):
        self.assertEqual(pickqueue.load(self.path), {})
        self.path.write_text("{not json")
        self.assertEqual(pickqueue.load(self.path), {})
        self.path.write_text("[1, 2]")
        self.assertEqual(pickqueue.load(self.path), {})

    def test_record_last_pick_wins_and_keeps_others(self):
        pickqueue.record(self.path, "me", "fox", "2026-10-27T10:00:00Z")
        pickqueue.record(self.path, "other", "owl", "2026-10-27T10:01:00Z")
        pickqueue.record(self.path, "me", "cat", "2026-10-27T10:02:00Z")
        self.assertEqual(json.loads(self.path.read_text()), {
            "me": {"avatar": "cat", "at": "2026-10-27T10:02:00Z"},
            "other": {"avatar": "owl", "at": "2026-10-27T10:01:00Z"}})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["queue.json"])

    def test_backfill_adds_only_missing_picker_avatars(self):
        pickqueue.record(self.path, "me", "fox", "t1")
        users = [{"username": "me", "attributes": {"avatar": BASE + "/img/owl.png"}},
                 {"username": "new", "attributes": {"avatar": BASE + "/img/cat.png"}},
                 {"username": "none", "attributes": {}},
                 {"username": "foreign", "attributes": {"avatar": "https://elsewhere/x.png"}}]
        self.assertEqual(pickqueue.backfill(self.path, users, BASE, "t2"), ["new"])
        self.assertEqual(pickqueue.load(self.path), {
            "me": {"avatar": "fox", "at": "t1"}, "new": {"avatar": "cat", "at": "t2"}})

    def test_backfill_nothing_missing_does_not_write(self):
        self.assertEqual(pickqueue.backfill(self.path, [], BASE, "t"), [])
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
