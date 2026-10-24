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
        "os": "ExampleOS 1", "board": {"make": "ACME", "model": "Board X1"},
        "cpu": {"make": "Example", "model": "CPU 9000", "cores": 4, "threads": 8, "base_ghz": 3.0, "max_ghz": 3.5},
        "ram": {"total_gb": 8 * modules, "modules": [{"make": "Acme", "part": "R8", "size_gb": 8, "type": "DDR4", "speed_mts": 3200}] * modules},
        "graphics": None,
        "disks": [{"make": "Acme", "model": f"Disk {i}", "size": "1 TB", "kind": kinds[i % 6], "link": None, "rpm": None} for i in range(disks)],
        "network": {"make": "Acme", "model": "N1", "speed": "1 Gbit/s"}, "source": "live",
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
    m = machine(board={"make": "A<b>&", "model": "x"}, cpu={"make": "C<i>", "model": "z", "cores": 1, "threads": 1, "base_ghz": None, "max_ghz": None})
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


PARTS = [{"part": "Cooler", "make": "Acme", "model": "Fan 1", "at": "cooler"},
         {"part": "NVMe HAT", "make": "Acme", "model": "HAT 2", "at": "hat"},
         {"part": "Case", "make": "Acme", "model": "Case 3", "at": "case"},
         {"part": "Power", "make": "Acme", "model": "PSU 4", "at": "power"},
         {"part": "Sticker", "model": "Sticker 5"}]


def test_parts_appear_in_spec_list_and_drawing():
    m = machine("sbc", 2, 0, parts=PARTS)
    html = render.render(specs(m))
    dl = html.split('<dl class="spec">', 1)[1]
    for p in PARTS:
        assert f"<dt>{p['part']}</dt><dd>{p.get('make', 'unknown')} {p['model']}</dd>" in dl
    svg = drawings.draw(m, "m0")
    for title in ("COOLER", "NVME HAT", "CASE", "POWER"):
        assert f">{title}<" in svg
    assert ">STICKER<" not in svg
    boxes = drawings.label_boxes(svg)
    assert not any(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3] for a, b in itertools.combinations(boxes, 2))


CPU = {"make": "Intel", "model": "Core i5-11400", "cores": 6, "threads": 12, "base_ghz": 2.6, "max_ghz": 4.4}
CRUCIAL = {"make": "Crucial", "part": "CT8G4SFS832A", "size_gb": 8, "type": "DDR4", "speed_mts": 3200}
EXOS = {"make": "Seagate", "model": "Exos ST30000NM004K", "size": "30 TB", "kind": "hdd", "link": "SATA 6 Gb/s", "rpm": 7200}


def test_display_strings():
    assert drawings.cpu_sub(CPU) == "Intel Core i5-11400 · 6C/12T · 2.6–4.4 GHz"
    assert drawings.cpu_sub({**CPU, "base_ghz": None, "max_ghz": 2.4}) == "Intel Core i5-11400 · 6C/12T · 2.4 GHz"
    assert drawings.cpu_sub({**CPU, "base_ghz": 2.0, "max_ghz": 2.0}) == "Intel Core i5-11400 · 6C/12T · 2 GHz"
    assert drawings.cpu_sub({**CPU, "make": "unknown", "base_ghz": None, "max_ghz": None}) == "unknown Core i5-11400 · 6C/12T"
    assert drawings.ram_sub({"total_gb": 16, "modules": [CRUCIAL, CRUCIAL]}) == "2× Crucial CT8G4SFS832A · DDR4-3200 · 16 GB"
    assert drawings.ram_sub({"total_gb": 8, "modules": [CRUCIAL]}) == "Crucial CT8G4SFS832A · DDR4-3200 · 8 GB"
    pi = {"make": "Raspberry Pi (on-board)", "part": "LPDDR4X", "size_gb": 8, "type": "LPDDR4X", "speed_mts": 4267}
    assert drawings.ram_sub({"total_gb": 8, "modules": [pi]}) == "Raspberry Pi (on-board) · LPDDR4X-4267 · 8 GB"
    assert drawings.ram_sub({"total_gb": 8, "modules": []}) == "unknown · 8 GB"
    assert drawings.disk_sub(EXOS) == "Seagate Exos ST30000NM004K · SATA 6 Gb/s · 7200 rpm · 30 TB"
    assert drawings.disk_sub({**EXOS, "link": None, "rpm": None}) == "Seagate Exos ST30000NM004K · 30 TB"
    assert drawings.disk_sub({**EXOS, "make": "unknown"}, each=True) == "unknown Exos ST30000NM004K · SATA 6 Gb/s · 7200 rpm · 30 TB each"
    assert drawings.net_sub({"make": "Realtek", "model": "RTL8111", "speed": "1 Gbit/s"}) == "Realtek RTL8111 · 1 Gbit/s"
    assert drawings.net_sub({"make": "unknown", "model": "", "speed": None}) == "unknown"
    assert drawings.board_sub({"board": {"make": "Gigabyte", "model": "H510M H V2"}, "graphics": {"make": "Intel", "model": "UHD Graphics 730"}}) == "Gigabyte H510M H V2 · Intel UHD Graphics 730"


def test_spec_list_and_drawing_use_the_same_strings():
    m = machine("tower", 2, 2)
    m["cpu"], m["ram"]["modules"], m["disks"] = CPU, [CRUCIAL, CRUCIAL], [EXOS, EXOS]
    html = render.render(specs(m))
    svg = drawings.draw(m)
    for s in (drawings.cpu_sub(CPU), "2× Crucial CT8G4SFS832A · DDR4-3200 · 16 GB", drawings.net_sub(m["network"])):
        assert e(s) in html
    rows = dict(render.spec_rows(m))
    assert rows["CPU"] == drawings.cpu_sub(CPU) and rows["Network"] == "Acme N1 · 1 Gbit/s"
    assert rows["HDD"] == drawings.disk_sub(EXOS)
    assert "7200 rpm" in html and "7200" in svg
    _no_overlap(svg)


def test_legacy_snapshot_still_renders_with_unknown_gaps():
    m = machine("sbc", 1, 1)
    del m["board"], m["cpu"]["make"], m["cpu"]["base_ghz"]
    m["model"], m["network"], m["graphics"] = "Old Board", "1 Gbit/s", "Intel UHD"
    m["cpu"]["model"] = "Old CPU"
    m["ram"]["modules"] = [{"size_gb": 8, "type": "DDR4"}]
    m["disks"] = [{"model": "Old Disk", "size": "1 TB", "kind": "hdd"}]
    html = render.render(specs(m))
    for s in ("unknown Old Board", "unknown Old CPU", "unknown Old Disk · 1 TB", "unknown · DDR4 · 8 GB", "unknown · 1 Gbit/s"):
        assert e(s) in html, s


e = render.e


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
