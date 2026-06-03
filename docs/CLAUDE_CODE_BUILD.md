# Claude Code build brief — Private Local AI Server

> **How to use this:** start Claude Code in an empty project directory (`claude` in the terminal, or the desktop Code tab), and paste this whole file as your first prompt. If you already have the previously generated files (compose files, `docs/ARCHITECTURE.md`, etc.), drop them in the repo first and tell Claude Code to *validate and build* them against this brief instead of authoring from scratch. `docs/ARCHITECTURE.md` is the canonical design; this brief is the build instruction.

---

## 0. Your mission (read first)

You are scaffolding and building a **private-first, local AI server** that runs as a Docker Compose stack on a single Ubuntu Server 24.04 host. Create the full repository structure and every file specified below, then validate and build incrementally.

**Operating rules — follow these throughout:**
1. **Work in small, validated steps.** After writing each file, validate it (YAML parse / `python -m py_compile` / `bash -n`). After each group, run `docker compose … config` to confirm the merge resolves. Commit to git after each working milestone.
2. **Never invent or hard-code secrets.** All secrets live in `.env` (from `.env.example`). Generate strong placeholders with `openssl rand -hex 32` only inside `.env`, which is git-ignored.
3. **Do not weaken the constraints in §2.** They are load-bearing.
4. **Some third-party tools move fast.** Where a flag/env/endpoint is marked "verify", leave a clear `# VERIFY:` comment rather than guessing silently; note them in a `BUILD_NOTES.md`.
5. **Ask before anything destructive** (removing data dirs, force-pushing, etc.). Don't run `docker compose down -v`.
6. Prefer `docker compose config` and image-pull/build dry checks over starting GPU services you can't test in your environment; clearly tell me which acceptance steps require the real GPU host.

---

## 1. Project overview & hardware target

A single host serving: an AI workspace + deep-research UI (Odysseus), private meta-search (SearXNG), an autonomous agent (Hermes), social automation (Postiz), an enterprise-knowledge "LLM wiki", read-only MCP context bridges to enterprise systems, event hooks, encrypted S3 backup, and observability — reachable only over a private Tailscale mesh.

- **CPU** i7-14700 (20c/28t) · **GPU** RTX 4000 Ada **20 GB**, FP8-capable · **RAM 32 GB single-channel DDR5** (bandwidth is the scarce resource) · **1 TB Gen4 NVMe** · **Ubuntu 24.04 LTS**.

---

## 2. Non-negotiable constraints

1. **Ingress:** no service publishes a port on `0.0.0.0`. **Tailscale is the sole ingress** (via `tailscale serve`). A few admin UIs may bind to `127.0.0.1` only. The **single public exception** is the Microsoft Graph notification receiver, exposed via **Tailscale Funnel scoped to exactly one path** (`/graph/notifications`).
2. **Inference (vLLM):** the LLM is served by vLLM, FP8, **fully parameterized via `VLLM_*` env**, defaulting to **single node / 1 GPU**. **Hermes rejects any model with <64k context**, so `--max-model-len 65536` + `--kv-cache-dtype fp8` are mandatory. Embeddings run in a **separate Infinity container on CPU** to preserve VRAM.
3. **Read-only enterprise access:** every enterprise connector is read-only, enforced at **two layers** — server read-only/restricted mode **and** read-scoped credentials (e.g. a dedicated `mcp_ro` Postgres role, a read-only SAP user, scoped API tokens). The custom SAP and domain-platform bridges issue **GET only**.
4. **Single-channel RAM:** every container has a hard `mem_limit`; the model stays resident in VRAM; heavy ingestion/compile/embedding work is confined to an **off-hours batch window**; vLLM's KV pool is bounded by `--gpu-memory-utilization`.
5. **One function per overlay file.** Adding a provider of an existing function = a sibling service in that overlay. Ingestion is the one exception (a single ephemeral Meltano container; new sources are *taps*, not containers).
6. **Backups are database-safe and never leave a DB frozen** (pause → snapshot → unpause with a guaranteed-unpause shell `trap`).

---

## 3. Repository layout to create

```
ai-stack/
├── docker-compose.yml                 # base (vLLM, embeddings, data, workspace, automation, tailscale)
├── docker-compose.integration.yml     # meltano + mcp-postgres                         [standard]
├── docker-compose.knowledgebase.yml   # wiki-viewer + wiki-compiler                    [standard]
├── docker-compose.repo.yml            # mcp-github + mcp-bitbucket                      [standard]
├── docker-compose.ticketing.yml       # mcp-jira (extensible)                           [standard]
├── docker-compose.collab.yml          # mcp-slack                                       [standard]
├── docker-compose.m365.yml            # mcp-m365 + m365-hooks                           [standard]
├── docker-compose.monitoring.yml      # beszel + beszel-agent + dozzle                  [standard]
├── docker-compose.erp.yml             # sap-b1-mcp + sap-b1-webhook                     [ON-DEMAND]
├── docker-compose.glg.yml             # mcp-glg + glg-poller (domain-specific platform) [ON-DEMAND]
├── docker-compose.cluster.yml         # multi-node Ray override for vllm                [ADVANCED]
├── .env.example                       # every variable (see §6); .env is git-ignored
├── .gitignore                         # must ignore .env, data/, odysseus/
├── README.md                          # short: clone→configure→up (you write this)
├── odysseus/                          # `git clone https://github.com/pewdiepie-archdaemon/odysseus.git`
├── searxng/settings.yml
├── postgres/{init-databases.sh, mcp-readonly.sql}
├── tailscale/serve.json
├── hermes/{Dockerfile, config.yaml}
├── meltano/{Dockerfile, meltano.yml}
├── librarian/{Dockerfile, compile.sh}
├── mcp-github/Dockerfile
├── sap-b1/{Dockerfile, server.py, webhook.py, extract.py}
├── m365/{Dockerfile, hooks.py}
├── glg/{Dockerfile, server.py, poll.py}
├── scripts/{backup.sh, nightly.sh}
└── docs/ARCHITECTURE.md               # design source of truth (place the provided doc here)
```

Shared conventions for every compose file: declare `networks: { ai-internal: { name: ai-internal, external: true } }` in the overlays (the **base** file *creates* it as a `bridge`); use a base `x-logging` anchor = `json-file`, `max-size: 10m`, `max-file: 3`; every service `restart: unless-stopped` (except `profiles:[jobs]` ones = `restart: "no"`); every service has a `deploy.resources.limits.memory`; all persistent data bind-mounts under `${DATA_ROOT}`.

---

## 4. Service specifications

### 4.1 `docker-compose.yml` (base) — creates network `ai-internal` (bridge)

| Service | Image | Key config |
|---|---|---|
| **vllm** | `vllm/vllm-openai:latest` | `ipc: host`; vol `${DATA_ROOT}/hf-cache:/root/.cache/huggingface`; env: `HF_TOKEN`, and `VLLM_MODEL`(default `RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8`), `VLLM_SERVED_NAME`(`llama3.1-8b`), `VLLM_MAX_MODEL_LEN`(`65536`), `VLLM_TENSOR_PARALLEL_SIZE`(`1`), `VLLM_PIPELINE_PARALLEL_SIZE`(`1`), `VLLM_GPU_MEMORY_UTILIZATION`(`0.82`), `VLLM_KV_CACHE_DTYPE`(`fp8`), `VLLM_MAX_NUM_SEQS`(`8`), `VLLM_EXTRA_ARGS`(empty). **Use shell-form so `VLLM_EXTRA_ARGS` word-splits:** `entrypoint: ["/bin/sh","-c"]` and a single `command` string calling `vllm serve "$${VLLM_MODEL}" --served-model-name "$${VLLM_SERVED_NAME}" --max-model-len "$${VLLM_MAX_MODEL_LEN}" --tensor-parallel-size "$${VLLM_TENSOR_PARALLEL_SIZE}" --pipeline-parallel-size "$${VLLM_PIPELINE_PARALLEL_SIZE}" --kv-cache-dtype "$${VLLM_KV_CACHE_DTYPE}" --gpu-memory-utilization "$${VLLM_GPU_MEMORY_UTILIZATION}" --max-num-seqs "$${VLLM_MAX_NUM_SEQS}" $${VLLM_EXTRA_ARGS}`. **`$$` is intentional** (escapes compose interpolation so the container shell expands the vars — which must therefore be in `environment:`). GPU: `deploy.resources.reservations.devices: [{driver: nvidia, count: ${VLLM_GPU_COUNT:-1}, capabilities: [gpu]}]`; `limits.memory: 8g`. Healthcheck: python urlopen `http://localhost:8000/health`, `start_period: 180s`. No published port. `# VERIFY: vllm serve is the modern CLI; older tags use python -m vllm.entrypoints.openai.api_server`. |
| **embeddings** | `michaelf34/infinity:latest` | `command: ["v2","--model-id","BAAI/bge-m3","--port","7997","--device","cpu"]`; vol hf-cache; healthcheck `/health`; `limits.memory: 4g`. CPU on purpose (preserve VRAM). |
| **chromadb** | `chromadb/chroma:latest` | vol `${DATA_ROOT}/chromadb:/data`; env `IS_PERSISTENT=TRUE`, `ANONYMIZED_TELEMETRY=FALSE`, `PERSIST_DIRECTORY=/data`; healthcheck via python urlopen `/api/v2/heartbeat` (`# VERIFY: v1 on older images`); `2g`. |
| **searxng** | `searxng/searxng:latest` | `ports: ["127.0.0.1:8080:8080"]` (loopback only); vol `./searxng/settings.yml:/etc/searxng/settings.yml:ro`; env `SEARXNG_BASE_URL=http://searxng:8080/`, `SEARXNG_SECRET=${SEARXNG_SECRET}`; `cap_drop:[ALL]`, `cap_add:[CHOWN,SETGID,SETUID]`; healthcheck `/healthz`; `512m`. |
| **postgres** | `postgres:16-alpine` | vols `${DATA_ROOT}/postgres:/var/lib/postgresql/data` + `./postgres/init-databases.sh:/docker-entrypoint-initdb.d/00-init-databases.sh:ro`; env superuser (`PG_SUPERUSER`/`PG_SUPERUSER_PASSWORD`, `POSTGRES_DB=postgres`) + app creds passed to init script (`ODYSSEUS_DB_*`, `POSTIZ_DB_*`); `command` tuning: `shared_buffers=256MB effective_cache_size=1GB max_connections=80 work_mem=16MB`; healthcheck `pg_isready`; `2g`. |
| **redis** | `redis:7-alpine` | `command: ["redis-server","--appendonly","yes","--maxmemory","384mb","--maxmemory-policy","noeviction"]`; vol `${DATA_ROOT}/redis:/data`; healthcheck `redis-cli ping`; `512m`. |
| **ntfy** | `binwiederhier/ntfy:latest` | `command:["serve"]`; vol `${DATA_ROOT}/ntfy:/var/lib/ntfy`; `256m`. |
| **odysseus** | build `./odysseus` (clone first), image `odysseus:local` | env: `APP_PORT=7000`, `AUTH_ENABLED=true`, `LOCALHOST_BYPASS=false`, `LLM_HOST=vllm:8000`, `SEARXNG_INSTANCE=http://searxng:8080`, `CHROMADB_HOST=chromadb`, `CHROMADB_PORT=8000`, `EMBEDDING_URL=http://embeddings:7997`, `DATABASE_URL=postgresql://${ODYSSEUS_DB_USER}:${ODYSSEUS_DB_PASSWORD}@postgres:5432/odysseus` (comment: fall back to its default SQLite if PG migration is immature), `ODYSSEUS_ADMIN_USER/PASSWORD`. vols `${DATA_ROOT}/odysseus/data` + `/odysseus/hf`. `depends_on`: vllm+embeddings (started), chromadb+postgres (healthy), searxng+ntfy (started). No public port. `4g`. |
| **hermes** | build `./hermes`, image `hermes-agent:local` | vols `${DATA_ROOT}/hermes:/root/.hermes` + `./hermes/config.yaml:/root/.hermes/config.yaml:ro`; env `OPENAI_API_KEY=vllm`, `HERMES_STREAM_READ_TIMEOUT=1800`; `depends_on: vllm (healthy)`; `2g`. |
| **postiz** | `ghcr.io/gitroomhq/postiz-app:v2.11.3` | **pin v2.11.3** (avoids the Temporal dep in v2.12+). vols config+uploads; env `MAIN_URL`/`FRONTEND_URL`=`https://${TS_HOSTNAME}.${TS_TAILNET}:8443`, `NEXT_PUBLIC_BACKEND_URL=…:8443/api`, `BACKEND_INTERNAL_URL=http://localhost:3000`, `JWT_SECRET`, `DATABASE_URL=…/postiz`, `REDIS_URL=redis://redis:6379`, `IS_GENERAL=true`, `DISABLE_REGISTRATION=false` (flip true after admin), `RUN_CRON=true`, `STORAGE_PROVIDER=local`, upload dirs. `depends_on` postgres+redis (healthy). No public port. `4g`. |
| **tailscale** | `tailscale/tailscale:latest` | `hostname: ${TS_HOSTNAME}`; vols `${DATA_ROOT}/tailscale:/var/lib/tailscale` + `./tailscale/serve.json:/config/serve.json:ro`; env `TS_AUTHKEY`, `TS_STATE_DIR=/var/lib/tailscale`, `TS_USERSPACE=true`, `TS_SERVE_CONFIG=/config/serve.json`, `TS_EXTRA_ARGS=--hostname=${TS_HOSTNAME} --accept-dns=true`; `depends_on` odysseus+postiz; `256m`. |

### 4.2 `docker-compose.integration.yml` (standard)
- **meltano** — build `./meltano`, image `meltano:local`, `profiles:["jobs"]`, `restart:"no"`, vols `./meltano:/project` + vault, env `TAP_*` (GitHub/Jira/Confluence/Slack), `1g`. (PostgreSQL DB itself stays in **base** — don't move it here.)
- **mcp-postgres** — `crystaldba/postgres-mcp:latest`, `command:["--access-mode=restricted","--transport=sse"]`, `DATABASE_URI=postgresql://${MCP_RO_DB_USER}:${MCP_RO_DB_PASSWORD}@postgres:5432/odysseus`, `depends_on postgres (healthy)`, `512m`. SSE → `:8000/sse`.

### 4.3 `docker-compose.knowledgebase.yml` (standard)
- **wiki-viewer** — build `./librarian`, image `librarian:local`, `command` runs `./llmwiki serve /data/vault --host 0.0.0.0 --port 3000`, vault vol, `1g`. `# VERIFY: ./llmwiki serve flags`.
- **wiki-compiler** — same image, `profiles:["jobs"]`, env `OPENAI_BASE_URL=http://vllm:8000/v1`, `OPENAI_API_KEY=vllm`, `LIBRARIAN_MODEL=llama3.1-8b`, `VAULT_RAW`/`VAULT_OUT`, `depends_on vllm (healthy)`, `command:["bash","/opt/compile.sh"]`, `3g`.

### 4.4 `docker-compose.repo.yml` (standard)
- **mcp-github** — build `./mcp-github`, image `mcp-github-sse:local`, env `GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_MCP_PAT}`, `GITHUB_READ_ONLY=1`, `GITHUB_LOCKDOWN_MODE=1`, `GITHUB_TOOLSETS=repos,issues,pull_requests`, `384m`. SSE → `:8081/sse`.
- **mcp-bitbucket** — `ghcr.io/ibrahimogod/bitbucket-mcp:latest` (Bitbucket **Cloud**), env `BITBUCKET_API_USERNAME`, `BITBUCKET_API_TOKEN` (scoped ATATT token — App Passwords deprecated 06/2026), `BITBUCKET_WORKSPACE`, `256m`. `# VERIFY: endpoint path/env vs image README`.

### 4.5 `docker-compose.ticketing.yml` (standard, extensible)
- **mcp-jira** — `ghcr.io/sooperset/mcp-atlassian:latest`, `command:["--transport","sse","--port","9000","--read-only"]`, env `JIRA_URL=${JIRA_BASE_URL}`, `JIRA_USERNAME=${JIRA_EMAIL}`, `JIRA_API_TOKEN`, `READ_ONLY_MODE=true` (omit Confluence creds → Jira-only), `384m`. Include **commented extension slots** for `mcp-linear`, `mcp-servicenow` to show the extensibility pattern.

### 4.6 `docker-compose.collab.yml` (standard)
- **mcp-slack** — `ghcr.io/korotovsky/slack-mcp-server:latest`, env `SLACK_MCP_XOXP_TOKEN=${SLACK_BOT_TOKEN}`, `SLACK_MCP_PORT=13080`, `SLACK_MCP_HOST=0.0.0.0`, `SLACK_MCP_SSE_API_KEY`, `384m`. `# VERIFY: token scheme`.

### 4.7 `docker-compose.m365.yml` (standard)
- **mcp-m365** — `ghcr.io/softeria/ms-365-mcp-server:latest`, `command:["--http","8000","--org-mode","--read-only"]`, env `MS365_MCP_TENANT_ID/CLIENT_ID/CLIENT_SECRET`, `512m`. `# VERIFY: env names + http flags in image docs/deployment.md`.
- **m365-hooks** — build `./m365`, image `m365-hooks:local`, env `MS365_*` + `GRAPH_NOTIFICATION_URL`, `GRAPH_CLIENT_STATE`, `GRAPH_SUBSCRIPTIONS`, `EXPIRATION_MINUTES=60`, `VAULT_EVENTS_DIR=/data/vault/raw/m365/events`, `NTFY_URL=http://ntfy:80/m365`; vault vol; `command:["uvicorn","hooks:app","--host","0.0.0.0","--port","8810"]`; `256m`.

### 4.8 `docker-compose.monitoring.yml` (standard)
- **beszel** — `henrygd/beszel:latest`, `ports:["127.0.0.1:8090:8090"]`, vol `${DATA_ROOT}/beszel:/beszel_data`, `256m`.
- **beszel-agent** — `henrygd/beszel-agent:latest`, vol `/var/run/docker.sock:/var/run/docker.sock:ro`, env `LISTEN=45876`, `KEY=${BESZEL_KEY}`, `GPU=true`, GPU reservation `[gpu, utility]`, `128m`. `# VERIFY: GPU-enable env for the tag`.
- **dozzle** — `amir20/dozzle:latest`, `ports:["127.0.0.1:8089:8080"]`, docker.sock ro, `DOZZLE_NO_ANALYTICS=true`, `128m`.

### 4.9 `docker-compose.erp.yml` (ON-DEMAND) — SAP Business One
- **sap-b1-mcp** — build `./sap-b1`, image `sap-b1-bridge:local`, `command:["python","server.py"]`, env `SAP_B1_SERVICE_LAYER_URL`, `SAP_B1_COMPANY_DB`, `SAP_B1_USER` (read-only SAP user), `SAP_B1_PASSWORD`, `SAP_B1_VERIFY_SSL` (default false), `MCP_HOST=0.0.0.0`, `MCP_PORT=8000`, `384m`. streamable-HTTP → `:8000/mcp`.
- **sap-b1-webhook** — same image, `command:["uvicorn","webhook:app","--host","0.0.0.0","--port","8800"]`, env `SAP_B1_WEBHOOK_SECRET`, `VAULT_EVENTS_DIR=/data/vault/raw/sap/events`, `NTFY_URL`, vault vol, `256m`.

### 4.10 `docker-compose.glg.yml` (ON-DEMAND) — enterprise domain-specific platform (reference impl)
- **mcp-glg** — build `./glg`, image `glg-bridge:local`, `command:["python","server.py"]`, env `GLG_API_BASE_URL`, `GLG_API_KEY`, `GLG_AUTH_HEADER`(`Authorization`), `GLG_AUTH_PREFIX`(`Bearer `), `GLG_ALLOWED_PATHS`, `MCP_HOST/PORT`, `384m`.
- **glg-poller** — same image, `command:["python","poll.py"]`, env `GLG_*` + `GLG_MODIFIED_PARAM`, `GLG_POLL_SECONDS=300`, `VAULT_EVENTS_DIR`, `NTFY_URL`, vault vol, `256m`.

### 4.11 `docker-compose.cluster.yml` (ADVANCED) — multi-node Ray override
- Override only the **vllm** service: append `--distributed-executor-backend ray` to `VLLM_EXTRA_ARGS`, publish `127.0.0.1:8265:8265` (Ray dashboard). Header comment must explain: single-host multi-GPU does NOT need this (just set TP + GPU_COUNT); cross-host uses vLLM's `run_cluster.sh` on each host (TP=GPUs/node, PP=nodes), shared image+model, same LAN.

---

## 5. Supporting files — required behavior

- **searxng/settings.yml** — `use_default_settings: true`; `server.bind_address 0.0.0.0`, `port 8080`, `secret_key "ultrasecretkey"` (image rewrites via `SEARXNG_SECRET`), `limiter: false`, `public_instance: false`; `search.formats: [html, json]` (**json required** for Odysseus). Trim engines sensibly.
- **postgres/init-databases.sh** — runs once on first boot; creates roles + databases `odysseus` (owner `${ODYSSEUS_DB_USER}`) and `postiz` (owner `${POSTIZ_DB_USER}`); grants schema `public` privileges (PG15+ locks it down).
- **postgres/mcp-readonly.sql** — idempotent: create `:mcp_user` LOGIN role; `GRANT USAGE` on schema public + `SELECT` on all tables/sequences; `ALTER DEFAULT PRIVILEGES … GRANT SELECT`; `REVOKE INSERT/UPDATE/DELETE/TRUNCATE`. Applied manually per DB after migrations.
- **tailscale/serve.json** — `tailscale serve` config using `${TS_CERT_DOMAIN}`: `:443 → http://odysseus:7000`, `:8443 → http://postiz:5000`; **plus a Funnel entry** on `:10000` proxying only `/graph/notifications → http://m365-hooks:8810` with `AllowFunnel` true for that port. Everything else `AllowFunnel: false`.
- **hermes/Dockerfile** — `FROM python:3.11-slim`; install `curl git tmux ca-certificates bash`; run the official Hermes installer (`curl -fsSL …NousResearch/hermes-agent…/install.sh | bash`, tolerate TTY probe with `|| true`); CMD starts the gateway headless (`hermes gateway start --headless || hermes gateway || tail -f /dev/null`). `# VERIFY: installer URL + gateway verb`.
- **hermes/config.yaml** — `model.default: llama3.1-8b`, `provider: custom`, `base_url: http://vllm:8000/v1`, **`context_length: 64000`** (Hermes hard minimum — do not lower); auxiliary compression model same; `terminal.backend: docker`.
- **meltano/{Dockerfile, meltano.yml}** — Dockerfile `FROM meltano/meltano:latest`, `meltano install`. `meltano.yml`: extractors `tap-github`, `tap-jira`, `tap-slack`, `tap-confluence`, `tap-google-drive`; loader `target-jsonl` → `destination_path: /data/vault/raw`; one **job per source** (`ingest-github`, …). `# VERIFY: tap variants for your tenancy`.
- **librarian/{Dockerfile, compile.sh}** — Dockerfile bundles **llmwiki** (`git clone lucasastorian/llmwiki`, install api + web) **and opencode** (npm global). `compile.sh`: loop each top-level dir under `/data/vault/raw/`, run `opencode run --model "openai/${LIBRARIAN_MODEL}" --mcp "llmwiki=stdio:./llmwiki mcp /data/vault" …` with a prompt to dedupe, build `[[backlinks]]`, tag `#contradiction`, writing into `/data/vault/wiki/<project>/` **only** (prevents cross-project context bleed). `# VERIFY: opencode + llmwiki CLI verbs`.
- **mcp-github/Dockerfile** — multi-stage: copy the `github-mcp-server` binary from `ghcr.io/github/github-mcp-server` into a `node:20-slim`, install `supergateway`, run `npx supergateway --stdio "github-mcp-server stdio" --outputTransport sse --port 8081 --ssePath /sse` (bridges stdio→SSE; read-only/lockdown via env from §4.4).
- **sap-b1/server.py** — read-only MCP (`mcp.server.fastmcp.FastMCP`, `transport="streamable-http"`). Handle the Service Layer **login handshake** (`POST /Login {CompanyDB,UserName,Password}` → session cookies), re-login on 401, **GET only**. Tools: `list_entities`, `query_entity(entity, select, filter, orderby, top≤100)`, `get_entity_by_key`. Allowlist common SL entities (BusinessPartners, Items, Orders, Invoices, …). `SAP_B1_VERIFY_SSL` toggles TLS verify.
- **sap-b1/webhook.py** — FastAPI; `POST /b1if/event` validates `X-B1-Secret` (constant-time) against `SAP_B1_WEBHOOK_SECRET`, persists raw payload (XML or JSON) + a `.meta.json` into `VAULT_EVENTS_DIR`, optional ntfy ping; `GET /healthz`.
- **sap-b1/extract.py** — login, page configured entity sets via `@odata.nextLink`, write one JSONL per entity into `/data/vault/raw/sap/`. Invoked by nightly cron.
- **sap-b1/Dockerfile** — `python:3.11-slim`, `pip install "mcp[cli]>=1.2" httpx fastapi "uvicorn[standard]"`, copy the three scripts.
- **m365/hooks.py** — FastAPI Graph hooks: **(1) receiver** `POST /graph/notifications` — if `?validationToken` present, echo it as `text/plain` 200 (Graph validation handshake); else verify each notification's `clientState` == `GRAPH_CLIENT_STATE`, persist accepted ones, return `202`. **(2) manager** — app-only token (client-credentials) → create/renew the `GRAPH_SUBSCRIPTIONS` every `EXPIRATION_MINUTES/2` in a background loop. `m365/Dockerfile`: `python:3.11-slim`, `pip install httpx fastapi "uvicorn[standard]"`.
- **glg/server.py** — generic **GET-only** REST→MCP bridge (`FastMCP`, streamable-http): `list_resources()` + `get(path, params)` restricted to an allowlist of leading path segments; auth header/prefix + key from env. **glg/poll.py** — poll each allowlisted resource with `GLG_MODIFIED_PARAM` since last run, write changed records to `VAULT_EVENTS_DIR`, ntfy ping, loop every `GLG_POLL_SECONDS`. `glg/Dockerfile`: `pip install "mcp[cli]>=1.2" httpx`.
- **scripts/backup.sh** — `set -Eeuo pipefail`; source `.env`; `flock` single-instance; **`trap` that guarantees `docker compose unpause`** on any exit; sequence: `restic init` if needed → `docker compose pause postgres redis chromadb` → `restic backup ${DATA_ROOT}` (exclude hf caches) → **unpause ASAP** → `restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune` (comment the S3 Object-Lock implications) → `restic check --read-data-subset=5%`.
- **scripts/nightly.sh** — phases `ingest` (run each Meltano job via `docker compose run --rm meltano meltano run <job>`, one at a time) and `compile` (`docker compose run --rm wiki-compiler`); confine to off-hours; usable from cron.

---

## 6. `.env.example` — generate complete, grouped by overlay

Include and document every variable, with safe placeholders. Top: **`COMPOSE_FILE`** = colon-joined standard set (`base:integration:knowledgebase:repo:ticketing:collab:m365:monitoring`) so a bare `docker compose up -d` works; note appending `:…erp.yml` / `:…glg.yml` / `:…cluster.yml` when needed. Groups & keys:
- **Core:** `DATA_ROOT`, vLLM block (`VLLM_MODEL`, `VLLM_SERVED_NAME`, `VLLM_MAX_MODEL_LEN`, `VLLM_GPU_MEMORY_UTILIZATION`, `VLLM_KV_CACHE_DTYPE`, `VLLM_MAX_NUM_SEQS`, `VLLM_EXTRA_ARGS`, `VLLM_TENSOR_PARALLEL_SIZE`, `VLLM_PIPELINE_PARALLEL_SIZE`, `VLLM_GPU_COUNT`), `HF_TOKEN`; Postgres roles; Odysseus admin; `POSTIZ_JWT_SECRET`; `SEARXNG_SECRET`; Tailscale (`TS_AUTHKEY`/`TS_HOSTNAME`/`TS_TAILNET`); optional `TELEGRAM_BOT_TOKEN`.
  - **Include a commented Qwen recipe**: `VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct-FP8`, `VLLM_SERVED_NAME=qwen`, and `VLLM_EXTRA_ARGS=--trust-remote-code --rope-scaling {"rope_type":"yarn","factor":2.0,"original_max_position_embeddings":32768}` (Qwen native ctx is 32k → YaRN needed for 64k). Note 14B-class won't fit 64k on 20 GB.
- **integration:** `MCP_RO_DB_USER/PASSWORD`, `GITHUB_MCP_PAT`, `JIRA_BASE_URL/EMAIL/API_TOKEN`, `CONFLUENCE_BASE_URL/API_TOKEN`, `SLACK_BOT_TOKEN`.
- **repo:** `BITBUCKET_API_USERNAME/API_TOKEN/WORKSPACE`.
- **ticketing:** (reuses Jira vars) + commented `JIRA_PERSONAL_TOKEN`, `LINEAR_API_KEY`, `SERVICENOW_*`.
- **collab:** `SLACK_MCP_SSE_API_KEY`.
- **m365:** `MS365_TENANT_ID/CLIENT_ID/CLIENT_SECRET`, `GRAPH_NOTIFICATION_URL` (Funnel URL on :10000), `GRAPH_CLIENT_STATE`, `GRAPH_SUBSCRIPTIONS` (one-line JSON).
- **monitoring:** `BESZEL_KEY`.
- **erp:** `SAP_B1_SERVICE_LAYER_URL/COMPANY_DB/USER/PASSWORD/VERIFY_SSL/WEBHOOK_SECRET`.
- **glg:** `GLG_API_BASE_URL/API_KEY/AUTH_HEADER/AUTH_PREFIX/ALLOWED_PATHS/MODIFIED_PARAM` (note `AUTH_PREFIX=Bearer ` keeps a trailing space).
- **backup:** `RESTIC_REPOSITORY`, `RESTIC_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`.

After writing it, **cross-check**: every `${VAR}` in any compose file / `hermes/config.yaml` is present (active or commented), and `backup.sh`'s vars too.

---

## 7. Build & validation workflow (run in order)

1. `git init`; write `.gitignore` (`.env`, `data/`, `odysseus/`, `**/__pycache__/`). Commit the skeleton.
2. **Static validation** (do this in your sandbox — no GPU needed):
   - YAML: `for f in docker-compose*.yml; do python3 -c "import yaml,sys; yaml.safe_load(open('$f'))" || exit 1; done`
   - Python: `python3 -m py_compile sap-b1/*.py m365/*.py glg/*.py`
   - Bash: `bash -n scripts/*.sh postgres/init-databases.sh`
   - Merge resolves: `docker compose $(printf -- '-f %s ' docker-compose*.yml | sed 's/-f docker-compose.cluster.yml //') config >/dev/null` (cluster overlay is an override; test it separately).
3. Print the standard-set `docker compose config` and confirm: no `0.0.0.0` published ports (only `127.0.0.1:*`), `ai-internal` external, every service has `mem_limit`, vllm has the GPU reservation, read-only flags present on mcp-github/postgres/jira/m365.
4. Record every `# VERIFY:` item in `BUILD_NOTES.md`.
5. **On the real GPU host** (tell me these need the hardware): install NVIDIA driver + Container Toolkit (`nvidia-ctk runtime configure`; `docker run --rm --gpus all ubuntu nvidia-smi`); `cp .env.example .env` and fill secrets; `git clone` Odysseus into `./odysseus`; `mkdir -p ${DATA_ROOT}`; `sysctl vm.swappiness=10`; `docker compose build`; `docker compose up -d`; confirm `vllm`/`embeddings` healthy; first-login Odysseus and add the vLLM provider; apply `mcp-readonly.sql`; wire MCP endpoints into Odysseus/Hermes; configure the M365 Funnel + subscriptions; install cron for `nightly.sh` and `backup.sh`; do a backup + **test restore**.

---

## 8. Acceptance criteria

- All compose files parse; standard-set `config` merges cleanly; no public `0.0.0.0` ports.
- vLLM serves `llama3.1-8b` and answers an OpenAI-style `/v1/chat/completions`; `nvidia-smi` shows ~13–14 GB used with ≥5 GB headroom; Hermes starts (64k accepted).
- Odysseus reachable only over the tailnet; a research query returns SearXNG JSON results.
- Each standard MCP returns **read-only** results to an agent; writes are rejected.
- Nightly ingest populates `vault/raw/`; compile produces interlinked `vault/wiki/<project>/`.
- `backup.sh` snapshots to S3 and a test restore succeeds; containers are confirmed unpaused even on simulated mid-run failure.
- Beszel shows host + GPU metrics; Dozzle streams logs.
- ERP and domain-platform overlays are **absent** from a standard `up` and work when their `-f` file is added.

---

## 9. Things to verify against current vendor docs (don't guess silently)

vLLM CLI (`vllm serve` vs module) and FP8 checkpoint name; Infinity v2 flags; Chroma heartbeat path (v1/v2); Hermes installer URL + headless gateway verb; opencode + llmwiki CLI verbs; Bitbucket Cloud MCP env/endpoint; Slack MCP token scheme; Softeria M365 env names + `--http` flags; `sooperset/mcp-atlassian` Jira-only scoping + read-only flag; Beszel agent GPU-enable env; Meltano tap variants; Postiz v2.11.3 env keys.

Build it methodically, validate at each step, and keep `BUILD_NOTES.md` current. Ask me whenever a `# VERIFY:` item materially affects correctness.
