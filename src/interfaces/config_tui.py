"""Configuration TUI for alt-agent-harness.

Allows configuring LLM providers (xAI, OpenRouter, OpenAI, Custom endpoints),
selecting LLM models, configuring Tavily search, and testing connections.
Can run standalone or as a modal screen inside ChatApp.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from openai import OpenAI
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static

from agent import config


class ConfigForm(VerticalScroll):
    """Configuration form containing all provider, model, and endpoint settings."""

    DEFAULT_CSS = """
    ConfigForm {
        padding: 1 2;
        height: 1fr;
    }
    .form-group {
        margin-bottom: 1;
    }
    .form-label {
        color: $text;
        text-style: bold;
        margin-bottom: 0;
    }
    .form-hint {
        color: $text-muted;
        margin-bottom: 0;
    }
    .form-row {
        height: auto;
        align: left middle;
    }
    .btn-row {
        margin-top: 1;
        margin-bottom: 1;
        height: auto;
        align: center middle;
    }
    .btn-row Button {
        margin-right: 1;
    }
    #status_box {
        margin-top: 1;
        padding: 0 1;
        height: auto;
        min-height: 2;
        border: round $accent;
        background: $surface;
    }
    Select {
        margin-bottom: 1;
    }
    Input {
        margin-bottom: 1;
    }
    """

    def __init__(self, cfg: dict, cfg_path: Path | str, on_save_callback=None, on_cancel_callback=None):
        super().__init__()
        self.cfg = dict(cfg)
        self.cfg_path = Path(cfg_path)
        self.on_save_callback = on_save_callback
        self.on_cancel_callback = on_cancel_callback
        self._current_provider = self.cfg.get("provider") or "xai"

    def _get_provider_options(self) -> list[tuple[str, str]]:
        return [(info.get("name", key), key) for key, info in config.PROVIDERS.items()]

    def _get_model_options_for_provider(self, provider: str) -> list[tuple[str, str]]:
        preset = config.PROVIDERS.get(provider, {})
        models = preset.get("models", [])
        options = [(m, m) for m in models]
        options.append(("[Custom model name...]", "__custom__"))
        return options

    def compose(self) -> ComposeResult:
        current_provider = self.cfg.get("provider") or "xai"
        if current_provider not in config.PROVIDERS:
            current_provider = "xai"
        self._current_provider = current_provider

        preset = config.PROVIDERS[current_provider]
        current_model = self.cfg.get("model") or preset.get("model", "")
        current_base_url = self.cfg.get("base_url") or preset.get("base_url", "")
        current_api_key = self.cfg.get("api_key") or ""
        current_tavily_key = self.cfg.get("tavily_api_key") or ""
        current_reasoning = self.cfg.get("reasoning_effort") or "low"
        current_temp = str(self.cfg.get("temperature", 0.2))
        current_tokens = str(self.cfg.get("max_tokens", 16384))

        yield Static(f"[bold cyan]Configure alt-agent-harness[/]  [dim]({self.cfg_path})[/]")
        yield Static("[dim]Choose your LLM provider, enter API credentials, and select your model.[/]")
        yield Static("")

        # 1. Provider
        yield Label("LLM Provider:", classes="form-label")
        yield Select(
            self._get_provider_options(),
            value=current_provider,
            id="provider_select",
            allow_blank=False,
        )

        # 2. Base URL
        yield Label("API Base URL (Endpoint):", classes="form-label")
        yield Input(
            value=current_base_url,
            placeholder="e.g. https://api.openai.com/v1 or http://localhost:11434/v1",
            id="base_url_input",
        )

        # 3. API Key
        yield Label("API Key:", classes="form-label")
        env_var_name = preset.get("env", "API_KEY")
        env_val = os.environ.get(env_var_name, "").strip() if env_var_name else ""
        env_hint = f" [green](Found in {env_var_name})[/]" if env_val else f" [dim](or set {env_var_name})[/]"
        yield Static(f"[dim]Credential for this provider[/]{env_hint}", classes="form-hint")
        yield Input(
            value=current_api_key or env_val,
            placeholder="Enter API key (optional for local endpoints)",
            password=True,
            id="api_key_input",
        )

        # 4. Model Selection
        yield Label("Model / LLM:", classes="form-label")
        model_options = self._get_model_options_for_provider(current_provider)
        initial_select_val = current_model if any(val == current_model for _, val in model_options) else "__custom__"
        yield Select(
            model_options,
            value=initial_select_val,
            id="model_select",
            allow_blank=False,
        )

        yield Label("Exact Model String:", classes="form-label")
        yield Input(
            value=current_model,
            placeholder="e.g. grok-4.6, gpt-4o, anthropic/claude-3.7-sonnet",
            id="model_input",
        )

        # 5. Tavily Search Key
        yield Label("Tavily Search API Key (Optional):", classes="form-label")
        tavily_env = os.environ.get("TAVILY_API_KEY", "").strip()
        tavily_hint = " [green](Found in TAVILY_API_KEY)[/]" if tavily_env else " [dim](enables web search tool)[/]"
        yield Static(f"[dim]Leave empty to disable the web search tool[/]{tavily_hint}", classes="form-hint")
        yield Input(
            value=current_tavily_key or tavily_env,
            placeholder="tvly-...",
            password=True,
            id="tavily_key_input",
        )

        # 6. Advanced Parameters
        yield Label("Advanced Parameters:", classes="form-label")
        yield Horizontal(
            Vertical(
                Label("Reasoning Effort:", classes="form-label"),
                Select(
                    [("low", "low"), ("medium", "medium"), ("high", "high"), ("none", "")],
                    value=current_reasoning if current_reasoning in ("low", "medium", "high", "") else "low",
                    id="reasoning_select",
                    allow_blank=False,
                ),
            ),
            Vertical(
                Label("Temperature:", classes="form-label"),
                Input(value=current_temp, id="temp_input", placeholder="0.2"),
            ),
            Vertical(
                Label("Max Tokens:", classes="form-label"),
                Input(value=current_tokens, id="tokens_input", placeholder="16384"),
            ),
            classes="form-row",
        )

        # 7. Status message box
        yield Static("[dim]Ready. Click 'Test Connection' to verify or 'Save' to apply.[/]", id="status_box")

        # 8. Action buttons
        yield Horizontal(
            Button("Test Connection", id="btn_test", variant="default"),
            Button("Save Configuration", id="btn_save", variant="primary"),
            Button("Cancel", id="btn_cancel", variant="error"),
            classes="btn-row",
        )

    @on(Select.Changed, "#provider_select")
    def on_provider_changed(self, event: Select.Changed) -> None:
        provider = str(event.value)
        if provider not in config.PROVIDERS:
            return
        if provider == self._current_provider:
            return
        self._current_provider = provider
        preset = config.PROVIDERS[provider]

        # Update base URL
        base_url_input = self.query_one("#base_url_input", Input)
        base_url_input.value = preset.get("base_url", "")

        # Check env for this provider
        env_name = preset.get("env", "")
        env_val = os.environ.get(env_name, "").strip() if env_name else ""
        api_key_input = self.query_one("#api_key_input", Input)
        if not api_key_input.value or api_key_input.value.startswith("sk-") or api_key_input.value.startswith("xai-"):
            if env_val:
                api_key_input.value = env_val

        # Update model options
        model_select = self.query_one("#model_select", Select)
        new_options = self._get_model_options_for_provider(provider)
        model_select.set_options(new_options)
        default_model = preset.get("model", "")
        model_select.value = default_model if any(val == default_model for _, val in new_options) else "__custom__"

        model_input = self.query_one("#model_input", Input)
        model_input.value = default_model

        status = self.query_one("#status_box", Static)
        status.update(f"[dim]Switched provider to [bold]{preset.get('name', provider)}[/].[/]")

    @on(Select.Changed, "#model_select")
    def on_model_selected(self, event: Select.Changed) -> None:
        val = str(event.value)
        if val and val != "__custom__":
            model_input = self.query_one("#model_input", Input)
            model_input.value = val

    def _collect_config(self) -> dict[str, Any]:
        provider = str(self.query_one("#provider_select", Select).value or "xai")
        base_url = self.query_one("#base_url_input", Input).value.strip()
        api_key = self.query_one("#api_key_input", Input).value.strip()
        model = self.query_one("#model_input", Input).value.strip()
        tavily_key = self.query_one("#tavily_key_input", Input).value.strip()
        reasoning = str(self.query_one("#reasoning_select", Select).value or "")

        try:
            temperature = float(self.query_one("#temp_input", Input).value.strip())
        except ValueError:
            temperature = 0.2

        try:
            max_tokens = int(self.query_one("#tokens_input", Input).value.strip())
        except ValueError:
            max_tokens = 16384

        data = dict(self.cfg)
        data.update({
            "provider": provider,
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "tavily_api_key": tavily_key,
            "reasoning_effort": reasoning,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return data

    @on(Button.Pressed, "#btn_test")
    def on_test_pressed(self) -> None:
        status = self.query_one("#status_box", Static)
        status.update("[yellow]Testing connection to LLM endpoint...[/]")
        cfg_data = self._collect_config()
        self._run_test_connection(cfg_data)

    @work(thread=True)
    def _run_test_connection(self, data: dict[str, Any]) -> None:
        status = self.query_one("#status_box", Static)
        provider = data.get("provider", "")
        base_url = data.get("base_url") or "https://api.x.ai/v1"
        api_key = data.get("api_key") or ("dummy" if provider == "custom" else "none")
        model = data.get("model") or "grok-4.6"

        headers = None
        if provider == "openrouter":
            headers = {
                "HTTP-Referer": "https://openrouter.ai",
                "X-Title": "alt-agent-harness",
            }

        start = time.time()
        try:
            client = OpenAI(
                api_key=api_key,
                base_url=base_url.rstrip("/"),
                timeout=15,
                default_headers=headers,
            )
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hello! Ping."}],
                max_tokens=15,
            )
            elapsed = time.time() - start
            reply = ""
            if resp.choices and resp.choices[0].message and resp.choices[0].message.content:
                reply = resp.choices[0].message.content.strip().replace("\n", " ")
                if len(reply) > 40:
                    reply = reply[:40] + "..."
            snippet = f': "{reply}"' if reply else ""
            self.app.call_from_thread(
                status.update,
                f"[bold green]✓ Connection successful![/] Model replied{snippet} [dim]({elapsed:.2f}s)[/]",
            )
        except Exception as exc:
            elapsed = time.time() - start
            msg = str(exc)
            if len(msg) > 160:
                msg = msg[:160] + "..."
            self.app.call_from_thread(
                status.update,
                f"[bold red]✗ Connection failed[/] [dim]({elapsed:.2f}s)[/]:\n{msg}",
            )

    @on(Button.Pressed, "#btn_save")
    def on_save_pressed(self) -> None:
        cfg_data = self._collect_config()
        config.save(cfg_data, self.cfg_path)
        status = self.query_one("#status_box", Static)
        status.update(f"[bold green]✓ Saved configuration to {self.cfg_path}[/]")
        if self.on_save_callback:
            self.on_save_callback(cfg_data)

    @on(Button.Pressed, "#btn_cancel")
    def on_cancel_pressed(self) -> None:
        if self.on_cancel_callback:
            self.on_cancel_callback()


class ConfigModal(ModalScreen[dict | None]):
    """Modal screen used inside ChatApp."""

    DEFAULT_CSS = """
    ConfigModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #dialog {
        width: 80%;
        max-width: 90;
        height: 85%;
        border: thick $accent;
        background: $surface;
        padding: 1;
    }
    """
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, cfg: dict, cfg_path: Path | str):
        super().__init__()
        self.cfg = cfg
        self.cfg_path = cfg_path

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield ConfigForm(
                self.cfg,
                self.cfg_path,
                on_save_callback=self.action_save,
                on_cancel_callback=self.action_cancel,
            )

    def action_save(self, saved_cfg: dict) -> None:
        self.dismiss(saved_cfg)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfigApp(App[dict | None]):
    """Standalone Textual App for configuration."""

    TITLE = "alt-agent-harness - Settings"
    CSS = """
    Screen {
        layout: vertical;
    }
    """
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True, priority=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, cfg: dict, cfg_path: Path | str):
        super().__init__()
        self.cfg = cfg
        self.cfg_path = cfg_path
        self._saved_cfg: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ConfigForm(
            self.cfg,
            self.cfg_path,
            on_save_callback=self._on_saved,
            on_cancel_callback=self.action_cancel,
        )
        yield Footer()

    def _on_saved(self, saved_cfg: dict) -> None:
        self._saved_cfg = saved_cfg
        self.set_timer(0.8, lambda: self.exit(self._saved_cfg))

    def action_cancel(self) -> None:
        self.exit(None)


def run_config_tui(cfg: dict, cfg_path: Path | str, workspace: str | None = None) -> dict | None:
    """Run the standalone Config TUI."""
    app = ConfigApp(cfg, cfg_path)
    return app.run()


if __name__ == "__main__":
    import sys
    from agent.runtime import default_workspace

    ws = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else default_workspace()
    path = config.default_path(ws)
    loaded_cfg = config.load(path)
    run_config_tui(loaded_cfg, path)
