#!/usr/bin/env python3
"""Authorize Polar once, then refresh and persist tokens for the CSV exporter."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


AUTHORIZE_URL = "https://auth.polar.com/oauth/authorize"
TOKEN_URL = "https://auth.polar.com/oauth/token"
SCOPE = "training_sessions:read sports:read profile:read"
DEFAULT_REDIRECT_URI = "http://localhost:8080/callback"


def default_credentials_file() -> Path:
    configured = os.environ.get("POLAR_EXPORT_CREDENTIALS_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "polar-csv-exporter" / "credentials.yml"


def token_file(credentials_file: Path) -> Path:
    return credentials_file.with_name("tokens.yml")


def read_yaml(path: Path) -> dict[str, Any] | None:
    """Read the small YAML mapping written below, without another dependency."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    value: dict[str, Any] = {}
    try:
        for line in lines:
            if not line or line.startswith("#"):
                continue
            key, encoded_value = line.split(": ", 1)
            value[key] = json.loads(encoded_value)
    except (ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid YAML in {path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected an object in {path}")
    return value


def write_private_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    yaml = "".join(f"{key}: {json.dumps(item, ensure_ascii=False)}\n" for key, item in value.items())
    path.write_text(yaml, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def prompt_credentials(credentials_file: Path) -> dict[str, str]:
    print("Polar client details are saved locally with owner-only permissions.")
    client_id = input("Polar client ID: ").strip()
    client_secret = getpass.getpass("Polar client secret: ").strip()
    redirect_uri = input(f"Redirect URI [{DEFAULT_REDIRECT_URI}]: ").strip() or DEFAULT_REDIRECT_URI
    if not client_id or not client_secret:
        raise RuntimeError("Both a client ID and client secret are required.")
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("This helper requires an http://localhost or http://127.0.0.1 redirect URI.")
    credentials = {"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}
    write_private_yaml(credentials_file, credentials)
    return credentials


def authorization_code(credentials: dict[str, str]) -> str:
    redirect_uri = credentials["redirect_uri"]
    parsed = urlparse(redirect_uri)
    if parsed.port is None:
        raise RuntimeError("The redirect URI must specify a port, for example http://localhost:8080/callback")
    state = secrets.token_urlsafe(24)
    url = f"{AUTHORIZE_URL}?{urlencode({'client_id': credentials['client_id'], 'response_type': 'code', 'scope': SCOPE, 'redirect_uri': redirect_uri, 'state': state})}"

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            received_state = query.get("state", [""])[0]
            if received_state != state:
                self.server.result = (None, "Invalid OAuth state. Please try again.")  # type: ignore[attr-defined]
                self.send_response(400)
                body = b"Authorization could not be verified. You can close this tab."
            elif "error" in query:
                self.server.result = (None, f"Polar authorization failed: {query['error'][0]}")  # type: ignore[attr-defined]
                self.send_response(400)
                body = b"Authorization was declined or failed. You can close this tab."
            else:
                self.server.result = (query.get("code", [None])[0], None)  # type: ignore[attr-defined]
                self.send_response(200)
                body = b"Polar authorization completed. You can close this tab."
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    try:
        server = HTTPServer((parsed.hostname or "localhost", parsed.port), CallbackHandler)
    except OSError as error:
        raise RuntimeError(f"Cannot start the callback server on port {parsed.port}: {error}") from error
    server.timeout = 300
    server.result = (None, "Timed out waiting for Polar authorization.")  # type: ignore[attr-defined]
    print("Opening Polar in your browser. Sign in and approve access once.")
    print("If it does not open, use this URL:\n" + url)
    webbrowser.open(url)
    server.handle_request()
    server.server_close()
    code, error = server.result  # type: ignore[attr-defined]
    if error or not code:
        raise RuntimeError(error or "Polar did not provide an authorization code.")
    return code


def request_token(credentials: dict[str, str], data: dict[str, str]) -> dict[str, Any]:
    response = requests.post(TOKEN_URL, auth=(credentials["client_id"], credentials["client_secret"]), data=data, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise RuntimeError(f"Polar token request returned HTTP {response.status_code}: {response.text[:500]}") from error
    token = response.json()
    if not isinstance(token, dict) or not token.get("access_token"):
        raise RuntimeError("Polar token response did not contain an access token.")
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 0))
    return token


def authorize(credentials_file: Path) -> str:
    credentials = read_yaml(credentials_file) or prompt_credentials(credentials_file)
    code = authorization_code(credentials)  # type: ignore[arg-type]
    token = request_token(credentials, {"grant_type": "authorization_code", "code": code, "redirect_uri": credentials["redirect_uri"]})  # type: ignore[index]
    write_private_yaml(token_file(credentials_file), token)
    return str(token["access_token"])


def get_access_token(credentials_file: Path | None = None, *, interactive: bool = True) -> str:
    """Return a valid token, refreshing it silently whenever possible."""
    credentials_file = credentials_file or default_credentials_file()
    token = read_yaml(token_file(credentials_file))
    if token and token.get("access_token") and int(token.get("expires_at", 0)) > time.time() + 60:
        return str(token["access_token"])
    credentials = read_yaml(credentials_file)
    if token and token.get("refresh_token") and credentials:
        try:
            refreshed = request_token(credentials, {"grant_type": "refresh_token", "refresh_token": str(token["refresh_token"])})
            refreshed.setdefault("refresh_token", token["refresh_token"])
            write_private_yaml(token_file(credentials_file), refreshed)
            return str(refreshed["access_token"])
        except RuntimeError:
            # A revoked refresh token needs an interactive authorization; retain the old file for diagnosis.
            if not interactive:
                raise
    if not interactive:
        raise RuntimeError("No usable Polar access token is available.")
    return authorize(credentials_file)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "reauthorize"), nargs="?", default="setup")
    parser.add_argument("--credentials-file", type=Path, default=default_credentials_file())
    args = parser.parse_args()
    if args.command == "reauthorize":
        token_file(args.credentials_file).unlink(missing_ok=True)
    get_access_token(args.credentials_file)
    print("Polar is authorized. Future exports will refresh the token automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
