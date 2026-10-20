import json
import sqlite3
from typing import Any

import httpx

from repodoctor.config import api_key, chat_model
from repodoctor.errors import ModelError
from repodoctor.grounding import _json_object
from repodoctor.models import ToolEvent, ToolResult
from repodoctor.tools import dispatch_tool

API_URL = "https://api.x.ai/v1/chat/completions"
KEY_HELP = "Set XAI_API_KEY in the project .env file."
TERMINAL_TOOLS = {"submit_answer", "submit_plan"}
MAX_STEPS = 8


def probe_grok() -> tuple[bool, str]:
    if not api_key():
        return False, KEY_HELP
    try:
        response = httpx.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {api_key()}"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        return False, f"Could not reach the Grok API: {exc}"
    if response.status_code == 401:
        return False, "The XAI_API_KEY was rejected. Check the key in .env."
    if response.status_code >= 400:
        return False, response.text[:300] or f"Grok API returned HTTP {response.status_code}."
    return True, f"Grok model {chat_model()} is ready."


def run_grok_tools(
    connection: sqlite3.Connection,
    prompt: str,
    tools: list[dict],
) -> tuple[dict | None, list[ToolEvent], str]:
    messages: list[dict] = [{"role": "user", "content": prompt}]
    events: list[ToolEvent] = []
    for _step in range(MAX_STEPS):
        message = _chat(messages, tools)
        messages.append(message)
        calls = message.get("tool_calls") or []
        if not calls:
            return None, events, str(message.get("content") or "")
        captured: dict[str, Any] | None = None
        for call in calls:
            name, arguments = _call_arguments(call)
            if name in TERMINAL_TOOLS:
                captured = arguments
                result = ToolResult(tool=name, summary="submitted", spans=[])
            else:
                result = dispatch_tool(connection, name, arguments)
            events.append(ToolEvent(seq=len(events) + 1, tool=name, args=arguments, result=result))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or name),
                    "content": result.model_dump_json(),
                }
            )
        if captured is not None:
            return captured, events, ""
    return None, events, ""


def parse_model_message(text: str) -> dict:
    payload = _json_object(text)
    if payload is None:
        return {"role": "assistant", "content": text}
    calls = _tool_calls(payload)
    if calls:
        return {"role": "assistant", "content": str(payload.get("content") or ""), "tool_calls": calls}
    return {"role": "assistant", "content": json.dumps(payload)}


def _chat(messages: list[dict], tools: list[dict]) -> dict:
    key = api_key()
    if not key:
        raise ModelError(KEY_HELP)
    try:
        response = httpx.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": chat_model(),
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.1,
            },
            timeout=180,
        )
    except httpx.HTTPError as exc:
        raise ModelError(f"Could not reach the Grok API: {exc}") from exc
    if response.status_code == 401:
        raise ModelError("The XAI_API_KEY was rejected. Check the key in .env.")
    if response.status_code >= 400:
        raise ModelError(response.text[:500] or f"Grok API returned HTTP {response.status_code}.")
    choices = response.json().get("choices") or []
    if not choices:
        raise ModelError("Grok returned no choices.")
    message = choices[0].get("message") or {}
    stored = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        stored["tool_calls"] = message["tool_calls"]
    return stored


def _call_arguments(call: dict) -> tuple[str, dict]:
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    raw = function.get("arguments", {})
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
    elif isinstance(raw, dict):
        parsed = raw
    else:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return name, parsed


def _tool_calls(payload: dict) -> list[dict]:
    raw_calls = payload.get("tool_calls")
    if isinstance(raw_calls, list):
        return [_normalize_call(call) for call in raw_calls if isinstance(call, dict)]
    if "name" in payload and "arguments" in payload:
        return [_normalize_call(payload)]
    return []


def _normalize_call(call: dict) -> dict:
    function = call.get("function") if isinstance(call.get("function"), dict) else call
    return {
        "function": {
            "name": function.get("name", ""),
            "arguments": function.get("arguments", {}),
        }
    }
