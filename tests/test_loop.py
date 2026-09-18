from pathlib import Path

from agent.loop import Agent
from agent.paths import Workspace
from agent.skills import SkillRegistry
from agent.tools import ToolRegistry


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "tools": tools,
        })
        if not self.responses:
            raise AssertionError("unexpected extra LLM call")
        return self.responses.pop(0)


def _agent(tmp_path: Path, responses) -> Agent:
    (tmp_path / "skills" / "sysinfo").mkdir(parents=True)
    (tmp_path / "skills" / "sysinfo" / "SKILL.md").write_text(
        "---\n"
        "name: sysinfo\n"
        "description: Host health report.\n"
        "---\n"
        "\n"
        "# Sysinfo\n"
        "Call host_status and summarise.\n"
    )
    (tmp_path / "tmp").mkdir(exist_ok=True)
    ws = Workspace(tmp_path)
    registry_skills = SkillRegistry(ws)
    registry = ToolRegistry({}, registry_skills, ws)
    client = FakeClient(responses)
    return Agent(
        {"max_tool_iterations": 8, "history_limit": 6},
        client, registry, registry_skills,
    )


def test_plain_reply_no_tools(tmp_path):
    agent = _agent(tmp_path, [
        {"role": "assistant", "content": "hello"},
    ])
    assert agent.ask("hi") == "hello"
    assert agent.history[-1]["content"] == "hello"


def test_tool_round_then_answer(tmp_path):
    agent = _agent(tmp_path, [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "load_skill", "arguments": '{"name":"sysinfo"}'},
            }],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_2",
                "type": "function",
                "function": {"name": "host_status", "arguments": "{}"},
            }],
        },
        {"role": "assistant", "content": "The host is fine."},
    ])
    reply = agent.ask("how's the machine?")
    assert reply == "The host is fine."
    roles = [m["role"] for m in agent.history]
    assert roles.count("tool") == 2
    skill_result = next(
        m for m in agent.history
        if m.get("role") == "tool" and m.get("tool_call_id") == "call_1"
    )
    assert "Call host_status" in skill_result["content"]


def test_unknown_tool_is_fed_back(tmp_path):
    agent = _agent(tmp_path, [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_x",
                "type": "function",
                "function": {"name": "not_a_tool", "arguments": "{}"},
            }],
        },
        {"role": "assistant", "content": "I don't have that tool."},
    ])
    reply = agent.ask("do the thing")
    assert reply == "I don't have that tool."
    tool_msg = [m for m in agent.history if m["role"] == "tool"][0]
    assert "no such tool" in tool_msg["content"]


def test_history_trim_keeps_tool_pairs(tmp_path):
    agent = _agent(tmp_path, [
        {"role": "assistant", "content": "ok"},
    ])
    # Seed history with a tool pair plus extra turns so trim must fire.
    agent.history = [
        {"role": "user", "content": "old"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": "host_status"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "{}"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "later"},
        {"role": "assistant", "content": "later-ok"},
    ]
    agent.cfg["history_limit"] = 4
    agent._trim()
    # Must not start on a tool message; the pair stays together.
    assert agent.history[0]["role"] != "tool"
    roles = [m["role"] for m in agent.history]
    if "tool" in roles:
        idx = roles.index("tool")
        assert agent.history[idx - 1].get("tool_calls")


def test_empty_reply_retries_once(tmp_path):
    agent = _agent(tmp_path, [
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "here it is"},
    ])
    assert agent.ask("hi") == "here it is"
    assistant = [m for m in agent.history if m["role"] == "assistant"]
    assert [m["content"] for m in assistant] == ["here it is"]
    nudge = agent.client.calls[1]["messages"][-1]
    assert nudge["role"] == "user"
    assert "empty" in nudge["content"].lower()


def test_length_finish_does_not_retry(tmp_path):
    agent = _agent(tmp_path, [
        {"role": "assistant", "content": "", "finish_reason": "length"},
    ])
    reply = agent.ask("hi")
    assert "token limit" in reply.lower()
    assert len(agent.client.calls) == 1


def test_empty_after_tool_retries(tmp_path):
    agent = _agent(tmp_path, [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "load_skill", "arguments": '{"name":"sysinfo"}'},
            }],
        },
        {"role": "assistant", "content": "", "finish_reason": "stop"},
        {"role": "assistant", "content": "The host is fine."},
    ])
    assert agent.ask("how's the machine?") == "The host is fine."
    assert len(agent.client.calls) == 3


def test_reasoning_details_kept_on_tool_message(tmp_path):
    details = [{"type": "reasoning.text", "text": "need sysinfo"}]
    agent = _agent(tmp_path, [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "load_skill", "arguments": '{"name":"sysinfo"}'},
            }],
            "reasoning_details": details,
        },
        {"role": "assistant", "content": "ok"},
    ])
    agent.ask("how's the machine?")
    tool_assistant = agent.history[1]
    assert tool_assistant["reasoning_details"] == details
    assert tool_assistant.get("content") is None
    sent = agent.client.calls[1]["messages"]
    assert any(m.get("reasoning_details") == details for m in sent)


def test_two_empty_replies_reports_error(tmp_path):
    agent = _agent(tmp_path, [
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": ""},
    ])
    reply = agent.ask("hi")
    assert "empty reply" in reply.lower()
    assert len(agent.client.calls) == 2


def test_stops_after_max_iterations(tmp_path):
    looping = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_loop",
            "type": "function",
            "function": {"name": "list_skills", "arguments": "{}"},
        }],
    }
    agent = _agent(tmp_path, [looping] * 8)
    agent.cfg["max_tool_iterations"] = 3
    reply = agent.ask("loop")
    assert reply.startswith("Stopped after 3 tool rounds")
