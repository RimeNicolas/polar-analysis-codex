"""Application layer shared by the CSV exporter and the MCP server."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .polar_export import DEFAULT_FEATURES, date_ranges, export_row, get_sessions, get_sport_names, load_token


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


def exercise_calorie_summary(activity_result: dict[str, Any]) -> dict[str, Any]:
    """Aggregate normalized Polar session calories by day and sport.

    Polar session calories represent exercise calories only. Sessions without a
    usable calorie value remain visible in the count but are excluded from the
    calorie totals, so a missing value is never silently treated as zero.
    """
    activities = activity_result.get("activities", [])
    if not isinstance(activities, list):
        raise ValueError("Polar activities response is invalid.")

    daily: dict[str, dict[str, int]] = {}
    sports: dict[str, dict[str, int]] = {}
    daily_sports: dict[tuple[str, str], dict[str, int]] = {}
    sessions_with_calories = 0
    sessions_without_calories = 0

    for activity in activities:
        if not isinstance(activity, dict):
            continue
        activity_date = str(activity.get("date", "Unknown date"))
        sport_type = str(activity.get("sport_type", "Unknown sport"))
        try:
            calories = int(float(str(activity.get("calories", ""))))
        except (TypeError, ValueError):
            sessions_without_calories += 1
            continue

        sessions_with_calories += 1
        daily_entry = daily.setdefault(activity_date, {"activity_count": 0, "calories": 0})
        daily_entry["activity_count"] += 1
        daily_entry["calories"] += calories

        sport_entry = sports.setdefault(sport_type, {"activity_count": 0, "calories": 0})
        sport_entry["activity_count"] += 1
        sport_entry["calories"] += calories

        daily_sport_entry = daily_sports.setdefault((activity_date, sport_type), {"activity_count": 0, "calories": 0})
        daily_sport_entry["activity_count"] += 1
        daily_sport_entry["calories"] += calories

    return {
        "from_date": activity_result.get("from_date"),
        "to_date": activity_result.get("to_date"),
        "total_exercise_calories": sum(entry["calories"] for entry in daily.values()),
        "activity_count": activity_result.get("activity_count", len(activities)),
        "sessions_with_calories": sessions_with_calories,
        "sessions_without_calories": sessions_without_calories,
        "daily_totals": [
            {"date": activity_date, **entry}
            for activity_date, entry in sorted(daily.items())
        ],
        "sport_totals": [
            {"sport_type": sport_type, **entry}
            for sport_type, entry in sorted(sports.items())
        ],
        "daily_sport_totals": [
            {"date": activity_date, "sport_type": sport_type, **entry}
            for (activity_date, sport_type), entry in sorted(daily_sports.items())
        ],
        "note": "Exercise calories from Polar-recorded training sessions only; this is not complete daily energy expenditure.",
    }
