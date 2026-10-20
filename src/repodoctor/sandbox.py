import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from repodoctor.config import project_root, sandbox_image
from repodoctor.errors import SandboxError
from repodoctor.gitutil import head_sha
from repodoctor.models import ChangePlan, Verification
from repodoctor.textutil import normalize_repo_path


def assess_verification(
    *,
    patch_applied: bool,
    exit_code: int | None,
    changed_files: list[str],
    planned_files: list[str],
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not patch_applied:
        failures.append("patch_failed")
        return False, failures
    if exit_code != 0:
        failures.append("tests_failed")
    planned = {normalize_repo_path(path) for path in planned_files}
    extra = [normalize_repo_path(path) for path in changed_files if normalize_repo_path(path) not in planned]
    if extra:
        failures.append("unplanned_files")
    return (not failures, failures)


def validate_test_command(command: str) -> str:
    text = command.strip()
    if not text:
        raise SandboxError("Test command is empty.")
    if any(char in text for char in "\n\r;&|`$<>(){}"):
        raise SandboxError(
            "Test command contains shell syntax. Use pytest, python -m pytest, npm test, or node --test."
        )
    try:
        parts = shlex.split(text, posix=True)
    except ValueError as exc:
        raise SandboxError("Test command could not be parsed.") from exc
    if not _command_allowed(parts):
        raise SandboxError(
            "Test command is not allowed. Use pytest, python -m pytest, npm test, or node --test."
        )
    return text


def verify_plan(repo: Path, plan: ChangePlan, timeout_seconds: int = 180) -> Verification:
    if not plan.diff.strip():
        return Verification(
            passed=False,
            patch_applied=False,
            planned_files=plan.files,
            failures=["patch_failed"],
            stderr="The plan does not include a diff.",
        )
    try:
        command = validate_test_command(plan.test_command)
    except SandboxError as exc:
        return Verification(
            passed=False,
            patch_applied=False,
            planned_files=plan.files,
            failures=["command_rejected"],
            stderr=str(exc),
        )
    _require_docker()
    _ensure_image()
    with tempfile.TemporaryDirectory(prefix="repodoctor-") as temporary:
        root = Path(temporary)
        clone = root / "repo"
        patch_dir = root / "patch"
        patch_dir.mkdir()
        _clone_at_head(repo, clone)
        (patch_dir / "patch.diff").write_text(plan.diff, encoding="utf-8", newline="\n")
        (patch_dir / "cmd.sh").write_text(command + "\n", encoding="utf-8", newline="\n")
        (patch_dir / "run.sh").write_text(_RUN_SCRIPT, encoding="utf-8", newline="\n")
        completed = _run_container(clone, patch_dir, timeout_seconds)
        if not (patch_dir / "applied.txt").exists():
            detail = (completed.stderr or completed.stdout or "Sandbox produced no result.").strip()
            raise SandboxError(detail[-2000:])
        return _read_result(patch_dir, plan.files)


def docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _command_allowed(parts: list[str]) -> bool:
    if not parts:
        return False
    program = PurePosixPath(parts[0]).name.lower()
    if program in {"pytest", "py.test"}:
        return True
    if program in {"python", "python3"}:
        return len(parts) >= 3 and parts[1] == "-m" and parts[2] == "pytest"
    if program == "npm":
        return parts[1:] in (["test"], ["run", "test"])
    if program == "node":
        return _is_node_test(parts[1:])
    return False


def _is_node_test(args: list[str]) -> bool:
    allowed_flags = {"--test", "--experimental-strip-types"}
    saw_test = False
    for arg in args:
        if arg == "--test":
            saw_test = True
            continue
        if arg.startswith("-") and arg not in allowed_flags:
            return False
    return saw_test


def _require_docker() -> None:
    if docker_available():
        return
    raise SandboxError("Docker is not available. Start Docker Desktop and retry.")


def _ensure_image() -> None:
    image = sandbox_image()
    inspect = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True)
    if inspect.returncode == 0:
        return
    dockerfile = project_root() / "docker" / "sandbox.Dockerfile"
    if not dockerfile.exists():
        raise SandboxError(f"Sandbox Dockerfile not found: {dockerfile}")
    print(f"Building sandbox image {image}. The first build can take a few minutes.")
    build = subprocess.run(
        ["docker", "build", "-t", image, "-f", str(dockerfile), str(dockerfile.parent)],
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        detail = (build.stderr or build.stdout)[-2000:]
        raise SandboxError(f"Docker image build failed.\n{detail}")


def _clone_at_head(repo: Path, destination: Path) -> None:
    sha = head_sha(repo)
    completed = subprocess.run(
        ["git", "clone", "--local", "-c", "core.autocrlf=false", str(repo), str(destination)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SandboxError(detail or "git clone failed")
    checkout = subprocess.run(
        ["git", "-C", str(destination), "checkout", "--detach", sha],
        capture_output=True,
        text=True,
    )
    if checkout.returncode != 0:
        detail = checkout.stderr.strip() or checkout.stdout.strip()
        raise SandboxError(detail or "git checkout failed")


def _run_container(clone: Path, patch_dir: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    image = sandbox_image()
    name = f"repodoctor-{patch_dir.parent.name}"[:60]
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "-v",
        _mount(clone, "/work"),
        "-v",
        _mount(patch_dir, "/patch"),
        image,
        "sh",
        "/patch/run.sh",
    ]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        raise SandboxError("Docker is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)
        raise SandboxError(f"Sandbox timed out after {timeout_seconds} seconds.") from exc


def _read_result(patch_dir: Path, planned_files: list[str]) -> Verification:
    applied = (patch_dir / "applied.txt").read_text(encoding="utf-8").strip() == "1" if (patch_dir / "applied.txt").exists() else False
    exit_code = _read_int(patch_dir / "exit_code.txt")
    changed = _read_lines(patch_dir / "changed.txt")
    stdout = _clip(patch_dir / "stdout.txt")
    stderr = _clip(patch_dir / "stderr.txt")
    passed, failures = assess_verification(
        patch_applied=applied,
        exit_code=exit_code,
        changed_files=changed,
        planned_files=planned_files,
    )
    return Verification(
        passed=passed,
        patch_applied=applied,
        exit_code=exit_code,
        changed_files=changed,
        planned_files=[normalize_repo_path(path) for path in planned_files],
        failures=failures,
        stdout=stdout,
        stderr=stderr,
    )


def _read_int(path: Path) -> int | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _clip(path: Path, limit: int = 20000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[-limit:]


_RUN_SCRIPT = """#!/bin/sh
cd /work || exit 2
git apply --whitespace=nowarn /patch/patch.diff > /patch/apply_stdout.txt 2> /patch/apply_stderr.txt
apply_status=$?
if [ "$apply_status" -ne 0 ]; then
  echo 0 > /patch/applied.txt
  echo "$apply_status" > /patch/exit_code.txt
  cat /patch/apply_stderr.txt >> /patch/stderr.txt
  exit "$apply_status"
fi
echo 1 > /patch/applied.txt
git diff --name-only > /patch/changed.txt
sh /patch/cmd.sh > /patch/stdout.txt 2> /patch/stderr.txt
echo $? > /patch/exit_code.txt
"""


def sandbox_executable() -> str | None:
    return shutil.which("docker")


def _mount(host: Path, container: str) -> str:
    resolved = str(host.resolve())
    if len(resolved) >= 2 and resolved[1] == ":":
        drive = resolved[0].lower()
        rest = resolved[2:].replace("\\", "/")
        return f"//{drive}{rest}:{container}"
    return f"{host.resolve().as_posix()}:{container}"
