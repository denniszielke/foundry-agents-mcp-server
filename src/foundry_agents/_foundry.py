"""Azure AI Foundry helpers: look up agents by name and invoke them synchronously.

These utilities are shared by ``case_study_agent``, ``architecture_agent``, and
``project_log_workflow`` so they can take advantage of deployed Foundry agents
when available.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("foundry-agents")

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}
_POLL_INTERVAL_SECS = 2


def find_agent_by_name_sync(project_client, name: str):
    """Return the first agent in the project whose name matches *name*, or None."""
    agents = list(project_client.agents.list_agents())
    return next(
        (a for a in agents if getattr(a, "name", None) == name),
        None,
    )


async def find_agent_by_name(project_client, name: str):
    """Async wrapper around :func:`find_agent_by_name_sync`."""
    return await asyncio.to_thread(find_agent_by_name_sync, project_client, name)


async def invoke_and_wait(
    project_client,
    agent_id: str,
    user_message: str,
) -> str:
    """Create a thread-and-run, poll until terminal, and return the assistant's reply.

    Raises ``RuntimeError`` if the run ends in a non-completed state.
    """
    from azure.ai.agents.models import (  # noqa: PLC0415
        AgentThreadCreationOptions,
        ListSortOrder,
        ThreadMessageOptions,
    )

    thread_run = await asyncio.to_thread(
        lambda: project_client.agents.create_thread_and_run(
            agent_id=agent_id,
            thread=AgentThreadCreationOptions(
                messages=[ThreadMessageOptions(role="user", content=user_message)]
            ),
        )
    )

    thread_id = thread_run.thread_id
    run_id = thread_run.id

    # Poll until the run reaches a terminal status
    while True:
        run = await asyncio.to_thread(
            lambda: project_client.agents.get_run(thread_id=thread_id, run_id=run_id)
        )
        status = str(run.status)
        if status in _TERMINAL_STATUSES:
            break
        await asyncio.sleep(_POLL_INTERVAL_SECS)

    if status != "completed":
        err = getattr(run, "last_error", None)
        msg = getattr(err, "message", str(err)) if err else "unknown error"
        raise RuntimeError(f"Agent run ended with status '{status}': {msg}")

    # Retrieve the most recent assistant message
    messages = await asyncio.to_thread(
        lambda: project_client.agents.list_messages(
            thread_id=thread_id,
            order=ListSortOrder.DESCENDING,
        )
    )
    for msg in messages:
        if str(getattr(msg, "role", "")) == "assistant":
            for part in getattr(msg, "content", []):
                text_obj = getattr(part, "text", None)
                if text_obj is not None:
                    return getattr(text_obj, "value", str(text_obj))

    return ""
