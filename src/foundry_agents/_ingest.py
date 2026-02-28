"""Standalone Azure AI Search index management and document ingestion.

Used by ``project_log_workflow`` so the CLI can store results without depending
on ``foundry_agents_mcp``.
"""

import asyncio
import logging

from azure.search.documents import SearchClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    VectorSearch,
    VectorSearchProfile,
)

from foundry_agents._client import (
    AZURE_AI_SEARCH_ENDPOINT,
    AZURE_AI_SEARCH_INDEX_NAME,
    AZURE_OPENAI_EMBEDDING_DIMENSIONS,
    build_document,
    embed,
    get_credential,
    get_search_client,
)

logger = logging.getLogger("foundry-agents")


def _build_index_fields() -> list:
    return [
        SearchField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchField(name="title", type=SearchFieldDataType.String, searchable=True, filterable=True, sortable=True),
        SearchField(name="type", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
        SearchField(name="customer_name", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
        SearchField(name="short_summary", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="context", type=SearchFieldDataType.String, searchable=True),
        SearchField(
            name="context_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            vector_search_dimensions=AZURE_OPENAI_EMBEDDING_DIMENSIONS,
            vector_search_profile_name="hnsw-profile",
        ),
        SearchField(name="project_name", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
        SearchField(name="tags", type="Collection(Edm.String)", searchable=True, filterable=True, facetable=True),
        SearchField(name="reference_url", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="architecture", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="creation_date", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        SearchField(name="modified_date", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
    ]


async def ensure_index() -> None:
    """Create the project-log index if it does not already exist."""
    if not AZURE_AI_SEARCH_ENDPOINT:
        raise RuntimeError("AZURE_AI_SEARCH_ENDPOINT is not configured")

    from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415
    from azure.search.documents.indexes import SearchIndexClient  # noqa: PLC0415

    index_client = SearchIndexClient(
        endpoint=AZURE_AI_SEARCH_ENDPOINT,
        credential=get_credential(),
    )

    try:
        await asyncio.to_thread(lambda: index_client.get_index(AZURE_AI_SEARCH_INDEX_NAME))
        return  # already exists
    except ResourceNotFoundError:
        pass

    fields = _build_index_fields()
    vector_search = VectorSearch(
        profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
    )
    index = SearchIndex(name=AZURE_AI_SEARCH_INDEX_NAME, fields=fields, vector_search=vector_search)
    await asyncio.to_thread(lambda: index_client.create_or_update_index(index))
    logger.info("Created index '%s'", AZURE_AI_SEARCH_INDEX_NAME)


async def ingest_document(
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
    """Embed *context*, build the document, and upload it to the search index.

    Ensures the index exists first.  Returns the new document ID on success.
    """
    await ensure_index()

    context_vector = await embed(context)
    doc = build_document(
        title=title,
        entry_type=entry_type,
        customer_name=customer_name,
        short_summary=short_summary,
        context=context,
        context_vector=context_vector,
        project_name=project_name,
        tags=tags,
        reference_url=reference_url,
        architecture=architecture,
    )

    # Always create a fresh client so the index name is correct
    search_client = SearchClient(
        endpoint=AZURE_AI_SEARCH_ENDPOINT,
        index_name=AZURE_AI_SEARCH_INDEX_NAME,
        credential=get_credential(),
    )
    results = await asyncio.to_thread(
        lambda: list(search_client.upload_documents(documents=[doc]))
    )
    if not any(r.succeeded for r in results):
        raise RuntimeError("Document upload failed for all results")

    return doc["id"]
