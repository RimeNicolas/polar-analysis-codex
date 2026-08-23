"""Local allow-list proxy for public Polar OAuth browser callbacks.

Run this on a separate localhost port and point a public HTTPS reverse tunnel
only at this process.  It deliberately forwards just the two OAuth browser
routes; the private MCP endpoint is never available through this proxy.
"""

from __future__ import annotations

import argparse
import os
from urllib.parse import urlsplit

import requests
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route


def upstream_url(request: Request) -> str:
    base = os.environ.get("POLAR_OAUTH_UPSTREAM", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}{request.url.path}" + (f"?{request.url.query}" if request.url.query else "")


async def forward(request: Request) -> Response:
    try:
        response = requests.get(upstream_url(request), allow_redirects=False, timeout=30)
    except requests.RequestException:
        return Response("Polar OAuth service is temporarily unavailable.", status_code=503, media_type="text/plain")
    headers: dict[str, str] = {}
    for name in ("content-type", "location"):
        if value := response.headers.get(name):
            headers[name] = value
    return Response(response.content, status_code=response.status_code, headers=headers)


app = Starlette(routes=[Route("/polar/login", forward, methods=["GET"]), Route("/polar/callback", forward, methods=["GET"])])


def main() -> None:
    parser = argparse.ArgumentParser(description="OAuth-only proxy for the local Polar MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8081, type=int)
    args = parser.parse_args()
    parsed = urlsplit(os.environ.get("POLAR_OAUTH_UPSTREAM", "http://127.0.0.1:8000"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("POLAR_OAUTH_UPSTREAM must be a local HTTP URL.")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
