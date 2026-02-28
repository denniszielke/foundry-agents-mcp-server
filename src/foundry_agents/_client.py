"""Shared Azure client singletons for the ``foundry_agents`` package.

This module is self-contained – it does NOT import from ``foundry_agents_mcp``.
It reads the same environment variables so both packages share a consistent
configuration surface.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

logger = logging.getLogger("foundry-agents")

# ── Environment variables ──────────────────────────────────────────────────────
AZURE_AI_PROJECT_ENDPOINT: str = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
AZURE_AI_SEARCH_ENDPOINT: str = os.getenv("AZURE_AI_SEARCH_ENDPOINT", "")
AZURE_AI_SEARCH_INDEX_NAME: str = os.getenv("AZURE_AI_SEARCH_INDEX_NAME", "project-log-index")
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_EMBEDDING_MODEL: str = os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
AZURE_OPENAI_EMBEDDING_DIMENSIONS: int = int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))
AZURE_OPENAI_COMPLETION_MODEL_NAME: str = os.getenv("AZURE_OPENAI_COMPLETION_MODEL_NAME", "")
_RUNNING_IN_PRODUCTION: bool = os.getenv("RUNNING_IN_PRODUCTION", "false").lower() == "true"
_AZURE_CLIENT_ID: str = os.getenv("AZURE_CLIENT_ID", "")

# ── Lazy singletons ────────────────────────────────────────────────────────────
_credential: Optional[DefaultAzureCredential] = None
_chat_client: Optional[AzureOpenAI] = None
_embed_client: Optional[AzureOpenAI] = None
_search_client: Optional[SearchClient] = None
_project_client = None


def get_credential() -> DefaultAzureCredential | ManagedIdentityCredential:
    global _credential
    if _credential is None:
        if _RUNNING_IN_PRODUCTION and _AZURE_CLIENT_ID:
            _credential = ManagedIdentityCredential(client_id=_AZURE_CLIENT_ID)
        else:
            _credential = DefaultAzureCredential()
    return _credential


def get_project_client():
    """Return an AIProjectClient or None if not configured."""
    global _project_client
    if _project_client is None:
        if not AZURE_AI_PROJECT_ENDPOINT:
            return None
        try:
            from azure.ai.projects import AIProjectClient  # noqa: PLC0415

            _project_client = AIProjectClient(
                endpoint=AZURE_AI_PROJECT_ENDPOINT,
                credential=get_credential(),
            )
        except ImportError:
            logger.error("azure-ai-projects is not installed")
            return None
    return _project_client


def get_chat_client() -> Optional[AzureOpenAI]:
    """Return an AzureOpenAI client for chat completions or None if not configured."""
    global _chat_client
    if _chat_client is None:
        if not AZURE_OPENAI_COMPLETION_MODEL_NAME:
            return None
        cred = get_credential()
        token_provider = get_bearer_token_provider(
            cred, "https://cognitiveservices.azure.com/.default"
        )
        endpoint = AZURE_OPENAI_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT
        _chat_client = AzureOpenAI(
            azure_deployment=AZURE_OPENAI_COMPLETION_MODEL_NAME,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
        )
    return _chat_client


def get_embed_client() -> AzureOpenAI:
    """Return an AzureOpenAI client configured for the embedding model."""
    global _embed_client
    if _embed_client is None:
        cred = get_credential()
        token_provider = get_bearer_token_provider(
            cred, "https://cognitiveservices.azure.com/.default"
        )
        endpoint = AZURE_OPENAI_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT
        _embed_client = AzureOpenAI(
            azure_deployment=AZURE_OPENAI_EMBEDDING_MODEL,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
        )
    return _embed_client


def get_search_client(index_name: Optional[str] = None) -> Optional[SearchClient]:
    """Return a SearchClient for the project-log index or None if not configured."""
    global _search_client
    if _search_client is None:
        if not AZURE_AI_SEARCH_ENDPOINT:
            return None
        _search_client = SearchClient(
            endpoint=AZURE_AI_SEARCH_ENDPOINT,
            index_name=index_name or AZURE_AI_SEARCH_INDEX_NAME,
            credential=get_credential(),
        )
    return _search_client


# ── Embedding helper ───────────────────────────────────────────────────────────

def embed_sync(text: str) -> list[float]:
    client = get_embed_client()
    response = client.embeddings.create(
        input=text,
        model=AZURE_OPENAI_EMBEDDING_MODEL,
        dimensions=AZURE_OPENAI_EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding


async def embed(text: str) -> list[float]:
    return await asyncio.to_thread(embed_sync, text)


# ── Document builder ───────────────────────────────────────────────────────────

def build_document(
    *,
    title: str,
    entry_type: str,
    customer_name: str,
    short_summary: str,
    context: str,
    context_vector: list[float],
    project_name: str = "",
    tags: list[str] | None = None,
    reference_url: str = "",
    architecture: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "type": entry_type,
        "customer_name": customer_name,
        "short_summary": short_summary,
        "context": context,
        "context_vector": context_vector,
        "project_name": project_name,
        "tags": tags or [],
        "reference_url": reference_url,
        "architecture": architecture,
        "creation_date": now,
        "modified_date": now,
    }
