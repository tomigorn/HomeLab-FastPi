import copy
import itertools
import json
import os
import re
import sys

import drawings
import render


def machine(shape="tower", disks=4, modules=2, **over):
    kinds = ["nvme", "ssd", "ssd", "hdd", "hdd", "hdd"]
    m = {
        "name": "alpha", "role": "test box", "shape": shape, "collected": "2026-01-02",
        "os": "ExampleOS 1", "model": "ACME Board X1",
        "cpu": {"model": "Example CPU 9000 @ 3.00GHz", "cores": 4, "threads": 8, "max_ghz": 3.5},
        "ram": {"total_gb": 8 * modules, "modules": [{"size_gb": 8, "type": "DDR4"}] * modules},
        "graphics": None,
        "disks": [{"model": f"Disk {i}", "size": "1 TB", "kind": kinds[i % 6]} for i in range(disks)],
        "network": "1 Gbit/s", "source": "live",
    }
    m.update(over)
    return m


def specs(*machines):
    return {"machines": list(machines)}


def three():
    return specs(machine("sbc", 2, 0, name="one"), machine("tower", name="two"), machine("nas", 1, 2, name="three"))


def test_render_has_three_cards_and_title():
    html = render.render(three())
    assert "<title>Holy Grail · Machines</title>" in html
    assert html.count('class="card"') == 3 and html.count('<h2>') == 3
    assert 'name="viewport"' in html
    assert "<script" not in html and "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html


def test_render_escapes_markup():
    m = machine(model="A<b>&", cpu={"model": "C<i>", "cores": 1, "threads": 1, "max_ghz": None})
    html = render.render(specs(m))
    assert "A&lt;b&gt;&amp;" in html
    assert "A<b>" not in html and "C<i>" not in html


def test_beefy_drawing_draws_every_disk_and_no_label_overlap():
    svg = drawings.draw(machine("tower", disks=5, modules=4))
    assert svg.count('data-part="disk"') == 5
    assert svg.count('data-part="ram"') == 4
    boxes = drawings.label_boxes(svg)
    assert len(boxes) >= 6
    for a, b in itertools.combinations(boxes, 2):
        assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (a, b)


def test_every_shape_draws_every_part_without_overlap():
    for shape in ("sbc", "tower", "nas"):
        svg = drawings.draw(machine(shape, disks=5, modules=4))
        assert svg.count('data-part="disk"') == 5, shape
        assert svg.count('data-part="ram"') == 4, shape
        boxes = drawings.label_boxes(svg)
        for a, b in itertools.combinations(boxes, 2):
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (shape, a, b)


def test_missing_ram_modules_still_draws_one_chip():
    svg = drawings.draw(machine("sbc", 1, 0))
    assert svg.count('data-part="ram"') == 1


def _no_overlap(svg, what=""):
    for a, b in itertools.combinations(drawings.label_boxes(svg), 2):
        assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (what, a, b)


def test_attributes_are_escaped():
    bad = 'x"<y'
    m = machine(name=bad, disks=2)
    m["disks"][0]["kind"] = bad
    html = render.render(specs(m))
    assert 'x"<y' not in html
    assert html.count('x&quot;&lt;y') >= 4
    assert 'id="x&quot;&lt;y"' in html


def test_svg_ids_unique_for_similar_names():
    html = render.render(specs(machine(name="a b"), machine(name="a-b"), machine(name="A B")))
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), ids


def test_unknown_shape_is_a_clear_error():
    try:
        drawings.draw(machine("toaster"))
    except ValueError as err:
        assert "toaster" in str(err)
    else:
        raise AssertionError("no error")


def test_real_snapshot_has_no_label_overlap():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "specs.json")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        real = json.load(f)
    for m in real["machines"]:
        _no_overlap(drawings.draw(m), m["name"])


def test_svg_is_well_formed_xml():
    import xml.etree.ElementTree as ET
    for shape in ("sbc", "tower", "nas"):
        ET.fromstring(drawings.draw(machine(shape)))


def test_notes_source_is_marked():
    html = render.render(specs(machine(source="notes")))
    assert "(from notes)" in html
    assert "(from notes)" not in render.render(specs(machine()))
    assert "as of 2026-01-02" in html


def test_no_forbidden_fields_rendered():
    m = machine()
    m["serial"] = "SN-SECRET-123"
    m["mac"] = "aa:bb:cc:dd:ee:ff"
    m["disks"][0]["serial"] = "DISKSERIAL9"
    html = render.render(specs(m))
    for bad in ("SN-SECRET-123", "aa:bb:cc", "DISKSERIAL9"):
        assert bad not in html


PARTS = [{"part": "Cooler", "model": "Example Fan 1", "at": "cooler"},
         {"part": "NVMe HAT", "model": "Example HAT 2", "at": "hat"},
         {"part": "Case", "model": "Example Case 3", "at": "case"},
         {"part": "Power", "model": "Example PSU 4", "at": "power"},
         {"part": "Sticker", "model": "Example Sticker 5"}]


def test_parts_appear_in_spec_list_and_drawing():
    m = machine("sbc", 2, 0, parts=PARTS)
    html = render.render(specs(m))
    dl = html.split('<dl class="spec">', 1)[1]
    for p in PARTS:
        assert f"<dt>{p['part']}</dt><dd>{p['model']}</dd>" in dl
    svg = drawings.draw(m, "m0")
    for title in ("COOLER", "NVME HAT", "CASE", "POWER"):
        assert f">{title}<" in svg
    assert ">STICKER<" not in svg
    boxes = drawings.label_boxes(svg)
    assert not any(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3] for a, b in itertools.combinations(boxes, 2))


def test_merge_parts_by_machine_name():
    s = render.merge_parts(specs(machine("sbc", name="one"), machine("tower", name="two")), {"one": PARTS[:1]})
    assert s["machines"][0]["parts"] == PARTS[:1] and "parts" not in s["machines"][1]

if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for n, f in fns:
        try:
            f()
        except Exception:  # noqa: BLE001
            bad += 1
            print(f"FAIL {n}")
            traceback.print_exc()
    print(f"\n{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
