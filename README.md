# alt-agent-harness

A small skill-based agent that runs on your laptop. Same shape as
[esp32s3-agent](https://github.com/mngaonkar/esp32s3-ai-agent): an OpenAI-compatible
model, a local tool loop, and Anthropic-style **Skills** on disk.

The model never sees full skill bodies up front. The system prompt lists name +
description only; the agent loads a skill when it decides the request matches,
then uses tools (files, scripts, search) to do the work.

Default inference is **SpaceXAI** (`grok-4.6` at `https://api.x.ai/v1`).
**OpenRouter** works too: set `OPENROUTER_API_KEY` and the harness switches
endpoint and model (`x-ai/grok-4.6` at `https://openrouter.ai/api/v1`).

## Quick start

Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
export XAI_API_KEY=...                 # https://console.x.ai
# or: export OPENROUTER_API_KEY=...    # https://openrouter.ai/settings/keys
uv run alt-agent-harness
```

Keys can also live in a gitignored `.env` next to `config.json`:

```
OPENROUTER_API_KEY=sk-or-v1-...
# XAI_API_KEY=...
# TAVILY_API_KEY=...
uv run alt-agent-harness
```

Shell exports still win over `.env`. On first run, if there is no key in the
environment, `.env`, or `config.json`, the harness asks for a provider and key
and writes `config.json` (gitignored).

Non-interactive:

```bash
uv run alt-agent-harness -c "how's this machine doing?"
```

The default chat UI is a Textual TUI. Use `--repl` (or `--interface repl`) for
a plain stdin prompt — pipes, dumb terminals, or logging.

```bash
uv run alt-agent-harness --repl
uv run alt-agent-harness --workspace /path/to/other/checkout
```

`--workspace` is the project root (skills, config, `/tmp`). It defaults to the
current directory when that looks like a harness checkout.

### Commands

These are **user** slash commands, handled by `Session` before the model sees
the line. They are not model tools.

| Command | What it does |
|---|---|
| `/reset` | Clear conversation history |
| `/skills` | List installed skills (name + description) |
| `/tools` | List native tools the model can call |
| `/info` | Raw `host_status` snapshot for this process |
| `/help` | Show this list (`/?` also works) |
| `/quit` | Exit (`/exit` also works) |

TUI keys: `Ctrl+C` / `Ctrl+D` quit, `Ctrl+L` clear the log.

`/skills` is a catalog dump for you. `load_skill` is the **model** tool that
pulls a skill's full instructions into the current turn.

## How it is put together

```
you  ── TUI / REPL / (later: web, Discord) ──►  Session
                                                   │
                                                   ▼
                                              agent loop
                                                   │
                                    ├─ skills (instructions on disk)
                                    ├─ tools  (files, scripts, search)
                                    └─ HTTPS ──►  SpaceXAI or OpenRouter
```

Front-ends live in `interfaces/` and talk only to `Session`. The harness does
not import them, so a web or Discord adapter can be added without touching
the loop.

**Skills** are how to do a job in *this* workspace.

**Tools** are raw capability — `load_skill`, `list_skills`, `list_dir`, `read_file`,
`write_file`, `delete_file`, `run_script`, `host_status`, `http_get`, and
`tavily_search` when a Tavily key is set.

**The model** decides what to do next.

That split is why a new skill needs no code change: it is new instructions over
existing tools.

## Skills

A skill is a directory with a `SKILL.md` whose YAML frontmatter carries a
`name` and a `description`:

```
skills/sysinfo/
    SKILL.md
    scripts/rss_watch.py
```

Loading follows Anthropic's progressive disclosure model:

| Level | What loads | When |
|---|---|---|
| 1 | `name` + `description` only | always, in the system prompt |
| 2 | full `SKILL.md` body | when the model calls `load_skill` |
| 3 | bundled `scripts/` | via `read_file` / `run_script` |

The model talks to a **virtual filesystem** rooted at `/`. `/skills/sysinfo/SKILL.md`
is `skills/sysinfo/SKILL.md` in this repo. Writes are allowed only under
`/skills/` and `/tmp/`, so a bad tool call cannot overwrite the harness.

If a request matches a skill's description, the agent's first action must be
`load_skill` — that gating rule is in the system prompt on purpose. Direct
tool calls skip the procedure the skill exists to teach.

The agent can also **author skills itself**. `write_file` refuses a loose `.py`
under `/skills/`, a bundled file without a `SKILL.md`, and a manifest whose
`name` does not match its directory.

### Bundled skills

| Skill | Purpose |
|---|---|
| `sysinfo` | Host diagnostics. `host_status` plus `rss_watch.py`. |
| `websearch` | Live web lookup via Tavily — when to search, how to phrase queries. |
| `write-skill` | How to author new skills so the harness can extend itself. |

`tavily_search` is registered only when `tavily_api_key` is set, so the model is
never offered a tool that is guaranteed to fail. The name is not `web_search`
because grok-4.6 treats that as xAI's built-in server tool and returns an empty
reply instead of a function call.

Scripts reuse existing capability through `tool(name, args)`:

```python
tool("host_status", {})
```

Without a supported way to call a tool from a script, models invent one —
`import host_status` — which raises at run time.

## Config

Copy `config.example.json` to `config.json`, or let first-run setup write it.

| Key | Default | Notes |
|---|---|---|
| `provider` | `xai` | `xai` or `openrouter`. Inferred from env if omitted |
| `base_url` | `https://api.x.ai/v1` | OpenRouter: `https://openrouter.ai/api/v1` |
| `api_key` | *(empty)* | Or `XAI_API_KEY` / `OPENROUTER_API_KEY` (env or `.env`) |
| `model` | `grok-4.6` | OpenRouter: `x-ai/grok-4.6` (or any OpenRouter id) |
| `temperature` | `0.2` | Dropped automatically if the model rejects it |
| `max_tokens` | `16384` | Includes reasoning tokens. Switches to `max_completion_tokens` if the API requires it |
| `reasoning_effort` | `low` | `low` / `medium` / `high` / `xhigh`. grok-4.6 defaults to high if omitted, which can eat the token budget and return an empty reply after `load_skill` |
| `request_timeout` | `120` | Seconds per LLM request |
| `max_tool_iterations` | `50` | Skill authoring needs the room |
| `history_limit` | `40` | Oldest turns drop; tool-call pairs are never split |
| `system_prompt` | *(empty)* | Appended to the built-in prompt |
| `tavily_api_key` | *(empty)* | Enables `tavily_search` (or `TAVILY_API_KEY`) |
| `tavily_max_results` | `5` | Sources per search |
| `tavily_search_depth` | `basic` | Passed through to Tavily |

## Layout

```
src/agent/cli.py         process entry: boot Session, pick an interface
src/agent/runtime.py     config + tools + skills → Session
src/agent/session.py     interface-agnostic ask / slash commands / events
src/agent/loop.py        agent loop: prompt -> tools -> observations -> answer
src/agent/tools.py       native tools (load_skill, files, scripts, search)
src/agent/skills.py      skill discovery and progressive disclosure
src/agent/config.py      config.json + .env + provider inference
src/agent/setup.py       first-run API-key prompt
src/agent/paths.py       virtual filesystem (/skills, /tmp) over the workspace
src/agent/llm.py         OpenAI-compatible client (SpaceXAI or OpenRouter)
src/interfaces/tui.py    default Textual chat UI
src/interfaces/repl.py   plain stdin REPL (`--repl`)
skills/<name>/           bundled skills
```

## Tests

```bash
uv run pytest
```
