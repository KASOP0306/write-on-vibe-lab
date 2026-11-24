import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Bot,
  ClipboardList,
  ExternalLink,
  Plus,
  Send,
  Trash2,
} from "lucide-react";
import { api } from "../api/client.js";
import StepIndicator from "../components/StepIndicator.jsx";

export default function CopilotRetroPage({ projects, onAddInterest }) {
  const [mode, setMode] = useState("copilot");

  // Mode A: Copilot Chat
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [chatSteps, setChatSteps] = useState([]);
  const [chatRunning, setChatRunning] = useState(false);

  // Mode B: Application Retrospective
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
  const [addedKeywords, setAddedKeywords] = useState(new Set());
  const [applications, setApplications] = useState([]);

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

  const updateStepList = (setter, ev) => {
    if (ev.event === "node_start") {
      setter((prev) => [
        ...prev,
        { node: ev.node, status: "running", message: ev.message },
      ]);
    } else if (ev.event === "node_end") {
      setter((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (next[i].node === ev.node || next[i].status === "running") {
            next[i] = { ...next[i], node: ev.node, status: "done" };
            break;
          }
        }
        return next;
      });
    } else if (ev.event === "error") {
      setter((prev) => [
        ...prev,
        { node: "error", status: "error", message: ev.message },
      ]);
    }
  };

  const handleSendChat = async (e) => {
    e.preventDefault();
    const msg = chatInput.trim();
    if (!msg || chatRunning) return;

    const historyForApi = chatMessages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    setChatMessages((prev) => [...prev, { role: "user", content: msg }]);
    setChatInput("");
    setChatRunning(true);
    setChatSteps([]);

    try {
      await api.copilotChat(
        {
          message: msg,
          project_id: selectedProjectId ? Number(selectedProjectId) : null,
          chat_history: historyForApi,
        },
        (ev) => {
          updateStepList(setChatSteps, ev);
          if (ev.event === "done") {
            setChatMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                content: ev.data?.answer || "",
                usedWebFallback: ev.data?.used_web_fallback,
                webSources: ev.data?.web_sources || [],
              },
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
        updateStepList(setRetroSteps, ev);
        if (ev.event === "done") {
          setRetroResult(ev.data);
          loadApplications();
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

  const handleQuickAddInterest = async (keyword) => {
    await onAddInterest(keyword, "retrospective_suggested");
    setAddedKeywords((prev) => new Set([...prev, keyword]));
  };

  const handleDeleteLog = async (id) => {
    if (!window.confirm("이 지원 회고 기록을 삭제할까요?")) return;
    try {
      await api.deleteApplication(id);
      setApplications((prev) => prev.filter((item) => item.id !== id));
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">5. 코파일럿 &amp; 회고</h2>
          <p className="text-sm text-slate-600 mt-1">
            과거 경험·관심 클립 기반 Corrective RAG 프로젝트 조언과 취준 결과 Gap 분석·보완 플랜을 실행합니다.
          </p>
        </div>

        <div className="inline-flex rounded-xl border border-slate-200 bg-white p-1">
          <button
            type="button"
            onClick={() => setMode("copilot")}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold ${
              mode === "copilot"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            <Bot className="w-3.5 h-3.5" />
            <span>프로젝트 코파일럿</span>
          </button>
          <button
            type="button"
            onClick={() => setMode("retro")}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold ${
              mode === "retro"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            <ClipboardList className="w-3.5 h-3.5" />
            <span>취준 회고 &amp; Gap 플래너</span>
          </button>
        </div>
      </div>

      {mode === "copilot" ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-5 flex flex-col justify-between min-h-[520px] shadow-sm">
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-2 pb-3 border-b border-slate-100">
                <span className="text-xs font-semibold text-slate-600">
                  Corrective RAG 채팅 (내 경험 + 관심 클립 + 부족 시 웹 검색 1회)
                </span>
                <select
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs bg-white"
                >
                  <option value="">전체 경험 참조</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
                {chatMessages.length === 0 ? (
                  <div className="py-16 text-center text-sm text-slate-400">
                    예: &ldquo;내 과거 FastAPI/pgvector 경험을 살려서 다음 포트폴리오에 멀티에이전트 평가 파이프라인을 어떻게 붙이면 좋을까?&rdquo;
                  </div>
                ) : (
                  chatMessages.map((m, idx) =>
                    m.role === "user" ? (
                      <div key={idx} className="flex justify-end">
                        <div className="max-w-[85%] rounded-2xl bg-slate-900 text-white px-4 py-2.5 text-sm whitespace-pre-wrap">
                          {m.content}
                        </div>
                      </div>
                    ) : (
                      <div key={idx} className="flex justify-start">
                        <div className="max-w-[92%] rounded-2xl bg-slate-50 border border-slate-200 px-4 py-3 space-y-2">
                          {m.usedWebFallback && (
                            <span className="inline-block rounded-full bg-blue-50 border border-blue-200 px-2 py-0.5 text-[10px] font-semibold text-blue-700">
                              Corrective Web Search 보강 적용
                            </span>
                          )}
                          <div className="prose prose-sm prose-slate max-w-none">
                            <ReactMarkdown>{m.content}</ReactMarkdown>
                          </div>
                          {(m.webSources || []).length > 0 && (
                            <div className="pt-2 border-t border-slate-200 flex flex-wrap gap-2">
                              {m.webSources.map((s, sIdx) => (
                                <a
                                  key={sIdx}
                                  href={s.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-[11px] text-blue-600 hover:underline"
                                >
                                  <span>{s.title || s.url}</span>
                                  <ExternalLink className="w-3 h-3" />
                                </a>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  )
                )}
              </div>
            </div>

            <form
              onSubmit={handleSendChat}
              className="pt-3 mt-4 border-t border-slate-100 flex gap-2"
            >
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="새 프로젝트 기획, 트러블슈팅, 아키텍처 질문을 입력하세요..."
                className="flex-1 rounded-lg border border-slate-200 px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/15"
              />
              <button
                type="submit"
                disabled={chatRunning || !chatInput.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
                <span>{chatRunning ? "답변 중..." : "전송"}</span>
              </button>
            </form>
          </div>

          <div>
            <StepIndicator steps={chatSteps} />
          </div>
        </div>
      ) : (
        <div className="space-y-8">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <form
              onSubmit={handleRetrospect}
              className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm"
            >
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <input
                  required
                  type="text"
                  value={retroForm.company_name}
                  onChange={(e) =>
                    setRetroForm({ ...retroForm, company_name: e.target.value })
                  }
                  placeholder="지원 기업명 *"
                  className="md:col-span-2 rounded-lg border border-slate-200 px-3 py-2 text-sm"
                />
                <select
                  value={retroForm.stage}
                  onChange={(e) =>
                    setRetroForm({ ...retroForm, stage: e.target.value })
                  }
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white"
                >
                  <option value="서류">서류</option>
                  <option value="코테">코테 / 과제</option>
                  <option value="면접">면접</option>
                </select>
                <select
                  value={retroForm.status}
                  onChange={(e) =>
                    setRetroForm({ ...retroForm, status: e.target.value })
                  }
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white"
                >
                  <option value="불합격">불합격</option>
                  <option value="진행중">진행중</option>
                  <option value="합격">합격</option>
                </select>
              </div>

              <input
                type="text"
                value={retroForm.role}
                onChange={(e) =>
                  setRetroForm({ ...retroForm, role: e.target.value })
                }
                placeholder="지원 직무 (예: AI Agent Backend Engineer)"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />

              <textarea
                required
                rows={4}
                value={retroForm.feedback_memo}
                onChange={(e) =>
                  setRetroForm({ ...retroForm, feedback_memo: e.target.value })
                }
                placeholder="면접 질문, 탈락 추정 사유, 부족했다고 느낀 역량·피드백을 솔직하게 적어 주세요..."
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={retroRunning}
                  className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  {retroRunning
                    ? "Gap 분석 & 보완 플랜 수립 중..."
                    : "회고 저장 & Gap 분석"}
                </button>
              </div>
            </form>

            <div>
              <StepIndicator steps={retroSteps} />
            </div>
          </div>

          {retroResult && (
            <div className="rounded-2xl border border-slate-200 bg-white p-6 space-y-5 shadow-sm">
              <div className="space-y-2">
                <h3 className="text-base font-bold text-slate-900">
                  포트폴리오 Gap 분석 결과
                </h3>
                <div className="prose prose-sm prose-slate max-w-none bg-slate-50 rounded-xl p-4">
                  <ReactMarkdown>{retroResult.gap_analysis}</ReactMarkdown>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-4 space-y-2">
                  <div className="text-xs font-bold text-blue-900">
                    단기 보완 플랜 (자소서·포폴)
                  </div>
                  <ul className="list-disc pl-4 space-y-1 text-xs text-slate-800">
                    {(retroResult.short_term_plan || []).map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-4 space-y-2">
                  <div className="text-xs font-bold text-indigo-900">
                    중기 보완 플랜 (신규 프로젝트·학습)
                  </div>
                  <ul className="list-disc pl-4 space-y-1 text-xs text-slate-800">
                    {(retroResult.mid_term_plan || []).map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>

              {(retroResult.suggested_interests || []).length > 0 && (
                <div className="space-y-2 pt-2 border-t border-slate-100">
                  <div className="text-xs font-semibold text-slate-700">
                    추천 보완 키워드 (클릭 시 사이드바 관심 분야에 즉시 추가):
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {retroResult.suggested_interests.map((kw, idx) => {
                      const added = addedKeywords.has(kw);
                      return (
                        <button
                          key={idx}
                          type="button"
                          disabled={added}
                          onClick={() => handleQuickAddInterest(kw)}
                          className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${
                            added
                              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : "bg-amber-50 text-amber-900 border border-amber-200 hover:bg-amber-100"
                          }`}
                        >
                          <Plus className="w-3 h-3" />
                          <span>{added ? `${kw} (추가됨)` : kw}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Past Application Logs */}
          <div className="space-y-3 pt-4 border-t border-slate-200">
            <h3 className="text-base font-bold text-slate-900">
              지원 회고 타임라인 ({applications.length})
            </h3>
            {applications.length === 0 ? (
              <p className="text-sm text-slate-500">기록된 지원 회고가 없습니다.</p>
            ) : (
              <div className="space-y-3">
                {applications.map((log) => (
                  <div
                    key={log.id}
                    className="rounded-xl border border-slate-200 bg-white p-4 space-y-2 shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-slate-900">
                          {log.company_name}
                        </span>
                        {log.role && (
                          <span className="text-xs text-slate-500">{log.role}</span>
                        )}
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                          {log.stage}
                        </span>
                        <span
                          className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
                            log.status === "합격"
                              ? "bg-emerald-50 text-emerald-700"
                              : log.status === "불합격"
                                ? "bg-rose-50 text-rose-700"
                                : "bg-blue-50 text-blue-700"
                          }`}
                        >
                          {log.status}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleDeleteLog(log.id)}
                        className="text-slate-400 hover:text-red-600"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                    <p className="text-xs text-slate-600">{log.feedback_memo}</p>
                    {log.gap_analysis && (
                      <details className="text-xs text-slate-700 pt-1">
                        <summary className="cursor-pointer font-semibold text-slate-800">
                          Gap 분석 &amp; 액션 플랜 보기
                        </summary>
                        <div className="mt-2 prose prose-xs prose-slate max-w-none bg-slate-50 rounded-lg p-3">
                          <ReactMarkdown>
                            {`${log.gap_analysis}\n\n${log.action_plan}`}
                          </ReactMarkdown>
                        </div>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
