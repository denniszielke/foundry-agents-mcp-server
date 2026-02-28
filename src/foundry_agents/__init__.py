"""foundry_agents – deployable Azure AI Foundry agent and workflow implementations.

This package is intentionally independent of ``foundry_agents_mcp`` so that it
can be used standalone (e.g. from the CLI) or imported by the MCP server.

Exposed constants
-----------------
DEFINITIONS_DIR : pathlib.Path
    Directory containing the declarative YAML definitions for agents and
    the workflow (``kind: Prompt`` / ``kind: Workflow`` format).
"""

from pathlib import Path

DEFINITIONS_DIR: Path = Path(__file__).parent / "definitions"

__all__ = ["DEFINITIONS_DIR"]
