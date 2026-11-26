"""조합형 멀티트랙(Multi-Track) 포트폴리오 템플릿 중앙 레지스트리 (Single Source of Truth).

공통 코어(개요/성과) 2개는 프로젝트당 1회만 생성하고,
사용자가 복수 선택한 프로젝트 유형 트랙 팩의 전문 섹션들을 중복 없이 조합합니다.
"""

from __future__ import annotations

import re
from typing import Any

CORE_TOP_SECTIONS: list[dict[str, Any]] = [
    {
        "section_type": "overview",
        "track": "core",
        "title": "개요 & 문제 정의",
        "display_order": 10,
        "placeholder": "프로젝트 배경, 해결하려는 핵심 문제, 기간·팀 구성·예산 등 제약조건을 정리합니다.",
    }
]

CORE_BOTTOM_SECTIONS: list[dict[str, Any]] = [
    {
        "section_type": "outcomes",
        "track": "core",
        "title": "성과, 지표 & 회고",
        "display_order": 900,
        "placeholder": "측정 가능한 정량·정성 성과, 배포/운영 결과, 배운 점과 향후 개선 방향을 정리합니다.",
    }
]

TRACK_PACKS: dict[str, dict[str, Any]] = {
    "engineering": {
        "id": "engineering",
        "label": "개발 · 엔지니어링",
        "short_label": "개발",
        "description": "웹·백엔드·AI·데이터 파이프라인·인프라 등 소프트웨어 구현 프로젝트",
        "color": "indigo",
        "skills_label": "기술 스택",
        "supports_github": True,
        "ai_persona": "시니어 소프트웨어 엔지니어 / 테크 리드",
        "prune_focus": "단순 패키지 설치, 뻔한 기본 CRUD 설명, 추상적 미사여구는 제거하고 아키텍처·트레이드오프·트러블슈팅·정량 성능 지표를 보존하세요.",
        "sections": [
            {
                "section_type": "architecture",
                "track": "engineering",
                "title": "시스템 아키텍처 & 기술 스택",
                "display_order": 110,
                "placeholder": "전체 서비스/데이터 흐름(Mermaid 포함), 핵심 컴포넌트, DB 및 인프라 구성을 정리합니다.",
            },
            {
                "section_type": "decisions",
                "track": "engineering",
                "title": "핵심 기술 의사결정 (Mini-ADR)",
                "display_order": 120,
                "placeholder": "상황 → 선택한 기술/구조 → 비교한 대안 → 수용한 트레이드오프를 기록합니다.",
            },
            {
                "section_type": "implementation",
                "track": "engineering",
                "title": "담당 역할 & 핵심 구현",
                "display_order": 130,
                "placeholder": "본인이 직접 설계·구현한 기능 모듈과 코드·API·파이프라인 포인트를 정리합니다.",
            },
            {
                "section_type": "troubleshooting",
                "track": "engineering",
                "title": "트러블슈팅 & 성능 개선",
                "display_order": 140,
                "placeholder": "장애·병목 계측 원인 → 해결 과정 → 재발 방지 설계를 기록합니다.",
            },
        ],
    },
    "product_planning": {
        "id": "product_planning",
        "label": "기획 · PM · 전략",
        "short_label": "기획·PM",
        "description": "서비스 기획, 프로덕트 매니지먼트, 공모전·사업 전략 제안, UX 리서치",
        "color": "violet",
        "skills_label": "활용 도구 & 기획 역량",
        "supports_github": False,
        "ai_persona": "시니어 프로덕트 매니저(PM) / 사업 전략 리드",
        "prune_focus": "근거 없는 추상적 주장이나 장황한 시장 서론은 제거하고 고객 인사이트, 가설, 우선순위 결정 논리, KPI 검증 결과를 보존하세요.",
        "sections": [
            {
                "section_type": "research_insights",
                "track": "product_planning",
                "title": "리서치 & 고객·시장 인사이트",
                "display_order": 210,
                "placeholder": "사용자 인터뷰, 설문, 경쟁사/시장 분석에서 도출한 핵심 Pain Point와 근거를 정리합니다.",
            },
            {
                "section_type": "solution_design",
                "track": "product_planning",
                "title": "솔루션 & 서비스·비즈니스 설계",
                "display_order": 220,
                "placeholder": "핵심 가치 제안, 사용자 여정(User Flow), 기능 명세, 수익/운영 모델을 정리합니다.",
            },
            {
                "section_type": "prioritization_alignment",
                "track": "product_planning",
                "title": "우선순위 · 이해관계자 조율",
                "display_order": 230,
                "placeholder": "MVP 범위 절단 기준, 개발·디자인·유관부서 간 의견 충돌 조율 과정을 기록합니다.",
            },
            {
                "section_type": "execution_validation",
                "track": "product_planning",
                "title": "실행 · 검증 (MVP / 파일럿 / 실험)",
                "display_order": 240,
                "placeholder": "런칭, A/B 테스트, UT, 파일럿 운영에서 확인한 사용자 반응과 피벗 내역을 정리합니다.",
            },
        ],
    },
    "data_research": {
        "id": "data_research",
        "label": "데이터 분석 · 리서치 · 논문",
        "short_label": "데이터·리서치",
        "description": "데이터 분석, 통계/ML 실험, 학부 연구·논문, 정책·도메인 리서치",
        "color": "cyan",
        "skills_label": "분석 도구 & 방법론",
        "supports_github": True,
        "ai_persona": "리드 데이터 사이언티스트 / 시니어 리서처",
        "prune_focus": "단순 전처리 코드 나열과 상투적 결론을 제거하고 핵심 가설, 방법론 선택 근거, 정량 실험 결과, 의사결정 연결점을 보존하세요.",
        "sections": [
            {
                "section_type": "hypothesis_eda",
                "track": "data_research",
                "title": "핵심 가설 & 데이터 수집 · EDA",
                "display_order": 310,
                "placeholder": "검증할 가설, 데이터 원천·규모, 전처리 및 탐색적 데이터 분석(EDA) 결과를 정리합니다.",
            },
            {
                "section_type": "methodology_modeling",
                "track": "data_research",
                "title": "분석 방법론 & 모델 · 실험 설계",
                "display_order": 320,
                "placeholder": "적용한 통계·ML·평가 지표 설계와 베이스라인 대비 실험 개선 과정을 정리합니다.",
            },
            {
                "section_type": "insights_recommendations",
                "track": "data_research",
                "title": "핵심 발견(Insights) & 의사결정 제안",
                "display_order": 330,
                "placeholder": "분석 결과에서 도출한 실행 가능한 액션 제안과 한계·보완점을 기록합니다.",
            },
        ],
    },
    "operations_leadership": {
        "id": "operations_leadership",
        "label": "운영 · 마케팅 · 리더십",
        "short_label": "운영·리더십",
        "description": "동아리·학회 운영, 캠페인/그로스 마케팅, 행사 기획, 인턴 프로세스 개선",
        "color": "amber",
        "skills_label": "핵심 역량 & 툴",
        "supports_github": False,
        "ai_persona": "조직 운영 / 그로스 마케팅 리드",
        "prune_focus": "단순 참석 기록이나 추상적 다짐을 제거하고 병목 진단, 프로세스 개선 설계, 이해관계자 조율 행동, 정량 성과를 보존하세요.",
        "sections": [
            {
                "section_type": "diagnosis_bottlenecks",
                "track": "operations_leadership",
                "title": "현황 진단 & 병목 분석",
                "display_order": 410,
                "placeholder": "기존 운영·마케팅·조직 프로세스의 비효율이나 이탈 지점을 어떻게 포착했는지 정리합니다.",
            },
            {
                "section_type": "strategy_process",
                "track": "operations_leadership",
                "title": "실행 전략 & 프로세스 · 캠페인 설계",
                "display_order": 420,
                "placeholder": "목표(KPI) 달성을 위해 설계한 캠페인, 운영 체계, 자동화·표준화 방안을 기록합니다.",
            },
            {
                "section_type": "collaboration_resolution",
                "track": "operations_leadership",
                "title": "팀 협업 · 갈등 조율 & 현장 개선",
                "display_order": 430,
                "placeholder": "팀원·외부 파트너 간 협업 조율, 돌발 이슈 대응, 현장 피드백 반영 사례를 정리합니다.",
            },
        ],
    },
    "general": {
        "id": "general",
        "label": "기타 · 자유 프로젝트",
        "short_label": "기타·자유",
        "description": "창작, 교육, 복합 대외활동 등 자유 형식의 포트폴리오 프로젝트",
        "color": "slate",
        "skills_label": "핵심 키워드 & 도구",
        "supports_github": False,
        "ai_persona": "시니어 커리어 포트폴리오 에디터",
        "prune_focus": "추상적 수식어와 중복 문장을 줄이고 구체적 행동, 산출물, 배운 점을 중심으로 간결히 다듬으세요.",
        "sections": [
            {
                "section_type": "key_contributions",
                "track": "general",
                "title": "본인 역할 & 핵심 기여",
                "display_order": 510,
                "placeholder": "프로젝트에서 본인이 주도적으로 맡은 역할과 핵심 기여를 구체적으로 정리합니다.",
            },
            {
                "section_type": "process_problem_solving",
                "track": "general",
                "title": "진행 과정 & 문제 해결",
                "display_order": 520,
                "placeholder": "진행 중 마주한 어려움과 이를 돌파하기 위해 선택한 해결 과정을 정리합니다.",
            },
        ],
    },
}

TRACK_ORDER = [
    "engineering",
    "product_planning",
    "data_research",
    "operations_leadership",
    "general",
]

ALL_KNOWN_SECTIONS: dict[str, dict[str, Any]] = {}
for _sec in CORE_TOP_SECTIONS + CORE_BOTTOM_SECTIONS:
    ALL_KNOWN_SECTIONS[_sec["section_type"]] = _sec
for _pack in TRACK_PACKS.values():
    for _sec in _pack["sections"]:
        ALL_KNOWN_SECTIONS[_sec["section_type"]] = _sec


def normalize_project_types(project_types: list[str] | None) -> list[str]:
    """유효한 트랙 ID만 순서대로 중복 제거하고, 비어 있으면 ['engineering']을 반환한다."""
    if not project_types:
        return ["engineering"]
    seen: list[str] = []
    for raw in project_types:
        key = str(raw).strip()
        if key in TRACK_PACKS and key not in seen:
            seen.append(key)
    return seen or ["engineering"]


def compose_sections_for_types(project_types: list[str] | None) -> list[dict[str, Any]]:
    """공통 코어(상단 overview) + 선택한 트랙 팩 섹션(중복 없음) + 공통 코어(하단 outcomes)를 조합한다."""
    normalized = normalize_project_types(project_types)
    composed: list[dict[str, Any]] = [dict(s) for s in CORE_TOP_SECTIONS]
    seen_types = {s["section_type"] for s in composed}

    for track_id in normalized:
        pack = TRACK_PACKS[track_id]
        for sec in pack["sections"]:
            if sec["section_type"] not in seen_types:
                composed.append(dict(sec))
                seen_types.add(sec["section_type"])

    for sec in CORE_BOTTOM_SECTIONS:
        if sec["section_type"] not in seen_types:
            composed.append(dict(sec))
            seen_types.add(sec["section_type"])

    return composed


def infer_track_for_section_type(section_type: str) -> str:
    known = ALL_KNOWN_SECTIONS.get(section_type)
    if known:
        return str(known["track"])
    return "custom"


def get_track_labels(project_types: list[str] | None) -> list[str]:
    return [TRACK_PACKS[t]["label"] for t in normalize_project_types(project_types)]


def get_combined_ai_guidance(project_types: list[str] | None) -> dict[str, str]:
    normalized = normalize_project_types(project_types)
    personas = [TRACK_PACKS[t]["ai_persona"] for t in normalized]
    prune_guides = [
        f"- [{TRACK_PACKS[t]['label']}] {TRACK_PACKS[t]['prune_focus']}"
        for t in normalized
    ]
    return {
        "persona": " / ".join(personas),
        "prune_focus": "\n".join(prune_guides),
        "labels": ", ".join(TRACK_PACKS[t]["label"] for t in normalized),
    }


def get_templates_payload() -> dict[str, Any]:
    """프론트엔드 동적 렌더링용 전체 템플릿 레지스트리 페이로드."""
    return {
        "core_sections": CORE_TOP_SECTIONS + CORE_BOTTOM_SECTIONS,
        "tracks": [TRACK_PACKS[t] for t in TRACK_ORDER],
    }


# ==============================================================================
# 섹션 제목 생성 기준 (Section Naming Policy — QA #1)
# ==============================================================================
SECTION_NAMING_RULES = (
    "[섹션 제목 생성 기준 (필수 준수)]\n"
    "1. 표준 섹션(`overview`, `architecture`, `decisions`, `implementation`, `troubleshooting`, `outcomes` 등)은 "
    "반드시 제공된 표준 제목을 그대로 사용하거나, 구체 핵심 주제를 덧붙일 때만 '표준 제목 — 핵심 주제(10자 내외)' 형식으로 작성하세요.\n"
    "2. 무의미하거나 모호한 추상 제목('요약', '내용', '정리', '기타', '섹션 1', '추가 사항', '본문', 'Overview', 'Summary') 단독 사용을 엄격히 금지합니다.\n"
    "3. 커스텀 섹션이나 리캡 소제목(`##`)은 '[관점/역할]: [구체 대상·해결 과제]' 명사구 구조(8~28자)로 작성해 제목만 보고도 어떤 내용인지 즉시 파악되게 하세요.\n"
    "   - 좋은 예: '트러블슈팅 & 성능 개선 — Redis 분산 락과 P99 지연 단축', '1. 문제 정의: 새벽 정산 배치 지연과 CS 병목'\n"
    "   - 나쁜 예: '섹션 1', '프로젝트 내용', '기타 정리', 'overview'"
)

_VAGUE_SECTION_TITLES = {
    "요약",
    "내용",
    "정리",
    "기타",
    "본문",
    "개요",
    "추가",
    "추가 내용",
    "추가 사항",
    "기타 내용",
    "기타 정리",
    "프로젝트 내용",
    "프로젝트 요약",
    "프로젝트 정리",
    "상세 내용",
    "핵심 내용",
    "핵심",
    "설명",
    "참고",
    "메모",
    "결과",
    "summary",
    "overview",
    "content",
    "section",
    "details",
    "notes",
    "misc",
    "other",
    "untitled",
    "conclusion",
    "introduction",
}
_GENERIC_NUMBERED_RE = re.compile(r"^(?:섹션|section|part|파트|항목|chapter|챕터)\s*\d*$", re.IGNORECASE)
_LEADING_DECOR_RE = re.compile(r"^[#\-\*\d\.\)\s]+")


def is_vague_section_title(title: str, section_type: str = "") -> bool:
    """제목이 비어 있거나, 영문 raw key이거나, 의미를 알 수 없는 추상어인지 판별한다."""
    clean = _LEADING_DECOR_RE.sub("", (title or "").strip()).strip()
    if len(clean) < 3:
        return True
    low = clean.lower()
    if section_type and low == section_type.strip().lower():
        return True
    if low in _VAGUE_SECTION_TITLES:
        return True
    if _GENERIC_NUMBERED_RE.match(clean):
        return True
    return False


def resolve_section_title(
    section_type: str,
    proposed_title: str = "",
    *,
    fallback_title: str = "",
    preserve_canonical: bool = True,
) -> str:
    """섹션 이름 생성 기준에 따라 모호·무의미한 AI 제목을 표준 제목으로 안전하게 정규화한다.

    - 표준 섹션(`ALL_KNOWN_SECTIONS` 등록 키):
      - 모호한 제목/raw key/과도한 길이(>36자)면 표준 제목(`canonical`) 반환
      - `preserve_canonical=True`일 때 표준 제목과 무관한 임의 제목 대신
        표준 제목 또는 `'표준 제목 — 구체 핵심 주제'` 형식만 허용
    - 커스텀 섹션:
      - 모호한 제목이면 `fallback_title` 사용, 아니면 정제된 제목(최대 40자) 반환
    """
    st = (section_type or "").strip()
    known = ALL_KNOWN_SECTIONS.get(st)
    canonical = str(known["title"]) if known else ""
    base_fallback = canonical or (fallback_title or "").strip() or st or "상세 내용 정리"

    cleaned = _LEADING_DECOR_RE.sub("", (proposed_title or "").strip()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    if not cleaned or is_vague_section_title(cleaned, st):
        return base_fallback

    if known and preserve_canonical:
        if cleaned == canonical:
            return canonical
        # "표준 제목 — 구체 주제" / "표준 제목: 구체 주제" 형태는 소주제가 구체적일 때만 허용
        for sep in (" — ", " - ", ": ", " | "):
            if cleaned.startswith(canonical + sep):
                sub = cleaned[len(canonical) + len(sep) :].strip()
                if 3 <= len(sub) <= 24 and not is_vague_section_title(sub, st):
                    return f"{canonical} — {sub}"
                return canonical
        # 표준 섹션인데 LLM이 표준 제목을 임의로 갈아치운 경우 표준 제목 유지 (일관성 보장)
        return canonical

    return cleaned[:40]
