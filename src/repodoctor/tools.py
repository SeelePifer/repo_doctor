import sqlite3

from repodoctor.models import Span, ToolResult
from repodoctor.search import hybrid_search
from repodoctor.textutil import clamp_text

MAX_READ_LINES = 200


def read_tools() -> list[dict]:
    return [
        _tool(
            "search",
            "Lexical search plus hashed token similarity over indexed chunks. These are not neural embeddings. Returns path and line spans.",
            {"query": {"type": "string"}, "limit": {"type": "integer"}},
            ["query"],
        ),
        _tool(
            "read_file",
            "Read an inclusive line range from an indexed file. start_line and end_line are required.",
            {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            ["path", "start_line", "end_line"],
        ),
        _tool(
            "symbols",
            "Find functions, classes, and methods by name.",
            {"name": {"type": "string"}},
            ["name"],
        ),
        _tool(
            "importers",
            "List files that import a module or symbol name.",
            {"name": {"type": "string"}},
            ["name"],
        ),
        _tool(
            "entry_points",
            "List repository entry points such as __main__, project scripts, and package.json scripts.",
            {},
            [],
        ),
        _tool(
            "repo_map",
            "Summarize tracked files and their top-level symbols.",
            {},
            [],
        ),
    ]


def dispatch_tool(connection: sqlite3.Connection, name: str, args: dict) -> ToolResult:
    try:
        if name == "search":
            return _search(connection, str(args.get("query", "")), int(args.get("limit", 8) or 8))
        if name == "read_file":
            return _read_file(
                connection,
                str(args.get("path", "")),
                args.get("start_line"),
                args.get("end_line"),
            )
        if name == "symbols":
            return _symbols(connection, str(args.get("name", "")))
        if name == "importers":
            return _importers(connection, str(args.get("name", "")))
        if name == "entry_points":
            return _entry_points(connection)
        if name == "repo_map":
            return _repo_map(connection)
    except (TypeError, ValueError) as exc:
        return ToolResult(tool=name, summary=str(exc), spans=[])
    return ToolResult(tool=name, summary=f"Unknown tool: {name}", spans=[])


def default_test_command(connection: sqlite3.Connection) -> str:
    rows = connection.execute("SELECT path FROM files").fetchall()
    paths = [str(row["path"]) for row in rows]
    if any(path.endswith(".py") for path in paths):
        return "pytest -q"
    if "package.json" in paths:
        return "npm test"
    return "pytest -q"


def importer_risks(connection: sqlite3.Connection, files: list[str]) -> list[str]:
    risks: list[str] = []
    for path in files:
        symbols = connection.execute(
            """
            SELECT s.name
            FROM symbols s
            JOIN files f ON f.id = s.file_id
            WHERE f.path = ?
            """,
            (path,),
        ).fetchall()
        for symbol in symbols:
            rows = connection.execute(
                """
                SELECT f.path
                FROM imports i
                JOIN files f ON f.id = i.file_id
                WHERE f.path != ?
                  AND (i.imported_name = ? OR i.local_name = ? OR i.module = ?)
                """,
                (path, symbol["name"], symbol["name"], symbol["name"]),
            ).fetchall()
            importers = []
            for row in rows:
                importer = str(row["path"])
                if importer not in importers:
                    importers.append(importer)
            if not importers:
                continue
            shown = ", ".join(importers[:8])
            risk = f"{path}:{symbol['name']} is imported by {shown}"
            if risk not in risks:
                risks.append(risk)
    return risks


def _search(connection: sqlite3.Connection, query: str, limit: int) -> ToolResult:
    if not query.strip():
        return ToolResult(tool="search", summary="query is required", spans=[])
    hits, note = hybrid_search(connection, query, limit=max(1, min(limit, 20)))
    spans = [_span_from_text(hit.path, hit.start_line, hit.text) for hit in hits]
    return ToolResult(tool="search", summary=f"{len(spans)} hits ({note})", spans=spans)


def _read_file(connection: sqlite3.Connection, path: str, start_line: object, end_line: object) -> ToolResult:
    if start_line is None or end_line is None:
        return ToolResult(tool="read_file", summary="start_line and end_line are required", spans=[])
    start = int(start_line)
    end = int(end_line)
    row = _file_row(connection, path)
    if row is None:
        return ToolResult(tool="read_file", summary=f"file not in index: {path}", spans=[])
    line_count = int(row["line_count"])
    if start < 1 or end < start:
        return ToolResult(tool="read_file", summary="invalid line range", spans=[])
    if end - start + 1 > MAX_READ_LINES:
        end = start + MAX_READ_LINES - 1
    end = min(end, line_count)
    if start > line_count:
        return ToolResult(tool="read_file", summary="start_line is past the end of the file", spans=[])
    lines = str(row["text"]).splitlines()
    text = "\n".join(lines[start - 1 : end])
    span = Span(path=str(row["path"]), start_line=start, end_line=end, text=text)
    return ToolResult(tool="read_file", summary=f"{row['path']}:{start}-{end}", spans=[span])


def _symbols(connection: sqlite3.Connection, name: str) -> ToolResult:
    if not name.strip():
        return ToolResult(tool="symbols", summary="name is required", spans=[])
    rows = connection.execute(
        """
        SELECT f.path, f.text, s.name, s.kind, s.start_line, s.end_line, s.signature
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE s.name LIKE ? ESCAPE '\\' OR s.signature LIKE ? ESCAPE '\\'
        ORDER BY f.path, s.start_line
        LIMIT 30
        """,
        (_like_contains(name), _like_contains(name)),
    ).fetchall()
    spans: list[Span] = []
    for row in rows:
        end_line = min(int(row["end_line"]), int(row["start_line"]) + 39)
        lines = str(row["text"]).splitlines()
        text = "\n".join(lines[int(row["start_line"]) - 1 : end_line])
        spans.append(
            Span(path=str(row["path"]), start_line=int(row["start_line"]), end_line=end_line, text=clamp_text(text))
        )
    return ToolResult(tool="symbols", summary=f"{len(spans)} symbols", spans=spans)


def _importers(connection: sqlite3.Connection, name: str) -> ToolResult:
    if not name.strip():
        return ToolResult(tool="importers", summary="name is required", spans=[])
    rows = connection.execute(
        """
        SELECT f.path, f.text, i.module, i.imported_name, i.local_name, i.line
        FROM imports i
        JOIN files f ON f.id = i.file_id
        WHERE i.imported_name = ? OR i.local_name = ? OR i.module = ? OR i.module LIKE ? ESCAPE '\\'
        ORDER BY f.path, i.line
        LIMIT 40
        """,
        (name, name, name, f"%.{_like_literal(name)}"),
    ).fetchall()
    spans: list[Span] = []
    for row in rows:
        lines = str(row["text"]).splitlines()
        line = int(row["line"])
        text = lines[line - 1] if 0 < line <= len(lines) else ""
        spans.append(Span(path=str(row["path"]), start_line=line, end_line=line, text=text))
    return ToolResult(tool="importers", summary=f"{len(spans)} imports", spans=spans)


def _entry_points(connection: sqlite3.Connection) -> ToolResult:
    rows = connection.execute(
        """
        SELECT f.path, f.text, e.kind, e.detail, e.line
        FROM entry_points e
        JOIN files f ON f.id = e.file_id
        ORDER BY f.path, e.line
        """
    ).fetchall()
    spans: list[Span] = []
    for row in rows:
        lines = str(row["text"]).splitlines()
        line = int(row["line"])
        text = lines[line - 1] if 0 < line <= len(lines) else str(row["detail"])
        spans.append(Span(path=str(row["path"]), start_line=line, end_line=line, text=text))
    return ToolResult(tool="entry_points", summary=f"{len(spans)} entry points", spans=spans)


def _repo_map(connection: sqlite3.Connection) -> ToolResult:
    files = connection.execute("SELECT id, path FROM files ORDER BY path LIMIT 80").fetchall()
    spans: list[Span] = []
    for file_row in files:
        symbols = connection.execute(
            """
            SELECT name, kind, start_line, signature
            FROM symbols
            WHERE file_id = ?
            ORDER BY start_line
            LIMIT 8
            """,
            (int(file_row["id"]),),
        ).fetchall()
        if not symbols:
            spans.append(Span(path=str(file_row["path"]), start_line=1, end_line=1, text=str(file_row["path"])))
            continue
        for symbol in symbols:
            spans.append(
                Span(
                    path=str(file_row["path"]),
                    start_line=int(symbol["start_line"]),
                    end_line=int(symbol["start_line"]),
                    text=str(symbol["signature"]),
                )
            )
    return ToolResult(tool="repo_map", summary=f"{len(files)} files", spans=spans)


def _file_row(connection: sqlite3.Connection, path: str):
    normalized = path.replace("\\", "/").lstrip("./")
    return connection.execute("SELECT path, text, line_count FROM files WHERE path = ?", (normalized,)).fetchone()


def _span_from_text(path: str, start_line: int, text: str) -> Span:
    clipped = clamp_text(text)
    line_count = clipped.count("\n") + 1 if clipped else 1
    return Span(path=path, start_line=start_line, end_line=start_line + line_count - 1, text=clipped)


def _like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_contains(value: str) -> str:
    return f"%{_like_literal(value)}%"


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
