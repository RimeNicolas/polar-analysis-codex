#!/usr/bin/env python3
"""Run the personal, localhost-only Polar MCP server.

This entry point always uses development mode and the local SQLite credential
store. It is intended for OpenAI Secure MCP Tunnel or another local MCP host.
It must not be used as a public web service.
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="Must stay on localhost for the tunnel setup.")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()

    if args.transport == "streamable-http" and args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Local MCP must bind to 127.0.0.1 or localhost. Use hosted_mcp_server.py for Render.")

    # Set this before importing the shared app, which chooses its auth and
    # credential-store implementation during initialization.
    os.environ["MCP_AUTH_MODE"] = "development"
    from polar_mcp_server import mcp

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
