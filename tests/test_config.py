from agent.config import OPENROUTER_MODEL, OPENROUTER_URL, load, load_dotenv, save


def _clear_keys(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def test_load_defaults_and_file_override(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    missing = tmp_path / "nope.json"
    cfg = load(missing)
    assert cfg["provider"] == "xai"
    assert cfg["model"] == "grok-4.6"
    assert cfg["base_url"] == "https://api.x.ai/v1"
    assert cfg["api_key"] == ""

    path = tmp_path / "config.json"
    save({"model": "grok-4.5", "api_key": "file-key", "base_url": "https://api.x.ai/v1"}, path)
    cfg = load(path)
    assert cfg["model"] == "grok-4.5"
    assert cfg["api_key"] == "file-key"
    assert cfg["provider"] == "xai"


def test_env_fills_empty_api_key(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    path = tmp_path / "config.json"
    save({"api_key": "", "model": "grok-4.6"}, path)
    monkeypatch.setenv("XAI_API_KEY", "env-key")
    cfg = load(path)
    assert cfg["api_key"] == "env-key"
    assert cfg["provider"] == "xai"


def test_file_key_not_overwritten_by_env(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    path = tmp_path / "config.json"
    save({"api_key": "file-key"}, path)
    monkeypatch.setenv("XAI_API_KEY", "env-key")
    cfg = load(path)
    assert cfg["api_key"] == "file-key"


def test_openrouter_env_switches_provider(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = load(tmp_path / "missing.json")
    assert cfg["provider"] == "openrouter"
    assert cfg["api_key"] == "sk-or-test"
    assert cfg["base_url"] == OPENROUTER_URL
    assert cfg["model"] == OPENROUTER_MODEL


def test_openrouter_env_does_not_override_explicit_xai(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    path = tmp_path / "config.json"
    save({"provider": "xai", "api_key": "xai-file"}, path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = load(path)
    assert cfg["provider"] == "xai"
    assert cfg["api_key"] == "xai-file"
    assert cfg["base_url"] == "https://api.x.ai/v1"


def test_explicit_openrouter_provider_uses_its_env(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    path = tmp_path / "config.json"
    save({"provider": "openrouter", "api_key": "", "model": "anthropic/claude-sonnet-4"}, path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("XAI_API_KEY", "xai-ignored")
    cfg = load(path)
    assert cfg["provider"] == "openrouter"
    assert cfg["api_key"] == "sk-or-test"
    assert cfg["base_url"] == OPENROUTER_URL
    assert cfg["model"] == "anthropic/claude-sonnet-4"


def test_both_env_keys_default_to_xai(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("XAI_API_KEY", "xai-env")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = load(tmp_path / "missing.json")
    assert cfg["provider"] == "xai"
    assert cfg["api_key"] == "xai-env"
    assert cfg["model"] == "grok-4.6"


def test_dotenv_fills_openrouter_key(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    (tmp_path / ".env").write_text(
        '# comment\n'
        'export OPENROUTER_API_KEY="sk-or-from-file"\n'
        "TAVILY_API_KEY=tvly-from-file\n"
    )
    cfg = load(tmp_path / "config.json")
    assert cfg["provider"] == "openrouter"
    assert cfg["api_key"] == "sk-or-from-file"
    assert cfg["tavily_api_key"] == "tvly-from-file"


def test_dotenv_does_not_override_shell_env(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-shell")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sk-or-file\n")
    cfg = load(tmp_path / "missing.json")
    assert cfg["api_key"] == "sk-or-shell"


def test_load_dotenv_missing_file(tmp_path):
    assert load_dotenv(tmp_path) is None
