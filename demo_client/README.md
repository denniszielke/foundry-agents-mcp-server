# Demo MCP Client

A lightweight demo client that connects to the **foundry-agents-mcp-server**
and exercises its core tools: listing agents/workflows, invoking an agent, and
running a workflow.

## Prerequisites

* Python ≥ 3.10
* The MCP server's dependencies installed (run `pip install -e .` from the repo root)
* A `.env` file in the **repo root** with at least `AZURE_AI_PROJECT_ENDPOINT` set

## Usage

```bash
# From the repo root (the .env file must be there):
python -m demo_client

# Or run individual demos:
python -m demo_client --list-agents
python -m demo_client --list-workflows
python -m demo_client --invoke-agent <AGENT_ID> "Summarise the latest AI announcements"
python -m demo_client --run-workflow "https://www.microsoft.com/en/customers/story/..."
```

## How it works

The client uses the **fastmcp `Client`** (part of the Microsoft Agent Framework
MCP libraries already installed with the server) to spawn the MCP server as a
subprocess over **stdio** transport and call tools exactly as any MCP host would.
