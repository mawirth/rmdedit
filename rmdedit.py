#!/usr/bin/env python3
"""Compatibility wrapper for running rmdedit from a source checkout."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from rmdedit.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
