#!/usr/bin/env bash
# =============================================================================
#  compile.sh — the nightly "Librarian" run (cron @ 02:00).
#
#  Flow:
#    1. Ensure the llmwiki index is initialized over the staging vault.
#    2. Launch opencode as an MCP client wired to llmwiki's tools and pointed
#       at the LOCAL Ollama model, with an instruction to compile the wiki:
#       dedupe sources, build [[backlinks]], flag contradictions, write to
#       /data/vault/wiki, segregated by project subdirectory.
#
#  Quality is model-bound: llama3.1:8b will produce a usable but modest wiki.
#  For a sharper nightly synthesis, point OPENAI_BASE_URL/KEY at a stronger
#  endpoint for this job only — everything else in the stack stays local.
# =============================================================================
set -Eeuo pipefail

RAW="${VAULT_RAW:-/data/vault/raw}"
OUT="${VAULT_OUT:-/data/vault/wiki}"
MODEL="${LIBRARIAN_MODEL:-llama3.1:8b-instruct-q8_0}"

mkdir -p "${OUT}"

cd /opt/llmwiki

# 1) Initialize / refresh the index over the whole vault (idempotent).
./llmwiki init /data/vault || true

# 2) Per-project compilation to PREVENT CROSS-DEPARTMENT CONTEXT BLEED.
#    Each top-level folder under raw/ becomes its own wiki namespace, so the
#    model never mixes engineering + ops sources inside one inference window.
shopt -s nullglob
for project_dir in "${RAW}"/*/; do
  project="$(basename "${project_dir}")"
  echo "[librarian] compiling project: ${project}"

  read -r -d '' PROMPT <<EOF || true
You are the Librarian. Read ONLY the sources under ${project_dir}.
Using the llmwiki MCP tools (guide, search, read, create, edit, append):
  1. Read the guide first.
  2. Ingest every source in this folder.
  3. Synthesize duplicates into single canonical pages.
  4. Create bi-directional [[backlinks]] between related pages.
  5. Where two sources disagree, create a page tagged #contradiction that
     states both claims with citations to the source files.
Write all output pages under ${OUT}/${project}/ ONLY. Do not read or write
any other project's folder. Keep pages markdown, Obsidian-compatible.
EOF

  # opencode headless run. Flag names evolve — verify with `opencode --help`.
  # The MCP server (llmwiki) is launched in-process over stdio by opencode.
  opencode run \
    --model "ollama/${MODEL}" \
    --mcp "llmwiki=stdio:./llmwiki mcp /data/vault" \
    --cwd "${OUT}/${project}" \
    "${PROMPT}" \
    || echo "[librarian] WARNING: compile for ${project} returned non-zero"
done

echo "[librarian] nightly compilation complete."
