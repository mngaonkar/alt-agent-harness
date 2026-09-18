from agent.llm import Client, _jsonable


def _client(**overrides):
    cfg = {
        "provider": "xai",
        "api_key": "test-key",
        "model": "grok-4.6",
        "base_url": "https://api.x.ai/v1",
        "temperature": 0.2,
        "max_tokens": 16384,
        "reasoning_effort": "low",
        "request_timeout": 30,
    }
    cfg.update(overrides)
    return Client(cfg)


def test_xai_kwargs_include_reasoning_effort():
    kwargs = _client()._kwargs([{"role": "user", "content": "hi"}], tools=None)
    assert kwargs["reasoning_effort"] == "low"
    assert "extra_body" not in kwargs
    assert kwargs["max_tokens"] == 16384


def test_openrouter_kwargs_use_extra_body_reasoning():
    client = _client(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="x-ai/grok-4.6",
    )
    kwargs = client._kwargs([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"]["reasoning"]["effort"] == "low"
    assert kwargs["tool_choice"] == "auto"


def test_adapt_drops_reasoning_effort():
    client = _client()
    assert client._adapt("Unknown parameter: 'reasoning_effort'")
    assert client._send_reasoning_effort is False
    kwargs = client._kwargs([{"role": "user", "content": "hi"}], tools=None)
    assert "reasoning_effort" not in kwargs


def test_adapt_strips_reasoning_traces_from_messages():
    client = _client()
    messages = [{
        "role": "assistant",
        "content": None,
        "reasoning_details": [{"type": "reasoning.text", "text": "think"}],
        "tool_calls": [{"id": "c1"}],
    }]
    assert client._adapt("unexpected field reasoning_details")
    assert client._strip_reasoning is True
    cleaned = client._kwargs(messages, tools=None)["messages"]
    assert "reasoning_details" not in cleaned[0]
    assert cleaned[0]["tool_calls"][0]["id"] == "c1"


def test_jsonable_dumps_nested_objects():
    class Obj:
        def model_dump(self):
            return {"type": "reasoning.text", "text": "hi"}

    assert _jsonable([Obj()]) == [{"type": "reasoning.text", "text": "hi"}]
