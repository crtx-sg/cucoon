# =============================================================================
#  mcp-github (SSE) — GitHub's official MCP server is stdio-only, so we wrap it
#  with supergateway to expose an SSE endpoint other containers can reach.
#    result: http://mcp-github:8081/sse
# =============================================================================
# Start from the official GitHub MCP image (provides the stdio binary)...
FROM ghcr.io/github/github-mcp-server:latest AS gh

# ...and run it behind supergateway (Node).
FROM node:20-slim
COPY --from=gh /server/github-mcp-server /usr/local/bin/github-mcp-server
RUN npm install -g supergateway

EXPOSE 8081
# READ_ONLY/LOCKDOWN/TOOLSETS are supplied via env in docker-compose.
# supergateway launches the stdio child and bridges it to SSE on :8081.
CMD ["npx", "-y", "supergateway", \
     "--stdio", "github-mcp-server stdio", \
     "--outputTransport", "sse", \
     "--port", "8081", \
     "--ssePath", "/sse", \
     "--messagePath", "/message"]
