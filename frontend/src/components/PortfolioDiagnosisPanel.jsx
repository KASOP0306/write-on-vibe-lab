import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Award,
  BookOpen,
  ChevronDown,
  ChevronUp,
  Compass,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Target,
} from "lucide-react";
import { api } from "../api/client.js";
import RadarChart, { RubricReferenceModal } from "./RadarChart.jsx";

const PORTFOLIO_AXIS_LIST = [
  { id: "problem_depth", label: "문제해결 깊이", domain: "internal" },
  { id: "evidence_impact", label: "증거력·성과", domain: "internal" },
  { id: "narrative_coherence", label: "서사 일관성", domain: "internal" },
  { id: "time_execution", label: "시간·우선순위", domain: "external" },
  { id: "people_collaboration", label: "인적·협업관리", domain: "external" },
  { id: "adaptability_growth", label: "적응·학습력", domain: "external" },
];

const STAR_AXIS_LIST = [
  { id: "situation", label: "S 상황" },
  { id: "task", label: "T 책임" },
  { id: "action", label: "A 행동" },
  { id: "result", label: "R 성과" },
  { id: "learning", label: "L 회고" },
];

const EXTERNAL_NOTE_FIELDS = [
  {
    key: "time_execution",
    label: "시간 · 일정 · 우선순위 관리 경험 (선택)",
    placeholder:
      "예: 3주 마감 해커톤에서 핵심 기능 3개로 스코프를 절단하고 주간 마일스톤을 관리해 기한 내 배포",
  },
  {
    key: "people_collaboration",
    label: "인적 · 이해관계자 협업 경험 (선택)",
    placeholder:
      "예: 디자이너·백엔드 간 API 스펙 충돌 시 데이터 계약서(OpenAPI)를 선제안해 주 2회 싱크로 조율",
  },
  {
    key: "adaptability_growth",
    label: "적응력 · 실패 복구 · 학습 민첩성 경험 (선택)",
    placeholder:
      "예: 중간 시연 피드백 후 핵심 UX를 48시간 만에 피벗하거나 장애 원인을 포스트모템으로 정리해 재발 방지",
  },
];

export default function PortfolioDiagnosisPanel({ projectCount = 0 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [showExternalForm, setShowExternalForm] = useState(false);
  const [externalNotes, setExternalNotes] = useState({
    time_execution: "",
    people_collaboration: "",
    adaptability_growth: "",
  });
  const [rubricRef, setRubricRef] = useState(null);
  const [showRubricModal, setShowRubricModal] = useState(false);

  const loadCached = async () => {
    setLoading(true);
    try {
      const res = await api.getPortfolioDiagnosis();
      setData(res);
      if (res?.external_notes) {
        setExternalNotes((prev) => ({
          ...prev,
          ...res.external_notes,
        }));
      }
    } catch (err) {
      console.warn("Failed to load cached diagnosis:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCached();
  }, [projectCount]);

  const handleOpenRubric = async () => {
    setShowRubricModal(true);
    if (!rubricRef) {
      try {
        const ref = await api.getRubricReference();
        setRubricRef(ref);
      } catch (err) {
        console.warn(err);
      }
    }
  };

  const handleRunDiagnosis = async () => {
    if (running) return;
    setRunning(true);
    setError("");
    try {
      const res = await api.runPortfolioDiagnosis(externalNotes);
      setData(res);
      setShowExternalForm(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  };

  const diag = data?.diagnosis && data.diagnosis.character_archetype ? data.diagnosis : null;
  const starAvg = data?.overall_star_averages || {};

  const portfolioRadarItems = PORTFOLIO_AXIS_LIST.map((ax) => {
    const entry = diag?.axes?.[ax.id] || {};
    return {
      id: ax.id,
      label: ax.label,
      domain: ax.domain,
      score: entry.score || 0,
      status: entry.evidence_status || "verified",
    };
  });

  const starRadarItems = STAR_AXIS_LIST.map((ax) => ({
    id: ax.id,
    label: ax.label,
    score: starAvg?.axes?.[ax.id]?.score || 0,
  }));

  const missingExternalAxes = PORTFOLIO_AXIS_LIST.filter(
    (ax) => diag?.axes?.[ax.id]?.evidence_status === "missing"
  );

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-700">
            <Compass className="w-4 h-4" />
            <span>포트폴리오 캐릭터 &amp; 이중 역량 레이더 진단</span>
          </div>
          <h3 className="text-lg font-bold text-slate-900 mt-0.5">
            내 포트폴리오 종합 점수 (내적 3축 × 외적 3축) &amp; 평균 STAR-L
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            KFLA · Google 4대 채용 기준 · Spencer 빙산 모델로 반복 패턴, 강점과 약점(50:50)을 냉정하게 진단합니다.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleOpenRubric}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            <BookOpen className="w-3.5 h-3.5 text-indigo-600" />
            <span>평가 기준 레퍼런스</span>
          </button>

          <button
            type="button"
            onClick={() => setShowExternalForm((v) => !v)}
            className="inline-flex items-center gap-1 rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 text-xs font-semibold text-violet-800 hover:bg-violet-100"
          >
            <span>외적 역량 보충 메모</span>
            {showExternalForm ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>

          <button
            type="button"
            disabled={running || projectCount === 0}
            onClick={handleRunDiagnosis}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {running ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            <span>{running ? "AI 캐릭터 분석 중..." : diag ? "캐릭터 재진단" : "포트폴리오 캐릭터 진단"}</span>
          </button>
        </div>
      </div>

      {/* Optional External Competency Context Drawer */}
      {showExternalForm && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/40 p-4 space-y-3">
          <div className="text-xs text-violet-950">
            <strong>외적 역량 보충 메모 (선택):</strong> 코드·기획서에는 잘 드러나지 않는{" "}
            <strong>시간·일정 관리, 인적·협업 조율, 위기 대응 경험</strong>을 짧게 적어두면
            근거 기반으로 정확히 반영됩니다.
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {EXTERNAL_NOTE_FIELDS.map((field) => (
              <label key={field.key} className="block space-y-1">
                <span className="text-[11px] font-semibold text-slate-700">
                  {field.label}
                </span>
                <textarea
                  rows={3}
                  value={externalNotes[field.key] || ""}
                  onChange={(e) =>
                    setExternalNotes((prev) => ({
                      ...prev,
                      [field.key]: e.target.value,
                    }))
                  }
                  placeholder={field.placeholder}
                  className="w-full rounded-lg border border-slate-200 bg-white p-2 text-xs focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                />
              </label>
            ))}
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              disabled={running || projectCount === 0}
              onClick={handleRunDiagnosis}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-violet-700 disabled:opacity-50"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>보충 메모 반영해 진단 실행</span>
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-800">
          {error}
        </div>
      )}

      {loading ? (
        <div className="py-8 flex items-center justify-center gap-2 text-xs text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>진단 결과 불러오는 중...</span>
        </div>
      ) : !diag ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-6 text-center space-y-2.5">
          <p className="text-sm font-semibold text-slate-800">
            아직 포트폴리오 캐릭터 진단이 실행되지 않았습니다.
          </p>
          <p className="text-xs text-slate-500 max-w-xl mx-auto">
            등록된 프로젝트·섹션·STAR·신념을 종합해 <strong>6축 육각형 점수(내적 3축 × 외적 3축)</strong>,{" "}
            <strong>나의 포트폴리오 캐릭터</strong>, 그리고 <strong>강점 3가지 vs 약점·사각지대 3가지</strong>를
            한눈에 정리해 드립니다.
          </p>
          <button
            type="button"
            disabled={running || projectCount === 0}
            onClick={handleRunDiagnosis}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>
              {projectCount === 0
                ? "먼저 프로젝트를 1개 이상 등록하세요"
                : "지금 포트폴리오 캐릭터 진단하기"}
            </span>
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          {/* Character Archetype Banner */}
          <div className="rounded-2xl bg-gradient-to-r from-slate-900 via-indigo-950 to-violet-950 p-5 text-white space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-indigo-300">
                  나의 포트폴리오 캐릭터 아키타입 ({diag.analyzed_project_count || projectCount}개 프로젝트 종합)
                </div>
                <div className="text-xl font-extrabold mt-0.5">
                  {diag.character_archetype}
                </div>
                <p className="text-xs text-slate-200 mt-1 leading-relaxed">
                  {diag.one_line_identity}
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <div className="rounded-xl bg-white/10 px-3.5 py-2 text-center">
                  <div className="text-[10px] text-indigo-200">포트폴리오 종합</div>
                  <div className="text-lg font-extrabold">{diag.overall_score}점</div>
                </div>
                <div className="rounded-xl bg-white/10 px-3 py-2 text-center">
                  <div className="text-[10px] text-sky-200">내적 3축</div>
                  <div className="text-sm font-bold">{diag.internal_score}</div>
                </div>
                <div className="rounded-xl bg-white/10 px-3 py-2 text-center">
                  <div className="text-[10px] text-violet-200">외적 3축</div>
                  <div className="text-sm font-bold">{diag.external_score}</div>
                </div>
              </div>
            </div>

            {(diag.recurring_patterns || []).length > 0 && (
              <div className="pt-2 border-t border-white/10 space-y-1.5">
                <div className="text-[11px] font-semibold text-indigo-200">
                  프로젝트 전반에서 반복 관찰되는 나의 패턴:
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {diag.recurring_patterns.map((pat, i) => (
                    <span
                      key={i}
                      className="rounded-lg bg-white/10 px-2.5 py-1 text-[11px] text-slate-100"
                    >
                      • {pat}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Missing External Evidence Alert */}
          {missingExternalAxes.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 flex flex-wrap items-center justify-between gap-2 text-xs text-amber-900">
              <div className="flex items-start gap-2">
                <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                <span>
                  <strong>외적 역량 사각지대 감지:</strong>{" "}
                  {missingExternalAxes.map((a) => a.label).join(", ")} 축은 현재 포트폴리오에
                  근거가 부족해 <strong>미검증(보수 평가)</strong> 상태입니다. 실제 협업·일정 관리
                  경험이 있다면 &apos;외적 역량 보충 메모&apos;에 추가 후 재진단해 보세요.
                </span>
              </div>
              <button
                type="button"
                onClick={() => setShowExternalForm(true)}
                className="rounded-lg bg-amber-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-amber-700 shrink-0"
              >
                보충 메모 입력
              </button>
            </div>
          )}

          {/* Dual Radar Graphs: 6-Axis Portfolio Hexagon + 5-Axis Average STAR-L Pentagon */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Left: 6-Axis Portfolio Character Hexagon */}
            <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs font-bold text-slate-900">
                    ① 6축 포트폴리오 종합 레이더 (내적 3 × 외적 3)
                  </div>
                  <div className="text-[11px] text-slate-500">
                    남색: 내적(산출물) · 보라: 외적(시간·인적·적응) · 빨강: 미검증
                  </div>
                </div>
                <span className="text-sm font-extrabold text-indigo-700">
                  {diag.overall_score} / 100
                </span>
              </div>

              <RadarChart
                items={portfolioRadarItems}
                size={275}
                strokeColor="#4f46e5"
                fillColor="rgba(79, 70, 229, 0.16)"
              />

              <div className="space-y-2 pt-1">
                {PORTFOLIO_AXIS_LIST.map((ax) => {
                  const entry = diag?.axes?.[ax.id] || {};
                  const statusLabel =
                    entry.evidence_status === "verified"
                      ? "검증됨"
                      : entry.evidence_status === "partial"
                        ? "부분 근거"
                        : "근거 부족";
                  const statusClass =
                    entry.evidence_status === "verified"
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : entry.evidence_status === "partial"
                        ? "bg-amber-50 text-amber-700 border-amber-200"
                        : "bg-rose-50 text-rose-700 border-rose-200";
                  return (
                    <div
                      key={ax.id}
                      className="rounded-lg bg-white border border-slate-200 px-3 py-2 text-[11px] space-y-0.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-bold text-slate-800">
                          {ax.label}{" "}
                          <span className="text-[10px] font-medium text-slate-400">
                            ({ax.domain === "external" ? "외적" : "내적"})
                          </span>
                        </span>
                        <div className="flex items-center gap-1.5">
                          <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${statusClass}`}>
                            {statusLabel}
                          </span>
                          <span className="font-extrabold text-slate-900">
                            {entry.score || 0}점
                          </span>
                        </div>
                      </div>
                      {entry.evidence && (
                        <p className="text-slate-600 leading-snug">{entry.evidence}</p>
                      )}
                      {entry.improvement_tip && (
                        <p className="text-indigo-700 leading-snug">
                          → {entry.improvement_tip}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right: 5-Axis Overall STAR-L Pentagon + Growth Roadmap */}
            <div className="space-y-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs font-bold text-slate-900">
                      ② 전체 평균 5축 STAR-L 레이더 (BARS 기준)
                    </div>
                    <div className="text-[11px] text-slate-500">
                      평가된 STAR {starAvg.evaluated_count || 0} / {starAvg.total_count || 0}건 평균
                    </div>
                  </div>
                  <span className="text-sm font-extrabold text-emerald-700">
                    {starAvg.evaluated_count > 0 ? `${starAvg.weighted_score} / 100` : "미채점"}
                  </span>
                </div>

                <RadarChart
                  items={starRadarItems}
                  size={250}
                  strokeColor="#059669"
                  fillColor="rgba(5, 150, 105, 0.16)"
                />

                {starAvg.evaluated_count === 0 && (
                  <p className="text-[11px] text-slate-500 text-center">
                    각 프로젝트 워크스페이스의 <strong>연결된 STAR 경험</strong> 탭에서{" "}
                    <strong>5축 BARS 재채점</strong>을 누르면 이 그래프가 채워집니다.
                  </p>
                )}
              </div>

              {/* Next Growth Actions */}
              {(diag.growth_actions || []).length > 0 && (
                <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 space-y-2.5">
                  <div className="text-xs font-bold text-indigo-950 flex items-center gap-1.5">
                    <Target className="w-4 h-4 text-indigo-600" />
                    <span>약점 보완 우선 성장 액션 (3가지)</span>
                  </div>
                  <div className="space-y-2">
                    {diag.growth_actions.map((g, i) => (
                      <div
                        key={i}
                        className="rounded-lg bg-white border border-indigo-100 p-3 text-xs space-y-1"
                      >
                        <div className="text-[11px] font-bold text-rose-700">
                          대상 약점: {g.target_weakness}
                        </div>
                        <div className="font-semibold text-slate-900">
                          {i + 1}. {g.action}
                        </div>
                        <div className="text-[11px] text-emerald-700">
                          기대 효과: {g.expected_impact}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 50:50 Balanced Strengths vs Weaknesses & Blind Spots */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Left 50%: Strengths */}
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/30 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-emerald-950 flex items-center gap-1.5">
                  <Award className="w-4 h-4 text-emerald-600" />
                  <span>핵심 강점 &amp; 무기 (50%)</span>
                </h4>
                <span className="text-[11px] font-semibold text-emerald-700">
                  {(diag.strengths || []).length}개
                </span>
              </div>
              <div className="space-y-2.5">
                {(diag.strengths || []).map((st, idx) => (
                  <div
                    key={idx}
                    className="rounded-xl bg-white border border-emerald-200/80 p-3.5 space-y-1.5 text-xs"
                  >
                    <div className="font-bold text-slate-900">
                      {idx + 1}. {st.title}
                    </div>
                    <p className="text-slate-600 leading-relaxed">{st.detail}</p>
                    {(st.evidence_projects || []).length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-0.5">
                        {st.evidence_projects.map((p, i) => (
                          <span
                            key={i}
                            className="rounded-md bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800"
                          >
                            {p}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Right 50%: Weaknesses & Blind Spots (Equal Prominence!) */}
            <div className="rounded-2xl border border-rose-200 bg-rose-50/30 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-rose-950 flex items-center gap-1.5">
                  <AlertTriangle className="w-4 h-4 text-rose-600" />
                  <span>핵심 약점 &amp; 면접 사각지대 (동등 50%)</span>
                </h4>
                <span className="text-[11px] font-semibold text-rose-700">
                  {(diag.weaknesses || []).length}개
                </span>
              </div>
              <div className="space-y-2.5">
                {(diag.weaknesses || []).map((wk, idx) => (
                  <div
                    key={idx}
                    className="rounded-xl bg-white border border-rose-200/80 p-3.5 space-y-1.5 text-xs"
                  >
                    <div className="font-bold text-slate-900">
                      {idx + 1}. {wk.title}
                    </div>
                    <p className="text-slate-600 leading-relaxed">{wk.detail}</p>
                    {(wk.evidence_projects || []).length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-0.5">
                        {wk.evidence_projects.map((p, i) => (
                          <span
                            key={i}
                            className="rounded-md bg-rose-50 border border-rose-200 px-1.5 py-0.5 text-[10px] font-medium text-rose-800"
                          >
                            {p}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <RubricReferenceModal
        open={showRubricModal}
        onClose={() => setShowRubricModal(false)}
        reference={rubricRef}
      />
    </section>
  );
}
