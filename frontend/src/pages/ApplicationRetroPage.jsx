import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  ArrowRight,
  ClipboardCheck,
  Loader2,
  Rocket,
  Trash2,
} from "lucide-react";
import { api } from "../api/client.js";
import StepIndicator from "../components/StepIndicator.jsx";

export default function ApplicationRetroPage({ onJumpToCopilot }) {
  const [retroForm, setRetroForm] = useState({
    company_name: "",
    role: "",
    stage: "서류",
    status: "불합격",
    feedback_memo: "",
  });
  const [retroSteps, setRetroSteps] = useState([]);
  const [retroRunning, setRetroRunning] = useState(false);
  const [retroResult, setRetroResult] = useState(null);
  const [applications, setApplications] = useState([]);
  const [filterStatus, setFilterStatus] = useState("all");

  const loadApplications = async () => {
    try {
      const logs = await api.listApplications();
      setApplications(logs || []);
    } catch (err) {
      console.warn(err);
    }
  };

  useEffect(() => {
    loadApplications();
  }, []);

  const handleRetrospect = async (e) => {
    e.preventDefault();
    if (!retroForm.company_name.trim() || !retroForm.feedback_memo.trim() || retroRunning) {
      return;
    }

    setRetroRunning(true);
    setRetroSteps([]);
    setRetroResult(null);

    try {
      await api.retrospectApplication(retroForm, (ev) => {
        if (ev.event === "node_start") {
          setRetroSteps((prev) => [
            ...prev,
            { node: ev.node, status: "running", message: ev.message },
          ]);
        } else if (ev.event === "node_end") {
          setRetroSteps((prev) => {
            const next = [...prev];
            for (let i = next.length - 1; i >= 0; i -= 1) {
              if (next[i].node === ev.node || next[i].status === "running") {
                next[i] = { ...next[i], node: ev.node, status: "done" };
                break;
              }
            }
            return next;
          });
        } else if (ev.event === "done") {
          setRetroResult(ev.data);
          loadApplications();
        } else if (ev.event === "error") {
          setRetroSteps((prev) => [
            ...prev,
            { node: "error", status: "error", message: ev.message },
          ]);
        }
      });
    } catch (err) {
      setRetroSteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: err.message },
      ]);
    } finally {
      setRetroRunning(false);
    }
  };

  const handleDeleteLog = async (log) => {
    if (!window.confirm(`'${log.company_name} (${log.stage})' 회고 기록을 삭제할까요?`)) {
      return;
    }
    try {
      await api.deleteApplication(log.id);
      setApplications((prev) => prev.filter((item) => item.id !== log.id));
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const passCount = applications.filter((a) => a.status === "합격").length;
  const failCount = applications.filter((a) => a.status === "불합격").length;
  const inProgressCount = applications.filter((a) => a.status === "진행중").length;

  const filteredApps =
    filterStatus === "all"
      ? applications
      : applications.filter((a) => a.status === filterStatus);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <ClipboardCheck className="w-6 h-6 text-indigo-600" />
          <span>6. 지원 &amp; 취준 회고</span>
        </h2>
        <p className="text-sm text-slate-600 mt-1">
          서류·과제·면접 결과를 기록하면 <strong>내 포트폴리오 캐릭터와 경험</strong> 대비 핵심 격차(Gap)를 진단하고,
          보완이 필요한 주제를 <strong>새 프로젝트 코파일럿</strong>으로 바로 연결합니다.
        </p>
      </div>

      {/* Summary Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "총 지원 기록", value: applications.length, tone: "text-slate-900" },
          { label: "합격", value: passCount, tone: "text-emerald-700" },
          { label: "진행중", value: inProgressCount, tone: "text-indigo-700" },
          { label: "불합격 · 복기", value: failCount, tone: "text-rose-700" },
        ].map((card) => (
          <div
            key={card.label}
            className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs"
          >
            <div className="text-xs text-slate-500">{card.label}</div>
            <div className={`text-2xl font-extrabold mt-1 ${card.tone}`}>
              {card.value}
            </div>
          </div>
        ))}
      </div>

      {/* Retrospect Form + Progress */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <form
          onSubmit={handleRetrospect}
          className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm"
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">지원 기업 *</span>
              <input
                required
                type="text"
                value={retroForm.company_name}
                onChange={(e) =>
                  setRetroForm({ ...retroForm, company_name: e.target.value })
                }
                placeholder="예: 카카오, 토스, 당근"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">지원 직무</span>
              <input
                type="text"
                value={retroForm.role}
                onChange={(e) =>
                  setRetroForm({ ...retroForm, role: e.target.value })
                }
                placeholder="예: AI 플랫폼 백엔드, 서비스 기획"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">전형 단계</span>
              <select
                value={retroForm.stage}
                onChange={(e) =>
                  setRetroForm({ ...retroForm, stage: e.target.value })
                }
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white"
              >
                <option value="서류">서류</option>
                <option value="코테/과제">코테 / 과제</option>
                <option value="1차 면접">1차 면접</option>
                <option value="최종 면접">최종 면접</option>
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">결과</span>
              <select
                value={retroForm.status}
                onChange={(e) =>
                  setRetroForm({ ...retroForm, status: e.target.value })
                }
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white"
              >
                <option value="불합격">불합격</option>
                <option value="합격">합격</option>
                <option value="진행중">진행중</option>
              </select>
            </label>
          </div>

          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">
              복기 메모 / 면접 질문 / 아쉬웠던 점 *
            </span>
            <textarea
              required
              rows={4}
              value={retroForm.feedback_memo}
              onChange={(e) =>
                setRetroForm({ ...retroForm, feedback_memo: e.target.value })
              }
              placeholder="예: 면접에서 대규모 트래픽 동시성 처리나 팀 간 우선순위 갈등 해결 경험을 깊게 물었는데 근거가 약했음."
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={retroRunning}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {retroRunning ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ClipboardCheck className="w-4 h-4" />
              )}
              <span>
                {retroRunning ? "Gap 진단 & 보완 플랜 생성 중..." : "회고 저장 & Gap 분석"}
              </span>
            </button>
          </div>
        </form>

        <div>
          <StepIndicator steps={retroSteps} />
        </div>
      </div>

      {/* Latest Retrospect Result + Handoff to New Project Copilot */}
      {retroResult && (
        <div className="rounded-2xl border border-indigo-200 bg-white p-6 space-y-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-base font-bold text-slate-900">
              AI Gap 진단 &amp; 보완 액션 플랜
            </h3>
            {retroResult.recommended_copilot_topic && (
              <button
                type="button"
                onClick={() => onJumpToCopilot?.(retroResult.recommended_copilot_topic)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
              >
                <Rocket className="w-3.5 h-3.5" />
                <span>새 프로젝트 코파일럿에서 보완 프로젝트 기획하기</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {retroResult.recommended_copilot_topic && (
            <div className="rounded-xl bg-indigo-50 border border-indigo-200 px-4 py-2.5 text-xs text-indigo-950">
              <strong>추천 보완 프로젝트 방향:</strong> {retroResult.recommended_copilot_topic}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-xl bg-rose-50/40 border border-rose-200 p-4 prose prose-xs prose-slate max-w-none">
              <div className="text-xs font-bold text-rose-900 mb-2">핵심 Gap 진단</div>
              <ReactMarkdown>{retroResult.gap_analysis}</ReactMarkdown>
            </div>
            <div className="rounded-xl bg-emerald-50/40 border border-emerald-200 p-4 prose prose-xs prose-slate max-w-none">
              <div className="text-xs font-bold text-emerald-900 mb-2">단기 · 중기 보완 플랜</div>
              <ReactMarkdown>{retroResult.action_plan}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}

      {/* History Archive */}
      <div className="space-y-3 pt-2 border-t border-slate-200">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-bold text-slate-900">
            지원 &amp; 회고 이력 ({filteredApps.length})
          </h3>
          <div className="flex gap-1.5">
            {["all", "합격", "진행중", "불합격"].map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => setFilterStatus(st)}
                className={`rounded-full px-3 py-1 text-xs font-semibold border ${
                  filterStatus === st
                    ? "bg-slate-900 text-white border-slate-900"
                    : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                }`}
              >
                {st === "all" ? "전체" : st}
              </button>
            ))}
          </div>
        </div>

        {filteredApps.length === 0 ? (
          <p className="text-sm text-slate-500">아직 기록된 지원 회고가 없습니다.</p>
        ) : (
          <div className="space-y-3">
            {filteredApps.map((log) => (
              <div
                key={log.id}
                className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3 shadow-xs"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-slate-900">
                      {log.company_name}
                    </span>
                    {log.role && (
                      <span className="text-xs text-slate-500">· {log.role}</span>
                    )}
                    <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold text-slate-700">
                      {log.stage}
                    </span>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${
                        log.status === "합격"
                          ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                          : log.status === "불합격"
                            ? "bg-rose-50 text-rose-700 border border-rose-200"
                            : "bg-indigo-50 text-indigo-700 border border-indigo-200"
                      }`}
                    >
                      {log.status}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        onJumpToCopilot?.(
                          `${log.company_name} ${log.role || ""} ${log.stage} 회고 보완: ${log.feedback_memo.slice(0, 140)}`
                        )
                      }
                      className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-100"
                    >
                      <Rocket className="w-3 h-3" />
                      <span>코파일럿으로 보완</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteLog(log)}
                      className="p-1 text-slate-400 hover:text-red-600"
                      title="삭제"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <p className="text-xs text-slate-700 bg-slate-50 rounded-lg p-3 whitespace-pre-wrap">
                  {log.feedback_memo}
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                  {log.gap_analysis && (
                    <div className="rounded-xl border border-slate-200 p-3 prose prose-xs prose-slate max-w-none">
                      <div className="font-bold text-slate-800 mb-1">Gap 분석</div>
                      <ReactMarkdown>{log.gap_analysis}</ReactMarkdown>
                    </div>
                  )}
                  {log.action_plan && (
                    <div className="rounded-xl border border-slate-200 p-3 prose prose-xs prose-slate max-w-none">
                      <div className="font-bold text-slate-800 mb-1">보완 플랜</div>
                      <ReactMarkdown>{log.action_plan}</ReactMarkdown>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
