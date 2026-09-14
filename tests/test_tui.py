from pathlib import Path

from agent.session import Session
from interfaces.tui import ChatApp


class _DummyAgent:
    on_event = None

    def reset(self):
        pass


def test_chat_app_constructs():
    session = Session(_DummyAgent(), {"provider": "xai", "model": "grok-4.6"}, ".")
    app = ChatApp(session)
    assert app.session is session


def test_chat_app_composes():
    session = Session(_DummyAgent(), {"provider": "openrouter", "model": "x-ai/grok-4.6"}, ".")
    app = ChatApp(session)

    async def _run():
        async with app.run_test() as _pilot:
            log = app.query_one("#log")
            composer = app.query_one("#composer")
            assert "openrouter" in app.sub_title
            assert composer.placeholder
            # on_mount wrote the workspace line
            assert str(log.lines)

    import asyncio
    asyncio.run(_run())


def test_core_harness_does_not_import_interfaces():
    root = Path(__file__).resolve().parents[1] / "src" / "agent"
    # cli.py is the process compositor and may load a front-end.
    skip = {"cli.py"}
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in skip:
            continue
        text = path.read_text()
        if "import interfaces" in text or "from interfaces" in text:
            offenders.append(str(path.relative_to(root.parent)))
    assert not offenders, offenders
