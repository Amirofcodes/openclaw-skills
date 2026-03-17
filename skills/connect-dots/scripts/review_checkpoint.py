#!/usr/bin/env python3
"""connect-dots review checkpoint — opinionated review wrapper around doctor.

Purpose:
- run a 2-week style review in one command
- summarize current health
- print concrete review prompts and follow-up commands

Read-only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _lib import load_json
from doctor import build_report, render_text, _load_runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--runs-limit", type=int, default=30)
    ap.add_argument("--stale-days", type=int, default=14)
    ap.add_argument("--label", default="2-week review")
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    runs = _load_runs(ws / "tmp" / "connect-dots" / "runs", args.runs_limit)
    insights = ws / "memory" / "internal" / "connect-dots" / "insights"
    lessons = load_json(insights / "lessons.json", default={"lessons": []})
    anti = load_json(insights / "anti-patterns.json", default={"anti_patterns": []})
    feedback = load_json(insights / "feedback.json", default={"feedback": []})

    report = build_report(runs=runs, lessons=lessons, anti=anti, feedback=feedback, stale_days=args.stale_days)

    print(f"connect-dots {args.label}")
    print("=" * (len(f"connect-dots {args.label}")))
    print()
    print(render_text(report), end="")

    print("\nReview questions")
    print("- Are active lessons actually useful, or just accumulating?")
    print("- Are suppressed patterns correct, or are we suppressing something valuable?")
    print("- Do anti-pattern collisions reveal a real bug or just a noisy threshold?")
    print("- Is feedback volume high enough to trust the usefulness scorer yet?")
    print("- Did any failed/partial runs hide a regression we should fix now?")

    print("\nRecommended spot checks")
    print(f"- python3 scripts/doctor.py --workspace {ws} --json")
    print(f"- find {ws}/tmp/connect-dots/runs -name run.json | sort | tail -n 5")
    print(f"- cat {ws}/memory/internal/connect-dots/insights/lessons.json")
    print(f"- cat {ws}/memory/internal/connect-dots/insights/anti-patterns.json")
    print(f"- cat {ws}/memory/internal/connect-dots/insights/feedback.json")

    if report["recent_failures"]:
        print("\nCallout: there are recent failed/partial runs. Fix those before trusting the scoring layer too much.")
    elif report["feedback_summary"].get("useful", 0) + report["feedback_summary"].get("confirmed", 0) == 0 and report["health"]["feedback_total"] == 0:
        print("\nCallout: there is no feedback yet. The usefulness layer is installed, but still mostly untrained.")
    else:
        print("\nCallout: the system has enough structure to review meaningfully. Focus on signal quality, not more scaffolding.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
