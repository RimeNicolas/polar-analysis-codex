#!/usr/bin/env bash
# Start the localhost-only allow-list proxy for Polar OAuth browser callbacks.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$project_dir/.venv/bin/python"

if [[ ! -x "$venv_python" ]]; then
  echo "Virtual environment not found. Install project dependencies first." >&2
  exit 1
fi

cd "$project_dir"
exec "$venv_python" polar_oauth_callback_proxy.py "$@"
