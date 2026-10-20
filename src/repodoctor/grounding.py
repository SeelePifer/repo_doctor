import json
import sqlite3

from pydantic import ValidationError

from repodoctor.models import Answer, Citation, CitationCheck, GroundingReport, ToolEvent
from repodoctor.textutil import line_window, normalize_repo_path, snippet_matches


def score_citations(
    connection: sqlite3.Connection,
    citations: list[Citation],
    events: list[ToolEvent],
) -> GroundingReport:
    observations = [span for event in events for span in event.result.spans]
    checks: list[CitationCheck] = []
    for citation in citations:
        failures: list[str] = []
        actual_text: str | None = None
        path = normalize_repo_path(citation.path)
        row = connection.execute(
            "SELECT text, line_count FROM files WHERE path = ?",
            (path,),
        ).fetchone()
        if row is None:
            failures.append("file_missing")
        elif citation.start_line < 1 or citation.end_line < citation.start_line or citation.end_line > int(row["line_count"]):
            failures.append("line_range")
        else:
            if _span_is_wider_than_snippet(citation):
                failures.append("wide_span")
            actual_text = line_window(str(row["text"]), citation.start_line, citation.end_line)
            if not snippet_matches(citation.snippet, actual_text):
                failures.append("snippet_mismatch")
        if not _has_provenance(path, citation, observations):
            failures.append("no_provenance")
        checks.append(
            CitationCheck(
                citation=citation,
                supported=not failures,
                failures=failures,
                actual_text=actual_text,
            )
        )
    supported = sum(1 for check in checks if check.supported)
    cited = len(checks)
    rate = 0.0 if cited == 0 else supported / cited
    return GroundingReport(supported=supported, cited=cited, support_rate=rate, checks=checks)


def coerce_answer(content: str) -> Answer | None:
    payload = _json_object(content)
    if payload is None:
        return None
    try:
        return Answer.model_validate(payload)
    except ValidationError:
        return None


def _span_is_wider_than_snippet(citation: Citation) -> bool:
    cited_lines = citation.end_line - citation.start_line + 1
    snippet_lines = max(len(citation.snippet.splitlines()), 1)
    return cited_lines > snippet_lines


def _has_provenance(path: str, citation: Citation, observations) -> bool:
    for span in observations:
        if normalize_repo_path(span.path) != path:
            continue
        if citation.start_line < span.start_line or citation.end_line > span.end_line:
            continue
        if snippet_matches(citation.snippet, span.text):
            return True
    return False


def _json_object(content: str) -> dict | None:
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload
