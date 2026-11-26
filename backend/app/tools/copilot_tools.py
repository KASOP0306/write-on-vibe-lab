"""새 프로젝트 코파일럿 Agentic RAG 전용 @tool 6종 & AsyncPostgresStore 장기 기억 어댑터 (Unit 7~8)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any, Literal
from uuid import uuid4

from langchain_core.tools import tool
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg import AsyncConnection
from sqlalchemy import select

from app.config import settings
from app.core.database import (
    BeliefPillar,
    CompanyProfile,
    Experience,
    Project,
    UserProfile,
    _store_embed_texts,
    get_psycopg_conninfo,
    get_session_factory,
)
from app.core.project_templates import normalize_project_types
from app.core.star_rubric import (
    STAR_AXES,
    STAR_AXIS_ORDER,
    compute_cumulative_portfolio_xp,
)
from app.core.vector_store import (
    DocType,
    SearchStrategy,
    format_hits_with_citations,
    search_documents,
)
from app.tools.web_search import search_and_extract

logger = logging.getLogger(__name__)

MEMORY_NAMESPACE: tuple[str, str] = ("default_user", "career_memories")

_PII_BLOCK_RE = re.compile(
    r"(비밀번호|패스워드|password|주민등록|계좌번호|카드번호|010[-.\s]?\d{3,4}[-.\s]?\d{4})",
    re.IGNORECASE,
)


def _contains_blocked_pii(text: str) -> bool:
    return bool(_PII_BLOCK_RE.search(text or ""))


async def _open_store(aconn: AsyncConnection) -> AsyncPostgresStore:
    return AsyncPostgresStore(
        aconn,
        index={
            "dims": settings.embedding_dim,
            "embed": _store_embed_texts,
            "fields": ["text"],
        },
    )


async def list_career_memories(limit: int = 20) -> list[dict[str, Any]]:
    """장기 기억 Store에 저장된 사용자 커리어 메모 목록을 반환한다."""
    conninfo = get_psycopg_conninfo()
    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        store = await _open_store(aconn)
        items = await store.asearch(MEMORY_NAMESPACE, limit=limit)
        results: list[dict[str, Any]] = []
        for it in items:
            val = dict(it.value or {})
            results.append(
                {
                    "key": it.key,
                    "text": str(val.get("text") or ""),
                    "category": str(val.get("category") or "preference"),
                    "created_at": str(val.get("created_at") or ""),
                }
            )
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results


async def delete_career_memory(key: str) -> bool:
    """장기 기억 Store에서 특정 키의 메모를 삭제한다."""
    conninfo = get_psycopg_conninfo()
    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        store = await _open_store(aconn)
        await store.adelete(MEMORY_NAMESPACE, key)
    return True


@tool
async def search_portfolio_docs(
    query: str,
    strategy: Literal["basic", "hybrid", "rewrite", "hyde"] = "hybrid",
    doc_type: Literal["experience", "career_identity", "company_research"] = "experience",
) -> str:
    """지원자의 포트폴리오·STAR-L 경험·신념/회고 저널·기업 리서치 벡터 DB에서 관련 조각을 출처와 함께 검색한다.

    query: 핵심 키워드 또는 질문 문장.
    strategy에는 다음 중 하나를 그대로 넣는다:
      - hybrid: 기본 권장. 한국어 2-gram BM25 키워드 + 벡터 RRF 하이브리드 검색
      - basic: 질문 원문 벡터 유사도 검색
      - rewrite: 첫 검색에 답이 없을 때 문서 용어로 질문을 재작성해 재검색
      - hyde: rewrite로도 못 찾았을 때 가상 답변 임베딩으로 재검색
    doc_type에는 다음 중 하나를 그대로 넣는다:
      - experience: 보유 프로젝트 섹션과 STAR-L 경험 팩트
      - career_identity: 나의 커리어 비전·신념·일상 회고 저널
      - company_research: 저장된 목표 기업 리서치
    """
    valid_strategy: SearchStrategy = (
        strategy if strategy in ("basic", "hybrid", "rewrite", "hyde") else "hybrid"
    )
    doc_type_enum = DocType(doc_type)
    max_dist = 0.80 if valid_strategy in ("basic", "hybrid") else 0.86

    async with get_session_factory()() as session:
        hits = await search_documents(
            session,
            query=query,
            doc_types=[doc_type_enum],
            top_k=4,
            strategy=valid_strategy,
            max_distance=max_dist,
            use_mmr=True,
        )

    if not hits:
        return (
            f"[검색 결과 없음] doc_type={doc_type}, strategy={valid_strategy}, query='{query}'. "
            "다른 키워드나 다음 전략(rewrite 또는 hyde)으로 재시도하세요. "
            "모든 전략으로도 없으면 등록된 포트폴리오에 없는 내용입니다."
        )

    top_sim = hits[0].similarity
    formatted = format_hits_with_citations(hits, max_chars_per_hit=550)
    return (
        f"[검색 전략={valid_strategy} | doc_type={doc_type} | 최고 유사도={top_sim:.2f} | {len(hits)}건]\n"
        f"{formatted}"
    )


def format_star_mastery_summary(
    mastery: dict[str, Any],
    pillars: list[dict[str, Any]] | None = None,
) -> str:
    """STAR-L 21지표 마스터리(1,000 XP / 대표 4프로젝트)와 핵심 신념 카드(특히 미증명 신념)를 텍스트로 포맷한다."""
    lv = mastery.get("level") or {}
    total_xp = int(mastery.get("total_xp") or 0)
    max_xp = int(mastery.get("max_total_xp") or 1000)
    max_sel = int(mastery.get("max_selected_projects") or 4)
    sel_projs = mastery.get("selected_projects") or []
    star_avg = (mastery.get("star_averages") or {}).get("axes") or {}
    cp_stats = mastery.get("checkpoint_heatmap") or mastery.get("checkpoint_stats") or []

    axis_lines = [
        f"  - {STAR_AXES[ax]['label']}({ax.upper()}): {(star_avg.get(ax) or {}).get('score', 0)}%"
        for ax in STAR_AXIS_ORDER
    ]
    evaluated_cps = [c for c in cp_stats if int(c.get("evaluated_count") or 0) > 0]
    weak_pool = sorted(
        evaluated_cps if evaluated_cps else cp_stats,
        key=lambda c: (int(c.get("mastery_pct") or 0), -int(c.get("weight") or 0)),
    )[:5]
    weak_cp_lines = [
        f"  - [{c['id']}] {c['label']} (배점 {c['weight']}점 · 달성률 {c['mastery_pct']}%) — {c.get('probe_hint', '')}"
        for c in weak_pool
    ]
    slot_lines = [
        f"  - {p['name']}: {p['capped_xp']}/{p['cap']} XP (경험 {p['experience_count']}건, 최고 {p['best_score']}점)"
        for p in sel_projs
    ]
    empty_slots = max(0, max_sel - len(sel_projs))
    if empty_slots > 0:
        slot_lines.append(f"  - (빈 대표 프로젝트 슬롯 {empty_slots}개 — 새 프로젝트로 최대 +{empty_slots * int(mastery.get('project_cap') or 250)} XP 확보 가능)")

    parts = [
        f"[STAR-L 21지표 마스터리] Lv.{lv.get('level', 1)} {lv.get('name', 'Seed')} · 총 {total_xp} / {max_xp} XP (대표 {len(sel_projs)}/{max_sel}슬롯)\n"
        f"[대표 프로젝트 XP 슬롯]\n" + ("\n".join(slot_lines) or "  (등록된 프로젝트 없음)") + "\n"
        f"[STAR-L 5축 평균]\n" + "\n".join(axis_lines) + "\n"
        f"[21지표 취약 체크포인트 TOP 5 (새 프로젝트에서 반드시 증거 확보)]\n" + ("\n".join(weak_cp_lines) or "  (데이터 없음)")
    ]

    if pillars:
        unproven = [
            b for b in pillars
            if not (b.get("linked_project_ids") or b.get("linked_experience_ids"))
        ]
        proven = [
            b for b in pillars
            if (b.get("linked_project_ids") or b.get("linked_experience_ids"))
        ]
        pillar_lines = [
            f"  - [미실천 신념 ⚠️] {b['title']} (커리어 지향: {b.get('tradeoff_rule') or '미입력'})"
            for b in unproven
        ] + [
            f"  - [실천 연결됨 ✅] {b['title']} (커리어 지향: {b.get('tradeoff_rule') or '미입력'})"
            for b in proven[:4]
        ]
        parts.append("[인간·사회적 커리어 신념 카드 현황 (미실천 신념은 새 프로젝트 기획의 최우선 주제)]\n" + "\n".join(pillar_lines))

    return "\n\n".join(parts)


@tool
async def get_portfolio_character_and_loop() -> str:
    """지원자의 STAR-L 21지표 마스터리(총 1,000 XP · 대표 4프로젝트 슬롯 · 5축 평균 · 취약 체크포인트 TOP 5), 핵심 신념 카드(미증명 신념 포함), 보유 프로젝트 요약, 그리고 이전 프로젝트 회고 Try 학습 루프를 조회한다.

    새 프로젝트 기획, STAR-L 취약 지표 보완, 미증명 신념 증명, 이전 실수 재발 방지 규칙을 확인할 때 사용한다.
    """
    async with get_session_factory()() as session:
        profile = await session.get(UserProfile, 1)
        projects = (
            (await session.execute(select(Project).order_by(Project.created_at.desc()).limit(15)))
            .scalars()
            .all()
        )
        experiences = (
            (await session.execute(select(Experience).order_by(Experience.created_at.desc())))
            .scalars()
            .all()
        )
        pillars = (
            (await session.execute(select(BeliefPillar).order_by(BeliefPillar.created_at.desc())))
            .scalars()
            .all()
        )

    proj_dicts = [
        {
            "id": p.id,
            "name": p.name,
            "period": p.period,
            "project_types": normalize_project_types(p.project_types),
            "is_portfolio_selected": bool(p.is_portfolio_selected),
        }
        for p in projects
    ]
    exp_dicts = [
        {
            "id": e.id,
            "project_id": e.project_id,
            "title": e.title,
            "completeness_score": e.completeness_score,
            "star_scores": e.star_scores or {},
        }
        for e in experiences
    ]
    pillar_dicts = [
        {
            "id": b.id,
            "title": b.title,
            "category": b.category,
            "tradeoff_rule": b.tradeoff_rule,
            "linked_project_ids": list(b.linked_project_ids or []),
            "linked_experience_ids": list(b.linked_experience_ids or []),
        }
        for b in pillars
    ]
    mastery = compute_cumulative_portfolio_xp(proj_dicts, exp_dicts)

    parts: list[str] = []
    if profile:
        parts.append(
            f"[커리어 프로필]\n비전: {profile.career_vision or '(미설정)'}\n"
            f"핵심 신념 요약: {profile.core_beliefs or '(미설정)'}\n"
            f"희망 직무: {profile.target_roles or '(미설정)'}"
        )

    parts.append(format_star_mastery_summary(mastery, pillar_dicts))

    proj_lines = [
        f"- {p.name} ({', '.join(normalize_project_types(p.project_types))}) | 역할: {p.role or '미입력'} | 스택: {', '.join(p.tech_stack or [])}"
        for p in projects
    ]
    parts.append("[보유 프로젝트 목록]\n" + ("\n".join(proj_lines) or "(등록된 프로젝트 없음)"))

    loop_lines: list[str] = []
    for p in projects:
        retro = p.retrospective or {}
        tries = [str(t).strip() for t in (retro.get("try_items") or []) if str(t).strip()]
        if tries:
            loop_lines.append(f"- [{p.name} 회고 Try] " + " / ".join(tries))
    parts.append(
        "[이전 프로젝트 회고 Try 학습 루프]\n"
        + ("\n".join(loop_lines) or "(아직 인계된 Try 규칙 없음)")
    )
    return "\n\n".join(parts)


@tool
async def get_company_research(company_name: str = "") -> str:
    """저장된 목표 기업 리서치(미션·비전·핵심가치·최근 동향·신념 3각 매칭)를 조회한다.

    company_name: 특정 기업명(예: '토스', '네이버'). 비워 두면 최근 리서치한 기업 최대 2곳을 반환한다.
    """
    async with get_session_factory()() as session:
        all_companies = (
            (await session.execute(select(CompanyProfile).order_by(CompanyProfile.created_at.desc())))
            .scalars()
            .all()
        )

    if not all_companies:
        return "저장된 기업 리서치가 없습니다. '4. 기업 리서치' 페이지에서 먼저 목표 기업을 분석해 주세요."

    target = (company_name or "").strip().lower()
    if target:
        matched = [c for c in all_companies if target in c.company_name.lower()]
        if not matched:
            available = ", ".join(c.company_name for c in all_companies[:10])
            return (
                f"'{company_name}'에 해당하는 저장된 기업 리서치를 찾지 못했습니다. "
                f"현재 저장된 기업 목록: [{available}]"
            )
        chosen = matched[:2]
    else:
        chosen = all_companies[:2]

    blocks = []
    for c in chosen:
        blocks.append(
            f"[기업 리서치: {c.company_name} ({c.target_role or '직무 미지정'})]\n"
            f"- 미션/비전: {c.mission_vision}\n"
            f"- 핵심가치: {c.core_values}\n"
            f"- 최근 동향: {c.recent_trends}\n"
            f"- 3각 매칭: {c.value_alignment_map}"
        )
    return "\n\n".join(blocks)


@tool
async def web_search_reference(query: str) -> str:
    """최신 기술 스택 비교, 오픈소스 아키텍처, 실무 벤치마크 사례를 실시간 웹 검색으로 조회한다.

    내부 포트폴리오에 없는 외부 최신 정보나 구현 레퍼런스가 필요할 때만 호출한다 (턴당 최대 1회).
    """
    sources = await search_and_extract(query.strip(), max_results=4, fetch_top_n=2)
    if not sources:
        return f"'{query}'에 대한 웹 검색 결과를 찾지 못했습니다."

    lines = []
    for idx, s in enumerate(sources, start=1):
        excerpt = (s.get("content") or s.get("snippet") or "").strip()[:550]
        lines.append(f"[{idx}] {s.get('title', '제목 없음')} ({s.get('url', '')})\n{excerpt}")
    return "\n\n".join(lines)


@tool
async def save_career_memory(
    memory: str,
    category: Literal["preference", "constraint", "goal", "skill_focus"] = "preference",
) -> str:
    """새 대화에서도 계속 기억해야 할 사용자의 커리어 선호, 일정·시간 제약, 목표, 집중 기술 스택을 장기 기억(Store)에 저장한다.

    category에는 다음 중 하나를 그대로 넣는다: preference, constraint, goal, skill_focus.
    주의: 비밀번호, 연락처, 주민번호, 계좌번호 등 민감 개인정보는 절대 저장하지 않는다.
    """
    clean = (memory or "").strip()
    if not clean:
        return "저장할 기억 내용이 비어 있습니다."
    if _contains_blocked_pii(clean):
        return "보안 정책상 비밀번호·연락처·계좌번호 등 민감 개인정보는 장기 기억에 저장할 수 없습니다."

    valid_cat = category if category in ("preference", "constraint", "goal", "skill_focus") else "preference"
    key = f"mem-{uuid4().hex[:10]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    conninfo = get_psycopg_conninfo()
    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        store = await _open_store(aconn)
        await store.aput(
            MEMORY_NAMESPACE,
            key,
            {
                "text": clean,
                "category": valid_cat,
                "created_at": now_iso,
            },
        )
    return f"장기 기억에 저장 완료 (key={key}, category={valid_cat}): {clean}"


@tool
async def recall_career_memory(query: str) -> str:
    """장기 기억(Store)에서 사용자의 선호·제약조건·목표·집중 역량 메모를 의미 검색으로 꺼내 온다.

    query: 찾고 싶은 맥락 (예: '투자 가능 시간 제약', '선호 기술 스택', '목표 직무').
    """
    conninfo = get_psycopg_conninfo()
    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        store = await _open_store(aconn)
        items = await store.asearch(MEMORY_NAMESPACE, query=query.strip() or None, limit=6)
        if not items:
            items = await store.asearch(MEMORY_NAMESPACE, limit=6)

    if not items:
        return "저장된 장기 기억이 아직 없습니다."

    lines = []
    for it in items:
        val = dict(it.value or {})
        lines.append(f"- [{val.get('category', 'preference')}] {val.get('text', '')}")
    return "[장기 기억 조회 결과]\n" + "\n".join(lines)


COPILOT_TOOLS = [
    search_portfolio_docs,
    get_portfolio_character_and_loop,
    get_company_research,
    web_search_reference,
    save_career_memory,
    recall_career_memory,
]

COPILOT_TOOLS_BY_NAME = {t.name: t for t in COPILOT_TOOLS}
