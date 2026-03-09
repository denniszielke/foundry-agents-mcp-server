"""Demo MCP client for the foundry-agents-mcp-server.

Uses the **fastmcp Client** (Microsoft Agent Framework MCP library) to connect
to the server over stdio and exercise the core tools:

  1. List agents          – agents_list_agents
  2. List workflows       – workflows_list_sample_workflows
  3. Invoke an agent      – agents_invoke_agent  → poll → get result
  4. Run a workflow       – workflows_run_project_log_workflow
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from fastmcp import Client
from mcp import StdioServerParameters


# ── Helpers ──────────────────────────────────────────────────────────────────

def _server_params() -> StdioServerParameters:
    """Build stdio transport parameters that launch the MCP server."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "foundry_agents_mcp"],
    )


def _print_section(title: str, body: str) -> None:
    width = max(len(title) + 4, 60)
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)
    print(body)
    print()


# ── Tool wrappers ───────────────────────────────────────────────────────────

async def list_tools(client: Client) -> None:
    """Print every tool the server exposes."""
    tools = await client.list_tools()
    _print_section(
        "Available MCP Tools",
        "\n".join(f"  • {t.name}: {t.description[:80]}..." if t.description and len(t.description) > 80
                  else f"  • {t.name}: {t.description or '(no description)'}"
                  for t in tools),
    )


async def list_agents(client: Client) -> str:
    """Call agents_list_agents and print the result."""
    result = await client.call_tool("agents_list_agents", {})
    text = _extract_text(result)
    _print_section("Agents", text)
    return text


async def list_workflows(client: Client) -> str:
    """Call workflows_list_sample_workflows and print the result."""
    result = await client.call_tool("workflows_list_sample_workflows", {})
    text = _extract_text(result)
    _print_section("Sample Workflows", text)
    return text


async def invoke_agent(client: Client, agent_id: str, task: str) -> str:
    """Invoke an agent, poll for completion, and return the result."""
    # Start invocation
    result = await client.call_tool(
        "agents_invoke_agent",
        {"agent_id": agent_id, "task": task},
    )
    text = _extract_text(result)
    _print_section("Invocation Started", text)

    # Extract invocation ID from the response
    inv_id = _extract_invocation_id(text)
    if not inv_id:
        print("⚠  Could not extract invocation ID – skipping polling.")
        return text

    # Poll for completion (max ~5 minutes)
    print(f"Polling invocation {inv_id} ...")
    final_text = await _poll_until_done(client, inv_id, timeout_seconds=300)
    return final_text


async def run_workflow(client: Client, story_url: str, project_name: str = "") -> str:
    """Run the project-log workflow end-to-end."""
    args: dict = {"story_url": story_url}
    if project_name:
        args["project_name"] = project_name

    result = await client.call_tool("workflows_run_project_log_workflow", args)
    text = _extract_text(result)
    _print_section("Workflow Result", text)
    return text


# ── Polling helper ──────────────────────────────────────────────────────────

async def _poll_until_done(client: Client, invocation_id: str, *, timeout_seconds: int = 300) -> str:
    """Poll agents_get_invocation_status until terminal, then fetch the result."""
    terminal_keywords = {"completed", "failed", "cancelled", "expired"}
    deadline = time.monotonic() + timeout_seconds
    interval = 3  # seconds between polls

    while time.monotonic() < deadline:
        status_result = await client.call_tool(
            "agents_get_invocation_status",
            {"invocation_id": invocation_id},
        )
        status_text = _extract_text(status_result)

        # Check if any terminal keyword appears in the status response
        status_lower = status_text.lower()
        if any(kw in status_lower for kw in terminal_keywords):
            _print_section("Invocation Status (final)", status_text)
            break

        print(f"  … still running (will retry in {interval}s)")
        await asyncio.sleep(interval)
    else:
        _print_section("Timeout", f"Invocation {invocation_id} did not complete within {timeout_seconds}s.")
        return f"Timed out waiting for {invocation_id}"

    # Fetch the actual result
    res = await client.call_tool(
        "agents_get_invocation_result",
        {"invocation_id": invocation_id},
    )
    text = _extract_text(res)
    _print_section("Invocation Result", text)
    return text


# ── Text extraction utilities ───────────────────────────────────────────────

def _extract_text(result) -> str:
    """Extract plain-text content from a call_tool result."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = []
        for item in result:
            if hasattr(item, "text"):
                parts.append(item.text)
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(result)


def _extract_invocation_id(text: str) -> str | None:
    """Try to pull the invocation ID out of the agents_invoke_agent response."""
    # The server returns a line like: - **Invocation ID**: `thread_xxx::run_xxx`
    for line in text.splitlines():
        if "invocation id" in line.lower():
            # Grab content between backticks
            if "`" in line:
                parts = line.split("`")
                if len(parts) >= 2:
                    return parts[1]
    return None


# ── Main entry point ────────────────────────────────────────────────────────

async def _async_main(args: argparse.Namespace) -> None:
    client = Client(_server_params())

    async with client:
        # Always show available tools first
        await list_tools(client)

        if args.list_agents:
            await list_agents(client)

        if args.list_workflows:
            await list_workflows(client)

        if args.invoke_agent:
            agent_id, task = args.invoke_agent
            await invoke_agent(client, agent_id, task)

        if args.run_workflow:
            await run_workflow(client, args.run_workflow, args.project_name or "")

        # Default: if no specific flag given, list agents and workflows
        if not any([args.list_agents, args.list_workflows, args.invoke_agent, args.run_workflow]):
            await list_agents(client)
            await list_workflows(client)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo MCP client for the foundry-agents-mcp-server",
    )
    parser.add_argument(
        "--list-agents",
        action="store_true",
        help="List all agents available in the Foundry project",
    )
    parser.add_argument(
        "--list-workflows",
        action="store_true",
        help="List built-in sample workflows",
    )
    parser.add_argument(
        "--invoke-agent",
        nargs=2,
        metavar=("AGENT_ID", "TASK"),
        help="Invoke an agent: provide agent ID and task text",
    )
    parser.add_argument(
        "--run-workflow",
        metavar="STORY_URL",
        help="Run the project-log workflow on a Microsoft customer story URL",
    )
    parser.add_argument(
        "--project-name",
        default="",
        help="Optional project name to tag the workflow log entry",
    )

    args = parser.parse_args()
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
