"""모듈형 포트폴리오 섹션 관리, 문서 기반 자동 업데이트 Diff 제안, AI 노이즈 정리(Prune) 엔진."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_smart_llm

logger = logging.getLogger(__name__)

STANDARD_SECTIONS: list[dict[str, Any]] = [
    {
        "section_type": "overview",
        "title": "1. 개요 & 문제 정의",
        "display_order": 1,
        "placeholder": "프로젝트 배경, 해결하려던 핵심 문제, 일정·인원·인프라 제약조건을 정리합니다.",
    },
    {
        "section_type": "architecture",
        "title": "2. 시스템 아키텍처 & 기술 스택",
        "display_order": 2,
        "placeholder": "전체 서비스/데이터 흐름, 핵심 컴포넌트, DB/인프라 구성(Mermaid 다이어그램 포함)을 정리합니다.",
    },
    {
        "section_type": "decisions",
        "title": "3. 핵심 기술 의사결정 (Mini-ADR)",
        "display_order": 3,
        "placeholder": "주요 기술 선택의 배경 → 선택 → 비교한 대안 → 수용한 트레이드오프를 기록합니다.",
    },
    {
        "section_type": "implementation",
        "title": "4. 담당 역할 & 핵심 구현",
        "display_order": 4,
        "placeholder": "본인이 직접 설계·구현한 기능 모듈과 코드 구조 포인트를 정리합니다.",
    },
    {
        "section_type": "troubleshooting",
        "title": "5. 트러블슈팅 & 성능 개선",
        "display_order": 5,
        "placeholder": "장애/병목 계측 원인 → 해결 과정 → 재발 방지 설계를 기록합니다.",
    },
    {
        "section_type": "outcomes",
        "title": "6. 성과, 정량 지표 & 회고",
        "display_order": 6,
        "placeholder": "측정 가능한 성과 지표, 배포/운영 결과, 배운 점과 향후 개선 방향을 정리합니다.",
    },
]

STANDARD_SECTION_MAP = {s["section_type"]: s for s in STANDARD_SECTIONS}


def render_portfolio_markdown(
    project: dict[str, Any], sections: list[dict[str, Any]]
) -> str:
    """구조화된 프로젝트 메타와 섹션 목록을 노션/이력서용 Markdown으로 결정론적 렌더링한다."""
    lines: list[str] = [f"# {project.get('name') or 'Untitled Project'}"]

    meta_parts: list[str] = []
    if project.get("period"):
        meta_parts.append(f"**기간:** {project['period']}")
    if project.get("role"):
        meta_parts.append(f"**역할:** {project['role']}")
    if project.get("repo_url"):
        meta_parts.append(f"**Repository:** {project['repo_url']}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))

    if project.get("summary"):
        lines.append(f"\n> {project['summary']}")

    tech_stack = project.get("tech_stack") or []
    if tech_stack:
        tags = " ".join(f"`{t}`" for t in tech_stack)
        lines.append(f"\n**기술 스택:** {tags}")

    if project.get("portfolio_goal_link"):
        lines.append(f"\n**커리어 비전 연결:** {project['portfolio_goal_link']}")

    ordered = sorted(
        sections,
        key=lambda s: (int(s.get("display_order") or 99), int(s.get("id") or 0)),
    )
    for sec in ordered:
        content = (sec.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"\n---\n\n## {sec.get('title') or sec.get('section_type')}\n\n{content}")

    return "\n".join(lines).strip()


# ==============================================================================
# 1. 문서 / GitHub 변경분 → 섹션별 자동 업데이트 제안 (Diff-Merge)
# ==============================================================================
class SectionUpdateProposalItem(BaseModel):
    section_type: str = Field(
        default="overview",
        description="대상 섹션 타입 (overview, architecture, decisions, implementation, troubleshooting, outcomes 또는 custom)",
    )
    title: str = Field(default="", description="섹션 제목")
    action: str = Field(default="update", description="'create' 또는 'update'")
    change_summary: str = Field(
        default="", description="신규 문서에서 어떤 내용이 추가/보강되었는지 1~2문장 요약"
    )
    proposed_content: str = Field(
        default="",
        description="기존 내용의 핵심을 유지하면서 신규 문서의 사실을 자연스럽게 통합한 Markdown 본문",
    )


class ExtractedStarDraft(BaseModel):
    title: str = Field(default="", description="STAR 경험 제목 (30자 내외)")
    situation: str = Field(default="")
    task: str = Field(default="")
    action: str = Field(default="")
    result: str = Field(default="")
    quantified_metrics: str = Field(
        default="", description="문서에 실제 명시된 수치만 기재 (없으면 빈 문자열)"
    )


class DocumentUpdateProposalSchema(BaseModel):
    document_summary: str = Field(
        default="", description="업로드된 문서의 핵심 내용 1~2문장 요약"
    )
    suggested_summary: str = Field(
        default="",
        description="프로젝트 한 줄~두 줄 요약을 보강할 필요가 있을 때만 제안 (불필요 시 빈 문자열)",
    )
    suggested_tech_stack_additions: list[str] = Field(
        default_factory=list,
        description="기존 tech_stack에 없지만 문서에서 새롭게 확인된 기술명",
    )
    section_updates: list[SectionUpdateProposalItem] = Field(
        default_factory=list,
        description="신규 문서의 근거로 실제로 업데이트가 필요한 섹션 목록만 포함",
    )
    suggested_experiences: list[ExtractedStarDraft] = Field(
        default_factory=list,
        description="문서에서 새롭게 추출된 핵심 STAR 경험 초안 (0~3건)",
    )


async def propose_document_updates(
    *,
    project: dict[str, Any],
    existing_sections: list[dict[str, Any]],
    doc_text: str,
    filename: str,
    user_instruction: str = "",
) -> dict[str, Any]:
    """업로드된 문서와 기존 포트폴리오 섹션을 대조해 섹션별 안전한 업데이트 Diff 제안을 생성한다."""
    existing_map = {s["section_type"]: s for s in existing_sections}

    existing_blocks = []
    for std in STANDARD_SECTIONS:
        st = std["section_type"]
        cur = existing_map.get(st)
        body = (cur.get("content") if cur else "") or "(아직 비어 있음)"
        existing_blocks.append(f"### [{st}] {std['title']}\n{body}")

    for sec in existing_sections:
        if sec["section_type"] not in STANDARD_SECTION_MAP:
            existing_blocks.append(
                f"### [{sec['section_type']}] {sec['title']}\n{sec.get('content') or '(비어 있음)'}"
            )

    system_prompt = (
        "당신은 시니어 소프트웨어 엔지니어의 포트폴리오 편집 어시스턴트입니다.\n"
        "새로 들어온 문서/자료의 사실만을 근거로 기존 포트폴리오의 알맞은 섹션에 내용을 통합·업데이트하는 제안을 만드세요.\n"
        "엄격한 규칙:\n"
        "1. 문서에 없는 성능 수치, 사용자 수, 트래픽, 기술명을 절대 지어내지 마세요.\n"
        "2. 기존 섹션에 이미 잘 적혀 있는 구체적인 사실은 삭제하지 말고, 새 문서의 정보와 중복 없이 깔끔하게 병합하세요.\n"
        "3. 새 문서가 유의미한 정보를 제공하지 않는 섹션은 `section_updates`에 포함하지 마세요.\n"
        "4. `section_type`은 가능한 6대 표준 키(`overview`, `architecture`, `decisions`, `implementation`, `troubleshooting`, `outcomes`) 중 가장 알맞은 곳에 배치하세요.\n"
        "5. 각 섹션 본문(`proposed_content`)은 불릿 포인트와 굵은 키워드 위주의 읽기 쉬운 한국어 Markdown으로 작성하세요."
    )

    user_prompt = (
        f"[프로젝트 정보]\n"
        f"- 이름: {project.get('name')}\n"
        f"- 역할: {project.get('role')}\n"
        f"- 요약: {project.get('summary')}\n"
        f"- 기존 기술 스택: {', '.join(project.get('tech_stack') or [])}\n\n"
        f"[현재 포트폴리오 섹션 내용]\n" + "\n\n".join(existing_blocks) + "\n\n"
        f"[새로 업로드된 문서: {filename}]\n"
        f"[사용자 추가 지시] {user_instruction or '문서 내용을 알맞은 섹션에 반영해 주세요.'}\n\n"
        f"{doc_text[:18000]}"
    )

    llm = get_smart_llm(temperature=0.25)
    proposal = await ainvoke_structured(
        llm,
        DocumentUpdateProposalSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=1,
    )

    enriched_updates = []
    for item in proposal.section_updates:
        st = item.section_type.strip() or "overview"
        cur = existing_map.get(st)
        std = STANDARD_SECTION_MAP.get(st)
        title = item.title.strip() or (
            cur["title"] if cur else (std["title"] if std else st)
        )
        enriched_updates.append(
            {
                "section_id": cur["id"] if cur else None,
                "section_type": st,
                "title": title,
                "action": "update" if cur and (cur.get("content") or "").strip() else "create",
                "change_summary": item.change_summary.strip(),
                "before_content": (cur.get("content") or "") if cur else "",
                "proposed_content": item.proposed_content.strip(),
            }
        )

    existing_stack_lower = {t.lower() for t in (project.get("tech_stack") or [])}
    new_stack = [
        t.strip()
        for t in proposal.suggested_tech_stack_additions
        if t.strip() and t.strip().lower() not in existing_stack_lower
    ]

    return {
        "document_summary": proposal.document_summary.strip(),
        "suggested_summary": proposal.suggested_summary.strip(),
        "suggested_tech_stack_additions": new_stack,
        "section_updates": enriched_updates,
        "suggested_experiences": [e.model_dump() for e in proposal.suggested_experiences if e.title.strip()],
    }


# ==============================================================================
# 2. 불필요한 내용 정리 / AI 노이즈 삭제 (Prune & Tighten)
# ==============================================================================
class SectionPruneItem(BaseModel):
    section_type: str = Field(description="정리 대상 섹션 타입")
    removed_items: list[str] = Field(
        default_factory=list,
        description="제거·축소한 불필요한 표현, 중복 문장, 사소한 내용 목록",
    )
    reason: str = Field(default="", description="정리 이유 1문장")
    cleaned_content: str = Field(
        default="", description="핵심 기술 근거와 수치만 남겨 압축·정제한 Markdown 본문"
    )


class PortfolioPruneSchema(BaseModel):
    overall_assessment: str = Field(
        default="", description="포트폴리오 전체 밀도 및 정리 방향 1~2문장 진단"
    )
    section_prunes: list[SectionPruneItem] = Field(
        default_factory=list,
        description="불필요하거나 중복된 내용이 발견되어 정리가 필요한 섹션 목록",
    )


async def propose_noise_pruning(
    *,
    project: dict[str, Any],
    existing_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """포트폴리오 섹션 전체를 점검해 추상적 미사여구·중복·사소한 셋업 내용을 제거한 압축안을 제안한다."""
    non_empty = [s for s in existing_sections if (s.get("content") or "").strip()]
    if not non_empty:
        return {
            "overall_assessment": "정리할 섹션 내용이 아직 없습니다.",
            "section_prunes": [],
        }

    sec_by_type = {s["section_type"]: s for s in non_empty}
    blocks = [
        f"### [{s['section_type']}] {s['title']}\n{s['content']}" for s in non_empty
    ]

    system_prompt = (
        "당신은 채용 담당자와 테크 리드 관점에서 포트폴리오의 군더더기를 걷어내는 엄격한 기술 에디터입니다.\n"
        "아래 4가지 불필요한 노이즈를 탐지해 과감히 제거·압축하세요:\n"
        "1. 추상적 미사여구·AI 상투어 (예: '혁신적인', '성공적으로 구현', '한 단계 성장', '최적의 시너지')\n"
        "2. 다른 섹션과 중복 서술된 내용 (가장 적합한 섹션 1곳에만 남김)\n"
        "3. 엔지니어링 변별력이 낮은 사소한 작업 나열 (단순 패키지 설치, 뻔한 기본 CRUD 설명 등)\n"
        "4. 장황한 서론·배경 설명\n\n"
        "규칙:\n"
        "- 실제 기술명, 아키텍처 의사결정, 트레이드오프, 계측된 정량 수치는 절대 지우지 마세요.\n"
        "- 원문에 없는 새로운 사실이나 수치를 추가하지 마세요.\n"
        "- 이미 충분히 간결해 고칠 게 없는 섹션은 `section_prunes`에 넣지 마세요.\n"
        "- 무엇을 지웠는지 `removed_items`에 명확히 적어 사용자가 확인 후 승인할 수 있게 하세요."
    )

    user_prompt = (
        f"[프로젝트명] {project.get('name')} ({project.get('role')})\n\n"
        f"[현재 섹션 전체]\n" + "\n\n".join(blocks)
    )

    llm = get_smart_llm(temperature=0.2)
    result = await ainvoke_structured(
        llm,
        PortfolioPruneSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=1,
    )

    items = []
    for p in result.section_prunes:
        cur = sec_by_type.get(p.section_type)
        if not cur:
            continue
        cleaned = p.cleaned_content.strip()
        if cleaned == (cur.get("content") or "").strip():
            continue
        items.append(
            {
                "section_id": cur["id"],
                "section_type": cur["section_type"],
                "title": cur["title"],
                "removed_items": [r.strip() for r in p.removed_items if r.strip()],
                "reason": p.reason.strip(),
                "before_content": cur.get("content") or "",
                "cleaned_content": cleaned,
            }
        )

    return {
        "overall_assessment": result.overall_assessment.strip(),
        "section_prunes": items,
    }
