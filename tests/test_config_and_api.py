import os
from pathlib import Path

from fastapi.testclient import TestClient

from repodoctor.config import apply_env_text
from repodoctor.db import connection_lock


def test_env_file_overrides_process_value(monkeypatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "stale")
    apply_env_text("XAI_API_KEY=from-file\n# comment\n")
    assert os.environ["XAI_API_KEY"] == "from-file"


def test_same_database_shares_one_lock(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite"
    assert connection_lock(path) is connection_lock(path)


def test_non_loopback_requires_token(monkeypatch) -> None:
    monkeypatch.setenv("REPODOCTOR_REQUIRE_TOKEN", "1")
    monkeypatch.setenv("REPODOCTOR_API_TOKEN", "secret")
    monkeypatch.setattr("repodoctor.api.probe_grok", lambda: (True, "ready"))
    from repodoctor.api import app

    client = TestClient(app)
    denied = client.get("/health")
    assert denied.status_code == 401
    allowed = client.get("/health", headers={"X-RepoDoctor-Token": "secret"})
    assert allowed.status_code == 200
    assert allowed.json()["grok_ok"] is True
