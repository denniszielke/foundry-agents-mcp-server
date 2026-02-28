"""HTML page fetch and text extraction utilities for the ``foundry_agents`` package."""

import re
from html.parser import HTMLParser

import httpx

_SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "head", "header", "noscript"})

_USER_AGENT = (
    "Mozilla/5.0 (compatible; FoundryAgentsMCPServer/1.0; "
    "+https://github.com/denniszielke/foundry-agents-mcp-server)"
)


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-plain-text converter that strips noise tags."""

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
        return re.sub(r"\s{3,}", "\n\n", " ".join(self._texts))


def extract_text(html: str, max_chars: int = 12_000) -> str:
    """Return visible text from an HTML string, truncated to *max_chars*."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.get_text()[:max_chars]


async def fetch_page_text(url: str, max_chars: int = 12_000) -> str:
    """Fetch a web page and return its visible text content."""
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
    return extract_text(response.text, max_chars=max_chars)
