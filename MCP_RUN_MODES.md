# Running the Polar MCP server

The project has two intentional ways to run the same Polar tools. Choose one;
they are separate deployments, not two processes that need to run together.

| Use case | Start command | Where it runs | Authentication and token store |
| --- | --- | --- | --- |
| Personal local development | `./scripts/start_local_mcp.sh` | This Linux machine, `127.0.0.1:8000` | One development user; private SQLite database on this machine |
| Personal ChatGPT connection through an OpenAI tunnel | `./scripts/start_local_mcp_tunnel.sh` | This Linux machine, reachable only through the Secure MCP Tunnel | Same local SQLite database; requires `.env.local` and the tunnel client |
| Hosted ChatGPT app | Render runs `python -m polar_mcp.hosted_mcp_server` | Render, public HTTPS `/mcp` endpoint | Auth0 user access token plus optional PostgreSQL; otherwise, in-memory Polar tokens until restart |

## Local mode

Use local mode when you are developing on this Linux machine or prefer the private
OpenAI Secure MCP Tunnel.

```bash
./scripts/start_local_mcp.sh
```

This runs `src/polar_mcp/local_mcp_server.py` in Streamable HTTP mode. It always selects
`MCP_AUTH_MODE=development` and binds only to localhost. It reads local-only
settings from `.env.local` and uses this machine's SQLite file:

```text
~/.local/share/polar-mcp/credentials.sqlite3
```

To use ChatGPT with the local server, use the tunnel launcher instead:

```bash
./scripts/start_local_mcp_tunnel.sh
```

The tunnel launcher starts the local server and then starts the OpenAI Secure
MCP Tunnel. Keep that command running (for example in tmux). It is the only
mode that needs `OPENAI_API_KEY` and `POLAR_MCP_TUNNEL_ID`.

Polar's browser callback still needs a temporary public HTTPS address because
Polar must redirect the browser back to your laptop. Start the callback-only
Cloudflare tunnel separately when reconnecting a Polar account:

```bash
./scripts/start_polar_oauth_tunnel.sh
```

That callback tunnel exposes only `/polar/login` and `/polar/callback`, never
the local `/mcp` endpoint.

## Hosted mode

Use hosted mode when ChatGPT should reach the server directly over the web.
Render's Docker image runs:

```bash
python -m polar_mcp.hosted_mcp_server
```

This entry point always selects `MCP_AUTH_MODE=auth0`. It expects these secrets
to be configured in the Render dashboard, never in `.env.local`:

```text
MCP_PUBLIC_URL
AUTH0_DOMAIN
AUTH0_AUDIENCE
POLAR_CLIENT_ID
POLAR_CLIENT_SECRET
POLAR_REDIRECT_URI
```

In this mode the public `/mcp` endpoint verifies an Auth0 token before it can
read any Polar data. `DATABASE_URL` is an optional additional Render variable:
when set, PostgreSQL stores
each user's Polar access and refresh tokens. Without it, the server uses an
in-memory store; tokens and usage metrics are lost on a restart or redeploy, so
users authorize Polar again. No OpenAI Secure MCP Tunnel is involved.

## Shared code

`src/polar_mcp/polar_mcp_server.py` is deliberately not a launch target in normal use. It
contains the shared `get_activities` MCP tool and the Polar OAuth callback
routes used by both modes.

`src/polar_mcp/local_mcp_server.py` defaults to stdio when it is launched directly, which is
useful for the MCP Inspector or a local MCP host. The `scripts/start_local_mcp.sh` and
`scripts/start_local_mcp_tunnel.sh` scripts explicitly select Streamable HTTP instead.

Other relevant files:

| File | Responsibility |
| --- | --- |
| `src/polar_mcp/polar_mcp_oauth.py` | Polar authorization URLs, token exchange/refresh, SQLite, in-memory, and PostgreSQL credential stores |
| `src/polar_mcp/polar_mcp_auth.py` | Auth0 token verification; used only by hosted mode |
| `src/polar_mcp/polar_service.py` | Requests and normalizes activity data from Polar |
| `Dockerfile`, `render.yaml` | Hosted Render deployment only |

Hosted mode also records aggregate `get_activities` usage in its active store.
Without PostgreSQL, those metrics reset with the server. The
`get_server_metrics` tool is available only to an Auth0 user with the
`polar-mcp-admin` role; see the **Hosted admin metrics** section in the README
for the one-time Auth0 Action and role setup.

## Compatibility names

The older `scripts/start_polar_mcp.sh` and `scripts/start_polar_tunnel.sh` commands still work,
but now forward to the clearly named local commands above. Prefer the new
names in future notes and tmux sessions.
