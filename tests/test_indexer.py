from pathlib import Path

from repodoctor.db import connect
from repodoctor.gitutil import head_sha
from repodoctor.indexer import index_repo
from repodoctor.config import index_db_path
from repodoctor.tools import dispatch_tool
from tests.repo_factory import write_repo

CALC = '''def add(left: int, right: int) -> int:
    return left + right


def multiply(left: int, right: int) -> int:
    return left + right
'''

TEST = '''from calc import multiply


def test_multiply() -> None:
    assert multiply(2, 4) == 8
'''

MAIN = '''def main() -> None:
    print("run")


if __name__ == "__main__":
    main()
'''


def _repo(tmp_path: Path) -> Path:
    write_repo(
        tmp_path,
        {
            "calc.py": CALC,
            "tests/test_calc.py": TEST,
            "app/__main__.py": MAIN,
        },
    )
    (tmp_path / "untracked.txt").write_text("visible", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("secret", encoding="utf-8")
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("ignored.txt\n", encoding="utf-8")
    return tmp_path


def test_index_tracks_symbols_imports_and_entries(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    summary = index_repo(repo, embed=False)
    assert summary.files == 4
    assert summary.embed_status == "skipped"
    connection = connect(index_db_path(repo, head_sha(repo)))
    try:
        names = {row["name"] for row in connection.execute("SELECT name FROM symbols")}
        assert {"add", "multiply", "test_multiply", "main"} <= names
        imports = connection.execute(
            "SELECT module, imported_name, local_name FROM imports"
        ).fetchall()
        assert any(row["module"] == "calc" and row["imported_name"] == "multiply" for row in imports)
        kinds = {row["kind"] for row in connection.execute("SELECT kind FROM entry_points")}
        assert "module_main" in kinds
        assert "name_main" in kinds
        paths = {row["path"] for row in connection.execute("SELECT path FROM files")}
        assert "untracked.txt" in paths
        assert "ignored.txt" not in paths
        chunks = connection.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()
        assert int(chunks["count"]) >= 3
    finally:
        connection.close()


def test_search_and_importers_return_real_lines(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    index_repo(repo, embed=False)
    connection = connect(index_db_path(repo, head_sha(repo)))
    try:
        found = dispatch_tool(connection, "search", {"query": "multiply"})
        assert found.spans
        assert any("def multiply" in span.text for span in found.spans)
        importers = dispatch_tool(connection, "importers", {"name": "multiply"})
        assert any(span.path == "tests/test_calc.py" for span in importers.spans)
        read = dispatch_tool(
            connection,
            "read_file",
            {"path": "calc.py", "start_line": 5, "end_line": 6},
        )
        assert read.spans[0].text.splitlines()[0].startswith("def multiply")
        missing_range = dispatch_tool(connection, "read_file", {"path": "calc.py"})
        assert missing_range.spans == []
        wildcard = dispatch_tool(connection, "symbols", {"name": "%"})
        assert wildcard.spans == []
    finally:
        connection.close()


def test_reindex_keeps_previous_runs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    index_repo(repo, embed=False)
    database = index_db_path(repo, head_sha(repo))
    connection = connect(database)
    try:
        connection.execute(
            "INSERT INTO runs(id, kind, prompt, created_at) VALUES (?, ?, ?, ?)",
            ("keep-me", "ask", "where", "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()
    finally:
        connection.close()
    index_repo(repo, embed=False)
    connection = connect(database)
    try:
        row = connection.execute("SELECT id FROM runs WHERE id = ?", ("keep-me",)).fetchone()
        assert row is not None
        files = connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()
        assert int(files["count"]) == 4
    finally:
        connection.close()
