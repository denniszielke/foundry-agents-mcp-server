"""MCP tools for the **agents_*** namespace.

Covers the full Azure AI Foundry agent/workflow lifecycle:
list → invoke → poll status → retrieve results.
"""

import asyncio
import json
from typing import Optional

from foundry_agents_mcp.app import mcp
from foundry_agents_mcp.client import (
    _get_project_client,
    _make_invocation_id,
    _parse_invocation_id,
    logger,
)


@mcp.tool()
async def agents_list_agents() -> str:
    """List all available agents and workflows in the Azure AI Foundry project.

    Returns a formatted list of published agents including their IDs, models,
    descriptions, and available tools/capabilities.

    Example prompts:
    - "What agents are available in the project?"
    - "List all AI workflows I can invoke"
    - "Show me the agents and their capabilities in this Foundry project"
    """
    project_client = _get_project_client()
    if project_client is None:
        return (
            "Error: AZURE_AI_PROJECT_ENDPOINT is not configured. "
            "Set this environment variable to your Azure AI Foundry project endpoint."
        )

    try:
        agents = await asyncio.to_thread(lambda: list(project_client.agents.list_agents()))
        if not agents:
            return "No agents are currently available in the project."

        lines = ["## Available Agents and Workflows\n"]
        for agent in agents:
            lines.append(f"### {getattr(agent, 'name', None) or 'Unnamed Agent'}")
            lines.append(f"- **ID**: `{agent.id}`")
            lines.append(f"- **Model**: {getattr(agent, 'model', 'N/A')}")
            description = getattr(agent, "description", None)
            if description:
                lines.append(f"- **Description**: {description}")
            tools = getattr(agent, "tools", None) or []
            if tools:
                tool_types = [getattr(t, "type", str(t)) for t in tools]
                lines.append(f"- **Tools**: {', '.join(tool_types)}")
            metadata = getattr(agent, "metadata", None) or {}
            if metadata:
                lines.append(f"- **Metadata**: {json.dumps(metadata)}")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        logger.exception("agents_list_agents failed")
        return f"Error listing agents: {exc}"


@mcp.tool()
async def agents_invoke_agent(
    agent_id: str,
    task: str,
    file_context: Optional[str] = None,
) -> str:
    """Invoke an agent or workflow with a task and optional context.

    Creates a new conversation thread, submits the task, and returns an
    invocation ID that can be used with agents_get_invocation_status and
    agents_get_invocation_result.

    Args:
        agent_id: The ID of the agent or workflow to invoke (from agents_list_agents).
        task: The task description or question to send to the agent.
        file_context: Optional additional text or file content to include as context.

    Example prompts:
    - "Ask agent <agent_id> to summarize the latest Azure AI announcements"
    - "Invoke the research workflow with task: analyze competitive landscape for AI"
    - "Send this document to the analysis agent and include the file text as context"
    """
    project_client = _get_project_client()
    if project_client is None:
        return "Error: AZURE_AI_PROJECT_ENDPOINT is not configured."

    try:
        from azure.ai.agents.models import (  # noqa: PLC0415
            AgentThreadCreationOptions,
            ThreadMessageOptions,
        )

        content = task
        if file_context:
            content = f"{task}\n\nAdditional context:\n{file_context}"

        thread_run = await asyncio.to_thread(
            lambda: project_client.agents.create_thread_and_run(
                agent_id=agent_id,
                thread=AgentThreadCreationOptions(
                    messages=[ThreadMessageOptions(role="user", content=content)]
                ),
            )
        )

        inv_id = _make_invocation_id(thread_run.thread_id, thread_run.id)
        return (
            "Agent invocation started.\n"
            f"- **Invocation ID**: `{inv_id}`\n"
            f"- **Status**: {thread_run.status}\n\n"
            "Use `agents_get_invocation_status` to check progress and "
            "`agents_get_invocation_result` to retrieve results."
        )

    except Exception as exc:
        logger.exception("agents_invoke_agent failed")
        return f"Error invoking agent '{agent_id}': {exc}"


@mcp.tool()
async def agents_get_invocation_status(invocation_id: str) -> str:
    """Check the status of an agent or workflow invocation.

    Args:
        invocation_id: The invocation ID returned by agents_invoke_agent.

    Returns the current run status: queued, in_progress, requires_action,
    cancelling, cancelled, failed, completed, or expired.

    Example prompts:
    - "Check the status of invocation <invocation_id>"
    - "Has my agent task finished? ID: <invocation_id>"
    - "Is the workflow still running for invocation <invocation_id>?"
    """
    project_client = _get_project_client()
    if project_client is None:
        return "Error: AZURE_AI_PROJECT_ENDPOINT is not configured."

    try:
        thread_id, run_id = _parse_invocation_id(invocation_id)
    except ValueError as exc:
        return str(exc)

    try:
        run = await asyncio.to_thread(
            lambda: project_client.agents.get_run(thread_id=thread_id, run_id=run_id)
        )

        lines = [
            "## Invocation Status\n",
            f"- **Invocation ID**: `{invocation_id}`",
            f"- **Status**: {run.status}",
        ]
        if getattr(run, "started_at", None):
            lines.append(f"- **Started At**: {run.started_at}")
        if getattr(run, "completed_at", None):
            lines.append(f"- **Completed At**: {run.completed_at}")
        if getattr(run, "last_error", None):
            lines.append(f"- **Error**: {run.last_error}")

        terminal = {"completed", "failed", "cancelled", "expired"}
        if str(run.status) in terminal:
            lines.append(
                "\nInvocation has finished. "
                "Use `agents_get_invocation_result` to retrieve results."
            )
        else:
            lines.append("\nInvocation is still running. Check again later.")

        return "\n".join(lines)

    except Exception as exc:
        logger.exception("agents_get_invocation_status failed")
        return f"Error getting status for '{invocation_id}': {exc}"


@mcp.tool()
async def agents_get_invocation_result(invocation_id: str) -> str:
    """Retrieve the text or file results from a completed agent or workflow invocation.

    Args:
        invocation_id: The invocation ID returned by agents_invoke_agent.

    Returns the assistant's response messages and any file output references.

    Example prompts:
    - "Get the results from invocation <invocation_id>"
    - "What did the agent return for ID <invocation_id>?"
    - "Show me the output of the completed workflow: <invocation_id>"
    """
    project_client = _get_project_client()
    if project_client is None:
        return "Error: AZURE_AI_PROJECT_ENDPOINT is not configured."

    try:
        thread_id, run_id = _parse_invocation_id(invocation_id)
    except ValueError as exc:
        return str(exc)

    try:
        run = await asyncio.to_thread(
            lambda: project_client.agents.get_run(thread_id=thread_id, run_id=run_id)
        )

        status = str(run.status)
        terminal = {"completed", "failed", "cancelled", "expired"}
        if status not in terminal:
            return (
                f"Invocation is not complete yet. Current status: **{status}**\n"
                "Use `agents_get_invocation_status` to monitor progress."
            )

        if status == "failed":
            err = getattr(run, "last_error", None)
            msg = getattr(err, "message", str(err)) if err else "Unknown error"
            return f"Invocation **failed**: {msg}"

        if status in ("cancelled", "expired"):
            return f"Invocation was **{status}**."

        from azure.ai.agents.models import ListSortOrder  # noqa: PLC0415

        messages = await asyncio.to_thread(
            lambda: project_client.agents.list_messages(
                thread_id=thread_id,
                order=ListSortOrder.DESCENDING,
            )
        )

        lines = [
            "## Invocation Result\n",
            f"- **Invocation ID**: `{invocation_id}`\n",
            "### Response\n",
        ]

        found = False
        for msg in messages:
            if str(getattr(msg, "role", "")) == "assistant":
                found = True
                for part in getattr(msg, "content", []):
                    text_obj = getattr(part, "text", None)
                    if text_obj is not None:
                        lines.append(getattr(text_obj, "value", str(text_obj)))
                    image_obj = getattr(part, "image_file", None)
                    if image_obj is not None:
                        file_id = getattr(image_obj, "file_id", "unknown")
                        lines.append(f"[Image file: {file_id}]")
                break  # most recent assistant message only

        if not found:
            lines.append("No assistant response found.")

        return "\n".join(lines)

    except Exception as exc:
        logger.exception("agents_get_invocation_result failed")
        return f"Error retrieving result for '{invocation_id}': {exc}"
