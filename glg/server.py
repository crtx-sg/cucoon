#!/usr/bin/env python3
"""
Greenlight Guru (medical-device eQMS) — read-only MCP bridge.

GLG exposes a RESTful API with API-key auth. There's no public MCP for it, so
this is a thin GET-only bridge: it can ONLY issue GET requests against an
allowlist of path prefixes, so it is structurally incapable of mutating QMS
records (important for an audited, regulated system).

The exact base URL, auth header, and resource paths come from YOUR Greenlight
Guru API reference (behind their developer portal). Everything here is
parameterized via env so you fill in the specifics without code changes:
  GLG_API_BASE_URL, GLG_API_KEY, GLG_AUTH_HEADER, GLG_AUTH_PREFIX, GLG_ALLOWED_PATHS

Transport: streamable HTTP at /mcp -> http://mcp-glg:8000/mcp
"""
import os
import httpx
from mcp.server.fastmcp import FastMCP

BASE = os.environ["GLG_API_BASE_URL"].rstrip("/")
API_KEY = os.environ["GLG_API_KEY"]
AUTH_HEADER = os.environ.get("GLG_AUTH_HEADER", "Authorization")
AUTH_PREFIX = os.environ.get("GLG_AUTH_PREFIX", "Bearer ")
ALLOWED = [p.strip().strip("/") for p in os.environ.get("GLG_ALLOWED_PATHS", "").split(",") if p.strip()]
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8000"))

mcp = FastMCP("greenlight-guru-readonly")
_client = httpx.Client(timeout=60.0, headers={AUTH_HEADER: f"{AUTH_PREFIX}{API_KEY}"})


def _allowed(path: str) -> bool:
    head = path.strip("/").split("/", 1)[0]
    return head in ALLOWED


@mcp.tool()
def list_resources() -> list[str]:
    """List the Greenlight Guru resource paths this read-only bridge may access."""
    return sorted(ALLOWED)


@mcp.tool()
def get(path: str, params: dict | None = None) -> dict:
    """
    Read from a Greenlight Guru REST resource (GET only).

    path   : e.g. "capas", "capas/123", "design-controls?status=open"
             The leading segment must be in list_resources().
    params : optional query parameters (filters, paging) per the GLG API.
    """
    if not _allowed(path):
        return {"error": f"path '{path}' not in allowlist", "allowed": sorted(ALLOWED)}
    r = _client.get(f"{BASE}/{path.lstrip('/')}", params=params or {})
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


if __name__ == "__main__":
    mcp.settings.host = HOST
    mcp.settings.port = PORT
    mcp.run(transport="streamable-http")
