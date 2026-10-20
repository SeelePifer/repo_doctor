import shutil
from pathlib import Path

from repodoctor.config import data_dir, fixtures_root
from repodoctor.errors import RepoDoctorError
from repodoctor.gitutil import commit_snapshot
from repodoctor.indexer import index_repo
from repodoctor.models import EvalFixtureResult, EvalReport
from repodoctor.service import ask_question, plan_change, verify_change
from repodoctor.textutil import normalize_repo_path

FIXTURES = [
    {
        "name": "py_calc",
        "question": "What expression does the multiply function return?",
        "expect_path": "calc.py",
        "request": (
            "Fix multiply so it returns the product of left and right. "
            "Keep add unchanged. The sandbox test command must be pytest -q."
        ),
    },
    {
        "name": "ts_greet",
        "question": "What string prefix does the greet function use?",
        "expect_path": "src/greet.ts",
        "request": (
            "Change greet so it returns Hello followed by a space and the name. "
            "The sandbox test command must be npm test."
        ),
    },
]


def run_eval() -> EvalReport:
    fixture_results: list[EvalFixtureResult] = []
    for fixture in FIXTURES:
        repo = materialize_fixture(fixture["name"])
        index_repo(repo, embed=True)
        answer = ask_question(repo, fixture["question"])
        expected = normalize_repo_path(fixture["expect_path"])
        cited = any(
            check.supported and normalize_repo_path(check.citation.path) == expected
            for check in answer.grounding.checks
        )
        planned = plan_change(repo, fixture["request"])
        verified = verify_change(repo, run_id=planned.run_id, timeout_seconds=180)
        failures: list[str] = []
        if not cited:
            failures.append("expected_path_not_supported")
        failures.extend(verified.verification.failures)
        fixture_results.append(
            EvalFixtureResult(
                name=fixture["name"],
                citation_support_rate=answer.grounding.support_rate,
                expected_path_cited=cited,
                sandbox_passed=verified.verification.passed,
                failures=failures,
            )
        )
    return _report(fixture_results)


def materialize_fixture(name: str) -> Path:
    source = fixtures_root() / name
    if not source.is_dir():
        raise RepoDoctorError(f"Missing fixture: {source}")
    destination = data_dir() / "eval-fixtures" / name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", ".empty-hooks"))
    commit_snapshot(destination, "Fixture snapshot")
    return destination


def _report(fixtures: list[EvalFixtureResult]) -> EvalReport:
    if not fixtures:
        return EvalReport(citation_support_rate=0.0, sandbox_pass_rate=0.0, fixtures=[])
    citation_rate = sum(item.citation_support_rate for item in fixtures) / len(fixtures)
    sandbox_rate = sum(1 for item in fixtures if item.sandbox_passed) / len(fixtures)
    return EvalReport(
        citation_support_rate=citation_rate,
        sandbox_pass_rate=sandbox_rate,
        fixtures=fixtures,
    )
