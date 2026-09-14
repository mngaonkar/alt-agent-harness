import asyncio
from pathlib import Path

from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.strip import Strip

from agent.session import Session
from interfaces.tui import ChatApp, ChatLog, Composer, _border_t, _recolor_strip_cells


class _DummyAgent:
    on_event = None

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
