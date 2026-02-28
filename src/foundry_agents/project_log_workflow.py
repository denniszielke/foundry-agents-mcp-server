"""ProjectLogWorkflow – the full two-agent pipeline.

Run from the command line::

    run-project-log-workflow --url <story_url> [--project <project_name>]

Or call :func:`run_pipeline` directly from Python (e.g. from the MCP server's
``workflows_run_project_log_workflow`` tool).

Pipeline
--------
1. **Fetch** – Download and extract text from the customer story URL.
2. **CaseStudyAgent** – Extract structured metadata (title, customer, summary,
   context, tags, URL).  Uses the deployed Foundry agent when available;
   falls back to direct Azure OpenAI inference.
3. **ArchitectureAgent** – Generate a JSON architecture diagram from the case
   study context and technology tags.  Same fallback logic.
4. **Ingest** – Upload the combined entry to the Azure AI Search project-log
   index (auto-creates the index if needed).
"""

import asyncio
import json
import logging
import sys
from typing import Optional

from foundry_agents._html import fetch_page_text
from foundry_agents._ingest import ingest_document
from foundry_agents.architecture_agent import run as run_architecture
from foundry_agents.case_study_agent import run as run_case_study

logger = logging.getLogger("foundry-agents")


async def run_pipeline(
    story_url: str,
    project_name: str = "",
    *,
    project_client=None,
    chat_client=None,
) -> str:
    """Execute the full project-log ingestion pipeline.

    Parameters
    ----------
    story_url:
        URL of a Microsoft customer success story page.
    project_name:
        Optional project name to tag the log entry with.
    project_client:
        Pre-constructed ``AIProjectClient``; created from env vars if omitted.
    chat_client:
        Pre-constructed ``AzureOpenAI`` chat client; created from env vars if
        omitted (used for the direct-inference fallback path).

    Returns
    -------
    str
        A multi-line Markdown-formatted status string suitable for CLI output
        or as the return value of an MCP tool.
    """
    lines: list[str] = ["## Project-Log Workflow\n"]

    # ── Step 1: Fetch page ────────────────────────────────────────────────────
    lines.append("### Step 1: Fetching customer story page…\n")
    try:
        page_text = await fetch_page_text(story_url)
    except Exception as exc:
        logger.exception("run_pipeline – page fetch failed")
        return "\n".join(lines) + f"\n❌ Failed to fetch `{story_url}`: {exc}"

    lines.append(f"Fetched {len(page_text):,} characters from `{story_url}`.\n")

    # ── Step 2: CaseStudyAgent ────────────────────────────────────────────────
    lines.append("### Step 2: CaseStudyAgent – extracting metadata…\n")
    try:
        case_study = await run_case_study(
            page_text,
            story_url,
            project_client=project_client,
            chat_client=chat_client,
        )
    except Exception as exc:
        logger.exception("run_pipeline – CaseStudyAgent failed")
        return "\n".join(lines) + f"\n❌ CaseStudyAgent failed: {exc}"

    title: str = case_study.get("title", "Untitled Customer Story")
    customer_name: str = case_study.get("customer_name", "")
    short_summary: str = case_study.get("short_summary", "")
    context: str = case_study.get("context", "")
    tags: list[str] = case_study.get("tags", [])
    reference_url: str = case_study.get("reference_url", story_url) or story_url

    lines.append(f"- **Title**: {title}")
    lines.append(f"- **Customer**: {customer_name}")
    lines.append(f"- **Tags**: {', '.join(tags)}")
    lines.append(f"- **Summary**: {short_summary}\n")

    # ── Step 3: ArchitectureAgent ─────────────────────────────────────────────
    lines.append("### Step 3: ArchitectureAgent – generating architecture diagram…\n")
    try:
        architecture_json = await run_architecture(
            title,
            customer_name,
            context,
            tags,
            project_client=project_client,
            chat_client=chat_client,
        )
        arch_data = json.loads(architecture_json)
        component_names = [c.get("name", "") for c in arch_data.get("components", [])]
        lines.append(f"- **Components** ({len(component_names)}): {', '.join(component_names[:6])}")
        lines.append(f"- **Patterns**: {', '.join(arch_data.get('patterns', []))}\n")
    except Exception as exc:
        logger.exception("run_pipeline – ArchitectureAgent failed")
        architecture_json = json.dumps({"error": str(exc)})
        lines.append(f"⚠️ Architecture generation failed: {exc}. Storing empty diagram.\n")

    # ── Step 4: Ingest ────────────────────────────────────────────────────────
    lines.append("### Step 4: Ingesting into project-log vector index…\n")
    try:
        doc_id = await ingest_document(
            title=title,
            entry_type="blog",
            customer_name=customer_name,
            short_summary=short_summary,
            context=context,
            project_name=project_name,
            tags=tags,
            reference_url=reference_url,
            architecture=architecture_json,
        )
    except Exception as exc:
        logger.exception("run_pipeline – ingestion failed")
        return "\n".join(lines) + f"\n❌ Ingestion failed: {exc}"

    lines.append(
        "Project log ingested successfully.\n"
        f"- **ID**: `{doc_id}`\n"
        f"- **Title**: {title}\n"
        f"- **Customer**: {customer_name}"
    )
    lines.append("\n✅ Project-log workflow completed successfully.")
    return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────────────────────────

def run_cmd() -> None:
    """Entry point for the ``run-project-log-workflow`` CLI command."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="run-project-log-workflow",
        description=(
            "Fetch a Microsoft customer story, extract metadata, generate an "
            "architecture diagram, and store the result in the project-log "
            "Azure AI Search index.\n\n"
            "The two agents (CaseStudyAgent, ArchitectureAgent) are used from "
            "Azure AI Foundry if already deployed; otherwise direct Azure OpenAI "
            "inference is used as a fallback.\n\n"
            "Required env vars: AZURE_OPENAI_COMPLETION_MODEL_NAME, "
            "AZURE_AI_SEARCH_ENDPOINT, AZURE_OPENAI_ENDPOINT (or "
            "AZURE_AI_PROJECT_ENDPOINT)"
        ),
    )
    parser.add_argument(
        "--url",
        required=True,
        metavar="URL",
        help=(
            "URL of a Microsoft customer success story, e.g. "
            "https://www.microsoft.com/en/customers/story/25676-commerzbank-ag-azure-ai-foundry-agent-service"
        ),
    )
    parser.add_argument(
        "--project",
        default="",
        metavar="NAME",
        help="Optional project name to tag the log entry with.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            stream=sys.stderr,
        )

    try:
        result = asyncio.run(run_pipeline(args.url, args.project))
        print(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
