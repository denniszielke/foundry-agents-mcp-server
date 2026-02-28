"""CaseStudyAgent – Azure AI Foundry deployment and runtime.

Deployment (registers the agent in your Foundry project)::

    deploy-case-study-agent

The deployed agent will then appear in ``agents_list_agents`` output from the
MCP server and can be invoked directly with ``agents_invoke_agent``.

Runtime (used internally by :mod:`foundry_agents.project_log_workflow`)::

    result = await run(page_text, reference_url)
    # → {"title": ..., "customer_name": ..., "short_summary": ...,
    #    "context": ..., "tags": [...], "reference_url": ...}

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

AGENT_NAME = "CaseStudyAgent"
AGENT_DESCRIPTION = (
    "Extracts structured metadata from Microsoft customer success story text "
    "and returns a JSON object ready for ingestion into the project-log index."
)

INSTRUCTIONS = """\
You extract structured information from Microsoft customer success story text.
When given the text content of a customer story page, extract and return ONLY
a valid JSON object with these fields:
{
  "title": "<story title>",
  "customer_name": "<customer organization name>",
  "short_summary": "<1–2 sentence summary of the project>",
  "context": "<200–400 word description: challenges faced, Azure solution adopted, and measurable outcomes>",
  "tags": ["<Azure service or technology>", ...],
  "reference_url": "<original URL if mentioned or provided, else empty string>"
}
Be factual and precise. Return ONLY the JSON object with no markdown fences,
no explanations, and no extra text.
"""


# ── Deploy ────────────────────────────────────────────────────────────────────

async def deploy(project_client=None) -> str:
    """Create or update ``CaseStudyAgent`` in Azure AI Foundry.

    Returns the agent ID.  If an agent with this name already exists it is
    updated in-place so re-running the deploy command is idempotent.
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
    page_text: str,
    reference_url: str = "",
    *,
    project_client=None,
    chat_client=None,
) -> dict:
    """Extract structured metadata from *page_text*.

    Tries the deployed Foundry agent first; falls back to a direct
    Azure OpenAI inference call if no deployed agent is found.

    Returns a ``dict`` with keys: ``title``, ``customer_name``,
    ``short_summary``, ``context``, ``tags``, ``reference_url``.
    """
    user_message = (
        f"Reference URL: {reference_url}\n\nPage content:\n{page_text}"
    )

    # ── Try deployed Foundry agent ────────────────────────────────────────────
    pc = project_client or get_project_client()
    if pc is not None:
        foundry_agent = await find_agent_by_name(pc, AGENT_NAME)
        if foundry_agent:
            logger.info("Using deployed Foundry agent %s (%s)", AGENT_NAME, foundry_agent.id)
            raw = await invoke_and_wait(pc, foundry_agent.id, user_message)
            return json.loads(raw)

    # ── Fallback: direct Azure OpenAI inference ────────────────────────────────
    cc = chat_client or get_chat_client()
    if cc is None:
        raise RuntimeError(
            f"'{AGENT_NAME}' is not deployed and AZURE_OPENAI_COMPLETION_MODEL_NAME "
            "is not configured. Deploy the agent first with `deploy-case-study-agent`."
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
            temperature=0.1,
        )
    )
    return json.loads(response.choices[0].message.content or "{}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def deploy_cmd() -> None:
    """Entry point for the ``deploy-case-study-agent`` CLI command."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="deploy-case-study-agent",
        description=(
            "Deploy the CaseStudyAgent to your Azure AI Foundry project.\n\n"
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
