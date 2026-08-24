#!/usr/bin/env bash
# Start the personal localhost MCP server and its private OpenAI Secure MCP Tunnel.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$project_dir/.venv/bin/python"
tunnel_client="$project_dir/tools/bin/tunnel-client"
env_file="$project_dir/.env.local"
profile_dir="$project_dir/.tunnel-client"
profile_name="polar-flow"

usage() {
  echo "Usage: $0 [tunnel_YOUR_ID]" >&2
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ ! -x "$venv_python" ]]; then
  echo "Virtual environment not found. Install project dependencies first." >&2
  exit 1
fi
if [[ ! -x "$tunnel_client" ]]; then
  echo "tunnel-client not found at $tunnel_client." >&2
  exit 1
fi
if [[ ! -f "$env_file" ]]; then
  echo "OpenAI runtime key file not found at $env_file." >&2
  exit 1
fi

set -a
source "$env_file"
set +a
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is missing from $env_file." >&2
  exit 1
fi
export CONTROL_PLANE_API_KEY="${CONTROL_PLANE_API_KEY:-$OPENAI_API_KEY}"

tunnel_id="${1:-${POLAR_MCP_TUNNEL_ID:-}}"
if [[ ! "$tunnel_id" =~ ^tunnel_[A-Za-z0-9]+$ ]]; then
  usage
  exit 1
fi

mkdir -p "$profile_dir"
"$venv_python" "$project_dir/local_mcp_server.py" --transport streamable-http --host 127.0.0.1 --port 8000 &
polar_pid=$!

cleanup() {
  kill "$polar_pid" 2>/dev/null || true
  wait "$polar_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in {1..30}; do
  if curl --silent --output /dev/null --max-time 1 http://127.0.0.1:8000/mcp; then
    break
  fi
  if ! kill -0 "$polar_pid" 2>/dev/null; then
    echo "Local Polar MCP server stopped before the tunnel could start." >&2
    exit 1
  fi
  sleep 0.2
done

if ! curl --silent --output /dev/null --max-time 1 http://127.0.0.1:8000/mcp; then
  echo "Local Polar MCP server did not become reachable on localhost:8000." >&2
  exit 1
fi

"$tunnel_client" init \
  --sample sample_mcp_remote_no_auth \
  --profile "$profile_name" \
  --profile-dir "$profile_dir" \
  --tunnel-id "$tunnel_id" \
  --mcp-server-url http://127.0.0.1:8000/mcp \
  --health-listen-addr 127.0.0.1:0 \
  --force
"$tunnel_client" doctor --profile "$profile_name" --profile-dir "$profile_dir" --explain
"$tunnel_client" run --profile "$profile_name" --profile-dir "$profile_dir"
