#!/usr/bin/env python3
"""Produce a bounded, calm changelog between two model snapshots.

Output is meant to feed section 5 of the "show assumptions" view.

Usage:
  model_diff.py --prev <prev.json> --cur <cur.json>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _lib import load_json


def _index(model):
    idx = {}
    if not model:
        return idx
    for section in (
        "confirmed_facts",
        "hypotheses",
        "stale_items",
        "open_loops",
        "candidate_moves",
    ):
        for it in model.get(section) or []:
            if isinstance(it, dict) and it.get("id"):
                idx[it["id"]] = (section, it)
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev", required=True)
    ap.add_argument("--cur", required=True)
    ap.add_argument("--cap", type=int, default=10)
    args = ap.parse_args()

    prev = load_json(Path(args.prev), default={})
    cur = load_json(Path(args.cur), default={})

    p = _index(prev)
    c = _index(cur)

    added, updated, retracted = [], [], []

    for cid, (_, it) in c.items():
        if cid not in p:
            added.append(f"+ {it.get('statement') or it.get('fact') or cid}")
            continue
        _, pit = p[cid]
        if it.get("status") == "retracted" and pit.get("status") != "retracted":
            retracted.append(f"- {it.get('statement') or it.get('fact') or cid}")
            continue
        changed = False
        for k in ("statement", "value", "confidence", "status", "expires_at"):
            if it.get(k) != pit.get(k):
                changed = True
                break
        if changed:
            updated.append(f"~ {it.get('statement') or it.get('fact') or cid}")

    # items that disappeared entirely are treated as retracted for audit
    for pid, (_, pit) in p.items():
        if pid not in c:
            retracted.append(f"- {pit.get('statement') or pit.get('fact') or pid}")

    def cap(xs):
        return xs[: max(0, args.cap)]

    for line in cap(added):
        print(line)
    for line in cap(updated):
        print(line)
    for line in cap(retracted):
        print(line)

    if not (added or updated or retracted):
        print("(no material changes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
