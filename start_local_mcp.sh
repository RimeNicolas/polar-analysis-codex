#!/usr/bin/env bash
# Start the personal localhost MCP server. Use this for local development.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$project_dir/.venv/bin/python"

if [[ ! -x "$venv_python" ]]; then
  echo "Virtual environment not found. Run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

if [[ -f "$project_dir/.env.local" ]]; then
  set -a
  source "$project_dir/.env.local"
  set +a
fi

exec "$venv_python" "$project_dir/local_mcp_server.py" \
  --transport streamable-http --host 127.0.0.1 --port 8000 "$@"
