#!/usr/bin/env python3
"""Score and suppress connect-dots recommendation patterns deterministically.

Inputs:
- run record
- optional lessons store
- optional anti-patterns store
- optional feedback store

Output:
- JSON decision with score and suppression flag
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from _lib import load_json


def _signal_key(scope_run: Dict[str, Any]) -> str:
    scope = scope_run.get("scope") or "unknown"
    lane = scope_run.get("lane") or "unknown"
    action = ((scope_run.get("proposed_action") or {}).get("kind")) or "unknown"
    signals = ",".join(scope_run.get("signals") or [])
    return f"{scope}|{lane}|{action}|{signals}"


def _count_feedback(feedback: Dict[str, Any], signal_key: str) -> Dict[str, int]:
    counts = {"useful": 0, "not-useful": 0, "confirmed": 0, "denied": 0}
    for item in feedback.get("feedback") or []:
        if isinstance(item, dict) and item.get("signal_key") == signal_key and item.get("verdict") in counts:
            counts[item["verdict"]] += 1
    return counts


def _matching_lessons(lessons: Dict[str, Any], scope: str, signals: list[str]) -> int:
    sigset = set(signals or [])
    c = 0
    for item in lessons.get("lessons") or []:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "active":
            continue
        if scope not in (item.get("scope") or []):
            continue
        if sigset.intersection(set(item.get("signals") or [])):
            c += 1
    return c


def _matching_anti(anti: Dict[str, Any], scope: str, signals: list[str]) -> int:
    sigset = set(signals or [])
    c = 0
    for item in anti.get("anti_patterns") or []:
        if not isinstance(item, dict):
            continue
        if scope not in (item.get("scope") or []):
            continue
        if sigset.intersection(set(item.get("trigger_signals") or [])):
            c += 1
    return c


def score_scope(scope_run: Dict[str, Any], lessons: Dict[str, Any], anti: Dict[str, Any], feedback: Dict[str, Any]) -> Dict[str, Any]:
    signals = list(scope_run.get("signals") or [])
    scope = scope_run.get("scope") or "unknown"
    base = float((scope_run.get("hypothesis") or {}).get("confidence") or 0.0)
    signal_key = _signal_key(scope_run)
    fb = _count_feedback(feedback, signal_key)
    lesson_hits = _matching_lessons(lessons, scope, signals)
    anti_hits = _matching_anti(anti, scope, signals)

    score = base
    score += min(0.15, lesson_hits * 0.05)
    score -= min(0.25, anti_hits * 0.08)
    score += min(0.20, fb["useful"] * 0.05)
    score += min(0.20, fb["confirmed"] * 0.06)
    score -= min(0.35, fb["not-useful"] * 0.10)
    score -= min(0.35, fb["denied"] * 0.12)
    if fb["not-useful"] >= 2 or fb["denied"] >= 2:
        suppressed = True
        reason = "repeated_negative_feedback"
    elif anti_hits >= 2 and fb["useful"] == 0 and fb["confirmed"] == 0:
        suppressed = True
        reason = "anti_pattern_collision"
    else:
        suppressed = False
        reason = "ok"

    score = max(0.0, min(0.99, score))
    return {
        "scope": scope,
        "signal_key": signal_key,
        "score": round(score, 3),
        "suppressed": suppressed,
        "reason": reason,
        "evidence": {
            "lesson_hits": lesson_hits,
            "anti_hits": anti_hits,
            "feedback": fb,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--lessons")
    ap.add_argument("--anti-patterns")
    ap.add_argument("--feedback")
    args = ap.parse_args()

    run_data = load_json(Path(args.run), default=None)
    if not run_data:
        raise SystemExit(f"run record missing/empty: {args.run}")
    lessons = load_json(Path(args.lessons), default={"lessons": []}) if args.lessons else {"lessons": []}
    anti = load_json(Path(args.anti_patterns), default={"anti_patterns": []}) if args.anti_patterns else {"anti_patterns": []}
    feedback = load_json(Path(args.feedback), default={"feedback": []}) if args.feedback else {"feedback": []}

    decisions = [score_scope(scope_run, lessons, anti, feedback) for scope_run in (run_data.get("scopes") or []) if isinstance(scope_run, dict)]
    print(json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
