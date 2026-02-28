"""ArchitectureAgent – Azure AI Foundry deployment and runtime.

Deployment (registers the agent in your Foundry project)::

    deploy-architecture-agent

The deployed agent will then appear in ``agents_list_agents`` output from the
MCP server and can be invoked directly with ``agents_invoke_agent``.

Runtime (used internally by :mod:`foundry_agents.project_log_workflow`)::

    architecture_json = await run(title, customer_name, context, tags)
    # → JSON string describing solution components, connections, and patterns

The ``run`` function prefers a **deployed Foundry agent** if one exists;
otherwise it falls back to a direct Azure OpenAI chat-completion call.
"""

import asyncio
import json
import logging
import os
import sys

from foundry_agents._client import (
    AZURE_OPENAI_COMPLETION_MODEL_NAME,
    get_chat_client,
    get_project_client,
)
from foundry_agents._foundry import find_agent_by_name, invoke_and_wait

logger = logging.getLogger("foundry-agents")

# ── Agent identity ─────────────────────────────────────────────────────────────

AGENT_NAME = "ArchitectureAgent"
AGENT_DESCRIPTION = (
    "Generates a structured JSON representation of a solution architecture "
    "from a project description, customer name, and list of Azure technologies."
)

INSTRUCTIONS = """\
You are a cloud solution architect. When given a project title, customer name,
context description, and list of technology tags, generate a structured JSON
representation of the solution architecture following this exact schema:
{
  "diagram_type": "solution_architecture",
  "components": [
    {
      "name": "<component name>",
      "type": "<Azure service type>",
      "description": "<what it does in the solution>"
    }
  ],
  "connections": [
    {
      "from": "<component A name>",
      "to": "<component B name>",
      "description": "<data or control flow description>"
    }
  ],
  "patterns": ["<architectural pattern>", ...]
}
Derive the components and connections from the context description and tags.
Each component should correspond to a real Azure service or architectural
building block mentioned or implied by the project context.
Return ONLY the JSON object with no markdown fences, no explanations, and no
extra text.
"""


# ── Deploy ────────────────────────────────────────────────────────────────────

async def deploy(project_client=None) -> str:
    """Create or update ``ArchitectureAgent`` in Azure AI Foundry.

    Returns the agent ID.  Idempotent – re-running updates the existing agent.
    """
    pc = project_client or get_project_client()
    if pc is None:
        raise RuntimeError(
            "AZURE_AI_PROJECT_ENDPOINT is not configured. "
            "Set this environment variable before deploying."
        )

    model = AZURE_OPENAI_COMPLETION_MODEL_NAME or os.getenv("AZURE_OPENAI_COMPLETION_MODEL_NAME", "")
    if not model:
        raise RuntimeError(
            "AZURE_OPENAI_COMPLETION_MODEL_NAME is not configured. "
            "Set this environment variable to your chat model deployment name."
        )

    existing = await find_agent_by_name(pc, AGENT_NAME)

    if existing:
        agent = await asyncio.to_thread(
            lambda: pc.agents.update_agent(
                assistant_id=existing.id,
                model=model,
                name=AGENT_NAME,
                description=AGENT_DESCRIPTION,
                instructions=INSTRUCTIONS,
            )
        )
        print(f"Updated {AGENT_NAME} (ID: {agent.id})")
    else:
        agent = await asyncio.to_thread(
            lambda: pc.agents.create_agent(
                model=model,
                name=AGENT_NAME,
                description=AGENT_DESCRIPTION,
                instructions=INSTRUCTIONS,
            )
        )
        print(f"Created {AGENT_NAME} (ID: {agent.id})")

    return agent.id


# ── Run ───────────────────────────────────────────────────────────────────────

async def run(
    title: str,
    customer_name: str,
    context: str,
    tags: list[str],
    *,
    project_client=None,
    chat_client=None,
) -> str:
    """Generate a JSON architecture diagram for the given project details.

    Tries the deployed Foundry agent first; falls back to a direct
    Azure OpenAI inference call if no deployed agent is found.

    Returns a JSON *string* (not a dict) suitable for storage in the
    ``architecture`` field of the project-log index.
    """
    user_message = (
        f"Title: {title}\n"
        f"Customer: {customer_name}\n"
        f"Technologies: {', '.join(tags)}\n\n"
        f"Context:\n{context}"
    )

    # ── Try deployed Foundry agent ────────────────────────────────────────────
    pc = project_client or get_project_client()
    if pc is not None:
        foundry_agent = await find_agent_by_name(pc, AGENT_NAME)
        if foundry_agent:
            logger.info("Using deployed Foundry agent %s (%s)", AGENT_NAME, foundry_agent.id)
            raw = await invoke_and_wait(pc, foundry_agent.id, user_message)
            # Validate JSON before returning
            json.loads(raw)
            return raw

    # ── Fallback: direct Azure OpenAI inference ────────────────────────────────
    cc = chat_client or get_chat_client()
    if cc is None:
        raise RuntimeError(
            f"'{AGENT_NAME}' is not deployed and AZURE_OPENAI_COMPLETION_MODEL_NAME "
            "is not configured. Deploy the agent first with `deploy-architecture-agent`."
        )

    logger.info("Deployed agent not found; using direct inference for %s", AGENT_NAME)
    response = await asyncio.to_thread(
        lambda: cc.chat.completions.create(
            model=AZURE_OPENAI_COMPLETION_MODEL_NAME,
            messages=[
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
    )
    raw = response.choices[0].message.content or "{}"
    json.loads(raw)  # validate
    return raw


# ── CLI entry point ───────────────────────────────────────────────────────────

def deploy_cmd() -> None:
    """Entry point for the ``deploy-architecture-agent`` CLI command."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="deploy-architecture-agent",
        description=(
            "Deploy the ArchitectureAgent to your Azure AI Foundry project.\n\n"
            "Required env vars: AZURE_AI_PROJECT_ENDPOINT, "
            "AZURE_OPENAI_COMPLETION_MODEL_NAME"
        ),
    )
    parser.parse_args()

    try:
        agent_id = asyncio.run(deploy())
        print(f"\nAgent ID: {agent_id}")
        print(
            "\nThe agent is now available in your Foundry project.\n"
            "Use `agents_list_agents` in the MCP server to verify."
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
