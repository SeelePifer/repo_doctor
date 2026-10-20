from repodoctor.grok_model import parse_model_message
from repodoctor.search import _cosine, token_vector


def test_parse_tool_call() -> None:
    message = parse_model_message(
        '{"tool_calls":[{"name":"search","arguments":{"query":"multiply"}}]}'
    )
    assert message["tool_calls"][0]["function"]["name"] == "search"
    assert message["tool_calls"][0]["function"]["arguments"]["query"] == "multiply"


def test_parse_answer_json_stays_in_content() -> None:
    message = parse_model_message('{"answer":"ok","citations":[],"unknowns":[]}')
    assert "tool_calls" not in message
    assert "ok" in message["content"]


def test_token_vector_matches_shared_words() -> None:
    related = _cosine(token_vector("def multiply(left, right)"), token_vector("multiply left right"))
    unrelated = _cosine(token_vector("def multiply(left, right)"), token_vector("package json scripts"))
    assert related > unrelated
