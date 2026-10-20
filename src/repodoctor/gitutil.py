import subprocess
from pathlib import Path

from repodoctor.errors import GitError


def run_git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("Git is not installed or not on PATH.") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitError(detail or f"git {' '.join(args)} failed")
    return result


def require_repo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise GitError(f"Not a directory: {resolved}")
    inside = run_git(resolved, ["rev-parse", "--is-inside-work-tree"])
    if inside.stdout.strip() != "true":
        raise GitError(f"Not a git repository: {resolved}")
    return resolved


def head_sha(repo: Path) -> str:
    result = run_git(repo, ["rev-parse", "HEAD"], check=False)
    if result.returncode != 0:
        raise GitError(f"{repo} has no commits. Commit the files you want RepoDoctor to index.")
    return result.stdout.strip()


def tracked_files(repo: Path) -> list[str]:
    result = run_git(repo, ["ls-files", "-z"])
    return [item for item in result.stdout.split("\0") if item]


def worktree_files(repo: Path) -> list[str]:
    result = run_git(repo, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    return [item for item in result.stdout.split("\0") if item]


def commit_snapshot(repo: Path, message: str) -> None:
    if not (repo / ".git").exists():
        run_git(repo, ["init"])
    run_git(repo, ["add", "-A"])
    status = run_git(repo, ["status", "--porcelain"])
    head = run_git(repo, ["rev-parse", "--verify", "HEAD"], check=False)
    if not status.stdout.strip() and head.returncode == 0:
        return
    hooks = repo / ".empty-hooks"
    hooks.mkdir(exist_ok=True)
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.email=repodoctor@example.com",
                "-c",
                "user.name=RepoDoctor",
                "-c",
                f"core.hooksPath={hooks}",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                message,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("Git is not installed or not on PATH.") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GitError(detail or "git commit failed")
