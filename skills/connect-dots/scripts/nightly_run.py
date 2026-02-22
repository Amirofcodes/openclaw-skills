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
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now_id() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


def sh(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    # the agentTurn message should instruct it to do so. We read from tmp first.
    ok_any = True

    for scope in scopes:
        scope_dir = runs_root / scope.replace("/", "_")
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
        # (We re-run build_model to avoid copying an unvalidated file; it re-validates citations.
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
