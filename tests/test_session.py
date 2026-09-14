from pathlib import Path

from agent.loop import Agent
from agent.paths import Workspace
from agent.session import HELP, Session
from agent.skills import SkillRegistry
from agent.tools import ToolRegistry


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, tools=None):
        if not self.responses:
            raise AssertionError("unexpected extra LLM call")
        return self.responses.pop(0)


def _session(tmp_path: Path, responses) -> Session:
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
    skills = SkillRegistry(ws)
    registry = ToolRegistry({}, skills, ws)
    agent = Agent(
        {"max_tool_iterations": 8, "history_limit": 6},
        FakeClient(responses), registry, skills,
    )
    return Session(agent, {"provider": "xai", "model": "grok-4.6"}, tmp_path)


def test_slash_commands(tmp_path):
    session = _session(tmp_path, [])
    assert session.submit("").kind == "empty"
    assert session.submit("/quit").kind == "quit"
    assert session.submit("/exit").kind == "quit"
    help_turn = session.submit("/help")
    assert help_turn.kind == "help"
    assert HELP in help_turn.text
    reset = session.submit("/reset")
    assert reset.kind == "status"
    assert "cleared" in reset.text.lower()
    skills = session.submit("/skills")
    assert "sysinfo" in skills.text
    tools = session.submit("/tools")
    assert tools.kind == "status"
    assert "- load_skill:" in tools.text
    assert "- host_status:" in tools.text
    assert "web_search" not in tools.text
    info = session.submit("/info")
    assert "python" in info.text


def test_submit_ask_and_events(tmp_path):
    session = _session(tmp_path, [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "load_skill", "arguments": '{"name":"sysinfo"}'},
            }],
        },
        {"role": "assistant", "content": "The host is fine."},
    ])
    events = []
    session.subscribe(lambda kind, text: events.append((kind, text)))
    turn = session.submit("how's the machine?")
    assert turn.kind == "reply"
    assert turn.text == "The host is fine."
    assert turn.elapsed_s is not None
    assert any(kind == "tool" and "load_skill" in text for kind, text in events)


def test_reset_clears_history(tmp_path):
    session = _session(tmp_path, [{"role": "assistant", "content": "hi"}])
    session.submit("hello")
    assert session.agent.history
    session.submit("/reset")
    assert session.agent.history == []
