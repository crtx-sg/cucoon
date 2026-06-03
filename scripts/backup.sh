#!/usr/bin/env bash
# =============================================================================
#  backup.sh — database-safe Restic snapshot of the whole AI stack to AWS S3.
#
#  Strategy (exactly as specified):
#    1. PAUSE the stateful containers so no writes happen mid-snapshot.
#    2. Restic-snapshot the entire ${DATA_ROOT} persistent tree.
#    3. UNPAUSE immediately — pause is freeze-time, not the upload time.
#    4. Prune old snapshots per the retention policy.
#
#  Safety guarantees:
#    * A bash `trap` UNPAUSES the containers on ANY exit path (success, error,
#      Ctrl-C, kill). The DB is never left frozen because Restic failed.
#    * A flock prevents two backups (e.g. overlapping cron runs) colliding.
#    * S3 Object Lock is respected — see the OBJECT LOCK notes near `forget`.
#
#  Cron (daily 03:30, log to file):
#    30 3 * * *  /opt/ai-stack/scripts/backup.sh >> /var/log/ai-stack-backup.log 2>&1
# =============================================================================
set -Eeuo pipefail

# --- Resolve paths & load secrets -------------------------------------------
STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # .../ai-stack
ENV_FILE="${STACK_DIR}/.env"
COMPOSE="docker compose -f ${STACK_DIR}/docker-compose.yml"

# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a   # exports RESTIC_*, AWS_*, DATA_ROOT, ...

: "${DATA_ROOT:?DATA_ROOT must be set in .env}"
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY must be set in .env}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD must be set in .env}"
export RESTIC_REPOSITORY RESTIC_PASSWORD AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION

# Containers whose on-disk state must be quiesced before snapshotting.
PAUSE_TARGETS=(postgres redis chromadb)

# Retention policy. KEEP THIS >= your S3 Object Lock retention (see notes).
KEEP_DAILY=7
KEEP_WEEKLY=4
KEEP_MONTHLY=6

log() { printf '%s [backup] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }

# --- Single-instance lock ----------------------------------------------------
exec 9>"/tmp/ai-stack-backup.lock"
if ! flock -n 9; then
  log "another backup is already running — exiting."
  exit 0
fi

# --- GUARANTEED UNPAUSE on any exit -----------------------------------------
RESUMED=0
resume_containers() {
  if [[ "${RESUMED}" -eq 0 ]]; then
    log "unpausing containers: ${PAUSE_TARGETS[*]}"
    ${COMPOSE} unpause "${PAUSE_TARGETS[@]}" || \
      log "WARNING: unpause failed — check container state manually!"
    RESUMED=1
  fi
}
trap resume_containers EXIT INT TERM

# --- Ensure the repo exists (first run initializes it) -----------------------
if ! restic snapshots >/dev/null 2>&1; then
  log "initializing new Restic repository at ${RESTIC_REPOSITORY}"
  restic init
fi

# --- 1) PAUSE ----------------------------------------------------------------
log "pausing containers: ${PAUSE_TARGETS[*]}"
${COMPOSE} pause "${PAUSE_TARGETS[@]}"

# --- 2) SNAPSHOT -------------------------------------------------------------
log "snapshotting ${DATA_ROOT}"
restic backup "${DATA_ROOT}" \
  --tag ai-stack \
  --host ai-server \
  --exclude "${DATA_ROOT}/odysseus/hf"        # HF model cache: re-downloadable
  # (add more --exclude lines for any other large, reproducible caches)

# --- 3) UNPAUSE (also runs via trap, but do it ASAP to minimize freeze time) -
resume_containers

# --- 4) PRUNE ----------------------------------------------------------------
# OBJECT LOCK NOTE:
#   If the S3 bucket uses Object Lock (COMPLIANCE mode), objects cannot be
#   deleted until their retention expires, so `forget --prune` will FAIL to
#   remove still-locked pack files. Two supported ways to stay consistent:
#     (a) Use GOVERNANCE mode + an IAM role allowed to BypassGovernanceRetention
#         for the pruning identity, OR
#     (b) Align the values above with the bucket's lock window and let Restic's
#         metadata `forget` run while pack deletion happens after lock expiry.
#   On a hard-immutable (COMPLIANCE) bucket, run only `forget` (no --prune) and
#   let lifecycle rules reclaim space after the lock period:
log "applying retention policy (d=${KEEP_DAILY} w=${KEEP_WEEKLY} m=${KEEP_MONTHLY})"
restic forget \
  --keep-daily   "${KEEP_DAILY}" \
  --keep-weekly  "${KEEP_WEEKLY}" \
  --keep-monthly "${KEEP_MONTHLY}" \
  --prune \
  --tag ai-stack || log "WARNING: forget/prune incomplete (expected on Object-Lock COMPLIANCE buckets)."

# --- 5) Integrity spot-check (cheap; full check is heavier) ------------------
log "verifying repository metadata"
restic check --read-data-subset=5% || log "WARNING: restic check reported issues."

log "backup complete."
