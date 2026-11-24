/**
 * 조합형 멀티트랙 포트폴리오 유형 메타 & 스타일 유틸
 */

export const DEFAULT_TRACKS = [
  {
    id: "engineering",
    label: "개발 · 엔지니어링",
    short_label: "개발",
    description: "웹·백엔드·AI·데이터 파이프라인·인프라 구현",
    color: "indigo",
    skills_label: "기술 스택",
    supports_github: true,
    section_count: 4,
  },
  {
    id: "product_planning",
    label: "기획 · PM · 전략",
    short_label: "기획·PM",
    description: "서비스 기획, 프로덕트 매니지먼트, 공모전·사업 전략",
    color: "violet",
    skills_label: "활용 도구 & 기획 역량",
    supports_github: false,
    section_count: 4,
  },
  {
    id: "data_research",
    label: "데이터 분석 · 리서치 · 논문",
    short_label: "데이터·리서치",
    description: "데이터 분석, 실험/가설 검증, 학부 연구·논문",
    color: "cyan",
    skills_label: "분석 도구 & 방법론",
    supports_github: true,
    section_count: 3,
  },
  {
    id: "operations_leadership",
    label: "운영 · 마케팅 · 리더십",
    short_label: "운영·리더십",
    description: "동아리·학회 운영, 캠페인·그로스, 행사·프로세스 개선",
    color: "amber",
    skills_label: "핵심 역량 & 툴",
    supports_github: false,
    section_count: 3,
  },
  {
    id: "general",
    label: "기타 · 자유 프로젝트",
    short_label: "기타·자유",
    description: "창작, 교육, 복합 대외활동 등 자유 형식",
    color: "slate",
    skills_label: "핵심 키워드 & 도구",
    supports_github: false,
    section_count: 2,
  },
];

export const TRACK_BADGE_STYLES = {
  core: "bg-slate-100 text-slate-700 border-slate-200",
  engineering: "bg-indigo-50 text-indigo-800 border-indigo-200",
  product_planning: "bg-violet-50 text-violet-800 border-violet-200",
  data_research: "bg-cyan-50 text-cyan-800 border-cyan-200",
  operations_leadership: "bg-amber-50 text-amber-800 border-amber-200",
  general: "bg-slate-100 text-slate-700 border-slate-300",
  custom: "bg-emerald-50 text-emerald-800 border-emerald-200",
};

export const TRACK_LABELS = {
  core: "공통 코어",
  engineering: "개발 · 엔지니어링",
  product_planning: "기획 · PM · 전략",
  data_research: "데이터 · 리서치",
  operations_leadership: "운영 · 리더십",
  general: "기타 · 자유",
  custom: "사용자 추가 섹션",
};

export const TRACK_SHORT_LABELS = {
  core: "공통",
  engineering: "개발",
  product_planning: "기획·PM",
  data_research: "데이터·리서치",
  operations_leadership: "운영·리더십",
  general: "기타",
  custom: "커스텀",
};

export function getTrackBadgeClass(trackId) {
  return TRACK_BADGE_STYLES[trackId] || TRACK_BADGE_STYLES.general;
}

export function getSkillsFieldLabel(selectedTypes, tracks = DEFAULT_TRACKS) {
  const list = selectedTypes && selectedTypes.length > 0 ? selectedTypes : ["engineering"];
  if (list.length === 1) {
    const found = tracks.find((t) => t.id === list[0]);
    return found?.skills_label || "기술 스택 · 역량";
  }
  return "핵심 기술 · 도구 · 역량 (쉼표 구분)";
}

export function groupSectionsByTrack(sections) {
  const groups = [];
  const byTrack = new Map();
  for (const sec of sections || []) {
    const track = sec.track || "core";
    if (!byTrack.has(track)) {
      const grp = {
        track,
        label: TRACK_LABELS[track] || track,
        sections: [],
      };
      byTrack.set(track, grp);
      groups.push(grp);
    }
    byTrack.get(track).sections.push(sec);
  }
  return groups;
}
