#!/usr/bin/env python3
"""connect-dots pending decisions utilities.

Minimal deterministic helpers for:
- parsing the pending-decisions canon
- validating proposal-mode deferred-decision candidates
- rendering a reviewable row + entry snippet without auto-writing canon
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from _lib import load_json, now_iso, validate_or_die, verify_evidence_sources


DEFER_PATTERNS = [
    re.compile(r"\bdecide later\b", re.IGNORECASE),
    re.compile(r"\bwe(?:\s+will|'ll)\b.*\bdecide\b.*\blater\b", re.IGNORECASE),
    re.compile(r"\bnot now\b", re.IGNORECASE),
    re.compile(r"\bdefer(?:red|\s+this)?\b", re.IGNORECASE),
    re.compile(r"\brevisit later\b", re.IGNORECASE),
    re.compile(r"\bafter\s+\S+\s+\S+", re.IGNORECASE),
]

PENDING_DECISIONS_PATH = Path("docs/assistant/PENDING_DECISIONS.md")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def _parse_table_row(line: str) -> List[str]:
    if not line.strip().startswith("|"):
        return []
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if not cells or all(set(c) <= {"-", ":"} for c in cells):
        return []
    return cells


def parse_pending_decisions(md_path: Path) -> Dict[str, List[Dict[str, str]]]:
    lines = _read_text(md_path).splitlines()
    section = None
    out = {"active": [], "resolved": []}

    for line in lines:
        if line.startswith("## Active decisions"):
            section = "active"
            continue
        if line.startswith("## Resolved decisions"):
            section = "resolved"
            continue
        if line.startswith("## ") and "decisions" not in line.lower():
            section = None
        if section is None:
            continue

        cells = _parse_table_row(line)
        if not cells:
            continue

        if section == "active" and len(cells) == 5 and re.match(r"^PD-\d+$", cells[0]):
            out["active"].append(
                {
                    "id": cells[0],
                    "topic": cells[1],
                    "decision": cells[2],
                    "status": cells[3],
                    "trigger": cells[4],
                }
            )
        elif section == "resolved" and len(cells) == 5 and re.match(r"^PD-\d+$", cells[0]):
            out["resolved"].append(
                {
                    "id": cells[0],
                    "topic": cells[1],
                    "decision": cells[2],
                    "status": cells[3],
                    "resolution_note": cells[4],
                }
            )

    return out


def _next_id(entries: Dict[str, List[Dict[str, str]]]) -> str:
    max_n = 0
    for section in ("active", "resolved"):
        for item in entries.get(section) or []:
            m = re.match(r"PD-(\d+)$", item.get("id") or "")
            if m:
                max_n = max(max_n, int(m.group(1)))
    return f"PD-{max_n + 1:04d}"


def _has_explicit_defer_signal(text: str) -> bool:
    return any(p.search(text or "") for p in DEFER_PATTERNS)


def _dedupe(candidate: Dict[str, Any], existing: Dict[str, List[Dict[str, str]]]) -> Tuple[bool, str | None]:
    cand_decision = _normalize(candidate.get("decision") or "")
    cand_pair = (_normalize(candidate.get("topic") or ""), cand_decision)

    for section in ("active", "resolved"):
        for item in existing.get(section) or []:
            existing_pair = (_normalize(item.get("topic") or ""), _normalize(item.get("decision") or ""))
            if cand_pair == existing_pair or cand_decision == existing_pair[1]:
                return True, item.get("id")
    return False, None


def _render_entry(entry_id: str, candidate: Dict[str, Any]) -> Tuple[str, str]:
    row = f"| {entry_id} | {candidate['topic']} | {candidate['decision']} | {candidate['status']} | {candidate['revisit_trigger']} |"

    lines = [
        f"## {entry_id} — {candidate['topic']}",
        f"- **Decision:** {candidate['decision']}",
    ]
    options = candidate.get("options") or []
    if options:
        lines.append("- **Options:**")
        for idx, opt in enumerate(options, start=1):
            lines.append(f"  {idx}) {opt}")
    lines.extend(
        [
            f"- **Status:** {candidate['status']}",
            f"- **Revisit trigger:** {candidate['revisit_trigger']}",
            f"- **Owner:** {candidate['owner']}",
            "- **Context/links:**",
        ]
    )
    for link in candidate.get("context_links") or []:
        lines.append(f"  - {link}")
    ev = candidate["source_evidence"]
    lines.append(f"  - Source: {ev['path']}#{ev['lines']}")
    if candidate.get("notes"):
        lines.append(f"- **Notes:** {candidate['notes']}")
    return row, "\n".join(lines) + "\n"


def summarize_pending_decisions(entries: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    active = entries.get("active") or []
    resolved = entries.get("resolved") or []

    dueish_patterns = [
        re.compile(r"\bnow\b", re.IGNORECASE),
        re.compile(r"\barrived\b", re.IGNORECASE),
        re.compile(r"\bafter jd sends\b", re.IGNORECASE),
        re.compile(r"\bafter forum debrief\b", re.IGNORECASE),
        re.compile(r"\bafter jd sends the forum debrief\b", re.IGNORECASE),
    ]

    dueish = []
    for item in active:
        trig = item.get("trigger") or ""
        if any(p.search(trig) for p in dueish_patterns):
            dueish.append(item)

    return {
        "active_total": len(active),
        "resolved_total": len(resolved),
        "dueish": dueish,
    }


def _match_defer_signal(*texts: str) -> str | None:
    for text in texts:
        if not text:
            continue
        for pat in DEFER_PATTERNS:
            m = pat.search(text)
            if m:
                return m.group(0)
    return None


def _topic_for_item(scope: str, item: Dict[str, Any]) -> str:
    domain = (item.get("domain") or "").strip()
    if domain:
        return domain.replace("_", " ").replace("-", " / ")
    return scope.replace("/", " / ")


def _trigger_for_item(item: Dict[str, Any]) -> str | None:
    for key in ("confirm", "why", "statement"):
        value = (item.get(key) or "").strip()
        if not value:
            continue
        if key == "statement":
            m = re.search(r"\bafter\b.+", value, re.IGNORECASE)
            if m:
                return m.group(0).strip().rstrip(".")
        elif key == "confirm":
            return value.rstrip("?").strip()
        else:
            m = re.search(r"\b(after|when|once)\b.+", value, re.IGNORECASE)
            if m:
                return m.group(0).strip().rstrip(".")
    return None


def candidate_from_item(*, scope: str, item: Dict[str, Any]) -> Dict[str, Any] | None:
    signal = _match_defer_signal(item.get("statement", ""), item.get("why", ""), item.get("confirm", ""))
    if not signal:
        return None
    evidence = (item.get("evidence") or [])
    if not evidence:
        return None
    trigger = _trigger_for_item(item)
    if not trigger:
        return None

    statement = (item.get("statement") or "").strip()
    candidate = {
        "topic": _topic_for_item(scope, item),
        "decision": statement.rstrip("."),
        "status": "deferred",
        "revisit_trigger": trigger,
        "owner": "JD",
        "defer_signal": signal,
        "source_evidence": evidence[0],
    }
    if item.get("why"):
        candidate["notes"] = item["why"]
    return candidate


def prepare_candidates_from_proposal(*, workspace: Path, proposal: Dict[str, Any], existing: Dict[str, List[Dict[str, str]]], schema_path: Path) -> List[Dict[str, Any]]:
    scope = proposal.get("scope") or "unknown"
    out = []
    items = proposal.get("items") or {}
    next_id_num = int(_next_id(existing).split("-")[1])

    for section in ("open_loops", "candidate_moves"):
        for item in items.get(section) or []:
            if not isinstance(item, dict):
                continue
            candidate = candidate_from_item(scope=scope, item=item)
            if not candidate:
                continue
            validate_or_die(candidate, schema_path, "pending decision candidate")
            verify_evidence_sources([candidate["source_evidence"]], workspace)
            duplicate, duplicate_id = _dedupe(candidate, existing)
            entry_id = f"PD-{next_id_num:04d}"
            if not duplicate:
                next_id_num += 1
            row, entry_md = _render_entry(entry_id, candidate)
            out.append(
                {
                    "status": "duplicate" if duplicate else "proposal-ready",
                    "duplicate": duplicate,
                    "duplicate_id": duplicate_id,
                    "next_id": entry_id,
                    "row": row,
                    "entry_markdown": entry_md,
                    "candidate": candidate,
                    "section": section,
                    "source_item_id": item.get("id"),
                }
            )
    return out


def cmd_parse(args: argparse.Namespace) -> int:
    ws = Path(args.workspace).resolve()
    pd_path = ws / PENDING_DECISIONS_PATH
    print(json.dumps(parse_pending_decisions(pd_path), ensure_ascii=False, indent=2))
    return 0


def cmd_prepare_proposal(args: argparse.Namespace) -> int:
    ws = Path(args.workspace).resolve()
    pd_path = ws / PENDING_DECISIONS_PATH
    candidate_path = Path(args.candidate).resolve()
    schema_path = Path(args.schema).resolve() if args.schema else (Path(__file__).resolve().parents[1] / "references" / "pending-decision.schema.json")

    candidate = load_json(candidate_path, default=None)
    if not isinstance(candidate, dict):
        raise SystemExit("candidate must be a JSON object")
    validate_or_die(candidate, schema_path, "pending decision candidate")

    verify_evidence_sources([candidate["source_evidence"]], ws)

    signal = candidate.get("defer_signal") or ""
    quote = candidate["source_evidence"].get("quote") or ""
    if not (_has_explicit_defer_signal(signal) or _has_explicit_defer_signal(quote)):
        raise SystemExit("candidate missing explicit defer signal")

    existing = parse_pending_decisions(pd_path)
    duplicate, duplicate_id = _dedupe(candidate, existing)
    next_id = _next_id(existing)
    row, entry_md = _render_entry(next_id, candidate)

    result = {
        "generated_at": now_iso(),
        "status": "duplicate" if duplicate else "proposal-ready",
        "duplicate": duplicate,
        "duplicate_id": duplicate_id,
        "next_id": next_id,
        "row": row,
        "entry_markdown": entry_md,
    }

    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_extract_from_proposal(args: argparse.Namespace) -> int:
    ws = Path(args.workspace).resolve()
    pd_path = ws / PENDING_DECISIONS_PATH
    proposal_path = Path(args.proposal).resolve()
    schema_path = Path(args.schema).resolve() if args.schema else (Path(__file__).resolve().parents[1] / "references" / "pending-decision.schema.json")

    proposal = load_json(proposal_path, default=None)
    if not isinstance(proposal, dict):
        raise SystemExit("proposal must be a JSON object")

    existing = parse_pending_decisions(pd_path)
    candidates = prepare_candidates_from_proposal(workspace=ws, proposal=proposal, existing=existing, schema_path=schema_path)
    result = {
        "generated_at": now_iso(),
        "proposal": str(proposal_path),
        "count": len(candidates),
        "items": candidates,
    }
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_parse = sub.add_parser("parse")
    p_parse.add_argument("--workspace", required=True)
    p_parse.set_defaults(func=cmd_parse)

    p_prepare = sub.add_parser("prepare-proposal")
    p_prepare.add_argument("--workspace", required=True)
    p_prepare.add_argument("--candidate", required=True)
    p_prepare.add_argument("--schema")
    p_prepare.add_argument("--output")
    p_prepare.set_defaults(func=cmd_prepare_proposal)

    p_extract = sub.add_parser("extract-from-proposal")
    p_extract.add_argument("--workspace", required=True)
    p_extract.add_argument("--proposal", required=True)
    p_extract.add_argument("--schema")
    p_extract.add_argument("--output")
    p_extract.set_defaults(func=cmd_extract_from_proposal)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
