"""Load and save config.json. Credentials stay out of the source tree."""

import json
import os
from pathlib import Path


XAI_URL = "https://api.x.ai/v1"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
XAI_MODEL = "grok-4.6"
OPENROUTER_MODEL = "x-ai/grok-4.6"

PROVIDERS = {
    "xai": {
        "base_url": XAI_URL,
        "env": "XAI_API_KEY",
        "model": XAI_MODEL,
    },
    "openrouter": {
        "base_url": OPENROUTER_URL,
        "env": "OPENROUTER_API_KEY",
        "model": OPENROUTER_MODEL,
    },
}

_DEFAULTS = {
    # SpaceXAI by default; set provider to "openrouter" to use OpenRouter.
    "provider": "xai",
    "base_url": XAI_URL,
    "api_key": "",
    "model": XAI_MODEL,
    "temperature": 0.2,
    "max_tokens": 16384,
    # grok-4.6 defaults to high reasoning, which burns max_tokens and can
    # return an empty reply after load_skill. low is what xAI recommends
    # for tool-calling agents.
    "reasoning_effort": "low",
    # Tavily web search. Leave empty to omit the tavily_search tool.
    "tavily_api_key": "",
    "tavily_max_results": 5,
    "tavily_search_depth": "basic",
    "request_timeout": 120,
    "skills_dir": "/skills",
    "max_tool_iterations": 50,
    "history_limit": 40,
    "system_prompt": "",
}


class Config(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def default_path(workspace):
    return Path(workspace) / "config.json"


def _parse_dotenv_line(line):
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[7:].strip()
    if "=" not in text:
        return None
    key, _, value = text.partition("=")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    if not key:
        return None
    return key, value


def load_dotenv(directory):
    """Load KEY=value pairs from directory/.env into os.environ.

    Existing environment variables win; the file never overrides a shell export.
    Returns the path loaded, or None if there was no file.
    """
    path = Path(directory) / ".env"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        print("[config] could not read %s: %s" % (path, exc))
        return None

    loaded = 0
    for line in raw.splitlines():
        parsed = _parse_dotenv_line(line)
        if not parsed:
            continue
        key, value = parsed
        if key not in os.environ:
            os.environ[key] = value
            loaded += 1
    if loaded:
        print("[config] loaded %d var(s) from %s" % (loaded, path))
    return path


def infer_provider(cfg):
    explicit = (cfg.get("provider") or "").strip().lower()
    if explicit in PROVIDERS:
        return explicit
    xai_key = os.environ.get("XAI_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    file_key = (cfg.get("api_key") or "").strip()
    if or_key and not xai_key and not file_key:
        return "openrouter"
    return "xai"


def apply_provider(cfg):
    """Fill provider, api_key, base_url, and model from env / presets.

    Mutates and returns cfg. A custom base_url or model is left alone unless
    it is still the other provider's default (so `export OPENROUTER_API_KEY`
    is enough to switch).
    """
    provider = infer_provider(cfg)
    cfg["provider"] = provider
    preset = PROVIDERS[provider]
    other = PROVIDERS["openrouter" if provider == "xai" else "xai"]

    if not (cfg.get("api_key") or "").strip():
        env_key = os.environ.get(preset["env"], "").strip()
        if env_key:
            cfg["api_key"] = env_key

    if not cfg.get("base_url") or cfg.get("base_url") == other["base_url"]:
        cfg["base_url"] = preset["base_url"]
    if not cfg.get("model") or cfg.get("model") == other["model"]:
        cfg["model"] = preset["model"]
    if not (cfg.get("tavily_api_key") or "").strip():
        tavily = os.environ.get("TAVILY_API_KEY", "").strip()
        if tavily:
            cfg["tavily_api_key"] = tavily
    return cfg


def load(path):
    cfg = dict(_DEFAULTS)
    path = Path(path)
    load_dotenv(path.parent)
    user = {}
    try:
        with open(path) as f:
            user = json.load(f)
        if not isinstance(user, dict):
            raise ValueError("config.json must contain a JSON object")
        cfg.update(user)
    except FileNotFoundError:
        print("[config] %s not found; using defaults" % path)

    # Default provider is xai, but that must not block auto-detecting
    # OPENROUTER_API_KEY when the file never named a provider.
    if "provider" not in user:
        cfg["provider"] = ""
    apply_provider(cfg)
    return Config(cfg)


def save(cfg, path):
    path = Path(path)
    serializable = {k: v for k, v in cfg.items()}
    with open(path, "w") as f:
        json.dump(serializable, f, indent=2)
        f.write("\n")
