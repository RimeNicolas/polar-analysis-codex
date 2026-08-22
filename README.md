# Polar cycling CSV exporter

This command-line app downloads all Polar Flow training sessions in a date range and writes one Excel-friendly CSV row per session. It uses the current Polar AccessLink v4 training-session endpoint, so reading data does not commit or remove it.

## One-time Polar authorization

The first export can guide you through authorization automatically. Before doing it, register `http://localhost:8080/callback` as a redirect URL for your client in [Polar AccessLink Admin](https://admin.polaraccesslink.com/). Then run:

```bash
python polar_oauth.py setup
```

It prompts once for your client ID and client secret, opens Polar in your browser, captures the approval callback, and saves its credentials and refresh token outside the project in `~/.config/polar-csv-exporter/`, with owner-only file permissions. Do not put that directory in Git or share it.

The files are readable YAML:

* `credentials.yml` holds your client ID, client secret, and callback address.
* `tokens.yml` holds the current access token, refresh token, expiry, and granted scope.

You enter the client credentials only during setup. The access token lasts 12 hours; later exports use the saved refresh token to fetch a replacement automatically.

After that, simply run an export. The exporter refreshes its 12-hour access token automatically; no authorization code or token copying is needed. It asks Polar for `training_sessions:read`, `sports:read`, and `profile:read`. The first two support session exports and sport-name mapping; `profile:read` supports the optional account export below. Polar's catalogue can be empty for some accounts, so the exporter also recognizes Polar's Cycling sport ID directly. If access is revoked or your authorization predates these scopes, run `python polar_oauth.py reauthorize`.

## Export Polar account data

Retrieve the authorized user's Polar account profile and save it as owner-readable JSON (`0600` permissions where supported):

```bash
python polar_account.py
```

The default output is `exports/polar_account.json`. It can contain sensitive personal information, including name, email, birthdate, height, weight, training background, heart-rate thresholds, contact details, and consent records. Do not commit or share it. To select another destination:

```bash
python polar_account.py --output /private/path/polar_account.json
```

If your existing OAuth grant predates the `profile:read` scope, run `python polar_oauth.py reauthorize` once and approve access. The exporter never writes the access token or client credentials into the account JSON and does not print them.

## Manual-token setup (optional)

Create a virtual environment and install the only dependency:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

You can also supply an active Polar OAuth access token manually. This is useful for testing, but the automated authorization above is more convenient.

```bash
export POLAR_ACCESS_TOKEN='your-token-here'
```

Alternatively, put only the token in a local file outside version control and use `--token-file /path/to/polar-token.txt`.

## Export all activities

```bash
python polar_export.py --from 2026-07-01 --to 2026-07-31
```

For the latest seven calendar days (today plus the preceding six days), use:

```bash
./export_last_7_days.sh
```

It writes a dated file such as `exports/polar_activities_260815-260821.csv`.

The end date is inclusive. The exporter sends each boundary to Polar as midnight in ISO datetime form. The default output is `exports/polar_activities.csv`, encoded as UTF-8 with a BOM so Excel recognizes accented characters. Open the file directly in Excel or use **Data → From Text/CSV**.

The first CSV columns are `date`, `sport_type`, `duration`, `distance` (km), `avg_speed`, `calories`, `avg_hr`, and `avg_power`; every other field returned by Polar follows. `avg_speed` and `avg_power` are Polar's raw statistics values, without unit conversion.

By default the exporter asks for useful optional details (`statistics`, `zones`, `laps`, `pause-times`, and `comments`). Polar allows optional features only one day at a time; the exporter automatically splits a larger range into day requests. Nested objects become dotted CSV columns, while arrays remain compact JSON in one cell.

Useful variants:

```bash
# Summary fields only; up to 90 days per API request
python polar_export.py --from 2026-01-01 --to 2026-03-31 --features ''

# Choose the CSV path
python polar_export.py --from 2026-08-01 --to 2026-08-15 --output ~/Downloads/august-activities.csv
```

The AccessLink OAuth token must include the `training_sessions:read` scope. If the API reports `401`, obtain a fresh token through your Polar application’s authorization flow.

## MCP server

`polar_mcp_server.py` is a thin, local MCP layer over the existing OAuth and Polar retrieval code. It provides one read-only tool, `get_activities(from_date, to_date, features=None)`, returning activity rows as structured data instead of writing a CSV.

Install the dependencies first, then use the MCP Inspector for local testing:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mcp dev polar_mcp_server.py
```

The server uses standard input/output by default, so a local MCP-capable host can launch it as a child process. A portable launch command is:

```bash
uv run --with "mcp[cli]" mcp run /home/nicolas/Documents/ChatGPT/polar-analysis-codex/polar_mcp_server.py
```

The existing local OAuth files under `~/.config/polar-csv-exporter/` continue to provide the credential and refreshed token; the MCP server never exposes them as a tool result.

### ChatGPT connection

ChatGPT cannot connect directly to a local stdio server. For the ChatGPT Secure MCP Tunnel route, run this server in Streamable HTTP mode, bound only to your computer:

```bash
source .venv/bin/activate
python polar_mcp_server.py --transport streamable-http --host 127.0.0.1 --port 8000
```

Or use the included launcher from the project directory:

```bash
./start_polar_mcp.sh
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Keep this terminal running, then use ChatGPT's Secure MCP Tunnel flow to make the local endpoint available to ChatGPT without exposing it publicly. Do not use `--host 0.0.0.0` or a public tunnel for this personal-health-data server.

### Private ChatGPT tunnel

After installing OpenAI's `tunnel-client` in `tools/bin/`, create a tunnel in [OpenAI Platform](https://platform.openai.com/settings/organization/tunnels), then run:

```bash
./start_polar_tunnel.sh tunnel_YOUR_ID
```

The launcher starts the Polar server on localhost, creates a local tunnel-client profile, checks it, and keeps the tunnel in the foreground. It reads the runtime OpenAI key only from the ignored `.env.local` file. Keep this command running while using the private developer-mode plugin in ChatGPT; no inbound port is opened and no Polar credential is exposed.
