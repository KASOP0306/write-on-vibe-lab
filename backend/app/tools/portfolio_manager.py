"""조합형 멀티트랙 포트폴리오 렌더링, 문서 기반 프로젝트 자동 생성, Diff-Merge 업데이트, AI 노이즈 정리 엔진."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_fast_llm, get_smart_llm
from app.core.project_templates import (
    ALL_KNOWN_SECTIONS,
    TRACK_PACKS,
    compose_sections_for_types,
    get_combined_ai_guidance,
    get_track_labels,
    infer_track_for_section_type,
    normalize_project_types,
)
from app.core.star_rubric import (
    PORTFOLIO_AXES,
    PORTFOLIO_AXIS_ORDER,
    STAR_AXES,
    STAR_AXIS_ORDER,
    compute_portfolio_overall_score,
    evaluate_star_experience_rubric,
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

    llm = get_smart_llm(temperature=0.25, max_tokens=5000)
    synthesized = await ainvoke_structured(
        llm,
        DocumentToPortfolioSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
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


# ==============================================================================
# 4. 섹션 단일 타깃 문서·파일 정밀 AI 업데이트 (Section-Scoped Diff)
# ==============================================================================
class SectionScopedUpdateSchema(BaseModel):
    document_summary: str = Field(
        default="", description="첨부 문서/메모에서 이 섹션과 관련해 추출한 핵심 요약 (1~2문장)"
    )
    change_summary: str = Field(
        default="", description="기존 섹션 대비 무엇이 추가·보강·정리되었는지 요약"
    )
    proposed_title: str = Field(
        default="", description="섹션 제목 유지 또는 필요 시 개선안"
    )
    proposed_content: str = Field(
        default="", description="업데이트가 반영된 해당 섹션의 최종 한국어 Markdown 본문"
    )
    added_facts: list[str] = Field(
        default_factory=list, description="신규 문서에서 새롭게 반영된 핵심 사실/지표 목록 (최대 5개)"
    )
    suggested_tech_stack_additions: list[str] = Field(
        default_factory=list, description="문서에서 새로 발견된 기술·툴·방법론 키워드 (최대 6개)"
    )


async def propose_section_document_update(
    *,
    project: dict[str, Any],
    target_section: dict[str, Any],
    doc_text: str,
    filename: str,
    instruction: str = "",
    update_mode: Literal["merge", "replace", "append"] = "merge",
) -> dict[str, Any]:
    """특정 포트폴리오 섹션 1개만을 대상으로 첨부 파일/메모를 정밀 반영한 Before/After Diff를 제안한다."""
    project_types = normalize_project_types(project.get("project_types"))
    guidance = get_combined_ai_guidance(project_types)

    mode_rules = {
        "merge": "기존 섹션의 검증된 핵심 사실·수치를 보존하면서 신규 문서의 새로운 사실을 중복 없이 자연스럽게 통합하세요.",
        "replace": "신규 문서를 주 근거로 삼아 이 섹션을 처음부터 깔끔하게 재구조화하세요. 단, 기존 섹션에만 있던 중요 정량 지표는 유지하세요.",
        "append": "기존 섹션의 문장을 최대한 유지한 채, 신규 문서에서 확인된 추가 근거·사례를 자연스러운 하위 불릿으로 덧붙이세요.",
    }

    system_prompt = (
        f"당신은 {guidance['persona']} 관점의 시니어 포트폴리오 섹션 에디터입니다.\n"
        f"오직 타깃 섹션 `[{target_section.get('section_type')}] {target_section.get('title')}`의 품질을 높이는 데만 집중하세요.\n\n"
        f"[업데이트 모드: {update_mode}]\n{mode_rules.get(update_mode, mode_rules['merge'])}\n\n"
        "엄격한 규칙:\n"
        "1. 기존 섹션이나 신규 문서에 없는 수치·성과·도구는 절대 지어내지 마세요.\n"
        "2. 다른 섹션으로 가야 할 무관한 잡설은 제외하고, 이 섹션 목적에 맞는 핵심 불릿 위주로 밀도 있게 정리하세요.\n"
        "3. `proposed_content`는 바로 저장 가능한 깔끔한 한국어 Markdown으로 작성하세요."
    )

    user_prompt = (
        f"[프로젝트] {project.get('name')} ({project.get('role') or '역할 미입력'})\n"
        f"[프로젝트 유형] {guidance['labels']}\n"
        f"[프로젝트 한 줄 요약] {project.get('summary') or '(없음)'}\n"
        f"[타깃 섹션] {target_section.get('title')} (type: {target_section.get('section_type')}, track: {target_section.get('track', 'core')})\n"
        f"[사용자 추가 지시] {instruction or '(없음)'}\n\n"
        f"=== 현재 섹션 본문 (Before) ===\n{(target_section.get('content') or '').strip() or '(비어 있음)'}\n\n"
        f"=== 첨부 문서/메모 ({filename}) ===\n{doc_text[:18000]}"
    )

    llm = get_smart_llm(temperature=0.2, max_tokens=4000)
    proposal = await ainvoke_structured(
        llm,
        SectionScopedUpdateSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
    )

    return {
        "section_id": target_section["id"],
        "section_type": target_section["section_type"],
        "track": target_section.get("track") or infer_track_for_section_type(target_section["section_type"]),
        "title": proposal.proposed_title.strip() or target_section["title"],
        "before_content": target_section.get("content") or "",
        "proposed_content": proposal.proposed_content.strip(),
        "document_summary": proposal.document_summary.strip(),
        "change_summary": proposal.change_summary.strip(),
        "added_facts": [x.strip() for x in proposal.added_facts if x.strip()][:5],
        "suggested_tech_stack_additions": [
            x.strip() for x in proposal.suggested_tech_stack_additions if x.strip()
        ][:6],
    }


# ==============================================================================
# 5. 선택형 프로젝트 STAR 보강 역질문 (Opt-in STAR Deepening)
# ==============================================================================
class OnboardingQuestionItem(BaseModel):
    id: str = Field(description="질문 식별자 (q1, q2, q3, q4)")
    target_axis: Literal["situation", "task", "action", "result", "learning"] = Field(
        description="이 질문이 보강하려는 STAR-L 핵심 축"
    )
    question: str = Field(description="사용자가 2~3문장으로 답하기 쉬운 날카롭고 구체적인 역질문")
    rationale: str = Field(description="이 질문이 왜 STAR/면접 완성도에 중요한지 1문장 설명")
    example_hint: str = Field(default="", description="답변 감을 잡을 수 있는 짧은 예시 힌트")


class StarOnboardingQuestionsSchema(BaseModel):
    diagnosis_summary: str = Field(
        description="현재 프로젝트 기록에서 어떤 STAR-L 축이 비어 있거나 약한지 1~2문장 진단"
    )
    weak_axes: list[str] = Field(
        default_factory=list, description="가장 보강이 시급한 축 ID 목록 (예: ['action', 'result'])"
    )
    questions: list[OnboardingQuestionItem] = Field(
        default_factory=list, description="핵심 역질문 3~4개"
    )


class OnboardingSectionPatchItem(BaseModel):
    section_type: str = Field(description="보강할 기존 섹션의 section_type")
    title: str = Field(default="", description="섹션 제목")
    change_summary: str = Field(default="", description="답변에서 반영할 보강 포인트 1문장")
    proposed_content: str = Field(default="", description="기존 내용 + 답변을 병합한 섹션 Markdown")


class StarOnboardingApplySchema(BaseModel):
    experiences: list[ExtractedStarDraft] = Field(
        default_factory=list,
        description="역질문 답변을 반영해 고밀도로 구조화한 STAR 경험 1~2건",
    )
    section_patches: list[OnboardingSectionPatchItem] = Field(
        default_factory=list,
        description="답변 속 핵심 의사결정/성과를 프로젝트 섹션에도 반영할 보강안 (필요한 섹션만 최대 3개)",
    )


async def generate_star_onboarding_questions(
    *,
    project: dict[str, Any],
    sections: list[dict[str, Any]],
    experiences: list[dict[str, Any]],
) -> dict[str, Any]:
    """프로젝트 현재 기록의 빈약한 STAR-L 축을 진단해 선택형 딥다이브 역질문 3~4개를 생성한다."""
    project_types = normalize_project_types(project.get("project_types"))
    guidance = get_combined_ai_guidance(project_types)

    section_dump = "\n\n".join(
        f"### [{s['section_type']}] {s['title']}\n{(s.get('content') or '').strip() or '(비어 있음)'}"
        for s in sections
    )
    exp_dump = "\n\n".join(
        f"- {e.get('title')} (점수 {e.get('completeness_score', 0)})\n"
        f"  S: {e.get('situation', '')}\n  T: {e.get('task', '')}\n"
        f"  A: {e.get('action', '')}\n  R: {e.get('result', '')}\n"
        f"  지표: {e.get('quantified_metrics', '')}"
        for e in experiences
    ) or "(등록된 STAR 경험 없음)"

    system_prompt = (
        f"당신은 DDI BARS × Amazon Bar Raiser × Google XYZ 기준을 쓰는 {guidance['persona']} 커리어 인터뷰어입니다.\n"
        "코드나 문서만으로 등록된 프로젝트는 보통 '본인 담당 범위(T)', '대안 비교·의사결정 근거(A)', '전후 정량 성과(R)', '회고/재발방지(L)'가 비어 있습니다.\n"
        "현재 프로젝트 기록에서 가장 빈약한 축을 진단하고, 사용자가 2~3줄씩 가볍게 답하면 STAR 밀도가 확 올라갈 날카로운 역질문 3~4개를 만드세요.\n"
        "규칙:\n"
        "1. 이미 문서에 자세히 적혀 있는 뻔한 내용은 다시 묻지 마세요.\n"
        "2. 질문은 서로 다른 STAR-L 축(특히 task, action, result, learning 중심)을 커버하게 설계하세요.\n"
        "3. `example_hint`는 사용자가 '아 이렇게 답하면 되겠구나' 감을 잡을 수 있게 1줄 짧은 예시로 작성하세요."
    )

    user_prompt = (
        f"[프로젝트] {project.get('name')} ({project.get('period') or '기간 미입력'} / {project.get('role') or '역할 미입력'})\n"
        f"[유형] {guidance['labels']}\n"
        f"[요약] {project.get('summary') or '(없음)'}\n\n"
        f"[현재 섹션]\n{section_dump[:12000]}\n\n"
        f"[현재 STAR 경험]\n{exp_dump[:4000]}"
    )

    llm = get_fast_llm(temperature=0.25, max_tokens=2048)
    result = await ainvoke_structured(
        llm,
        StarOnboardingQuestionsSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
    )

    return {
        "diagnosis_summary": result.diagnosis_summary.strip(),
        "weak_axes": [a for a in result.weak_axes if a in STAR_AXES],
        "questions": [q.model_dump() for q in result.questions[:4]],
    }


async def synthesize_star_onboarding_answers(
    *,
    project: dict[str, Any],
    sections: list[dict[str, Any]],
    qa_pairs: list[dict[str, str]],
) -> dict[str, Any]:
    """역질문 답변을 바탕으로 고밀도 STAR 경험(5축 BARS 자동 채점 포함)과 섹션 보강 제안을 생성한다."""
    project_types = normalize_project_types(project.get("project_types"))
    guidance = get_combined_ai_guidance(project_types)

    qa_text = "\n\n".join(
        f"Q ({item.get('target_axis', '')}): {item.get('question', '')}\nA: {item.get('answer', '')}"
        for item in qa_pairs
        if (item.get("answer") or "").strip()
    )
    section_dump = "\n\n".join(
        f"### [{s['section_type']}] {s['title']}\n{(s.get('content') or '').strip() or '(비어 있음)'}"
        for s in sections
    )

    system_prompt = (
        f"당신은 {guidance['persona']} 커리어 에디터입니다.\n"
        "프로젝트 기존 기록과 사용자의 역질문 답변을 결합하여:\n"
        "1. 자소서·면접에 바로 쓸 수 있는 고밀도 STAR 경험 1~2건 (`experiences`)을 작성하세요.\n"
        "   - 본인 책임(T), 대안 비교·트레이드오프·구체 행동(A), 확인된 수치/성과(R), 배운 점(result 끝에 자연스럽게 포함)을 촘촘히 담으세요.\n"
        "2. 답변 속 새로운 핵심 사실을 프로젝트의 기존 섹션 중 가장 알맞은 1~3곳에 반영한 `section_patches`도 제안하세요.\n"
        "엄격한 규칙: 기존 기록과 사용자 답변에 없는 수치·성과는 절대 지어내지 마세요."
    )

    user_prompt = (
        f"[프로젝트] {project.get('name')} ({project.get('role') or '역할 미입력'})\n"
        f"[유형] {guidance['labels']}\n\n"
        f"[기존 섹션]\n{section_dump[:10000]}\n\n"
        f"[사용자 역질문 답변]\n{qa_text[:6000]}"
    )

    llm = get_smart_llm(temperature=0.25, max_tokens=4500)
    synthesized = await ainvoke_structured(
        llm,
        StarOnboardingApplySchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
    )

    evaluated_experiences: list[dict[str, Any]] = []
    for exp in synthesized.experiences[:2]:
        if not exp.title.strip():
            continue
        exp_dict = exp.model_dump()
        grade = await evaluate_star_experience_rubric(exp_dict, context_text=qa_text)
        evaluated_experiences.append(
            {
                **exp_dict,
                "completeness_score": grade["completeness_score"],
                "star_scores": grade["star_scores"],
            }
        )

    sec_by_type = {s["section_type"]: s for s in sections}
    section_patches: list[dict[str, Any]] = []
    for patch in synthesized.section_patches[:3]:
        cur = sec_by_type.get(patch.section_type.strip())
        if not cur or not patch.proposed_content.strip():
            continue
        section_patches.append(
            {
                "section_id": cur["id"],
                "section_type": cur["section_type"],
                "track": cur.get("track") or infer_track_for_section_type(cur["section_type"]),
                "title": patch.title.strip() or cur["title"],
                "change_summary": patch.change_summary.strip(),
                "before_content": cur.get("content") or "",
                "proposed_content": patch.proposed_content.strip(),
            }
        )

    return {
        "experiences": evaluated_experiences,
        "section_patches": section_patches,
    }


# ==============================================================================
# 6. 전체 포트폴리오 6축 육각형 점수 & 캐릭터 진단 (강점 50% : 약점 50%)
# ==============================================================================
class PortfolioAxisScoreSchema(BaseModel):
    score: int = Field(ge=0, le=100, description="0~100 점수 (근거 부족 시 35 이하로 보수 평가)")
    evidence_status: Literal["verified", "partial", "missing"] = Field(
        description="verified(다수 근거 확인), partial(일부 근거), missing(기록 부족·사각지대)"
    )
    evidence: str = Field(
        default="", description="점수 근거(실제 프로젝트명/내용 인용, missing이면 어떤 기록이 빠졌는지 명시)"
    )
    improvement_tip: str = Field(default="", description="이 축을 강화하기 위한 구체적 1문장 팁")


class BalancedTraitItem(BaseModel):
    title: str = Field(description="핵심 강점 또는 약점/사각지대 제목 (15자 내외)")
    detail: str = Field(description="면접관 관점의 구체적 근거 분석 (2~3문장)")
    evidence_projects: list[str] = Field(
        default_factory=list, description="근거가 된 프로젝트명 목록 (부재 시 빈 배열)"
    )
    related_axis: str = Field(default="", description="연관된 6축 ID")


class GrowthActionItem(BaseModel):
    target_weakness: str = Field(description="해결 대상 약점/사각지대")
    action: str = Field(description="다음 프로젝트나 포트폴리오 보강에서 바로 실행할 구체 액션")
    expected_impact: str = Field(description="실행 시 면접·서류에서 얻게 될 기대 효과")


class PortfolioCharacterDiagnosisSchema(BaseModel):
    character_archetype: str = Field(
        description="지원자의 포트폴리오 캐릭터 아키타입 별칭 (예: '가설 검증형 풀스택 빌더', '구조화 집착형 시스템 플래너')"
    )
    one_line_identity: str = Field(
        description="포트폴리오 전반에서 읽히는 지원자의 캐릭터 한 줄 정의 (강점과 현재 단계가 균형 있게 드러나게)"
    )
    recurring_patterns: list[str] = Field(
        default_factory=list,
        description="여러 프로젝트에 걸쳐 반복적으로 나타나는 문제 접근 습관·일관된 패턴 2~4개 (프로젝트명 인용)",
    )
    problem_depth: PortfolioAxisScoreSchema
    evidence_impact: PortfolioAxisScoreSchema
    narrative_coherence: PortfolioAxisScoreSchema
    time_execution: PortfolioAxisScoreSchema
    people_collaboration: PortfolioAxisScoreSchema
    adaptability_growth: PortfolioAxisScoreSchema
    strengths: list[BalancedTraitItem] = Field(
        default_factory=list,
        description="채용 시장에서 통하는 핵심 강점 정확히 3가지",
    )
    weaknesses: list[BalancedTraitItem] = Field(
        default_factory=list,
        description="면접관이 바로 파고들 핵심 약점·사각지대 정확히 3가지 (강점과 완전히 동등한 깊이와 직설성으로 작성)",
    )
    growth_actions: list[GrowthActionItem] = Field(
        default_factory=list,
        description="위 약점 3가지에 1:1 대응하는 구체적 성장·보완 액션 3가지",
    )


async def diagnose_portfolio_character(
    *,
    profile: dict[str, Any],
    projects: list[dict[str, Any]],
    external_notes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """전체 프로젝트·섹션·STAR·신념·외적 보충 메모를 종합해 6축 육각형 포트폴리오 점수 & 캐릭터 진단을 생성한다."""
    axis_spec = "\n".join(
        f"- `{axis_id}` [{PORTFOLIO_AXES[axis_id]['domain_label']}] "
        f"{PORTFOLIO_AXES[axis_id]['label']} ({PORTFOLIO_AXES[axis_id]['reference']}): "
        f"{PORTFOLIO_AXES[axis_id]['description']}"
        for axis_id in PORTFOLIO_AXIS_ORDER
    )

    project_blocks: list[str] = []
    for p in projects:
        types = ", ".join(get_track_labels(p.get("project_types")))
        links = ", ".join(
            f"{l.get('label') or l.get('url')}" for l in (p.get("artifact_links") or [])
        )
        secs = "\n".join(
            f"  - [{s.get('track', 'core')}/{s.get('section_type')}] {s.get('title')}: {(s.get('content') or '')[:350]}"
            for s in (p.get("sections") or [])
            if (s.get("content") or "").strip()
        )
        exps = "\n".join(
            f"  * STAR '{e.get('title')}' (점수 {e.get('completeness_score', 0)}): "
            f"A={(e.get('action') or '')[:160]} / R={(e.get('result') or '')[:140]} / 지표={e.get('quantified_metrics', '')}"
            for e in (p.get("experiences") or [])
        )
        project_blocks.append(
            f"## 프로젝트: {p.get('name')} | 기간: {p.get('period') or '미입력'} | 역할: {p.get('role') or '미입력'}\n"
            f"유형: {types} | 기술·역량: {', '.join(p.get('tech_stack') or [])}\n"
            f"GitHub: {p.get('repo_url') or '없음'} | 참고 링크: {links or '없음'}\n"
            f"요약: {p.get('summary') or '(없음)'}\n"
            f"[주요 섹션]\n{secs or '  (작성된 섹션 없음)'}\n"
            f"[STAR 경험]\n{exps or '  (등록된 STAR 없음)'}"
        )

    ext_notes = external_notes or {}
    ext_dump = "\n".join(
        f"- {k}: {v.strip()}" for k, v in ext_notes.items() if isinstance(v, str) and v.strip()
    ) or "(별도 외적 역량 보충 메모 없음)"

    system_prompt = (
        "당신은 Korn Ferry Leadership Architect(KFLA), Google 4 Hiring Attributes, Spencer 역량 빙산 모델을 적용하는 "
        "냉철하고 통찰력 있는 시니어 커리어 아키텍트입니다.\n"
        "지원자의 전체 포트폴리오(내적 산출물 + 외적 운영·협업·적응 역량)를 6축 육각형 모델로 종합 진단하고, "
        "지원자의 '포트폴리오 캐릭터'와 강점/약점을 **정확히 50:50 동등한 비중**으로 제시하세요.\n\n"
        f"[6축 평가 기준 (내적 3축 × 외적 3축)]\n{axis_spec}\n\n"
        "절대 준수해야 할 객관성 규칙:\n"
        "1. **아부 금지 & 강점·약점 50:50 균형:** 칭찬만 늘어놓지 마세요. `strengths` 3가지와 `weaknesses` 3가지를 동일한 분량·깊이·구체성으로 작성하세요.\n"
        "2. **외적 축 정직성 가드레일(핵심!):** 시간·일정·우선순위(`time_execution`), 인적·이해관계자 관리(`people_collaboration`), 적응력(`adaptability_growth`) 중 "
        "실제 프로젝트 기록과 보충 메모 어디에도 근거가 없다면 절대 추측해 높은 점수를 주지 마세요. "
        "`evidence_status='missing'`, `score=20~35`로 솔직하게 표기하고 약점/사각지대에 명확히 짚어주세요.\n"
        "3. `recurring_patterns`에는 여러 프로젝트에서 반복 관찰되는 지원자 특유의 문제 해결 습관·일관성을 실제 프로젝트명을 인용해 정리하세요.\n"
        "4. `growth_actions`는 `weaknesses` 3가지와 1:1로 대응되는 즉시 실행 가능한 보완 계획 3가지를 제시하세요."
    )

    user_prompt = (
        f"[지원자 커리어 프로필]\n"
        f"- 커리어 비전: {profile.get('career_vision') or '(미입력)'}\n"
        f"- 핵심 신념: {profile.get('core_beliefs') or '(미입력)'}\n"
        f"- 희망 직무: {profile.get('target_roles') or '(미입력)'}\n\n"
        f"[외적 역량 보충 메모 (사용자 선택 입력)]\n{ext_dump}\n\n"
        f"[전체 포트폴리오 프로젝트 ({len(projects)}건)]\n"
        + ("\n\n".join(project_blocks)[:18000] if project_blocks else "(등록된 프로젝트 없음)")
    )

    llm = get_smart_llm(temperature=0.25, max_tokens=5000)
    diagnosed = await ainvoke_structured(
        llm,
        PortfolioCharacterDiagnosisSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
    )

    axes = {
        axis_id: getattr(diagnosed, axis_id).model_dump()
        for axis_id in PORTFOLIO_AXIS_ORDER
    }
    aggregates = compute_portfolio_overall_score(axes)

    return {
        "framework": "KFLA 4 Factors × Google 4 Attributes × Spencer Iceberg",
        "analyzed_project_count": len(projects),
        "diagnosed_at": datetime.now(timezone.utc).isoformat(),
        "character_archetype": diagnosed.character_archetype.strip(),
        "one_line_identity": diagnosed.one_line_identity.strip(),
        "recurring_patterns": [p.strip() for p in diagnosed.recurring_patterns if p.strip()][:4],
        "overall_score": aggregates["overall_score"],
        "internal_score": aggregates["internal_score"],
        "external_score": aggregates["external_score"],
        "axes": axes,
        "strengths": [s.model_dump() for s in diagnosed.strengths[:3]],
        "weaknesses": [w.model_dump() for w in diagnosed.weaknesses[:3]],
        "growth_actions": [g.model_dump() for g in diagnosed.growth_actions[:3]],
    }
