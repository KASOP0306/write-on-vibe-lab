"""GitHub 저장소 링크 분석 및 포트폴리오·STAR 경험 초안 자동 생성 도구."""

import asyncio
import logging
import re
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.core.bedrock import ainvoke_structured, get_smart_llm

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

KEY_FILES_TO_INSPECT = [
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "docker-compose.yml",
    "backend/requirements.txt",
    "frontend/package.json",
    "ARCHITECTURE.md",
]


class GitHubAnalyzerError(Exception):
    """GitHub 저장소 조회 실패 시 사용자에게 전달할 오류."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class SuggestedStarItem(BaseModel):
    title: str = Field(default="", description="핵심 구현/문제 해결 경험 제목 (30자 내외)")
    situation: str = Field(default="", description="배경 및 해결하려던 문제 (Situation)")
    task: str = Field(default="", description="구현 목표 및 설계 과제 (Task)")
    action: str = Field(default="", description="저장소 코드·구조에서 확인된 구체적 구현 및 기술 선택 (Action)")
    result: str = Field(default="", description="구현 결과 및 아키텍처 효과 (Result)")
    quantified_metrics: str = Field(
        default="",
        description="README/문서에 명시된 실제 수치만 기재 (없으면 반드시 빈 문자열)",
    )


class GitHubPortfolioSynthesisSchema(BaseModel):
    name: str = Field(default="", description="포트폴리오에 표시할 프로젝트명")
    period: str = Field(default="", description="개발 기간 (예: 2026.10 - 2026.11)")
    role: str = Field(default="", description="담당 역할 (힌트 또는 레포 구성 기반)")
    summary: str = Field(default="", description="프로젝트 핵심 요약 (2~4문장)")
    tech_stack: list[str] = Field(
        default_factory=list, description="실제 코드·의존성에서 확인된 핵심 기술 스택 목록"
    )
    portfolio_goal_link: str = Field(
        default="", description="지원자의 커리어 비전·신념과 이 프로젝트가 연결되는 지점"
    )
    portfolio_markdown: str = Field(
        default="",
        description="이력서·노션 포트폴리오에 바로 활용할 수 있는 한국어 Markdown 포트폴리오 본문",
    )
    suggested_experiences: list[SuggestedStarItem] = Field(
        default_factory=list,
        description="저장소 내용에서 추출한 핵심 STAR 경험 초안 1~3건",
    )


def parse_github_url(repo_url: str) -> tuple[str, str]:
    """다양한 GitHub URL 형식에서 (owner, repo)를 추출한다."""
    raw = (repo_url or "").strip()
    if not raw:
        raise GitHubAnalyzerError("GitHub 저장소 URL을 입력해 주세요.", status_code=400)

    pattern = re.compile(
        r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?$"
    )
    match = pattern.match(raw)
    if not match:
        raise GitHubAnalyzerError(
            "올바른 GitHub 저장소 주소 형식이 아닙니다. (예: https://github.com/owner/repo)",
            status_code=400,
        )
    return match.group(1), match.group(2)


def _build_github_headers(*, raw: bool = False) -> dict[str, str]:
    headers = {
        "Accept": (
            "application/vnd.github.raw+json"
            if raw
            else "application/vnd.github+json"
        ),
        "User-Agent": "career-agent-github-analyzer/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


async def _fetch_optional_raw_file(
    client: httpx.AsyncClient, owner: str, repo: str, path: str, max_chars: int = 1800
) -> tuple[str, str]:
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    try:
        resp = await client.get(url, headers=_build_github_headers(raw=True))
        if resp.status_code == 200:
            return path, resp.text[:max_chars]
    except Exception as exc:
        logger.debug("Optional file fetch skipped (%s): %s", path, exc)
    return path, ""


async def fetch_github_repo_context(repo_url: str) -> dict[str, Any]:
    """GitHub REST API로 저장소 메타데이터, 언어, README, 주요 설정/의존성 파일, 최근 커밋을 수집한다."""
    owner, repo = parse_github_url(repo_url)
    base = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        repo_resp = await client.get(base, headers=_build_github_headers())
        if repo_resp.status_code == 404:
            raise GitHubAnalyzerError(
                f"저장소 '{owner}/{repo}'를 찾을 수 없습니다. 비공개(Private) 저장소이거나 주소가 잘못되었습니다.",
                status_code=404,
            )
        if repo_resp.status_code == 403:
            raise GitHubAnalyzerError(
                "GitHub API 요청 한도에 도달했거나 접근이 거부되었습니다. 잠시 후 다시 시도하거나 GITHUB_TOKEN을 설정해 주세요.",
                status_code=429,
            )
        if repo_resp.status_code >= 400:
            raise GitHubAnalyzerError(
                f"GitHub 저장소 조회 실패 (HTTP {repo_resp.status_code})",
                status_code=502,
            )

        repo_data = repo_resp.json()

        # 메타 외 부가 정보 병렬 수집
        lang_task = client.get(f"{base}/languages", headers=_build_github_headers())
        readme_task = client.get(
            f"{base}/readme", headers=_build_github_headers(raw=True)
        )
        root_task = client.get(f"{base}/contents", headers=_build_github_headers())
        commits_task = client.get(
            f"{base}/commits",
            params={"per_page": 15},
            headers=_build_github_headers(),
        )

        lang_resp, readme_resp, root_resp, commits_resp = await asyncio.gather(
            lang_task, readme_task, root_task, commits_task, return_exceptions=True
        )

        languages: list[str] = []
        if isinstance(lang_resp, httpx.Response) and lang_resp.status_code == 200:
            languages = list(lang_resp.json().keys())

        readme_text = ""
        if isinstance(readme_resp, httpx.Response) and readme_resp.status_code == 200:
            readme_text = readme_resp.text[:5500]

        root_entries: list[str] = []
        root_names: set[str] = set()
        if isinstance(root_resp, httpx.Response) and root_resp.status_code == 200:
            items = root_resp.json()
            if isinstance(items, list):
                for item in items[:40]:
                    name = str(item.get("name") or "")
                    kind = "dir" if item.get("type") == "dir" else "file"
                    root_entries.append(f"{name}{'/' if kind == 'dir' else ''}")
                    root_names.add(name)

        # 주요 매니페스트/아키텍처 파일 후보만 선별 조회
        candidate_files = []
        for path in KEY_FILES_TO_INSPECT:
            top = path.split("/", 1)[0]
            if not root_names or top in root_names:
                candidate_files.append(path)

        file_results = await asyncio.gather(
            *(
                _fetch_optional_raw_file(client, owner, repo, path)
                for path in candidate_files
            )
        )
        inspected_files = {path: content for path, content in file_results if content}

        commits: list[str] = []
        commit_dates: list[str] = []
        if isinstance(commits_resp, httpx.Response) and commits_resp.status_code == 200:
            raw_commits = commits_resp.json()
            if isinstance(raw_commits, list):
                for c in raw_commits[:15]:
                    commit_obj = c.get("commit") or {}
                    msg = str(commit_obj.get("message") or "").splitlines()[0][:120]
                    date_str = str(
                        (commit_obj.get("author") or {}).get("date") or ""
                    )[:10]
                    if date_str:
                        commit_dates.append(date_str)
                    if msg:
                        commits.append(f"[{date_str}] {msg}")

    created_ym = str(repo_data.get("created_at") or "")[:7].replace("-", ".")
    pushed_ym = str(repo_data.get("pushed_at") or "")[:7].replace("-", ".")
    period_hint = (
        f"{created_ym} - {pushed_ym}"
        if created_ym and pushed_ym and created_ym != pushed_ym
        else (pushed_ym or created_ym)
    )

    return {
        "owner": owner,
        "repo": repo,
        "full_name": repo_data.get("full_name") or f"{owner}/{repo}",
        "html_url": repo_data.get("html_url") or f"https://github.com/{owner}/{repo}",
        "description": repo_data.get("description") or "",
        "topics": list(repo_data.get("topics") or []),
        "stars": int(repo_data.get("stargazers_count") or 0),
        "default_branch": repo_data.get("default_branch") or "main",
        "period_hint": period_hint,
        "languages": languages,
        "root_entries": root_entries,
        "readme_text": readme_text,
        "inspected_files": inspected_files,
        "commits": commits,
    }


async def analyze_github_to_portfolio(
    repo_url: str,
    *,
    role_hint: str = "",
    extra_context: str = "",
    profile_context: str = "",
) -> dict[str, Any]:
    """GitHub 저장소 정보를 수집하고 Smart LLM으로 포트폴리오 + STAR 경험 초안을 생성한다."""
    repo_ctx = await fetch_github_repo_context(repo_url)

    files_summary = "\n\n".join(
        f"--- {path} ---\n{content}"
        for path, content in repo_ctx["inspected_files"].items()
    ) or "(확인된 주요 설정 파일 없음)"

    commits_summary = "\n".join(repo_ctx["commits"]) or "(커밋 내역 없음)"

    system_prompt = (
        "당신은 시니어 테크 리크루터이자 포트폴리오 아키텍트입니다.\n"
        "제공된 GitHub 저장소의 실제 코드 구조, README, 의존성 파일, 커밋 로그만을 근거로 "
        "포트폴리오 프로젝트 정보, Markdown 포트폴리오 초안, 그리고 핵심 STAR 경험 초안 1~3건을 한국어로 작성하세요.\n"
        "엄격한 규칙:\n"
        "1. 저장소 자료에 없는 성능 수치(예: 응답 속도 50% 단축, 사용자 1만명 등)는 절대 지어내지 마세요. "
        "정량 수치가 명시되지 않았으면 `quantified_metrics`는 빈 문자열(\"\")로 두세요.\n"
        "2. `tech_stack`에는 의존성 파일과 언어 목록에서 실제로 확인된 핵심 기술명만 깔끔하게 추려 넣으세요 (최대 10개).\n"
        "3. `portfolio_markdown`은 `# 프로젝트명`, `## 개요`, `## 아키텍처 및 기술 스택`, `## 핵심 구현 기능`, `## 기술적 고민 및 설계 포인트` 구조로 작성하세요.\n"
        "4. `suggested_experiences`에는 자소서·면접에 바로 쓸 수 있는 가장 돋보이는 구현/설계 경험 1~3건을 STAR 형식으로 추출하세요."
    )

    user_prompt = (
        f"[저장소] {repo_ctx['full_name']} ({repo_ctx['html_url']})\n"
        f"[설명] {repo_ctx['description'] or '(없음)'}\n"
        f"[토픽] {', '.join(repo_ctx['topics']) or '(없음)'}\n"
        f"[추정 기간] {repo_ctx['period_hint']}\n"
        f"[사용 언어] {', '.join(repo_ctx['languages']) or '(없음)'}\n"
        f"[사용자 역할 힌트] {role_hint or '(미입력 — 레포 구성으로 추정)'}\n"
        f"[사용자 추가 메모] {extra_context or '(없음)'}\n\n"
        f"[지원자 커리어 신념/비전]\n{profile_context or '(미설정)'}\n\n"
        f"[루트 디렉토리 구조]\n{', '.join(repo_ctx['root_entries'])}\n\n"
        f"[README.md]\n{repo_ctx['readme_text'] or '(README 없음)'}\n\n"
        f"[주요 의존성 / 설정 / 아키텍처 파일]\n{files_summary}\n\n"
        f"[최근 커밋 이력]\n{commits_summary}"
    )

    llm = get_smart_llm(temperature=0.3)
    synthesized = await ainvoke_structured(
        llm,
        GitHubPortfolioSynthesisSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=1,
    )

    return {
        "project": {
            "name": synthesized.name or repo_ctx["repo"],
            "period": synthesized.period or repo_ctx["period_hint"],
            "role": synthesized.role or role_hint or "풀스택 / AI 개발",
            "summary": synthesized.summary or repo_ctx["description"],
            "tech_stack": synthesized.tech_stack or repo_ctx["languages"],
            "portfolio_goal_link": synthesized.portfolio_goal_link,
            "repo_url": repo_ctx["html_url"],
        },
        "portfolio_markdown": synthesized.portfolio_markdown,
        "suggested_experiences": [e.model_dump() for e in synthesized.suggested_experiences],
        "repo_meta": {
            "full_name": repo_ctx["full_name"],
            "stars": repo_ctx["stars"],
            "languages": repo_ctx["languages"],
            "default_branch": repo_ctx["default_branch"],
            "commits_sampled": len(repo_ctx["commits"]),
            "files_analyzed": list(repo_ctx["inspected_files"].keys()),
        },
    }
