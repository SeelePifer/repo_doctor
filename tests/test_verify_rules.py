import pytest

from repodoctor.errors import SandboxError
from repodoctor.sandbox import assess_verification, validate_test_command


def test_verification_passes_when_patch_tests_and_files_agree() -> None:
    passed, failures = assess_verification(
        patch_applied=True,
        exit_code=0,
        changed_files=["calc.py"],
        planned_files=["calc.py"],
    )
    assert passed
    assert failures == []


def test_verification_rejects_unplanned_files() -> None:
    passed, failures = assess_verification(
        patch_applied=True,
        exit_code=0,
        changed_files=["calc.py", "other.py"],
        planned_files=["calc.py"],
    )
    assert not passed
    assert failures == ["unplanned_files"]


def test_allowed_test_commands() -> None:
    assert validate_test_command("pytest -q") == "pytest -q"
    assert validate_test_command("python -m pytest") == "python -m pytest"
    assert validate_test_command("npm test") == "npm test"
    assert (
        validate_test_command("node --experimental-strip-types --test test/greet.test.ts")
        == "node --experimental-strip-types --test test/greet.test.ts"
    )


def test_shell_and_unknown_commands_are_rejected() -> None:
    with pytest.raises(SandboxError):
        validate_test_command("pytest -q; rm -rf /")
    with pytest.raises(SandboxError):
        validate_test_command("bash -c 'pytest'")
    with pytest.raises(SandboxError):
        validate_test_command("npm run build")


def test_verification_stops_when_patch_fails() -> None:
    passed, failures = assess_verification(
        patch_applied=False,
        exit_code=1,
        changed_files=[],
        planned_files=["calc.py"],
    )
    assert not passed
    assert failures == ["patch_failed"]
