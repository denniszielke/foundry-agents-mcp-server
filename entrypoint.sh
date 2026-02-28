#!/bin/sh
set -e

# TRANSPORT=http  → uvicorn HTTP server (Container Apps, default)
# TRANSPORT=stdio → stdio MCP server  (local / uvx usage)
TRANSPORT="${TRANSPORT:-http}"

if [ "$TRANSPORT" = "stdio" ]; then
    echo "Starting foundry-agents-mcp-server (stdio transport)"
    exec foundry-agents-mcp-server
else
    echo "Starting foundry-agents-mcp-server (HTTP transport on :8000)"
    exec uvicorn foundry_agents_mcp.server:http_app \
        --host 0.0.0.0 \
        --port 8000 \
        --workers 1 \
        --log-level warning
fi
