"""Foundry Agents MCP Server – entry point.

All tool implementations live in dedicated modules:

- ``agents.py``   – ``agents_*`` tools (list / invoke / status / result)
- ``search.py``   – ``search_*`` tools (vector search / add to index)
- ``index.py``    – ``index_*`` tools (create index / ingest project log)
- ``workflows.py``– ``workflows_*`` tools (list workflows / run project-log pipeline)

The shared ``FastMCP`` instance is in ``app.py``; Azure client singletons,
environment variables, and helpers are in ``client.py``.

Configuration is driven by environment variables – see README.md.
"""

from foundry_agents_mcp.app import mcp

# Import all tool modules so their @mcp.tool() decorators register the tools
# against the shared mcp instance defined in app.py.
from foundry_agents_mcp import agents, index, search, workflows  # noqa: F401


def main() -> None:
    """Launch the Foundry Agents MCP Server via stdio (compatible with uvx)."""
    mcp.run()


if __name__ == "__main__":
    main()
