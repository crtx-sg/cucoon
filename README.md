# Cucoon — a private, self-hosted AI server

*A sovereign "city" of AI services on your own hardware: an autonomous workspace, deep-research platform, agent hub, enterprise-knowledge compiler, and read-only bridges to your business systems — reachable only over your private mesh.*

> *Cucoon* — a protective, self-contained enclosure for your AI. The name appears only in docs/paths, never in service config, so it's easy to change.

---

## What it is

Cucoon runs as a modular Docker Compose stack on a single Linux box. Everything operates **locally or over an encrypted Tailscale mesh**; the public cloud is used only for encrypted off-site backup. The full design rationale lives in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); to build it with Claude Code, see [`docs/CLAUDE_CODE_BUILD.md`](docs/CLAUDE_CODE_BUILD.md).

**Core**
- **vLLM** — local LLM serving (FP8, OpenAI-compatible), configurable; single-node default, multi-GPU/multi-node ready.
- **Infinity** — local embeddings (`bge-m3`, CPU).
- **Odysseus** — AI workspace & deep-research UI · **Hermes** — autonomous agent · **Postiz** — social automation.
- **SearXNG** — private meta-search · **PostgreSQL · Redis · ChromaDB · ntfy** — data & messaging.
- **Tailscale** — the *sole* ingress.

**Knowledge & integration overlays** (one function per file)
- **integration** — Meltano ingestion + read-only Postgres MCP
- **knowledgebase** — LLM-wiki compiler + viewer
- **repo** — GitHub + Bitbucket (read-only)
- **ticketing** — Jira (read-only; extensible to Linear/ServiceNow/…)
- **collab** — Slack (read-only)
- **m365** — Outlook/Teams/SharePoint + Microsoft Graph event hooks
- **monitoring** — Beszel dashboard + GPU metrics + Dozzle live logs
- **erp** *(on-demand)* — SAP Business One (read-only MCP + B1if event hooks)
- **glg** *(on-demand)* — reference implementation of the *enterprise domain-specific platform* pattern (read-only REST MCP + polling)
- **cluster** *(advanced)* — multi-node GPU serving via Ray

Every enterprise connector is **read-only**. No application UI is exposed to the public internet.

---

## Hardware target

| | |
|---|---|
| CPU | Intel Core i7-14700 (20c/28t) |
| GPU | NVIDIA RTX 4000 Ada, 20 GB (FP8-capable) |
| RAM | 32 GB single-channel DDR5 *(bandwidth is the scarce resource)* |
| Storage | 1 TB Gen4 NVMe |
| OS | Ubuntu Server 24.04 LTS |

Other GPUs work; adjust the model and `VLLM_*` settings to your VRAM.

---

## Quick start

**1. Prerequisites (one-time, on the host)**

```bash
# NVIDIA driver + Container Toolkit
sudo ubuntu-drivers autoinstall
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
docker run --rm --gpus all ubuntu nvidia-smi      # must list the RTX 4000 Ada

echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-cucoon.conf && sudo sysctl --system
```

**2. Configure**

```bash
git clone https://github.com/pewdiepie-archdaemon/odysseus.git ./odysseus   # build context
cp .env.example .env                 # then fill in EVERY secret you use
sudo mkdir -p /opt/cucoon/data        # = DATA_ROOT in .env
# generate strong secrets:
for k in PG_SUPERUSER_PASSWORD ODYSSEUS_DB_PASSWORD POSTIZ_DB_PASSWORD \
         POSTIZ_JWT_SECRET SEARXNG_SECRET MCP_RO_DB_PASSWORD \
         GRAPH_CLIENT_STATE SAP_B1_WEBHOOK_SECRET SLACK_MCP_SSE_API_KEY RESTIC_PASSWORD; do
  echo "$k=$(openssl rand -hex 32)"
done   # paste into .env; also set TS_*, AWS_*, and the connector tokens you use
```

`COMPOSE_FILE` in `.env` is preset to the **standard** set, so a bare `docker compose` command picks up the right overlays.

**3. Build & run**

```bash
docker compose build          # builds odysseus, hermes, meltano, librarian, mcp-github, sap-b1, m365, glg
docker compose up -d
docker compose ps             # watch healthchecks
docker compose logs -f vllm   # first run downloads the model (a few minutes)
```

**4. First login**

- Open `https://<TS_HOSTNAME>.<TS_TAILNET>.ts.net/` (Odysseus) over your tailnet.
- In Odysseus → Settings, add an OpenAI-compatible provider: `http://vllm:8000/v1`, model `llama3.1-8b`; enable the "served behind a trusted HTTPS proxy" setting.
- Apply the read-only DB role once schemas exist:
  ```bash
  docker compose exec -T postgres psql -U "$PG_SUPERUSER" -d odysseus \
    -v mcp_user="$MCP_RO_DB_USER" -v mcp_pass="'$MCP_RO_DB_PASSWORD'" \
    -f - < postgres/mcp-readonly.sql
  ```
- Wire the MCP endpoints into Odysseus/Hermes (see `docs/ARCHITECTURE.md` §3.5).

---

## Bring-up profiles

```bash
# Standard (default via COMPOSE_FILE): workspace + automation + ingestion/wiki + MCP + M365 + monitoring
docker compose up -d

# Add the SAP B1 module only when needed:
docker compose -f docker-compose.yml -f docker-compose.integration.yml \
  -f docker-compose.knowledgebase.yml -f docker-compose.repo.yml \
  -f docker-compose.ticketing.yml -f docker-compose.collab.yml \
  -f docker-compose.m365.yml -f docker-compose.monitoring.yml \
  -f docker-compose.erp.yml up -d
# (…append -f docker-compose.glg.yml for the domain-specific platform module.)
```

Run the batch jobs (or schedule them via cron — see `scripts/nightly.sh`):

```bash
docker compose run --rm meltano meltano run ingest-github   # ingestion (per source)
docker compose run --rm wiki-compiler                       # nightly LLM-wiki compile
```

---

## Configuration highlights

- **Swap the model** via `.env`: `VLLM_MODEL` / `VLLM_SERVED_NAME`. Default is Llama-3.1-8B FP8 (native 128k → clean 64k for Hermes). A ready-to-use **Qwen** recipe (with YaRN for 64k) is in `.env.example`.
- **Scale the GPU**: single host with N GPUs → `VLLM_TENSOR_PARALLEL_SIZE=N`, `VLLM_GPU_COUNT=N`. Multi-node → add `docker-compose.cluster.yml` (Ray). Default is single node, 1 GPU.
- **Monitoring UIs** (loopback; surface over the tailnet if wanted): Beszel `http://127.0.0.1:8090`, Dozzle `http://127.0.0.1:8089`.
- **Backups**: `scripts/backup.sh` (Restic → S3, database-safe pause/snapshot/unpause). Schedule via cron; **test a restore**.

---

## Repository structure

```
docker-compose.yml + *.{integration,knowledgebase,repo,ticketing,collab,m365,monitoring,erp,glg,cluster}.yml
searxng/ postgres/ tailscale/ hermes/ meltano/ librarian/ mcp-github/ sap-b1/ m365/ glg/ scripts/ odysseus/
.env.example   docs/{ARCHITECTURE.md, CLAUDE_CODE_BUILD.md}
```

---

## Security model (in one breath)

Tailscale is the only way in; application UIs publish no public ports (a few bind to `127.0.0.1`). The single public surface is one Tailscale Funnel path for Microsoft Graph notifications, protected by a validation handshake + shared secret. Enterprise connectors are read-only at two layers (server mode + scoped credentials). Secrets live only in `.env`. Backups are encrypted (Restic) to an Object-Lock S3 bucket.

---

## Documentation

- **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** — specification, architecture, block diagram, phased implementation plan, design decisions.
- **[`docs/CLAUDE_CODE_BUILD.md`](docs/CLAUDE_CODE_BUILD.md)** — build brief to scaffold/validate/build the stack with Claude Code.

---

## Notes

Several third-party components are young and move quickly; spots that should be checked against current upstream docs are marked `# VERIFY:` in the files and listed in `docs/CLAUDE_CODE_BUILD.md §9`. This stack is provided as an architecture and configuration baseline, not a turnkey appliance — review credentials, scopes, and backups before relying on it.
