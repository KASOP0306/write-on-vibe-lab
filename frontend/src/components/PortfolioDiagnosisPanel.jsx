import { useEffect, useState } from "react";
import {
  ArrowRight,
  Award,
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  Layers,
  Loader2,
  SlidersHorizontal,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { api } from "../api/client.js";

const STAR_AXIS_META = [
  { id: "situation", code: "S", label: "상황·맥락", maxPoints: 12 },
  { id: "task", code: "T", label: "과제·책임", maxPoints: 14 },
  { id: "action", code: "A", label: "행동·실행·운영", maxPoints: 36 },
  { id: "result", code: "R", label: "결과·검증", maxPoints: 26 },
  { id: "learning", code: "L", label: "회고·전이", maxPoints: 12 },
];

const LEVEL_BADGE_CLASSES = {
  emerald: "bg-emerald-500/20 text-emerald-200 border-emerald-400/40",
  indigo: "bg-indigo-500/20 text-indigo-200 border-indigo-400/40",
  amber: "bg-amber-500/20 text-amber-200 border-amber-400/40",
  slate: "bg-white/10 text-slate-200 border-white/20",
};

export default function PortfolioDiagnosisPanel({
  projectCount = 0,
  experienceSignature = "",
  onJumpToMiner = null,
  onOpenProject = null,
}) {
  const [expanded, setExpanded] = useState(true);
  const [mastery, setMastery] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Representative 4-project selector
  const [showSelector, setShowSelector] = useState(false);
  const [draftSelectedIds, setDraftSelectedIds] = useState([]);
  const [savingSelection, setSavingSelection] = useState(false);

  // 21-checkpoint heatmap toggle
  const [showHeatmap, setShowHeatmap] = useState(false);

  // Rubric v2.0 Reference Modal
  const [rubricRef, setRubricRef] = useState(null);
  const [showRubricModal, setShowRubricModal] = useState(false);

  const loadMastery = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.getPortfolioMastery();
      setMastery(res);
      const manualIds = (res?.all_projects || [])
        .filter((p) => p.is_selected)
        .map((p) => p.project_id);
      setDraftSelectedIds(manualIds);
    } catch (err) {
      setError(`STAR-L 마스터리 조회 실패: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMastery();
  }, [projectCount, experienceSignature]);

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

  const toggleProjectSelection = (pid) => {
    setDraftSelectedIds((prev) => {
      if (prev.includes(pid)) {
        return prev.filter((id) => id !== pid);
      }
      if (prev.length >= 4) {
        return prev;
      }
      return [...prev, pid];
    });
  };

  const handleSaveSelection = async () => {
    if (savingSelection) return;
    setSavingSelection(true);
    setError("");
    try {
      const updated = await api.updatePortfolioSelection(draftSelectedIds);
      setMastery(updated);
      setShowSelector(false);
    } catch (err) {
      setError(`대표 프로젝트 저장 실패: ${err.message}`);
    } finally {
      setSavingSelection(false);
    }
  };

  const level = mastery?.level || {
    code: "Lv.1",
    name: "Seed",
    color: "slate",
    description: "첫 대표 프로젝트의 STAR-L 경험 채굴을 시작한 단계",
  };
  const totalXp = mastery?.total_xp ?? 0;
  const maxTotalXp = mastery?.max_total_xp ?? 1000;
  const xpPct = mastery?.xp_pct ?? 0;
  const projectCap = mastery?.project_cap ?? 250;
  const selectedProjects = mastery?.selected_projects || [];
  const allProjects = mastery?.all_projects || [];
  const starAvg = mastery?.star_averages || {};
  const weakestCheckpoints = mastery?.weakest_checkpoints || [];
  const heatmap = mastery?.checkpoint_heatmap || [];

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div
          onClick={() => setExpanded((v) => !v)}
          className="cursor-pointer select-none min-w-0 flex-1 flex flex-wrap items-center gap-2"
        >
          <Award className="w-5 h-5 text-indigo-600 shrink-0" />
          <h3 className="text-base font-bold text-slate-900">
            STAR-L 마스터리
          </h3>
          {mastery && !expanded && (
            <span className="rounded-full bg-indigo-50 border border-indigo-200 px-2.5 py-0.5 text-[11px] font-bold text-indigo-800">
              {level.code} {level.name} · {totalXp} / {maxTotalXp} XP
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            {expanded ? (
              <>
                <ChevronUp className="w-3.5 h-3.5" />
                <span>접기</span>
              </>
            ) : (
              <>
                <ChevronDown className="w-3.5 h-3.5" />
                <span>펼치기</span>
              </>
            )}
          </button>

          {expanded && (
            <>
              <button
                type="button"
                onClick={handleOpenRubric}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                <BookOpen className="w-3.5 h-3.5 text-indigo-600" />
                <span>21지표 평가 기준</span>
              </button>

              {allProjects.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowSelector((v) => !v)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
                >
                  <SlidersHorizontal className="w-3.5 h-3.5" />
                  <span>대표 프로젝트 선택 ({draftSelectedIds.length}/4)</span>
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {expanded && (
        <>
          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-800">
              {error}
            </div>
          )}

          {/* Representative 4-Project Selector Drawer */}
          {showSelector && (
            <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs text-indigo-950">
                  <strong>대표 프로젝트 최대 4개 선택:</strong> 포트폴리오 {maxTotalXp.toLocaleString()} XP 점수에 반영할 핵심 프로젝트 4개를 고르세요. (4개 미만 선택 시 남은 슬롯은 XP 상위 프로젝트로 자동 채워집니다.)
                </div>
                <span className="text-xs font-bold text-indigo-800">
                  선택됨: {draftSelectedIds.length} / 4
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {allProjects.map((proj) => {
                  const checked = draftSelectedIds.includes(proj.project_id);
                  const disabled = !checked && draftSelectedIds.length >= 4;
                  return (
                    <button
                      key={proj.project_id}
                      type="button"
                      disabled={disabled}
                      onClick={() => toggleProjectSelection(proj.project_id)}
                      className={`text-left rounded-xl border p-3 flex items-center justify-between gap-2 transition ${
                        checked
                          ? "border-indigo-500 bg-white ring-2 ring-indigo-500/15"
                          : "border-slate-200 bg-white/80 hover:border-slate-300 disabled:opacity-45"
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="text-xs font-bold text-slate-900 truncate">
                          {proj.name}
                        </div>
                        <div className="text-[11px] text-slate-500">
                          경험 {proj.experience_count}건 · {proj.capped_xp} / {proj.cap} XP
                        </div>
                      </div>
                      <span
                        className={`w-5 h-5 rounded-md border flex items-center justify-center shrink-0 ${
                          checked
                            ? "bg-indigo-600 border-indigo-600 text-white"
                            : "border-slate-300 bg-white"
                        }`}
                      >
                        {checked && <Check className="w-3.5 h-3.5" />}
                      </span>
                    </button>
                  );
                })}
              </div>

              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDraftSelectedIds([])}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  자동 상위 4개로 초기화
                </button>
                <button
                  type="button"
                  disabled={savingSelection}
                  onClick={handleSaveSelection}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {savingSelection ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  <span>대표 프로젝트 저장</span>
                </button>
              </div>
            </div>
          )}

          {loading ? (
            <div className="py-8 flex items-center justify-center gap-2 text-xs text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>누적 STAR-L 마스터리 계산 중...</span>
            </div>
          ) : (
            <div className="space-y-5">
              {/* Cumulative 600 XP Hero Banner */}
              <div className="rounded-2xl bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 p-5 text-white space-y-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-full border px-2.5 py-0.5 text-[11px] font-bold ${
                          LEVEL_BADGE_CLASSES[level.color] || LEVEL_BADGE_CLASSES.slate
                        }`}
                      >
                        {level.code} · {level.name}
                      </span>
                      <span className="text-[11px] text-indigo-200">
                        대표 {selectedProjects.length} / {mastery?.max_selected_projects || 4}개 프로젝트 반영 중
                      </span>
                    </div>
                    <p className="text-xs text-slate-300 mt-1">{level.description}</p>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <div className="rounded-xl bg-white/10 px-4 py-2 text-center">
                      <div className="text-[10px] text-indigo-200">누적 포트폴리오 XP</div>
                      <div className="text-xl font-extrabold">
                        {totalXp} <span className="text-xs font-normal text-slate-300">/ {maxTotalXp}</span>
                      </div>
                    </div>
                    <div className="rounded-xl bg-white/10 px-3.5 py-2 text-center">
                      <div className="text-[10px] text-emerald-200">평균 STAR-L</div>
                      <div className="text-lg font-extrabold">
                        {starAvg?.evaluated_count > 0 ? `${starAvg.weighted_score}점` : "-"}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Global 600 XP Progress Bar with 150 / 300 / 480 milestones */}
                <div className="space-y-1.5">
                  <div className="h-3 w-full rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-indigo-400 via-violet-400 to-emerald-400 transition-all duration-500"
                      style={{ width: `${xpPct}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-slate-300">
                    <span>Lv.1 Seed (0)</span>
                    <span>Lv.2 Builder (250)</span>
                    <span>Lv.3 Proven (500)</span>
                    <span>Lv.4 Bar Raiser (800~1000)</span>
                  </div>
                  {mastery?.next_level && (
                    <div className="text-[11px] text-indigo-200">
                      다음 단계 <strong>{mastery.next_level.code} {mastery.next_level.name}</strong>까지{" "}
                      <strong>{mastery.xp_to_next_level} XP</strong> 남았습니다.
                    </div>
                  )}
                </div>
              </div>

              {/* Representative 4 Project Slots (150 XP Cap Each) */}
              <div className="space-y-2.5">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                    <Layers className="w-4 h-4 text-indigo-600" />
                    <span>대표 4개 프로젝트 슬롯 (프로젝트당 최대 {projectCap} XP 캡 · 상위 4경험 체감 합산)</span>
                  </div>
                  {mastery?.unlinked_experience_count > 0 && (
                    <span className="text-[11px] text-amber-700">
                      * 프로젝트 미연결 경험 {mastery.unlinked_experience_count}건은 프로젝트 XP에 미합산
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                  {[0, 1, 2, 3].map((slotIdx) => {
                    const proj = selectedProjects[slotIdx];
                    if (!proj) {
                      return (
                        <div
                          key={`empty-${slotIdx}`}
                          className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 p-3.5 flex flex-col justify-between min-h-[126px]"
                        >
                          <div className="text-[11px] font-semibold text-slate-400">
                            슬롯 #{slotIdx + 1} (비어 있음)
                          </div>
                          <p className="text-[11px] text-slate-400">
                            프로젝트를 추가하고 경험을 채굴하면 최대 {projectCap} XP가 누적됩니다.
                          </p>
                        </div>
                      );
                    }
                    return (
                      <div
                        key={proj.project_id}
                        className="rounded-xl border border-slate-200 bg-slate-50/50 p-3.5 flex flex-col justify-between gap-2.5"
                      >
                        <div className="space-y-1">
                          <div className="flex items-center justify-between gap-1">
                            <span
                              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                                proj.selection_mode === "manual"
                                  ? "bg-indigo-100 text-indigo-800"
                                  : "bg-slate-200 text-slate-700"
                              }`}
                            >
                              {proj.selection_mode === "manual" ? "직접 선택" : "자동 배정"}
                            </span>
                            {proj.cap_reached && (
                              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-800">
                                {proj.cap} CAP 달성
                              </span>
                            )}
                          </div>
                          <button
                            type="button"
                            onClick={() => onOpenProject && onOpenProject(proj.project_id)}
                            className="text-left text-xs font-bold text-slate-900 hover:text-indigo-700 line-clamp-1"
                          >
                            {proj.name}
                          </button>
                          <div className="text-[11px] text-slate-500">
                            채굴 경험 {proj.experience_count}건 · 최고 {proj.best_score}점
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between text-[11px]">
                            <span className="font-semibold text-slate-600">누적 XP</span>
                            <span className="font-extrabold text-indigo-700">
                              {proj.capped_xp} / {proj.cap}
                            </span>
                          </div>
                          <div className="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                proj.cap_reached ? "bg-emerald-500" : "bg-indigo-600"
                              }`}
                              style={{ width: `${proj.progress_pct}%` }}
                            />
                          </div>
                          {onJumpToMiner && (
                            <button
                              type="button"
                              onClick={() => onJumpToMiner(proj.project_id, "")}
                              className="w-full mt-1 inline-flex items-center justify-center gap-1 rounded-lg border border-indigo-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-50"
                            >
                              <Sparkles className="w-3 h-3" />
                              <span>이 프로젝트 경험 채굴</span>
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* 5-Axis STAR-L Average + Top 3 Weakest Checkpoints Action Board */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="rounded-xl border border-slate-200 bg-slate-50/40 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-bold text-slate-800">
                      5축 STAR-L 누적 달성도 (대표 프로젝트 기준)
                    </div>
                    <span className="text-[11px] text-slate-500">
                      평가된 경험 {starAvg?.evaluated_count || 0}건
                    </span>
                  </div>
                  <div className="space-y-2">
                    {STAR_AXIS_META.map((m) => {
                      const entry = starAvg?.axes?.[m.id] || {};
                      const pct = entry.score || 0;
                      const earned = entry.earned ?? Math.round((pct / 100) * m.maxPoints);
                      const color =
                        pct >= 75
                          ? "bg-emerald-500"
                          : pct >= 50
                            ? "bg-indigo-500"
                            : pct >= 25
                              ? "bg-amber-500"
                              : "bg-rose-400";
                      return (
                        <div key={m.id} className="space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-semibold text-slate-700">
                              <span className="font-bold text-indigo-700 mr-1">{m.code}</span>
                              {m.label}
                            </span>
                            <span className="font-bold text-slate-800">
                              {earned} / {m.maxPoints}점 <span className="text-slate-400 font-normal">({pct}%)</span>
                            </span>
                          </div>
                          <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${color}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="rounded-xl border border-amber-200 bg-amber-50/30 p-4 space-y-2.5">
                  <div className="text-xs font-bold text-amber-950 flex items-center gap-1.5">
                    <Target className="w-4 h-4 text-amber-600" />
                    <span>지금 가장 먼저 채굴할 약점 체크포인트 TOP 3</span>
                  </div>
                  {weakestCheckpoints.length === 0 ? (
                    <p className="text-xs text-slate-500">
                      경험을 1건 이상 채굴하면 가장 점수가 낮은 체크포인트 TOP 3를 자동으로 짚어드립니다.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {weakestCheckpoints.map((cp) => (
                        <div
                          key={cp.id}
                          className="rounded-lg border border-amber-200/80 bg-white p-2.5 flex items-center justify-between gap-2"
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5 text-xs font-bold text-slate-900">
                              <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[10px] text-amber-900">
                                {cp.id} · {cp.weight}점
                              </span>
                              <span className="truncate">{cp.label}</span>
                            </div>
                            <div className="text-[11px] text-slate-500 mt-0.5">
                              달성률 {cp.mastery_pct}% · 입증 {cp.passed_count} / 부분 {cp.partial_count} / 미충족 {cp.missed_count}
                            </div>
                          </div>
                          {onJumpToMiner && cp.suggested_project_id && (
                            <button
                              type="button"
                              onClick={() =>
                                onJumpToMiner(
                                  cp.suggested_project_id,
                                  `[${cp.id} ${cp.label}] 항목을 집중 보강하고 싶습니다.`
                                )
                              }
                              className="shrink-0 inline-flex items-center gap-1 rounded-lg bg-amber-600 px-2.5 py-1.5 text-[11px] font-semibold text-white hover:bg-amber-700"
                            >
                              <span>채굴</span>
                              <ArrowRight className="w-3 h-3" />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Collapsible 21-Checkpoint Mastery Heatmap */}
              <div className="rounded-xl border border-slate-200 bg-white">
                <button
                  type="button"
                  onClick={() => setShowHeatmap((v) => !v)}
                  className="w-full px-4 py-3 flex items-center justify-between text-xs font-bold text-slate-800 hover:bg-slate-50 rounded-xl"
                >
                  <span>21개 Atomic 체크포인트 전체 마스터리 히트맵 보기</span>
                  {showHeatmap ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
                {showHeatmap && (
                  <div className="px-4 pb-4 pt-1 border-t border-slate-100 space-y-3">
                    {STAR_AXIS_META.map((ax) => {
                      const items = heatmap.filter((c) => c.axis === ax.id);
                      return (
                        <div key={ax.id} className="space-y-1.5">
                          <div className="text-[11px] font-bold text-slate-600">
                            {ax.code} · {ax.label} ({ax.maxPoints}점)
                          </div>
                          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
                            {items.map((cp) => {
                              const bg =
                                cp.evaluated_count === 0
                                  ? "bg-slate-50 border-slate-200 text-slate-500"
                                  : cp.mastery_pct >= 75
                                    ? "bg-emerald-50 border-emerald-200 text-emerald-900"
                                    : cp.mastery_pct >= 40
                                      ? "bg-amber-50 border-amber-200 text-amber-900"
                                      : "bg-rose-50 border-rose-200 text-rose-900";
                              return (
                                <div
                                  key={cp.id}
                                  title={cp.probe_hint}
                                  className={`rounded-lg border p-2 text-[11px] ${bg}`}
                                >
                                  <div className="flex items-center justify-between font-bold">
                                    <span className="font-mono">{cp.id}</span>
                                    <span>{cp.evaluated_count > 0 ? `${cp.mastery_pct}%` : "-"}</span>
                                  </div>
                                  <div className="text-[10px] truncate mt-0.5">{cp.label}</div>
                                  <div className="text-[9px] opacity-75 mt-0.5">
                                    배점 {cp.weight} · ✅{cp.passed_count} ◐{cp.partial_count} ○{cp.missed_count}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* Rubric v2.0 Reference Modal */}
      {showRubricModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[85vh] overflow-y-auto p-6 space-y-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-bold text-indigo-700">
                  Locked Rubric {rubricRef?.rubric_version || "v2.0"}
                </div>
                <h3 className="text-lg font-bold text-slate-900">
                  STAR-L 21지표 3단계 하이브리드 평가 기준 &amp; 누적 XP 설계
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowRubricModal(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {rubricRef ? (
              <div className="space-y-4 text-xs">
                <div className="rounded-xl bg-indigo-50/60 border border-indigo-200 p-3.5 space-y-1.5">
                  <div className="font-bold text-indigo-950">학술·채용 레퍼런스 근거</div>
                  {(rubricRef.star_rubric?.frameworks || []).map((fw, idx) => (
                    <div key={idx} className="text-slate-700">
                      <strong>• {fw.name}:</strong> {fw.role}
                    </div>
                  ))}
                </div>

                <div className="rounded-xl bg-slate-50 border border-slate-200 p-3.5 space-y-1">
                  <div className="font-bold text-slate-900">산출 공식 &amp; 누적 XP 규칙</div>
                  <p className="text-slate-700">{rubricRef.star_rubric?.formula}</p>
                  <p className="text-slate-600">
                    • 경험 XP = STAR-L 점수 × 엄격 등급 배수 (S:1.0 / A:0.85 / B:0.6 / C:0.3 / D:0.1, 단일 경험 최대 100 XP)
                    <br />• 프로젝트 XP = 상위 4개 경험 체감 합산 (100% · 80% · 50% · 20%, 5번째 이후 0% → 프로젝트당 상한 250 XP)
                    <br />• 포트폴리오 XP = 대표 4개 프로젝트 합산 = 만점 1,000 XP
                  </p>
                </div>

                <div className="space-y-2">
                  <div className="font-bold text-slate-900">21개 Atomic 체크포인트 상세</div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {(rubricRef.star_rubric?.checkpoints || []).map((cp) => (
                      <div key={cp.id} className="rounded-lg border border-slate-200 p-2.5 space-y-0.5">
                        <div className="flex items-center justify-between font-bold text-slate-900">
                          <span>
                            <span className="font-mono text-indigo-700 mr-1">{cp.id}</span>
                            {cp.label}
                          </span>
                          <span className="text-slate-500">0 / {cp.weight / 2} / {cp.weight}점</span>
                        </div>
                        <div className="text-[11px] text-slate-600">2점 기준: {cp.anchor_2}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-slate-500">불러오는 중...</div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
