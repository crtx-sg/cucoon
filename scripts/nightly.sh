#!/usr/bin/env bash
# =============================================================================
#  nightly.sh — off-hours batch window orchestrator.
#
#  Enforces your performance boundary: all heavy ingestion, OCR, embedding and
#  wiki synthesis happen here, OUTSIDE work hours, so the single-channel RAM
#  isn't contended while you're using the workspace.
#
#  Sequence:
#    1. ~01:00  ingest each source (ephemeral Meltano runs, one at a time so
#               peak RAM stays tiny).
#    2. ~02:00  compile the wiki (Librarian: opencode + local Ollama).
#
#  Cron (run the two phases separately so a slow ingest can't delay compile):
#    0 1 * * *  /opt/ai-stack/scripts/nightly.sh ingest  >> /var/log/ai-nightly.log 2>&1
#    0 2 * * *  /opt/ai-stack/scripts/nightly.sh compile  >> /var/log/ai-nightly.log 2>&1
# =============================================================================
set -Eeuo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -f ${STACK_DIR}/docker-compose.yml -f ${STACK_DIR}/docker-compose.enterprise.yml"
PHASE="${1:-all}"

log() { printf '%s [nightly] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }

run_ingest() {
  # One job at a time -> low peak memory on the single channel.
  for job in ingest-github ingest-jira ingest-slack ingest-confluence ingest-drive; do
    log "meltano: ${job}"
    ${COMPOSE} run --rm meltano meltano run "${job}" \
      || log "WARNING: ${job} failed (continuing with the rest)"
  done
}

run_compile() {
  log "librarian: compiling wiki"
  ${COMPOSE} run --rm wiki-compiler \
    || log "WARNING: wiki compile returned non-zero"
}

case "${PHASE}" in
  ingest)  run_ingest ;;
  compile) run_compile ;;
  all)     run_ingest; run_compile ;;
  *) echo "usage: $0 {ingest|compile|all}" >&2; exit 2 ;;
esac

log "phase '${PHASE}' done."
