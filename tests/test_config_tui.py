import asyncio
from pathlib import Path
from textual.widgets import Button, Input, Select

from agent import config
from interfaces.config_tui import ConfigApp, ConfigModal


def test_config_app_composes(tmp_path):
    cfg_path = tmp_path / "config.json"
    initial_cfg = {
        "provider": "openai",
        "api_key": "sk-test",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "tavily_api_key": "tvly-test",
    }
    app = ConfigApp(initial_cfg, cfg_path)

    async def _run():
        async with app.run_test() as pilot:
            provider_sel = app.query_one("#provider_select", Select)
            assert provider_sel.value == "openai"

            base_url_in = app.query_one("#base_url_input", Input)
            assert base_url_in.value == "https://api.openai.com/v1"

            model_in = app.query_one("#model_input", Input)
            assert model_in.value == "gpt-4o"

            tavily_in = app.query_one("#tavily_key_input", Input)
            assert tavily_in.value == "tvly-test"

    asyncio.run(_run())


def test_config_switch_provider_updates_fields(tmp_path):
    cfg_path = tmp_path / "config.json"
    initial_cfg = {
        "provider": "xai",
        "api_key": "xai-test",
        "model": "grok-4.6",
    }
    app = ConfigApp(initial_cfg, cfg_path)

    async def _run():
        async with app.run_test() as pilot:
            provider_sel = app.query_one("#provider_select", Select)
            # Switch to custom endpoint
            provider_sel.value = "custom"
            await pilot.pause()

            base_url_in = app.query_one("#base_url_input", Input)
            assert base_url_in.value == "http://localhost:11434/v1"

            model_in = app.query_one("#model_input", Input)
            assert model_in.value == "llama3.2"

    asyncio.run(_run())


def test_config_save_writes_file(tmp_path):
    cfg_path = tmp_path / "config.json"
    initial_cfg = {
        "provider": "openrouter",
        "api_key": "sk-or-test",
        "model": "anthropic/claude-3.7-sonnet",
    }
    app = ConfigApp(initial_cfg, cfg_path)

    async def _run():
        async with app.run_test() as pilot:
            btn_save = app.query_one("#btn_save", Button)
            btn_save.press()
            await pilot.pause()

            assert cfg_path.is_file()
            loaded = config.load(cfg_path)
            assert loaded["provider"] == "openrouter"
            assert loaded["model"] == "anthropic/claude-3.7-sonnet"
            assert loaded["api_key"] == "sk-or-test"

    asyncio.run(_run())
