#!/usr/bin/env python3
"""Apply consent mutations to a connect-dots model.json.

Supported ops (fail closed on invalid input):
- don't store: add a do_not_store pattern
- forget: retract an item by id (or substring match)
- confirm: promote a hypothesis to confirmed_facts (preference/fact)
- deny: retract an item by id

Usage:
  consent_mutations.py --model model.json --op dont-store --pattern "secret"
  consent_mutations.py --model model.json --op forget --id <item-id>
  consent_mutations.py --model model.json --op forget --match "some text"
  consent_mutations.py --model model.json --op confirm --id <hyp-id> [--fact "..." --value "..."]
  consent_mutations.py --model model.json --op deny --id <item-id>

By default updates the file in-place (atomic).
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from _lib import (
    atomic_write_json,
    drop_retracted,
    ensure_model_skeleton,
    index_by_id,
    load_json,
    now_iso,
    validate_or_die,
)


def _find_item(model, item_id: str):
    for section in ("hypotheses", "stale_items", "open_loops", "candidate_moves", "confirmed_facts"):
        for it in model.get(section) or []:
            if isinstance(it, dict) and it.get("id") == item_id:
                return section, it
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument(
        "--schema",
        default=str(Path(__file__).resolve().parent.parent / "references" / "model.schema.json"),
    )
    ap.add_argument("--op", required=True, choices=["dont-store", "forget", "confirm", "deny"])
    ap.add_argument("--pattern")
    ap.add_argument("--domain")
    ap.add_argument("--note")
    ap.add_argument("--id")
    ap.add_argument("--match")
    ap.add_argument("--fact")
    ap.add_argument("--value")
    args = ap.parse_args()

    model_path = Path(args.model)
    model = load_json(model_path, default=None)
    if not model:
        raise SystemExit(f"model not found or empty: {model_path}")

    out = deepcopy(model)
    out["updatedAt"] = now_iso()

    if args.op == "dont-store":
        if not args.pattern:
            raise SystemExit("dont-store requires --pattern")
        out.setdefault("do_not_store", [])
        rule = {
            "pattern": args.pattern,
            "created_at": now_iso(),
        }
        if args.domain:
            rule["domain"] = args.domain
        if args.note:
            rule["note"] = args.note
        out["do_not_store"].append(rule)

    elif args.op == "deny":
        if not args.id:
            raise SystemExit("deny requires --id")
        sec, it = _find_item(out, args.id)
        if not it:
            raise SystemExit(f"id not found: {args.id}")
        it["status"] = "retracted"

    elif args.op == "forget":
        if not (args.id or args.match):
            raise SystemExit("forget requires --id or --match")
        if args.id:
            sec, it = _find_item(out, args.id)
            if not it:
                raise SystemExit(f"id not found: {args.id}")
            it["status"] = "retracted"
        else:
            needle = args.match.lower()
            hit = False
            for sec in ("hypotheses", "stale_items", "open_loops", "candidate_moves", "confirmed_facts"):
                for it in out.get(sec) or []:
                    if not isinstance(it, dict):
                        continue
                    s = (it.get("statement") or it.get("fact") or "").lower()
                    if needle in s:
                        it["status"] = "retracted"
                        hit = True
            if not hit:
                raise SystemExit(f"no matches for: {args.match}")

    elif args.op == "confirm":
        if not args.id:
            raise SystemExit("confirm requires --id")
        sec, it = _find_item(out, args.id)
        if not it:
            raise SystemExit(f"id not found: {args.id}")
        # Promote to confirmed_facts.
        fact = args.fact or it.get("statement")
        if not fact:
            raise SystemExit("confirm requires --fact or statement")
        value = args.value
        # Remove from hypotheses-like section.
        for s in ("hypotheses", "stale_items", "open_loops", "candidate_moves"):
            out[s] = [x for x in (out.get(s) or []) if not (isinstance(x, dict) and x.get("id") == args.id)]
        out.setdefault("confirmed_facts", [])
        out["confirmed_facts"].append(
            {
                "id": args.id,
                "fact": fact,
                "value": value,
                "domain": it.get("domain", ""),
                "confidence": 0.99,
                "first_seen": it.get("first_seen") or now_iso(),
                "last_seen": now_iso(),
                "last_confirmed": now_iso(),
                "expires_at": it.get("expires_at") or "9999-12-31T00:00:00+00:00",
                "status": "active",
                "evidence": it.get("evidence") or [],
            }
        )

    # Drop retracted from active lists but keep them in stale_items for audit.
    # (Renderer should also hide retracted.)
    out["hypotheses"] = drop_retracted(out.get("hypotheses") or [])
    out["open_loops"] = drop_retracted(out.get("open_loops") or [])
    out["candidate_moves"] = drop_retracted(out.get("candidate_moves") or [])

    # Validate
    validate_or_die(out, Path(args.schema), label=f"model ({model_path})")

    atomic_write_json(model_path, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
