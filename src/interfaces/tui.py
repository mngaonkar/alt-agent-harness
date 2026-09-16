"""Lightweight Textual chat UI.

Talks only to Session. Agent work runs on a worker thread so the input
stays responsive while a turn is in flight.
"""

from functools import lru_cache

from rich.cells import cell_len
from rich.markup import escape
from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color, ColorParseError, Gradient
from textual.geometry import Region
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, RichLog

from agent.session import HELP, Session, Turn


def _border_t(x: int, y: int, width: int, height: int) -> float | None:
    """Clockwise 0..1 position on the box perimeter, or None if interior."""
    if width < 2 or height < 2:
        return None
    last_x = width - 1
    last_y = height - 1
    on_top = y == 0
    on_bottom = y == last_y
    on_left = x == 0
    on_right = x == last_x
    if not (on_top or on_bottom or on_left or on_right):
        return None
    perimeter = 2 * (width + height - 2)
    if on_top:
        pos = x
    elif on_right:
        pos = last_x + y
    elif on_bottom:
        pos = last_x + last_y + (last_x - x)
    else:
        pos = last_x + last_y + last_x + (last_y - y)
    return pos / perimeter


def _edge_flags(widget: Widget) -> tuple[bool, bool, bool, bool]:
    top, right, bottom, left = widget.styles.border
    return bool(top[0]), bool(right[0]), bool(bottom[0]), bool(left[0])


def _on_border(
    x: int,
    y: int,
    width: int,
    height: int,
    has_top: bool,
    has_right: bool,
    has_bottom: bool,
    has_left: bool,
) -> bool:
    last_x = width - 1
    last_y = height - 1
    if y == 0 and has_top:
        return True
    if y == last_y and has_bottom:
        return True
    if x == 0 and has_left:
        return True
    if x == last_x and has_right:
        return True
    return False


@lru_cache(maxsize=16)
def _hue_loop_gradient(hex_color: str) -> Gradient:
    """Spectrum that wraps around the box, anchored on a theme color."""
    base = Color.parse(hex_color)
    hsl = base.hsl
    sat = max(hsl.s, 0.55)
    lit = min(max(hsl.l, 0.48), 0.62)
    colors = [Color.from_hsl((hsl.h + i / 6) % 1.0, sat, lit) for i in range(6)]
    colors.append(colors[0])
    return Gradient.from_colors(*colors, quality=72)


def _border_gradient(widget: Widget) -> Gradient:
    variables = getattr(widget.app, "theme_variables", {}) or {}
    for key in ("accent", "primary"):
        raw = variables.get(key)
        if not raw:
            continue
        token = raw.split()[0]
        try:
            color = Color.parse(token)
        except ColorParseError:
            continue
        if not color.is_transparent:
            return _hue_loop_gradient(color.hex)
    return _hue_loop_gradient("#7c6fff")


def _recolor_strip_cells(strip: Strip, colors: dict[int, Color]) -> Strip:
    """Replace foreground color at the given cell offsets inside a strip."""
    if not colors:
        return strip
    new_segments: list[Segment] = []
    buf: list[str] = []
    buf_style: RichStyle | None = None
    x = 0

    def flush() -> None:
        if buf:
            new_segments.append(Segment("".join(buf), buf_style))
            buf.clear()

    for text, style, control in strip:
        if control:
            flush()
            new_segments.append(Segment(text, style, control))
            continue
        for char in text:
            width = cell_len(char)
            color = colors.get(x)
            new_style = style
            if color is not None:
                tint = RichStyle.from_color(color.rich_color)
                new_style = tint if style is None else style + tint
            if buf and new_style != buf_style:
                flush()
            buf.append(char)
            buf_style = new_style
            x += width
    flush()
    return Strip(new_segments, strip.cell_length)


def apply_border_gradient(
    widget: Widget, strips: list[Strip], crop: Region
) -> list[Strip]:
    """Paint a hue-loop gradient onto the widget's existing CSS border."""
    if getattr(widget.app, "no_color", False):
        return strips
    if widget.has_class("-invalid"):
        return strips
    width, height = widget.outer_size
    if width < 2 or height < 1 or not strips:
        return strips
    has_top, has_right, has_bottom, has_left = _edge_flags(widget)
    if not (has_top or has_right or has_bottom or has_left):
        return strips

    gradient = _border_gradient(widget)
    painted: list[Strip] = []
    for index, strip in enumerate(strips):
        y = crop.y + index
        is_horizontal_edge = (y == 0 and has_top) or (
            y == height - 1 and has_bottom
        )
        paint_left = has_left and crop.x == 0
        paint_right = has_right and crop.x + strip.cell_length >= width
        if not (is_horizontal_edge or paint_left or paint_right):
            painted.append(strip)
            continue

        colors: dict[int, Color] = {}
        if is_horizontal_edge:
            for x in range(crop.x, crop.x + strip.cell_length):
                if not _on_border(
                    x, y, width, height, has_top, has_right, has_bottom, has_left
                ):
                    continue
                t = _border_t(x, y, width, height)
                if t is not None:
                    colors[x - crop.x] = gradient.get_color(t)
        else:
            if paint_left:
                t = _border_t(0, y, width, height)
                if t is not None:
                    colors[0] = gradient.get_color(t)
            if paint_right:
                x = width - 1
                local = x - crop.x
                if 0 <= local < strip.cell_length:
                    t = _border_t(x, y, width, height)
                    if t is not None:
                        colors[local] = gradient.get_color(t)
        painted.append(_recolor_strip_cells(strip, colors) if colors else strip)
    return painted


class _GradientBorder:
    """Mixin that recolors CSS borders along a looping color gradient."""

    def render_lines(self, crop: Region) -> list[Strip]:
        strips = super().render_lines(crop)  # type: ignore[misc]
        return apply_border_gradient(self, strips, crop)  # type: ignore[arg-type]


class ChatLog(_GradientBorder, RichLog):
    """Transcript log with a gradient border."""


class Composer(_GradientBorder, Input):
    """Prompt input with a gradient border."""


class ChatApp(App):
    TITLE = "alt-agent-harness"
    CSS = """
    Screen {
        layout: vertical;
    }
    #log {
        height: 1fr;
        border: round $accent;
        padding: 0 1;
        scrollbar-gutter: stable;
    }
    #composer {
        height: 3;
        border: round $accent;
    }
    #composer:focus {
        border: round $accent;
    }
    """
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+d", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+l", "clear_log", "Clear", show=True),
    ]

    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self._busy = False

    def compose(self) -> ComposeResult:
        self.sub_title = "%s · %s" % (self.session.provider, self.session.model)
        yield Header(show_clock=True)
        yield ChatLog(id="log", wrap=True, markup=True, highlight=False)
        yield Composer(
            placeholder="Message  ·  /help  /reset  /skills  /tools  /quit",
            id="composer",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.session.subscribe(self._on_agent_event)
        log = self.query_one("#log", ChatLog)
        log.write("[dim]workspace[/] %s" % self.session.workspace)
        log.write("[dim]%s[/]" % HELP)
        self.query_one("#composer", Composer).focus()

    def action_clear_log(self) -> None:
        self.query_one("#log", ChatLog).clear()

    def _on_agent_event(self, kind, text):
        self.call_from_thread(self._write_event, kind, text)

    def _write_event(self, kind, text):
        self.query_one("#log", ChatLog).write(
            "[yellow]%s[/] %s" % (escape("[%s]" % kind), escape(text))
        )

    def _write_user(self, text):
        self.query_one("#log", ChatLog).write("[bold cyan]you[/]  %s" % escape(text))

    def _write_turn(self, turn: Turn):
        log = self.query_one("#log", ChatLog)
        if turn.kind == "quit":
            self.exit()
            return
        if turn.kind == "empty":
            return
        if turn.kind == "reply":
            log.write("[bold green]agent[/]")
            log.write(Markdown(turn.text or "(no reply)"))
            if turn.elapsed_s is not None:
                log.write("[dim]%.1fs[/]" % turn.elapsed_s)
            return
        log.write("[dim]%s[/]" % escape(turn.kind))
        log.write(escape(turn.text))

    def _set_busy(self, busy: bool):
        self._busy = busy
        composer = self.query_one("#composer", Composer)
        composer.disabled = busy
        composer.placeholder = (
            "working…" if busy else "Message  ·  /help  /reset  /skills  /tools  /quit"
        )
        if not busy:
            composer.focus()

    @on(Input.Submitted, "#composer")
    def on_composer_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self._busy:
            return
        self._set_busy(True)
        self._write_user(text)
        self._run_turn(text)

    @work(thread=True, exclusive=True)
    def _run_turn(self, text: str) -> None:
        try:
            turn = self.session.submit(text)
        except Exception as exc:
            turn = Turn("status", "Error: %s: %s" % (type(exc).__name__, exc))
        self.call_from_thread(self._write_turn, turn)
        self.call_from_thread(self._set_busy, False)


def run(session: Session) -> None:
    ChatApp(session).run()
