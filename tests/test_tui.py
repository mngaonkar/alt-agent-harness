import asyncio
from pathlib import Path

from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.strip import Strip

from agent.session import Session
from interfaces.tui import ChatApp, ChatLog, Composer, SlashSuggester, _border_t, _recolor_strip_cells


class _DummySkills:
    skills = {"sysinfo": object(), "coinbase-cli": object()}

    def discover(self):
        return self.skills


class _DummyAgent:
    on_event = None
    skills = _DummySkills()

    def reset(self):
        pass


def _session(**kwargs):
    cfg = {"provider": "xai", "model": "grok-4.6"}
    cfg.update(kwargs)
    return Session(_DummyAgent(), cfg, ".")


def _unique_fg_colors(strip: Strip) -> set[str]:
    colors = set()
    for _text, style, control in strip:
        if control or style is None or style.color is None:
            continue
        colors.add(style.color.name or str(style.color))
    return colors


def test_chat_app_constructs():
    session = _session()
    app = ChatApp(session)
    assert app.session is session


def test_chat_app_composes():
    session = _session(provider="openrouter", model="x-ai/grok-4.6")
    app = ChatApp(session)

    async def _run():
        async with app.run_test() as _pilot:
            log = app.query_one("#log")
            composer = app.query_one("#composer")
            assert "openrouter" in app.sub_title
            assert composer.placeholder
            # on_mount wrote the workspace line
            assert str(log.lines)
            assert isinstance(log, ChatLog)
            assert isinstance(composer, Composer)
            assert not app.query_one("#debug-pane").display

    asyncio.run(_run())


def test_ctrl_d_toggles_debug_panel_and_records_agent_events():
    app = ChatApp(_session())

    async def _run():
        async with app.run_test() as pilot:
            pane = app.query_one("#debug-pane")
            debug_log = app.query_one("#debug-log")
            assert not pane.display

            await pilot.press("ctrl+d")
            assert pane.display

            app._write_event("tool", "read_file /README.md")
            await pilot.pause()
            assert "TOOL" in "\n".join(strip.text for strip in debug_log.lines)
            assert "read_file /README.md" in "\n".join(
                strip.text for strip in debug_log.lines
            )

            await pilot.press("ctrl+d")
            assert not pane.display
            app._write_event("error", "request failed")
            await pilot.pause()
            assert "request failed" in "\n".join(
                strip.text for strip in debug_log.lines
            )

    asyncio.run(_run())


def test_border_t_walks_clockwise_around_the_box():
    # 4x3 box has a 10-cell perimeter.
    assert _border_t(0, 0, 4, 3) == 0.0
    assert _border_t(3, 0, 4, 3) == 0.3
    assert _border_t(3, 2, 4, 3) == 0.5
    assert _border_t(0, 2, 4, 3) == 0.8
    assert _border_t(0, 1, 4, 3) == 0.9
    assert _border_t(1, 1, 4, 3) is None
    assert _border_t(0, 0, 1, 1) is None


def test_recolor_strip_cells_tints_selected_offsets():
    base = Style.parse("white")
    strip = Strip([Segment("-----", base)], 5)
    painted = _recolor_strip_cells(
        strip,
        {0: Color.parse("#ff0000"), 4: Color.parse("#0000ff")},
    )
    colors = [
        (style.color.name or "").lower()
        for _text, style, _ in painted
        if style and style.color
    ]
    assert colors[0] in {"#ff0000", "ff0000", "red"}
    assert colors[-1] in {"#0000ff", "0000ff", "blue"}


def test_log_and_composer_borders_use_a_color_gradient(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = ChatApp(_session())

    async def _run():
        async with app.run_test(size=(48, 24)) as _pilot:
            for widget_id in ("#log", "#composer"):
                widget = app.query_one(widget_id)
                strips = widget.render_lines(widget.outer_size.region)
                assert len(strips) >= 2
                top_colors = _unique_fg_colors(strips[0])
                bottom_colors = _unique_fg_colors(strips[-1])
                assert len(top_colors) >= 4, (widget_id, "top", top_colors)
                assert len(bottom_colors) >= 4, (widget_id, "bottom", bottom_colors)
                middle = strips[len(strips) // 2]
                edge_colors = _unique_fg_colors(middle)
                assert edge_colors, widget_id

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


def test_chat_log_mouse_selection_copies_text(monkeypatch):
    monkeypatch.setattr("interfaces.tui.shutil.which", lambda _name: None)
    app = ChatApp(_session())

    async def _run():
        async with app.run_test(size=(80, 24)) as pilot:
            log = app.query_one("#log", ChatLog)
            log.clear()
            log.write("hello world")
            log.write("second line")
            await pilot.pause()
            # Content starts inside the border (1) + left padding (1).
            await pilot.mouse_down(log, offset=(2, 1))
            await pilot.hover(log, offset=(6, 1))
            await pilot.mouse_up(log, offset=(6, 1))
            await pilot.pause()
            assert app.screen.get_selected_text() == "hello"
            # Copied on select, so Cmd+V works without a copy key.
            assert app._clipboard == "hello"
            app._clipboard = ""
            await pilot.press("ctrl+c")
            assert app._clipboard == "hello"
            assert app.is_running

    asyncio.run(_run())


def test_copy_last_reply(monkeypatch):
    monkeypatch.setattr("interfaces.tui.shutil.which", lambda _name: None)
    app = ChatApp(_session())

    async def _run():
        async with app.run_test() as pilot:
            from agent.session import Turn

            app._write_turn(Turn("reply", "the **answer**"))
            await pilot.press("ctrl+y")
            assert app._clipboard == "the **answer**"

    asyncio.run(_run())


def test_slash_suggester_matches_commands_and_skills():
    suggester = SlashSuggester(_session())
    assert suggester.matches("hello") == []
    assert suggester.matches("/sysinfo now") == []
    assert "/coinbase-cli" in suggester.matches("/")
    assert suggester.matches("/SY") == ["/sysinfo"]
    assert suggester.matches("/co") == ["/config", "/coinbase-cli"]


def test_tab_completes_slash_skill():
    app = ChatApp(_session())

    async def _run():
        async with app.run_test() as pilot:
            await pilot.press("/", "s", "y")
            await pilot.pause()
            hint = app.query_one("#completions")
            assert hint.display
            assert "/sysinfo" in str(hint.render())
            await pilot.press("tab")
            composer = app.query_one("#composer", Composer)
            assert composer.value == "/sysinfo "
            assert composer.has_focus
            await pilot.pause()
            assert not hint.display

    asyncio.run(_run())


def test_up_down_walks_prompt_history():
    app = ChatApp(_session())

    async def _run():
        async with app.run_test() as pilot:
            composer = app.query_one("#composer", Composer)
            for text in ("first", "second", "second"):
                composer.remember(text)
            assert composer.history == ["first", "second"]
            composer.value = "draft"
            await pilot.press("up")
            assert composer.value == "second"
            await pilot.press("up")
            assert composer.value == "first"
            await pilot.press("up")
            assert composer.value == "first"
            await pilot.press("down", "down")
            assert composer.value == "draft"
            assert composer.cursor_position == len("draft")
            await pilot.press("down")
            assert composer.value == "draft"

    asyncio.run(_run())


def test_selection_highlight_overrides_segment_colors():
    from textual.selection import Selection

    app = ChatApp(_session())

    async def _run():
        async with app.run_test() as pilot:
            log = app.query_one("#log", ChatLog)
            log.clear()
            log.write("[dim green on #222222]hello world[/]")
            app.screen.selections = {log: Selection(None, None)}
            await pilot.pause()
            expected = log._selection_style()
            styles = [
                style
                for text, style, _ in log._render_line(0, 0, 20)
                if text.strip()
            ]
            assert styles
            for style in styles:
                assert style.bgcolor == expected.bgcolor
                assert style.color == expected.color
                assert not style.dim

    asyncio.run(_run())


def test_bracketed_paste_keeps_all_lines():
    from textual import events

    app = ChatApp(_session())

    async def _run():
        async with app.run_test() as pilot:
            composer = app.query_one("#composer", Composer)
            composer.post_message(events.Paste("line one\nline two"))
            await pilot.pause()
            assert composer.value == "line one line two"

    asyncio.run(_run())
