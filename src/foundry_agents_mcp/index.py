"""MCP tools for the **index_*** namespace.

Handles creation of the project-log Azure AI Search index and ingestion of
project log entries with auto-generated vector embeddings.
"""

import asyncio

from azure.search.documents import SearchClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    VectorSearch,
    VectorSearchProfile,
)

from foundry_agents_mcp.app import mcp
from foundry_agents_mcp.client import (
    AZURE_AI_SEARCH_ENDPOINT,
    AZURE_AI_SEARCH_INDEX_NAME,
    AZURE_OPENAI_EMBEDDING_DIMENSIONS,
    _build_document,
    _embed,
    _get_credential,
    _get_index_client,
    logger,
)


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


async def _ensure_index_exists() -> str | None:
    """Create the project-log index if it does not already exist.

    Returns an error string on failure, or None on success.
    """
    index_client = _get_index_client()
    if index_client is None:
        return "Error: AZURE_AI_SEARCH_ENDPOINT is not configured."

    from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415

    try:
        await asyncio.to_thread(
            lambda: index_client.get_index(AZURE_AI_SEARCH_INDEX_NAME)
        )
        return None  # already exists
    except ResourceNotFoundError:
        pass

    fields = _build_index_fields()
    vector_search = VectorSearch(
        profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
    )
    index = SearchIndex(
        name=AZURE_AI_SEARCH_INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
    )
    try:
        await asyncio.to_thread(lambda: index_client.create_or_update_index(index))
        return None
    except Exception as exc:
        logger.exception("_ensure_index_exists failed")
        return f"Error creating index: {exc}"


async def _ingest_project_log_doc(
    *,
    title: str,
    entry_type: str,
    customer_name: str,
    short_summary: str,
    context: str,
    project_name: str = "",
    tags: list[str] | None = None,
    reference_url: str = "",
    architecture: str = "",
) -> str:
    """Core ingestion logic shared by the MCP tool and the workflow pipeline."""
    if not AZURE_AI_SEARCH_ENDPOINT:
        return "Error: AZURE_AI_SEARCH_ENDPOINT is not configured."

    err = await _ensure_index_exists()
    if err:
        return err

    embedding = await _embed(context)

    document = _build_document(
        title=title,
        entry_type=entry_type,
        customer_name=customer_name,
        short_summary=short_summary,
        context=context,
        context_vector=embedding,
        project_name=project_name,
        tags=tags or [],
        reference_url=reference_url,
        architecture=architecture,
    )

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
            f"- **ID**: `{document['id']}`\n"
            f"- **Title**: {title}\n"
            f"- **Type**: {entry_type}\n"
            f"- **Customer**: {customer_name}"
        )
    return "Failed to ingest project log document."


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
            pass

        fields = _build_index_fields()
        vector_search = VectorSearch(
            profiles=[
                VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")
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
    tags_list = [t.strip() for t in tags.split(",")] if tags else []
    try:
        return await _ingest_project_log_doc(
            title=title,
            entry_type=entry_type,
            customer_name=customer_name,
            short_summary=short_summary,
            context=context,
            project_name=project_name,
            tags=tags_list,
            reference_url=reference_url,
            architecture=architecture,
        )
    except Exception as exc:
        logger.exception("index_ingest_project_log failed")
        return f"Error ingesting project log: {exc}"
