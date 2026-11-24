"""고도화된 무료 멀티소스 웹 리서치 & 스마트 본문 추출 모듈.

지원 소스 (모두 무료, 유료 API 키 불필요):
- ddgs (DuckDuckGo / 멀티 백엔드 텍스트 & 뉴스 검색)
- Google News RSS (한국어/글로벌 최신 기사)
- Hacker News Algolia API & GitHub Search API (글로벌 기술 트렌드)
- 사용자 직접 제공 URL (최우선 근거)

본문 추출 파이프라인:
1) trafilatura 본문 전용 추출
2) BeautifulSoup <article>/<main> + OG/JSON-LD 메타 보강
3) SPA(React/Next.js) 빈 본문 시 선택적 r.jina.ai 리더 폴백
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urlparse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import httpx

from app.config import settings

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - legacy fallback
    from duckduckgo_search import DDGS  # type: ignore

try:
    import trafilatura
except ImportError:  # pragma: no cover
    trafilatura = None  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

BLOCKED_DOMAIN_KEYWORDS = (
    "linkedin.com",
    "instagram.com",
    "facebook.com",
    "pinterest.",
    "tiktok.com",
    "namu.wiki",
)

TRUSTED_DOMAIN_KEYWORDS = (
    "toss.tech",
    "d2.naver.com",
    "tech.kakao.com",
    "techblog.woowahan.com",
    "medium.com",
    "velog.io",
    "yozm.wishket.com",
    "github.com",
    "aws.amazon.com",
    "engineering.",
    "tech.",
    "blog.",
    "docs.",
    "zdnet.co.kr",
    "bloter.net",
    "etnews.com",
    "aitimes.com",
    "hankyung.com",
    "mk.co.kr",
    "news.ycombinator.com",
    "openai.com",
    "anthropic.com",
    "langchain.com",
)


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _is_blocked_url(url: str) -> bool:
    domain = _extract_domain(url)
    return any(bad in domain for bad in BLOCKED_DOMAIN_KEYWORDS)


def _normalize_title_key(title: str) -> str:
    return re.sub(r"[\W_]+", "", title.lower())[:50]


def _clean_html_snippet(raw: str) -> str:
    unescaped = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", text).strip()


# ==============================================================================
# 1. 개별 무료 검색 소스
# ==============================================================================
def _ddg_text_sync(
    query: str, max_results: int, region: str, timelimit: str | None
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        with DDGS() as ddgs:
            kwargs: dict[str, Any] = {
                "region": region,
                "safesearch": "moderate",
                "max_results": max_results,
            }
            if timelimit:
                kwargs["timelimit"] = timelimit
            raw = ddgs.text(query, **kwargs)
            for row in raw or []:
                url = str(row.get("href") or row.get("link") or "").strip()
                title = str(row.get("title") or "").strip()
                snippet = str(row.get("body") or row.get("snippet") or "").strip()
                if not (title or snippet) or _is_blocked_url(url):
                    continue
                items.append(
                    {
                        "title": title,
                        "url": url,
                        "domain": _extract_domain(url),
                        "snippet": snippet,
                        "source_type": "web",
                        "published_at": "",
                    }
                )
    except Exception as exc:
        logger.warning("ddgs.text failed for '%s': %s", query, exc)
    return items


def _ddg_news_sync(
    query: str, max_results: int, region: str, timelimit: str | None
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        with DDGS() as ddgs:
            kwargs: dict[str, Any] = {
                "region": region,
                "safesearch": "moderate",
                "max_results": max_results,
            }
            if timelimit:
                kwargs["timelimit"] = timelimit
            raw = ddgs.news(query, **kwargs)
            for row in raw or []:
                url = str(row.get("url") or row.get("href") or "").strip()
                title = str(row.get("title") or "").strip()
                snippet = str(row.get("body") or row.get("excerpt") or "").strip()
                published = str(row.get("date") or "")[:10]
                if not (title or snippet) or _is_blocked_url(url):
                    continue
                items.append(
                    {
                        "title": title,
                        "url": url,
                        "domain": _extract_domain(url) or str(row.get("source") or ""),
                        "snippet": snippet,
                        "source_type": "news",
                        "published_at": published,
                    }
                )
    except Exception as exc:
        logger.debug("ddgs.news failed for '%s': %s", query, exc)
    return items


async def search_web_results(
    query: str,
    max_results: int = 5,
    *,
    region: str = "kr-kr",
    timelimit: str | None = None,
) -> list[dict[str, Any]]:
    clean = query.strip()
    if not clean:
        return []
    return await asyncio.to_thread(_ddg_text_sync, clean, max_results, region, timelimit)


async def search_news_results(
    query: str,
    max_results: int = 5,
    *,
    region: str = "kr-kr",
    timelimit: str | None = "m",
) -> list[dict[str, Any]]:
    clean = query.strip()
    if not clean:
        return []
    return await asyncio.to_thread(_ddg_news_sync, clean, max_results, region, timelimit)


async def search_google_news_rss(
    query: str,
    *,
    max_results: int = 6,
    lang: str = "ko",
) -> list[dict[str, Any]]:
    """Google News RSS에서 한국어/글로벌 최신 기사를 무료·무인증으로 수집한다."""
    clean = query.strip()
    if not clean:
        return []

    if lang == "en":
        rss_url = (
            f"https://news.google.com/rss/search?q={quote_plus(clean)}"
            "&hl=en-US&gl=US&ceid=US:en"
        )
    else:
        rss_url = (
            f"https://news.google.com/rss/search?q={quote_plus(clean)}"
            "&hl=ko&gl=KR&ceid=KR:ko"
        )

    items: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS, timeout=8.0, follow_redirects=True
        ) as client:
            resp = await client.get(rss_url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)

        for entry in root.findall(".//item")[:max_results]:
            title = (entry.findtext("title") or "").strip()
            link = (entry.findtext("link") or "").strip()
            pub_date = (entry.findtext("pubDate") or "").strip()[:16]
            desc = _clean_html_snippet(entry.findtext("description") or "")
            source_el = entry.find("source")
            source_name = (
                source_el.text.strip()
                if source_el is not None and source_el.text
                else "Google News"
            )
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "url": link,
                    "domain": source_name,
                    "snippet": desc or title,
                    "source_type": "google_news",
                    "published_at": pub_date,
                }
            )
    except Exception as exc:
        logger.warning("Google News RSS failed for '%s': %s", query, exc)
    return items


async def search_hackernews(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Hacker News Algolia API(무료·무인증)에서 글로벌 기술 토론/아티클을 검색한다."""
    clean = query.strip()
    if not clean:
        return []
    url = (
        f"https://hn.algolia.com/api/v1/search?query={quote_plus(clean)}"
        f"&tags=story&hitsPerPage={max_results}"
    )
    items: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        for hit in data.get("hits") or []:
            story_url = str(hit.get("url") or "").strip()
            obj_id = hit.get("objectID") or ""
            hn_link = f"https://news.ycombinator.com/item?id={obj_id}" if obj_id else ""
            final_url = story_url or hn_link
            title = str(hit.get("title") or "").strip()
            if not title or _is_blocked_url(final_url):
                continue
            points = hit.get("points") or 0
            comments = hit.get("num_comments") or 0
            created = str(hit.get("created_at") or "")[:10]
            items.append(
                {
                    "title": title,
                    "url": final_url,
                    "domain": _extract_domain(final_url) or "news.ycombinator.com",
                    "snippet": f"Hacker News ({points} points, {comments} comments) - {title}",
                    "source_type": "hackernews",
                    "published_at": created,
                }
            )
    except Exception as exc:
        logger.debug("Hacker News search failed for '%s': %s", query, exc)
    return items


async def search_github_repos(query: str, max_results: int = 4) -> list[dict[str, Any]]:
    """GitHub Search API에서 관련 오픈소스/기술 레퍼런스를 조회한다."""
    clean = query.strip()
    if not clean:
        return []
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "career-agent-research/1.0",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    items: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            resp = await client.get(
                "https://api.github.com/search/repositories",
                params={"q": clean, "sort": "stars", "per_page": max_results},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        for repo in data.get("items") or []:
            full_name = str(repo.get("full_name") or "")
            desc = str(repo.get("description") or "").strip()
            stars = int(repo.get("stargazers_count") or 0)
            lang = str(repo.get("language") or "")
            pushed = str(repo.get("pushed_at") or "")[:10]
            items.append(
                {
                    "title": f"{full_name} ({stars:,}★)",
                    "url": str(repo.get("html_url") or ""),
                    "domain": "github.com",
                    "snippet": f"[{lang}] {desc}" if lang else desc,
                    "source_type": "github",
                    "published_at": pushed,
                }
            )
    except Exception as exc:
        logger.debug("GitHub repo search failed for '%s': %s", query, exc)
    return items


# ==============================================================================
# 2. 스마트 본문 추출기 (trafilatura -> BS4/Meta -> 선택적 Jina Reader SPA 폴백)
# ==============================================================================
def _extract_with_bs4_and_meta(raw_html: str, max_chars: int) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    meta_parts: list[str] = []
    for attr_name, attr_val in (
        ("property", "og:title"),
        ("property", "og:description"),
        ("name", "description"),
    ):
        tag = soup.find("meta", attrs={attr_name: attr_val})
        if tag and tag.get("content"):
            val = str(tag["content"]).strip()
            if val and val not in meta_parts:
                meta_parts.append(val)

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    main_container = soup.find("article") or soup.find("main") or soup.body or soup
    body = re.sub(r"\s+", " ", main_container.get_text(separator=" ", strip=True)).strip()
    combined = " | ".join(meta_parts) + ("\n" + body if body else "")
    return combined.strip()[:max_chars]


async def _fetch_jina_reader(url: str, max_chars: int) -> str:
    if not settings.enable_jina_reader_fallback:
        return ""
    if "news.google.com/rss/articles" in url:
        return ""
    try:
        jina_url = f"https://r.jina.ai/{url}"
        async with httpx.AsyncClient(
            headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]},
            timeout=6.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(jina_url)
            if resp.status_code == 200:
                text = re.sub(r"\n{3,}", "\n\n", resp.text).strip()
                return text[:max_chars]
    except Exception as exc:
        logger.debug("Jina reader fallback skipped for '%s': %s", url, exc)
    return ""


async def fetch_page_text(
    url: str, *, timeout: float = 8.0, max_chars: int = 2000
) -> str:
    """trafilatura -> BS4/OG 메타 -> SPA 시 r.jina.ai 순으로 본문을 추출한다."""
    if not url or not url.startswith(("http://", "https://")):
        return ""
    if "news.google.com/rss/articles" in url:
        # Google News 암호화 리다이렉트 링크는 RSS 제목/스니펫이 더 안정적
        return ""

    extracted = ""
    try:
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            if response.status_code < 400:
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type or "text/plain" in content_type:
                    raw_html = response.text
                    if trafilatura is not None:
                        t_text = await asyncio.to_thread(
                            trafilatura.extract,
                            raw_html,
                            include_comments=False,
                            include_tables=True,
                            favor_recall=True,
                        )
                        if t_text:
                            extracted = re.sub(r"\s+", " ", t_text).strip()[:max_chars]
                    if len(extracted) < 200:
                        bs_text = _extract_with_bs4_and_meta(raw_html, max_chars=max_chars)
                        if len(bs_text) > len(extracted):
                            extracted = bs_text
    except Exception as exc:
        logger.debug("Direct fetch failed for '%s': %s", url, exc)

    # SPA / 봇 차단으로 본문이 비어 있을 때만 r.jina.ai 리더 폴백
    if len(extracted) < 200:
        jina_text = await _fetch_jina_reader(url, max_chars=max_chars)
        if len(jina_text) > len(extracted):
            extracted = jina_text

    return extracted[:max_chars]


# ==============================================================================
# 3. 스코어링, 중복 제거 & 멀티소스 리서치 오케스트레이터
# ==============================================================================
def _score_source(item: dict[str, Any], focus_keywords: list[str]) -> int:
    score = 0
    if item.get("source_type") == "user_reference":
        score += 100
    domain = (item.get("domain") or "").lower()
    if any(t in domain for t in TRUSTED_DOMAIN_KEYWORDS):
        score += 25
    if item.get("source_type") in ("google_news", "news", "hackernews", "github"):
        score += 12
    if item.get("published_at"):
        score += 8

    title_lower = (item.get("title") or "").lower()
    snippet_lower = (item.get("snippet") or "").lower()
    for kw in focus_keywords:
        k = kw.strip().lower()
        if not k:
            continue
        if k in title_lower:
            score += 15
        elif k in snippet_lower:
            score += 6
    return score


def deduplicate_and_rank_sources(
    candidates: list[dict[str, Any]],
    *,
    focus_keywords: list[str],
    max_total: int = 8,
) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict[str, Any]] = []

    for item in candidates:
        url = (item.get("url") or "").strip()
        title_key = _normalize_title_key(item.get("title") or "")
        if url and url in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title_key:
            seen_titles.add(title_key)
        scored = dict(item)
        scored["_score"] = _score_source(scored, focus_keywords)
        unique.append(scored)

    unique.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return unique[:max_total]


async def multi_source_research(
    queries: list[str],
    *,
    focus_keywords: list[str] | None = None,
    include_news_rss: bool = True,
    news_query: str = "",
    reference_urls: list[str] | None = None,
    max_total: int = 8,
    fetch_top_n: int = 5,
    max_chars: int = 1800,
) -> list[dict[str, Any]]:
    """다중 쿼리 + Google News RSS + 사용자 제공 URL을 병렬 수집·정렬·본문 추출한다."""
    tasks = [search_web_results(q, max_results=3) for q in queries if q.strip()]
    if include_news_rss:
        rss_q = news_query.strip() or (queries[0] if queries else "")
        if rss_q:
            tasks.append(search_google_news_rss(rss_q, max_results=5, lang="ko"))
            tasks.append(search_news_results(rss_q, max_results=3))

    batches = await asyncio.gather(*tasks, return_exceptions=True)

    candidates: list[dict[str, Any]] = []
    # 사용자 직접 입력 URL은 최우선 근거로 삽입
    for raw_url in reference_urls or []:
        u = raw_url.strip()
        if u.startswith(("http://", "https://")):
            candidates.append(
                {
                    "title": f"사용자 제공 참고 자료 ({_extract_domain(u)})",
                    "url": u,
                    "domain": _extract_domain(u),
                    "snippet": "",
                    "source_type": "user_reference",
                    "published_at": "",
                }
            )

    for batch in batches:
        if isinstance(batch, list):
            candidates.extend(batch)

    ranked = deduplicate_and_rank_sources(
        candidates,
        focus_keywords=focus_keywords or [],
        max_total=max_total,
    )

    # 사용자 제공 URL + 상위 N건의 실제 본문을 병렬 추출
    fetch_indices = [
        idx
        for idx, item in enumerate(ranked)
        if item.get("source_type") == "user_reference" or idx < fetch_top_n
    ]
    fetched = await asyncio.gather(
        *(
            fetch_page_text(ranked[idx]["url"], max_chars=max_chars)
            for idx in fetch_indices
        ),
        return_exceptions=True,
    )
    fetched_map = {
        fetch_indices[i]: fetched[i]
        for i in range(len(fetch_indices))
        if isinstance(fetched[i], str) and fetched[i].strip()
    }

    enriched: list[dict[str, Any]] = []
    for idx, item in enumerate(ranked):
        body = fetched_map.get(idx) or item.get("snippet") or item.get("title") or ""
        enriched.append(
            {
                "title": item.get("title") or item.get("url") or "제목 없음",
                "url": item.get("url") or "",
                "domain": item.get("domain") or _extract_domain(item.get("url") or ""),
                "snippet": item.get("snippet") or "",
                "content": body[:max_chars],
                "source_type": item.get("source_type") or "web",
                "published_at": item.get("published_at") or "",
            }
        )
    return enriched


async def search_interest_sources(
    keyword: str,
    *,
    scope: str = "ko",
    recency: str = "recent",
    max_results: int = 6,
) -> list[dict[str, Any]]:
    """관심 분야 트렌드 검색 (한국어 뉴스/블로그, 글로벌 HN/GitHub, 통합 지원)."""
    clean = keyword.strip()
    if not clean:
        return []
    timelimit = "m" if recency == "recent" else None

    tasks: list[Any] = []
    if scope in ("ko", "all"):
        tasks.append(
            search_web_results(
                f"{clean} 기술 트렌드 아키텍처 실무 사례",
                max_results=4,
                region="kr-kr",
                timelimit=timelimit,
            )
        )
        tasks.append(search_google_news_rss(clean, max_results=4, lang="ko"))

    if scope in ("global", "all"):
        tasks.append(
            search_web_results(
                f"{clean} engineering architecture best practices",
                max_results=4,
                region="wt-wt",
                timelimit=timelimit,
            )
        )
        tasks.append(search_hackernews(clean, max_results=4))
        tasks.append(search_github_repos(clean, max_results=3))
        tasks.append(search_google_news_rss(clean, max_results=3, lang="en"))

    batches = await asyncio.gather(*tasks, return_exceptions=True)
    candidates: list[dict[str, Any]] = []
    for batch in batches:
        if isinstance(batch, list):
            candidates.extend(batch)

    ranked = deduplicate_and_rank_sources(
        candidates,
        focus_keywords=clean.split(),
        max_total=max_results,
    )

    fetch_n = min(4, len(ranked))
    fetched = await asyncio.gather(
        *(fetch_page_text(item["url"], max_chars=1500) for item in ranked[:fetch_n]),
        return_exceptions=True,
    )

    enriched: list[dict[str, Any]] = []
    for idx, item in enumerate(ranked):
        body = (
            fetched[idx]
            if idx < len(fetched) and isinstance(fetched[idx], str) and fetched[idx].strip()
            else item.get("snippet") or ""
        )
        enriched.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "domain": item.get("domain") or "",
                "snippet": item.get("snippet") or "",
                "content": body or item.get("title") or "",
                "source_type": item.get("source_type") or "web",
                "published_at": item.get("published_at") or "",
            }
        )
    return enriched


async def search_and_extract(
    query: str,
    *,
    max_results: int = 4,
    fetch_top_n: int = 2,
    timeout: float = 8.0,
    max_chars: int = 1600,
) -> list[dict[str, Any]]:
    """단일 쿼리용 멀티소스 검색 + 스마트 본문 추출 (코파일럿 Corrective RAG 등에서 공용)."""
    del timeout  # fetch_page_text 내부 기본 타임아웃 사용
    return await multi_source_research(
        [query],
        focus_keywords=query.split(),
        include_news_rss=True,
        news_query=query,
        max_total=max_results,
        fetch_top_n=fetch_top_n,
        max_chars=max_chars,
    )
