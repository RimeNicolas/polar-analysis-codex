"""Auth0 validation for the public MCP resource server.

The MCP SDK exposes the OAuth protected-resource metadata and rejects requests
without a valid bearer token. This module verifies Auth0 JWT access tokens and
turns their issuer/subject pair into the application's stable user identity.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings


MCP_SCOPE = "polar:activities:read"
DEFAULT_ADMIN_ROLE = "polar-mcp-admin"


class MCPAuthenticationError(RuntimeError):
    """Raised when public MCP authentication is misconfigured."""


@dataclass(frozen=True)
class Auth0Config:
    issuer: str
    audience: str
    resource_server_url: str
    roles_claim: str
    admin_role: str

    @classmethod
    def from_environment(cls) -> "Auth0Config":
        domain = os.environ.get("AUTH0_DOMAIN", "").strip().rstrip("/")
        audience = os.environ.get("AUTH0_AUDIENCE", "").strip()
        resource_server_url = os.environ.get("MCP_PUBLIC_URL", "").strip().rstrip("/")
        missing = [name for name, value in {"AUTH0_DOMAIN": domain, "AUTH0_AUDIENCE": audience, "MCP_PUBLIC_URL": resource_server_url}.items() if not value]
        if missing:
            raise MCPAuthenticationError("Public mode requires AUTH0_DOMAIN, AUTH0_AUDIENCE, and MCP_PUBLIC_URL.")
        issuer = domain if domain.startswith("https://") else f"https://{domain}"
        issuer = issuer.rstrip("/") + "/"
        for name, value in {"AUTH0_DOMAIN": issuer, "MCP_PUBLIC_URL": resource_server_url}.items():
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.netloc:
                raise MCPAuthenticationError(f"{name} must be a public HTTPS URL.")
        roles_claim = os.environ.get("AUTH0_ROLES_CLAIM", f"{resource_server_url}/roles").strip()
        admin_role = os.environ.get("AUTH0_ADMIN_ROLE", DEFAULT_ADMIN_ROLE).strip()
        if not roles_claim or not admin_role:
            raise MCPAuthenticationError("AUTH0_ROLES_CLAIM and AUTH0_ADMIN_ROLE cannot be empty.")
        return cls(
            issuer=issuer,
            audience=audience,
            resource_server_url=resource_server_url,
            roles_claim=roles_claim,
            admin_role=admin_role,
        )


class Auth0TokenVerifier(TokenVerifier):
    """Verify RS256 Auth0 access tokens and enforce the MCP read scope."""

    def __init__(self, config: Auth0Config):
        self.config = config
        self.jwks_client = jwt.PyJWKClient(f"{config.issuer}.well-known/jwks.json", cache_keys=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = await asyncio.to_thread(self.jwks_client.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.config.audience,
                issuer=self.config.issuer,
            )
            scopes = str(claims.get("scope", "")).split()
            subject = claims.get("sub")
            if MCP_SCOPE not in scopes or not isinstance(subject, str) or not subject:
                return None
            raw_roles = claims.get(self.config.roles_claim, [])
            roles = [role for role in raw_roles if isinstance(role, str)] if isinstance(raw_roles, list) else []
            return AccessToken(
                token=token,
                client_id=str(claims.get("azp") or claims.get("client_id") or "chatgpt"),
                scopes=scopes,
                expires_at=int(claims["exp"]),
                resource=self.config.audience,
                subject=subject,
                claims={"iss": self.config.issuer, "roles": roles},
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            return None


def auth0_settings_from_environment() -> tuple[AuthSettings, Auth0TokenVerifier]:
    config = Auth0Config.from_environment()
    return (
        AuthSettings(
            issuer_url=config.issuer,
            resource_server_url=config.resource_server_url,
            required_scopes=[MCP_SCOPE],
        ),
        Auth0TokenVerifier(config),
    )


def authenticated_user_id(access_token: AccessToken | None) -> str:
    """Return a database-safe identity unique to the Auth0 issuer and subject."""
    if access_token is None or not access_token.subject:
        raise MCPAuthenticationError("This MCP request is not authenticated.")
    issuer = str((access_token.claims or {}).get("iss", ""))
    if not issuer:
        raise MCPAuthenticationError("The access token is missing its issuer.")
    return f"{issuer}|{access_token.subject}"


def is_admin(access_token: AccessToken | None, admin_role: str) -> bool:
    """Return whether a verified token carries the configured Auth0 admin role."""
    if access_token is None:
        return False
    roles = (access_token.claims or {}).get("roles", [])
    return isinstance(roles, list) and admin_role in roles
