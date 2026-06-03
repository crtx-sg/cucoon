# =============================================================================
#  SAP B1 bridge image — one image, three entrypoints:
#    * server.py   -> read-only Service Layer MCP server (command in compose)
#    * webhook.py  -> B1if event receiver (command in compose)
#    * extract.py  -> Service Layer -> JSONL ingestion (run by nightly cron)
# =============================================================================
FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir \
      "mcp[cli]>=1.2" \
      httpx \
      fastapi \
      "uvicorn[standard]"

COPY server.py webhook.py extract.py /app/

# Default to the MCP server; compose overrides for the webhook service.
CMD ["python", "server.py"]
