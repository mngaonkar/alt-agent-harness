"""Thin shim so `python src/main.py` still works. Prefer `uv run alt-agent-harness`."""

from agent.cli import main

if __name__ == "__main__":
    main()
