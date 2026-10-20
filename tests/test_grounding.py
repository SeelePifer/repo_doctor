from pathlib import Path

from repodoctor.config import index_db_path
from repodoctor.db import connect
from repodoctor.gitutil import head_sha
from repodoctor.grounding import score_citations
from repodoctor.indexer import index_repo
from repodoctor.models import Citation, Span, ToolEvent, ToolResult
from tests.repo_factory import write_repo


def _indexed(tmp_path: Path):
    write_repo(tmp_path, {"calc.py": "def multiply(left: int, right: int) -> int:\n    return left + right\n"})
    index_repo(tmp_path, embed=False)
    return connect(index_db_path(tmp_path, head_sha(tmp_path)))


def _event(text: str, start: int, end: int) -> list[ToolEvent]:
    span = Span(path="calc.py", start_line=start, end_line=end, text=text)
    return [
        ToolEvent(
            seq=1,
            tool="read_file",
            args={"path": "calc.py"},
            result=ToolResult(tool="read_file", summary="ok", spans=[span]),
        )
    ]


def test_supported_citation_matches_file_and_tool_span(tmp_path: Path) -> None:
    connection = _indexed(tmp_path)
    try:
        citation = Citation(
            path="calc.py",
            start_line=2,
            end_line=2,
            snippet="return left + right",
            reason="The return expression is in the function body.",
        )
        report = score_citations(
            connection,
            [citation],
            _event("    return left + right", 2, 2),
        )
        assert report.supported == 1
        assert report.cited == 1
        assert report.checks[0].failures == []
    finally:
        connection.close()


def test_bad_snippet_and_missing_provenance_fail(tmp_path: Path) -> None:
    connection = _indexed(tmp_path)
    try:
        citation = Citation(
            path="calc.py",
            start_line=2,
            end_line=2,
            snippet="return left * right",
            reason="Invented a product.",
        )
        report = score_citations(connection, [citation], _event("    return left + right", 2, 2))
        assert report.supported == 0
        assert "snippet_mismatch" in report.checks[0].failures
        assert "no_provenance" in report.checks[0].failures
    finally:
        connection.close()


def test_wide_citation_range_fails(tmp_path: Path) -> None:
    connection = _indexed(tmp_path)
    try:
        citation = Citation(
            path="calc.py",
            start_line=1,
            end_line=2,
            snippet="return left + right",
            reason="The snippet is one line inside a wider range.",
        )
        report = score_citations(
            connection,
            [citation],
            _event("def multiply(left: int, right: int) -> int:\n    return left + right", 1, 2),
        )
        assert report.supported == 0
        assert "wide_span" in report.checks[0].failures
    finally:
        connection.close()


def test_missing_file_fails(tmp_path: Path) -> None:
    connection = _indexed(tmp_path)
    try:
        citation = Citation(
            path="missing.py",
            start_line=1,
            end_line=1,
            snippet="nope",
            reason="Not in the repo.",
        )
        report = score_citations(connection, [citation], [])
        assert report.checks[0].failures[0] == "file_missing"
        assert "no_provenance" in report.checks[0].failures
    finally:
        connection.close()
