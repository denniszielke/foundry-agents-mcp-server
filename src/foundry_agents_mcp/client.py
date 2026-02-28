"""Shared Azure client singletons, environment configuration, and utilities.

All modules in this package import from here to avoid duplicated setup code.
All Azure services authenticate via DefaultAzureCredential so no API keys are
needed in the environment (managed identity, Azure CLI, etc. all work).
"""

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("foundry-agents-mcp")

# ── Environment configuration ──────────────────────────────────────────────────
AZURE_AI_PROJECT_ENDPOINT: str = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
AZURE_AI_SEARCH_ENDPOINT: str = os.getenv("AZURE_AI_SEARCH_ENDPOINT", "")
AZURE_AI_SEARCH_INDEX_NAME: str = os.getenv("AZURE_AI_SEARCH_INDEX_NAME", "project-log-index")
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_EMBEDDING_MODEL: str = os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
AZURE_OPENAI_EMBEDDING_DIMENSIONS: int = int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))
AZURE_OPENAI_COMPLETION_MODEL_NAME: str = os.getenv("AZURE_OPENAI_COMPLETION_MODEL_NAME", "")
APPLICATIONINSIGHTS_CONNECTION_STRING: str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
# When deployed to Container Apps, use a user-assigned managed identity if provided
_RUNNING_IN_PRODUCTION: bool = os.getenv("RUNNING_IN_PRODUCTION", "false").lower() == "true"
_AZURE_CLIENT_ID: str = os.getenv("AZURE_CLIENT_ID", "")

# ── Lazy client singletons ─────────────────────────────────────────────────────
_credential: Optional[DefaultAzureCredential] = None
_openai_embed_client: Optional[AzureOpenAI] = None
_openai_chat_client: Optional[AzureOpenAI] = None
_search_client: Optional[SearchClient] = None
_index_client: Optional[SearchIndexClient] = None
_project_client = None


def _get_credential() -> DefaultAzureCredential | ManagedIdentityCredential:
    global _credential
    if _credential is None:
        if _RUNNING_IN_PRODUCTION and _AZURE_CLIENT_ID:
            _credential = ManagedIdentityCredential(client_id=_AZURE_CLIENT_ID)
        else:
            _credential = DefaultAzureCredential()
    return _credential


def _get_openai_client() -> AzureOpenAI:
    """Return an AzureOpenAI client configured for the embedding model."""
    global _openai_embed_client
    if _openai_embed_client is None:
        cred = _get_credential()
        token_provider = get_bearer_token_provider(
            cred, "https://cognitiveservices.azure.com/.default"
        )
        endpoint = AZURE_OPENAI_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT
        _openai_embed_client = AzureOpenAI(
            azure_deployment=AZURE_OPENAI_EMBEDDING_MODEL,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
        )
    return _openai_embed_client


def _get_chat_client() -> Optional[AzureOpenAI]:
    """Return an AzureOpenAI client configured for the completion model.

    Returns None when AZURE_OPENAI_COMPLETION_MODEL_NAME is not configured.
    """
    global _openai_chat_client
    if _openai_chat_client is None:
        if not AZURE_OPENAI_COMPLETION_MODEL_NAME:
            return None
        cred = _get_credential()
        token_provider = get_bearer_token_provider(
            cred, "https://cognitiveservices.azure.com/.default"
        )
        endpoint = AZURE_OPENAI_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT
        _openai_chat_client = AzureOpenAI(
            azure_deployment=AZURE_OPENAI_COMPLETION_MODEL_NAME,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
        )
    return _openai_chat_client


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
    """Return an AIProjectClient, or None if not configured / not installed."""
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


# ── Embedding helpers ─────────────────────────────────────────────────────────

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
    """Generate a vector embedding (async wrapper)."""
    return await asyncio.to_thread(_embed_sync, text)


# ── Invocation ID helpers ─────────────────────────────────────────────────────

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


# ── Document helper ───────────────────────────────────────────────────────────

def _build_document(
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
    """Build a document dict ready for upload to the Azure AI Search index."""
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
