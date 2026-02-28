"""Foundry Agents MCP Server

Provides MCP tools organized into three namespaces:

- **agents_***: List and invoke Azure AI Foundry agents/workflows; check status
  and retrieve results by invocation ID.
- **search_***: Semantic search in an Azure AI Search vector index; add new
  documents with auto-generated embeddings.
- **index_***: Create the project-log schema in Azure AI Search; ingest project
  log entries with vector embeddings.

Configuration is driven by environment variables (see README.md).
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery
from dotenv import load_dotenv
from fastmcp import FastMCP
from openai import AzureOpenAI

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("foundry-agents-mcp")

# ── Environment configuration ─────────────────────────────────────────────────
AZURE_AI_PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
AZURE_AI_SEARCH_ENDPOINT = os.getenv("AZURE_AI_SEARCH_ENDPOINT", "")
AZURE_AI_SEARCH_INDEX_NAME = os.getenv("AZURE_AI_SEARCH_INDEX_NAME", "project-log-index")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_EMBEDDING_MODEL = os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
AZURE_OPENAI_EMBEDDING_DIMENSIONS = int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))
AZURE_OPENAI_COMPLETION_MODEL_NAME = os.getenv("AZURE_OPENAI_COMPLETION_MODEL_NAME", "")
APPLICATIONINSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")

# ── MCP server ────────────────────────────────────────────────────────────────
mcp = FastMCP("foundry-agents-mcp-server")

# ── Lazy client singletons ────────────────────────────────────────────────────
_credential: Optional[DefaultAzureCredential] = None
_openai_client: Optional[AzureOpenAI] = None
_search_client: Optional[SearchClient] = None
_index_client: Optional[SearchIndexClient] = None
_project_client = None


def _get_credential() -> DefaultAzureCredential:
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def _get_openai_client() -> AzureOpenAI:
    global _openai_client
    if _openai_client is None:
        cred = _get_credential()
        token_provider = get_bearer_token_provider(
            cred, "https://cognitiveservices.azure.com/.default"
        )
        # Fall back to project endpoint when a dedicated OpenAI endpoint is absent
        endpoint = AZURE_OPENAI_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT
        _openai_client = AzureOpenAI(
            azure_deployment=AZURE_OPENAI_EMBEDDING_MODEL,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
        )
    return _openai_client


def _get_search_client() -> Optional[SearchClient]:
    global _search_client
    if _search_client is None:
        if not AZURE_AI_SEARCH_ENDPOINT:
            return None
        _search_client = SearchClient(
            endpoint=AZURE_AI_SEARCH_ENDPOINT,
            index_name=AZURE_AI_SEARCH_INDEX_NAME,
            credential=_get_credential(),
        )
    return _search_client


def _get_index_client() -> Optional[SearchIndexClient]:
    global _index_client
    if _index_client is None:
        if not AZURE_AI_SEARCH_ENDPOINT:
            return None
        _index_client = SearchIndexClient(
            endpoint=AZURE_AI_SEARCH_ENDPOINT,
            credential=_get_credential(),
        )
    return _index_client


def _get_project_client():
    global _project_client
    if _project_client is None:
        if not AZURE_AI_PROJECT_ENDPOINT:
            return None
        try:
            from azure.ai.projects import AIProjectClient  # noqa: PLC0415

            _project_client = AIProjectClient(
                endpoint=AZURE_AI_PROJECT_ENDPOINT,
                credential=_get_credential(),
            )
        except ImportError:
            logger.error("azure-ai-projects is not installed")
            return None
    return _project_client


# ── Helpers ───────────────────────────────────────────────────────────────────

def _embed_sync(text: str) -> list[float]:
    """Generate a vector embedding using Azure OpenAI (blocking)."""
    client = _get_openai_client()
    response = client.embeddings.create(
        input=text,
        model=AZURE_OPENAI_EMBEDDING_MODEL,
        dimensions=AZURE_OPENAI_EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding


async def _embed(text: str) -> list[float]:
    """Generate a vector embedding (non-blocking wrapper)."""
    return await asyncio.to_thread(_embed_sync, text)


def _make_invocation_id(thread_id: str, run_id: str) -> str:
    return f"{thread_id}::{run_id}"


def _parse_invocation_id(invocation_id: str) -> tuple[str, str]:
    parts = invocation_id.split("::")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid invocation ID '{invocation_id}'. "
            "Expected format: '<thread_id>::<run_id>'."
        )
    return parts[0], parts[1]


def _build_index_fields() -> list:
    """Return the field definitions for the project-log search index."""
    return [
        SearchField(
            name="id", type=SearchFieldDataType.String, key=True, filterable=True
        ),
        SearchField(
            name="title",
            type=SearchFieldDataType.String,
            searchable=True,
            filterable=True,
            sortable=True,
        ),
        SearchField(
            name="type",
            type=SearchFieldDataType.String,
            searchable=True,
            filterable=True,
            facetable=True,
        ),
        SearchField(
            name="customer_name",
            type=SearchFieldDataType.String,
            searchable=True,
            filterable=True,
            facetable=True,
        ),
        SearchField(name="short_summary", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="context", type=SearchFieldDataType.String, searchable=True),
        SearchField(
            name="context_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            vector_search_dimensions=AZURE_OPENAI_EMBEDDING_DIMENSIONS,
            vector_search_profile_name="hnsw-profile",
        ),
        SearchField(
            name="project_name",
            type=SearchFieldDataType.String,
            searchable=True,
            filterable=True,
            facetable=True,
        ),
        SearchField(
            name="tags",
            type="Collection(Edm.String)",
            searchable=True,
            filterable=True,
            facetable=True,
        ),
        SearchField(name="reference_url", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="architecture", type=SearchFieldDataType.String, searchable=True),
        SearchField(
            name="creation_date",
            type=SearchFieldDataType.DateTimeOffset,
            filterable=True,
            sortable=True,
        ),
        SearchField(
            name="modified_date",
            type=SearchFieldDataType.DateTimeOffset,
            filterable=True,
            sortable=True,
        ),
    ]


# ── AGENTS namespace ──────────────────────────────────────────────────────────


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


# ── SEARCH namespace ──────────────────────────────────────────────────────────


@mcp.tool()
async def search_vector_db(query: str, top_k: int = 5) -> str:
    """Search the project vector database using semantic similarity.

    Generates a vector embedding for the query and returns the most similar
    documents from the Azure AI Search index.

    Args:
        query: Natural language query or reference text to search for.
        top_k: Number of results to return (default: 5).

    Example prompts:
    - "Find project logs related to Azure Kubernetes Service"
    - "Search for workshop summaries about machine learning"
    - "What meetings discussed security architecture?"
    - "Find blog posts about microservices, return top 10 results"
    """
    search_client = _get_search_client()
    if search_client is None:
        return (
            "Error: AZURE_AI_SEARCH_ENDPOINT is not configured. "
            "Set this environment variable to your Azure AI Search endpoint."
        )

    try:
        embedding = await _embed(query)
        vector_query = VectorizedQuery(
            vector=embedding,
            k_nearest_neighbors=top_k,
            fields="context_vector",
        )

        results = await asyncio.to_thread(
            lambda: list(
                search_client.search(
                    search_text=None,
                    vector_queries=[vector_query],
                    select=[
                        "id",
                        "title",
                        "type",
                        "customer_name",
                        "short_summary",
                        "project_name",
                        "tags",
                        "reference_url",
                        "creation_date",
                    ],
                    top=top_k,
                )
            )
        )

        if not results:
            return f"No results found for query: '{query}'"

        lines = [f"## Search Results for: '{query}'\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"### {i}. {r.get('title', 'Untitled')}")
            lines.append(f"- **Type**: {r.get('type', 'N/A')}")
            lines.append(f"- **Customer**: {r.get('customer_name', 'N/A')}")
            lines.append(f"- **Project**: {r.get('project_name', 'N/A')}")
            lines.append(f"- **Summary**: {r.get('short_summary', 'N/A')}")
            tags = r.get("tags") or []
            if tags:
                lines.append(f"- **Tags**: {', '.join(tags)}")
            if r.get("reference_url"):
                lines.append(f"- **Reference**: {r['reference_url']}")
            score = r.get("@search.score")
            if score is not None:
                lines.append(f"- **Relevance Score**: {score:.4f}")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        logger.exception("search_vector_db failed")
        return f"Error searching vector database: {exc}"


@mcp.tool()
async def search_add_to_vector_db(
    title: str,
    content: str,
    entry_type: str = "meeting",
    customer_name: str = "",
    short_summary: str = "",
    project_name: str = "",
    tags: str = "",
    reference_url: str = "",
    architecture: str = "",
) -> str:
    """Add a new document to the project vector database.

    Generates a vector embedding for the content and stores the document in
    the Azure AI Search index for future semantic searches.

    Args:
        title: Document title.
        content: Main content text to index and embed.
        entry_type: Entry type: workshop, meeting, blog, or repo (default: meeting).
        customer_name: Name of the customer or organization.
        short_summary: Brief summary of the content.
        project_name: Name of the associated project.
        tags: Comma-separated list of technology/product tags (e.g. "azure,kubernetes").
        reference_url: External URL reference for the source.
        architecture: Architecture diagram encoded as JSON or XML.

    Example prompts:
    - "Add this meeting summary to the vector database: title='Azure Workshop', content='...'"
    - "Store a new project log about our Kubernetes migration discussion"
    - "Index this blog post with tags: azure, containers, devops"
    """
    search_client = _get_search_client()
    if search_client is None:
        return "Error: AZURE_AI_SEARCH_ENDPOINT is not configured."

    try:
        embedding = await _embed(content)
        doc_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        tags_list = [t.strip() for t in tags.split(",")] if tags else []

        document = {
            "id": doc_id,
            "title": title,
            "type": entry_type,
            "customer_name": customer_name,
            "short_summary": short_summary,
            "context": content,
            "context_vector": embedding,
            "project_name": project_name,
            "tags": tags_list,
            "reference_url": reference_url,
            "architecture": architecture,
            "creation_date": now,
            "modified_date": now,
        }

        results = await asyncio.to_thread(
            lambda: list(search_client.upload_documents(documents=[document]))
        )
        succeeded = sum(1 for r in results if r.succeeded)

        if succeeded:
            return (
                "Document added to vector database.\n"
                f"- **ID**: `{doc_id}`\n"
                f"- **Title**: {title}\n"
                f"- **Type**: {entry_type}"
            )
        return "Failed to add document to vector database."

    except Exception as exc:
        logger.exception("search_add_to_vector_db failed")
        return f"Error adding to vector database: {exc}"


# ── INDEX namespace ───────────────────────────────────────────────────────────


@mcp.tool()
async def index_create_project_log_index() -> str:
    """Create the project log search index in Azure AI Search.

    Sets up the index schema including vector search capabilities for semantic
    similarity search on the context field. The schema supports:
    title, type, customer_name, short_summary, context (+ embedding vector),
    project_name, tags, reference_url, architecture, creation_date, modified_date.

    Safe to call if the index already exists – it will return a confirmation
    without modifying the existing index.

    Example prompts:
    - "Set up the project log search index"
    - "Create the Azure AI Search index for storing project summaries"
    - "Initialize the vector database schema for project logs"
    """
    index_client = _get_index_client()
    if index_client is None:
        return "Error: AZURE_AI_SEARCH_ENDPOINT is not configured."

    try:
        from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415

        try:
            await asyncio.to_thread(
                lambda: index_client.get_index(AZURE_AI_SEARCH_INDEX_NAME)
            )
            return f"Index '{AZURE_AI_SEARCH_INDEX_NAME}' already exists."
        except ResourceNotFoundError:
            pass  # does not exist – create below

        fields = _build_index_fields()
        vector_search = VectorSearch(
            profiles=[
                VectorSearchProfile(
                    name="hnsw-profile", algorithm_configuration_name="hnsw"
                )
            ],
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        )
        index = SearchIndex(
            name=AZURE_AI_SEARCH_INDEX_NAME,
            fields=fields,
            vector_search=vector_search,
        )

        result = await asyncio.to_thread(
            lambda: index_client.create_or_update_index(index)
        )
        field_names = ", ".join(f.name for f in fields)
        return (
            f"Index '{result.name}' created successfully.\n"
            f"Fields: {field_names}"
        )

    except Exception as exc:
        logger.exception("index_create_project_log_index failed")
        return f"Error creating index: {exc}"


@mcp.tool()
async def index_ingest_project_log(
    title: str,
    entry_type: str,
    customer_name: str,
    short_summary: str,
    context: str,
    project_name: str = "",
    tags: str = "",
    reference_url: str = "",
    architecture: str = "",
) -> str:
    """Ingest a project log entry into the Azure AI Search index with vector embeddings.

    Generates a vector embedding for the context field and stores the complete
    project log entry. Creates the index automatically if it does not exist.

    Args:
        title: Title of the project log entry.
        entry_type: Entry type: workshop, meeting, blog, or repo.
        customer_name: Customer or organization name.
        short_summary: Brief summary (1–2 sentences).
        context: Full context or body text (will be vectorized for search).
        project_name: Project name for filtering/faceting.
        tags: Comma-separated technology/product tags (e.g. "azure,kubernetes,devops").
        reference_url: External source URL.
        architecture: Architecture diagram as JSON or XML string.

    Example prompts:
    - "Add a workshop log: title='Azure AI Day', entry_type='workshop', customer='Contoso'"
    - "Index a new meeting summary about the cloud migration project"
    - "Store this repo documentation with tags: python, mcp, azure"
    """
    if not AZURE_AI_SEARCH_ENDPOINT:
        return "Error: AZURE_AI_SEARCH_ENDPOINT is not configured."

    try:
        # Auto-create the index if missing
        index_client = _get_index_client()
        if index_client:
            from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415

            try:
                await asyncio.to_thread(
                    lambda: index_client.get_index(AZURE_AI_SEARCH_INDEX_NAME)
                )
            except ResourceNotFoundError:
                creation_result = await index_create_project_log_index()
                if creation_result.startswith("Error"):
                    return creation_result

        embedding = await _embed(context)
        doc_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        tags_list = [t.strip() for t in tags.split(",")] if tags else []

        document = {
            "id": doc_id,
            "title": title,
            "type": entry_type,
            "customer_name": customer_name,
            "short_summary": short_summary,
            "context": context,
            "context_vector": embedding,
            "project_name": project_name,
            "tags": tags_list,
            "reference_url": reference_url,
            "architecture": architecture,
            "creation_date": now,
            "modified_date": now,
        }

        ingest_client = SearchClient(
            endpoint=AZURE_AI_SEARCH_ENDPOINT,
            index_name=AZURE_AI_SEARCH_INDEX_NAME,
            credential=_get_credential(),
        )
        results = await asyncio.to_thread(
            lambda: list(ingest_client.upload_documents(documents=[document]))
        )
        succeeded = sum(1 for r in results if r.succeeded)

        if succeeded:
            return (
                "Project log ingested successfully.\n"
                f"- **ID**: `{doc_id}`\n"
                f"- **Title**: {title}\n"
                f"- **Type**: {entry_type}\n"
                f"- **Customer**: {customer_name}"
            )
        return "Failed to ingest project log document."

    except Exception as exc:
        logger.exception("index_ingest_project_log failed")
        return f"Error ingesting project log: {exc}"


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Launch the Foundry Agents MCP Server via stdio (compatible with uvx)."""
    mcp.run()


if __name__ == "__main__":
    main()
