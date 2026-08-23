"""Application layer shared by the CSV exporter and the MCP server."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from polar_export import DEFAULT_FEATURES, date_ranges, export_row, get_sessions, get_sport_names, load_token


def parse_iso_date(value: str, parameter: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{parameter} must use YYYY-MM-DD") from error


def get_activities(
    from_date: str,
    to_date: str,
    features: list[str] | None = None,
    *,
    token_file: Path | None = None,
    credentials_file: Path | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Retrieve normalized Polar activities for an inclusive date range."""
    start = parse_iso_date(from_date, "from_date")
    end = parse_iso_date(to_date, "to_date")
    if end < start:
        raise ValueError("to_date must be on or after from_date")
    token = load_token(token_file, credentials_file)
    return get_activities_for_token(from_date, to_date, token, features, timeout=timeout)


def get_activities_for_token(
    from_date: str,
    to_date: str,
    token: str,
    features: list[str] | None = None,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    """Retrieve normalized activities using a caller-owned valid access token."""
    start = parse_iso_date(from_date, "from_date")
    end = parse_iso_date(to_date, "to_date")
    if end < start:
        raise ValueError("to_date must be on or after from_date")
    selected_features = tuple(features) if features is not None else DEFAULT_FEATURES
    if any(not isinstance(feature, str) or not feature.strip() for feature in selected_features):
        raise ValueError("features must be a list of non-empty strings")

    sport_names = get_sport_names(token, timeout)
    max_days = 1 if selected_features else 90
    sessions: list[dict[str, Any]] = []
    for range_start, range_end in date_ranges(start, end, max_days=max_days):
        sessions.extend(get_sessions(token, range_start, range_end, selected_features, timeout))
    return {
        "from_date": from_date,
        "to_date": to_date,
        "features": list(selected_features),
        "activity_count": len(sessions),
        "activities": [export_row(session, sport_names) for session in sessions],
    }
