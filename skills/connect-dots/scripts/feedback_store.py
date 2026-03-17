#!/usr/bin/env python3
"""Deterministic feedback capture for connect-dots usefulness tuning."""

from __future__ import annotations

import argparse
from pathlib import Path

from _lib import atomic_write_json, load_json, now_iso, validate_or_die


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--scope", required=True)
    ap.add_argument("--signal-key", required=True)
    ap.add_argument("--verdict", required=True, choices=["useful", "not-useful", "confirmed", "denied"])
    ap.add_argument("--note", default="")
    ap.add_argument(
        "--schema",
        default=str(Path(__file__).resolve().parent.parent / "references" / "feedback.schema.json"),
    )
    args = ap.parse_args()

    store_path = Path(args.store)
    data = load_json(store_path, default={"feedback": []})
    items = list(data.get("feedback") or [])
    item = {
        "id": f"fb-{args.run_id}-{args.scope}-{args.signal_key}-{args.verdict}",
        "run_id": args.run_id,
        "scope": args.scope,
        "signal_key": args.signal_key,
        "verdict": args.verdict,
        "note": args.note,
        "created_at": now_iso(),
    }
    if not any(isinstance(x, dict) and x.get("id") == item["id"] for x in items):
        items.append(item)
    data["feedback"] = items
    validate_or_die(data, Path(args.schema), label=f"feedback store ({store_path})")
    atomic_write_json(store_path, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
