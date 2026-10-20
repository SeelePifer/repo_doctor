import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from repodoctor.agent import run_agent
from repodoctor.config import index_db_path
from repodoctor.db import connect, connection_lock, get_meta
from repodoctor.errors import RepoDoctorError
from repodoctor.gitutil import head_sha, require_repo
from repodoctor.grounding import score_citations
from repodoctor.indexer import index_repo
from repodoctor.models import (
    AskResult,
    IndexSummary,
    PlanResult,
    RepoStatus,
    ToolEvent,
    VerifyResult,
)
from repodoctor.planner import parse_plan_json, run_planner
from repodoctor.sandbox import verify_plan


def status_for(path: Path) -> RepoStatus:
    repo = require_repo(path)
    commit = head_sha(repo)
    database = index_db_path(repo, commit)
    if not database.exists():
        return RepoStatus(indexed=False, path=str(repo), commit_sha=commit, summary=None)
    with connection_lock(database):
        connection = connect(database)
        try:
            summary = _summary_from_connection(connection, repo, commit, database)
        finally:
            connection.close()
    return RepoStatus(indexed=True, path=str(repo), commit_sha=commit, summary=summary)


def ask_question(path: Path, question: str) -> AskResult:
    if not question.strip():
        raise RepoDoctorError("Question is required.")
    repo = require_repo(path)
    database, commit = _index_path(repo)
    with connection_lock(database):
        connection = connect(database)
        try:
            run_id = _create_run(connection, "ask", question)
            answer, events = run_agent(connection, question)
            _save_events(connection, run_id, events)
            grounding = score_citations(connection, answer.citations, events)
            connection.execute(
                "UPDATE runs SET answer_json = ?, grounding_json = ? WHERE id = ?",
                (answer.model_dump_json(), grounding.model_dump_json(), run_id),
            )
            connection.commit()
            return AskResult(
                run_id=run_id,
                question=question,
                answer=answer,
                grounding=grounding,
                commit_sha=commit,
            )
        finally:
            connection.close()


def plan_change(path: Path, request: str) -> PlanResult:
    if not request.strip():
        raise RepoDoctorError("Change request is required.")
    repo = require_repo(path)
    database, commit = _index_path(repo)
    with connection_lock(database):
        connection = connect(database)
        try:
            run_id = _create_run(connection, "plan", request)
            plan, events = run_planner(connection, request)
            _save_events(connection, run_id, events)
            connection.execute(
                "UPDATE runs SET plan_json = ?, diff = ? WHERE id = ?",
                (plan.model_dump_json(), plan.diff, run_id),
            )
            connection.commit()
            return PlanResult(run_id=run_id, request=request, plan=plan, commit_sha=commit)
        finally:
            connection.close()


def verify_change(path: Path, run_id: str | None = None, timeout_seconds: int = 180) -> VerifyResult:
    repo = require_repo(path)
    database, commit = _index_path(repo)
    with connection_lock(database):
        connection = connect(database)
        try:
            row = _plan_row(connection, run_id)
            if row is None:
                raise RepoDoctorError("No change plan found. Run plan before verify.")
            plan = parse_plan_json(str(row["plan_json"]))
            verification = verify_plan(repo, plan, timeout_seconds=timeout_seconds)
            connection.execute(
                "UPDATE runs SET verify_json = ? WHERE id = ?",
                (verification.model_dump_json(), row["id"]),
            )
            connection.commit()
            return VerifyResult(run_id=str(row["id"]), verification=verification, commit_sha=commit)
        finally:
            connection.close()


def _index_path(repo: Path) -> tuple[Path, str]:
    commit = head_sha(repo)
    database = index_db_path(repo, commit)
    if not database.exists():
        raise RepoDoctorError(f"No index for {repo} at {commit}. Run: repodoctor index {repo}")
    return database, commit


def _summary_from_connection(
    connection: sqlite3.Connection,
    repo: Path,
    commit: str,
    database: Path,
) -> IndexSummary:
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
        embed_status=get_meta(connection, "embed_status") or "unknown",
        database=str(database),
    )


def _create_run(connection: sqlite3.Connection, kind: str, prompt: str) -> str:
    run_id = uuid4().hex
    connection.execute(
        "INSERT INTO runs(id, kind, prompt, created_at) VALUES (?, ?, ?, ?)",
        (run_id, kind, prompt, datetime.now(timezone.utc).isoformat()),
    )
    connection.commit()
    return run_id


def _save_events(connection: sqlite3.Connection, run_id: str, events: list[ToolEvent]) -> None:
    for event in events:
        connection.execute(
            """
            INSERT INTO tool_events(run_id, seq, tool, args_json, result_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, event.seq, event.tool, json.dumps(event.args), event.result.model_dump_json()),
        )
    connection.commit()


def _plan_row(connection: sqlite3.Connection, run_id: str | None):
    if run_id:
        return connection.execute(
            "SELECT id, plan_json FROM runs WHERE id = ? AND plan_json IS NOT NULL",
            (run_id,),
        ).fetchone()
    return connection.execute(
        """
        SELECT id, plan_json FROM runs
        WHERE kind = 'plan' AND plan_json IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()

