import html
import re
import textwrap

W = 1000
COL_L, COL_R = 300, 700
X_L, X_R = 30, 970
TITLE, SUB, LINE = 20, 13, 17
KIND = {"nvme": "NVME", "ssd": "SSD", "hdd": "HDD", "usb-hdd": "USB HDD"}

INK, LEAD, SUBC = "#e8f1ff", "#9cc3ff", "#b9d4ff"


def esc(s):
    return html.escape(str(s))


def wrap(text, width=33, maxlines=4):
    lines = textwrap.wrap(text, width, break_long_words=True) or [""]
    if len(lines) > maxlines:
        lines = lines[:maxlines]
        lines[-1] = lines[-1][: width - 1] + "…"
    return lines


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "m"


def text(x, y, s, size, anchor=None, fill=INK, cls=""):
    a = f' text-anchor="{anchor}"' if anchor else ""
    c = f' class="{cls}"' if cls else ""
    return f'<text x="{x}" y="{y}" font-size="{size}"{a} fill="{fill}"{c}>{esc(s)}</text>'


def label_boxes(svg):
    boxes = []
    for m in re.finditer(r"<text ([^>]*)>(.*?)</text>", svg):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        s = html.unescape(m.group(2))
        x, y, fs = float(attrs["x"]), float(attrs["y"]), float(attrs["font-size"])
        w = len(s) * 0.6 * fs
        x0 = x - w if attrs.get("text-anchor") == "end" else x - w / 2 if attrs.get("text-anchor") == "middle" else x
        boxes.append((x0, y - fs, x0 + w, y))
    return boxes


def frame(uid, h, body, title):
    return (
        f'<svg class="art" viewBox="0 0 {W} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(title)}" '
        'font-family="ui-monospace, Menlo, Consolas, monospace">'
        f'<defs><pattern id="g1-{uid}" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="#2f5b9a" stroke-width=".6"/></pattern>'
        f'<pattern id="g2-{uid}" width="100" height="100" patternUnits="userSpaceOnUse"><path d="M100 0H0V100" fill="none" stroke="#3d6db3" stroke-width="1.1"/></pattern></defs>'
        f'<rect width="{W}" height="{h}" fill="#173d73"/><rect width="{W}" height="{h}" fill="url(#g1-{uid})"/><rect width="{W}" height="{h}" fill="url(#g2-{uid})"/>'
        f"{body}</svg>"
    )


def layout(callouts, h_min):
    h = h_min
    while True:
        leaders, texts, ok = [], [], True
        for side in ("L", "R"):
            items = sorted((c for c in callouts if c["side"] == side), key=lambda c: c["py"])
            for c in items:
                c["lines"] = wrap(c["sub"]) if c.get("sub") else []
                c["pitch"] = 22 + LINE * len(c["lines"]) + 14
            ys, nxt = [], 50
            for c in items:
                y = max(c["py"], nxt)
                ys.append(y)
                nxt = y + c["pitch"]
            limit = h - 24
            for i in range(len(items) - 1, -1, -1):
                cap = limit - (items[i]["pitch"] - 14) + 4
                if i + 1 < len(items):
                    cap = min(cap, ys[i + 1] - items[i]["pitch"])
                ys[i] = min(ys[i], cap)
            if items and ys[0] < 50:
                h += 50 - ys[0] + 10
                ok = False
                break
            for c, y in zip(items, ys):
                ex, tx, anc = (COL_L, X_L, None) if side == "L" else (COL_R, X_R, "end")
                leaders.append(f'<path d="M{c["px"]} {c["py"]} L{ex} {y + 7} H{tx}"/>')
                leaders.append(f'<circle cx="{c["px"]}" cy="{c["py"]}" r="3" fill="{LEAD}" stroke="none"/>')
                texts.append(text(tx, y, c["title"], TITLE, anc, cls="t"))
                for k, ln in enumerate(c["lines"]):
                    texts.append(text(tx, y + 22 + LINE * k, ln, SUB, anc, SUBC, "sub"))
        if ok:
            return h, f'<g stroke="{LEAD}" stroke-width="1.2" fill="none">{"".join(leaders)}</g><g fill="{INK}">{"".join(texts)}</g>'


def unk(v):
    return (v or "").strip() or "unknown"


def make_model(make, model):
    return f"{unk(make)} {model or ''}".strip()


def normalize(m):
    m = dict(m)
    if "board" not in m:
        m["board"] = {"make": "unknown", "model": m.get("model", "")}
    if isinstance(m.get("graphics"), str):
        m["graphics"] = {"make": "unknown", "model": m["graphics"]}
    if isinstance(m.get("network"), str):
        m["network"] = {"make": "unknown", "model": "", "speed": m["network"]}
    return m


def ghz(c):
    base, top = c.get("base_ghz"), c.get("max_ghz")
    if base and top and base != top:
        return f"{base:g}–{top:g} GHz"
    v = top or base
    return f"{v:g} GHz" if v else None


def join(*parts):
    return " · ".join(p for p in parts if p)


def cpu_sub(c):
    return join(make_model(c.get("make"), c.get("model")), f'{c["cores"]}C/{c["threads"]}T', ghz(c))


def ram_sub(r):
    groups = {}
    for mod in r.get("modules") or []:
        k = (mod.get("make"), mod.get("part") or "", mod.get("type") or "", mod.get("speed_mts"))
        groups.setdefault(k, []).append(mod["size_gb"])
    if not groups:
        return join("unknown", f'{r["total_gb"]} GB')
    out = []
    for (make, part, typ, speed), sizes in groups.items():
        kind = f"{typ}-{speed}" if typ and speed else typ
        name = make_model(make, "" if part == typ else part)
        out.append(join((f"{len(sizes)}× " if len(sizes) > 1 else "") + name, kind, f"{sum(sizes)} GB"))
    return " + ".join(out)


def disk_sub(d, each=False):
    s = join(make_model(d.get("make"), d["model"]), d.get("link"), f'{d["rpm"]} rpm' if d.get("rpm") else None, d["size"])
    return s + (" each" if each else "")


def net_sub(n):
    return join(make_model(n.get("make"), n.get("model")), n.get("speed"))


def board_sub(m):
    g = m.get("graphics")
    return join(make_model(m["board"].get("make"), m["board"].get("model")), make_model(g.get("make"), g.get("model")) if g else None)


def part_sub(p):
    return make_model(p.get("make"), p["model"])


def disk_callouts(disks, coords, side_of):
    groups = {}
    for i, d in enumerate(disks):
        groups.setdefault((d["kind"], d.get("make"), d["model"], d["size"], d.get("link"), d.get("rpm")), []).append(i)
    out = []
    for (kind, *_), idx in groups.items():
        n = len(idx)
        px, py = coords[idx[0]]
        out.append({"side": side_of(px), "px": px, "py": py, "title": KIND.get(kind, kind.upper()) + (f" ×{n}" if n > 1 else ""),
                    "sub": disk_sub(disks[idx[0]], each=n > 1)})
    return out


def disk_box(x, y, w, h, d, extra=""):
    return f'<rect data-part="disk" data-kind="{esc(d["kind"])}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="2"{extra}/>'


def ram_sticks(modules, x0, y0, h, pitch=16, w=10):
    n = max(len(modules), 1)
    return "".join(f'<rect data-part="ram" x="{x0 + pitch * i}" y="{y0}" width="{w}" height="{h}"/>' for i in range(n))


def common_callouts(m, side_cpu="L"):
    return [{"side": side_cpu, "title": "CPU", "sub": cpu_sub(m["cpu"])},
            {"side": "R", "title": "RAM", "sub": ram_sub(m["ram"])},
            {"side": "R", "title": "BOARD", "sub": board_sub(m)}]


def part_callouts(m, anchors):
    """Hand-listed parts (parts.json) with an `at` this shape knows get a label; the rest only appear in the spec list."""
    return [{"side": anchors[p["at"]][2], "px": anchors[p["at"]][0], "py": anchors[p["at"]][1], "title": p["part"].upper(), "sub": part_sub(p)}
            for p in m.get("parts", []) if p.get("at") in anchors]


def has_part(m, at):
    return any(p.get("at") == at for p in m.get("parts", []))


SBC_ANCHORS = {"cooler": (476, 152, "R"), "hat": (584, 248, "R"), "case": (646, 74, "R"), "power": (381, 282, "L")}


def draw_tower(m):
    nv = [i for i, d in enumerate(m["disks"]) if d["kind"] == "nvme"]
    bay = [i for i, d in enumerate(m["disks"]) if d["kind"] != "nvme"]
    b = ['<g stroke="#e8f1ff" fill="none" stroke-width="2">',
         '<rect x="330" y="60" width="300" height="400" rx="8"/><rect x="345" y="75" width="270" height="370" rx="4" stroke-dasharray="6 5" stroke-width="1.2"/>',
         '<rect x="370" y="100" width="200" height="220" stroke-width="1.6"/><rect x="362" y="108" width="14" height="64"/>',
         '<rect x="410" y="140" width="70" height="70"/><circle cx="445" cy="175" r="26"/><circle cx="445" cy="175" r="6"/>',
         ram_sticks(m["ram"]["modules"], 500, 130, 100)]
    coords = {}
    for k, i in enumerate(nv):
        y = 250 + 24 * k
        b.append(disk_box(395, y, 110, 16, m["disks"][i]))
        coords[i] = (450, y + 8)
    n = len(bay)
    if n:
        pitch = min(32, 100 / n)
        for k, i in enumerate(bay):
            y = 340 + pitch * k
            b.append(disk_box(520, y, 90, pitch - 5, m["disks"][i]))
            coords[i] = (565, round(y + (pitch - 5) / 2, 1))
    b.append('<rect x="350" y="380" width="140" height="60" rx="3"/><circle cx="420" cy="410" r="22"/><circle cx="600" cy="150" r="20"/></g>')
    cs = common_callouts(m)
    cs[0].update(px=445, py=175)
    cs[1].update(px=505, py=150)
    cs[2].update(px=470, py=110)
    if m.get("network"):
        cs.append({"side": "L", "px": 369, "py": 140, "title": "NETWORK", "sub": net_sub(m["network"])})
    cs.append({"side": "L", "px": 420, "py": 410, "title": "PSU", "sub": None})
    cs += disk_callouts(m["disks"], coords, lambda x: "L" if x < 480 else "R")
    return "".join(b), cs, 520


def draw_sbc(m):
    nv = [i for i, d in enumerate(m["disks"]) if d["kind"] == "nvme"]
    ext = [i for i, d in enumerate(m["disks"]) if d["kind"] != "nvme"]
    b = ['<g stroke="#e8f1ff" fill="none" stroke-width="2">',
         '<rect x="340" y="80" width="300" height="198" rx="10"/>',
         '<circle cx="352" cy="92" r="4"/><circle cx="557" cy="92" r="4"/><circle cx="352" cy="265" r="4"/><circle cx="557" cy="265" r="4"/>',
         '<rect x="365" y="86" width="176" height="18" stroke-width="1.4"/><path d="M369 95H537" stroke-dasharray="3 3" stroke-width="6"/>',
         '<rect x="430" y="140" width="52" height="52"/><rect x="438" y="148" width="36" height="36" stroke-width="1.2"/>',
         '<rect x="540" y="170" width="30" height="30" stroke-width="1.4"/>',
         '<rect x="598" y="92" width="52" height="40"/><rect x="598" y="136" width="52" height="40"/><rect x="598" y="182" width="52" height="54"/>',
         '<rect x="368" y="268" width="26" height="14"/><rect x="420" y="268" width="24" height="14"/><rect x="450" y="268" width="24" height="14"/>']
    n = max(len(m["ram"]["modules"]), 1)
    rh = (52 - 4 * (n - 1)) / n
    for i in range(n):
        b.append(f'<rect data-part="ram" x="496" y="{140 + (rh + 4) * i:.1f}" width="38" height="{rh:.1f}" rx="2"/>')
    coords = {}
    b.append('<rect data-part="hat" x="372" y="203" width="214" height="62" stroke-dasharray="6 5" stroke-width="1.2"/>')
    if nv:
        pitch = min(24, 48 / len(nv))
        for k, i in enumerate(nv):
            y = 210 + pitch * k
            b.append(disk_box(392, y, 150, pitch - 6 if len(nv) > 1 else 16, m["disks"][i]))
            coords[i] = (467, round(y + 8, 1))
    n = len(ext)
    if n:
        w = min(130, (340 - 16 * (n - 1)) / n)
        x0 = 490 - (n * w + (n - 1) * 16) / 2
        for k, i in enumerate(ext):
            x = x0 + k * (w + 16)
            b.append(disk_box(x, 330, w, 78, m["disks"][i], ' stroke-width="2"'))
            b.append(f'<circle cx="{x + w / 2:.1f}" cy="369" r="{min(26, w / 3):.1f}" stroke-width="1.2"/><circle cx="{x + w / 2:.1f}" cy="369" r="5"/><rect x="{x + 8:.1f}" y="396" width="8" height="4" stroke-width="1.2"/>')
            coords[i] = (round(x + w / 2, 1), 330)
    if has_part(m, "cooler"):
        b.append('<circle cx="456" cy="166" r="22" stroke-width="1.2"/><path d="M456 144V188M434 166H478" stroke-width="1"/>')
    if has_part(m, "case"):
        b.append('<rect data-part="case" x="328" y="68" width="324" height="222" rx="14" stroke-dasharray="10 6" stroke-width="1.2"/>')
    b.append("</g>")
    cs = common_callouts(m)
    cs[0].update(px=456, py=165)
    cs[1].update(px=515, py=158)
    cs[2].update(side="L", px=352, py=92, title="BOARD")
    if m.get("network"):
        cs.append({"side": "R", "px": 624, "py": 209, "title": "NETWORK", "sub": net_sub(m["network"])})
    cs += disk_callouts(m["disks"], coords, lambda x: "L" if x < 490 else "R")
    cs += part_callouts(m, SBC_ANCHORS)
    return "".join(b), cs, 450


def draw_nas(m):
    n = len(m["disks"])
    slots = max(n, 4)
    pitch = min(66, 280 / slots)
    b = ['<g stroke="#e8f1ff" fill="none" stroke-width="2">',
         '<rect x="340" y="60" width="320" height="330" rx="10"/><path d="M360 390v14M640 390v14" stroke-width="4"/>',
         '<rect x="360" y="90" width="180" height="180" stroke-width="1.6"/><rect x="350" y="110" width="12" height="40"/>',
         '<rect x="395" y="120" width="56" height="56"/><circle cx="423" cy="148" r="18"/><circle cx="423" cy="148" r="5"/>',
         '<rect x="470" y="215" width="40" height="30" stroke-width="1.2"/>',
         ram_sticks(m["ram"]["modules"], 480, 105, 80, 14, 9)]
    coords = {}
    for k in range(slots):
        y = 85 + pitch * k
        if k < n:
            b.append(disk_box(555, y, 90, pitch - 10, m["disks"][k]))
            b.append(f'<path d="M565 {y + pitch / 2 - 5:.1f}H620" stroke-width="1.2"/><circle cx="633" cy="{y + pitch / 2 - 5:.1f}" r="3"/>')
            coords[k] = (600, round(y + (pitch - 10) / 2, 1))
        else:
            b.append(f'<rect x="555" y="{y:.1f}" width="90" height="{pitch - 10:.1f}" rx="2" stroke-dasharray="5 4" stroke-width="1.2"/>')
    b.append("</g>")
    cs = common_callouts(m)
    cs[0].update(px=423, py=148)
    cs[1].update(px=484, py=140)
    cs[2].update(side="L", px=370, py=255)
    if m.get("network"):
        cs.append({"side": "L", "px": 356, "py": 130, "title": "NETWORK", "sub": net_sub(m["network"])})
    cs += disk_callouts(m["disks"], coords, lambda x: "R")
    return "".join(b), cs, 440


SHAPES = {"sbc": draw_sbc, "tower": draw_tower, "nas": draw_nas}


def draw(m, uid=None):
    if m["shape"] not in SHAPES:
        raise ValueError(f'unknown shape {m["shape"]!r} for machine {m["name"]!r}')
    m = normalize(m)
    body, cs, h0 = SHAPES[m["shape"]](m)
    h, lab = layout(cs, h0)
    return frame(uid or slug(m["name"]), h, body + lab, f'{m["name"]} drawing')
