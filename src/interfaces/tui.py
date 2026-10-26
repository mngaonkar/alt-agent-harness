"""Lightweight Textual chat UI.

Talks only to Session. Agent work runs on a worker thread so the input
stays responsive while a turn is in flight.
"""

import shutil
import subprocess
import sys
from datetime import datetime
from functools import lru_cache

from rich.cells import cell_len
from rich.markup import escape
from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color, ColorParseError, Gradient
from textual.containers import Horizontal, Vertical
from textual.geometry import Region
from textual.selection import Selection
from textual.strip import Strip
from textual.suggester import Suggester
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, RichLog, Static

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
    """Transcript log with a gradient border and mouse text selection."""

    ALLOW_SELECT = True

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        text = "\n".join(strip.text.rstrip() for strip in self.lines)
        return selection.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        self._line_cache.clear()
        self.refresh()

    def _selection_style(self) -> RichStyle:
        """Solid accent background with contrasting text, readable on any segment."""
        try:
            bg = Color.parse(self.app.current_theme.primary)
        except (AttributeError, ColorParseError):
            bg = Color.parse("#0178D4")
        fg = bg.get_contrast_text(1.0)
        return RichStyle(color=fg.rich_color, bgcolor=bg.rich_color, dim=False, italic=False)

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        if y >= len(self.lines):
            return Strip.blank(width, self.rich_style)
        selection = self.text_selection
        line = self.lines[y]
        if selection is not None and (span := selection.get_span(y)) is not None:
            start, end = span
            if end == -1:
                end = line.cell_length
            selected = line.crop(start, end)
            # post_style so the highlight wins over each segment's own colors/dim.
            selected = Strip(
                Segment.apply_style(selected, post_style=self._selection_style()),
                selected.cell_length,
            )
            line = Strip.join([line.crop(0, start), selected, line.crop(end, line.cell_length)])
        return line.crop_extend(scroll_x, scroll_x + width, self.rich_style).apply_offsets(
            scroll_x, y
        )


def _system_clipboard() -> str:
    if sys.platform != "darwin" or not shutil.which("pbpaste"):
        return ""
    result = subprocess.run(["pbpaste"], capture_output=True, check=False)
    return result.stdout.decode("utf-8", errors="replace")


class SlashSuggester(Suggester):
    """Completes /commands and /<skill> names; the list is reloaded on each new "/"."""

    def __init__(self, session: Session):
        super().__init__(use_cache=False, case_sensitive=False)
        self.session = session
        self._commands: list[str] = []

    def matches(self, value: str) -> list[str]:
        if not value.startswith("/") or " " in value:
            return []
        if value == "/" or not self._commands:
            self._commands = self.session.slash_commands()
        prefix = value.casefold()
        return [c for c in self._commands if c.casefold().startswith(prefix)]

    async def get_suggestion(self, value: str) -> str | None:
        found = self.matches(value)
        return found[0] if found else None


class Composer(_GradientBorder, Input):
    """Prompt input with a gradient border.

    Tab accepts a /command completion; Up/Down walk the prompt history.
    """

    BINDINGS = [
        Binding("tab", "accept_suggestion", "Complete", show=False),
        Binding("super+v", "paste", "Paste", show=False),
        Binding("up", "history(-1)", "Previous prompt", show=False),
        Binding("down", "history(1)", "Next prompt", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history: list[str] = []
        self._history_index = 0
        self._draft = ""

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self._history_index = len(self.history)
        self._draft = ""

    def _insert_pasted(self, text: str) -> None:
        # Single-line input: keep every pasted line instead of only the first.
        start, end = self.selection
        self.replace(" ".join(text.splitlines()), start, end)

    def _on_paste(self, event: events.Paste) -> None:
        # Cmd+V arrives from the terminal as a bracketed paste.
        if event.text:
            self._insert_pasted(event.text)
        event.prevent_default()
        event.stop()

    def action_paste(self) -> None:
        # Input's default pastes only Textual's internal clipboard; read the system one.
        text = _system_clipboard() or self.app.clipboard
        if text:
            self._insert_pasted(text)

    def action_history(self, step: int) -> None:
        index = self._history_index + step
        if not 0 <= index <= len(self.history):
            return
        if self._history_index == len(self.history):
            self._draft = self.value
        self._history_index = index
        self.value = self.history[index] if index < len(self.history) else self._draft
        self.cursor_position = len(self.value)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "accept_suggestion":
            return bool(self._suggestion) and self._suggestion != self.value
        return super().check_action(action, parameters)

    def action_accept_suggestion(self) -> None:
        self.value = self._suggestion + " "
        self.cursor_position = len(self.value)


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
    #completions {
        height: auto;
        padding: 0 2;
        color: $text-muted;
        display: none;
    }
    #content {
        height: 1fr;
    }
    #debug-pane {
        width: 36;
        min-width: 24;
        height: 1fr;
        border: round $accent;
        display: none;
    }
    #debug-title {
        height: 1;
        padding: 0 1;
        text-style: bold;
    }
    #debug-log {
        height: 1fr;
        padding: 0 1;
        scrollbar-gutter: stable;
    }
    """
    BINDINGS = [
        Binding("ctrl+c", "copy_or_quit", "Copy/Quit", show=True, priority=True),
        Binding("super+c", "copy_selection", "Copy", show=False, priority=True),
        Binding("ctrl+y", "copy_last_reply", "Copy reply", show=True),
        Binding("ctrl+d", "toggle_debug", "Debug log", show=True, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+o", "open_config", "Config", show=True),
        Binding("ctrl+l", "clear_log", "Clear", show=True),
    ]

    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self._busy = False
        self._last_reply = ""

    def compose(self) -> ComposeResult:
        self.sub_title = "%s · %s" % (self.session.provider, self.session.model)
        yield Header(show_clock=True)
        with Horizontal(id="content"):
            yield ChatLog(id="log", wrap=True, markup=True, highlight=False)
            with Vertical(id="debug-pane"):
                yield Static("DEBUG EVENTS · Ctrl+D to hide", id="debug-title")
                yield RichLog(id="debug-log", wrap=True, markup=True, highlight=False)
        yield Static(id="completions")
        yield Composer(
            placeholder="Message  ·  /help  /config  /reset  /skills  /tools  /quit",
            id="composer",
            suggester=SlashSuggester(self.session),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.session.subscribe(self._on_agent_event)
        log = self.query_one("#log", ChatLog)
        log.write("[dim]workspace[/] %s" % self.session.workspace)
        log.write("[dim]%s[/]" % HELP)
        self.query_one("#composer", Composer).focus()

    def copy_to_clipboard(self, text: str) -> None:
        # OSC 52 (Textual's default) is ignored by macOS Terminal.app; use pbcopy too.
        super().copy_to_clipboard(text)
        if sys.platform == "darwin" and shutil.which("pbcopy"):
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)

    def _selected_text(self) -> str:
        text = self.screen.get_selected_text()
        focused = self.focused
        if not text and isinstance(focused, Input):
            text = focused.selected_text
        return text or ""

    def on_text_selected(self, event: events.TextSelected) -> None:
        # Copy on select: iTerm2/Terminal.app keep Cmd+C for themselves, so the
        # app never sees it. After a drag, Cmd+V anywhere pastes the selection.
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.notify("Copied to clipboard", timeout=1.5)

    def action_copy_selection(self) -> None:
        text = self._selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.notify("Copied to clipboard", timeout=1.5)

    def action_copy_or_quit(self) -> None:
        text = self._selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.screen.clear_selection()
            self.notify("Copied to clipboard")
        else:
            self.exit()

    def action_copy_last_reply(self) -> None:
        if not self._last_reply:
            self.notify("No reply to copy yet", severity="warning")
            return
        self.copy_to_clipboard(self._last_reply)
        self.notify("Copied last reply")

    def action_clear_log(self) -> None:
        self.query_one("#log", ChatLog).clear()

    def action_toggle_debug(self) -> None:
        pane = self.query_one("#debug-pane")
        pane.display = not pane.display

    def action_open_config(self) -> None:
        from agent import config
        from interfaces.config_tui import ConfigModal

        cfg_path = config.default_path(self.session.workspace)
        self.push_screen(ConfigModal(self.session.cfg, cfg_path), callback=self._on_config_saved)

    def _on_config_saved(self, new_cfg: dict | None) -> None:
        if not new_cfg:
            return
        self.session.update_config(new_cfg)
        self.sub_title = "%s · %s" % (self.session.provider, self.session.model)
        log = self.query_one("#log", ChatLog)
        log.write(
            "[bold green][config][/] Configuration updated! Provider: [bold]%s[/], Model: [bold]%s[/]"
            % (self.session.provider, self.session.model)
        )

    def _on_agent_event(self, kind, text):
        self.call_from_thread(self._write_event, kind, text)

    def _write_event(self, kind, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.query_one("#debug-log", RichLog).write(
            "[dim]%s[/] [bold yellow]%s[/] %s"
            % (timestamp, escape(str(kind).upper()), escape(str(text)))
        )
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
        if turn.kind == "config":
            self.action_open_config()
            return
        if turn.kind == "reply":
            self._last_reply = turn.text or ""
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
            "working…" if busy else "Message  ·  /help  /config  /reset  /skills  /tools  /quit"
        )
        if not busy:
            composer.focus()

    @on(Input.Changed, "#composer")
    def on_composer_changed(self, event: Input.Changed) -> None:
        suggester = event.input.suggester
        found = suggester.matches(event.value) if isinstance(suggester, SlashSuggester) else []
        hint = self.query_one("#completions", Static)
        hint.display = bool(found)
        if found:
            first, rest = found[0], found[1:9]
            more = "  …+%d" % (len(found) - 9) if len(found) > 9 else ""
            hint.update(
                "[bold]%s[/]  %s%s  [dim](tab)[/]"
                % (escape(first), "  ".join(escape(c) for c in rest), more)
            )

    @on(Input.Submitted, "#composer")
    def on_composer_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self._busy:
            return
        self.query_one("#composer", Composer).remember(text)
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
