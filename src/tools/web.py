from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import httpx
from duckduckgo_search import DDGS

LOGGER = logging.getLogger(__name__)

_FETCH_TIMEOUT = 10
_MAX_PAGE_CHARS = 4000
_JUNK_TAGS = frozenset({
    "script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg", "iframe",
})


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor that skips nav/script/style."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _JUNK_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _JUNK_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._pieces.append(text)

    def get_text(self) -> str:
        return " ".join(self._pieces)


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    text = extractor.get_text()
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text[:_MAX_PAGE_CHARS]


class WebSearchTool:
    def __init__(self, region: str = "wt-wt", max_results: int = 5) -> None:
        self._region = region
        self._max_results = max_results

    def search(self, query: str) -> str:
        """Quick search: returns DuckDuckGo snippets only."""
        with DDGS() as ddgs:
            results = list(
                ddgs.text(
                    keywords=query,
                    region=self._region,
                    max_results=self._max_results,
                )
            )
        if not results:
            return "No web results found."

        lines = []
        for index, result in enumerate(results, start=1):
            title = result.get("title", "Untitled")
            href = result.get("href", "")
            body = result.get("body", "")
            lines.append(f"{index}. {title}\n{href}\n{body}")
        return "\n\n".join(lines)

    def deep_search(self, query: str, max_pages: int = 5) -> list[dict]:
        """Fetch DuckDuckGo results, then read actual page content for the top links.

        Returns a list of dicts: {url, title, snippet, content, fetched}.
        """
        with DDGS() as ddgs:
            raw_results = list(
                ddgs.text(
                    keywords=query,
                    region=self._region,
                    max_results=max_pages,
                )
            )
        if not raw_results:
            return []

        pages: list[dict] = []
        for result in raw_results[:max_pages]:
            url = result.get("href", "")
            title = result.get("title", "Untitled")
            snippet = result.get("body", "")

            page_info: dict = {
                "url": url,
                "title": title,
                "snippet": snippet,
                "content": "",
                "fetched": False,
            }

            if url:
                content = self._fetch_page(url)
                if content:
                    page_info["content"] = content
                    page_info["fetched"] = True

            pages.append(page_info)

        return pages

    @staticmethod
    def _fetch_page(url: str) -> str:
        """Fetch a URL and extract readable text. Returns empty string on failure."""
        try:
            with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MyAssistBot/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                })
                if resp.status_code != 200:
                    return ""
                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return ""
                return _html_to_text(resp.text)
        except Exception as exc:
            LOGGER.debug("Failed to fetch %s: %s", url, exc)
            return ""

    @staticmethod
    def format_deep_results(pages: list[dict]) -> str:
        """Format deep search results for LLM consumption."""
        if not pages:
            return "No results found."
        parts: list[str] = []
        for i, page in enumerate(pages, 1):
            header = f"[Source {i}] {page['title']}\nURL: {page['url']}"
            if page["fetched"] and page["content"]:
                body = page["content"][:_MAX_PAGE_CHARS]
                parts.append(f"{header}\n{body}")
            else:
                parts.append(f"{header}\nSnippet: {page['snippet']}")
        return "\n\n---\n\n".join(parts)
