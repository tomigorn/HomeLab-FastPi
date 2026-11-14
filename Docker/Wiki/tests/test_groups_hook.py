import importlib.util
import re
import unittest
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("groups", WIKI / "site/hooks/groups.py")
groups = importlib.util.module_from_spec(spec)
spec.loader.exec_module(groups)

GATES = {"streaming-requesters"}


class PageGroups(unittest.TestCase):
    def test_no_front_matter_means_everyone(self):
        self.assertEqual(groups.page_groups("# Title\n"), [])

    def test_front_matter_list(self):
        text = "---\ngroups: [streaming-requesters]\n---\n# Requests\n"
        self.assertEqual(groups.page_groups(text), ["streaming-requesters"])

    def test_front_matter_single_value(self):
        text = "---\ngroups: streaming-requesters\n---\n# Requests\n"
        self.assertEqual(groups.page_groups(text), ["streaming-requesters"])

    def test_front_matter_without_groups(self):
        self.assertEqual(groups.page_groups("---\ntemplate: public.html\n---\n# Hi\n"), [])


class Visible(unittest.TestCase):
    def test_open_page_visible_without_groups(self):
        self.assertTrue(groups.visible([], set(), GATES))

    def test_gated_page_hidden_without_group(self):
        self.assertFalse(groups.visible(["streaming-requesters"], set(), GATES))

    def test_gated_page_visible_with_group(self):
        self.assertTrue(groups.visible(["streaming-requesters"], {"streaming-requesters"}, GATES))

    def test_negated_group_visible_only_without_it(self):
        self.assertTrue(groups.visible(["!streaming-requesters"], set(), GATES))
        self.assertFalse(groups.visible(["!streaming-requesters"], {"streaming-requesters"}, GATES))

    def test_unknown_group_fails_the_build(self):
        with self.assertRaises(ValueError):
            groups.visible(["streaming-requestors"], set(), GATES)


class FilterBlocks(unittest.TestCase):
    MD = "a\n<!-- only: streaming-requesters -->\nsecret\n<!-- /only -->\nb\n"

    def test_block_removed_without_group(self):
        self.assertEqual(groups.filter_blocks(self.MD, set(), GATES), "a\nb\n")

    def test_block_kept_with_group_markers_dropped(self):
        self.assertEqual(groups.filter_blocks(self.MD, {"streaming-requesters"}, GATES), "a\nsecret\nb\n")

    def test_negated_block(self):
        md = "<!-- only: !streaming-requesters -->\nask the admin\n<!-- /only -->\n"
        self.assertEqual(groups.filter_blocks(md, set(), GATES), "ask the admin\n")
        self.assertEqual(groups.filter_blocks(md, {"streaming-requesters"}, GATES), "")

    def test_indented_markers(self):
        md = "- x\n    <!-- only: streaming-requesters -->\n    y\n    <!-- /only -->\n"
        self.assertEqual(groups.filter_blocks(md, set(), GATES), "- x\n")

    def test_unclosed_block_fails(self):
        with self.assertRaises(ValueError):
            groups.filter_blocks("<!-- only: streaming-requesters -->\nx\n", set(), GATES)

    def test_stray_close_fails(self):
        with self.assertRaises(ValueError):
            groups.filter_blocks("x\n<!-- /only -->\n", set(), GATES)

    def test_nested_block_fails(self):
        md = "<!-- only: streaming-requesters -->\n<!-- only: streaming-requesters -->\n<!-- /only -->\n<!-- /only -->\n"
        with self.assertRaises(ValueError):
            groups.filter_blocks(md, set(), GATES)

    def test_unknown_group_in_marker_fails(self):
        with self.assertRaises(ValueError):
            groups.filter_blocks("<!-- only: nobody -->\nx\n<!-- /only -->\n", set(), GATES)


class PruneNav(unittest.TestCase):
    NAV = [
        {"Start": [{"Home": "index.md"}]},
        {"Requesting": [{"Films": "apps/requests.md"}, {"Help": "apps/request-help.md"}]},
        {"Audiobooks": [{"Requests": "apps/audiobook-requests.md"}]},
    ]

    def test_hidden_pages_and_empty_sections_dropped(self):
        pruned = groups.prune_nav(self.NAV, {"apps/requests.md", "apps/audiobook-requests.md"})
        self.assertEqual(pruned, [
            {"Start": [{"Home": "index.md"}]},
            {"Requesting": [{"Help": "apps/request-help.md"}]},
        ])

    def test_nothing_hidden_keeps_nav(self):
        self.assertEqual(groups.prune_nav(self.NAV, set()), self.NAV)

    def test_no_nav(self):
        self.assertIsNone(groups.prune_nav(None, {"x.md"}))


class Wiring(unittest.TestCase):
    """build.sh, the Caddyfile and the pages must agree on the gate groups."""

    def build_gates(self):
        m = re.search(r"^GATES=\((.*)\)$", (WIKI / "build.sh").read_text(), re.M)
        return set(m.group(1).split())

    def test_every_gate_has_a_caddy_map(self):
        caddy = (WIKI / "Caddyfile").read_text()
        for gate in self.build_gates():
            self.assertIn(f'"+{gate}"', caddy, gate)

    def test_pages_only_use_known_gates(self):
        gates = self.build_gates()
        for page in (WIKI / "site/docs").rglob("*.md"):
            text = page.read_text()
            for g in groups.page_groups(text):
                self.assertIn(g.lstrip("!"), gates, page)
            groups.filter_blocks(text, set(), gates)


if __name__ == "__main__":
    unittest.main()
