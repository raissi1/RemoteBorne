#!/usr/bin/env python3
"""Fast, side-effect-free pre-flight checks for an RBM delivery."""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys
import tokenize


ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
REQUIRED_ENTRYPOINTS = (
    SRC / "RemoteBorneManager.py",
    SRC / "app.py",
    SRC / "ssh_manager.py",
    SRC / "test_sequence.py",
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def check_no_duplicate_manager() -> None:
    duplicate = SRC / "RemoteBorneManager - Copy.py"
    if duplicate.exists():
        fail(f"Duplicate manager file found: {duplicate}")
    print("[OK] No duplicate RemoteBorneManager copy file")


def check_python_syntax() -> None:
    py_files = sorted(SRC.glob("*.py"))
    if not py_files:
        fail("No Python files found in src/")
    for path in py_files:
        try:
            with tokenize.open(path) as handle:
                ast.parse(handle.read(), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            fail(f"Syntax or encoding error in {path}: {exc}")
    print(f"[OK] AST syntax check passed for {len(py_files)} files")


def check_entrypoints() -> None:
    missing = [str(path) for path in REQUIRED_ENTRYPOINTS if not path.exists()]
    if missing:
        fail(f"Missing critical files: {', '.join(missing)}")
    print("[OK] Critical entrypoints exist")


def check_readable_test_sequence() -> None:
    source = (SRC / "test_sequence.py").read_text(encoding="utf-8")
    blocked_markers = ("exec(_marshal", "_PAYLOAD =", "marshal.loads")
    found = [marker for marker in blocked_markers if marker in source]
    if found:
        fail("Test Sequence must remain auditable; blocked marker(s): " + ", ".join(found))
    if "class TestSequenceWindow" not in source:
        fail("TestSequenceWindow class is missing")
    print("[OK] Test Sequence source is readable and auditable")


def check_v16_documents() -> None:
    for language in ("FR", "EN"):
        folder = SRC / "documents" / language
        documents = sorted(folder.glob("RBM_V16_*.docx"))
        if len(documents) != 2:
            fail(
                f"Expected two V16 delivery documents in {folder}; found {len(documents)}"
            )
    print("[OK] V16 EN/FR delivery documents are present")


def check_regression_tests() -> None:
    """Run the headless V16.1 checks without leaving bytecode in the project."""
    tests = ROOT / "tests"
    if not tests.is_dir():
        fail("Regression test folder is missing")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        details = (result.stdout + result.stderr).strip()
        fail(f"Regression tests failed:\n{details}")
    print("[OK] Headless V16.1 regression tests passed")


def main() -> int:
    check_no_duplicate_manager()
    check_python_syntax()
    check_entrypoints()
    check_readable_test_sequence()
    check_v16_documents()
    check_regression_tests()
    print("\n[SUCCESS] Quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
