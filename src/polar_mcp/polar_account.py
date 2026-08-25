#!/usr/bin/env python3
"""Download the authorized Polar user's account data as private JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

from .polar_oauth import get_access_token

ACCOUNT_URL = "https://www.polaraccesslink.com/v4/data/user/account-data"


def get_account_data(token: str, timeout: int = 30) -> dict[str, Any]:
    """Return account data without ever logging the bearer token."""
    response = requests.get(
        ACCOUNT_URL,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        if response.status_code in {401, 403}:
            detail = (
                "Authorization is missing or does not include profile:read. "
                "Run 'python -m polar_mcp.polar_oauth reauthorize' and approve access."
            )
        else:
            detail = f"Polar API returned HTTP {response.status_code}."
        raise RuntimeError(detail) from error
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Polar API returned an unexpected account-data response.")
    # Polar's documentation shows an {"accountData": {...}} envelope, but the
    # live v4 endpoint can return the account object directly.
    if isinstance(body.get("accountData"), dict):
        return body
    if any(key in body for key in ("basicInfo", "physicalInformation", "localizationSettings")):
        return {"accountData": body}
    raise RuntimeError("Polar API returned an unexpected account-data response.")


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    """Write personal account data with owner-only permissions where supported."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("exports/polar_account.json"), help="private JSON destination")
    parser.add_argument("--credentials-file", type=Path, help="alternate Polar OAuth credential file")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    try:
        token = get_access_token(args.credentials_file)
        account = get_account_data(token, args.timeout)
        write_private_json(args.output, account)
    except (RuntimeError, requests.RequestException, ValueError) as error:
        print(f"Account export failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote private account data to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
