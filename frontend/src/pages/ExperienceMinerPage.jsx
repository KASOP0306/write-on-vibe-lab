import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FolderOpen,
  Loader2,
  RotateCcw,
  Save,
  Send,
  Sparkles,
  Star,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from "lucide-react";
import { api } from "../api/client.js";
import StarMeter from "../components/StarMeter.jsx";
import StepIndicator from "../components/StepIndicator.jsx";

const NEGATIVE_REASONS = [
  { id: "already_answered", label: "이미 답한 내용" },
  { id: "too_abstract", label: "너무 추상적" },
  { id: "role_mismatch", label: "직무·맥락 불일치" },
  { id: "too_complex", label: "질문이 길고 복잡함" },
];

const REASON_LABELS = Object.fromEntries(NEGATIVE_REASONS.map((r) => [r.id, r.label]));

const PERCEPTION_OPTIONS = [
  { value: -1, label: "너무 박함", cls: "border-rose-300 bg-rose-50 text-rose-800" },
  { value: 0, label: "적절함", cls: "border-emerald-300 bg-emerald-50 text-emerald-800" },
  { value: 1, label: "점수가 후함", cls: "border-amber-300 bg-amber-50 text-amber-800" },
];

export default function ExperienceMinerPage({
  projects,
  experiences,
  onRefresh,
  initialPrefill = null,
  onConsumeInitialPrefill = null,
}) {
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [rawNotes, setRawNotes] = useState("");
  const [threadId, setThreadId] = useState(null);
  const [replyText, setReplyText] = useState("");

  const [messages, setMessages] = useState([]);
  const [steps, setSteps] = useState([]);
  const [completenessScore, setCompletenessScore] = useState(0);
  const [initialScore, setInitialScore] = useState(0);
  const [lastUnlocked, setLastUnlocked] = useState(0);
  const [turnCount, setTurnCount] = useState(0);
  const [linkedProjectContext, setLinkedProjectContext] = useState(null);
  const [starScores, setStarScores] = useState(null);
  const [missingPoints, setMissingPoints] = useState([]);
  const [draftStar, setDraftStar] = useState(null);
  const [savedResult, setSavedResult] = useState(null);
  const [running, setRunning] = useState(false);

  // Per-question user feedback state: { [feedback_log_id]: { vote: 1|-1, reason: string, saved: bool } }
  const [qVotes, setQVotes] = useState({});

  // Post-save experience satisfaction & score perception feedback
  const [expRating, setExpRating] = useState(5);
  const [expPerception, setExpPerception] = useState(0);
  const [expComment, setExpComment] = useState("");
  const [submittingExpFb, setSubmittingExpFb] = useState(false);
  const [expFbSaved, setExpFbSaved] = useState(false);

  // Collapsible Quality & Calibration Metrics Dashboard
  const [showMetrics, setShowMetrics] = useState(false);
  const [metricsData, setMetricsData] = useState(null);
  const [loadingMetrics, setLoadingMetrics] = useState(false);

  useEffect(() => {
    if (initialPrefill) {
      if (initialPrefill.projectId) {
        setSelectedProjectId(String(initialPrefill.projectId));
      }
      if (initialPrefill.focusHint) {
        setRawNotes(initialPrefill.focusHint);
      }
      if (onConsumeInitialPrefill) {
        onConsumeInitialPrefill();
      }
    }
  }, [initialPrefill]);

  const loadMetrics = async () => {
    setLoadingMetrics(true);
    try {
      const res = await api.getExperienceMiningMetrics();
      setMetricsData(res);
    } catch (err) {
      console.warn("Failed to load experience mining metrics:", err);
    } finally {
      setLoadingMetrics(false);
    }
  };

  const handleToggleMetrics = () => {
    const next = !showMetrics;
    setShowMetrics(next);
    if (next) {
      loadMetrics();
    }
  };

  const handleEvent = (ev) => {
    if (ev.event === "node_start") {
      setSteps((prev) => [
        ...prev,
        { node: ev.node, status: "running", message: ev.message },
      ]);
    } else if (ev.event === "node_end") {
      setSteps((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (next[i].node === ev.node || next[i].status === "running") {
            next[i] = {
              ...next[i],
              node: ev.node,
              status: "done",
              badge:
                ev.data?.completeness_score !== undefined
                  ? `${ev.data.completeness_score}점`
                  : ev.data?.project_name
                    ? ev.data.project_name
                    : undefined,
            };
            break;
          }
        }
        return next;
      });
      if (ev.data?.project_name) {
        setLinkedProjectContext({
          name: ev.data.project_name,
          types: ev.data.project_types || [],
          preview: ev.data.project_context_preview || "",
        });
      }
      if (ev.data?.star) setDraftStar(ev.data.star);
      if (ev.data?.completeness_score !== undefined) {
        setCompletenessScore(ev.data.completeness_score);
      }
      if (ev.data?.initial_score !== undefined) {
        setInitialScore(ev.data.initial_score);
      }
      if (ev.data?.last_unlocked_checkpoints !== undefined) {
        setLastUnlocked(ev.data.last_unlocked_checkpoints);
      }
      if (ev.data?.star_scores?.axes) setStarScores(ev.data.star_scores);
      if (ev.data?.missing_points) setMissingPoints(ev.data.missing_points);
    } else if (ev.event === "interrupt") {
      setThreadId(ev.thread_id);
      setCompletenessScore(ev.data?.completeness_score ?? 0);
      if (ev.data?.initial_score !== undefined) setInitialScore(ev.data.initial_score);
      if (ev.data?.last_unlocked_checkpoints !== undefined) {
        setLastUnlocked(ev.data.last_unlocked_checkpoints);
      }
      if (ev.data?.turn_count !== undefined) setTurnCount(ev.data.turn_count);
      if (ev.data?.project_name) {
        setLinkedProjectContext({
          name: ev.data.project_name,
          types: ev.data.project_types || [],
          preview: ev.data.project_context_preview || "",
        });
      }
      if (ev.data?.star_scores?.axes) setStarScores(ev.data.star_scores);
      setMissingPoints(ev.data?.missing_points || []);
      if (ev.data?.star) setDraftStar(ev.data.star);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          questions: ev.data?.questions || [],
          structured_questions: ev.data?.structured_questions || [],
        },
      ]);
    } else if (ev.event === "done") {
      setSavedResult(ev.data);
      setThreadId(null);
      setCompletenessScore(ev.data?.completeness_score ?? 100);
      if (ev.data?.initial_score !== undefined) setInitialScore(ev.data.initial_score);
      if (ev.data?.turn_count !== undefined) setTurnCount(ev.data.turn_count);
      if (ev.data?.star_scores?.axes) setStarScores(ev.data.star_scores);
      setMissingPoints([]);
      if (ev.data?.star) setDraftStar(ev.data.star);
      setExpFbSaved(false);
      onRefresh();
    } else if (ev.event === "error") {
      setSteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: ev.message },
      ]);
    }
  };

  const selectedProjectObj = projects.find(
    (p) => String(p.id) === String(selectedProjectId)
  );

  const canStart = !running && (Boolean(selectedProjectId) || rawNotes.trim().length >= 5);

  const handleStart = async (e) => {
    e.preventDefault();
    if (!canStart) return;

    setRunning(true);
    setSteps([]);
    setSavedResult(null);
    setLastUnlocked(0);
    setExpFbSaved(false);
    setQVotes({});
    const userOpening = rawNotes.trim()
      ? rawNotes.trim()
      : `[프로젝트 '${selectedProjectObj?.name || ""}' 요약 기반 경험 채굴 시작]`;
    setMessages([{ role: "user", content: userOpening }]);

    try {
      await api.startInterview(
        {
          raw_notes: rawNotes.trim(),
          project_id: selectedProjectId ? Number(selectedProjectId) : null,
          force_save: false,
        },
        handleEvent
      );
    } catch (err) {
      setSteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: err.message },
      ]);
    } finally {
      setRunning(false);
    }
  };

  const handleReply = async (forceSave = false) => {
    if (!threadId || running) return;
    if (!forceSave && !replyText.trim()) return;

    setRunning(true);
    setSteps([]);
    const userMsg = replyText.trim();
    if (userMsg) {
      setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
      setReplyText("");
    }

    try {
      await api.replyInterview(
        {
          thread_id: threadId,
          user_reply: userMsg,
          project_id: selectedProjectId ? Number(selectedProjectId) : null,
          force_save: forceSave,
        },
        handleEvent
      );
    } catch (err) {
      setSteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: err.message },
      ]);
    } finally {
      setRunning(false);
    }
  };

  const handleVoteQuestion = async (logId, vote, reason = "") => {
    if (!logId) return;
    setQVotes((prev) => ({
      ...prev,
      [logId]: { vote, reason, saved: false },
    }));
    try {
      await api.submitQuestionFeedback({
        feedback_log_id: logId,
        vote,
        reason,
      });
      setQVotes((prev) => ({
        ...prev,
        [logId]: { vote, reason, saved: true },
      }));
    } catch (err) {
      console.warn("Question feedback failed:", err);
    }
  };

  const handleSubmitExperienceFeedback = async (e) => {
    e.preventDefault();
    if (!savedResult || submittingExpFb) return;
    setSubmittingExpFb(true);
    try {
      await api.submitExperienceFeedback({
        experience_id: savedResult.experience_id || null,
        project_id: savedResult.project_id ?? (selectedProjectId ? Number(selectedProjectId) : null),
        thread_id: savedResult.thread_id || "",
        satisfaction_rating: expRating,
        score_perception: expPerception,
        comment: expComment.trim(),
        initial_score: savedResult.initial_score ?? initialScore,
        final_score: savedResult.completeness_score ?? completenessScore,
        turn_count: savedResult.turn_count ?? turnCount,
      });
      setExpFbSaved(true);
      if (showMetrics) loadMetrics();
    } catch (err) {
      alert(`피드백 저장 실패: ${err.message}`);
    } finally {
      setSubmittingExpFb(false);
    }
  };

  const handleReset = () => {
    setThreadId(null);
    setRawNotes("");
    setReplyText("");
    setMessages([]);
    setSteps([]);
    setCompletenessScore(0);
    setInitialScore(0);
    setLastUnlocked(0);
    setTurnCount(0);
    setLinkedProjectContext(null);
    setStarScores(null);
    setMissingPoints([]);
    setDraftStar(null);
    setSavedResult(null);
    setQVotes({});
    setExpFbSaved(false);
    setExpComment("");
  };

  const handleDeleteExperience = async (exp) => {
    if (!window.confirm(`'${exp.title}' 경험을 삭제할까요?`)) return;
    try {
      await api.deleteExperience(exp.id);
      await onRefresh();
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const projectNameById = Object.fromEntries(projects.map((p) => [p.id, p.name]));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-1.5 text-xs font-bold text-indigo-700 mb-1">
            <Sparkles className="w-3.5 h-3.5" />
            <span>CORE ENGINE · LangGraph HITL × 21-Checkpoint Hybrid Evaluator (v2.0)</span>
          </div>
          <h2 className="text-2xl font-bold text-slate-900">3. 경험 채굴 (STAR-L Active Interviewer)</h2>
          <p className="text-sm text-slate-600 mt-1">
            프로젝트 요약이나 거친 메모에서 <strong>21개 Atomic 체크포인트</strong>를 검증하고, 미충족 고배점 항목만 핀포인트 역질문으로 채굴합니다.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleToggleMetrics}
            className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-800 hover:bg-indigo-100"
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>품질 · 캘리브레이션 지표</span>
            {showMetrics ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>

          {(threadId || savedResult) && (
            <button
              type="button"
              onClick={handleReset}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>새 경험 채굴</span>
            </button>
          )}
        </div>
      </div>

      {/* Collapsible Live Quality · Calibration · Item Analysis Dashboard */}
      {showMetrics && (
        <section className="rounded-2xl border border-indigo-200 bg-white p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-indigo-600" />
              <h3 className="text-sm font-bold text-slate-900">
                경험 채굴 실시간 품질 · 점수축 캘리브레이션 &amp; 21지표 문항 분석 ({metricsData?.rubric_version || "v2.0"})
              </h3>
            </div>
            <button
              type="button"
              onClick={loadMetrics}
              disabled={loadingMetrics}
              className="text-xs font-semibold text-indigo-700 hover:underline"
            >
              {loadingMetrics ? "새로고침 중..." : "새로고침"}
            </button>
          </div>

          {loadingMetrics && !metricsData ? (
            <div className="py-6 flex items-center justify-center gap-2 text-xs text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>지표 집계 중...</span>
            </div>
          ) : metricsData ? (
            <div className="space-y-4">
              {/* Top 4 KPI Cards */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                  <div className="text-[11px] font-semibold text-slate-500">역질문 👍 만족률</div>
                  <div className="text-lg font-extrabold text-indigo-700 mt-0.5">
                    {metricsData.question_quality?.thumbs_up_rate !== null
                      ? `${metricsData.question_quality.thumbs_up_rate}%`
                      : "집계 전"}
                  </div>
                  <div className="text-[10px] text-slate-500">
                    투표 {metricsData.question_quality?.voted_count || 0}건 / 총 질문 {metricsData.question_quality?.total_questions || 0}건
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                  <div className="text-[11px] font-semibold text-slate-500">턴당 평균 ΔSTAR-L · 해금</div>
                  <div className="text-lg font-extrabold text-emerald-700 mt-0.5">
                    +{metricsData.question_quality?.avg_delta_score ?? 0}점
                  </div>
                  <div className="text-[10px] text-slate-500">
                    턴당 평균 +{metricsData.question_quality?.avg_unlocked_checkpoints ?? 0}개 체크포인트 해금
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                  <div className="text-[11px] font-semibold text-slate-500">완료 경험 만족도 · 상승폭</div>
                  <div className="text-lg font-extrabold text-amber-600 mt-0.5">
                    {metricsData.experience_growth?.avg_satisfaction !== null
                      ? `★ ${metricsData.experience_growth.avg_satisfaction} / 5.0`
                      : "집계 전"}
                  </div>
                  <div className="text-[10px] text-slate-500">
                    초안 {metricsData.experience_growth?.avg_initial_score || 0} → 최종 {metricsData.experience_growth?.avg_final_score || 0} (+{metricsData.experience_growth?.avg_score_gain || 0}점)
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                  <div className="text-[11px] font-semibold text-slate-500">점수 체감 캘리브레이션</div>
                  <div className="text-xs font-bold text-slate-800 mt-1 flex flex-wrap gap-1.5">
                    <span className="text-rose-700">박함 {metricsData.rubric_calibration?.perception_rates?.harsh ?? 0}%</span>
                    <span>·</span>
                    <span className="text-emerald-700">적절 {metricsData.rubric_calibration?.perception_rates?.fair ?? 0}%</span>
                    <span>·</span>
                    <span className="text-amber-700">후함 {metricsData.rubric_calibration?.perception_rates?.lenient ?? 0}%</span>
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5">
                    완료 피드백 {metricsData.experience_growth?.total_feedback_count || 0}건 기준
                  </div>
                </div>
              </div>

              {/* Negative Reasons & Hard Cap Triggers */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div className="rounded-xl border border-slate-200 p-3 space-y-1.5">
                  <div className="font-bold text-slate-800">최다 👎 역질문 지적 사유 (프롬프트 자동 반영)</div>
                  {(metricsData.question_quality?.top_negative_reasons || []).length === 0 ? (
                    <div className="text-[11px] text-slate-400">아직 👎 피드백이 없습니다.</div>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {metricsData.question_quality.top_negative_reasons.map((item) => (
                        <span
                          key={item.reason}
                          className="rounded-full bg-rose-50 border border-rose-200 px-2.5 py-0.5 text-[11px] font-semibold text-rose-800"
                        >
                          {REASON_LABELS[item.reason] || item.reason}: {item.count}회
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-xl border border-slate-200 p-3 space-y-1.5">
                  <div className="font-bold text-slate-800">Python 코드 하드 캡 발동 빈도 (관대화 차단)</div>
                  {(metricsData.rubric_calibration?.hard_cap_triggers || []).length === 0 ? (
                    <div className="text-[11px] text-slate-400">아직 발동 기록이 없습니다.</div>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {metricsData.rubric_calibration.hard_cap_triggers.map((item) => (
                        <span
                          key={item.reason}
                          className="rounded-full bg-amber-50 border border-amber-200 px-2.5 py-0.5 text-[11px] font-mono text-amber-900"
                        >
                          {item.reason} ({item.count})
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* 21-Checkpoint Item Analysis (for rubric_v2.0 -> v2.1 evolution) */}
              <div className="space-y-1.5">
                <div className="text-xs font-bold text-slate-800">
                  21개 체크포인트 문항 분석 (통과율 &amp; 버전 업그레이드 진단)
                </div>
                <div className="grid grid-cols-3 sm:grid-cols-7 gap-1.5">
                  {(metricsData.rubric_calibration?.item_analysis || []).map((cp) => {
                    const badgeCls =
                      cp.health === "high_friction"
                        ? "border-rose-300 bg-rose-50 text-rose-900"
                        : cp.health === "too_hard"
                          ? "border-orange-300 bg-orange-50 text-orange-900"
                          : cp.health === "too_easy"
                            ? "border-sky-300 bg-sky-50 text-sky-900"
                            : "border-slate-200 bg-slate-50 text-slate-800";
                    return (
                      <div
                        key={cp.id}
                        title={`${cp.id} ${cp.label} (표본 ${cp.sample_count}건 | 입증 ${cp.pass_rate}% | 👎 ${cp.negative_vote_rate}%)`}
                        className={`rounded-lg border px-2 py-1.5 text-[10px] ${badgeCls}`}
                      >
                        <div className="flex items-center justify-between font-bold">
                          <span className="font-mono">{cp.id}</span>
                          <span>{cp.sample_count > 0 ? `${cp.pass_rate}%` : "-"}</span>
                        </div>
                        <div className="truncate opacity-80">{cp.label}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : null}
        </section>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Input & Interview Chat */}
        <div className="lg:col-span-2 space-y-4">
          {/* Linked Project Summary Context Banner (active during session) */}
          {linkedProjectContext && (
            <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 px-4 py-3 text-xs space-y-1">
              <div className="flex items-center gap-1.5 font-bold text-indigo-950">
                <FolderOpen className="w-4 h-4 text-indigo-600" />
                <span>연결된 프로젝트 요약 자동 로드됨: {linkedProjectContext.name}</span>
              </div>
              {linkedProjectContext.preview && (
                <p className="text-[11px] text-slate-600 line-clamp-2 whitespace-pre-wrap">
                  {linkedProjectContext.preview}
                </p>
              )}
            </div>
          )}

          {!threadId && !savedResult && (
            <form
              onSubmit={handleStart}
              className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm"
            >
              <label className="block space-y-1.5">
                <span className="text-xs font-semibold text-slate-700">
                  연결할 프로젝트 (선택 시 프로젝트 요약·섹션·직무 트랙 자동 연동)
                </span>
                <select
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white"
                >
                  <option value="">프로젝트 미지정 (독립 경험 메모로 채굴)</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} {p.period ? `(${p.period})` : ""}
                    </option>
                  ))}
                </select>
              </label>

              {selectedProjectObj && (
                <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-3 text-xs space-y-1">
                  <div className="font-bold text-indigo-950">
                    선택된 프로젝트 요약 미리보기 · {selectedProjectObj.name}
                  </div>
                  <p className="text-slate-600 line-clamp-2">
                    {selectedProjectObj.summary || "요약 없음 — 작성된 프로젝트 섹션 내용을 자동으로 불러와 분석합니다."}
                  </p>
                  <div className="text-[11px] text-indigo-700">
                    메모 없이 바로 <strong>[경험 채굴 시작]</strong>을 눌러도 프로젝트 요약 전체에서 빈틈 체크포인트를 찾아 역질문을 시작합니다!
                  </div>
                </div>
              )}

              <label className="block space-y-1.5">
                <span className="text-xs font-semibold text-slate-700">
                  {selectedProjectObj
                    ? "집중 채굴할 에피소드 / 추가 메모 (선택)"
                    : "경험 메모 입력 (필수)"}
                </span>
                <textarea
                  rows={5}
                  required={!selectedProjectObj}
                  value={rawNotes}
                  onChange={(e) => setRawNotes(e.target.value)}
                  placeholder={
                    selectedProjectObj
                      ? "비워두면 프로젝트 요약 전체에서 핵심 경험을 채굴합니다. 특정 트러블슈팅·의사결정·성과 에피소드만 파고들고 싶다면 2~3줄로 적어주세요."
                      : "예: FastAPI 서버 응답이 느려서 인덱스를 걸고 비동기로 바꿨더니 빨라졌다. 정확한 수치나 어떤 쿼리가 문제였는지는 대충 기억남..."
                  }
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/15"
                />
              </label>

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={!canStart}
                  className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  <Sparkles className="w-4 h-4" />
                  <span>
                    {running
                      ? "21지표 하이브리드 분석 중..."
                      : selectedProjectObj
                        ? "프로젝트 요약으로 경험 채굴 시작"
                        : "경험 채굴 시작"}
                  </span>
                </button>
              </div>
            </form>
          )}

          {/* Conversation History */}
          {messages.length > 0 && (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  역질문 인터뷰 진행 내역 {threadId && `(세션: ${threadId})`}
                </div>
                {lastUnlocked > 0 && (
                  <span className="rounded-full bg-emerald-100 border border-emerald-200 px-2.5 py-0.5 text-[11px] font-bold text-emerald-800">
                    🎉 직전 답변으로 +{lastUnlocked}개 체크포인트 해금!
                  </span>
                )}
              </div>

              <div className="space-y-3 max-h-[460px] overflow-y-auto pr-1">
                {messages.map((msg, idx) =>
                  msg.role === "user" ? (
                    <div key={idx} className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl bg-slate-900 text-white px-4 py-2.5 text-sm whitespace-pre-wrap">
                        {msg.content}
                      </div>
                    </div>
                  ) : (
                    <div key={idx} className="flex justify-start">
                      <div className="max-w-[94%] rounded-2xl bg-indigo-50/70 border border-indigo-200 px-4 py-3 space-y-2.5">
                        <div className="text-xs font-bold text-indigo-950">
                          AI 인터뷰어 핀포인트 역질문 (0점 고배점 체크포인트 공략)
                        </div>
                        {(msg.structured_questions || []).length > 0 ? (
                          <div className="space-y-2.5">
                            {msg.structured_questions.map((sq, qIdx) => {
                              const logId = sq.feedback_log_id;
                              const voteEntry = logId ? qVotes[logId] : null;
                              return (
                                <div
                                  key={qIdx}
                                  className="rounded-xl bg-white border border-indigo-100 p-3 space-y-1.5"
                                >
                                  <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
                                    {sq.target_checkpoint_id && (
                                      <span className="rounded-full bg-amber-100 px-2 py-0.5 font-mono font-bold text-amber-900">
                                        {sq.target_checkpoint_id} {sq.target_checkpoint_label}
                                        {sq.target_checkpoint_weight ? ` (${sq.target_checkpoint_weight}점)` : ""}
                                      </span>
                                    )}
                                    <span className="rounded-full bg-indigo-100 px-2 py-0.5 font-bold text-indigo-800">
                                      {sq.technique_label || sq.technique}
                                    </span>
                                  </div>
                                  <div className="text-sm font-semibold text-slate-900">
                                    Q{qIdx + 1}. {sq.question}
                                  </div>
                                  {sq.interviewer_intent && (
                                    <div className="text-[11px] text-slate-500">
                                      면접관 검증 의도: {sq.interviewer_intent}
                                    </div>
                                  )}

                                  {/* Per-question 👍/👎 Feedback Loop */}
                                  {logId && (
                                    <div className="pt-1.5 border-t border-slate-100 space-y-1.5">
                                      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                                        <span className="text-slate-400">
                                          이 질문이 경험을 구체화하는 데 도움이 되었나요?
                                        </span>
                                        <div className="flex items-center gap-1.5">
                                          <button
                                            type="button"
                                            onClick={() => handleVoteQuestion(logId, 1, "")}
                                            className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold transition ${
                                              voteEntry?.vote === 1
                                                ? "border-emerald-400 bg-emerald-50 text-emerald-800"
                                                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                                            }`}
                                          >
                                            <ThumbsUp className="w-3 h-3" />
                                            <span>도움됨</span>
                                          </button>
                                          <button
                                            type="button"
                                            onClick={() =>
                                              handleVoteQuestion(logId, -1, voteEntry?.reason || "")
                                            }
                                            className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold transition ${
                                              voteEntry?.vote === -1
                                                ? "border-rose-400 bg-rose-50 text-rose-800"
                                                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                                            }`}
                                          >
                                            <ThumbsDown className="w-3 h-3" />
                                            <span>아쉬움</span>
                                          </button>
                                        </div>
                                      </div>

                                      {voteEntry?.vote === -1 && (
                                        <div className="flex flex-wrap items-center gap-1.5">
                                          <span className="text-[10px] text-rose-700 font-semibold">
                                            이유 선택:
                                          </span>
                                          {NEGATIVE_REASONS.map((r) => (
                                            <button
                                              key={r.id}
                                              type="button"
                                              onClick={() => handleVoteQuestion(logId, -1, r.id)}
                                              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                                                voteEntry.reason === r.id
                                                  ? "border-rose-500 bg-rose-600 text-white"
                                                  : "border-rose-200 bg-rose-50/70 text-rose-800 hover:bg-rose-100"
                                              }`}
                                            >
                                              {r.label}
                                            </button>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        ) : (
                          <ul className="list-disc pl-4 space-y-1 text-sm text-slate-800">
                            {(msg.questions || []).map((q, qIdx) => (
                              <li key={qIdx}>{q}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  )
                )}
              </div>

              {threadId && (
                <div className="pt-3 border-t border-slate-100 space-y-2.5">
                  <textarea
                    rows={3}
                    value={replyText}
                    onChange={(e) => setReplyText(e.target.value)}
                    placeholder="역질문에 대한 답변을 입력하세요. (기억나는 수치, 전후 비교, 포기한 대안, 본인 기여 등)"
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/15"
                  />
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <button
                      type="button"
                      disabled={running}
                      onClick={() => handleReply(true)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300 bg-emerald-50 px-3.5 py-2 text-xs font-semibold text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
                    >
                      <Save className="w-3.5 h-3.5" />
                      <span>이 상태로 저장하기</span>
                    </button>

                    <button
                      type="button"
                      disabled={running || !replyText.trim()}
                      onClick={() => handleReply(false)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                    >
                      <Send className="w-3.5 h-3.5" />
                      <span>{running ? "21지표 재채점 중..." : "답변 보내기"}</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Completion Summary + Experience Satisfaction & Calibration Feedback */}
              {savedResult && (
                <div className="space-y-3">
                  <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-4 flex flex-wrap items-center justify-between gap-2 text-sm text-emerald-900">
                    <div className="flex items-center gap-2.5">
                      <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                      <div>
                        <strong>경험 #{savedResult.experience_id} 저장 완료!</strong>{" "}
                        <span className="text-xs">
                          (초안 {savedResult.initial_score ?? initialScore}점 → 최종{" "}
                          <strong>{savedResult.completeness_score}점</strong>
                          {savedResult.star_scores?.xp ? ` · +${savedResult.star_scores.xp} XP` : ""} · 벡터 동기화:{" "}
                          {savedResult.vector_synced ? "완료" : "대기"})
                        </span>
                      </div>
                    </div>
                  </div>

                  {expFbSaved ? (
                    <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 px-4 py-3 text-xs font-semibold text-indigo-900">
                      ✅ 경험 만족도 및 점수 체감 피드백이 캘리브레이션 로그에 기록되었습니다!
                    </div>
                  ) : (
                    <form
                      onSubmit={handleSubmitExperienceFeedback}
                      className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 space-y-3 text-xs"
                    >
                      <div className="font-bold text-slate-900">
                        완성된 경험과 점수 평가가 어떠셨나요? (피드백 루프 반영)
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="space-y-1">
                          <div className="text-[11px] font-semibold text-slate-600">
                            1. 완성된 경험 만족도
                          </div>
                          <div className="flex items-center gap-1">
                            {[1, 2, 3, 4, 5].map((starVal) => (
                              <button
                                key={starVal}
                                type="button"
                                onClick={() => setExpRating(starVal)}
                                className={`p-1 rounded transition ${
                                  starVal <= expRating
                                    ? "text-amber-500"
                                    : "text-slate-300 hover:text-amber-300"
                                }`}
                              >
                                <Star className="w-5 h-5 fill-current" />
                              </button>
                            ))}
                            <span className="ml-1 font-bold text-slate-700">{expRating} / 5</span>
                          </div>
                        </div>

                        <div className="space-y-1">
                          <div className="text-[11px] font-semibold text-slate-600">
                            2. 산출된 점수({savedResult.completeness_score}점) 체감
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {PERCEPTION_OPTIONS.map((opt) => (
                              <button
                                key={opt.value}
                                type="button"
                                onClick={() => setExpPerception(opt.value)}
                                className={`rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition ${
                                  expPerception === opt.value
                                    ? `${opt.cls} ring-2 ring-slate-900/15`
                                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                                }`}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          type="text"
                          value={expComment}
                          onChange={(e) => setExpComment(e.target.value)}
                          placeholder="점수 기준이나 역질문에 대해 남길 한 줄 의견 (선택)"
                          className="flex-1 min-w-[200px] rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                        />
                        <button
                          type="submit"
                          disabled={submittingExpFb}
                          className="rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {submittingExpFb ? "저장 중..." : "피드백 기록"}
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: 21-Checkpoint StarMeter + Live STAR Preview + Steps */}
        <div className="space-y-4">
          <StarMeter
            score={completenessScore}
            missingPoints={missingPoints}
            starScores={starScores}
            defaultShowCheckpoints={true}
          />
          <StepIndicator steps={steps} />

          {draftStar && (
            <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-2 text-xs">
              <div className="font-bold text-slate-900 text-sm">
                {draftStar.title || "추출 중인 STAR 초안"}
              </div>
              <p>
                <strong className="text-slate-700">S:</strong> {draftStar.situation}
              </p>
              <p>
                <strong className="text-slate-700">T:</strong> {draftStar.task}
              </p>
              <p>
                <strong className="text-slate-700">A:</strong> {draftStar.action}
              </p>
              <p>
                <strong className="text-slate-700">R:</strong> {draftStar.result}
              </p>
              {draftStar.learning && (
                <p>
                  <strong className="text-indigo-700">L (배운 점):</strong> {draftStar.learning}
                </p>
              )}
              {draftStar.quantified_metrics && (
                <p className="rounded-md bg-emerald-50 px-2 py-1 text-emerald-800">
                  <strong>정량 지표:</strong> {draftStar.quantified_metrics}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Saved Experiences Archive */}
      <div className="space-y-3 pt-4 border-t border-slate-200">
        <h3 className="text-base font-bold text-slate-900">
          저장된 STAR-L 경험 아카이브 ({experiences.length})
        </h3>
        {experiences.length === 0 ? (
          <p className="text-sm text-slate-500">아직 저장된 경험이 없습니다.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {experiences.map((exp) => (
              <div
                key={exp.id}
                className="rounded-xl border border-slate-200 bg-white p-4 space-y-2.5 shadow-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-bold text-slate-900">{exp.title}</h4>
                    <div className="flex flex-wrap items-center gap-2 mt-0.5 text-[11px] text-slate-500">
                      <span>
                        {exp.project_id
                          ? projectNameById[exp.project_id] || `프로젝트 #${exp.project_id}`
                          : "프로젝트 미지정"}
                      </span>
                      <span>·</span>
                      <span className="font-semibold text-emerald-700">
                        {exp.completeness_score}점
                      </span>
                      {exp.star_scores?.grade && (
                        <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-bold text-indigo-700">
                          {exp.star_scores.grade}등급
                        </span>
                      )}
                      {exp.star_scores?.xp > 0 && (
                        <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-bold text-violet-700">
                          +{exp.star_scores.xp} XP
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteExperience(exp)}
                    className="p-1 rounded text-slate-400 hover:text-red-600"
                    title="경험 삭제"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
                <p className="text-xs text-slate-700 line-clamp-2">
                  <strong>Action:</strong> {exp.action}
                </p>
                <p className="text-xs text-slate-700 line-clamp-2">
                  <strong>Result:</strong> {exp.result}
                </p>
                {exp.learning && (
                  <p className="text-xs text-indigo-800 line-clamp-2">
                    <strong>Learning:</strong> {exp.learning}
                  </p>
                )}
                {exp.quantified_metrics && (
                  <div className="text-[11px] text-emerald-800 bg-emerald-50 rounded-md px-2 py-1">
                    지표: {exp.quantified_metrics}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
