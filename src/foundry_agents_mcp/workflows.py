"""MCP tools for the **workflows_*** namespace.

Provides two sample workflows that demonstrate sequential agent orchestration
using declaratively-defined Azure AI Foundry agents:

1. **CaseStudyAgent** – fetches a Microsoft customer story page and extracts
   structured metadata (title, customer, summary, context, tags, URL).
2. **ArchitectureAgent** – generates a JSON architecture diagram from a project
   description.
3. **Project-log workflow** – runs both agents in order and stores the combined
   result in the Azure AI Search vector index.

The agent definitions live in ``src/foundry_agents_mcp/agents/`` as YAML files
using the ``kind: Prompt`` declarative format compatible with the
``agent-framework-declarative`` package.  The workflow orchestration is
implemented here in Python so it works without that optional package: it uses
``AzureOpenAI.chat.completions`` (via the shared chat client) with the same
system instructions as the YAML files.
"""

import asyncio
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

import httpx

from foundry_agents_mcp.app import mcp
from foundry_agents_mcp.client import (
    AZURE_OPENAI_COMPLETION_MODEL_NAME,
    _get_chat_client,
    logger,
)
from foundry_agents_mcp.index import _ingest_project_log_doc

# ── Agent instruction constants (mirrors the YAML definitions) ─────────────────

_CASE_STUDY_INSTRUCTIONS = """\
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

_ARCHITECTURE_INSTRUCTIONS = """\
You are a cloud solution architect. When given a project title, customer name,
context description, and list of technology tags, generate a structured JSON
representation of the solution architecture following this exact schema:
{
  "diagram_type": "solution_architecture",
  "components": [
    {"name": "<component name>", "type": "<Azure service type>", "description": "<what it does in the solution>"}
  ],
  "connections": [
    {"from": "<component A name>", "to": "<component B name>", "description": "<data or control flow>"}
  ],
  "patterns": ["<architectural pattern>", ...]
}
Derive the components and connections from the context description and tags.
Return ONLY the JSON object with no markdown fences, no explanations, and no
extra text.
"""

# ── HTML text extractor ────────────────────────────────────────────────────────

_SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "head", "header", "noscript"})


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text converter that strips noise tags."""

    def __init__(self) -> None:
        super().__init__()
        self._texts: list[str] = []
        self._depth: int = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TAGS and self._depth > 0:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth == 0 and data.strip():
            self._texts.append(data.strip())

    def get_text(self) -> str:
        # Collapse repeated whitespace and join paragraphs
        return re.sub(r"\s{3,}", "\n\n", " ".join(self._texts))


def _extract_text(html: str, max_chars: int = 12_000) -> str:
    """Return visible text from an HTML page, truncated to *max_chars*."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.get_text()[:max_chars]


# ── HTTP fetch ────────────────────────────────────────────────────────────────

async def _fetch_page_text(url: str) -> str:
    """Fetch the visible text content from a web page."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; FoundryAgentsMCPServer/1.0; "
            "+https://github.com/denniszielke/foundry-agents-mcp-server)"
        )
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    return _extract_text(response.text)


# ── Inference helper ──────────────────────────────────────────────────────────

async def _run_chat_agent(system_instructions: str, user_message: str) -> str:
    """Call the Azure OpenAI chat completions endpoint in JSON mode."""
    chat_client = _get_chat_client()
    if chat_client is None:
        raise RuntimeError(
            "AZURE_OPENAI_COMPLETION_MODEL_NAME is not configured. "
            "Set this environment variable to your chat model deployment name."
        )

    response = await asyncio.to_thread(
        lambda: chat_client.chat.completions.create(
            model=AZURE_OPENAI_COMPLETION_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
    )
    return response.choices[0].message.content or ""


# ── MCP tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
async def workflows_list_sample_workflows() -> str:
    """List the available sample workflow and agent definitions.

    Returns the names and descriptions of the built-in declarative workflow
    and agent YAML files, which can be used as templates for deploying agents
    to Azure AI Foundry.

    Example prompts:
    - "What sample workflows are available?"
    - "Show me the built-in workflow definitions"
    - "List the declarative agent templates"
    """
    agents_dir = Path(__file__).parent / "agents"
    workflows_dir = Path(__file__).parent / "workflows"

    lines = ["## Sample Workflow and Agent Definitions\n"]

    lines.append("### Declarative Agent YAML Files\n")
    lines.append(
        "These files use the `kind: Prompt` format compatible with "
        "`agent-framework-declarative`. They can be loaded with "
        "`AgentFactory().create_agent_from_yaml_path(path)` or deployed to "
        "Azure AI Foundry.\n"
    )
    for yaml_file in sorted(agents_dir.glob("*.yaml")):
        lines.append(f"- **{yaml_file.name}** (`{yaml_file}`)")
    lines.append("")

    lines.append("### Workflow YAML Files\n")
    lines.append(
        "These files use the `kind: Workflow` format for declarative "
        "multi-agent workflow orchestration.\n"
    )
    for yaml_file in sorted(workflows_dir.glob("*.yaml")):
        lines.append(f"- **{yaml_file.name}** (`{yaml_file}`)")
    lines.append("")

    lines.append("### Python Workflow Tools\n")
    lines.append(
        "- **`workflows_run_project_log_workflow`** – "
        "Fetch a Microsoft customer story → extract metadata (CaseStudyAgent) → "
        "generate architecture JSON (ArchitectureAgent) → store in vector DB."
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

    Args:
        story_url: URL of a Microsoft customer success story, e.g.
            https://www.microsoft.com/en/customers/story/25676-commerzbank-ag-azure-ai-foundry-agent-service
        project_name: Optional project name to tag the log entry with.

    Example prompts:
    - "Run the project log workflow for https://www.microsoft.com/en/customers/story/..."
    - "Index this customer story and generate its architecture: <url>"
    - "Ingest the Commerzbank case study into the project log"
    """
    lines: list[str] = ["## Project-Log Workflow\n"]

    # ── Step 1: Fetch the customer story page ─────────────────────────────────
    lines.append("### Step 1: Fetching customer story page…\n")
    try:
        page_text = await _fetch_page_text(story_url)
    except Exception as exc:
        logger.exception("workflows_run_project_log_workflow – page fetch failed")
        return "\n".join(lines) + f"\n❌ Failed to fetch `{story_url}`: {exc}"

    lines.append(f"Fetched {len(page_text):,} characters from `{story_url}`.\n")

    # ── Step 2: CaseStudyAgent – extract structured metadata ─────────────────
    lines.append("### Step 2: CaseStudyAgent – extracting metadata…\n")
    user_msg = (
        f"Reference URL: {story_url}\n\n"
        f"Page content:\n{page_text}"
    )
    try:
        case_study_json = await _run_chat_agent(_CASE_STUDY_INSTRUCTIONS, user_msg)
        case_study = json.loads(case_study_json)
    except Exception as exc:
        logger.exception("workflows_run_project_log_workflow – CaseStudyAgent failed")
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

    # ── Step 3: ArchitectureAgent – generate architecture diagram ─────────────
    lines.append("### Step 3: ArchitectureAgent – generating architecture diagram…\n")
    arch_user_msg = (
        f"Title: {title}\n"
        f"Customer: {customer_name}\n"
        f"Technologies: {', '.join(tags)}\n\n"
        f"Context:\n{context}"
    )
    try:
        architecture_json = await _run_chat_agent(_ARCHITECTURE_INSTRUCTIONS, arch_user_msg)
        # Validate it is parseable JSON before storing
        json.loads(architecture_json)
    except Exception as exc:
        logger.exception("workflows_run_project_log_workflow – ArchitectureAgent failed")
        architecture_json = json.dumps({"error": str(exc)})
        lines.append(f"⚠️ Architecture generation failed: {exc}. Storing empty diagram.\n")
    else:
        arch_data = json.loads(architecture_json)
        component_names = [c.get("name", "") for c in arch_data.get("components", [])]
        lines.append(f"- **Components** ({len(component_names)}): {', '.join(component_names[:6])}")
        lines.append(
            f"- **Patterns**: {', '.join(arch_data.get('patterns', []))}\n"
        )

    # ── Step 4: Ingest combined entry into the vector index ───────────────────
    lines.append("### Step 4: Ingesting into project-log vector index…\n")
    try:
        ingest_result = await _ingest_project_log_doc(
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
        logger.exception("workflows_run_project_log_workflow – ingestion failed")
        return "\n".join(lines) + f"\n❌ Ingestion failed: {exc}"

    lines.append(ingest_result)
    lines.append("\n✅ Project-log workflow completed successfully.")
    return "\n".join(lines)
