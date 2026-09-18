#!/usr/bin/env bash
# Launch alt-agent-harness from the repo root. Extra args are passed through:
#   ./run.sh
#   ./run.sh --repl
#   ./run.sh -c "how's this machine doing?"
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  uv sync
fi

# `.env` next to config.json (gitignored). Shell exports still win.
if [[ -f .env ]]; then
  exec uv run --env-file .env alt-agent-harness "$@"
fi

exec uv run alt-agent-harness "$@"
