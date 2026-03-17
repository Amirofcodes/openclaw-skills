#!/usr/bin/env python3
"""Deterministically upsert connect-dots anti-patterns from a run record."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

from _lib import atomic_write_json, load_json, now_iso, validate_or_die


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def _load_store(path: Path) -> Dict[str, Any]:
    return load_json(path, default={"anti_patterns": []})


def _classify(scope_run: Dict[str, Any]) -> Tuple[str, str, str, List[str]] | None:
    v = scope_run.get("validation") or {}
    scope = scope_run.get("scope") or "unknown"
    status = scope_run.get("status")
    if status != "failed" and v.get("schema_ok") and v.get("citations_ok") and v.get("policy_ok"):
        return None

    if not v.get("schema_ok"):
        return (
            f"anti-schema-failure-{_slug(scope)}",
            f"Schema failure in {scope} should not be treated as a reusable successful path.",
            "high",
            ["schema_failure", scope],
        )
    if not v.get("citations_ok"):
        return (
            f"anti-citation-failure-{_slug(scope)}",
            f"Citation validation failure in {scope} means the run must fail closed and avoid surfacing conclusions.",
            "high",
            ["citation_failure", scope],
        )
    if not v.get("policy_ok"):
        return (
            f"anti-policy-failure-{_slug(scope)}",
            f"Policy violation in {scope} must stop the recommendation path before any surfacing or writes.",
            "high",
            ["policy_failure", scope],
        )
    return (
        f"anti-run-failure-{_slug(scope)}",
        f"A failed {scope} run should be treated as an anti-pattern until the failure mode is corrected and later contradicted by successful runs.",
        "medium",
        ["run_failure", scope],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="Path to run.json")
    ap.add_argument("--store", required=True, help="Path to anti-patterns.json")
    ap.add_argument(
        "--schema",
        default=str(Path(__file__).resolve().parent.parent / "references" / "anti-patterns.schema.json"),
    )
    args = ap.parse_args()

    run_path = Path(args.run)
    store_path = Path(args.store)
    run_data = load_json(run_path, default=None)
    if not run_data:
        raise SystemExit(f"run record missing/empty: {run_path}")

    store = _load_store(store_path)
    items: List[Dict[str, Any]] = list(store.get("anti_patterns") or [])
    by_id = {item.get("id"): item for item in items if isinstance(item, dict) and item.get("id")}
    run_id = run_data.get("run_id") or "unknown"
    changed = False

    for scope_run in run_data.get("scopes") or []:
        if not isinstance(scope_run, dict):
            continue
        classified = _classify(scope_run)
        if classified is None:
            continue
        ap_id, pattern, severity, trigger_signals = classified
        existing = by_id.get(ap_id)
        if existing is None:
            item = {
                "id": ap_id,
                "scope": [scope_run.get("scope") or "unknown"],
                "pattern": pattern,
                "trigger_signals": trigger_signals,
                "severity": severity,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "source_runs": [run_id],
            }
            items.append(item)
            by_id[ap_id] = item
            changed = True
            continue
        existing["updated_at"] = now_iso()
        existing["severity"] = severity if severity == "high" else existing.get("severity") or severity
        existing["trigger_signals"] = list(dict.fromkeys((existing.get("trigger_signals") or []) + trigger_signals))
        existing["source_runs"] = list(dict.fromkeys((existing.get("source_runs") or []) + [run_id]))
        changed = True

    store["anti_patterns"] = items
    validate_or_die(store, Path(args.schema), label=f"anti-patterns store ({store_path})")
    if changed or not store_path.exists():
        atomic_write_json(store_path, store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
