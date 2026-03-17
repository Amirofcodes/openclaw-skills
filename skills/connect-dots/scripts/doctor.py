#!/usr/bin/env python3
"""connect-dots doctor — audit stale lessons, anti-pattern collisions, suppressed patterns, and store health.

Read-only diagnostic script.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from _lib import load_json, parse_iso
from score_recommendation import score_scope


def _now():
    return datetime.now(timezone.utc).astimezone()


def _days_old(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        dt = parse_iso(ts)
        return max(0, int(round((_now() - dt).total_seconds() / 86400.0)))
    except Exception:
        return None


def _load_runs(runs_root: Path, limit: int) -> List[Dict[str, Any]]:
    run_files = sorted(runs_root.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in run_files[: max(0, limit)]:
        data = load_json(path, default=None)
        if isinstance(data, dict):
            data["_path"] = path
            out.append(data)
    return out


def _signal_key(scope_run: Dict[str, Any]) -> str:
    scope = scope_run.get("scope") or "unknown"
    lane = scope_run.get("lane") or "unknown"
    action = ((scope_run.get("proposed_action") or {}).get("kind")) or "unknown"
    signals = ",".join(scope_run.get("signals") or [])
    return f"{scope}|{lane}|{action}|{signals}"


def build_report(*, runs: List[Dict[str, Any]], lessons: Dict[str, Any], anti: Dict[str, Any], feedback: Dict[str, Any], stale_days: int) -> Dict[str, Any]:
    lessons_list = [x for x in (lessons.get("lessons") or []) if isinstance(x, dict)]
    anti_list = [x for x in (anti.get("anti_patterns") or []) if isinstance(x, dict)]
    feedback_list = [x for x in (feedback.get("feedback") or []) if isinstance(x, dict)]

    stale_lessons = []
    for item in lessons_list:
        age = _days_old(item.get("updated_at"))
        if age is not None and age >= stale_days:
            stale_lessons.append({
                "id": item.get("id"),
                "status": item.get("status"),
                "age_days": age,
                "scope": item.get("scope") or [],
            })

    anti_counter = Counter()
    for item in anti_list:
        for sig in item.get("trigger_signals") or []:
            anti_counter[sig] += 1
    anti_collisions = [{"signal": sig, "count": count} for sig, count in anti_counter.items() if count >= 2]

    suppressed_patterns = []
    for run in runs:
        for scope_run in run.get("scopes") or []:
            if not isinstance(scope_run, dict):
                continue
            decision = score_scope(scope_run, lessons, anti, feedback)
            if decision.get("suppressed"):
                suppressed_patterns.append({
                    "run_id": run.get("run_id"),
                    "scope": scope_run.get("scope"),
                    "signal_key": decision.get("signal_key"),
                    "reason": decision.get("reason"),
                    "score": decision.get("score"),
                })

    feedback_counter = Counter()
    for item in feedback_list:
        feedback_counter[item.get("verdict") or "unknown"] += 1

    recent_failures = []
    for run in runs:
        if run.get("status") in {"failed", "partial"}:
            recent_failures.append({
                "run_id": run.get("run_id"),
                "status": run.get("status"),
                "created_at": run.get("created_at"),
            })

    health = {
        "lessons_total": len(lessons_list),
        "lessons_pending": sum(1 for x in lessons_list if x.get("status") == "pending"),
        "lessons_active": sum(1 for x in lessons_list if x.get("status") == "active"),
        "anti_patterns_total": len(anti_list),
        "feedback_total": len(feedback_list),
        "runs_scanned": len(runs),
    }

    return {
        "health": health,
        "stale_lessons": stale_lessons,
        "anti_pattern_collisions": anti_collisions,
        "suppressed_patterns": suppressed_patterns,
        "feedback_summary": dict(feedback_counter),
        "recent_failures": recent_failures,
    }


def render_text(report: Dict[str, Any]) -> str:
    lines = []
    h = report["health"]
    lines.append("connect-dots doctor")
    lines.append(f"- lessons: {h['lessons_total']} total ({h['lessons_active']} active / {h['lessons_pending']} pending)")
    lines.append(f"- anti-patterns: {h['anti_patterns_total']}")
    lines.append(f"- feedback items: {h['feedback_total']}")
    lines.append(f"- runs scanned: {h['runs_scanned']}")

    lines.append("\nStale lessons")
    if report["stale_lessons"]:
        for item in report["stale_lessons"][:10]:
            lines.append(f"- {item['id']} · {item['status']} · {item['age_days']}d old")
    else:
        lines.append("- none")

    lines.append("\nAnti-pattern collisions")
    if report["anti_pattern_collisions"]:
        for item in report["anti_pattern_collisions"][:10]:
            lines.append(f"- {item['signal']} · {item['count']} hits")
    else:
        lines.append("- none")

    lines.append("\nSuppressed patterns")
    if report["suppressed_patterns"]:
        for item in report["suppressed_patterns"][:10]:
            lines.append(f"- {item['run_id']} · {item['scope']} · {item['reason']} · score={item['score']}")
    else:
        lines.append("- none")

    lines.append("\nRecent failures")
    if report["recent_failures"]:
        for item in report["recent_failures"][:10]:
            lines.append(f"- {item['run_id']} · {item['status']} · {item['created_at']}")
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--runs-limit", type=int, default=20)
    ap.add_argument("--stale-days", type=int, default=14)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    runs = _load_runs(ws / "tmp" / "connect-dots" / "runs", args.runs_limit)
    insights = ws / "memory" / "internal" / "connect-dots" / "insights"
    lessons = load_json(insights / "lessons.json", default={"lessons": []})
    anti = load_json(insights / "anti-patterns.json", default={"anti_patterns": []})
    feedback = load_json(insights / "feedback.json", default={"feedback": []})

    report = build_report(runs=runs, lessons=lessons, anti=anti, feedback=feedback, stale_days=args.stale_days)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
