#!/usr/bin/env bash
# Start the OAuth-only localhost proxy and a temporary Cloudflare HTTPS tunnel.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
venv_python="$project_dir/.venv/bin/python"
cloudflared="$project_dir/tools/bin/cloudflared"

if [[ ! -x "$venv_python" || ! -x "$cloudflared" ]]; then
  echo "Missing .venv or tools/bin/cloudflared. Install project dependencies and Cloudflare client first." >&2
  exit 1
fi

export PYTHONPATH="$project_dir/src${PYTHONPATH:+:$PYTHONPATH}"
"$venv_python" -m polar_mcp.polar_oauth_callback_proxy --host 127.0.0.1 --port 8081 &
proxy_pid=$!

cleanup() {
  kill "$proxy_pid" 2>/dev/null || true
  wait "$proxy_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Waiting for the callback-only proxy on http://127.0.0.1:8081..."
for _ in {1..30}; do
  if curl --silent --output /dev/null --max-time 1 http://127.0.0.1:8081/polar/login; then
    break
  fi
  sleep 0.2
done

echo "Copy the https://...trycloudflare.com URL printed below."
echo "Set POLAR_REDIRECT_URI to that URL plus /polar/callback, then register it in Polar AccessLink Admin."
"$cloudflared" tunnel --url http://127.0.0.1:8081
