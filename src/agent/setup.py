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
    if xai_key and not or_key:
        cfg["provider"] = "xai"
        cfg["api_key"] = xai_key
        config.apply_provider(cfg)
        print("[setup] using XAI_API_KEY from the environment")
        config.save(cfg, path)
        return cfg
    if or_key and not xai_key:
        cfg["provider"] = "openrouter"
        cfg["api_key"] = or_key
        config.apply_provider(cfg)
        print("[setup] using OPENROUTER_API_KEY from the environment")
        config.save(cfg, path)
        return cfg
    if xai_key and or_key:
        # Both set: honour an explicit provider, otherwise SpaceXAI.
        provider = (cfg.get("provider") or "xai").strip().lower()
        if provider not in config.PROVIDERS:
            provider = "xai"
        cfg["provider"] = provider
        cfg["api_key"] = or_key if provider == "openrouter" else xai_key
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
    print("Providers: xai (SpaceXAI) or openrouter\n")
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
