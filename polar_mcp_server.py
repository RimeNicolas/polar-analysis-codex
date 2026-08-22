#!/usr/bin/env python3
"""Local MCP server exposing Polar activities through a single read-only tool."""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server import MCPServer

from polar_service import get_activities as retrieve_activities


mcp = MCPServer("Polar Activities")


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
    return retrieve_activities(from_date, to_date, features)


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
