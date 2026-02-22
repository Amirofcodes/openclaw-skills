#!/usr/bin/env python3
"""Find a quote in a file and return an evidence line range.

This exists to make citations deterministic and reduce LLM error.

Usage:
  find_quote_lines.py --workspace /home/amiro/.openclaw/workspace \
    --path memory/2026-02-21.md --quote "Dual-bot setup" \
    [--window 1]

Output:
  L<start>-L<end>

Exit non-zero if quote not found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--path", required=True, help="workspace-relative")
    ap.add_argument("--quote", required=True)
    ap.add_argument("--window", type=int, default=1)
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    p = (ws / args.path).resolve()
    if not str(p).startswith(str(ws)):
        print("error: path escapes workspace", file=sys.stderr)
        return 2
    if not p.exists():
        print("error: file not found", file=sys.stderr)
        return 2

    q = args.quote.strip()
    if not q:
        print("error: empty quote", file=sys.stderr)
        return 2

    with p.open("r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    for i, line in enumerate(lines, start=1):
        if q in line:
            end = min(len(lines), i + max(1, args.window) - 1)
            sys.stdout.write(f"L{i}-L{end}\n")
            return 0

    # fallback: search whole file (multi-line snippets)
    full = "".join(lines)
    idx = full.find(q)
    if idx >= 0:
        # map to line
        upto = full[:idx]
        line_no = upto.count("\n") + 1
        end = min(len(lines), line_no + max(1, args.window) - 1)
        sys.stdout.write(f"L{line_no}-L{end}\n")
        return 0

    print("error: quote not found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
