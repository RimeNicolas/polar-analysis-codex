#!/usr/bin/env python3
"""Run the public, Auth0-protected Polar MCP server for Render.

This entry point always enables Auth0 verification. It uses PostgreSQL when
DATABASE_URL is set, otherwise an in-memory credential store. It is the only
MCP entry point used by the Docker image.
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", default=int(os.environ.get("PORT", "8000")), type=int)
    args = parser.parse_args()

    # Set this before importing the shared app, which constructs Auth0's
    # protected-resource metadata and token verifier during initialization.
    os.environ["MCP_AUTH_MODE"] = "auth0"
    from .polar_mcp_server import mcp

    mcp.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
