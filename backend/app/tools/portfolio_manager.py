"""조합형 멀티트랙 포트폴리오 렌더링, 문서 기반 프로젝트 자동 생성, Diff-Merge 업데이트, AI 노이즈 정리 엔진."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_smart_llm
from app.core.project_templates import (
    ALL_KNOWN_SECTIONS,
    TRACK_PACKS,
    compose_sections_for_types,
    get_combined_ai_guidance,
    get_track_labels,
    infer_track_for_section_type,
    normalize_project_types,
)

logger = logging.getLogger(__name__)

# 하위 호환용 alias (기존 테스트/참조 유지)
STANDARD_SECTIONS = compose_sections_for_types(["engineering"])
STANDARD_SECTION_MAP = ALL_KNOWN_SECTIONS


def render_portfolio_markdown(
    project: dict[str, Any], sections: list[dict[str, Any]]
) -> str:
    """구조화된 멀티트랙 프로젝트 메타와 섹션 목록을 노션/이력서용 Markdown으로 결정론적 렌더링한다."""
    lines: list[str] = [f"# {project.get('name') or 'Untitled Project'}"]

    project_types = normalize_project_types(project.get("project_types"))
    type_labels = get_track_labels(project_types)
    if type_labels:
        lines.append(f"**프로젝트 유형:** {' · '.join(type_labels)}")

    meta_parts: list[str] = []
    if project.get("period"):
        meta_parts.append(f"**기간:** {project['period']}")
    if project.get("role"):
        meta_parts.append(f"**역할:** {project['role']}")
    if project.get("repo_url"):
        meta_parts.append(f"**Repository:** {project['repo_url']}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))

    artifact_links = project.get("artifact_links") or []
    if artifact_links:
        link_md = " · ".join(
            f"[{item.get('label') or item.get('url')}]({item.get('url')})"
            for item in artifact_links
            if item.get("url")
        )
        if link_md:
            lines.append(f"**참고 링크:** {link_md}")

    if project.get("summary"):
        lines.append(f"\n> {project['summary']}")

    tech_stack = project.get("tech_stack") or []
    if tech_stack:
        tags = " ".join(f"`{t}`" for t in tech_stack)
        primary_label = (
            TRACK_PACKS[project_types[0]]["skills_label"]
            if len(project_types) == 1
            else "핵심 기술 · 역량 · 툴"
        )
        lines.append(f"\n**{primary_label}:** {tags}")

    if project.get("portfolio_goal_link"):
        lines.append(f"\n**커리어 비전 연결:** {project['portfolio_goal_link']}")

    ordered = sorted(
        sections,
        key=lambda s: (int(s.get("display_order") or 500), int(s.get("id") or 0)),
    )
    for sec in ordered:
        content = (sec.get("content") or "").strip()
        if not content:
            continue
        track_id = sec.get("track") or infer_track_for_section_type(
            sec.get("section_type") or ""
        )
        track_prefix = ""
        if track_id in TRACK_PACKS and len(project_types) > 1:
            track_prefix = f"[{TRACK_PACKS[track_id]['short_label']}] "
        lines.append(
            f"\n---\n\n## {track_prefix}{sec.get('title') or sec.get('section_type')}\n\n{content}"
        )

    return "\n".join(lines).strip()


# ==============================================================================
# 1. 문서·발표자료 기반 멀티트랙 포트폴리오 프로젝트 신규 자동 생성
# ==============================================================================
class GeneratedSectionDraft(BaseModel):
    section_type: str = Field(default="overview")
    title: str = Field(default="")
    content: str = Field(default="", description="한국어 Markdown 본문 (문서 사실만 기재)")


class ExtractedStarDraft(BaseModel):
    title: str = Field(default="", description="STAR 경험 제목 (30자 내외)")
    situation: str = Field(default="")
    task: str = Field(default="")
    action: str = Field(default="")
    result: str = Field(default="")
    quantified_metrics: str = Field(
        default="", description="문서에 실제 명시된 수치만 기재 (없으면 빈 문자열)"
    )


class DocumentToPortfolioSchema(BaseModel):
    name: str = Field(default="", description="포트폴리오 프로젝트명")
    period: str = Field(default="", description="진행 기간 (문서에 있으면 기재)")
    role: str = Field(default="", description="담당 역할")
    summary: str = Field(default="", description="프로젝트 핵심 요약 (2~3문장)")
    tech_stack: list[str] = Field(
        default_factory=list,
        description="문서에서 확인된 기술 스택·분석 도구·핵심 역량/툴 키워드 (최대 12개)",
    )
    portfolio_goal_link: str = Field(
        default="", description="지원자 커리어 비전·신념과 연결되는 지점"
    )
    sections: list[GeneratedSectionDraft] = Field(
        default_factory=list,
        description="지정된 멀티트랙 섹션 키들에 맞춘 구조화 본문",
    )
    suggested_experiences: list[ExtractedStarDraft] = Field(
        default_factory=list,
        description="문서에서 추출한 핵심 STAR 경험 초안 1~3건",
    )


async def analyze_document_to_portfolio(
    *,
    doc_text: str,
    filename: str,
    project_types: list[str] | None = None,
    role_hint: str = "",
    extra_context: str = "",
    profile_context: str = "",
) -> dict[str, Any]:
    """업로드된 기획서·발표자료·보고서·노트에서 선택한 복수 유형(트랙)의 포트폴리오 초안을 자동 생성한다."""
    normalized_types = normalize_project_types(project_types)
    target_sections = compose_sections_for_types(normalized_types)
    guidance = get_combined_ai_guidance(normalized_types)

    section_spec_lines = "\n".join(
        f"- `{s['section_type']}` ({s['title']}): {s['placeholder']}"
        for s in target_sections
    )

    system_prompt = (
        f"당신은 {guidance['persona']}입니다.\n"
        f"사용자가 업로드한 문서({filename})만을 근거로 [{guidance['labels']}] 성격의 "
        "체계적인 멀티트랙 포트폴리오 프로젝트 초안과 STAR 경험 1~3건을 한국어로 구조화하세요.\n\n"
        f"[작성할 목표 섹션 목록]\n{section_spec_lines}\n\n"
        "엄격한 규칙:\n"
        "1. 문서에 없는 수치, 지표, 도구명, 성과는 절대 지어내지 마세요. 정량 수치가 없으면 `quantified_metrics`는 빈 문자열로 두세요.\n"
        "2. 각 섹션의 `section_type`은 위 목록의 키를 정확히 사용하고, 내용이 확인되는 섹션만 충실히 채우세요.\n"
        "3. 각 섹션 `content`는 불릿 포인트와 굵은 키워드 중심의 깔끔한 한국어 Markdown으로 작성하세요."
    )

    user_prompt = (
        f"[선택된 프로젝트 유형] {guidance['labels']}\n"
        f"[사용자 역할 힌트] {role_hint or '(미입력 — 문서 내용으로 추정)'}\n"
        f"[사용자 추가 메모] {extra_context or '(없음)'}\n"
        f"[지원자 커리어 신념/비전]\n{profile_context or '(미설정)'}\n\n"
        f"[문서 파일명: {filename}]\n{doc_text[:19000]}"
    )

    llm = get_smart_llm(temperature=0.25)
    synthesized = await ainvoke_structured(
        llm,
        DocumentToPortfolioSchema,
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
        "name": synthesized.name.strip() or filename.rsplit(".", 1)[0],
        "period": synthesized.period.strip(),
        "role": synthesized.role.strip() or role_hint,
        "summary": synthesized.summary.strip(),
        "tech_stack": [t.strip() for t in synthesized.tech_stack if t.strip()][:12],
        "portfolio_goal_link": synthesized.portfolio_goal_link.strip(),
        "repo_url": "",
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
    }


# ==============================================================================
# 2. 기존 프로젝트에 문서 / GitHub 변경분 → 트랙별 자동 분배 Diff-Merge
# ==============================================================================
class SectionUpdateProposalItem(BaseModel):
    section_type: str = Field(
        default="overview",
        description="대상 섹션 키 (현재 프로젝트에 구성된 섹션 키 중 가장 적합한 곳에 배치)",
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


class DocumentUpdateProposalSchema(BaseModel):
    document_summary: str = Field(
        default="", description="업로드된 문서의 핵심 내용 1~2문장 요약"
    )
    suggested_summary: str = Field(
        default="",
        description="프로젝트 핵심 요약을 보강할 필요가 있을 때만 제안 (불필요 시 빈 문자열)",
    )
    suggested_tech_stack_additions: list[str] = Field(
        default_factory=list,
        description="기존 목록에 없지만 문서에서 새롭게 확인된 기술·도구·방법론 키워드",
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
    """업로드된 문서를 프로젝트의 멀티트랙 섹션들에 알맞게 자동 분배·병합하는 Diff 제안을 생성한다."""
    project_types = normalize_project_types(project.get("project_types"))
    guidance = get_combined_ai_guidance(project_types)
    existing_map = {s["section_type"]: s for s in existing_sections}
    composed_templates = compose_sections_for_types(project_types)

    ordered_blocks = []
    seen_keys: set[str] = set()
    for sec in sorted(
        existing_sections,
        key=lambda s: (int(s.get("display_order") or 500), int(s.get("id") or 0)),
    ):
        st = sec["section_type"]
        seen_keys.add(st)
        track = sec.get("track") or infer_track_for_section_type(st)
        body = (sec.get("content") or "").strip() or "(아직 비어 있음)"
        ordered_blocks.append(f"### [{st} | track:{track}] {sec['title']}\n{body}")

    for tpl in composed_templates:
        if tpl["section_type"] not in seen_keys:
            ordered_blocks.append(
                f"### [{tpl['section_type']} | track:{tpl['track']}] {tpl['title']}\n(아직 비어 있음)"
            )

    allowed_keys = ", ".join(
        list(seen_keys)
        + [t["section_type"] for t in composed_templates if t["section_type"] not in seen_keys]
    )

    system_prompt = (
        f"당신은 {guidance['persona']} 관점의 포트폴리오 편집 어시스턴트입니다.\n"
        f"이 프로젝트는 [{guidance['labels']}] 유형으로 구성되어 있습니다.\n"
        "새로 들어온 문서/자료의 사실만을 근거로 가장 알맞은 트랙의 섹션에 내용을 통합·업데이트하세요.\n"
        "엄격한 규칙:\n"
        "1. 문서에 없는 수치, 성과, 도구명을 절대 지어내지 마세요.\n"
        "2. 기존 섹션의 구체적 사실은 보존하면서 새 문서 내용을 중복 없이 깔끔하게 병합하세요.\n"
        "3. 새 문서가 유의미한 근거를 제공하지 않는 섹션은 `section_updates`에 포함하지 마세요.\n"
        f"4. `section_type`은 가급적 다음 기존 섹션 키 중에서 선택하세요: {allowed_keys}\n"
        "5. 각 섹션 본문(`proposed_content`)은 불릿 포인트와 굵은 키워드 중심의 한국어 Markdown으로 작성하세요."
    )

    user_prompt = (
        f"[프로젝트 정보]\n"
        f"- 이름: {project.get('name')}\n"
        f"- 유형: {guidance['labels']}\n"
        f"- 역할: {project.get('role')}\n"
        f"- 요약: {project.get('summary')}\n"
        f"- 기존 기술·역량·툴: {', '.join(project.get('tech_stack') or [])}\n\n"
        f"[현재 포트폴리오 섹션 내용]\n" + "\n\n".join(ordered_blocks) + "\n\n"
        f"[새로 업로드된 문서: {filename}]\n"
        f"[사용자 추가 지시] {user_instruction or '문서 내용을 가장 알맞은 트랙 섹션에 반영해 주세요.'}\n\n"
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
        known = ALL_KNOWN_SECTIONS.get(st)
        title = item.title.strip() or (
            cur["title"] if cur else (known["title"] if known else st)
        )
        track = (
            cur.get("track")
            if cur and cur.get("track")
            else infer_track_for_section_type(st)
        )
        enriched_updates.append(
            {
                "section_id": cur["id"] if cur else None,
                "section_type": st,
                "track": track,
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
        "suggested_experiences": [
            e.model_dump() for e in proposal.suggested_experiences if e.title.strip()
        ],
    }


# ==============================================================================
# 3. 유형 인지형 AI 노이즈 정리 (Prune & Tighten)
# ==============================================================================
class SectionPruneItem(BaseModel):
    section_type: str = Field(description="정리 대상 섹션 타입")
    removed_items: list[str] = Field(
        default_factory=list,
        description="제거·축소한 불필요한 표현, 중복 문장, 사소한 내용 목록",
    )
    reason: str = Field(default="", description="정리 이유 1문장")
    cleaned_content: str = Field(
        default="", description="핵심 근거와 수치만 남겨 압축·정제한 Markdown 본문"
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
    """프로젝트의 모든 유형(project_types) 기준을 반영해 중복·미사여구·불필요한 내용을 정리 제안한다."""
    non_empty = [s for s in existing_sections if (s.get("content") or "").strip()]
    if not non_empty:
        return {
            "overall_assessment": "정리할 섹션 내용이 아직 없습니다.",
            "section_prunes": [],
        }

    project_types = normalize_project_types(project.get("project_types"))
    guidance = get_combined_ai_guidance(project_types)
    sec_by_type = {s["section_type"]: s for s in non_empty}
    blocks = [
        f"### [{s['section_type']} | track:{s.get('track', 'core')}] {s['title']}\n{s['content']}"
        for s in non_empty
    ]

    system_prompt = (
        f"당신은 {guidance['persona']} 관점에서 포트폴리오의 군더더기를 걷어내는 엄격한 에디터입니다.\n"
        f"이 프로젝트의 유형은 [{guidance['labels']}]입니다.\n"
        "아래 기준에 따라 불필요한 노이즈를 탐지해 과감히 제거·압축하세요:\n"
        "1. 추상적 미사여구·AI 상투어 ('혁신적인', '성공적으로 수행', '한 단계 성장', '최적의 시너지')\n"
        "2. 서로 다른 트랙/섹션 간 중복 서술 (가장 알맞은 섹션 1곳에만 남김)\n"
        f"3. 유형별 특화 정리 기준:\n{guidance['prune_focus']}\n\n"
        "규칙:\n"
        "- 확인된 수치, 구체적 의사결정 근거, 실제 도구/기술명, 핵심 행동은 절대 지우지 마세요.\n"
        "- 원문에 없는 새로운 사실이나 수치를 추가하지 마세요.\n"
        "- 이미 충분히 간결한 섹션은 `section_prunes`에 넣지 마세요."
    )

    user_prompt = (
        f"[프로젝트명] {project.get('name')} ({project.get('role')})\n"
        f"[유형] {guidance['labels']}\n\n"
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
