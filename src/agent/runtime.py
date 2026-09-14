"""Boot the harness: config, tools, skills, Session.

Interfaces import boot() and then run themselves. Nothing here knows
about TUIs, REPLs, or other front-ends.
"""

from pathlib import Path

from agent import config, llm, loop, setup, skills, tools
from agent.paths import Workspace
from agent.session import Session


def default_workspace():
    """Prefer cwd when it looks like a harness workspace; else this checkout."""
    cwd = Path.cwd()
    if (cwd / "skills").is_dir() or (cwd / "config.example.json").is_file():
        return cwd
    # src/agent/runtime.py -> repo root in an editable checkout
    repo = Path(__file__).resolve().parents[2]
    if (repo / "skills").is_dir():
        return repo
    return cwd


def boot(workspace=None):
    """Load config, construct the agent, return a Session."""
    root = Path(workspace).resolve() if workspace else default_workspace()
    cfg_path = config.default_path(root)
    cfg = config.load(cfg_path)
    cfg = setup.maybe_run(cfg, cfg_path)

    ws = Workspace(root)
    (root / "tmp").mkdir(exist_ok=True)

    registry_skills = skills.SkillRegistry(ws, cfg.get("skills_dir", "/skills"))
    client = llm.Client(cfg)
    registry = tools.ToolRegistry(cfg, registry_skills, ws)
    agent = loop.Agent(cfg, client, registry, registry_skills)
    session = Session(agent, cfg, root)

    print("[boot] provider=%s model=%s tools=%d search=%s workspace=%s" % (
        session.provider, session.model, len(registry.schemas()),
        "tavily" if registry.tavily.enabled else "off",
        root))
    return session
