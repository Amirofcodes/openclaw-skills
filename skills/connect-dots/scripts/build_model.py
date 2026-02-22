#!/usr/bin/env python3
"""Deterministic model builder for connect-dots.

Design goal (locked by JD):
- LLM does synthesis/proposals.
- Scripts do *all* state mutation (merge, TTL decay, retract handling, schema validation).
- Fail closed: any schema mismatch or bad citation -> no write.

Inputs:
- Existing model.json (optional)
- Proposal.json (required) following references/proposal.schema.json

Writes:
- Updated model.json (atomic)
- Optional snapshot + optional diff output

Usage:
  build_model.py --scope "user-profile/preferences" \
    --workspace /home/amiro/.openclaw/workspace \
    --model memory/internal/connect-dots/user-profile/preferences/model.json \
    --proposal tmp/connect-dots/proposals/user-profile.json \
    --snapshot-out memory/internal/connect-dots/user-profile/preferences/snapshots/2026-02-22.json \
    --diff-out tmp/connect-dots/last-diff.txt
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path

from _lib import (
    atomic_write_json,
    confidence_formula,
    ensure_model_skeleton,
    index_by_id,
    load_json,
    now_iso,
    normalize_item_common,
    validate_or_die,
    matches_do_not_store,
    verify_evidence_sources,
)


def _merge_list(*, current, proposed, section: str):
    """Merge by id: proposed overrides statement/why/confirm/evidence; preserves first_seen when present."""
    cur_idx = index_by_id(current)
    out = []

    for p in proposed:
        pid = p.get("id")
        if not pid:
            continue
        existing = cur_idx.get(pid)
        keep_first = existing.get("first_seen") if existing else None
        keep_domain = existing.get("domain") if existing else None

        merged = dict(p)
        if keep_domain and not merged.get("domain"):
            merged["domain"] = keep_domain
        merged["_keep_first_seen"] = keep_first
        merged["_refreshed"] = True
        out.append(merged)

    # keep any current items not mentioned in proposal
    proposed_ids = {p.get("id") for p in proposed if isinstance(p, dict)}
    for it in current:
        if not isinstance(it, dict):
            continue
        if it.get("id") and it.get("id") not in proposed_ids:
            kept = dict(it)
            kept["_refreshed"] = False
            out.append(kept)

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", required=True)
    ap.add_argument("--workspace", required=True, help="OpenClaw workspace root")
    ap.add_argument("--model", required=True)
    ap.add_argument("--proposal", required=True)
    ap.add_argument(
        "--model-schema",
        default=str(Path(__file__).resolve().parent.parent / "references" / "model.schema.json"),
    )
    ap.add_argument(
        "--proposal-schema",
        default=str(Path(__file__).resolve().parent.parent / "references" / "proposal.schema.json"),
    )
    ap.add_argument("--snapshot-out")
    ap.add_argument("--diff-out")
    ap.add_argument("--verify-sources", action="store_true", default=True)
    ap.add_argument("--no-verify-sources", dest="verify_sources", action="store_false")
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    model_path = Path(args.model)
    prop_path = Path(args.proposal)

    proposal = load_json(prop_path, default=None)
    if not proposal:
        raise SystemExit(f"proposal missing/empty: {prop_path}")

    validate_or_die(proposal, Path(args.proposal_schema), label=f"proposal ({prop_path})")

    if proposal.get("scope") != args.scope:
        raise SystemExit(f"proposal scope mismatch: expected {args.scope}, got {proposal.get('scope')}")

    prev_model = load_json(model_path, default=None)
    if not prev_model:
        model = ensure_model_skeleton(args.scope)
    else:
        model = copy.deepcopy(prev_model)

    # Always refresh updatedAt.
    model["updatedAt"] = now_iso()

    # Merge do_not_store as-is (LLM should not mutate it; only consent_mutations should).
    dns = model.get("do_not_store") or []

    items = proposal["items"]

    # Merge lists by id.
    model["confirmed_facts"] = _merge_list(
        current=model.get("confirmed_facts") or [],
        proposed=items.get("confirmed_facts") or [],
        section="confirmed_facts",
    )
    model["hypotheses"] = _merge_list(
        current=model.get("hypotheses") or [],
        proposed=items.get("hypotheses") or [],
        section="hypotheses",
    )
    model["open_loops"] = _merge_list(
        current=model.get("open_loops") or [],
        proposed=items.get("open_loops") or [],
        section="open_loops",
    )
    model["candidate_moves"] = _merge_list(
        current=model.get("candidate_moves") or [],
        proposed=items.get("candidate_moves") or [],
        section="candidate_moves",
    )

    now_dt = datetime.now(timezone.utc).astimezone()

    def process_section(section: str, default_ttl_days: int):
        processed = []
        for it in model.get(section) or []:
            if not isinstance(it, dict):
                continue

            # do-not-store filter
            stmt = it.get("statement") or it.get("fact") or ""
            hit = matches_do_not_store(stmt, dns)
            if hit:
                # drop silently; do_not_store should prevent storage.
                continue

            evidence = it.get("evidence") or []
            if args.verify_sources:
                verify_evidence_sources(evidence, workspace)

            keep_first = it.pop("_keep_first_seen", None)
            refreshed = bool(it.pop("_refreshed", False))

            if section == "confirmed_facts":
                # Facts are stable; only refresh timestamps/expiry if refreshed.
                out = dict(it)
                out.setdefault("confidence", 0.99)
                out.setdefault("first_seen", keep_first or out.get("first_seen") or now_dt.isoformat(timespec="seconds"))
                if refreshed:
                    out["last_seen"] = now_dt.isoformat(timespec="seconds")
                    ttl_days = int(out.get("ttl_days") or default_ttl_days)
                    out.pop("ttl_days", None)
                    out["expires_at"] = (
                        now_dt + __import__("datetime").timedelta(days=max(1, ttl_days))
                    ).isoformat(timespec="seconds")
                else:
                    out.setdefault("last_seen", out.get("last_seen") or now_dt.isoformat(timespec="seconds"))
                    out.setdefault("expires_at", out.get("expires_at") or "9999-12-31T00:00:00+00:00")
                out.setdefault("last_confirmed", out.get("last_confirmed") or out.get("last_seen") or now_dt.isoformat(timespec="seconds"))
                out.setdefault("status", "active")
                processed.append(out)
                continue

            if refreshed:
                # Normalize generic item (refresh = new evidence)
                out = normalize_item_common(
                    item=it,
                    now_dt=now_dt,
                    default_ttl_days=default_ttl_days,
                    keep_first_seen=keep_first,
                )

                # Deterministic confidence recompute
                out["confidence"] = confidence_formula(
                    evidence=evidence,
                    user_confirmed=bool(it.get("user_confirmed")),
                    conflicts=bool(it.get("conflicts")),
                    now=now_dt,
                )
                out.pop("user_confirmed", None)
                out.pop("conflicts", None)
            else:
                # Not refreshed: do not extend TTL.
                out = dict(it)
                out.setdefault("first_seen", keep_first or out.get("first_seen") or now_dt.isoformat(timespec="seconds"))
                out.setdefault("last_seen", out.get("last_seen") or now_dt.isoformat(timespec="seconds"))
                out.setdefault("expires_at", out.get("expires_at") or now_dt.isoformat(timespec="seconds"))
                out.setdefault("status", out.get("status") or "active")
                out.setdefault("confidence", float(out.get("confidence") or 0.2))

            processed.append(out)

        model[section] = processed

    # Apply processing
    process_section("confirmed_facts", default_ttl_days=365)
    process_section("hypotheses", default_ttl_days=21)
    process_section("open_loops", default_ttl_days=14)
    process_section("candidate_moves", default_ttl_days=7)

    # TTL decay: move expired items to stale_items, cap confidence.
    stale = model.get("stale_items") or []

    def is_expired(it):
        try:
            exp = datetime.fromisoformat(it.get("expires_at").replace("Z", "+00:00"))
            return now_dt > exp
        except Exception:
            return False

    def move_to_stale(section):
        keep = []
        for it in model.get(section) or []:
            if not isinstance(it, dict):
                continue
            if it.get("status") == "retracted":
                # keep retracted only in stale for audit
                it2 = dict(it)
                it2["status"] = "retracted"
                stale.append(it2)
                continue
            if is_expired(it):
                it2 = dict(it)
                it2["status"] = "stale"
                it2["confidence"] = min(float(it2.get("confidence") or 0.0), 0.35)
                stale.append(it2)
            else:
                keep.append(it)
        model[section] = keep

    move_to_stale("hypotheses")
    move_to_stale("open_loops")
    move_to_stale("candidate_moves")

    # Deduplicate stale by id, keeping the newest last_seen.
    by_id = {}
    for it in stale:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        cur = by_id.get(it["id"])
        if not cur or (it.get("last_seen") or "") > (cur.get("last_seen") or ""):
            by_id[it["id"]] = it
    model["stale_items"] = list(by_id.values())

    # Validate final model
    validate_or_die(model, Path(args.model_schema), label=f"model ({model_path})")

    # Write model
    atomic_write_json(model_path, model)

    if args.snapshot_out:
        atomic_write_json(Path(args.snapshot_out), model)

    # Diff
    if args.diff_out and prev_model:
        # minimal diff: added/updated/retracted
        prev_idx = index_by_id((prev_model.get("hypotheses") or []) + (prev_model.get("confirmed_facts") or []))
        cur_idx = index_by_id((model.get("hypotheses") or []) + (model.get("confirmed_facts") or []))

        added = [k for k in cur_idx.keys() if k not in prev_idx]
        retracted = [k for k, v in cur_idx.items() if v.get("status") == "retracted"]

        lines = []
        for k in added[:10]:
            it = cur_idx[k]
            lines.append(f"+ {it.get('statement') or it.get('fact') or k}")
        # updated = heuristic
        for k in cur_idx.keys():
            if k in prev_idx and (cur_idx[k].get("statement") != prev_idx[k].get("statement") or cur_idx[k].get("confidence") != prev_idx[k].get("confidence")):
                lines.append(f"~ {cur_idx[k].get('statement') or cur_idx[k].get('fact') or k}")
        for k in retracted[:10]:
            it = cur_idx[k]
            lines.append(f"- {it.get('statement') or it.get('fact') or k}")
        if not lines:
            lines.append("(no material changes)")
        Path(args.diff_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.diff_out).write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
