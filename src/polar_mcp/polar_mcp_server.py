#!/usr/bin/env python3
"""Shared Polar MCP application.

Use ``local_mcp_server.py`` for a personal localhost server and
``hosted_mcp_server.py`` for the Auth0-protected Render deployment. This file
contains the shared MCP tools and Polar callback routes only.
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from .polar_mcp_auth import MCPAuthenticationError, auth0_settings_from_environment, authenticated_user_id, is_admin
from .polar_mcp_oauth import (
    PolarNotConnectedError,
    PolarOAuthConfig,
    PolarOAuthError,
    authorization_url,
    credential_store_from_environment,
    exchange_token,
    get_valid_polar_access_token,
)
from .polar_service import get_activities_for_token


def public_auth_enabled() -> bool:
    return os.environ.get("MCP_AUTH_MODE", "development").strip().lower() == "auth0"


def mcp_auth_options() -> dict[str, Any]:
    if not public_auth_enabled():
        return {}
    auth, verifier = auth0_settings_from_environment()
    return {"auth": auth, "token_verifier": verifier}


mcp = MCPServer(
    "Polar Activities",
    instructions="This server is read-only. Use get_activities for a date range. If Polar is not connected, ask the user to open the returned authorization_url.",
    **mcp_auth_options(),
)


def get_current_user_id(_: Request | None = None) -> str:
    """Return a verified MCP user in public mode, or one local user in development."""
    if public_auth_enabled():
        return authenticated_user_id(get_access_token())
    return os.environ.get("POLAR_DEV_USER_ID", "development-user").strip() or "development-user"


def current_user_is_admin() -> bool:
    """Return whether the current public MCP request has the Auth0 admin role."""
    if not public_auth_enabled():
        return False
    _, verifier = auth0_settings_from_environment()
    return is_admin(get_access_token(), verifier.config.admin_role)


def oauth_dependencies() -> tuple[PolarOAuthConfig, Any]:
    return PolarOAuthConfig.from_environment(), credential_store_from_environment()


def authorization_required_response(user_id: str) -> dict[str, str]:
    try:
        config, store = oauth_dependencies()
        return {
            "error": "polar_not_connected",
            "message": "Connect your Polar account before using this tool.",
            # State is created while the MCP bearer token is present. The
            # browser callback does not need, and never receives, that token.
            "authorization_url": authorization_url(config, store, user_id),
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
        user_id = get_current_user_id()
    except MCPAuthenticationError as error:
        return {"error": "mcp_authentication_error", "message": str(error)}
    try:
        config, store = oauth_dependencies()
        store.record_activity_request(user_id)
        token = get_valid_polar_access_token(user_id, config, store)
    except PolarNotConnectedError:
        return authorization_required_response(user_id)
    except PolarOAuthError as error:
        return {"error": "polar_authorization_error", "message": str(error)}
    return get_activities_for_token(from_date, to_date, token, features)


@mcp.tool()
def get_server_metrics(from_date: str, to_date: str) -> dict[str, Any]:
    """Retrieve aggregate hosted MCP usage metrics for an inclusive YYYY-MM-DD date range.

    Use only for service administration. Requires the Auth0 `polar-mcp-admin`
    role (or the configured AUTH0_ADMIN_ROLE); returns no user identities,
    Polar tokens, or activity data.
    """
    if not public_auth_enabled():
        return {"error": "admin_metrics_hosted_only", "message": "Server metrics are available only in the Auth0-protected hosted deployment."}
    try:
        if not current_user_is_admin():
            return {"error": "admin_role_required", "message": "This tool requires the Auth0 administrator role."}
        _, store = oauth_dependencies()
        return store.usage_metrics(from_date, to_date).as_dict()
    except (MCPAuthenticationError, PolarOAuthError) as error:
        return {"error": "metrics_unavailable", "message": str(error)}


@mcp.custom_route("/polar/login", methods=["GET"], name="polar_login")
async def polar_login(request: Request) -> RedirectResponse | HTMLResponse:
    if public_auth_enabled():
        return HTMLResponse("<h1>Use the authorization link returned by the MCP tool.</h1>", status_code=400)
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
        help="Compatibility entry point. Prefer local_mcp_server.py or hosted_mcp_server.py.",
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"), help="HTTP bind address (localhost by default)")
    parser.add_argument("--port", default=int(os.environ.get("PORT", "8000")), type=int, help="HTTP port for streamable-http")
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
