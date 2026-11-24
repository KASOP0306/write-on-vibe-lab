"""DuckDuckGo 무료 웹 검색 및 BeautifulSoup 본문 텍스트 추출 도구 (agents_md.md Day 2)."""

import asyncio
import logging
import re
from typing import Any

from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import httpx

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _ddg_text_search_sync(query: str, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    try:
        with DDGS() as ddgs:
            raw_items = ddgs.text(
                query,
                region="kr-kr",
                safesearch="moderate",
                max_results=max_results,
            )
            for item in raw_items or []:
                url = str(item.get("href") or item.get("link") or "").strip()
                title = str(item.get("title") or "").strip()
                snippet = str(item.get("body") or item.get("snippet") or "").strip()
                if title or snippet:
                    results.append(
                        {
                            "title": title,
                            "url": url,
                            "snippet": snippet,
                        }
                    )
    except Exception as exc:
        logger.warning("DuckDuckGo search failed for query '%s': %s", query, exc)
    return results


async def search_web_results(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """DuckDuckGo 검색 결과를 비동기로 조회한다."""
    clean_query = query.strip()
    if not clean_query:
        return []
    return await asyncio.to_thread(_ddg_text_search_sync, clean_query, max_results)


def _extract_clean_text(html: str, max_chars: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


async def fetch_page_text(
    url: str, *, timeout: float = 8.0, max_chars: int = 1800
) -> str:
    """지정 URL의 HTML 본문을 타임아웃 안전하게 추출한다."""
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            return _extract_clean_text(response.text, max_chars=max_chars)
    except Exception as exc:
        logger.debug("Failed to fetch page '%s': %s", url, exc)
        return ""


async def search_and_extract(
    query: str,
    *,
    max_results: int = 4,
    fetch_top_n: int = 2,
    timeout: float = 8.0,
    max_chars: int = 1600,
) -> list[dict[str, Any]]:
    """DuckDuckGo 검색 후 상위 N건의 본문 텍스트를 병렬 추출한다."""
    hits = await search_web_results(query, max_results=max_results)
    if not hits:
        return []

    fetch_targets = hits[:fetch_top_n]
    fetched_texts = await asyncio.gather(
        *(
            fetch_page_text(item["url"], timeout=timeout, max_chars=max_chars)
            for item in fetch_targets
        ),
        return_exceptions=True,
    )

    enriched: list[dict[str, Any]] = []
    for idx, item in enumerate(hits):
        body_text = ""
        if idx < len(fetched_texts) and isinstance(fetched_texts[idx], str):
            body_text = fetched_texts[idx]
        enriched.append(
            {
                "title": item["title"],
                "url": item["url"],
                "snippet": item["snippet"],
                "content": body_text or item["snippet"],
            }
        )
    return enriched
