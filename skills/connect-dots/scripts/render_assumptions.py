#!/usr/bin/env python3
"""Render the bounded "show assumptions about me" snapshot.

This script enforces strict section caps + single-message output.
It expects the model JSON to already contain evidence with line refs.

Usage:
  python3 render_assumptions.py --model path/to/model.json [--prev path/to/prev.json]

Exit codes:
  0 ok
  2 bad input
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _safe_list(x):
    return x if isinstance(x, list) else []


def _fmt_evidence(item) -> str:
    ev = _safe_list(item.get("evidence"))
    if not ev:
        return "Source: (missing)"
    e0 = ev[0]
    path = e0.get("path", "?")
    lines = e0.get("lines", "?")
    recency = e0.get("recency", None)
    if recency is None:
        # accept ts; caller may precompute recency
        rec = ""
    else:
        rec = f" ({recency}d ago)"
    return f"Source: {path}#{lines}{rec}"


def _cap(items, n):
    return list(items)[:n]


def _diff(prev, cur):
    """Return diff bullets: added/updated/retracted.

    We define identity by (id). Updated if statement/confidence/status changed.
    """
    if not prev:
        return ["+ added initial snapshot"], [], []

    def index(model):
        idx = {}
        for section in ("confirmed_facts", "hypotheses", "stale_items"):
            for it in _safe_list(model.get(section)):
                if isinstance(it, dict) and it.get("id"):
                    idx[it["id"]] = (section, it)
        return idx

    p = index(prev)
    c = index(cur)

    added, updated, retracted = [], [], []
    for cid, (csec, cit) in c.items():
        if cid not in p:
            added.append(f"+ {cit.get('statement','(no statement)')}")
            continue
        _, pit = p[cid]
        changed = False
        for k in ("statement", "confidence", "status", "expires_at"):
            if cit.get(k) != pit.get(k):
                changed = True
                break
        if changed:
            updated.append(f"~ {cit.get('statement','(no statement)')}")

    for pid, (_, pit) in p.items():
        if pid not in c:
            retracted.append(f"- {pit.get('statement','(no statement)')}")

    return _cap(added, 5), _cap(updated, 5), _cap(retracted, 5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--prev")
    args = ap.parse_args()

    try:
        model = _load(args.model)
        prev = _load(args.prev) if args.prev else None
    except Exception as e:
        print(f"error: failed to load json: {e}", file=sys.stderr)
        return 2

    scope = model.get("scope", "(unknown)")
    gen = _now_iso()

    confirmed = [x for x in _safe_list(model.get("confirmed_facts")) if isinstance(x, dict) and x.get("status") != "retracted"]
    hyps = [x for x in _safe_list(model.get("hypotheses")) if isinstance(x, dict) and x.get("status") != "retracted"]
    stale = [x for x in _safe_list(model.get("stale_items")) if isinstance(x, dict) and x.get("status") != "retracted"]

    confirmed = sorted(confirmed, key=lambda x: x.get("last_seen", ""), reverse=True)
    hyps = sorted(hyps, key=lambda x: x.get("confidence", 0), reverse=True)
    stale = sorted(stale, key=lambda x: x.get("last_seen", ""), reverse=True)
    dns = _safe_list(model.get("do_not_store"))

    confirmed = _cap(confirmed, 5)
    hyps = _cap(hyps, 5)
    stale = _cap(stale, 3)

    added, updated, retracted = _diff(prev, model)

    lines = []
    lines.append(f"Assumptions snapshot — {scope}")
    lines.append(f"Generated: {gen}")

    # 1) Confirmed
    lines.append("\n1) Confirmed facts (max 5)")
    if confirmed:
        for it in confirmed:
            fact = it.get("fact") or it.get("statement") or "(fact)"
            val = it.get("value")
            last_conf = it.get("last_confirmed") or it.get("last_seen") or "?"
            v = f"{val}" if val is not None else ""
            src = _fmt_evidence(it)
            lines.append(f"- {fact} · {v} · last confirmed: {last_conf} · {src}")
    else:
        lines.append("- (none)")

    # 2) Hypotheses
    lines.append("\n2) Top hypotheses (max 5)")
    if hyps:
        for it in hyps:
            stmt = it.get("statement", "(no statement)")
            conf = it.get("confidence", 0)
            why = it.get("why", "")
            confirm = it.get("confirm", "")
            expires = it.get("expires_at", "?")
            src = _fmt_evidence(it)
            why_part = f" · why: {why}" if why else ""
            conf_part = f"{int(round(conf*100))}%" if conf <= 1 else f"{conf}%"
            confirm_part = f" · confirm/deny: {confirm}" if confirm else ""
            lines.append(f"- {stmt} · confidence: {conf_part}{why_part}{confirm_part} · expires: {expires} · {src}")
    else:
        lines.append("- (none)")

    # 3) Stale
    lines.append("\n3) Stale assumptions (max 3)")
    if stale:
        for it in stale:
            stmt = it.get("statement", "(no statement)")
            stale_why = it.get("stale_why", "expired/old evidence")
            action = it.get("proposed_action", "refresh/drop")
            src = _fmt_evidence(it)
            lines.append(f"- {stmt} · why stale: {stale_why} · action: {action} · {src}")
    else:
        lines.append("- (none)")

    # 4) DNS
    lines.append("\n4) Do-not-store protections (active)")
    if dns:
        for it in _cap(dns, 10):
            if isinstance(it, str):
                lines.append(f"- {it}")
            elif isinstance(it, dict):
                lines.append(f"- {it.get('pattern') or it.get('value') or json.dumps(it)}")
    else:
        lines.append("- (none)")

    # 5) Diff
    lines.append("\n5) What changed since last snapshot")
    if not prev:
        lines.append("- + added initial snapshot")
    else:
        if added:
            lines.extend([f"- {b}" for b in added])
        if updated:
            lines.extend([f"- {b}" for b in updated])
        if retracted:
            lines.extend([f"- {b}" for b in retracted])
        if not (added or updated or retracted):
            lines.append("- (no material changes)")

    # 6) Controls
    lines.append("\n6) Control shortcuts")
    lines.append("- forget <x> · don’t store <x> · confirm <x> · deny <x>")

    sys.stdout.write("\n".join(lines).rstrip() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
