import sqlite3

from pydantic import ValidationError

from repodoctor.grok_model import run_grok_tools
from repodoctor.models import ChangePlan, ToolEvent
from repodoctor.textutil import files_in_diff, normalize_repo_path
from repodoctor.tools import default_test_command, importer_risks, read_tools

SYSTEM_PROMPT = """You plan a code change for an indexed git repository. Do not apply it.
The repository is not on disk in this workspace. Use only the RepoDoctor tools.
Then call submit_plan with a unified diff.
The diff must use repo-relative paths and only touch files you list.
The sandbox has pytest, npm, node, and git, and it has no network.
test_command must be pytest, python -m pytest, npm test, or node --test.
Do not use shell syntax such as pipes, redirects, or command separators.
Do not edit files."""


def run_planner(connection: sqlite3.Connection, request: str) -> tuple[ChangePlan, list[ToolEvent]]:
    captured, events, text = run_grok_tools(
        connection,
        f"{SYSTEM_PROMPT}\n\nChange request:\n{request}",
        [*read_tools(), _submit_plan_tool()],
    )
    if captured is not None:
        try:
            return _finalize_plan(connection, ChangePlan.model_validate(captured), request), events
        except ValidationError:
            pass
    finalized = coerce_plan(text, connection, request)
    if finalized is not None:
        return finalized, events
    return (
        ChangePlan(
            goal=request,
            steps=["Grok did not submit a diff."],
            files=[],
            risks=["submit_plan was not called"],
            test_command=default_test_command(connection),
            diff="",
        ),
        events,
    )


def coerce_plan(content: str, connection: sqlite3.Connection, request: str) -> ChangePlan | None:
    from repodoctor.grounding import _json_object

    payload = _json_object(content)
    if payload is None:
        return None
    try:
        plan = ChangePlan.model_validate(payload)
    except ValidationError:
        return None
    return _finalize_plan(connection, plan, request)


def _finalize_plan(connection: sqlite3.Connection, plan: ChangePlan, request: str) -> ChangePlan:
    files = [normalize_repo_path(path) for path in plan.files if path.strip()]
    if not files:
        files = files_in_diff(plan.diff)
    risks = list(plan.risks)
    for risk in importer_risks(connection, files):
        if risk not in risks:
            risks.append(risk)
    steps = plan.steps or ["Apply the diff in the sandbox and run the test command."]
    test_command = plan.test_command.strip() or default_test_command(connection)
    goal = plan.goal.strip() or request
    return ChangePlan(
        goal=goal,
        steps=steps,
        files=files,
        risks=risks,
        test_command=test_command,
        diff=plan.diff,
    )


def _submit_plan_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "submit_plan",
            "description": "Submit the change plan and unified diff. This does not modify the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "test_command": {"type": "string"},
                    "diff": {"type": "string"},
                },
                "required": ["goal", "steps", "files", "risks", "test_command", "diff"],
            },
        },
    }


def parse_plan_json(payload: str) -> ChangePlan:
    return ChangePlan.model_validate_json(payload)
