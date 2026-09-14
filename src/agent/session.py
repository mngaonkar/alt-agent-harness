"""Interface-agnostic conversation with the agent.

UIs (TUI, stdin REPL, later web/Discord) should talk to Session, not to
Agent, tools, or config. The harness never prints; the interface decides
how events and replies are shown.
"""

import time
from dataclasses import dataclass


HELP = "Commands: /reset  /skills  /tools  /info  /help  /quit"


@dataclass(frozen=True)
class Turn:
    """Result of one user submission."""

    kind: str  # reply | status | help | quit | empty
    text: str = ""
    elapsed_s: float | None = None


class Session:
    def __init__(self, agent, cfg, workspace):
        self.agent = agent
        self.cfg = cfg
        self.workspace = workspace
        self._listeners = []
        self.agent.on_event = self._fanout

    @property
    def provider(self):
        return self.cfg.get("provider", "xai")

    @property
    def model(self):
        return self.cfg.get("model", "")

    def subscribe(self, callback):
        """callback(kind, text) for tool/error events during ask()."""
        self._listeners.append(callback)

    def _fanout(self, kind, text):
        for callback in list(self._listeners):
            try:
                callback(kind, text)
            except Exception:
                pass

    def reset(self):
        self.agent.reset()

    def skills_catalog(self):
        self.agent.skills.discover()
        return self.agent.skills.catalog()

    def tools_catalog(self):
        return self.agent.registry.catalog()

    def info(self):
        return self.agent.registry.invoke("host_status", {})

    def ask(self, text):
        return self.agent.ask(text)

    def submit(self, line):
        """Handle a slash command or run one agent turn."""
        text = (line or "").strip()
        if not text:
            return Turn("empty")
        if text in ("/quit", "/exit"):
            return Turn("quit")
        if text == "/reset":
            self.reset()
            return Turn("status", "Conversation cleared.")
        if text == "/skills":
            return Turn("status", self.skills_catalog())
        if text == "/tools":
            return Turn("status", self.tools_catalog())
        if text == "/info":
            return Turn("status", self.info())
        if text in ("/help", "/?"):
            return Turn("help", HELP)
        start = time.time()
        reply = self.ask(text)
        return Turn("reply", reply, elapsed_s=time.time() - start)
