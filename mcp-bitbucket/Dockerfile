# =============================================================================
#  mcp-bitbucket (SSE) — the upstream bitbucket-mcp image is a stdio-only binary
#  with no HTTP transport, so it exits immediately when run as a standalone
#  sidecar. We wrap it with supergateway to expose an SSE endpoint other
#  containers can reach.
#    result: http://mcp-bitbucket:8080/sse
#
#  NOTE: the upstream binary is musl-linked (built on Alpine), so the final
#  stage MUST be Alpine-based (node:20-alpine) — copying it into a glibc/Debian
#  image would fail with "not found" at exec time.
# =============================================================================
FROM ghcr.io/ibrahimogod/bitbucket-mcp:latest AS bb

FROM node:20-alpine
COPY --from=bb /app/bitbucket_mcp /usr/local/bin/bitbucket_mcp
RUN npm install -g supergateway

EXPOSE 8080
# BITBUCKET_API_USERNAME / BITBUCKET_API_TOKEN / BITBUCKET_WORKSPACE come from
# docker-compose env. supergateway launches the stdio child and bridges it to
# SSE on :8080. The child takes no subcommand (it goes straight to stdio).
CMD ["npx", "-y", "supergateway", \
     "--stdio", "bitbucket_mcp", \
     "--outputTransport", "sse", \
     "--port", "8080", \
     "--ssePath", "/sse", \
     "--messagePath", "/message"]
