#!/usr/bin/env python3
"""Merge a seed file (image = source of truth) into the runtime file on the
persistent volume, so a redeploy applies repo updates WITHOUT dropping
runtime/operator additions.

Usage: seed_merge.py <seed_path> <target_path> {json|md}

- json : the seed updates the target; nested dicts are unioned with the seed
         winning per key (e.g. mcp.json `mcpServers`: seed servers added/updated,
         volume-only servers preserved).
- md   : section merge by level-2 headings ('## '). The preamble and every
         section the seed defines come from the seed (doctrine refreshed);
         sections present only in the target are preserved at the end.

Stdlib only. Idempotent. If the target is missing/unpar. the seed wins wholesale.
"""

import json
import sys


def merge_json(seed_path: str, target_path: str) -> None:
    with open(seed_path, encoding="utf-8") as f:
        seed = json.load(f)
    try:
        with open(target_path, encoding="utf-8") as f:
            target = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        target = {}

    out = dict(target)
    for key, val in seed.items():
        if isinstance(val, dict) and isinstance(target.get(key), dict):
            merged = dict(target[key])
            merged.update(val)          # seed wins per sub-key, existing kept
            out[key] = merged
        else:
            out[key] = val

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _sections(text: str):
    """Split into (preamble, [(heading_line, body), ...]) on level-2 headings."""
    pre, secs, head, cur = [], [], None, []
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            if head is None:
                pre = cur
            else:
                secs.append((head, "".join(cur)))
            head, cur = line, []
        else:
            cur.append(line)
    if head is None:
        pre = cur
    else:
        secs.append((head, "".join(cur)))
    return "".join(pre), secs


def merge_md(seed_path: str, target_path: str) -> None:
    with open(seed_path, encoding="utf-8") as f:
        seed = f.read()
    try:
        with open(target_path, encoding="utf-8") as f:
            target = f.read()
    except FileNotFoundError:
        target = ""

    seed_pre, seed_secs = _sections(seed)
    _, target_secs = _sections(target)
    seed_heads = {h.strip() for h, _ in seed_secs}

    out = [seed_pre]
    for head, body in seed_secs:
        out.append(head + body)

    extra = [(h, b) for h, b in target_secs if h.strip() not in seed_heads]
    if extra:
        out.append("\n<!-- Sections runtime conservées (absentes du seed) -->\n")
        for head, body in extra:
            out.append(head + body)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write("".join(out))


def main(argv) -> int:
    if len(argv) != 4 or argv[3] not in ("json", "md"):
        print(__doc__, file=sys.stderr)
        return 2
    seed, target, kind = argv[1], argv[2], argv[3]
    (merge_json if kind == "json" else merge_md)(seed, target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
