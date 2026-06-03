#!/usr/bin/env python3
"""
SAP B1 Service Layer -> JSONL ingestion for the vault.

Pull-side counterpart to the event hooks: pages through configured entity sets
and writes one JSONL file per entity into /data/vault/raw/sap/, which the
nightly Librarian then folds into the wiki. Handles the SL login handshake and
follows @odata.nextLink pagination.

Run from the nightly cron (add to scripts/nightly.sh `run_ingest`):
    docker compose -f docker-compose.yml -f docker-compose.erp.yml \
      run --rm --entrypoint python sap-b1-mcp extract.py
"""
import os
import json
import httpx
from pathlib import Path

SL_URL = os.environ["SAP_B1_SERVICE_LAYER_URL"].rstrip("/")
COMPANY_DB = os.environ["SAP_B1_COMPANY_DB"]
USER = os.environ["SAP_B1_USER"]
PASSWORD = os.environ["SAP_B1_PASSWORD"]
VERIFY_SSL = os.environ.get("SAP_B1_VERIFY_SSL", "false").lower() == "true"
OUT_DIR = Path(os.environ.get("SAP_RAW_DIR", "/data/vault/raw/sap"))

# Entities to snapshot nightly. Keep this lean to respect the off-hours window.
ENTITIES = os.environ.get(
    "SAP_B1_ENTITIES", "BusinessPartners,Items,Orders,Invoices"
).split(",")

PAGE_SIZE = int(os.environ.get("SAP_B1_PAGE_SIZE", "200"))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(verify=VERIFY_SSL, timeout=120.0) as client:
        client.post(
            f"{SL_URL}/Login",
            json={"CompanyDB": COMPANY_DB, "UserName": USER, "Password": PASSWORD},
        ).raise_for_status()

        for entity in (e.strip() for e in ENTITIES if e.strip()):
            out = OUT_DIR / f"{entity}.jsonl"
            count = 0
            # Server-driven paging: SL returns @odata.nextLink until exhausted.
            url = f"{SL_URL}/{entity}"
            params = {"$top": str(PAGE_SIZE)}
            headers = {"Prefer": f"odata.maxpagesize={PAGE_SIZE}"}
            with out.open("w") as fh:
                while url:
                    r = client.get(url, params=params, headers=headers)
                    if r.status_code == 401:  # refresh session and retry once
                        client.post(
                            f"{SL_URL}/Login",
                            json={"CompanyDB": COMPANY_DB, "UserName": USER, "Password": PASSWORD},
                        ).raise_for_status()
                        r = client.get(url, params=params, headers=headers)
                    r.raise_for_status()
                    body = r.json()
                    for row in body.get("value", []):
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                        count += 1
                    # Follow nextLink (absolute or relative); params only apply to first call.
                    nxt = body.get("@odata.nextLink")
                    url = nxt if (nxt and nxt.startswith("http")) else (f"{SL_URL}/{nxt}" if nxt else None)
                    params = None
            print(f"[sap-extract] {entity}: {count} rows -> {out}")


if __name__ == "__main__":
    main()
