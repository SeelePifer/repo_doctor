import difflib
from pathlib import Path

import pytest

from repodoctor.models import ChangePlan
from repodoctor.sandbox import docker_available, verify_plan
from repodoctor.gitutil import run_git
from tests.repo_factory import write_repo

CALC = """def add(left: int, right: int) -> int:
    return left + right


def multiply(left: int, right: int) -> int:
    return left + right
"""

TEST = """from calc import add, multiply


def test_add() -> None:
    assert add(2, 3) == 5


def test_multiply() -> None:
    assert multiply(2, 4) == 8
"""


@pytest.mark.skipif(not docker_available(), reason="Docker is not available")
def test_sandbox_applies_diff_without_touching_host(tmp_path: Path) -> None:
    write_repo(
        tmp_path,
        {
            "calc.py": CALC,
            "tests/test_calc.py": TEST,
            "pytest.ini": "[pytest]\npythonpath = .\n",
        },
    )
    original = (tmp_path / "calc.py").read_text(encoding="utf-8")
    fixed = original.replace(
        "def multiply(left: int, right: int) -> int:\n    return left + right",
        "def multiply(left: int, right: int) -> int:\n    return left * right",
        1,
    )
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile="a/calc.py",
            tofile="b/calc.py",
        )
    )
    plan = ChangePlan(
        goal="Return the product",
        steps=["Replace addition with multiplication"],
        files=["calc.py"],
        risks=[],
        test_command="pytest -q",
        diff=diff,
    )
    result = verify_plan(tmp_path, plan, timeout_seconds=300)
    assert result.passed, result.model_dump()
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == original
    status = run_git(tmp_path, ["status", "--porcelain"])
    assert status.stdout.strip() == ""
