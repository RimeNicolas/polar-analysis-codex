#!/usr/bin/env python3
"""Local MCP server exposing Polar activities through a single read-only tool."""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from polar_mcp_oauth import (
    PolarNotConnectedError,
    PolarOAuthConfig,
    PolarOAuthError,
    SQLitePolarCredentialStore,
    authorization_start_url,
    authorization_url,
    default_store_path,
    exchange_token,
    get_valid_polar_access_token,
)
from polar_service import get_activities_for_token


mcp = MCPServer(
    "Polar Activities",
    instructions="This server is read-only. Use get_activities for a date range. If Polar is not connected, ask the user to open the returned authorization_url.",
)


def get_current_user_id(_: Request | None = None) -> str:
    """Development-only identity seam; replace with verified MCP/app identity in production."""
    return os.environ.get("POLAR_DEV_USER_ID", "development-user").strip() or "development-user"


def oauth_dependencies() -> tuple[PolarOAuthConfig, SQLitePolarCredentialStore]:
    return PolarOAuthConfig.from_environment(), SQLitePolarCredentialStore(default_store_path())


def authorization_required_response() -> dict[str, str]:
    try:
        config, _ = oauth_dependencies()
        return {
            "error": "polar_not_connected",
            "message": "Connect your Polar account before using this tool.",
            "authorization_url": authorization_start_url(config),
        }
    except PolarOAuthError as error:
        return {"error": "polar_configuration_missing", "message": str(error)}


@mcp.tool()
def get_activities(
    from_date: str,
    to_date: str,
    features: list[str] | None = None,
) -> dict[str, Any]:
    """Retrieve Polar activities in an inclusive YYYY-MM-DD date range.

    Returns normalized rows with date, sport type, duration, distance, speed,
    calories, heart rate, power, and every other returned Polar field. Leave
    features empty for summary-only data; omit it for standard details.
    """
    try:
        config, store = oauth_dependencies()
        token = get_valid_polar_access_token(get_current_user_id(), config, store)
    except PolarNotConnectedError:
        return authorization_required_response()
    except PolarOAuthError as error:
        return {"error": "polar_authorization_error", "message": str(error)}
    return get_activities_for_token(from_date, to_date, token, features)


@mcp.custom_route("/polar/login", methods=["GET"], name="polar_login")
async def polar_login(request: Request) -> RedirectResponse | HTMLResponse:
    try:
        config, store = oauth_dependencies()
        return RedirectResponse(authorization_url(config, store, get_current_user_id(request)), status_code=302)
    except PolarOAuthError as error:
        return HTMLResponse(f"<h1>Polar connection unavailable</h1><p>{error}</p>", status_code=500)


@mcp.custom_route("/polar/callback", methods=["GET"], name="polar_callback")
async def polar_callback(request: Request) -> HTMLResponse:
    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    if not state or not code:
        return HTMLResponse("<h1>Polar connection failed</h1><p>Missing authorization response. Please try again.</p>", status_code=400)
    try:
        config, store = oauth_dependencies()
        user_id = store.consume_state(state)
        if user_id is None:
            return HTMLResponse("<h1>Polar connection failed</h1><p>This authorization link is invalid or expired. Please try again.</p>", status_code=400)
        token = exchange_token(config, {"grant_type": "authorization_code", "code": code, "redirect_uri": config.redirect_uri})
        store.save_credentials(user_id, token)
    except PolarOAuthError:
        return HTMLResponse("<h1>Polar connection failed</h1><p>Polar authorization could not be completed. Please try again.</p>", status_code=400)
    return HTMLResponse("<h1>Polar account connected successfully.</h1><p>You can return to ChatGPT.</p>")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="stdio for local MCP hosts; streamable-http for a Secure MCP Tunnel",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (localhost by default)")
    parser.add_argument("--port", default=8000, type=int, help="HTTP port for streamable-http")
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
