# Polar Analysis MCP

Polar Analysis MCP is a read-only [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) service for querying Polar Flow activities from ChatGPT or another MCP client. It connects each user to Polar through OAuth, retrieves their training sessions through Polar AccessLink, and returns structured activity data to the client.

It supports two ways to run the same service:

* **Hosted:** an Auth0-protected MCP endpoint on Render. It uses PostgreSQL when configured, or an ephemeral in-memory token store at no database cost.
* **Local:** a private server on this Linux machine, optionally connected to ChatGPT through the OpenAI Secure MCP Tunnel; Polar tokens remain on the machine.

The repository also includes a local command-line CSV exporter for loading activities into Excel. All Polar operations are read-only: the service never changes or removes data in Polar Flow.

Start with [MCP_RUN_MODES.md](MCP_RUN_MODES.md) to choose between the local and hosted setup.

## Project layout

```text
src/polar_mcp/  Python package: exporter, Polar OAuth, MCP tools, and server entry points
scripts/        Bash commands for local exports, local MCP, tunnel, and callback tunnel
tests/          Automated Python tests
Dockerfile      Hosted Render container configuration
render.yaml     Hosted Render service configuration
```

Install the local package once inside the virtual environment before using a
`python -m polar_mcp...` command:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -e .
```

## Local CSV exporter: one-time Polar authorization

The first export can guide you through authorization automatically. Before doing it, register `http://localhost:8080/callback` as a redirect URL for your client in [Polar AccessLink Admin](https://admin.polaraccesslink.com/). Then run:

```bash
python -m polar_mcp.polar_oauth setup
```

It prompts once for your client ID and client secret, opens Polar in your browser, captures the approval callback, and saves its credentials and refresh token outside the project in `~/.config/polar-csv-exporter/`, with owner-only file permissions. Do not put that directory in Git or share it.

The files are readable YAML:

* `credentials.yml` holds your client ID, client secret, and callback address.
* `tokens.yml` holds the current access token, refresh token, expiry, and granted scope.

You enter the client credentials only during setup. The access token lasts 12 hours; later exports use the saved refresh token to fetch a replacement automatically.

After that, simply run an export. The exporter refreshes its 12-hour access token automatically; no authorization code or token copying is needed. It asks Polar for `training_sessions:read`, `sports:read`, and `profile:read`. The first two support session exports and sport-name mapping; `profile:read` supports the optional account export below. Polar's catalogue can be empty for some accounts, so the exporter also recognizes Polar's Cycling sport ID directly. If access is revoked or your authorization predates these scopes, run `python -m polar_mcp.polar_oauth reauthorize`.

## Export Polar account data

Retrieve the authorized user's Polar account profile and save it as owner-readable JSON (`0600` permissions where supported):

```bash
python -m polar_mcp.polar_account
```

The default output is `exports/polar_account.json`. It can contain sensitive personal information, including name, email, birthdate, height, weight, training background, heart-rate thresholds, contact details, and consent records. Do not commit or share it. To select another destination:

```bash
python -m polar_mcp.polar_account --output /private/path/polar_account.json
```

If your existing OAuth grant predates the `profile:read` scope, run `python -m polar_mcp.polar_oauth reauthorize` once and approve access. The exporter never writes the access token or client credentials into the account JSON and does not print them.

## Manual-token setup (optional)

Create a virtual environment and install the only dependency:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -e .
```

You can also supply an active Polar OAuth access token manually. This is useful for testing, but the automated authorization above is more convenient.

```bash
export POLAR_ACCESS_TOKEN='your-token-here'
```

Alternatively, put only the token in a local file outside version control and use `--token-file /path/to/polar-token.txt`.

## Export all activities

```bash
python -m polar_mcp.polar_export --from 2026-07-01 --to 2026-07-31
```

For the latest seven calendar days (today plus the preceding six days), use:

```bash
./scripts/export_last_7_days.sh
```

It writes a dated file such as `exports/polar_activities_260815-260821.csv`.

The end date is inclusive. The exporter sends each boundary to Polar as midnight in ISO datetime form. The default output is `exports/polar_activities.csv`, encoded as UTF-8 with a BOM so Excel recognizes accented characters. Open the file directly in Excel or use **Data → From Text/CSV**.

The first CSV columns are `date`, `sport_type`, `duration`, `distance` (km), `avg_speed`, `calories`, `avg_hr`, and `avg_power`; every other field returned by Polar follows. `avg_speed` and `avg_power` are Polar's raw statistics values, without unit conversion.

By default the exporter asks for useful optional details (`statistics`, `zones`, `laps`, `pause-times`, and `comments`). Polar allows optional features only one day at a time; the exporter automatically splits a larger range into day requests. Nested objects become dotted CSV columns, while arrays remain compact JSON in one cell.

Useful variants:

```bash
# Summary fields only; up to 90 days per API request
python -m polar_mcp.polar_export --from 2026-01-01 --to 2026-03-31 --features ''

# Choose the CSV path
python -m polar_mcp.polar_export --from 2026-08-01 --to 2026-08-15 --output ~/Downloads/august-activities.csv
```

The AccessLink OAuth token must include the `training_sessions:read` scope. If the API reports `401`, obtain a fresh token through your Polar application’s authorization flow.

## MCP server

The MCP server provides one read-only tool,
`get_activities(from_date, to_date, features=None)`, returning activity rows as
structured data instead of writing a CSV. It can run locally through the
private OpenAI Secure MCP Tunnel, or as an Auth0-protected service on Render.
The hosted server additionally offers the Auth0-admin-only
`get_server_metrics(from_date, to_date)` tool.

See [MCP_RUN_MODES.md](MCP_RUN_MODES.md) first: it shows exactly which command
and configuration belong to local versus hosted use.

### Choose how to use it with ChatGPT

Choose **one** of these paths. They use the same Polar tool but different
servers and token stores.

#### Option A — run it from this Linux machine

Use this for private development or to keep Polar credentials on the machine.

1. Install dependencies once:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt -e .
   cp .env.local.example .env.local
   ```

2. Edit `.env.local` with your Polar credentials, OpenAI runtime key, and
   `POLAR_MCP_TUNNEL_ID`. This file is ignored by Git.
3. Start the local server and private ChatGPT tunnel:

   ```bash
   cd ~/Documents/ChatGPT/polar-analysis-codex
   ./scripts/start_local_mcp_tunnel.sh
   ```

4. Keep that command running. ChatGPT reaches your machine through the private
   OpenAI Secure MCP Tunnel. The local server stores Polar tokens in
   `~/.local/share/polar-mcp/credentials.sqlite3`.

For the first Polar connection (or after revoking it), start the separate
callback tunnel with `./scripts/start_polar_oauth_tunnel.sh`, update
`POLAR_REDIRECT_URI` in `.env.local` and Polar AccessLink Admin with the new
callback URL, then authorize Polar in the browser. The callback tunnel is only
needed during Polar authorization.

#### Option B — use the hosted Render server

Use this when ChatGPT should connect directly to the hosted service. Nothing
needs to run on the Linux machine in normal day-to-day use.

1. Create a Render Web Service from this repository. A Render PostgreSQL
   database is optional.
2. In Render, set `MCP_PUBLIC_URL`, `AUTH0_DOMAIN`, `AUTH0_AUDIENCE`,
   `POLAR_CLIENT_ID`, `POLAR_CLIENT_SECRET`, and
   `POLAR_REDIRECT_URI`.
3. In Auth0, create the `polar:activities:read` API permission, configure
   default third-party user access for that permission, enable DCR and the
   Resource Parameter Compatibility Profile, and promote the desired login
   connection to domain level.
4. In ChatGPT Developer Mode, create or update the app to use:

   ```text
   https://polar-mcp-nicolas.onrender.com/mcp
   ```

5. Let ChatGPT complete the Auth0 sign-in. On the first activity request,
   follow the Polar authorization link and approve access.

Render runs `python -m polar_mcp.hosted_mcp_server` and verifies Auth0 tokens.
If `DATABASE_URL` is set, each user's Polar access and refresh tokens are stored
in PostgreSQL. If it is absent, they remain only in the running Render process:
users must reconnect Polar after a restart, redeploy, or Render free-tier
spin-down. The in-memory option has no database cost and does not write tokens
to the container filesystem. The hosted service does not use the OpenAI Secure
MCP Tunnel. After a code change, push it to GitHub and allow Render to deploy
the new commit.

### Hosted admin metrics

After deploying the metrics version, `get_server_metrics(from_date, to_date)`
is available from ChatGPT only to users assigned the Auth0 role
`polar-mcp-admin`. It reports inclusive UTC-date totals:

* `activity_requests`: authenticated calls to `get_activities`, including a
  first call that prompts the user to connect Polar.
* `unique_requesting_users`: distinct Auth0 users making those calls.
* `new_polar_connections`: users who completed a first Polar connection in the
  selected period.
* `total_polar_connected_users`: all users with stored Polar credentials.

No names, email addresses, activity data, or tokens are returned. Activity
request counts begin only after this version is deployed; connection totals can
include Polar accounts stored since the current server process started when
running without PostgreSQL.

#### One-time Auth0 admin setup

1. In **User Management → Roles**, create a role named `polar-mcp-admin`.
2. Open your own user in **User Management → Users → Roles** and assign that
   role.
3. In **Actions → Flows → Login**, create and add a **Post Login** Action with:

   ```javascript
   exports.onExecutePostLogin = async (event, api) => {
     if (event.authorization) {
       api.accessToken.setCustomClaim(
         'https://polar-mcp-nicolas.onrender.com/roles',
         event.authorization.roles
       );
     }
   };
   ```

4. Disconnect and reconnect the ChatGPT app, so it receives a new Auth0 access
   token containing the role. Then ask ChatGPT, for example:

   ```text
   Use Polar Activities to show server metrics from 2026-08-01 to 2026-08-31.
   ```

If you use another public MCP URL later, replace the URL in the Action with
that exact `MCP_PUBLIC_URL` followed by `/roles`. You can instead configure
`AUTH0_ROLES_CLAIM` and `AUTH0_ADMIN_ROLE` as non-secret Render environment
variables when you need different names.

Install the dependencies first, then use the MCP Inspector for local testing:

```bash
python3 -m venv .venv
source .venv/bin/activate
   python -m pip install -r requirements.txt -e .
   python -m polar_mcp.local_mcp_server --transport stdio
```

The server uses standard input/output by default, so a local MCP-capable host can launch it as a child process. A portable launch command is:

```bash
python -m polar_mcp.local_mcp_server --transport stdio
```

### Local-only Polar OAuth connection

The MCP server now uses a separate, server-side Polar OAuth store. It never accepts a Polar token as a tool parameter and never returns a token. Its SQLite database is outside the repository by default at `~/.local/share/polar-mcp/credentials.sqlite3`, with owner-only permissions. It has separate rows per application user, so it can later move to a hosted database without changing the tool code.

Create the ignored `.env.local` file from `.env.local.example`, then set your
Polar app credentials and the exact temporary public callback URL:

```bash
POLAR_CLIENT_ID=your-polar-client-id
POLAR_CLIENT_SECRET=your-polar-client-secret
POLAR_REDIRECT_URI=https://your-public-oauth-host.example/polar/callback
POLAR_DEV_USER_ID=development-user
```

Register that exact `POLAR_REDIRECT_URI` in [Polar AccessLink Admin](https://admin.polaraccesslink.com/). Start the local MCP server, then ask the MCP client to call `get_activities`. Before Polar is connected, the result includes a safe `authorization_url`. Open it in a browser, approve Polar, and return to the client. Later calls use the stored refresh token automatically.

`POLAR_DEV_USER_ID` is deliberately a development-only identity seam: all calls from this local development instance identify as that value. The database and OAuth state are per user, but a real multi-user deployment must replace `get_current_user_id()` with verified MCP/app identity before serving more than one person.

### Local ChatGPT connection

ChatGPT cannot connect directly to a local stdio server. For the ChatGPT Secure MCP Tunnel route, run this server in Streamable HTTP mode, bound only to your computer:

```bash
./scripts/start_local_mcp.sh
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Keep this terminal running, then use ChatGPT's Secure MCP Tunnel flow to make the local endpoint available to ChatGPT without exposing it publicly. Do not use `--host 0.0.0.0` or a public tunnel for this personal-health-data server.

### Hosted Render + Auth0 setup

The local setup is single-user development only. For a public server, set `MCP_AUTH_MODE=auth0`; each MCP request must then have an Auth0 access token containing the `polar:activities:read` scope. The server verifies its issuer, audience, expiry, signature, and scope before it retrieves any Polar data. The verified Auth0 issuer and `sub` claim become the per-user credential key.

Deploy using the included `Dockerfile` and `render.yaml`. Set these Render
secrets: `MCP_PUBLIC_URL`, `AUTH0_DOMAIN`, `AUTH0_AUDIENCE`,
`POLAR_CLIENT_ID`, `POLAR_CLIENT_SECRET`, and `POLAR_REDIRECT_URI`. Use the
stable public URL for both `MCP_PUBLIC_URL` and `AUTH0_AUDIENCE`; set Polar's
callback to `https://your-host/polar/callback`.

`DATABASE_URL` is optional. If set, the server uses PostgreSQL and retains each
user's Polar credentials and usage metrics. If omitted, it uses memory only:
credentials and metrics are discarded whenever Render restarts or redeploys,
and users must authorize Polar again.

Auth0 must be configured as an OAuth 2.1 authorization server for the ChatGPT MCP client. In its API settings, create the `polar:activities:read` permission and use your MCP public URL as the API identifier/audience. Enable Dynamic Client Registration (DCR), set `polar:activities:read` as the default user-delegated permission for third-party apps, enable the Resource Parameter Compatibility Profile, and promote the selected login connection to domain level. The MCP SDK exposes the required protected-resource metadata at `/.well-known/oauth-protected-resource` when public mode is enabled. Do not deploy until these values and the OAuth flow have been tested end to end.

Polar sends its browser callback to a public HTTPS URL, which the Secure MCP Tunnel does not provide. To keep `/mcp` private, use the included callback-only proxy on a second localhost port:

```bash
./scripts/start_polar_oauth_callback_proxy.sh
```

Point a separate public HTTPS reverse tunnel **only** at `http://127.0.0.1:8081`, and use its `https://.../polar/callback` URL for `POLAR_REDIRECT_URI`. That proxy allows only `/polar/login` and `/polar/callback`; `/mcp` is not routed through it. Do not point a public tunnel directly at port 8000. The choice and setup of the HTTPS reverse-tunnel provider is intentionally left to you; the OpenAI Secure MCP Tunnel remains dedicated to the private MCP connection.

For a temporary development callback URL, run the downloaded Cloudflare `cloudflared` client through the included launcher:

```bash
./scripts/start_polar_oauth_tunnel.sh
```

It prints a temporary `https://...trycloudflare.com` address. Set `POLAR_REDIRECT_URI` to that address plus `/polar/callback`, then register the exact value with Polar. A Quick Tunnel URL changes when the command stops; update `.env.local` and Polar's redirect setting before the next OAuth login. For a permanent address, configure a named Cloudflare Tunnel with a domain you control.

### Use tmux during authorization

Cloudflare Quick Tunnel URLs change each time they start, so use a first tmux session to start the OAuth callback tunnel, then update `POLAR_REDIRECT_URI` and Polar AccessLink Admin before starting the MCP tunnel in a second session:

```bash
tmux new -s polar-oauth
./scripts/start_polar_oauth_tunnel.sh
# Copy the URL, update configuration, then detach with Ctrl-b followed by d.

tmux new -s polar-mcp
./scripts/start_local_mcp_tunnel.sh
```

Once Polar is connected, only `polar-mcp` is needed for normal activity queries. `POLAR_MCP_TUNNEL_ID` can be stored privately in `.env.local`, so `./scripts/start_local_mcp_tunnel.sh` needs no argument. Detach with `Ctrl-b`, then `d`; rejoin with `tmux attach -t polar-mcp`; stop it with `tmux kill-session -t polar-mcp`.

### Private ChatGPT tunnel

After installing OpenAI's `tunnel-client` in `tools/bin/`, create a tunnel in [OpenAI Platform](https://platform.openai.com/settings/organization/tunnels), then run:

```bash
./scripts/start_local_mcp_tunnel.sh tunnel_YOUR_ID
```

The launcher starts the Polar server on localhost, creates a local tunnel-client profile, checks it, and keeps the tunnel in the foreground. It reads the runtime OpenAI key only from the ignored `.env.local` file. Keep this command running while using the private developer-mode plugin in ChatGPT; no inbound port is opened and no Polar credential is exposed.
