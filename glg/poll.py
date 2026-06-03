#!/usr/bin/env python3
"""
Greenlight Guru "hooks" via polling.

GLG's documented surface is a REST API with API keys; native outbound webhooks
aren't part of it, so the reliable, fully-PRIVATE way to get near-real-time
events is to poll the allowlisted resources for records changed since the last
check, write them into the vault, and ping ntfy so Hermes can react. Because we
pull, this needs NO public ingress (unlike the M365 Graph hooks).

Set GLG_MODIFIED_PARAM to whatever your GLG API uses to filter by change time
(e.g. updatedAfter / modifiedSince) — check your GLG API reference.
"""
import os
import json
import time
import datetime as dt
from pathlib import Path

import httpx

BASE = os.environ["GLG_API_BASE_URL"].rstrip("/")
API_KEY = os.environ["GLG_API_KEY"]
AUTH_HEADER = os.environ.get("GLG_AUTH_HEADER", "Authorization")
AUTH_PREFIX = os.environ.get("GLG_AUTH_PREFIX", "Bearer ")
ALLOWED = [p.strip().strip("/") for p in os.environ.get("GLG_ALLOWED_PATHS", "").split(",") if p.strip()]
MODIFIED_PARAM = os.environ.get("GLG_MODIFIED_PARAM", "updatedAfter")
POLL_SECONDS = int(os.environ.get("GLG_POLL_SECONDS", "300"))
EVENTS_DIR = Path(os.environ.get("VAULT_EVENTS_DIR", "/data/vault/raw/glg/events"))
NTFY_URL = os.environ.get("NTFY_URL", "")

EVENTS_DIR.mkdir(parents=True, exist_ok=True)
client = httpx.Client(timeout=60.0, headers={AUTH_HEADER: f"{AUTH_PREFIX}{API_KEY}"})


def _utcnow_iso() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def poll_once(since: str) -> int:
    """Poll every allowlisted resource for items changed since `since`. Returns count."""
    total = 0
    for resource in ALLOWED:
        try:
            r = client.get(f"{BASE}/{resource}", params={MODIFIED_PARAM: since})
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[glg-poll] {resource}: error {e}")
            continue
        # GLG list responses are typically {"data": [...]} or a bare list; handle both.
        items = data.get("data", data) if isinstance(data, dict) else data
        if not items:
            continue
        ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S_%f")
        (EVENTS_DIR / f"{resource}_{ts}.json").write_text(json.dumps(items, indent=2))
        total += len(items) if isinstance(items, list) else 1
    return total


def main() -> None:
    since = _utcnow_iso()
    print(f"[glg-poll] starting; interval={POLL_SECONDS}s; resources={ALLOWED}")
    while True:
        window_start = since
        since = _utcnow_iso()              # next window starts now (before the call)
        try:
            n = poll_once(window_start)
            if n:
                print(f"[glg-poll] {n} changed record(s) since {window_start}")
                if NTFY_URL:
                    try:
                        client.post(NTFY_URL, content=f"Greenlight Guru: {n} changed record(s)")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[glg-poll] cycle error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
