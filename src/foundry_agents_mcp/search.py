"""MCP tools for the **search_*** namespace.

Provides semantic vector search and document ingestion for the Azure AI Search
project-log index.
"""

import asyncio
from typing import Optional

from azure.search.documents.models import VectorizedQuery

from foundry_agents_mcp.app import mcp
from foundry_agents_mcp.client import (
    AZURE_AI_SEARCH_INDEX_NAME,
    _build_document,
    _embed,
    _get_search_client,
    logger,
)


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
        tags_list = [t.strip() for t in tags.split(",")] if tags else []

        document = _build_document(
            title=title,
            entry_type=entry_type,
            customer_name=customer_name,
            short_summary=short_summary,
            context=content,
            context_vector=embedding,
            project_name=project_name,
            tags=tags_list,
            reference_url=reference_url,
            architecture=architecture,
        )

        results = await asyncio.to_thread(
            lambda: list(search_client.upload_documents(documents=[document]))
        )
        succeeded = sum(1 for r in results if r.succeeded)

        if succeeded:
            return (
                "Document added to vector database.\n"
                f"- **ID**: `{document['id']}`\n"
                f"- **Title**: {title}\n"
                f"- **Type**: {entry_type}"
            )
        return "Failed to add document to vector database."

    except Exception as exc:
        logger.exception("search_add_to_vector_db failed")
        return f"Error adding to vector database: {exc}"
