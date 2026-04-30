#!/usr/bin/env python3
"""Minimal quality gate for RemoteBorne (fast local pre-flight checks).

Goal: reduce recurring regressions before packaging/deployment.
"""

from __future__ import annotations

import pathlib
import py_compile
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def check_no_duplicate_manager() -> None:
    duplicate = SRC / "RemoteBorneManager - Copy.py"
    if duplicate.exists():
        fail(f"Duplicate manager file found: {duplicate}")
    print("[OK] No duplicate RemoteBorneManager copy file")


def check_python_compiles() -> None:
    py_files = sorted(SRC.glob("*.py"))
    if not py_files:
        fail("No python files found in src/")

    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as exc:
            fail(f"Syntax/compile error in {p}: {exc}")
    print(f"[OK] py_compile passed for {len(py_files)} files")


def check_critical_entrypoints() -> None:
    required = [SRC / "RemoteBorneManager.py", SRC / "app.py", SRC / "ssh_manager.py"]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        fail(f"Missing critical files: {', '.join(missing)}")
    print("[OK] Critical entrypoints exist")


def main() -> int:
    check_no_duplicate_manager()
    check_python_compiles()
    check_critical_entrypoints()
    print("\n[SUCCESS] Quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
