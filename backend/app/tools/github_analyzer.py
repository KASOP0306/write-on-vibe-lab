"""안정화된 GitHub 저장소 딥 분석기 (Rate-Limit 방어 + 트리 스캔 + 6개 모듈 섹션 자동 생성).

핵심 개선점:
1. urlparse 기반 유연한 URL 파싱 (?tab=..., #readme, .git, /tree/..., git@github.com:... 지원)
2. git/trees/{branch}?recursive=1 (1회) + raw.githubusercontent.com (무제한 CDN)으로
   GitHub REST API 호출을 기존 최대 12회 -> 최대 3회로 축소
3. Public 레포에서 API 403 Rate Limit 발생 시 raw.githubusercontent.com + HTML 폴백 지원
4. 선택적 1회용 github_token(Private 레포/높은 Rate Limit용, DB 미저장) 지원
5. 거대 Markdown JSON 깨짐 방지를 위해 6개 구조화 섹션만 추출 후 Markdown은 결정론적 렌더링
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.core.bedrock import ainvoke_structured, get_smart_llm
from app.core.project_templates import (
    compose_sections_for_types,
    get_combined_ai_guidance,
    normalize_project_types,
)
from app.tools.portfolio_manager import render_portfolio_markdown

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

HIGH_PRIORITY_FILENAMES = {
    "readme.md": 100,
    "architecture.md": 95,
    "design.md": 90,
    "workflows.md": 88,
    "docker-compose.yml": 85,
    "docker-compose.yaml": 85,
    "dockerfile": 80,
    "pyproject.toml": 80,
    "requirements.txt": 78,
    "package.json": 78,
    "pom.xml": 75,
    "build.gradle": 75,
    "go.mod": 75,
    "cargo.toml": 75,
    "main.py": 72,
    "app.py": 72,
    "server.py": 70,
    "index.ts": 68,
    "index.js": 65,
    "schema.sql": 70,
    "init.sql": 68,
}

CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".sql", ".md", ".ipynb"}
IGNORE_PATH_PARTS = (
    "node_modules/",
    ".git/",
    "dist/",
    "build/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "vendor/",
    ".next/",
    "coverage/",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
)


class GitHubAnalyzerError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ModularSectionDraft(BaseModel):
    section_type: str = Field(
        default="overview",
        description="overview | architecture | decisions | implementation | troubleshooting | outcomes",
    )
    title: str = Field(default="")
    content: str = Field(default="", description="한국어 Markdown 본문 (확인된 사실만 기재)")


class SuggestedStarItem(BaseModel):
    title: str = Field(default="", description="핵심 구현/설계 경험 제목 (30자 내외)")
    situation: str = Field(default="")
    task: str = Field(default="")
    action: str = Field(default="")
    result: str = Field(default="")
    quantified_metrics: str = Field(
        default="", description="레포 문서에 실제 명시된 수치만 기재 (없으면 빈 문자열)"
    )


class GitHubStructuredPortfolioSchema(BaseModel):
    name: str = Field(default="", description="포트폴리오 프로젝트명")
    period: str = Field(default="", description="개발 기간 (예: 2026.10 - 2026.11)")
    role: str = Field(default="", description="담당 역할")
    summary: str = Field(default="", description="프로젝트 핵심 요약 (2~3문장)")
    tech_stack: list[str] = Field(
        default_factory=list, description="실제 코드·의존성에서 확인된 기술 스택 (최대 12개)"
    )
    portfolio_goal_link: str = Field(
        default="", description="지원자 커리어 비전·신념과 연결되는 지점"
    )
    sections: list[ModularSectionDraft] = Field(
        default_factory=list,
        description="6개 표준 포트폴리오 모듈(overview, architecture, decisions, implementation, troubleshooting, outcomes)",
    )
    suggested_experiences: list[SuggestedStarItem] = Field(
        default_factory=list,
        description="저장소에서 추출한 핵심 STAR 경험 초안 1~3건",
    )


def parse_github_url(repo_url: str) -> tuple[str, str]:
    """다양한 GitHub URL 형식(?tab=, #readme, .git, /tree/, git@github.com:, owner/repo)에서 (owner, repo)를 추출한다."""
    raw = (repo_url or "").strip()
    if not raw:
        raise GitHubAnalyzerError("GitHub 저장소 URL을 입력해 주세요.", status_code=400)

    # SSH 형식: git@github.com:owner/repo.git
    ssh_match = re.match(
        r"^git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$",
        raw,
        re.IGNORECASE,
    )
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    # 단축 형식: owner/repo
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", raw):
        owner, repo = raw.split("/", 1)
        return owner, repo.removesuffix(".git")

    normalized = raw if re.match(r"^https?://", raw, re.IGNORECASE) else f"https://{raw}"
    parsed = urlparse(normalized)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if host != "github.com":
        raise GitHubAnalyzerError(
            "올바른 GitHub 저장소 주소 형식이 아닙니다. (예: https://github.com/owner/repo)",
            status_code=400,
        )

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise GitHubAnalyzerError(
            "저장소 소유자와 이름이 모두 포함된 GitHub URL을 입력해 주세요. (예: https://github.com/owner/repo)",
            status_code=400,
        )

    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    if not owner or not repo:
        raise GitHubAnalyzerError("유효한 GitHub 저장소 주소가 아닙니다.", status_code=400)
    return owner, repo


def _build_github_headers(*, token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "career-agent-github-analyzer/2.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    effective_token = (token or "").strip() or (settings.github_token or "").strip()
    if effective_token:
        headers["Authorization"] = f"Bearer {effective_token}"
    return headers


def _score_repo_file(path: str) -> int:
    lower = path.lower()
    if any(part in lower for part in IGNORE_PATH_PARTS):
        return -100
    basename = lower.rsplit("/", 1)[-1]
    depth = lower.count("/")

    if basename in HIGH_PRIORITY_FILENAMES:
        return HIGH_PRIORITY_FILENAMES[basename] - depth * 4

    ext = "." + basename.rsplit(".", 1)[-1] if "." in basename else ""
    if ext not in CODE_EXTENSIONS:
        return -50

    score = 30 - depth * 5
    if any(k in lower for k in ("graph", "agent", "pipeline", "dag", "model", "router", "service", "core", "api", "etl", "spark")):
        score += 22
    if ext == ".md":
        score += 15
    if "test" in lower:
        score -= 15
    return score


async def _fetch_raw_file(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    branch: str,
    path: str,
    *,
    token: str | None = None,
    max_chars: int = 2400,
) -> tuple[str, str]:
    url = f"{GITHUB_RAW_BASE}/{owner}/{repo}/{branch}/{path}"
    headers = {"User-Agent": "career-agent-github-analyzer/2.0"}
    effective_token = (token or "").strip() or (settings.github_token or "").strip()
    if effective_token:
        headers["Authorization"] = f"Bearer {effective_token}"
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            text = resp.text
            if path.lower().endswith(".ipynb"):
                # 노트북은 셀 텍스트만 경량 추출
                from app.tools.document_parser import parse_uploaded_file

                try:
                    parsed = parse_uploaded_file(path, resp.content)
                    text = parsed["text"]
                except Exception:
                    text = text[:max_chars]
            return path, text[:max_chars]
    except Exception as exc:
        logger.debug("Raw fetch failed (%s): %s", path, exc)
    return path, ""


async def _fallback_fetch_public_raw(
    client: httpx.AsyncClient, owner: str, repo: str
) -> dict[str, Any]:
    """GitHub API 403 Rate Limit 발생 시 Public 레포를 raw.githubusercontent.com으로 폴백 수집."""
    candidate_branches = ("main", "master")
    candidate_files = (
        "README.md",
        "readme.md",
        "ARCHITECTURE.md",
        "docker-compose.yml",
        "requirements.txt",
        "package.json",
        "pyproject.toml",
        "backend/requirements.txt",
        "frontend/package.json",
    )

    branch_found = "main"
    inspected: dict[str, str] = {}
    for br in candidate_branches:
        results = await asyncio.gather(
            *(_fetch_raw_file(client, owner, repo, br, f, max_chars=4500 if "readme" in f.lower() else 1800) for f in candidate_files)
        )
        found = {p: c for p, c in results if c.strip()}
        if found:
            branch_found = br
            inspected = found
            break

    if not inspected:
        raise GitHubAnalyzerError(
            "GitHub API 요청 한도(403)에 도달했고 기본 브랜치(main/master)에서 공개 파일을 찾지 못했습니다. "
            "잠시 후 다시 시도하거나 GitHub 토큰(PAT)을 입력해 주세요.",
            status_code=429,
        )

    readme_text = inspected.pop("README.md", "") or inspected.pop("readme.md", "")
    return {
        "owner": owner,
        "repo": repo,
        "full_name": f"{owner}/{repo}",
        "html_url": f"https://github.com/{owner}/{repo}",
        "description": "",
        "topics": [],
        "stars": 0,
        "default_branch": branch_found,
        "period_hint": "",
        "languages": [],
        "tree_paths": list(inspected.keys()),
        "readme_text": readme_text,
        "inspected_files": inspected,
        "commits": [],
        "used_raw_fallback": True,
    }


async def fetch_github_repo_context(
    repo_url: str, *, github_token: str | None = None
) -> dict[str, Any]:
    """최소 API 호출(최대 3회) + raw.githubusercontent.com으로 저장소 전체 트리·핵심 코드·README·커밋을 수집한다."""
    owner, repo = parse_github_url(repo_url)
    base = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    headers = _build_github_headers(token=github_token)

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        repo_resp = await client.get(base, headers=headers)
        if repo_resp.status_code == 404:
            raise GitHubAnalyzerError(
                f"저장소 '{owner}/{repo}'를 찾을 수 없습니다. 주소 오타이거나 비공개(Private) 저장소인 경우 GitHub PAT를 입력해 주세요.",
                status_code=404,
            )
        if repo_resp.status_code == 403:
            logger.warning("GitHub API 403 rate-limit hit for %s/%s — using raw fallback.", owner, repo)
            return await _fallback_fetch_public_raw(client, owner, repo)
        if repo_resp.status_code >= 400:
            raise GitHubAnalyzerError(
                f"GitHub 저장소 조회 실패 (HTTP {repo_resp.status_code})",
                status_code=502,
            )

        repo_data = repo_resp.json()
        default_branch = repo_data.get("default_branch") or "main"

        # 단 2회의 추가 API 호출: 전체 재귀 트리 + 최근 커밋 15건
        tree_task = client.get(
            f"{base}/git/trees/{default_branch}",
            params={"recursive": "1"},
            headers=headers,
        )
        commits_task = client.get(
            f"{base}/commits",
            params={"per_page": 15},
            headers=headers,
        )
        tree_resp, commits_resp = await asyncio.gather(
            tree_task, commits_task, return_exceptions=True
        )

        all_paths: list[str] = []
        if isinstance(tree_resp, httpx.Response) and tree_resp.status_code == 200:
            for node in tree_resp.json().get("tree") or []:
                if node.get("type") == "blob" and node.get("path"):
                    all_paths.append(str(node["path"]))

        # 확장자 기반 언어 추정 (추가 API 호출 절약)
        ext_lang_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".java": "Java",
            ".kt": "Kotlin",
            ".go": "Go",
            ".rs": "Rust",
            ".sql": "SQL",
            ".ipynb": "Jupyter Notebook",
            ".sh": "Shell",
        }
        languages_seen: list[str] = []
        if repo_data.get("language"):
            languages_seen.append(str(repo_data["language"]))
        for p in all_paths:
            low = p.lower()
            for ext, lang_name in ext_lang_map.items():
                if low.endswith(ext) and lang_name not in languages_seen:
                    languages_seen.append(lang_name)

        # 전체 트리에서 가장 가치 높은 파일 최대 10개 선별 후 raw.githubusercontent.com으로 병렬 읽기 (API 제한 0)
        scored_files = sorted(
            ((p, _score_repo_file(p)) for p in all_paths),
            key=lambda pair: pair[1],
            reverse=True,
        )
        selected_paths = [p for p, sc in scored_files if sc > 0][:10]
        if not selected_paths:
            selected_paths = ["README.md", "requirements.txt", "package.json"]

        raw_results = await asyncio.gather(
            *(
                _fetch_raw_file(
                    client,
                    owner,
                    repo,
                    default_branch,
                    p,
                    token=github_token,
                    max_chars=5000 if p.lower().endswith("readme.md") else 2000,
                )
                for p in selected_paths
            )
        )

        readme_text = ""
        inspected_files: dict[str, str] = {}
        for p, content in raw_results:
            if not content.strip():
                continue
            if p.lower() == "readme.md" and not readme_text:
                readme_text = content
            else:
                inspected_files[p] = content

        commits: list[str] = []
        if isinstance(commits_resp, httpx.Response) and commits_resp.status_code == 200:
            raw_commits = commits_resp.json()
            if isinstance(raw_commits, list):
                for c in raw_commits[:15]:
                    commit_obj = c.get("commit") or {}
                    msg = str(commit_obj.get("message") or "").splitlines()[0][:120]
                    date_str = str((commit_obj.get("author") or {}).get("date") or "")[:10]
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
        "default_branch": default_branch,
        "period_hint": period_hint,
        "languages": languages_seen,
        "tree_paths": all_paths[:120],
        "readme_text": readme_text,
        "inspected_files": inspected_files,
        "commits": commits,
        "used_raw_fallback": False,
    }


def format_repo_context_as_document(repo_ctx: dict[str, Any]) -> str:
    """기존 프로젝트의 GitHub 재동기화(Diff-Merge)에 재사용할 수 있도록 저장소 정보를 문서 텍스트로 직렬화한다."""
    files_summary = "\n\n".join(
        f"--- {path} ---\n{content}"
        for path, content in (repo_ctx.get("inspected_files") or {}).items()
    ) or "(확인된 주요 파일 없음)"
    commits_summary = "\n".join(repo_ctx.get("commits") or []) or "(커밋 내역 없음)"
    tree_summary = ", ".join((repo_ctx.get("tree_paths") or [])[:80])

    return (
        f"[GitHub 저장소] {repo_ctx['full_name']} ({repo_ctx['html_url']})\n"
        f"[설명] {repo_ctx.get('description') or '(없음)'}\n"
        f"[토픽] {', '.join(repo_ctx.get('topics') or []) or '(없음)'}\n"
        f"[추정 기간] {repo_ctx.get('period_hint') or '(미상)'}\n"
        f"[감지 언어] {', '.join(repo_ctx.get('languages') or []) or '(없음)'}\n\n"
        f"[파일 트리 요약]\n{tree_summary}\n\n"
        f"[README.md]\n{repo_ctx.get('readme_text') or '(README 없음)'}\n\n"
        f"[핵심 코드·설정·문서 발췌]\n{files_summary}\n\n"
        f"[최근 커밋 이력]\n{commits_summary}"
    )


async def synthesize_portfolio_from_context(
    repo_ctx: dict[str, Any],
    *,
    project_types: list[str] | None = None,
    role_hint: str = "",
    extra_context: str = "",
    profile_context: str = "",
) -> dict[str, Any]:
    """수집된 GitHub 저장소 컨텍스트에서 선택한 복수 유형(트랙) 섹션 + 프로젝트 메타 + STAR 경험 초안을 생성한다."""
    normalized_types = normalize_project_types(project_types)
    target_sections = compose_sections_for_types(normalized_types)
    guidance = get_combined_ai_guidance(normalized_types)
    repo_doc = format_repo_context_as_document(repo_ctx)

    section_spec_lines = "\n".join(
        f"- `{s['section_type']}` ({s['title']}): {s['placeholder']}"
        for s in target_sections
    )

    system_prompt = (
        f"당신은 {guidance['persona']}입니다.\n"
        f"제공된 GitHub 저장소의 실제 코드 트리, README, 핵심 소스코드, 의존성, 커밋 이력만을 근거로 "
        f"[{guidance['labels']}] 포트폴리오 프로젝트 정보, 아래 목표 섹션, STAR 경험 초안 1~3건을 한국어로 구조화하세요.\n\n"
        f"[작성할 목표 섹션(`sections`) 키]\n{section_spec_lines}\n\n"
        "엄격한 규칙:\n"
        "1. 저장소에 없는 수치(예: 속도 50% 향상, MAU 등)는 절대 지어내지 마세요. 정량 수치가 없으면 `quantified_metrics`는 빈 문자열로 두세요.\n"
        "2. 각 섹션 `content`는 불릿 포인트 위주의 간결한 한국어 Markdown으로 작성하세요.\n"
        "3. `tech_stack`은 실제 코드/의존성에서 확인된 핵심 기술·도구만 최대 12개로 추리세요."
    )

    user_prompt = (
        f"[선택된 프로젝트 유형] {guidance['labels']}\n"
        f"[사용자 역할 힌트] {role_hint or '(미입력 — 레포 구성으로 추정)'}\n"
        f"[사용자 추가 메모] {extra_context or '(없음)'}\n"
        f"[지원자 커리어 신념/비전]\n{profile_context or '(미설정)'}\n\n"
        f"{repo_doc[:19000]}"
    )

    llm = get_smart_llm(temperature=0.25)
    synthesized = await ainvoke_structured(
        llm,
        GitHubStructuredPortfolioSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=1,
    )

    gen_by_type = {s.section_type.strip(): s for s in synthesized.sections if s.content.strip()}
    normalized_sections: list[dict[str, Any]] = []
    for tpl in target_sections:
        st = tpl["section_type"]
        gen = gen_by_type.get(st)
        normalized_sections.append(
            {
                "section_type": st,
                "track": tpl["track"],
                "title": (gen.title.strip() if gen and gen.title.strip() else tpl["title"]),
                "content": gen.content.strip() if gen else "",
                "display_order": tpl["display_order"],
            }
        )

    project_dict = {
        "name": synthesized.name.strip() or repo_ctx["repo"],
        "period": synthesized.period.strip() or repo_ctx.get("period_hint", ""),
        "role": synthesized.role.strip() or role_hint or "풀스택 / AI 개발",
        "summary": synthesized.summary.strip() or repo_ctx.get("description", ""),
        "tech_stack": [t.strip() for t in synthesized.tech_stack if t.strip()][:12]
        or repo_ctx.get("languages", []),
        "portfolio_goal_link": synthesized.portfolio_goal_link.strip(),
        "repo_url": repo_ctx["html_url"],
        "project_types": normalized_types,
        "artifact_links": [],
    }

    portfolio_markdown = render_portfolio_markdown(project_dict, normalized_sections)

    return {
        "project": project_dict,
        "sections": normalized_sections,
        "portfolio_markdown": portfolio_markdown,
        "suggested_experiences": [
            e.model_dump() for e in synthesized.suggested_experiences if e.title.strip()
        ],
        "repo_meta": {
            "full_name": repo_ctx["full_name"],
            "stars": repo_ctx.get("stars", 0),
            "languages": repo_ctx.get("languages", []),
            "default_branch": repo_ctx.get("default_branch", "main"),
            "commits_sampled": len(repo_ctx.get("commits") or []),
            "total_files_in_tree": len(repo_ctx.get("tree_paths") or []),
            "files_analyzed": (
                (["README.md"] if repo_ctx.get("readme_text") else [])
                + list((repo_ctx.get("inspected_files") or {}).keys())
            ),
            "used_raw_fallback": bool(repo_ctx.get("used_raw_fallback")),
        },
    }


async def analyze_github_to_portfolio(
    repo_url: str,
    *,
    project_types: list[str] | None = None,
    github_token: str | None = None,
    role_hint: str = "",
    extra_context: str = "",
    profile_context: str = "",
) -> dict[str, Any]:
    repo_ctx = await fetch_github_repo_context(repo_url, github_token=github_token)
    return await synthesize_portfolio_from_context(
        repo_ctx,
        project_types=project_types,
        role_hint=role_hint,
        extra_context=extra_context,
        profile_context=profile_context,
    )
