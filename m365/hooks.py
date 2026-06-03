#!/usr/bin/env python3
"""
Microsoft Graph change-notification hooks for Outlook / Teams / SharePoint.

Two jobs in one service:
  1. Receiver  — handles Graph's validation handshake (echo validationToken),
     verifies clientState, and persists notifications into the vault.
  2. Manager   — on startup and on a timer, creates/renews the configured Graph
     subscriptions using app-only (client-credentials) auth.

WHY THIS NEEDS PUBLIC HTTPS: Graph delivers notifications from Microsoft's cloud,
so GRAPH_NOTIFICATION_URL must be a public HTTPS URL. Expose ONLY this path with
`tailscale funnel` (see notes). Security rests on the validation handshake +
the clientState shared secret, not on network obscurity.

Resource lifetime note: max subscription lifetime varies by resource (mail/
calendar measured in days; Teams chat/channel messages much shorter, and Teams
change notifications also require resource-specific consent + a Graph change-
notification billing setup). We renew every EXPIRATION_MINUTES/2 to stay safe.
"""
import os
import json
import asyncio
import hmac
import datetime as dt
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response

TENANT = os.environ["MS365_TENANT_ID"]
CLIENT_ID = os.environ["MS365_CLIENT_ID"]
CLIENT_SECRET = os.environ["MS365_CLIENT_SECRET"]
NOTIFY_URL = os.environ["GRAPH_NOTIFICATION_URL"]
CLIENT_STATE = os.environ["GRAPH_CLIENT_STATE"]
SUBS = json.loads(os.environ.get("GRAPH_SUBSCRIPTIONS", "[]"))
EXP_MIN = int(os.environ.get("EXPIRATION_MINUTES", "60"))
EVENTS_DIR = Path(os.environ.get("VAULT_EVENTS_DIR", "/data/vault/raw/m365/events"))
NTFY_URL = os.environ.get("NTFY_URL", "")

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
GRAPH = "https://graph.microsoft.com/v1.0"

EVENTS_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="m365-hooks")


async def _token() -> str:
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(TOKEN_URL, data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        })
        r.raise_for_status()
        return r.json()["access_token"]


async def _ensure_subscriptions() -> None:
    """Create/refresh each configured subscription. Idempotent enough for a loop."""
    if not SUBS:
        return
    token = await _token()
    exp = (dt.datetime.utcnow() + dt.timedelta(minutes=EXP_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as c:
        existing = await c.get(f"{GRAPH}/subscriptions", headers=headers)
        by_resource = {}
        if existing.status_code == 200:
            for s in existing.json().get("value", []):
                by_resource[s.get("resource")] = s
        for sub in SUBS:
            body = {
                "changeType": sub.get("changeType", "created,updated"),
                "notificationUrl": NOTIFY_URL,
                "resource": sub["resource"],
                "expirationDateTime": exp,
                "clientState": CLIENT_STATE,
            }
            if sub["resource"] in by_resource:   # renew
                sid = by_resource[sub["resource"]]["id"]
                await c.patch(f"{GRAPH}/subscriptions/{sid}", headers=headers,
                              json={"expirationDateTime": exp})
            else:                                 # create (triggers validation POST)
                await c.post(f"{GRAPH}/subscriptions", headers=headers, json=body)


async def _renewal_loop() -> None:
    while True:
        try:
            await _ensure_subscriptions()
        except Exception as e:           # never let the loop die
            print(f"[m365-hooks] subscription refresh error: {e}")
        await asyncio.sleep(max(EXP_MIN // 2, 5) * 60)


@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(_renewal_loop())


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/graph/notifications")
async def notifications(request: Request) -> Response:
    # 1) Validation handshake: Graph sends ?validationToken=... -> echo as text/plain.
    token = request.query_params.get("validationToken")
    if token is not None:
        return Response(content=token, media_type="text/plain", status_code=200)

    # 2) Real notification batch.
    body = await request.json()
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S_%f")
    accepted = []
    for note in body.get("value", []):
        if not hmac.compare_digest(note.get("clientState", ""), CLIENT_STATE):
            continue                      # drop anything not carrying our secret
        accepted.append(note)
    if accepted:
        (EVENTS_DIR / f"{ts}.json").write_text(json.dumps(accepted, indent=2))
        if NTFY_URL:
            try:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    await c.post(NTFY_URL, content=f"M365 change: {len(accepted)} notification(s)")
            except Exception:
                pass
    # Graph expects a prompt 2xx or it will retry/disable the subscription.
    return Response(status_code=202)
