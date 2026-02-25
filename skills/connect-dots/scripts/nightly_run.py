#!/usr/bin/env python3
"""connect-dots nightly bridge: proposal -> validate/diff -> (optional) apply.

Rollout (locked by JD):
- Phase 1 (dry-run, 2 nights): generate proposal + validate + diff only (NO WRITES to model).
- Phase 2: enable apply if validation passes (fail-closed).

This script is intended to be called from an isolated cron agentTurn.
It is deterministic about file paths + artifacts, but relies on the LLM to produce
proposal JSON content.

Artifacts per run (per scope):
- proposal JSON: tmp/connect-dots/runs/<runId>/<scope>/proposal.json
- pre snapshot:  tmp/connect-dots/runs/<runId>/<scope>/model.pre.json (if exists)
- post snapshot: tmp/connect-dots/runs/<runId>/<scope>/model.post.json (if applied)
- diff:          tmp/connect-dots/runs/<runId>/<scope>/diff.txt
- error log:     tmp/connect-dots/runs/<runId>/<scope>/error.log

If any schema/citation checks fail: write nothing and log only.

Usage:
  nightly_run.py --workspace /home/amiro/.openclaw/workspace --phase 1|2

Phase selection:
- Default phase is read from env CONNECT_DOTS_PHASE, else --phase.

Notes:
- Evidence validation in build_model.py requires evidence paths to be **under the workspace**.
  For any runtime-derived facts, this script writes a small snapshot file under the run dir
  and rewrites the proposal evidence to cite that snapshot (so citations remain auditable).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now_id() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sh(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def resolve_scope_dir(runs_root: Path, scope: str) -> Path:
    """Prefer nested <run>/<scope>/... paths.

    Back-compat: older runs wrote <run>/<scope_with_slashes_replaced_by_underscores>/...
    """
    canonical = runs_root / Path(scope)
    legacy = runs_root / scope.replace("/", "_")

    if (legacy / "proposal.json").exists() and not (canonical / "proposal.json").exists():
        return legacy
    return canonical


def _read_openclaw_routing() -> dict:
    """Extract a safe routing snapshot from OpenClaw config.

    We only read the non-secret model routing bits.
    """
    cfg_path = os.environ.get("OPENCLAW_CONFIG_PATH")
    if cfg_path:
        p = Path(cfg_path).expanduser().resolve()
    else:
        p = Path.home() / ".openclaw" / "openclaw.json"

    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}

    defaults = (((cfg.get("agents") or {}).get("defaults") or {}))

    model = defaults.get("model") or {}
    primary = model.get("primary") or "(unknown)"
    fallbacks = model.get("fallbacks") or []
    if not isinstance(fallbacks, list):
        fallbacks = []

    # Respect JD request: avoid OpenRouter OpenAI/Anthropic usage.
    fallbacks = [
        m
        for m in fallbacks
        if not (isinstance(m, str) and (m.startswith("openrouter/openai/") or m.startswith("openrouter/anthropic/")))
    ]

    heartbeat = (defaults.get("heartbeat") or {}).get("model") or "(unknown)"

    return {
        "primary": primary,
        "fallbacks": [m for m in fallbacks if isinstance(m, str) and m.strip()],
        "heartbeat": heartbeat,
        "configPath": str(p),
    }


def _format_routing_value(r: dict) -> str:
    primary = r.get("primary") or "(unknown)"
    fallbacks = r.get("fallbacks") or []
    hb = r.get("heartbeat") or "(unknown)"

    fb_str = " -> ".join(fallbacks) if fallbacks else "none"
    return f"primary={primary}; fallbacks={fb_str}; heartbeat={hb}"


def _write_routing_snapshot(*, ws: Path, scope_dir: Path, r: dict) -> Path:
    """Write a small, auditable, workspace-local snapshot file for evidence."""
    primary = r.get("primary") or "(unknown)"
    fallbacks = r.get("fallbacks") or []
    hb = r.get("heartbeat") or "(unknown)"

    fb_str = " -> ".join(fallbacks) if fallbacks else "none"

    snap = scope_dir / "runtime-routing.txt"
    write_text(
        snap,
        "\n".join(
            [
                f"primary: {primary}",
                f"fallbacks: {fb_str}",
                f"heartbeat: {hb}",
                f"generatedAt: {now_iso()}",
            ]
        )
        + "\n",
    )
    return snap


def _patch_openclaw_runtime_proposal(*, ws: Path, scope_dir: Path, proposal_path: Path) -> None:
    """Ensure high-churn runtime routing facts are sourced from live config snapshots.

    This prevents stale routing facts from being re-ingested purely from memory notes.
    """
    try:
        proposal = load_json(proposal_path)
    except Exception:
        return

    if proposal.get("scope") != "openclaw-runtime/ops":
        return

    routing = _read_openclaw_routing()
    snap_path = _write_routing_snapshot(ws=ws, scope_dir=scope_dir, r=routing)
    rel = snap_path.relative_to(ws).as_posix()

    primary = routing.get("primary") or "(unknown)"
    value = _format_routing_value(routing)

    items = proposal.get("items") or {}
    facts = items.get("confirmed_facts") or []
    if not isinstance(facts, list):
        facts = []

    def matches(it: dict) -> bool:
        return (it.get("fact") == "model.routing_routine_check") or (it.get("id") == "ops-routing-routine-check")

    patched = False
    for it in facts:
        if not isinstance(it, dict):
            continue
        if matches(it):
            it["id"] = it.get("id") or "ops-routing-routine-check"
            it["fact"] = "model.routing_routine_check"
            it["value"] = value
            it.setdefault("domain", "openclaw")
            it["ttl_days"] = int(it.get("ttl_days") or 14)
            it["evidence"] = [
                {
                    "path": rel,
                    "lines": "L1-L1",
                    "quote": f"primary: {primary}",
                    "ts": now_iso(),
                }
            ]
            patched = True
            break

    if not patched:
        facts.append(
            {
                "id": "ops-routing-routine-check",
                "fact": "model.routing_routine_check",
                "value": value,
                "domain": "openclaw",
                "ttl_days": 14,
                "evidence": [
                    {
                        "path": rel,
                        "lines": "L1-L1",
                        "quote": f"primary: {primary}",
                        "ts": now_iso(),
                    }
                ],
            }
        )

    items["confirmed_facts"] = facts
    proposal["items"] = items

    dump_json(proposal_path, proposal)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--phase", type=int, choices=[1, 2], default=None)
    ap.add_argument(
        "--scopes",
        default="user-profile/preferences,openclaw-runtime/ops,repos",
        help="comma-separated",
    )
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    phase = args.phase or int(os.environ.get("CONNECT_DOTS_PHASE", "1"))
    ws = Path(args.workspace).resolve()

    # Resolve script dir (this file lives in skills/connect-dots/scripts)
    scripts_dir = Path(__file__).resolve().parent
    skill_dir = scripts_dir.parent

    run_id = args.run_id or now_id()
    runs_root = ws / "tmp" / "connect-dots" / "runs" / run_id

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]

    # Where models live (feature-flag check handled by agent; we still write to tmp always)
    model_root = ws / "memory" / "internal" / "connect-dots"

    # Phase gate: if memory/internal/connect-dots/.disabled exists, we still do dry-run artifacts.
    disabled_flag = model_root / ".disabled"

    # For each scope, expect the LLM to have already written a proposal to a known location OR
    # the agentTurn message should instruct it to do so.
    ok_any = True

    for scope in scopes:
        scope_dir = resolve_scope_dir(runs_root, scope)
        proposal_path = scope_dir / "proposal.json"
        pre_path = scope_dir / "model.pre.json"
        post_path = scope_dir / "model.post.json"
        diff_path = scope_dir / "diff.txt"
        err_path = scope_dir / "error.log"

        # Always create an error log file (empty on success).
        write_text(err_path, "")

        # The agent must create proposal.json; if missing, fail closed for this scope.
        if not proposal_path.exists():
            write_text(err_path, f"ERROR: proposal.json missing for scope {scope}\n")
            ok_any = False
            continue

        # Patch high-churn runtime facts (must happen before schema validation + build_model evidence checks).
        if scope == "openclaw-runtime/ops":
            _patch_openclaw_runtime_proposal(ws=ws, scope_dir=scope_dir, proposal_path=proposal_path)

        # Validate proposal schema (fail closed)
        prop_schema = skill_dir / "references" / "proposal.schema.json"
        code, out, err = sh(
            [
                sys.executable,
                "-c",
                "import json, jsonschema, sys; jsonschema.validate(json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))); print('OK')",
                str(proposal_path),
                str(prop_schema),
            ],
            cwd=ws,
            timeout=60,
        )
        if code != 0:
            write_text(err_path, f"ERROR: proposal schema invalid\n{err}\n")
            ok_any = False
            continue

        # Copy pre-model if exists
        model_path = model_root / scope / "model.json"
        if model_path.exists():
            pre_path.parent.mkdir(parents=True, exist_ok=True)
            pre_path.write_text(model_path.read_text(encoding="utf-8"), encoding="utf-8")

        # Always compute diff in phase 1 by simulating apply into a temp file.
        tmp_model = scope_dir / "model.tmp.json"

        # If storage disabled, we still simulate apply/diff; apply is a no-op.
        apply_allowed = (phase == 2) and (not disabled_flag.exists())

        # Build into tmp_model (fail closed if citations invalid)
        code, out, err = sh(
            [
                sys.executable,
                str(scripts_dir / "build_model.py"),
                "--scope",
                scope,
                "--workspace",
                str(ws),
                "--model",
                str(tmp_model),
                "--proposal",
                str(proposal_path),
            ],
            cwd=ws,
            timeout=600,
        )
        if code != 0:
            write_text(err_path, f"ERROR: build_model failed (dry-run)\n{err}\n")
            ok_any = False
            continue

        # Diff: prev vs tmp_model
        if pre_path.exists():
            code, d_out, d_err = sh(
                [
                    sys.executable,
                    str(scripts_dir / "model_diff.py"),
                    "--prev",
                    str(pre_path),
                    "--cur",
                    str(tmp_model),
                ],
                cwd=ws,
                timeout=60,
            )
            if code != 0:
                write_text(err_path, f"ERROR: model_diff failed\n{d_err}\n")
                ok_any = False
                continue
            write_text(diff_path, d_out)
        else:
            write_text(diff_path, "+ added initial snapshot\n")

        if phase == 1 or not apply_allowed:
            # No writes to model.json
            continue

        # Phase 2 apply: write tmp_model -> model.json atomically by calling build_model again against real path.
        # (We re-run build_model to avoid copying an unvalidated file; it re-validates citations.)
        code, out, err = sh(
            [
                sys.executable,
                str(scripts_dir / "build_model.py"),
                "--scope",
                scope,
                "--workspace",
                str(ws),
                "--model",
                str(model_path),
                "--proposal",
                str(proposal_path),
                "--snapshot-out",
                str(post_path),
            ],
            cwd=ws,
            timeout=600,
        )
        if code != 0:
            write_text(err_path, f"ERROR: build_model failed (apply)\n{err}\n")
            ok_any = False
            continue

    return 0 if ok_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
