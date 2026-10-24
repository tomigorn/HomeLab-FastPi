import copy
import itertools
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
    assert html.count('class="card"') == 4 and html.count('<h2>') == 4
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


def test_cabinet_has_machines_in_order_and_airflow_parts():
    svg = drawings.draw_cabinet(three())
    xs = [svg.index(f'href="#{n}"') for n in ("one", "two", "three")]
    assert xs == sorted(xs)
    pos = [float(__import__("re").search(rf'<a href="#{n}"><text x="([\d.]+)"', svg).group(1)) for n in ("one", "two", "three")]
    assert pos == sorted(pos) and len(set(pos)) == 3
    for part in ("exhaust", "intake", "power-strip"):
        assert f'data-part="{part}"' in svg, part
    assert "Max Hauri Design Line" in svg and "6× Type 13" in svg
    assert svg.count('data-part="socket"') == 6
    boxes = drawings.label_boxes(svg)
    for a, b in itertools.combinations(boxes, 2):
        assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (a, b)


def test_cabinet_is_first_in_page_and_cards_have_anchors():
    html = render.render(three())
    assert html.index("data-part=\"exhaust\"") < html.index('id="one"')
    assert 'id="one"' in html and 'id="three"' in html


def test_sbc_draws_nvme_hat_and_both_usb_disks():
    disks = [{"model": "N", "size": "512 GB", "kind": "nvme"}, {"model": "U1", "size": "2 TB", "kind": "usb-hdd"}, {"model": "U2", "size": "2 TB", "kind": "usb-hdd"}]
    svg = drawings.draw(dict(machine("sbc", 3, 0), disks=disks))
    assert svg.count('data-part="hat"') == 1
    assert svg.count('data-part="disk"') == 3
    assert svg.count('data-kind="usb-hdd"') == 2


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
