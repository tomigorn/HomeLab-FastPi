# Builds one guide per permission level: build.sh sets WIKI_GATES (groups that hide content) and WIKI_GROUPS (the ones this build has).
import os
import re
from pathlib import Path

import yaml

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
OPEN = re.compile(r"^\s*<!--\s*only:\s*(\S+)\s*-->\s*$")
CLOSE = re.compile(r"^\s*<!--\s*/only\s*-->\s*$")

_hidden = set()


def page_groups(text):
    m = FRONT_MATTER.match(text)
    if not m:
        return []
    value = (yaml.safe_load(m.group(1)) or {}).get("groups") or []
    return [value] if isinstance(value, str) else list(value)


def _allows(group, have, gates):
    name = group.lstrip("!")
    if name not in gates:
        raise ValueError(f"unknown group '{name}', known: {sorted(gates)}")
    return (name in have) != group.startswith("!")


def visible(required, have, gates):
    return all(_allows(g, have, gates) for g in required)


def filter_blocks(markdown, have, gates):
    out, keep, inside = [], True, False
    for n, line in enumerate(markdown.splitlines(keepends=True), 1):
        if m := OPEN.match(line):
            if inside:
                raise ValueError(f"line {n}: nested only block")
            inside, keep = True, _allows(m.group(1), have, gates)
        elif CLOSE.match(line):
            if not inside:
                raise ValueError(f"line {n}: /only without only")
            inside, keep = False, True
        elif keep:
            out.append(line)
    if inside:
        raise ValueError("only block not closed")
    return "".join(out)


def prune_nav(nav, hidden):
    if nav is None:
        return None
    pruned = []
    for item in nav:
        if isinstance(item, dict):
            (title, value), = item.items()
            if isinstance(value, list):
                value = prune_nav(value, hidden)
                if value:
                    pruned.append({title: value})
            elif value not in hidden:
                pruned.append(item)
        elif item not in hidden:
            pruned.append(item)
    return pruned


def _env(name):
    value = os.environ.get(name)
    if value is None:
        raise ValueError(f"{name} not set: build with build.sh")
    return {g for g in value.split(",") if g}


def on_config(config):
    gates, have = _env("WIKI_GATES"), _env("WIKI_GROUPS")
    docs = Path(config["docs_dir"])
    _hidden.clear()
    for page in docs.rglob("*.md"):
        if not visible(page_groups(page.read_text()), have, gates):
            _hidden.add(page.relative_to(docs).as_posix())
    config["nav"] = prune_nav(config["nav"], _hidden)
    return config


def on_files(files, config):
    for f in list(files):
        if f.src_uri in _hidden:
            files.remove(f)
    return files


def on_page_markdown(markdown, page, config, files):
    return filter_blocks(markdown, _env("WIKI_GROUPS"), _env("WIKI_GATES"))
