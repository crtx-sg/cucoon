#!/usr/bin/env python3
"""
SAP Business One — read-only MCP server over the Service Layer (OData v4).

Why a custom server: the Service Layer has no MCP of its own, and its auth is a
session-cookie handshake (POST /Login -> B1SESSION + ROUTEID cookies) that the
generic OData->MCP bridges don't handle cleanly. This thin server logs in,
caches the session, re-logs in on 401, and exposes ONLY read tools. It never
issues anything but GET, so it is structurally incapable of mutating SAP data.
Pair it with a dedicated READ-ONLY SAP B1 user for defense in depth.

Transport: streamable HTTP at /mcp (the current MCP standard; SSE is deprecated).
Reachable on the internal network at http://sap-b1-mcp:8000/mcp
"""
import os
import threading
import httpx
from mcp.server.fastmcp import FastMCP

SL_URL = os.environ["SAP_B1_SERVICE_LAYER_URL"].rstrip("/")   # https://sap:50000/b1s/v1
COMPANY_DB = os.environ["SAP_B1_COMPANY_DB"]
USER = os.environ["SAP_B1_USER"]
PASSWORD = os.environ["SAP_B1_PASSWORD"]
VERIFY_SSL = os.environ.get("SAP_B1_VERIFY_SSL", "false").lower() == "true"
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8000"))

# Common, useful read targets. Extend as needed; these are all standard SL entities.
ALLOWED_ENTITIES = {
    "BusinessPartners", "Items", "Orders", "Invoices", "Quotations",
    "PurchaseOrders", "DeliveryNotes", "Warehouses", "ItemGroups",
    "ChartOfAccounts", "JournalEntries", "Employees",
}

mcp = FastMCP("sap-b1-readonly")
_client = httpx.Client(verify=VERIFY_SSL, timeout=60.0)
_lock = threading.Lock()
_logged_in = False


def _login() -> None:
    global _logged_in
    resp = _client.post(
        f"{SL_URL}/Login",
        json={"CompanyDB": COMPANY_DB, "UserName": USER, "Password": PASSWORD},
    )
    resp.raise_for_status()           # cookies (B1SESSION/ROUTEID) now on _client
    _logged_in = True


def _get(path: str, params: dict | None = None) -> dict:
    """GET against the Service Layer, logging in (and re-logging in on 401) as needed."""
    with _lock:
        if not _logged_in:
            _login()
        r = _client.get(f"{SL_URL}/{path}", params=params)
        if r.status_code == 401:      # session expired -> refresh once
            _login()
            r = _client.get(f"{SL_URL}/{path}", params=params)
        r.raise_for_status()
        return r.json()


@mcp.tool()
def list_entities() -> list[str]:
    """List the SAP B1 Service Layer entity sets this read-only server exposes."""
    return sorted(ALLOWED_ENTITIES)


@mcp.tool()
def query_entity(
    entity: str,
    select: str | None = None,
    filter: str | None = None,
    orderby: str | None = None,
    top: int = 20,
) -> dict:
    """
    Read rows from a SAP B1 entity set using OData query options.

    entity : one of list_entities() (e.g. "BusinessPartners", "Orders")
    select : comma-separated fields, e.g. "CardCode,CardName,Balance"
    filter : OData $filter, e.g. "Balance gt 0 and Frozen eq 'tNO'"
    orderby: e.g. "CardName asc"
    top    : max rows (capped at 100 to protect the context window)
    """
    if entity not in ALLOWED_ENTITIES:
        return {"error": f"entity '{entity}' not allowed", "allowed": sorted(ALLOWED_ENTITIES)}
    params: dict[str, str] = {"$top": str(min(max(top, 1), 100))}
    if select:
        params["$select"] = select
    if filter:
        params["$filter"] = filter
    if orderby:
        params["$orderby"] = orderby
    return _get(entity, params)


@mcp.tool()
def get_entity_by_key(entity: str, key: str) -> dict:
    """
    Fetch a single record by key, e.g. get_entity_by_key("BusinessPartners", "'C20000'")
    or get_entity_by_key("Orders", "123"). String keys must include single quotes.
    """
    if entity not in ALLOWED_ENTITIES:
        return {"error": f"entity '{entity}' not allowed", "allowed": sorted(ALLOWED_ENTITIES)}
    return _get(f"{entity}({key})")


if __name__ == "__main__":
    mcp.settings.host = HOST
    mcp.settings.port = PORT
    mcp.run(transport="streamable-http")
