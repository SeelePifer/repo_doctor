import hashlib
import json
from pathlib import Path

import tomli

from repodoctor.config import index_db_path
from repodoctor.db import connection_lock, reset_index_content, set_meta
from repodoctor.gitutil import head_sha, require_repo, worktree_files
from repodoctor.models import IndexSummary
from repodoctor.parse import parse_source
from repodoctor.search import pack_vector, token_vector
from repodoctor.textutil import chunk_ranges

CHUNK_SIZE = 80
CHUNK_OVERLAP = 15
MAX_FILE_BYTES = 512_000
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".pyc",
    ".wasm",
    ".lock",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
}


def language_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".js", ".mjs", ".cjs", ".jsx"}:
        return "javascript"
    if suffix == ".ts":
        return "typescript"
    if suffix == ".tsx":
        return "tsx"
    return "text"


def index_repo(path: Path, embed: bool = True) -> IndexSummary:
    repo = require_repo(path)
    commit = head_sha(repo)
    database = index_db_path(repo, commit)
    with connection_lock(database):
        connection = reset_index_content(database)
        try:
            for relative in worktree_files(repo):
                _index_file(connection, repo, relative)
            embed_status = "skipped"
            if embed:
                _embed_chunks(connection)
                embed_status = "local-tokens"
            set_meta(connection, "repo_path", str(repo))
            set_meta(connection, "commit_sha", commit)
            set_meta(connection, "embed_status", embed_status)
            connection.commit()
            return _summary(connection, repo, commit, embed_status, database)
        finally:
            connection.close()


def _index_file(connection, repo: Path, relative: str) -> None:
    full = repo / relative
    if not full.is_file():
        return
    if full.suffix.lower() in BINARY_SUFFIXES:
        return
    data = full.read_bytes()
    if len(data) > MAX_FILE_BYTES or b"\0" in data[:8192]:
        return
    text = data.decode("utf-8", errors="replace").replace("\x00", "")
    language = language_for(relative)
    parsed = None
    if language != "text":
        try:
            parsed = parse_source(language, text)
        except Exception:
            language = "text"
    digest = hashlib.sha256(data).hexdigest()
    lines = text.splitlines()
    cursor = connection.execute(
        "INSERT INTO files(path, language, sha, line_count, text) VALUES (?, ?, ?, ?, ?)",
        (relative.replace("\\", "/"), language, digest, len(lines), text),
    )
    file_id = int(cursor.lastrowid)
    if parsed is not None:
        for symbol in parsed.symbols:
            connection.execute(
                """
                INSERT INTO symbols(file_id, name, kind, start_line, end_line, signature)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (file_id, symbol.name, symbol.kind, symbol.start_line, symbol.end_line, symbol.signature),
            )
        for item in parsed.imports:
            connection.execute(
                """
                INSERT INTO imports(file_id, module, imported_name, local_name, line)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_id, item.module, item.imported_name, item.local_name, item.line),
            )
    for kind, detail, line in _entry_points(relative, text):
        connection.execute(
            "INSERT INTO entry_points(file_id, kind, detail, line) VALUES (?, ?, ?, ?)",
            (file_id, kind, detail, line),
        )
    _insert_chunks(connection, file_id, relative.replace("\\", "/"), lines)


def _insert_chunks(connection, file_id: int, path: str, lines: list[str]) -> None:
    symbols = connection.execute(
        "SELECT name, start_line, end_line FROM symbols WHERE file_id = ?",
        (file_id,),
    ).fetchall()
    for start, end in chunk_ranges(len(lines), CHUNK_SIZE, CHUNK_OVERLAP):
        text = "\n".join(lines[start - 1 : end])
        names = [
            row["name"]
            for row in symbols
            if row["start_line"] <= end and row["end_line"] >= start
        ]
        cursor = connection.execute(
            "INSERT INTO chunks(file_id, start_line, end_line, text) VALUES (?, ?, ?, ?)",
            (file_id, start, end, text),
        )
        chunk_id = int(cursor.lastrowid)
        connection.execute(
            "INSERT INTO chunks_fts(rowid, path, text, symbol_names) VALUES (?, ?, ?, ?)",
            (chunk_id, path, text, " ".join(names)),
        )


def _entry_points(relative: str, text: str) -> list[tuple[str, str, int]]:
    path = relative.replace("\\", "/")
    found: list[tuple[str, str, int]] = []
    if path.endswith("__main__.py"):
        found.append(("module_main", path, 1))
    for index, line in enumerate(text.splitlines(), start=1):
        compact = line.replace(" ", "")
        if "if__name__==" in compact and "__main__" in compact:
            found.append(("name_main", line.strip(), index))
    if path.endswith("pyproject.toml"):
        found.extend(_pyproject_scripts(text))
    if path.endswith("package.json"):
        found.extend(_package_entries(text))
    return found


def _pyproject_scripts(text: str) -> list[tuple[str, str, int]]:
    try:
        data = tomli.loads(text)
    except tomli.TOMLDecodeError:
        return []
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return []
    lines = text.splitlines()
    found: list[tuple[str, str, int]] = []
    for name, target in scripts.items():
        found.append(("project_script", f"{name}: {target}", _line_containing(lines, str(name))))
    return found


def _package_entries(text: str) -> list[tuple[str, str, int]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    lines = text.splitlines()
    found: list[tuple[str, str, int]] = []
    main = data.get("main")
    if isinstance(main, str):
        found.append(("package_main", main, _line_containing(lines, '"main"')))
    bin_field = data.get("bin")
    if isinstance(bin_field, str):
        found.append(("package_bin", bin_field, _line_containing(lines, '"bin"')))
    elif isinstance(bin_field, dict):
        for name, target in bin_field.items():
            found.append(("package_bin", f"{name}: {target}", _line_containing(lines, '"bin"')))
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        for name, command in scripts.items():
            found.append(("package_script", f"{name}: {command}", _line_containing(lines, '"scripts"')))
    return found


def _line_containing(lines: list[str], needle: str) -> int:
    for index, line in enumerate(lines, start=1):
        if needle in line:
            return index
    return 1


def _embed_chunks(connection) -> None:
    rows = connection.execute("SELECT id, text FROM chunks ORDER BY id").fetchall()
    for row in rows:
        connection.execute(
            "INSERT INTO embeddings(chunk_id, vector) VALUES (?, ?)",
            (int(row["id"]), pack_vector(token_vector(str(row["text"])))),
        )


def _summary(connection, repo: Path, commit: str, embed_status: str, database: Path) -> IndexSummary:
    def count(table: str) -> int:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])

    return IndexSummary(
        path=str(repo),
        commit_sha=commit,
        files=count("files"),
        symbols=count("symbols"),
        imports=count("imports"),
        chunks=count("chunks"),
        entry_points=count("entry_points"),
        embed_status=embed_status,
        database=str(database),
    )
