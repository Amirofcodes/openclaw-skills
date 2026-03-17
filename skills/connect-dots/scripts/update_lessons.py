#!/usr/bin/env python3
"""Deterministically upsert connect-dots lessons from a run record.

Rule:
- one successful run creates/refreshes a pending lesson pattern
- two distinct successful source runs promote it to active
- no curated-memory writes; only internal insights store
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from _lib import atomic_write_json, load_json, now_iso, validate_or_die


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def _load_store(path: Path) -> Dict[str, Any]:
    return load_json(path, default={"lessons": []})


def _lesson_id(scope_run: Dict[str, Any], mode: str) -> str:
    return "lesson-" + _slug(
        f"{mode}-{scope_run['scope']}-{scope_run['lane']}-{scope_run['blast_radius_estimate']['class']}"
    )


def _pattern(scope_run: Dict[str, Any], mode: str) -> str:
    scope = scope_run["scope"]
    lane = scope_run["lane"]
    blast = scope_run["blast_radius_estimate"]["class"]
    return (
        f"When a {mode} connect-dots run for {scope} succeeds with validated artifacts under lane "
        f"{lane} and blast radius {blast}, keep the workflow quiet and reuse the same disciplined path."
    )


def _eligible(scope_run: Dict[str, Any]) -> bool:
    v = scope_run.get("validation") or {}
    return scope_run.get("status") == "success" and v.get("schema_ok") and v.get("citations_ok") and v.get("policy_ok")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="Path to run.json")
    ap.add_argument("--store", required=True, help="Path to lessons.json")
    ap.add_argument(
        "--schema",
        default=str(Path(__file__).resolve().parent.parent / "references" / "lessons.schema.json"),
    )
    args = ap.parse_args()

    run_path = Path(args.run)
    store_path = Path(args.store)
    run_data = load_json(run_path, default=None)
    if not run_data:
        raise SystemExit(f"run record missing/empty: {run_path}")

    store = _load_store(store_path)
    lessons: List[Dict[str, Any]] = list(store.get("lessons") or [])
    lesson_by_id = {item.get("id"): item for item in lessons if isinstance(item, dict) and item.get("id")}

    changed = False
    mode = run_data.get("mode") or "nightly"
    run_id = run_data.get("run_id") or "unknown"

    for scope_run in run_data.get("scopes") or []:
        if not isinstance(scope_run, dict) or not _eligible(scope_run):
            continue
        lid = _lesson_id(scope_run, mode)
        existing = lesson_by_id.get(lid)
        sigs = list(dict.fromkeys(scope_run.get("signals") or []))
        evidence_strength = float((scope_run.get("hypothesis") or {}).get("confidence") or 0.0)

        if existing is None:
            item = {
                "id": lid,
                "status": "pending",
                "scope": [scope_run["scope"]],
                "pattern": _pattern(scope_run, mode),
                "signals": sigs,
                "evidence_strength": evidence_strength,
                "applies_when": [
                    f"lane={scope_run['lane']}",
                    f"blast_radius={scope_run['blast_radius_estimate']['class']}",
                    f"mode={mode}",
                ],
                "avoid_when": ["validation_failed", "policy_violation"],
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "source_runs": [run_id],
            }
            lessons.append(item)
            lesson_by_id[lid] = item
            changed = True
            continue

        runs = list(dict.fromkeys((existing.get("source_runs") or []) + [run_id]))
        if runs != existing.get("source_runs"):
            existing["source_runs"] = runs
            changed = True
        existing["updated_at"] = now_iso()
        existing["signals"] = list(dict.fromkeys((existing.get("signals") or []) + sigs))
        existing["evidence_strength"] = max(float(existing.get("evidence_strength") or 0.0), evidence_strength)
        if len(existing["source_runs"]) >= 2:
            existing["status"] = "active"
        changed = True

    store["lessons"] = lessons
    validate_or_die(store, Path(args.schema), label=f"lessons store ({store_path})")
    if changed or not store_path.exists():
        atomic_write_json(store_path, store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
