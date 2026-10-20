import sqlite3

from pydantic import ValidationError

from repodoctor.grok_model import run_grok_tools
from repodoctor.grounding import coerce_answer
from repodoctor.models import Answer, ToolEvent
from repodoctor.tools import read_tools

SYSTEM_PROMPT = """You are RepoDoctor. Answer questions about the indexed git repository.
The repository is not on disk in this workspace. Use only the RepoDoctor tools.
Never invent file paths, line numbers, or code.
Every citation must copy a snippet from a tool span and use that span's path.
The citation line range must sit inside that span and must cover only the snippet lines.
If the tools do not show the answer, say so in unknowns and cite nothing you did not read.
Finish by calling submit_answer. Do not edit files."""


def run_agent(connection: sqlite3.Connection, question: str) -> tuple[Answer, list[ToolEvent]]:
    captured, events, text = run_grok_tools(
        connection,
        f"{SYSTEM_PROMPT}\n\nQuestion:\n{question}",
        [*read_tools(), _submit_answer_tool()],
    )
    if captured is not None:
        try:
            return Answer.model_validate(captured), events
        except ValidationError:
            pass
    coerced = coerce_answer(text)
    if coerced is not None:
        return coerced, events
    return (
        Answer(
            answer=text or "Cursor did not submit a cited answer.",
            citations=[],
            unknowns=["submit_answer was not called"],
        ),
        events,
    )


def _submit_answer_tool() -> dict:
    citation = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
            "snippet": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["path", "start_line", "end_line", "snippet", "reason"],
    }
    return {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": "Submit the final answer. Snippets must be copied from tool results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "citations": {"type": "array", "items": citation},
                    "unknowns": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["answer", "citations", "unknowns"],
            },
        },
    }
