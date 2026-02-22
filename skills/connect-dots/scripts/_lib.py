from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import jsonschema

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
LINES_RE = re.compile(r"^L(\d+)-L(\d+)$")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_iso(ts: str) -> datetime:
    # Best-effort: accept any ISO-ish string python can parse.
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        # Fall back to "now" if it's garbage.
        return datetime.now(timezone.utc).astimezone()


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_schema(schema_path: Path) -> Dict[str, Any]:
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_or_die(instance: Any, schema_path: Path, label: str) -> None:
    schema = load_schema(schema_path)
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as e:
        raise SystemExit(f"invalid {label}: {e.message} (at {list(e.absolute_path)})")


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def matches_do_not_store(text: str, dns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    t = (text or "").lower()
    for rule in dns or []:
        pat = (rule.get("pattern") or "").lower()
        if not pat:
            continue
        if pat in t:
            return rule
    return None


def compute_recency_days(evidence: List[Dict[str, Any]], now: datetime) -> float:
    # Use the newest evidence timestamp we can parse (most recent).
    best = None
    for ev in evidence or []:
        ts = ev.get("ts")
        if not ts:
            continue
        dt = parse_iso(ts)
        if best is None or dt > best:
            best = dt
    if best is None:
        return 9999.0
    return max(0.0, (now - best).total_seconds() / 86400.0)


def confidence_formula(
    *,
    evidence: List[Dict[str, Any]],
    user_confirmed: bool = False,
    conflicts: bool = False,
    now: datetime,
) -> float:
    """Deterministic confidence approximation.

    Intentionally simple: it is auditable + stable.
    """
    sources = len(evidence or [])
    sources_cap = min(5, sources)

    # Recency score: exp decay with ~7 day half-life.
    rec_days = compute_recency_days(evidence, now)
    recency_score = math.exp(-rec_days / 7.0) if rec_days < 9999 else 0.0

    agreement = 0.15 if sources >= 2 else 0.0

    base = 0.20
    count_score = 0.12 * sources_cap  # up to 0.60
    rec_score = 0.25 * recency_score  # up to 0.25
    confirm_bonus = 0.20 if user_confirmed else 0.0
    conflict_pen = 0.25 if conflicts else 0.0

    conf = base + count_score + rec_score + agreement + confirm_bonus - conflict_pen
    return clamp(conf, 0.05, 0.99)


def parse_lines_spec(lines: str) -> Tuple[int, int]:
    m = LINES_RE.match(lines or "")
    if not m:
        raise ValueError(f"bad lines spec: {lines}")
    a = int(m.group(1))
    b = int(m.group(2))
    if a <= 0 or b < a:
        raise ValueError(f"bad lines range: {lines}")
    return a, b


def verify_evidence_sources(evidence: List[Dict[str, Any]], workspace: Path) -> None:
    """Fail closed unless evidence is auditable.

    Enforces:
    - file exists under workspace
    - line range is valid
    - quote appears within the cited line range

    This is the hard guard behind "every non-trivial item needs a citation".
    """
    ws = workspace.resolve()
    for ev in evidence or []:
        p = ev.get("path")
        if not p:
            raise SystemExit("evidence missing path")
        full = (workspace / p).resolve()
        if not str(full).startswith(str(ws)):
            raise SystemExit(f"evidence path escapes workspace: {p}")
        if not full.exists():
            raise SystemExit(f"evidence file not found: {p}")

        a, b = parse_lines_spec(ev.get("lines", ""))
        quote = (ev.get("quote") or "").strip()
        if not quote:
            raise SystemExit(f"evidence quote missing: {p} {ev.get('lines')}")

        with full.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        n = len(lines)
        if b > n:
            raise SystemExit(f"evidence line range out of bounds: {p} {ev.get('lines')} (file has {n} lines)")

        snippet = "".join(lines[a - 1 : b])
        if quote not in snippet:
            raise SystemExit(
                f"evidence quote not found in cited range: {p} {ev.get('lines')} (quote='{quote[:80]}...')"
            )


def ensure_model_skeleton(scope: str) -> Dict[str, Any]:
    return {
        "scope": scope,
        "updatedAt": now_iso(),
        "meta": {},
        "confirmed_facts": [],
        "hypotheses": [],
        "stale_items": [],
        "open_loops": [],
        "candidate_moves": [],
        "do_not_store": [],
    }


def index_by_id(items: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        _id = it.get("id")
        if _id:
            out[_id] = it
    return out


def normalize_item_common(
    *,
    item: Dict[str, Any],
    now_dt: datetime,
    default_ttl_days: int,
    keep_first_seen: Optional[str],
) -> Dict[str, Any]:
    out = dict(item)

    out.setdefault("first_seen", keep_first_seen or now_dt.isoformat(timespec="seconds"))
    out["last_seen"] = now_dt.isoformat(timespec="seconds")

    ttl_days = int(out.get("ttl_days") or default_ttl_days)
    ttl_days = max(1, ttl_days)
    out.pop("ttl_days", None)

    # expiry is mandatory
    out["expires_at"] = (now_dt + timedelta(days=ttl_days)).isoformat(timespec="seconds")

    out.setdefault("status", "active")
    return out


def drop_retracted(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [it for it in (items or []) if isinstance(it, dict) and it.get("status") != "retracted"]
