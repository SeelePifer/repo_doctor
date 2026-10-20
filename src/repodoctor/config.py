import hashlib
import os
from pathlib import Path

from repodoctor.errors import RepoDoctorError


def load_env() -> None:
    path = project_root() / ".env"
    if not path.exists():
        return
    apply_env_text(path.read_text(encoding="utf-8"))


def apply_env_text(text: str) -> None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        name = key.strip()
        if not name:
            continue
        os.environ[name] = value.strip().strip('"').strip("'")


def api_token() -> str:
    load_env()
    return os.environ.get("REPODOCTOR_API_TOKEN", "")


def token_required() -> bool:
    return os.environ.get("REPODOCTOR_REQUIRE_TOKEN") == "1"


def is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def api_key() -> str:
    load_env()
    return os.environ.get("XAI_API_KEY", "")


def chat_model() -> str:
    load_env()
    return os.environ.get("REPODOCTOR_CHAT_MODEL", "grok-4")


def embed_model() -> str:
    return "local-tokens"


def sandbox_image() -> str:
    load_env()
    return os.environ.get("REPODOCTOR_SANDBOX_IMAGE", "repodoctor-sandbox")


def data_dir() -> Path:
    load_env()
    override = os.environ.get("REPODOCTOR_DATA")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".repodoctor"


def index_db_path(repo: Path, commit_sha: str) -> Path:
    key = hashlib.sha256(f"{repo.resolve()}|{commit_sha}".encode()).hexdigest()[:24]
    return data_dir() / "indexes" / key / "index.sqlite"


def project_root() -> Path:
    packaged = Path(__file__).resolve().parents[2]
    if (packaged / "docker" / "sandbox.Dockerfile").exists():
        return packaged
    cwd = Path.cwd()
    if (cwd / "docker" / "sandbox.Dockerfile").exists():
        return cwd
    raise RepoDoctorError("RepoDoctor project files were not found. Run commands from the repository root.")


def fixtures_root() -> Path:
    root = project_root() / "tests" / "fixtures"
    if root.exists():
        return root
    raise RepoDoctorError("Fixture directory not found. Run repodoctor eval from the repository root.")
