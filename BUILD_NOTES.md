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
- [x] Every `${VAR}` referenced in compose / `hermes/config.yaml` / `scripts/backup.sh` is defined in `.env.example` (or is a script-local var / runtime-substituted placeholder — see "Non-issues").

## Open VERIFY items (confirm against current vendor docs)

| # | Where | What to verify |
|---|---|---|
| 1 | `docker-compose.yml` vllm | `vllm serve` is the modern CLI; older image tags use `python -m vllm.entrypoints.openai.api_server`. Confirm the FP8 checkpoint name `RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8` still resolves on HF. |
| 2 | `docker-compose.yml` chromadb | **RESOLVED:** `/api/v2/heartbeat` is correct (`v1` → `410 Gone`). The image ships **no python/curl/wget**, so the python healthcheck never passed → container stuck "unhealthy" though the server was fine. Healthcheck rewritten to a bash `/dev/tcp` HTTP GET asserting `200 OK` (invoked via `CMD bash -c`, since `/bin/sh` is dash). |
| 3 | `docker-compose.yml` embeddings | Infinity v2 CLI flags (`v2 --model-id … --device cpu`). |
| 4 | `docker-compose.knowledgebase.yml` wiki-viewer | **PARTIALLY RESOLVED:** `llmwiki serve <workspace>` takes only a positional path (no `--host/--port`) and needs `llmwiki init` first — command fixed to `init || true; serve`. It launches API on `0.0.0.0:8000` + web on `:3000`. **Also fixed `librarian/Dockerfile`:** api deps were installed into a venv but `serve` calls `sys.executable -m uvicorn` (system python) → `No module named uvicorn`; now installed into system python. **Requires `docker compose build wiki-viewer` to take effect** (not yet rebuilt here). |
| 5 | `docker-compose.repo.yml` mcp-bitbucket | **OPEN — needs a decision.** `ghcr.io/ibrahimogod/bitbucket-mcp` `CMD` is a compiled **stdio-only** binary (`/app/bitbucket_mcp`); it has no HTTP/SSE mode and exits immediately ("expect initialize request" / `UnexpectedEof`) with no client attached, so it crash-loops as a standalone sidecar. To run it as a network MCP it needs a stdio→SSE bridge (the `supergateway` pattern used by `mcp-github`'s Dockerfile). Fix only if you use Bitbucket. |
| 6 | `docker-compose.collab.yml` mcp-slack | Token scheme — XOXP bot token vs browser XOXC/XOXD; env names changed across versions. Reference `@modelcontextprotocol/server-slack` is archived. |
| 7 | `docker-compose.m365.yml` mcp-m365 | **RESOLVED:** Softeria publishes **no** ghcr image (`ghcr.io/softeria/ms-365-mcp-server` → `denied`); it ships as npm `@softeria/ms-365-mcp-server`. Now run via `npx` on `node:22-bookworm-slim`, pinned `@0.114.0`, npm cache persisted at `${DATA_ROOT}/m365-mcp-npm`. Verified env names `MS365_MCP_TENANT_ID/CLIENT_ID/CLIENT_SECRET`, `--http 8000` (MCP at `/mcp`), `--org-mode`, `--read-only`. **Open:** the README documents delegated/device-code auth; true app-only (client-credentials) Graph access may require the companion `okapi-ca/ms-365-admin-mcp-server` — confirm app-only works for your tenant. Bump the version pin as upstream releases. |
| 8 | `docker-compose.ticketing.yml` mcp-jira | `sooperset/mcp-atlassian` Jira-only scoping (omit Confluence creds) + read-only flag; Cloud API token vs Server/DC PAT env names. |
| 9 | `docker-compose.monitoring.yml` beszel-agent | GPU-enable env for the pinned tag (`GPU=true` + `[gpu, utility]` reservation). |
| 10 | `meltano/meltano.yml` | Tap variants for the tenancy (`tap-github`, `tap-jira`, `tap-slack`, `tap-confluence`, `tap-google-drive`). |
| 11 | `librarian/Dockerfile`, `librarian/compile.sh` | `opencode` install command + `opencode`/`llmwiki` CLI verbs (`opencode run`, `llmwiki mcp`) — flag names evolve. |
| 12 | `hermes/Dockerfile` | Hermes installer URL + headless gateway verb (`hermes gateway start --headless`) can change between releases. |
| 13 | `docker-compose.repo.yml` / general | Postiz pinned at `v2.11.3` to avoid the Temporal dep in v2.12+; confirm env keys if bumping. |

## Required one-time host setup

- **Create the shared network before the first `up`:** `docker network create ai-internal`. The overlays declare it `external: true`, and in the merged standard set that wins over the base's bridge definition, so Compose will **not** auto-create it — `docker compose up -d` fails with *"network ai-internal declared as external, but could not be found"* until it exists. The network persists across reboots; only recreate it if explicitly removed. (Documented in README §3.)

## First-boot runtime findings (dev host: WSL2, RTX 4050 Laptop 6 GB)

- **postgres** init script never ran on first boot: it was mode `0600` (unreadable by the postgres uid) → "Permission denied", and the data dir was then non-empty so init was skipped. Fixed file modes to `0644` for all bind-mounted config (`init-databases.sh`, `mcp-readonly.sql`, `searxng/settings.yml`, `tailscale/serve.json`, `hermes/config.yaml`) and created the `odysseus`/`postiz` DBs + roles manually against the live cluster. (Git only stores the exec bit, so a fresh `git clone` checks these out `0644` — this was a local working-tree artifact.)
- **vllm** loads on the 6 GB laptop GPU but will not fit the default 8B-FP8 model at 64k context — needs the target **RTX 4000 Ada 20 GB** host. The `VLLM_*` "Unknown environment variable" warnings are benign (passed as env so the shell command expands them into CLI flags).
- **Credential-gated (not bugs)** — these crash-loop until real secrets are in `.env`: `mcp-slack` (`SLACK_BOT_TOKEN` xoxp → `invalid_auth`), `beszel-agent` (`BESZEL_KEY`, generated by the Beszel hub UI on first run).

## Non-issues (checked, intentional)

- `${TS_CERT_DOMAIN}` in `tailscale/serve.json` is auto-substituted by Tailscale at runtime, not from `.env`.
- `COMPOSE`, `STACK_DIR`, `ENV_FILE`, `RESUMED`, `KEEP_DAILY/WEEKLY/MONTHLY` are script-local variables in `scripts/*.sh`, not user config.
- `docker-compose.enterprise.yml` is an aggregate bundle overlay (meltano + wiki-viewer/compiler + mcp-postgres/slack/github) referenced by `scripts/nightly.sh`; it is intentionally NOT part of the standard `COMPOSE_FILE` set, so a standard `up` does not double-define services.

## Repo-structure note (vs brief §3)

- The variables file is named `.env.example` per §3. (It was briefly `env.example` with a duplicate at `tmp/.env.example`; renamed via `git mv` and the `tmp/` scratch dir removed. `.gitignore` ignores `.env` but not `.env.example`, so the example is tracked.)

## Steps that require the GPU host / live credentials (NOT run here)

See brief §7.5. In short: NVIDIA driver + Container Toolkit install, `cp .env.example .env` + fill secrets, `git clone` Odysseus, `mkdir ${DATA_ROOT}`, `docker compose build`, `docker compose up -d`, vLLM/embeddings health, Odysseus first-login + vLLM provider, apply `postgres/mcp-readonly.sql`, wire MCP endpoints, M365 Funnel + subscriptions, cron for `nightly.sh`/`backup.sh`, backup + test restore.
