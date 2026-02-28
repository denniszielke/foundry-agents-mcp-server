"""Foundry Agents MCP Server – entry point.

All tool implementations live in dedicated modules:

- ``agents.py``   – ``agents_*`` tools (list / invoke / status / result)
- ``search.py``   – ``search_*`` tools (vector search / add to index)
- ``index.py``    – ``index_*`` tools (create index / ingest project log)
- ``workflows.py``– ``workflows_*`` tools (list workflows / run project-log pipeline)

The shared ``FastMCP`` instance is in ``app.py``; Azure client singletons,
environment variables, and helpers are in ``client.py``.

Configuration is driven by environment variables – see README.md.

Transports
----------
stdio (uvx / local MCP clients)::

    foundry-agents-mcp-server          # or: python -m foundry_agents_mcp

HTTP / Container Apps (uvicorn)::

    uvicorn foundry_agents_mcp.server:http_app --host 0.0.0.0 --port 8000
"""

import logging
import os

from azure.core.settings import settings as azure_settings
from starlette.responses import JSONResponse

from foundry_agents_mcp.app import mcp

# Import all tool modules so their @mcp.tool() decorators register the tools
# against the shared mcp instance defined in app.py.
from foundry_agents_mcp import agents, index, search, workflows  # noqa: F401

# ── OpenTelemetry / Application Insights ─────────────────────────────────────

# Tell the Azure SDK to route traces through opentelemetry
azure_settings.tracing_implementation = "opentelemetry"

_APPINSIGHTS_CONN = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
if _APPINSIGHTS_CONN:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor  # noqa: PLC0415

        configure_azure_monitor(connection_string=_APPINSIGHTS_CONN)
        logging.getLogger("foundry-agents-mcp").info(
            "Azure Monitor / Application Insights tracing enabled"
        )
    except ImportError:
        logging.getLogger("foundry-agents-mcp").warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is set but "
            "azure-monitor-opentelemetry is not installed; tracing disabled."
        )

# ── Health check endpoint ─────────────────────────────────────────────────────


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_request):
    """Health probe used by Azure Container Apps liveness / readiness checks."""
    return JSONResponse({"status": "healthy", "service": "foundry-agents-mcp-server"})


# ── ASGI application (HTTP transport for Container Apps) ─────────────────────

http_app = mcp.http_app()

# Instrument the Starlette ASGI app with OpenTelemetry when available
try:
    from opentelemetry.instrumentation.starlette import StarletteInstrumentor  # noqa: PLC0415

    StarletteInstrumentor.instrument_app(http_app)
except ImportError:
    pass


# ── stdio entry point (uvx / local MCP clients) ───────────────────────────────


def main() -> None:
    """Launch the MCP server over stdio (compatible with uvx and local clients)."""
    mcp.run()


if __name__ == "__main__":
    main()

