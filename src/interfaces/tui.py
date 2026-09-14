"""Lightweight Textual chat UI.

Talks only to Session. Agent work runs on a worker thread so the input
stays responsive while a turn is in flight.
"""

from rich.markup import escape
from rich.markdown import Markdown
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, RichLog

from agent.session import HELP, Session, Turn


class ChatApp(App):
    TITLE = "agent-harness"
    CSS = """
    Screen {
        layout: vertical;
    }
    #log {
        height: 1fr;
        border: tall $accent;
        padding: 0 1;
        scrollbar-gutter: stable;
    }
    #composer {
        height: auto;
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
        yield RichLog(id="log", wrap=True, markup=True, highlight=False)
        yield Input(
            placeholder="Message  ·  /help  /reset  /skills  /tools  /quit",
            id="composer",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.session.subscribe(self._on_agent_event)
        log = self.query_one("#log", RichLog)
        log.write("[dim]workspace[/] %s" % self.session.workspace)
        log.write("[dim]%s[/]" % HELP)
        self.query_one("#composer", Input).focus()

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def _on_agent_event(self, kind, text):
        self.call_from_thread(self._write_event, kind, text)

    def _write_event(self, kind, text):
        self.query_one("#log", RichLog).write(
            "[yellow]%s[/] %s" % (escape("[%s]" % kind), escape(text))
        )

    def _write_user(self, text):
        self.query_one("#log", RichLog).write("[bold cyan]you[/]  %s" % escape(text))

    def _write_turn(self, turn: Turn):
        log = self.query_one("#log", RichLog)
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
        composer = self.query_one("#composer", Input)
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
