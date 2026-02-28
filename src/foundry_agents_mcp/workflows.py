"""MCP tools for the **workflows_*** namespace.

This module is an intentionally thin wrapper.  All business logic lives in the
``foundry_agents`` package (``src/foundry_agents/``), which can also be used
standalone from the command line.

Agent lookup strategy
---------------------
The :func:`workflows_run_project_log_workflow` tool first checks whether
``CaseStudyAgent`` and ``ArchitectureAgent`` have been deployed to the
configured Azure AI Foundry project.  If they are present they are invoked via
the Foundry API; otherwise the tool falls back to direct Azure OpenAI
inference using the same instructions.  This means the workflow works with or
without prior deployment of the sample agents.

Deployment commands
-------------------
``deploy-case-study-agent``     – register CaseStudyAgent in Foundry
``deploy-architecture-agent``   – register ArchitectureAgent in Foundry
``run-project-log-workflow``    – run the pipeline from the CLI
"""

from pathlib import Path

from foundry_agents import DEFINITIONS_DIR
from foundry_agents.project_log_workflow import run_pipeline

from foundry_agents_mcp.app import mcp
from foundry_agents_mcp.client import logger


@mcp.tool()
async def workflows_list_sample_workflows() -> str:
    """List the available sample workflow and agent definitions.

    Returns the names, locations, and descriptions of the built-in declarative
    YAML files in ``src/foundry_agents/definitions/`` and the available CLI
    deployment/run commands.

    Example prompts:
    - "What sample workflows are available?"
    - "Show me the built-in workflow definitions"
    - "List the declarative agent templates I can deploy to Foundry"
    """
    lines = ["## Sample Workflow and Agent Definitions\n"]

    lines.append("### Declarative YAML definitions (`src/foundry_agents/definitions/`)\n")
    lines.append(
        "These files use the Microsoft Agent Framework declarative format.\n"
        "- `kind: Prompt` files define individual agents.\n"
        "- `kind: Workflow` files describe multi-agent pipelines.\n"
    )
    for yaml_file in sorted(DEFINITIONS_DIR.glob("*.yaml")):
        lines.append(f"- **{yaml_file.name}**")
    lines.append("")

    lines.append("### CLI commands\n")
    lines.append(
        "| Command | Description |\n"
        "|---------|-------------|\n"
        "| `deploy-case-study-agent` | Register **CaseStudyAgent** in Azure AI Foundry |\n"
        "| `deploy-architecture-agent` | Register **ArchitectureAgent** in Azure AI Foundry |\n"
        "| `run-project-log-workflow --url <url>` | Run the full pipeline from the command line |\n"
    )

    lines.append("### MCP tool\n")
    lines.append(
        "- **`workflows_run_project_log_workflow`** – "
        "Fetch a Microsoft customer story → CaseStudyAgent → "
        "ArchitectureAgent → store in vector DB.  "
        "Uses deployed Foundry agents when available, falls back to "
        "direct inference otherwise."
    )

    return "\n".join(lines)


@mcp.tool()
async def workflows_run_project_log_workflow(
    story_url: str,
    project_name: str = "",
) -> str:
    """Run the full project-log ingestion workflow for a Microsoft customer story.

    This workflow sequentially invokes two declarative agents:

    1. **CaseStudyAgent** – fetches the story page and extracts:
       title, customer name, summary, context, tags, and the source URL.
    2. **ArchitectureAgent** – generates a structured JSON architecture
       diagram from the case study context and technology tags.

    The combined result is stored as a single entry in the Azure AI Search
    project-log vector index.

    If ``CaseStudyAgent`` and ``ArchitectureAgent`` have been deployed to
    Azure AI Foundry (via ``deploy-case-study-agent`` /
    ``deploy-architecture-agent``), they are invoked via the Foundry API so
    that the run is visible in the project telemetry.  Otherwise the same
    logic runs locally against Azure OpenAI directly.

    Args:
        story_url: URL of a Microsoft customer success story, e.g.
            https://www.microsoft.com/en/customers/story/25676-commerzbank-ag-azure-ai-foundry-agent-service
        project_name: Optional project name to tag the log entry with.

    Example prompts:
    - "Run the project log workflow for https://www.microsoft.com/en/customers/story/..."
    - "Index this customer story and generate its architecture: <url>"
    - "Ingest the Commerzbank case study into the project log"
    """
    try:
        return await run_pipeline(story_url, project_name)
    except Exception as exc:
        logger.exception("workflows_run_project_log_workflow failed")
        return f"❌ Workflow failed: {exc}"

