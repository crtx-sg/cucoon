# =============================================================================
#  Hermes Agent — containerized wrapper around Nous Research's official install.
#  Hermes is daemon-first and normally installed via its curl script; there is
#  no official image. This builds one so it lives in the same compose lifecycle.
#
#  IMPORTANT: Hermes onboarding (`hermes model`) is interactive. We avoid that by
#  pre-seeding ./hermes/config.yaml (mounted to /root/.hermes/config.yaml). The
#  gateway start command can change between Hermes releases — verify against
#  `hermes --help` if startup fails, and see the host-install fallback in notes.
# =============================================================================
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    HERMES_NONINTERACTIVE=1

# tmux is required by some Hermes background tasks; git/curl for the installer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git tmux ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

# Pull and run the official installer (pins to main; pin a tag for reproducibility).
RUN curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh -o /tmp/install.sh \
    && bash /tmp/install.sh || true   # installer may probe for a TTY; config is mounted at runtime

# Make the CLI available on PATH regardless of where the installer placed it.
ENV PATH="/root/.local/bin:/root/.hermes/bin:${PATH}"

WORKDIR /root/.hermes

# Headless gateway. If your Hermes version uses a different verb, override the
# command in docker-compose.yml (e.g. `hermes serve` / `hermes gateway run`).
CMD ["bash", "-lc", "hermes gateway start --headless || hermes gateway || tail -f /dev/null"]
