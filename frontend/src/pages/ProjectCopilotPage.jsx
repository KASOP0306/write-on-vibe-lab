import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Compass,
  ExternalLink,
  Globe,
  Loader2,
  MessageSquare,
  PlusCircle,
  Rocket,
  Send,
  Sparkles,
  Target,
} from "lucide-react";
import { api } from "../api/client.js";
import StepIndicator from "../components/StepIndicator.jsx";
import { TRACK_SHORT_LABELS, getTrackBadgeClass } from "../utils/projectTracks.js";

const QUICK_PROMPTS = [
  "내 포트폴리오 캐릭터 약점을 정면으로 보완할 3주 MVP 프로젝트 아키텍처와 실행 단계를 짜줘",
  "리서치해둔 목표 기업 동향에 맞춰 차별화할 수 있는 새 프로젝트 핵심 기능과 검증 지표를 설계해줘",
  "최신 오픈소스/실무 레퍼런스를 웹 검색해서 새 프로젝트에 쓸 최적의 기술 스택과 트레이드오프를 비교해줘",
  "협업·일정 관리(외적 역량)까지 포트폴리오 증거로 남길 수 있는 프로젝트 진행 방식과 산출물 체크리스트를 알려줘",
];

export default function ProjectCopilotPage({
  projects = [],
  initialTopic = "",
  onConsumeInitialTopic,
  onProjectCreated,
}) {
  const [modeTab, setModeTab] = useState("blueprint"); // "blueprint" | "chat"
  const [diagnosisData, setDiagnosisData] = useState(null);
  const [companies, setCompanies] = useState([]);

  // Shared Planning Context
  const [selectedCompanyId, setSelectedCompanyId] = useState("");
  const [focusWeakness, setFocusWeakness] = useState("");
  const [topicHint, setTopicHint] = useState("");
  const [useWebSearch, setUseWebSearch] = useState(true);

  // Blueprint Proposer State
  const [proposing, setProposing] = useState(false);
  const [blueprintResult, setBlueprintResult] = useState(null);
  const [blueprintError, setBlueprintError] = useState("");
  const [creatingIdx, setCreatingIdx] = useState(null);

  // New-Project Chat State
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [chatSteps, setChatSteps] = useState([]);
  const [chatRunning, setChatRunning] = useState(false);

  useEffect(() => {
    const loadContext = async () => {
      try {
        const [diag, comps] = await Promise.all([
          api.getPortfolioDiagnosis().catch(() => null),
          api.listCompanies().catch(() => []),
        ]);
        setDiagnosisData(diag);
        setCompanies(comps || []);
      } catch (err) {
        console.warn(err);
      }
    };
    loadContext();
  }, []);

  useEffect(() => {
    if (initialTopic) {
      setTopicHint(initialTopic);
      setChatInput(
        `지원 회고에서 나온 이 보완 과제를 해결하는 새 프로젝트를 기획해 줘: ${initialTopic}`
      );
      onConsumeInitialTopic?.();
    }
  }, [initialTopic]);

  const diag = diagnosisData?.diagnosis?.character_archetype
    ? diagnosisData.diagnosis
    : null;
  const weaknesses = diag?.weaknesses || [];

  const handleProposeBlueprints = async (e) => {
    e?.preventDefault();
    if (proposing) return;
    setProposing(true);
    setBlueprintError("");
    try {
      const res = await api.proposeNewProjects({
        company_profile_id: selectedCompanyId ? Number(selectedCompanyId) : null,
        focus_weakness: focusWeakness.trim(),
        topic_hint: topicHint.trim(),
        use_web_search: useWebSearch,
      });
      setBlueprintResult(res);
    } catch (err) {
      setBlueprintError(err.message);
    } finally {
      setProposing(false);
    }
  };

  const handleCreateDraftProject = async (bp, idx) => {
    if (creatingIdx !== null) return;
    setCreatingIdx(idx);
    try {
      const summaryText = `${bp.tagline}\n\n[보완 목표] ${(bp.target_weaknesses || []).join(", ")}\n[기업 연결] ${bp.company_alignment}`;
      const created = await api.createProject({
        name: bp.name,
        project_types: bp.project_types || ["engineering"],
        period: "기획 중 (신규)",
        role: "기획 · 주도",
        summary: summaryText,
        tech_stack: bp.recommended_stack_and_tools || [],
        portfolio_goal_link: bp.company_alignment || "",
      });

      // Seed the overview section with roadmap & evidence plan
      const detail = await api.getProject(created.id);
      const overviewSec = (detail.sections || []).find(
        (s) => s.section_type === "overview"
      );
      if (overviewSec) {
        const roadmapMd = (bp.execution_roadmap || [])
          .map((r, i) => `${i + 1}. ${r}`)
          .join("\n");
        const evidenceMd = (bp.evidence_plan || [])
          .map((ev) => `- ${ev}`)
          .join("\n");
        await api.updateSection(created.id, overviewSec.id, {
          content:
            `### 문제 정의 & 솔루션\n${bp.problem_and_solution}\n\n` +
            `### 보완 대상 캐릭터 약점\n${(bp.target_weaknesses || []).map((w) => `- ${w}`).join("\n")}\n\n` +
            `### 실행 로드맵\n${roadmapMd}\n\n` +
            `### 반드시 남길 객관적 증거 계획\n${evidenceMd}`,
        });
      }

      alert(`'${bp.name}' 프로젝트 초안이 포트폴리오에 생성되었습니다!`);
      onProjectCreated?.();
    } catch (err) {
      alert(`프로젝트 생성 실패: ${err.message}`);
    } finally {
      setCreatingIdx(null);
    }
  };

  const handleSendChat = async (e, overrideText = null) => {
    e?.preventDefault();
    const userMsg = (overrideText ?? chatInput).trim();
    if (!userMsg || chatRunning) return;

    const historyPayload = chatMessages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    setChatMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    if (overrideText === null) setChatInput("");
    setChatRunning(true);
    setChatSteps([]);

    try {
      await api.copilotChat(
        {
          message: userMsg,
          project_id: selectedProjectId ? Number(selectedProjectId) : null,
          company_profile_id: selectedCompanyId ? Number(selectedCompanyId) : null,
          focus_weakness: focusWeakness.trim(),
          chat_history: historyPayload,
        },
        (ev) => {
          if (ev.event === "node_start") {
            setChatSteps((prev) => [
              ...prev,
              { node: ev.node, status: "running", message: ev.message },
            ]);
          } else if (ev.event === "node_end") {
            setChatSteps((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i -= 1) {
                if (next[i].node === ev.node || next[i].status === "running") {
                  next[i] = {
                    ...next[i],
                    node: ev.node,
                    status: "done",
                    badge:
                      ev.node === "web_search_fallback"
                        ? `웹 ${ev.data?.web_source_count || 0}건`
                        : undefined,
                  };
                  break;
                }
              }
              return next;
            });
          } else if (ev.event === "done") {
            setChatMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                content: ev.data?.answer || "",
                used_web_fallback: ev.data?.used_web_fallback,
                web_sources: ev.data?.web_sources || [],
              },
            ]);
          } else if (ev.event === "error") {
            setChatSteps((prev) => [
              ...prev,
              { node: "error", status: "error", message: ev.message },
            ]);
          }
        }
      );
    } catch (err) {
      setChatSteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: err.message },
      ]);
    } finally {
      setChatRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <Rocket className="w-6 h-6 text-indigo-600" />
          <span>6. 새 프로젝트 코파일럿</span>
        </h2>
        <p className="text-sm text-slate-600 mt-1">
          <strong>나의 포트폴리오 캐릭터 약점</strong>, <strong>리서치해둔 목표 기업 동향</strong>, 그리고{" "}
          <strong>실시간 웹 검색</strong>을 결합해 어떤 새 프로젝트를 어떻게 진행하면 가장 강력하게 보완할 수 있는지 설계합니다.
        </p>
      </div>

      {/* Shared Context Bar: Portfolio Character Weaknesses + Researched Company */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Compass className="w-4 h-4 text-indigo-600" />
            <span className="text-sm font-bold text-slate-900">
              {diag
                ? `연동된 캐릭터: ${diag.character_archetype} (종합 ${diag.overall_score}점 · 내적 ${diag.internal_score} / 외적 ${diag.external_score})`
                : "포트폴리오 캐릭터 진단 미실행 (2번 탭에서 진단하면 약점이 자동 연동됩니다)"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Building2 className="w-4 h-4 text-slate-400" />
            <select
              value={selectedCompanyId}
              onChange={(e) => setSelectedCompanyId(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs bg-white font-medium text-slate-700"
            >
              <option value="">목표 기업: 전체 리서치 참고 ({companies.length}곳)</option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>
                  목표 기업: {c.company_name} {c.target_role ? `(${c.target_role})` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Clickable Weakness Focus Chips */}
        {weaknesses.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[11px] font-semibold text-rose-700 flex items-center gap-1">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>보완에 집중할 캐릭터 약점 선택 (클릭해 포커스 지정):</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setFocusWeakness("")}
                className={`rounded-full px-3 py-1 text-xs font-semibold border ${
                  !focusWeakness
                    ? "bg-slate-900 text-white border-slate-900"
                    : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                }`}
              >
                약점 전체 종합
              </button>
              {weaknesses.map((w, i) => {
                const active = focusWeakness === w.title;
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setFocusWeakness(active ? "" : w.title)}
                    className={`rounded-full px-3 py-1 text-xs font-semibold border ${
                      active
                        ? "bg-rose-600 text-white border-rose-600"
                        : "bg-rose-50 text-rose-800 border-rose-200 hover:bg-rose-100"
                    }`}
                  >
                    {w.title}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Mode Switch Tabs */}
      <div className="inline-flex rounded-xl border border-slate-200 bg-white p-1 shadow-xs">
        <button
          type="button"
          onClick={() => setModeTab("blueprint")}
          className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-bold transition-colors ${
            modeTab === "blueprint"
              ? "bg-indigo-600 text-white"
              : "text-slate-600 hover:bg-slate-50"
          }`}
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span>새 프로젝트 청사진 추천 (웹 검색 포함)</span>
        </button>
        <button
          type="button"
          onClick={() => setModeTab("chat")}
          className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-bold transition-colors ${
            modeTab === "chat"
              ? "bg-indigo-600 text-white"
              : "text-slate-600 hover:bg-slate-50"
          }`}
        >
          <MessageSquare className="w-3.5 h-3.5" />
          <span>새 프로젝트 설계 · 진행 코파일럿 채팅</span>
        </button>
      </div>

      {/* TAB 1: New Project Blueprint Recommender */}
      {modeTab === "blueprint" ? (
        <div className="space-y-5">
          <form
            onSubmit={handleProposeBlueprints}
            className="rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <label className="md:col-span-2 block space-y-1">
                <span className="text-xs font-semibold text-slate-700">
                  구상 중인 도메인·주제 힌트 (선택 — 비워두면 캐릭터 약점 &amp; 기업 리서치 기반으로 자동 추천)
                </span>
                <input
                  type="text"
                  value={topicHint}
                  onChange={(e) => setTopicHint(e.target.value)}
                  placeholder="예: 실시간 로그 모니터링, B2B 온보딩 퍼널 실험, 멀티에이전트 협업 도구..."
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                />
              </label>

              <div className="flex flex-col justify-end space-y-2">
                <label className="flex items-center gap-2 text-xs text-slate-700">
                  <input
                    type="checkbox"
                    checked={useWebSearch}
                    onChange={(e) => setUseWebSearch(e.target.checked)}
                    className="accent-indigo-600"
                  />
                  <Globe className="w-3.5 h-3.5 text-indigo-600" />
                  <span>최신 사례·오픈소스 웹 검색 반영</span>
                </label>
                <button
                  type="submit"
                  disabled={proposing}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-xs font-bold text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  {proposing ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Rocket className="w-4 h-4" />
                  )}
                  <span>
                    {proposing
                      ? "웹 검색 & 청사진 설계 중..."
                      : "보완형 새 프로젝트 청사진 추천"}
                  </span>
                </button>
              </div>
            </div>

            {blueprintError && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {blueprintError}
              </div>
            )}
          </form>

          {blueprintResult && (
            <div className="space-y-5">
              {blueprintResult.character_focus_summary && (
                <div className="rounded-2xl bg-indigo-50/70 border border-indigo-200 p-4 text-xs text-indigo-950 leading-relaxed">
                  <strong>전략 요약:</strong> {blueprintResult.character_focus_summary}
                </div>
              )}

              <div className="grid grid-cols-1 gap-5">
                {(blueprintResult.blueprints || []).map((bp, idx) => (
                  <div
                    key={idx}
                    className="rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded-full bg-slate-900 px-2.5 py-0.5 text-[11px] font-bold text-white">
                            청사진 #{idx + 1}
                          </span>
                          <h3 className="text-lg font-bold text-slate-900">
                            {bp.name}
                          </h3>
                          {(bp.project_types || []).map((t) => (
                            <span
                              key={t}
                              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${getTrackBadgeClass(t)}`}
                            >
                              {TRACK_SHORT_LABELS[t] || t}
                            </span>
                          ))}
                        </div>
                        <p className="text-xs font-medium text-indigo-700">
                          {bp.tagline}
                        </p>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setModeTab("chat");
                            setChatInput(
                              `'${bp.name}' 청사진을 실제로 시작하려고 해. 첫 1주차에 바로 실행할 구체적인 설계·일정·검증 계획을 더 자세히 짜줘.`
                            );
                          }}
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                        >
                          <MessageSquare className="w-3.5 h-3.5" />
                          <span>코파일럿과 심화 논의</span>
                        </button>
                        <button
                          type="button"
                          disabled={creatingIdx !== null}
                          onClick={() => handleCreateDraftProject(bp, idx)}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {creatingIdx === idx ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <PlusCircle className="w-3.5 h-3.5" />
                          )}
                          <span>포트폴리오 초안으로 바로 생성</span>
                        </button>
                      </div>
                    </div>

                    <p className="text-xs text-slate-700 leading-relaxed bg-slate-50 rounded-xl p-3.5">
                      {bp.problem_and_solution}
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                      <div className="rounded-xl border border-rose-200 bg-rose-50/40 p-3.5 space-y-1.5">
                        <div className="font-bold text-rose-900 flex items-center gap-1">
                          <Target className="w-3.5 h-3.5" />
                          <span>정면 보완하는 캐릭터 약점</span>
                        </div>
                        <ul className="space-y-1 text-rose-900">
                          {(bp.target_weaknesses || []).map((w, i) => (
                            <li key={i}>• {w}</li>
                          ))}
                        </ul>
                      </div>

                      <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-3.5 space-y-1.5">
                        <div className="font-bold text-indigo-950 flex items-center gap-1">
                          <Building2 className="w-3.5 h-3.5" />
                          <span>리서치 기업 연결 포인트</span>
                        </div>
                        <p className="text-slate-700 leading-relaxed">
                          {bp.company_alignment}
                        </p>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                      <div className="rounded-xl border border-slate-200 p-3.5 space-y-1.5">
                        <div className="font-bold text-slate-900">단계별 실행 로드맵</div>
                        <ol className="space-y-1 text-slate-700 list-decimal list-inside">
                          {(bp.execution_roadmap || []).map((step, i) => (
                            <li key={i}>{step}</li>
                          ))}
                        </ol>
                      </div>

                      <div className="rounded-xl border border-emerald-200 bg-emerald-50/30 p-3.5 space-y-1.5">
                        <div className="font-bold text-emerald-950 flex items-center gap-1">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                          <span>반드시 남길 정량·운영 증거 계획</span>
                        </div>
                        <ul className="space-y-1 text-emerald-900">
                          {(bp.evidence_plan || []).map((ev, i) => (
                            <li key={i}>• {ev}</li>
                          ))}
                        </ul>
                      </div>
                    </div>

                    {(bp.recommended_stack_and_tools || []).length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {bp.recommended_stack_and_tools.map((tech, i) => (
                          <span
                            key={i}
                            className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700"
                          >
                            {tech}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Web References */}
              {(blueprintResult.web_references || []).length > 0 && (
                <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-2.5">
                  <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                    <Globe className="w-4 h-4 text-indigo-600" />
                    <span>실시간 웹 검색으로 참고한 최신 레퍼런스 ({blueprintResult.web_references.length})</span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 text-xs">
                    {blueprintResult.web_references.map((ref, i) => (
                      <a
                        key={i}
                        href={ref.url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-xl border border-slate-200 p-3 hover:border-indigo-300 hover:bg-indigo-50/30 transition-colors space-y-1"
                      >
                        <div className="font-semibold text-indigo-700 flex items-center gap-1">
                          <span className="truncate">{ref.title || ref.url}</span>
                          <ExternalLink className="w-3 h-3 shrink-0" />
                        </div>
                        {ref.snippet && (
                          <p className="text-[11px] text-slate-500 line-clamp-2">
                            {ref.snippet}
                          </p>
                        )}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        /* TAB 2: New Project Design Copilot Chat */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-5 flex flex-col justify-between min-h-[540px] shadow-sm">
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100">
                <div className="text-sm font-bold text-slate-900">
                  새 프로젝트 기획 · 진행 코파일럿 (웹 검색 연동)
                </div>
                <select
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs bg-white"
                >
                  <option value="">참고 기존 프로젝트: 전체</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      참고: {p.name}
                    </option>
                  ))}
                </select>
              </div>

              {chatMessages.length === 0 ? (
                <div className="py-6 space-y-3">
                  <p className="text-xs text-slate-500 text-center">
                    새 프로젝트의 기획·아키텍처·차별화 포인트·협업/일정 설계를 무엇이든 물어보세요. 필요하면 최신 웹 레퍼런스를 자동으로 검색해 제안합니다.
                  </p>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {QUICK_PROMPTS.map((qp, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => handleSendChat(null, qp)}
                        className="text-left rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs text-slate-700 hover:border-indigo-300 hover:bg-indigo-50/40 transition-colors"
                      >
                        {qp}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-3 max-h-[420px] overflow-y-auto pr-1">
                  {chatMessages.map((msg, idx) => (
                    <div
                      key={idx}
                      className={`rounded-xl p-4 text-sm ${
                        msg.role === "user"
                          ? "bg-slate-900 text-white ml-10"
                          : "bg-slate-50 border border-slate-200 text-slate-800 mr-4"
                      }`}
                    >
                      {msg.role === "user" ? (
                        <p className="whitespace-pre-wrap text-xs leading-relaxed">
                          {msg.content}
                        </p>
                      ) : (
                        <div className="space-y-3">
                          <div className="prose prose-xs prose-slate max-w-none">
                            <ReactMarkdown>{msg.content}</ReactMarkdown>
                          </div>
                          {msg.used_web_fallback && (
                            <div className="pt-2 border-t border-slate-200 flex flex-wrap items-center gap-1.5 text-[11px] text-indigo-700">
                              <Globe className="w-3.5 h-3.5" />
                              <span className="font-semibold">웹 검색 보강:</span>
                              {(msg.web_sources || []).map((s, si) => (
                                <a
                                  key={si}
                                  href={s.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="underline hover:text-indigo-900 truncate max-w-[240px]"
                                >
                                  {s.title || s.url}
                                </a>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <form onSubmit={handleSendChat} className="pt-4 border-t border-slate-100 flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="새 프로젝트 아이디어, 아키텍처, 검증 지표, 최신 기술 비교 등을 질문해 보세요..."
                className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={chatRunning || !chatInput.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                <span>{chatRunning ? "설계 중..." : "전송"}</span>
              </button>
            </form>
          </div>

          <div>
            <StepIndicator steps={chatSteps} />
          </div>
        </div>
      )}
    </div>
  );
}
