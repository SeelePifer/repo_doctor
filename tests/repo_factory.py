import subprocess
from pathlib import Path


def write_repo(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True, text=True)
    hooks = root / ".empty-hooks"
    hooks.mkdir(exist_ok=True)
    subprocess.run(
        [
            "git",
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
            "init",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return root
