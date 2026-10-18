import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import core

GALLERY = [{"id": "fox", "name": "Fox", "file": "fox.png", "color": "#fff"},
           {"id": "owl", "name": "Owl", "file": "owl.png", "color": "#fff"}]
BASE = "https://avatars.example"

def user(pk, username, avatar=None, **attrs):
    if avatar: attrs["avatar"] = avatar
    return {"pk": pk, "username": username, "attributes": attrs}

class Urls(unittest.TestCase):
    def test_avatar_url(self):
        self.assertEqual(core.avatar_url(BASE, "fox"), "https://avatars.example/img/fox.png")

    def test_id_from_url(self):
        self.assertEqual(core.id_from_url(BASE, BASE + "/img/owl.png"), "owl")
        self.assertIsNone(core.id_from_url(BASE, "https://gravatar.com/x"))
        self.assertIsNone(core.id_from_url(BASE, None))

class State(unittest.TestCase):
    def test_marks_taken_and_mine(self):
        users = [user(1, "me", BASE + "/img/fox.png"), user(2, "other", BASE + "/img/owl.png")]
        st = core.gallery_state(GALLERY, users, BASE, "me")
        self.assertEqual({x["id"]: x["status"] for x in st}, {"fox": "mine", "owl": "taken"})
        self.assertTrue(all("username" not in x for x in st))  # never leak who

    def test_free_when_nobody_holds(self):
        st = core.gallery_state(GALLERY, [user(1, "me")], BASE, "me")
        self.assertEqual({x["status"] for x in st}, {"free"})

class Pick(unittest.TestCase):
    def test_unknown_id(self):
        with self.assertRaises(core.UnknownAvatar):
            core.check_pick(GALLERY, [], BASE, "me", "nope")

    def test_taken_by_other(self):
        users = [user(1, "me"), user(2, "other", BASE + "/img/fox.png")]
        with self.assertRaises(core.AvatarTaken):
            core.check_pick(GALLERY, users, BASE, "me", "fox")

    def test_repick_own_is_fine(self):
        users = [user(1, "me", BASE + "/img/fox.png")]
        self.assertEqual(core.check_pick(GALLERY, users, BASE, "me", "fox"), 1)

    def test_returns_caller_pk(self):
        users = [user(7, "me"), user(2, "other", BASE + "/img/fox.png")]
        self.assertEqual(core.check_pick(GALLERY, users, BASE, "me", "owl"), 7)

    def test_unknown_caller(self):
        with self.assertRaises(core.UnknownUser):
            core.check_pick(GALLERY, [user(2, "other")], BASE, "me", "owl")

class Merge(unittest.TestCase):
    def test_keeps_other_attributes(self):
        merged = core.merged_attributes({"theme": "dark", "avatar": "old"}, BASE, "owl")
        self.assertEqual(merged, {"theme": "dark", "avatar": BASE + "/img/owl.png"})

if __name__ == "__main__":
    unittest.main()
