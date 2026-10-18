"""First-run setup.

A fresh checkout has no config.json. Rather than fail with an unhelpful
error, ask for the one setting that cannot be guessed — an API key — and
write the file.
"""

import getpass
import os

from . import config


BANNER = """
==============================================
  First-time setup
==============================================
This harness has no API key yet. One answer
is required; press Enter to accept the
default shown in [brackets].
"""


def needed(cfg):
    if cfg.get("provider") == "custom" and cfg.get("base_url"):
        return False
    return not cfg.get("api_key")


def _ask(prompt, default=None, required=False, secret=False):
    while True:
        suffix = " [%s]" % default if default else ""
        label = "%s%s: " % (prompt, suffix)
        try:
            if secret:
                answer = getpass.getpass(label).strip()
            else:
                answer = input(label).strip()
        except (EOFError, KeyboardInterrupt):
            raise SetupAborted()

        if not answer and default is not None:
            answer = default
        if not answer:
            if required:
                print("  ...this one is required.")
                continue
            return ""
        return answer


class SetupAborted(Exception):
    pass


def _from_env(cfg, path):
    xai_key = os.environ.get("XAI_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    active_keys = {
        "xai": xai_key,
        "openrouter": or_key,
        "openai": openai_key,
    }
    present = {p: k for p, k in active_keys.items() if k}

    if len(present) == 1:
        provider, key = next(iter(present.items()))
        cfg["provider"] = provider
        cfg["api_key"] = key
        config.apply_provider(cfg)
        print("[setup] using %s from the environment" % config.PROVIDERS[provider]["env"])
        config.save(cfg, path)
        return cfg

    if len(present) > 1:
        # Multiple set: honour explicit provider, otherwise SpaceXAI
        provider = (cfg.get("provider") or "xai").strip().lower()
        if provider not in present:
            provider = "xai" if "xai" in present else next(iter(present))
        cfg["provider"] = provider
        cfg["api_key"] = present[provider]
        config.apply_provider(cfg)
        print("[setup] using %s from the environment" % config.PROVIDERS[provider]["env"])
        config.save(cfg, path)
        return cfg

    return None


def run(cfg, path):
    """Prompt for the mandatory settings and save. Returns the updated cfg."""
    from_env = _from_env(cfg, path)
    if from_env is not None:
        return from_env

    print(BANNER)
    print("Providers: xai, openrouter, openai, or custom\n")
    provider = _ask("Provider", "xai").strip().lower()
    if provider not in config.PROVIDERS:
        print("  ...unknown provider; using xai")
        provider = "xai"
    cfg["provider"] = provider
    preset = config.PROVIDERS[provider]

    if provider == "openrouter":
        print("Create a key at https://openrouter.ai/settings/keys\n")
        cfg["api_key"] = _ask("OpenRouter API key (OPENROUTER_API_KEY)",
                              required=True, secret=True)
    elif provider == "openai":
        print("Create a key at https://platform.openai.com/api-keys\n")
        cfg["api_key"] = _ask("OpenAI API key (OPENAI_API_KEY)",
                              required=True, secret=True)
    elif provider == "custom":
        cfg["base_url"] = _ask("Endpoint Base URL", preset["base_url"], required=True)
        cfg["api_key"] = _ask("API key (optional for local endpoints)", secret=True)
    else:
        print("Create a key at https://console.x.ai\n")
        cfg["api_key"] = _ask("SpaceXAI API key (XAI_API_KEY)",
                              required=True, secret=True)

    config.apply_provider(cfg)

    print("\nOptional -- press Enter to skip:")
    model = _ask("Model", cfg.get("model", preset["model"]))
    if model:
        cfg["model"] = model
    tavily = _ask("Tavily API key (enables web search)", secret=True)
    if tavily:
        cfg["tavily_api_key"] = tavily

    config.save(cfg, path)
    print("\nSaved to %s. Starting the agent...\n" % path)
    return cfg


def maybe_run(cfg, path):
    if not needed(cfg):
        return cfg
    return run(cfg, path)
