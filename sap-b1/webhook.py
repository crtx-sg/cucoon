#!/usr/bin/env python3
"""
SAP B1 event-hook receiver.

SAP Business One has NO native Service Layer webhooks. Outbound events come from
the B1 Integration Framework (B1if): its Event Sender catches B1 object events
(BP / order / invoice create/update/delete), an Event Filter trims the noise,
and an HttpCall atom POSTs the payload here. B1if classically sends XML; this
endpoint accepts XML or JSON, persists every event into the vault (so the
nightly Librarian can fold ERP activity into the wiki), and optionally pings
ntfy so Hermes can react in near-real-time.

Security: B1if must send a shared secret header (X-B1-Secret). Expose this
service to the SAP host over the tailnet only — never publicly.
"""
import os
import json
import hmac
import datetime as dt
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Header, HTTPException

SECRET = os.environ.get("SAP_B1_WEBHOOK_SECRET", "")
EVENTS_DIR = Path(os.environ.get("VAULT_EVENTS_DIR", "/data/vault/raw/sap/events"))
NTFY_URL = os.environ.get("NTFY_URL", "")

EVENTS_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="sap-b1-webhook")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/b1if/event")
async def b1if_event(request: Request, x_b1_secret: str = Header(default="")) -> dict:
    # Constant-time secret check (reject anything not coming from your B1if).
    if not SECRET or not hmac.compare_digest(x_b1_secret, SECRET):
        raise HTTPException(status_code=401, detail="bad or missing X-B1-Secret")

    raw = await request.body()
    ctype = request.headers.get("content-type", "")
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S_%f")

    # Persist the raw payload exactly as received (XML or JSON), plus a metadata sidecar.
    ext = "json" if "json" in ctype else "xml"
    (EVENTS_DIR / f"{ts}.{ext}").write_bytes(raw)
    (EVENTS_DIR / f"{ts}.meta.json").write_text(json.dumps({
        "received_utc": ts,
        "content_type": ctype,
        "bytes": len(raw),
        "source": request.client.host if request.client else None,
    }, indent=2))

    # Optional: nudge an agent. Fire-and-forget; never fail the webhook on this.
    if NTFY_URL:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                await c.post(NTFY_URL, content=f"SAP B1 event received ({ext}, {len(raw)} bytes)")
        except Exception:
            pass

    return {"status": "stored", "id": ts}
