#!/usr/bin/env python3
"""Export Polar activities from AccessLink v4 into an Excel-friendly CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import requests

from .polar_oauth import get_access_token


API_URL = "https://www.polaraccesslink.com/v4/data/training-sessions/list"
SPORTS_URL = "https://www.polaraccesslink.com/v4/data/sports/list"
# Polar uses this global sport ID for Cycling. The v4 catalogue endpoint may
# return an empty list for some accounts, so keep a reliable local fallback.
FALLBACK_SPORT_NAMES = {"2": "Cycling"}
DEFAULT_FEATURES = ("statistics", "zones", "laps", "pause-times", "comments")


def parse_date(value: str) -> date:
    """Parse an ISO date and give argparse a useful error on invalid input."""
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD") from error


def date_ranges(start: date, end: date, *, max_days: int) -> Iterable[tuple[date, date]]:
    """Yield inclusive date ranges no longer than max_days."""
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def load_token(token_file: Path | None, credentials_file: Path | None) -> str:
    token = os.environ.get("POLAR_ACCESS_TOKEN", "").strip()
    if not token and token_file:
        try:
            token = token_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError as error:
            raise RuntimeError(f"Token file not found: {token_file}") from error
    if not token:
        return get_access_token(credentials_file)
    return token


def get_sessions(
    token: str, start: date, end: date, features: tuple[str, ...], timeout: int
) -> list[dict[str, Any]]:
    """Get all sessions. Polar's `to` date is exclusive, hence +1 day."""
    params: list[tuple[str, str]] = [
        # The endpoint labels these as dates, but currently parses ISO datetimes.
        ("from", f"{start.isoformat()}T00:00:00"),
        ("to", f"{(end + timedelta(days=1)).isoformat()}T00:00:00"),
    ]
    params.extend(("features", feature) for feature in features)
    response = requests.get(
        API_URL,
        params=params,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        detail = response.text[:500].strip()
        raise RuntimeError(f"Polar API returned HTTP {response.status_code}: {detail}") from error

    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Polar API returned an unexpected non-object JSON response.")
    sessions = body.get("trainingSessions", [])
    if not isinstance(sessions, list):
        raise RuntimeError("Polar API response has an invalid trainingSessions field.")
    return [session for session in sessions if isinstance(session, dict)]


def get_sport_names(token: str, timeout: int) -> dict[str, str]:
    """Resolve the sport IDs returned by sessions to their Polar sport names."""
    response = requests.get(
        SPORTS_URL,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise RuntimeError(
            "Could not load Polar sport names. Run 'python -m polar_mcp.polar_oauth reauthorize' "
            "to grant the new sports:read permission."
        ) from error
    body = response.json()
    sports = body.get("sports", []) if isinstance(body, dict) else []
    result: dict[str, str] = dict(FALLBACK_SPORT_NAMES)
    for sport in sports:
        if not isinstance(sport, dict):
            continue
        identifier = sport.get("id")
        sport_id = identifier.get("id") if isinstance(identifier, dict) else None
        name = sport.get("name")
        if sport_id is not None and isinstance(name, str):
            result[str(sport_id)] = name
    return result


def sport_id(session: dict[str, Any]) -> str | None:
    sport = session.get("sport")
    if isinstance(sport, dict) and sport.get("id") is not None:
        return str(sport["id"])
    return None


def flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested objects; lists stay compact JSON in one CSV cell."""
    if isinstance(value, dict):
        flattened: dict[str, str] = {}
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(flatten(child, name))
        return flattened
    if isinstance(value, list):
        return {prefix: json.dumps(value, ensure_ascii=False, separators=(",", ":"))}
    if value is None:
        return {prefix: ""}
    return {prefix: str(value)}


def duration_text(milliseconds: Any) -> str:
    if not isinstance(milliseconds, (int, float)):
        return ""
    seconds = round(milliseconds / 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def statistic_average(value: Any, statistic: str) -> str:
    """Find the average for a Polar statistics type anywhere in a session."""
    if isinstance(value, dict):
        kind = value.get("type")
        average = value.get("avg")
        if isinstance(kind, str) and statistic in kind.upper() and average is not None:
            return str(average)
        for child in value.values():
            result = statistic_average(child, statistic)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = statistic_average(child, statistic)
            if result:
                return result
    return ""


def export_row(session: dict[str, Any], sport_names: dict[str, str]) -> dict[str, str]:
    row = flatten(session)
    start_time = str(session.get("startTime", ""))
    identifier = sport_id(session)
    row.update(
        {
            "date": start_time.split("T", 1)[0],
            "sport_type": sport_names.get(identifier or "", f"Polar sport ID {identifier}" if identifier else ""),
            "duration": duration_text(session.get("durationMillis")),
            "distance": f"{float(session['distanceMeters']) / 1000:.3f}" if isinstance(session.get("distanceMeters"), (int, float)) else "",
            "avg_speed": statistic_average(session, "SPEED"),
            "calories": str(session.get("calories", "")),
            "avg_hr": str(session.get("hrAvg", "")),
            "avg_power": statistic_average(session, "POWER"),
        }
    )
    return row


def write_csv(sessions: list[dict[str, Any]], output: Path, sport_names: dict[str, str]) -> None:
    rows = [export_row(session, sport_names) for session in sessions]
    leading_columns = ["date", "sport_type", "duration", "distance", "avg_speed", "calories", "avg_hr", "avg_power"]
    columns = leading_columns + sorted({column for row in rows for column in row} - set(leading_columns))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=parse_date, required=True, help="first date (YYYY-MM-DD, inclusive)")
    parser.add_argument("--to", dest="end", type=parse_date, required=True, help="last date (YYYY-MM-DD, inclusive)")
    parser.add_argument("--output", type=Path, default=Path("exports/polar_activities.csv"), help="CSV destination")
    parser.add_argument("--token-file", type=Path, help="file containing only the Polar access token")
    parser.add_argument("--credentials-file", type=Path, help="Polar OAuth credential file (first run will create it)")
    parser.add_argument("--features", default=",".join(DEFAULT_FEATURES), help="comma-separated optional Polar features; use '' for summary only")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.end < args.start:
        raise SystemExit("--to must be on or after --from")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")

    features = tuple(feature.strip() for feature in args.features.split(",") if feature.strip())
    # The v4 API permits a maximum one-day range when optional features are used.
    max_days = 1 if features else 90
    try:
        token = load_token(args.token_file, args.credentials_file)
        sessions: list[dict[str, Any]] = []
        sport_names = get_sport_names(token, args.timeout)
        for start, end in date_ranges(args.start, args.end, max_days=max_days):
            sessions.extend(get_sessions(token, start, end, features, args.timeout))
    except (RuntimeError, requests.RequestException, ValueError) as error:
        print(f"Export failed: {error}", file=sys.stderr)
        return 1

    write_csv(sessions, args.output, sport_names)
    print(f"Wrote {len(sessions)} session(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
