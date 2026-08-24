#!/usr/bin/env bash
# Backward-compatible name. Prefer start_local_mcp.sh.
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$project_dir/start_local_mcp.sh" "$@"
