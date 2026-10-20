from pathlib import Path

import typer

import os

from repodoctor import __version__
from repodoctor.config import api_token, is_loopback_host
from repodoctor.errors import RepoDoctorError
from repodoctor.eval_runner import run_eval
from repodoctor.indexer import index_repo
from repodoctor.service import ask_question, plan_change, status_for, verify_change

app = typer.Typer(help="Answer questions about a git repository with cited lines.", no_args_is_help=True)


@app.command()
def index(
    path: Path,
    no_embed: bool = typer.Option(False, "--no-embed", help="Skip local token vectors."),
) -> None:
    """Index symbols, imports, and chunks for a git repository."""
    summary = index_repo(path, embed=not no_embed)
    typer.echo(
        f"Indexed {summary.files} files, {summary.symbols} symbols, "
        f"{summary.chunks} chunks at {summary.commit_sha[:12]}."
    )
    typer.echo(f"Embeddings: {summary.embed_status}")
    typer.echo(f"Database: {summary.database}")


@app.command()
def ask(path: Path, question: str) -> None:
    """Answer a question and score each citation against the index."""
    result = ask_question(path, question)
    typer.echo(result.answer.answer)
    typer.echo("")
    grounding = result.grounding
    typer.echo(f"Citations {grounding.supported}/{grounding.cited} supported")
    for check in grounding.checks:
        citation = check.citation
        state = "supported" if check.supported else "failed"
        typer.echo(f"- {citation.path}:{citation.start_line}-{citation.end_line} [{state}]")
        if check.failures:
            typer.echo(f"  failures: {', '.join(check.failures)}")
        typer.echo(f"  {citation.snippet}")
        typer.echo(f"  {citation.reason}")
    if result.answer.unknowns:
        typer.echo("")
        typer.echo("Unknowns")
        for item in result.answer.unknowns:
            typer.echo(f"- {item}")
    typer.echo("")
    typer.echo(f"run {result.run_id}")


@app.command()
def plan(path: Path, request: str) -> None:
    """Write a change plan and diff without modifying the repository."""
    result = plan_change(path, request)
    change = result.plan
    typer.echo(change.goal)
    typer.echo("")
    typer.echo("Steps")
    for step in change.steps:
        typer.echo(f"- {step}")
    typer.echo("")
    typer.echo("Files")
    for file_path in change.files:
        typer.echo(f"- {file_path}")
    typer.echo("")
    typer.echo(f"Test: {change.test_command}")
    if change.risks:
        typer.echo("")
        typer.echo("Risks")
        for risk in change.risks:
            typer.echo(f"- {risk}")
    typer.echo("")
    typer.echo(change.diff)
    typer.echo(f"run {result.run_id}")


@app.command()
def verify(
    path: Path,
    run_id: str | None = typer.Option(None, "--run-id", help="Plan run to verify. Defaults to the latest plan."),
    timeout_seconds: int = typer.Option(180, "--timeout", help="Sandbox timeout in seconds."),
) -> None:
    """Apply the planned diff in Docker and run its test command."""
    result = verify_change(path, run_id=run_id, timeout_seconds=timeout_seconds)
    verification = result.verification
    state = "passed" if verification.passed else "failed"
    typer.echo(f"Sandbox {state}")
    typer.echo(f"Patch applied: {verification.patch_applied}")
    typer.echo(f"Exit code: {verification.exit_code}")
    if verification.changed_files:
        typer.echo("Changed files")
        for file_path in verification.changed_files:
            typer.echo(f"- {file_path}")
    if verification.failures:
        typer.echo("Failures")
        for failure in verification.failures:
            typer.echo(f"- {failure}")
    if verification.stdout:
        typer.echo("")
        typer.echo(verification.stdout)
    if verification.stderr:
        typer.echo("")
        typer.echo(verification.stderr)


@app.command()
def status(path: Path) -> None:
    """Show whether the current commit is indexed."""
    current = status_for(path)
    if not current.indexed or current.summary is None:
        typer.echo(f"Not indexed: {current.path} @ {current.commit_sha[:12]}")
        return
    summary = current.summary
    typer.echo(
        f"Indexed {summary.files} files, {summary.symbols} symbols at {summary.commit_sha[:12]}."
    )
    typer.echo(f"Embeddings: {summary.embed_status}")


@app.command(name="eval")
def eval_cmd() -> None:
    """Score fixture questions and sandbox patches."""
    report = run_eval()
    for fixture in report.fixtures:
        sandbox = "passed" if fixture.sandbox_passed else "failed"
        typer.echo(
            f"{fixture.name}: citation_support_rate={fixture.citation_support_rate:.2f} "
            f"expected_path_cited={fixture.expected_path_cited} sandbox={sandbox}"
        )
        for failure in fixture.failures:
            typer.echo(f"  - {failure}")
    typer.echo(f"citation_support_rate={report.citation_support_rate:.2f}")
    typer.echo(f"sandbox_pass_rate={report.sandbox_pass_rate:.2f}")
    if report.citation_support_rate < 1 or report.sandbox_pass_rate < 1:
        raise typer.Exit(code=1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="API bind host."),
    port: int = typer.Option(8000, help="API bind port."),
) -> None:
    """Start the FastAPI server."""
    import uvicorn

    if not is_loopback_host(host):
        if not api_token():
            raise RepoDoctorError(
                "Set REPODOCTOR_API_TOKEN before binding the API outside localhost."
            )
        os.environ["REPODOCTOR_REQUIRE_TOKEN"] = "1"
    uvicorn.run("repodoctor.api:app", host=host, port=port, reload=False)


@app.callback(invoke_without_command=True)
def main(version: bool = typer.Option(False, "--version", help="Print the version and exit.")) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


def cli() -> None:
    try:
        app()
    except RepoDoctorError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
