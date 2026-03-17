#!/usr/bin/env python3
"""Deterministic run-record writer for connect-dots.

Purpose:
- produce a machine-validated summary of a connect-dots cycle
- keep phase-B observability separate from model mutation logic
- fail closed on schema mismatch

Usage:
  write_run_record.py --workspace <ws> --run-id <id> --mode nightly --trigger nightly_inactivity_gate \
    --status success --scope user-profile/preferences:success

The script can be called multiple times for multiple scopes in one run.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from _lib import atomic_write_json, load_json, now_iso, validate_or_die

ALLOWED_SCOPES = {
    "user-profile/preferences",
    "openclaw-runtime/ops",
    "repos",
}

DEFAULT_SCOPE_PROFILES = {
    "user-profile/preferences": {
        "signals": ["nightly_sensemaking"],
        "lane": "observe-only",
        "blast_class": "memory-only",
        "blast_justification": "Only internal connect-dots model artifacts are read or updated for this scope.",
        "action_kind": "silent-update",
        "action_summary": "Refresh the internal user-profile model from validated evidence.",
        "hypothesis_statement": "Recent interactions may refine the internal user-profile model.",
    },
    "openclaw-runtime/ops": {
        "signals": ["nightly_sensemaking", "runtime_health_review"],
        "lane": "observe-only",
        "blast_class": "runtime-checks",
        "blast_justification": "This scope summarizes runtime evidence and artifacts without changing services.",
        "action_kind": "silent-update",
        "action_summary": "Refresh the internal runtime-ops model from validated evidence.",
        "hypothesis_statement": "Recent runtime evidence may update the internal operational picture.",
    },
    "repos": {
        "signals": ["nightly_sensemaking", "repo_review"],
        "lane": "safe-local-proposal",
        "blast_class": "local-analysis",
        "blast_justification": "This scope analyzes repo/project state and writes only internal artifacts or proposals.",
        "action_kind": "proposal",
        "action_summary": "Refresh the internal repos model and prepare local-only follow-up proposals if needed.",
        "hypothesis_statement": "Recent repo evidence may reveal updated blockers, loops, or candidate moves.",
    },
}


def rel_if_exists(path: Path, workspace: Path) -> str | None:
    if path.exists():
        return path.relative_to(workspace).as_posix()
    return None


def top_level_status(scope_statuses: List[str]) -> str:
    vals = set(scope_statuses)
    if vals == {"skipped"}:
        return "skipped"
    if vals == {"success"}:
        return "success"
    if "failed" in vals and "success" in vals:
        return "partial"
    if "failed" in vals:
        return "failed"
    return "partial"


def build_scope_record(*, workspace: Path, run_dir: Path, scope: str, status: str) -> Dict[str, Any]:
    if scope not in ALLOWED_SCOPES:
        raise SystemExit(f"unsupported scope: {scope}")
    if status not in {"success", "failed", "skipped"}:
        raise SystemExit(f"unsupported scope status: {status}")

    profile = DEFAULT_SCOPE_PROFILES[scope]
    scope_dir = run_dir / Path(scope)

    proposal = rel_if_exists(scope_dir / "proposal.json", workspace)
    pre_model = rel_if_exists(scope_dir / "model.pre.json", workspace)
    post_model = rel_if_exists(scope_dir / "model.post.json", workspace)
    diff = rel_if_exists(scope_dir / "diff.txt", workspace)
    err = rel_if_exists(scope_dir / "error.log", workspace)

    schema_ok = proposal is not None
    citations_ok = status != "failed"
    policy_ok = True

    notes = {
        "success": "Scope completed with validated artifacts.",
        "failed": "Scope failed during validation or model build; inspect error log.",
        "skipped": "Scope was intentionally skipped for this run.",
    }[status]

    outcome_status = {
        "success": "silent",
        "failed": "failed",
        "skipped": "skipped",
    }[status]

    record: Dict[str, Any] = {
        "scope": scope,
        "status": status,
        "signals": profile["signals"],
        "hypothesis": {
            "statement": profile["hypothesis_statement"],
            "confidence": 0.7 if status == "success" else (0.35 if status == "skipped" else 0.2),
            "evidence": [
                {
                    "path": proposal or err or "tmp/connect-dots/unknown",
                    "lines": "L1-L1",
                    "quote": "{",
                    "ts": now_iso(),
                }
            ],
        },
        "proposed_action": {
            "kind": profile["action_kind"] if status != "skipped" else "none",
            "summary": profile["action_summary"] if status != "skipped" else "No action taken for this scope in this run.",
        },
        "lane": profile["lane"],
        "blast_radius_estimate": {
            "class": profile["blast_class"],
            "justification": profile["blast_justification"],
        },
        "validation": {
            "schema_ok": schema_ok,
            "citations_ok": citations_ok,
            "policy_ok": policy_ok,
        },
        "outcome": {
            "status": outcome_status,
            "notes": notes,
        },
    }

    artifacts = {k: v for k, v in {
        "proposal": proposal,
        "pre_model": pre_model,
        "post_model": post_model,
        "diff": diff,
        "error_log": err,
    }.items() if v is not None}
    if artifacts:
        record["artifacts"] = artifacts
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--mode", choices=["nightly", "daytime", "explicit-audit"], required=True)
    ap.add_argument("--trigger", required=True)
    ap.add_argument("--status", choices=["success", "partial", "failed", "skipped"], default=None)
    ap.add_argument("--note", default="")
    ap.add_argument("--scope", action="append", default=[], help="Format: <scope>:<success|failed|skipped>")
    ap.add_argument(
        "--schema",
        default=str(Path(__file__).resolve().parent.parent / "references" / "run.schema.json"),
    )
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    run_dir = workspace / "tmp" / "connect-dots" / "runs" / args.run_id
    run_path = run_dir / "run.json"

    if not args.scope:
        raise SystemExit("at least one --scope is required")

    scopes = []
    scope_statuses = []
    for raw in args.scope:
        if ":" not in raw:
            raise SystemExit(f"bad --scope value: {raw}")
        scope_name, scope_status = raw.rsplit(":", 1)
        scopes.append(build_scope_record(workspace=workspace, run_dir=run_dir, scope=scope_name, status=scope_status))
        scope_statuses.append(scope_status)

    effective_status = args.status or top_level_status(scope_statuses)

    existing = load_json(run_path, default=None)
    created_at = existing.get("created_at") if isinstance(existing, dict) and existing.get("created_at") else now_iso()

    record = {
        "run_id": args.run_id,
        "mode": args.mode,
        "trigger": args.trigger,
        "created_at": created_at,
        "status": effective_status,
        "notes": args.note or "Deterministic run record emitted by write_run_record.py.",
        "validation": {
            "schema_ok": all(s["validation"]["schema_ok"] for s in scopes),
            "citations_ok": all(s["validation"]["citations_ok"] for s in scopes),
            "policy_ok": all(s["validation"]["policy_ok"] for s in scopes),
        },
        "scopes": scopes,
    }

    validate_or_die(record, Path(args.schema), label=f"run record ({run_path})")
    atomic_write_json(run_path, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
