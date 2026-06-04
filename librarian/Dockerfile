# =============================================================================
#  Librarian image — bundles llmwiki (the MCP wiki server + viewer) and
#  opencode (the MCP CLIENT that drives the nightly compile against Ollama).
#  Used two ways:
#    * wiki-viewer   -> `llmwiki serve` (always-on read-only UI)
#    * wiki-compiler -> compile.sh (opencode + llmwiki MCP, cron @ 02:00)
# =============================================================================
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates bash nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# --- llmwiki (Karpathy LLM-Wiki implementation; an MCP server) --------------
WORKDIR /opt
RUN git clone https://github.com/lucasastorian/llmwiki.git
WORKDIR /opt/llmwiki
# Install the API deps into the SYSTEM python: `llmwiki serve` launches uvicorn
# via sys.executable (the system interpreter), so a venv here is invisible to it.
RUN cd api && pip install --no-cache-dir -r requirements.txt \
    && cd ../web && npm install
# `./llmwiki init <folder>` builds the SQLite index; `serve` runs the UI.

# --- opencode: open-source agent w/ MCP + local-model support ---------------
#     Verify the current install command against opencode's README if it moves.
RUN npm install -g opencode-ai || npm install -g opencode || true

WORKDIR /opt
