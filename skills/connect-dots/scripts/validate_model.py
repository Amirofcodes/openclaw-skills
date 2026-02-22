#!/usr/bin/env python3
"""Validate a connect-dots model.json against JSON Schema.

Fail closed: exits non-zero on any schema mismatch.

Usage:
  validate_model.py --model <path> [--schema <schemaPath>]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _lib import load_json, validate_or_die


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument(
        "--schema",
        default=str(Path(__file__).resolve().parent.parent / "references" / "model.schema.json"),
    )
    args = ap.parse_args()

    model_path = Path(args.model)
    schema_path = Path(args.schema)
    model = load_json(model_path)
    validate_or_die(model, schema_path, label=f"model ({model_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
