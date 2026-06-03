# BUILD_NOTES

Static validation log + the "verify against current upstream docs" items that
remain open. None of these block a `docker compose config` merge; they are
fast-moving third-party flags/endpoints to confirm against vendor docs before
relying on the corresponding service (see brief §9).

## Validation status (this sandbox, no GPU)

- [x] All `docker-compose*.yml` parse as YAML (11 overlays + `docker-compose.enterprise.yml`).
- [x] `python -m py_compile` clean: `sap-b1/*.py`, `m365/*.py`, `glg/*.py`.
- [x] `bash -n` clean: `scripts/*.sh`, `postgres/init-databases.sh`.
- [x] Standard-set merge (`COMPOSE_FILE`) resolves; full glob merge (excl. cluster) resolves; base+cluster resolves; base+enterprise resolves.
- [x] No service publishes on `0.0.0.0` — only `127.0.0.1` (beszel 8090, dozzle 8089, searxng 8080).
- [x] `ai-internal` is `external: true` in every overlay; base creates it as a `bridge`.
- [x] All 22 standard-set services carry a `deploy.resources.limits.memory`.
- [x] `vllm` carries the GPU reservation (`driver: nvidia`, `count: ${VLLM_GPU_COUNT:-1}`, `capabilities: [gpu]`).
- [x] Read-only flags present: mcp-github (`GITHUB_READ_ONLY=1`, `GITHUB_LOCKDOWN_MODE=1`), mcp-postgres (`--access-mode=restricted`), mcp-jira (`--read-only` + `READ_ONLY_MODE=true`), mcp-m365 (`--read-only`).
- [x] Every `${VAR}` referenced in compose / `hermes/config.yaml` / `scripts/backup.sh` is defined in `env.example` (or is a script-local var / runtime-substituted placeholder — see "Non-issues").

## Open VERIFY items (confirm against current vendor docs)

| # | Where | What to verify |
|---|---|---|
| 1 | `docker-compose.yml` vllm | `vllm serve` is the modern CLI; older image tags use `python -m vllm.entrypoints.openai.api_server`. Confirm the FP8 checkpoint name `RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8` still resolves on HF. |
| 2 | `docker-compose.yml` chromadb | Heartbeat path: Chroma 1.x = `/api/v2/heartbeat`; pinning an older 0.5.x image needs `/api/v1/heartbeat`. |
| 3 | `docker-compose.yml` embeddings | Infinity v2 CLI flags (`v2 --model-id … --device cpu`). |
| 4 | `docker-compose.knowledgebase.yml` wiki-viewer | Exact `./llmwiki serve` flags — check `./llmwiki serve --help` for the checkout. |
| 5 | `docker-compose.repo.yml` mcp-bitbucket | Bitbucket **Cloud** MCP env names + endpoint path (`http://mcp-bitbucket:8080`?) vs image README. Note: scoped ATATT token (App Passwords deprecated 06/2026). |
| 6 | `docker-compose.collab.yml` mcp-slack | Token scheme — XOXP bot token vs browser XOXC/XOXD; env names changed across versions. Reference `@modelcontextprotocol/server-slack` is archived. |
| 7 | `docker-compose.m365.yml` mcp-m365 | Softeria env names (`MS365_MCP_*`) + `--http`/`--org-mode`/`--read-only` flags vs the image's `docs/deployment.md`; transport/path. |
| 8 | `docker-compose.ticketing.yml` mcp-jira | `sooperset/mcp-atlassian` Jira-only scoping (omit Confluence creds) + read-only flag; Cloud API token vs Server/DC PAT env names. |
| 9 | `docker-compose.monitoring.yml` beszel-agent | GPU-enable env for the pinned tag (`GPU=true` + `[gpu, utility]` reservation). |
| 10 | `meltano/meltano.yml` | Tap variants for the tenancy (`tap-github`, `tap-jira`, `tap-slack`, `tap-confluence`, `tap-google-drive`). |
| 11 | `librarian/Dockerfile`, `librarian/compile.sh` | `opencode` install command + `opencode`/`llmwiki` CLI verbs (`opencode run`, `llmwiki mcp`) — flag names evolve. |
| 12 | `hermes/Dockerfile` | Hermes installer URL + headless gateway verb (`hermes gateway start --headless`) can change between releases. |
| 13 | `docker-compose.repo.yml` / general | Postiz pinned at `v2.11.3` to avoid the Temporal dep in v2.12+; confirm env keys if bumping. |

## Non-issues (checked, intentional)

- `${TS_CERT_DOMAIN}` in `tailscale/serve.json` is auto-substituted by Tailscale at runtime, not from `.env`.
- `COMPOSE`, `STACK_DIR`, `ENV_FILE`, `RESUMED`, `KEEP_DAILY/WEEKLY/MONTHLY` are script-local variables in `scripts/*.sh`, not user config.
- `docker-compose.enterprise.yml` is an aggregate bundle overlay (meltano + wiki-viewer/compiler + mcp-postgres/slack/github) referenced by `scripts/nightly.sh`; it is intentionally NOT part of the standard `COMPOSE_FILE` set, so a standard `up` does not double-define services.

## Repo-structure note (vs brief §3)

- The variables file is named `env.example` (no leading dot) rather than `.env.example`. Functionally equivalent (both committed; `.gitignore` ignores `.env`). A duplicate copy exists at `tmp/.env.example`. Flagged for your awareness — not changed.

## Steps that require the GPU host / live credentials (NOT run here)

See brief §7.5. In short: NVIDIA driver + Container Toolkit install, `cp env.example .env` + fill secrets, `git clone` Odysseus, `mkdir ${DATA_ROOT}`, `docker compose build`, `docker compose up -d`, vLLM/embeddings health, Odysseus first-login + vLLM provider, apply `postgres/mcp-readonly.sql`, wire MCP endpoints, M365 Funnel + subscriptions, cron for `nightly.sh`/`backup.sh`, backup + test restore.
