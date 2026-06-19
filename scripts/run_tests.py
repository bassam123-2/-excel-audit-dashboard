#!/usr/bin/env python
"""Run the full project test suite. Usage: python scripts/run_tests.py"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--tb=short",
        "-ra",
        str(ROOT / "accounts_app" / "tests"),
        str(ROOT / "audit_app" / "tests"),
        str(ROOT / "reports_app" / "tests"),
        str(ROOT / "tests"),
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
