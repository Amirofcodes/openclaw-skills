#!/usr/bin/env python3
"""Deterministic policy guard for connect-dots recommendation paths.

This is Phase D:
- classify blast radius
- classify approval lane
- refuse actions that violate lane policy

The module is intentionally boring and auditable.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

ALLOWED_SCOPES = {
    "user-profile/preferences",
    "openclaw-runtime/ops",
    "repos",
}


def classify_blast_radius(*, scope: str, action_kind: str, external: bool = False, service_change: bool = False) -> str:
    if external:
        return "external-facing"
    if service_change:
        return "service-touching"

    if scope == "user-profile/preferences":
        if action_kind in {"silent-update", "refresh-question", "surface-brief", "none"}:
            return "memory-only"
        return "docs-only"

    if scope == "openclaw-runtime/ops":
        if action_kind in {"silent-update", "surface-brief", "refresh-question", "none"}:
            return "runtime-checks"
        return "docs-only"

    if scope == "repos":
        if action_kind == "proposal":
            return "local-analysis"
        if action_kind in {"surface-brief", "refresh-question", "none"}:
            return "local-analysis"
        return "docs-only"

    return "docs-only"


def classify_lane(*, action_kind: str, blast_radius: str) -> str:
    if blast_radius in {"service-touching", "external-facing"}:
        return "approval-required"
    if action_kind == "silent-update" or action_kind == "none":
        return "observe-only"
    if action_kind in {"refresh-question", "surface-brief"}:
        return "suggest-only"
    if action_kind == "proposal":
        return "safe-local-proposal"
    return "safe-local-proposal"


def enforce_policy(*, scope: str, action_kind: str, user_facing: bool, external: bool = False, service_change: bool = False, approved: bool = False) -> Dict[str, Any]:
    if scope not in ALLOWED_SCOPES:
        return {
            "allowed": False,
            "reason": f"unsupported_scope:{scope}",
            "blast_radius": "docs-only",
            "lane": "approval-required",
        }

    blast_radius = classify_blast_radius(
        scope=scope,
        action_kind=action_kind,
        external=external,
        service_change=service_change,
    )
    lane = classify_lane(action_kind=action_kind, blast_radius=blast_radius)

    if lane == "approval-required" and not approved:
        return {
            "allowed": False,
            "reason": "approval_required",
            "blast_radius": blast_radius,
            "lane": lane,
        }

    if user_facing and lane == "observe-only":
        return {
            "allowed": False,
            "reason": "observe_only_cannot_surface",
            "blast_radius": blast_radius,
            "lane": lane,
        }

    if blast_radius in {"external-facing", "service-touching"} and not approved:
        return {
            "allowed": False,
            "reason": "blast_radius_requires_approval",
            "blast_radius": blast_radius,
            "lane": lane,
        }

    return {
        "allowed": True,
        "reason": "ok",
        "blast_radius": blast_radius,
        "lane": lane,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", required=True)
    ap.add_argument("--action-kind", required=True)
    ap.add_argument("--user-facing", action="store_true")
    ap.add_argument("--external", action="store_true")
    ap.add_argument("--service-change", action="store_true")
    ap.add_argument("--approved", action="store_true")
    args = ap.parse_args()

    result = enforce_policy(
        scope=args.scope,
        action_kind=args.action_kind,
        user_facing=bool(args.user_facing),
        external=bool(args.external),
        service_change=bool(args.service_change),
        approved=bool(args.approved),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("allowed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
