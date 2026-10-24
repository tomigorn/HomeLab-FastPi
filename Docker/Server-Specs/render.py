import copy
import html
import json
import os

import drawings

HERE = os.path.dirname(os.path.abspath(__file__))
e = html.escape

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0f2647;color:#e8f1ff;font-family:ui-monospace,Menlo,Consolas,monospace}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.4rem;margin:0 0 1.2rem;letter-spacing:.04em}
.card{background:#173d73;border:2px solid #3d6db3;border-radius:6px;margin:0 0 22px;overflow:hidden}
.head{padding:12px 16px;border-bottom:1px solid #2f5b9a}
.head h2{margin:0;font-size:1.15rem;letter-spacing:.06em;text-transform:uppercase}
.head .meta{color:#b9d4ff;font-size:.85rem;margin-top:.25rem}
.art{display:block;width:100%;height:auto}
.art a{cursor:pointer}
dl.spec{display:none;margin:0;padding:12px 16px 16px;grid-template-columns:auto 1fr;gap:6px 14px;font-size:.9rem}
dl.spec dt{color:#9cc3ff}
dl.spec dd{margin:0;overflow-wrap:anywhere}
@media (max-width:720px){
.art .sub{display:none}
.art .t{font-size:30px}
dl.spec{display:grid}
}
"""


def spec_rows(m):
    c = m["cpu"]
    ram = drawings.ram_sub(m["ram"])
    rows = [("CPU", drawings.cpu_sub(c)), ("RAM", ram), ("Board", drawings.board_sub(m))]
    for d in m["disks"]:
        rows.append(("NVMe" if d["kind"] == "nvme" else drawings.KIND.get(d["kind"], d["kind"]), f'{d["model"]} · {d["size"]}'))
    if m.get("network"):
        rows.append(("Network", m["network"]))
    rows += [(p["part"], p["model"]) for p in m.get("parts", [])]
    return rows


def merge_parts(specs, parts):
    out = copy.deepcopy(specs)
    for m in out["machines"]:
        if m["name"] in parts:
            m["parts"] = parts[m["name"]]
    return out


def card(m, uid):
    notes = " (from notes)" if m.get("source") == "notes" else ""
    meta = f'{e(m["role"])} · {e(m["os"])} · as of {e(m["collected"])}{notes}'
    dl = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in spec_rows(m))
    return (f'<section class="card" id="{e(m["name"])}"><div class="head"><h2>{e(m["name"])}</h2><div class="meta">{meta}</div></div>'
            f'{drawings.draw(m, uid)}<dl class="spec">{dl}</dl></section>')


def render(specs):
    cards = "".join(card(m, f"m{i}") for i, m in enumerate(specs["machines"]))
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Holy Grail · Machines</title><style>{CSS}</style></head><body><main><h1>Holy Grail · Machines</h1>{cards}</main></body></html>\n')


def main():
    with open(os.path.join(HERE, "data", "specs.json"), encoding="utf-8") as f:
        specs = json.load(f)
    parts_file = os.path.join(HERE, "parts.json")
    if os.path.exists(parts_file):
        with open(parts_file, encoding="utf-8") as f:
            specs = merge_parts(specs, json.load(f))
    out = os.path.join(HERE, "www", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(specs))
    os.chmod(out, 0o644)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
