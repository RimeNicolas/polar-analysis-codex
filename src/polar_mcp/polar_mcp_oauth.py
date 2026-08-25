"""Per-user Polar OAuth support for the development MCP server.

The SQLite implementation is deliberately small and replaceable.  It keeps
Polar tokens server-side and never returns them through MCP tools or routes.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests


POLAR_AUTHORIZE_URL = "https://auth.polar.com/oauth/authorize"
POLAR_TOKEN_URL = "https://auth.polar.com/oauth/token"
POLAR_SCOPE = "training_sessions:read sports:read"
STATE_TTL_SECONDS = 10 * 60
TOKEN_REFRESH_MARGIN_SECONDS = 60


class PolarOAuthError(RuntimeError):
    """A safe error raised for a Polar OAuth problem."""


class PolarNotConnectedError(PolarOAuthError):
    """Raised when an application user has not authorized Polar."""


@dataclass(frozen=True)
class PolarOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_environment(cls) -> "PolarOAuthConfig":
        environment = {name: os.environ.get(name, "").strip() for name in ("POLAR_CLIENT_ID", "POLAR_CLIENT_SECRET", "POLAR_REDIRECT_URI")}
        missing = [name for name, value in environment.items() if not value]
        if missing:
            raise PolarOAuthError("Polar OAuth is not configured. Set POLAR_CLIENT_ID, POLAR_CLIENT_SECRET, and POLAR_REDIRECT_URI.")
        parsed = urlsplit(environment["POLAR_REDIRECT_URI"])
        if parsed.scheme != "https" or not parsed.netloc or parsed.path != "/polar/callback":
            raise PolarOAuthError("POLAR_REDIRECT_URI must be an HTTPS URL ending in /polar/callback.")
        return cls(
            client_id=environment["POLAR_CLIENT_ID"],
            client_secret=environment["POLAR_CLIENT_SECRET"],
            redirect_uri=environment["POLAR_REDIRECT_URI"],
        )

    @property
    def public_base_url(self) -> str:
        parsed = urlsplit(self.redirect_uri)
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


@dataclass(frozen=True)
class PolarCredentials:
    access_token: str
    refresh_token: str
    expires_at: int
    scope: str


@dataclass(frozen=True)
class MCPUsageMetrics:
    """Aggregated, non-identifying hosted MCP usage metrics."""

    from_date: str
    to_date: str
    activity_requests: int
    unique_requesting_users: int
    new_polar_connections: int
    total_polar_connected_users: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "from_date": self.from_date,
            "to_date": self.to_date,
            "activity_requests": self.activity_requests,
            "unique_requesting_users": self.unique_requesting_users,
            "new_polar_connections": self.new_polar_connections,
            "total_polar_connected_users": self.total_polar_connected_users,
        }


class PolarCredentialStore(Protocol):
    def create_state(self, user_id: str) -> str: ...

    def consume_state(self, state: str) -> str | None: ...

    def load_credentials(self, user_id: str) -> PolarCredentials | None: ...

    def save_credentials(self, user_id: str, token: dict[str, Any]) -> None: ...

    def record_activity_request(self, user_id: str, requested_at: int | None = None) -> None: ...

    def usage_metrics(self, from_date: str, to_date: str) -> MCPUsageMetrics: ...


def usage_range(from_date: str, to_date: str) -> tuple[date, date, int, int]:
    """Parse an inclusive ISO date range and return UTC epoch boundaries."""
    try:
        start_date = date.fromisoformat(from_date)
        end_date = date.fromisoformat(to_date)
    except ValueError as error:
        raise PolarOAuthError("Metrics dates must use YYYY-MM-DD format.") from error
    if end_date < start_date:
        raise PolarOAuthError("Metrics to_date must be on or after from_date.")
    start = int(datetime.combine(start_date, datetime_time.min, tzinfo=timezone.utc).timestamp())
    end_exclusive = int(datetime.combine(end_date + timedelta(days=1), datetime_time.min, tzinfo=timezone.utc).timestamp())
    return start_date, end_date, start, end_exclusive


class SQLitePolarCredentialStore:
    """Development credential store. Replace this class with a database adapter later."""

    def __init__(self, database_path: Path):
        self.database_path = database_path.expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.database_path.parent, 0o700)
        except OSError:
            pass
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS polar_credentials (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    scope TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mcp_activity_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    requested_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS mcp_activity_requests_requested_at_idx
                    ON mcp_activity_requests (requested_at);
                """
            )
        try:
            os.chmod(self.database_path, 0o600)
        except OSError:
            pass

    def _ensure_user(self, connection: sqlite3.Connection, user_id: str, now: int) -> None:
        connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, ?)", (user_id, now))

    def create_state(self, user_id: str) -> str:
        state = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._connect() as connection:
            self._ensure_user(connection, user_id, now)
            connection.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now,))
            connection.execute("INSERT INTO oauth_states (state, user_id, expires_at) VALUES (?, ?, ?)", (state, user_id, now + STATE_TTL_SECONDS))
        return state

    def consume_state(self, state: str) -> str | None:
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute("SELECT user_id, expires_at FROM oauth_states WHERE state = ?", (state,)).fetchone()
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if row is None or row["expires_at"] <= now:
            return None
        return str(row["user_id"])

    def load_credentials(self, user_id: str) -> PolarCredentials | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT access_token, refresh_token, expires_at, scope FROM polar_credentials WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        return PolarCredentials(
            access_token=str(row["access_token"]),
            refresh_token=str(row["refresh_token"]),
            expires_at=int(row["expires_at"]),
            scope=str(row["scope"]),
        )

    def save_credentials(self, user_id: str, token: dict[str, Any]) -> None:
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        if not isinstance(access_token, str) or not access_token or not isinstance(refresh_token, str) or not refresh_token:
            raise PolarOAuthError("Polar did not return the required credentials.")
        now = int(time.time())
        expires_at = now + int(token.get("expires_in", 0))
        scope = str(token.get("scope", POLAR_SCOPE))
        with self._connect() as connection:
            self._ensure_user(connection, user_id, now)
            connection.execute(
                """
                INSERT INTO polar_credentials (user_id, access_token, refresh_token, expires_at, scope, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    scope = excluded.scope,
                    updated_at = excluded.updated_at
                """,
                (user_id, access_token, refresh_token, expires_at, scope, now, now),
            )

    def record_activity_request(self, user_id: str, requested_at: int | None = None) -> None:
        now = int(time.time()) if requested_at is None else requested_at
        with self._connect() as connection:
            self._ensure_user(connection, user_id, now)
            connection.execute("INSERT INTO mcp_activity_requests (user_id, requested_at) VALUES (?, ?)", (user_id, now))

    def usage_metrics(self, from_date: str, to_date: str) -> MCPUsageMetrics:
        start_date, end_date, start, end_exclusive = usage_range(from_date, to_date)
        with self._connect() as connection:
            usage = connection.execute(
                """SELECT COUNT(*) AS activity_requests, COUNT(DISTINCT user_id) AS unique_requesting_users
                FROM mcp_activity_requests WHERE requested_at >= ? AND requested_at < ?""",
                (start, end_exclusive),
            ).fetchone()
            new_connections = connection.execute(
                "SELECT COUNT(*) AS count FROM polar_credentials WHERE created_at >= ? AND created_at < ?", (start, end_exclusive)
            ).fetchone()
            total_connections = connection.execute("SELECT COUNT(*) AS count FROM polar_credentials").fetchone()
        return MCPUsageMetrics(
            from_date=start_date.isoformat(),
            to_date=end_date.isoformat(),
            activity_requests=int(usage["activity_requests"]),
            unique_requesting_users=int(usage["unique_requesting_users"]),
            new_polar_connections=int(new_connections["count"]),
            total_polar_connected_users=int(total_connections["count"]),
        )


class PostgresPolarCredentialStore:
    """Production credential store backed by a managed PostgreSQL database."""

    def __init__(self, database_url: str):
        import psycopg

        self.database_url = database_url
        self._psycopg = psycopg
        self._initialize()

    def _connect(self):
        return self._psycopg.connect(self.database_url, row_factory=self._psycopg.rows.dict_row)

    def _initialize(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, created_at BIGINT NOT NULL);
                CREATE TABLE IF NOT EXISTS polar_credentials (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    access_token TEXT NOT NULL, refresh_token TEXT NOT NULL, expires_at BIGINT NOT NULL,
                    scope TEXT NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mcp_activity_requests (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    requested_at BIGINT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS mcp_activity_requests_requested_at_idx
                    ON mcp_activity_requests (requested_at);
                """
            )

    @staticmethod
    def _ensure_user(cursor: Any, user_id: str, now: int) -> None:
        cursor.execute("INSERT INTO users (id, created_at) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (user_id, now))

    def create_state(self, user_id: str) -> str:
        state, now = secrets.token_urlsafe(32), int(time.time())
        with self._connect() as connection, connection.cursor() as cursor:
            self._ensure_user(cursor, user_id, now)
            cursor.execute("DELETE FROM oauth_states WHERE expires_at <= %s", (now,))
            cursor.execute("INSERT INTO oauth_states (state, user_id, expires_at) VALUES (%s, %s, %s)", (state, user_id, now + STATE_TTL_SECONDS))
        return state

    def consume_state(self, state: str) -> str | None:
        now = int(time.time())
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM oauth_states WHERE state = %s RETURNING user_id, expires_at", (state,))
            row = cursor.fetchone()
        if row is None or int(row["expires_at"]) <= now:
            return None
        return str(row["user_id"])

    def load_credentials(self, user_id: str) -> PolarCredentials | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT access_token, refresh_token, expires_at, scope FROM polar_credentials WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
        return None if row is None else PolarCredentials(str(row["access_token"]), str(row["refresh_token"]), int(row["expires_at"]), str(row["scope"]))

    def save_credentials(self, user_id: str, token: dict[str, Any]) -> None:
        access_token, refresh_token = token.get("access_token"), token.get("refresh_token")
        if not isinstance(access_token, str) or not access_token or not isinstance(refresh_token, str) or not refresh_token:
            raise PolarOAuthError("Polar did not return the required credentials.")
        now, expires_at, scope = int(time.time()), int(time.time()) + int(token.get("expires_in", 0)), str(token.get("scope", POLAR_SCOPE))
        with self._connect() as connection, connection.cursor() as cursor:
            self._ensure_user(cursor, user_id, now)
            cursor.execute(
                """INSERT INTO polar_credentials (user_id, access_token, refresh_token, expires_at, scope, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET access_token = EXCLUDED.access_token, refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at, scope = EXCLUDED.scope, updated_at = EXCLUDED.updated_at""",
                (user_id, access_token, refresh_token, expires_at, scope, now, now),
            )

    def record_activity_request(self, user_id: str, requested_at: int | None = None) -> None:
        now = int(time.time()) if requested_at is None else requested_at
        with self._connect() as connection, connection.cursor() as cursor:
            self._ensure_user(cursor, user_id, now)
            cursor.execute("INSERT INTO mcp_activity_requests (user_id, requested_at) VALUES (%s, %s)", (user_id, now))

    def usage_metrics(self, from_date: str, to_date: str) -> MCPUsageMetrics:
        start_date, end_date, start, end_exclusive = usage_range(from_date, to_date)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS activity_requests, COUNT(DISTINCT user_id) AS unique_requesting_users
                FROM mcp_activity_requests WHERE requested_at >= %s AND requested_at < %s""",
                (start, end_exclusive),
            )
            usage = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS count FROM polar_credentials WHERE created_at >= %s AND created_at < %s", (start, end_exclusive))
            new_connections = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS count FROM polar_credentials")
            total_connections = cursor.fetchone()
        return MCPUsageMetrics(
            from_date=start_date.isoformat(),
            to_date=end_date.isoformat(),
            activity_requests=int(usage["activity_requests"]),
            unique_requesting_users=int(usage["unique_requesting_users"]),
            new_polar_connections=int(new_connections["count"]),
            total_polar_connected_users=int(total_connections["count"]),
        )


def default_store_path() -> Path:
    configured = os.environ.get("POLAR_TOKEN_STORE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "polar-mcp" / "credentials.sqlite3"


def credential_store_from_environment() -> PolarCredentialStore:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return PostgresPolarCredentialStore(database_url)
    if os.environ.get("MCP_AUTH_MODE", "development").strip().lower() == "auth0":
        raise PolarOAuthError("Public mode requires DATABASE_URL for persistent per-user Polar credentials.")
    return SQLitePolarCredentialStore(default_store_path())


def authorization_url(config: PolarOAuthConfig, store: PolarCredentialStore, user_id: str) -> str:
    state = store.create_state(user_id)
    query = urlencode(
        {
            "client_id": config.client_id,
            "response_type": "code",
            "redirect_uri": config.redirect_uri,
            "scope": POLAR_SCOPE,
            "state": state,
        }
    )
    return f"{POLAR_AUTHORIZE_URL}?{query}"


def authorization_start_url(config: PolarOAuthConfig) -> str:
    return f"{config.public_base_url}/polar/login"


def exchange_token(config: PolarOAuthConfig, data: dict[str, str]) -> dict[str, Any]:
    try:
        response = requests.post(POLAR_TOKEN_URL, auth=(config.client_id, config.client_secret), data=data, timeout=30)
        response.raise_for_status()
        token = response.json()
    except (requests.RequestException, ValueError) as error:
        raise PolarOAuthError("Polar authorization could not be completed. Please try again.") from error
    if not isinstance(token, dict) or not token.get("access_token") or not token.get("refresh_token"):
        raise PolarOAuthError("Polar authorization returned an incomplete credential response.")
    return token


def get_valid_polar_access_token(user_id: str, config: PolarOAuthConfig, store: PolarCredentialStore) -> str:
    credentials = store.load_credentials(user_id)
    if credentials is None:
        raise PolarNotConnectedError("Connect your Polar account before using this tool.")
    if credentials.expires_at > time.time() + TOKEN_REFRESH_MARGIN_SECONDS:
        return credentials.access_token
    refreshed = exchange_token(config, {"grant_type": "refresh_token", "refresh_token": credentials.refresh_token})
    if not refreshed.get("refresh_token"):
        refreshed["refresh_token"] = credentials.refresh_token
    store.save_credentials(user_id, refreshed)
    return str(refreshed["access_token"])
