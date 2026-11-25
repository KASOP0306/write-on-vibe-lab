import { useState } from "react";
import { CheckCircle2, RotateCcw, Save, Send, Sparkles, Trash2 } from "lucide-react";
import { api } from "../api/client.js";
import StarMeter from "../components/StarMeter.jsx";
import StepIndicator from "../components/StepIndicator.jsx";

export default function ExperienceMinerPage({ projects, experiences, onRefresh }) {
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [rawNotes, setRawNotes] = useState("");
  const [threadId, setThreadId] = useState(null);
  const [replyText, setReplyText] = useState("");

  const [messages, setMessages] = useState([]);
  const [steps, setSteps] = useState([]);
  const [completenessScore, setCompletenessScore] = useState(0);
  const [starScores, setStarScores] = useState(null);
  const [missingPoints, setMissingPoints] = useState([]);
  const [draftStar, setDraftStar] = useState(null);
  const [savedResult, setSavedResult] = useState(null);
  const [running, setRunning] = useState(false);

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
                  : undefined,
            };
            break;
          }
        }
        return next;
      });
      if (ev.data?.star) setDraftStar(ev.data.star);
      if (ev.data?.completeness_score !== undefined) {
        setCompletenessScore(ev.data.completeness_score);
      }
      if (ev.data?.star_scores?.axes) setStarScores(ev.data.star_scores);
      if (ev.data?.missing_points) setMissingPoints(ev.data.missing_points);
    } else if (ev.event === "interrupt") {
      setThreadId(ev.thread_id);
      setCompletenessScore(ev.data?.completeness_score ?? 0);
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
      if (ev.data?.star_scores?.axes) setStarScores(ev.data.star_scores);
      setMissingPoints([]);
      if (ev.data?.star) setDraftStar(ev.data.star);
      onRefresh();
    } else if (ev.event === "error") {
      setSteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: ev.message },
      ]);
    }
  };

  const handleStart = async (e) => {
    e.preventDefault();
    if (!rawNotes.trim() || running) return;

    setRunning(true);
    setSteps([]);
    setSavedResult(null);
    setMessages([{ role: "user", content: rawNotes.trim() }]);

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

  const handleReset = () => {
    setThreadId(null);
    setRawNotes("");
    setReplyText("");
    setMessages([]);
    setSteps([]);
    setCompletenessScore(0);
    setStarScores(null);
    setMissingPoints([]);
    setDraftStar(null);
    setSavedResult(null);
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
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">3. 경험 채굴 (STAR-L)</h2>
          <p className="text-sm text-slate-600 mt-1">
            거친 메모를 입력하면 5축 STAR-L BARS 기준으로 빈틈을 탐지해 역질문으로 정량 지표·의사결정·배운 점(L)을 끌어냅니다.
          </p>
        </div>
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Input & Interview Chat */}
        <div className="lg:col-span-2 space-y-4">
          {!threadId && !savedResult && (
            <form
              onSubmit={handleStart}
              className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm"
            >
              <label className="block space-y-1.5">
                <span className="text-xs font-semibold text-slate-700">
                  연결할 프로젝트 (선택)
                </span>
                <select
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white"
                >
                  <option value="">프로젝트 미지정</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block space-y-1.5">
                <span className="text-xs font-semibold text-slate-700">
                  경험 메모 입력
                </span>
                <textarea
                  rows={5}
                  required
                  value={rawNotes}
                  onChange={(e) => setRawNotes(e.target.value)}
                  placeholder="예: FastAPI 서버 응답이 느려서 인덱스를 걸고 비동기로 바꿨더니 빨라졌다. 정확한 수치나 어떤 쿼리가 문제였는지는 대충 기억남..."
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/15"
                />
              </label>

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={running || !rawNotes.trim()}
                  className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  <Sparkles className="w-4 h-4" />
                  <span>{running ? "분석 중..." : "경험 채굴 시작"}</span>
                </button>
              </div>
            </form>
          )}

          {/* Conversation History */}
          {messages.length > 0 && (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                역질문 인터뷰 진행 내역 {threadId && `(세션: ${threadId})`}
              </div>

              <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
                {messages.map((msg, idx) =>
                  msg.role === "user" ? (
                    <div key={idx} className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl bg-slate-900 text-white px-4 py-2.5 text-sm whitespace-pre-wrap">
                        {msg.content}
                      </div>
                    </div>
                  ) : (
                    <div key={idx} className="flex justify-start">
                      <div className="max-w-[92%] rounded-2xl bg-indigo-50/70 border border-indigo-200 px-4 py-3 space-y-2.5">
                        <div className="text-xs font-bold text-indigo-950 flex items-center justify-between gap-2">
                          <span>AI 인터뷰어 드릴다운 역질문 (DDI Funnel × Bar Raiser)</span>
                        </div>
                        {(msg.structured_questions || []).length > 0 ? (
                          <div className="space-y-2">
                            {msg.structured_questions.map((sq, qIdx) => (
                              <div
                                key={qIdx}
                                className="rounded-xl bg-white border border-indigo-100 p-3 space-y-1"
                              >
                                <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
                                  <span className="rounded-full bg-indigo-100 px-2 py-0.5 font-bold text-indigo-800">
                                    {sq.technique_label || sq.technique}
                                  </span>
                                  <span className="rounded-full bg-slate-100 px-2 py-0.5 font-semibold uppercase text-slate-700">
                                    타깃 축: {sq.target_axis}
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
                              </div>
                            ))}
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
                    placeholder="역질문에 대한 답변을 입력하세요. (기억나는 수치, 원인, 본인 기여 등)"
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
                      <span>{running ? "반영 중..." : "답변 보내기"}</span>
                    </button>
                  </div>
                </div>
              )}

              {savedResult && (
                <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-4 flex items-center gap-2.5 text-sm text-emerald-900">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                  <div>
                    <strong>경험 #{savedResult.experience_id} 저장 완료!</strong>{" "}
                    (완성도 {savedResult.completeness_score}점 · 벡터 동기화:{" "}
                    {savedResult.vector_synced ? "완료" : "대기"})
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Meter + Live STAR Preview + Steps */}
        <div className="space-y-4">
          <StarMeter
            score={completenessScore}
            missingPoints={missingPoints}
            starScores={starScores}
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
          저장된 STAR 경험 아카이브 ({experiences.length})
        </h3>
        {experiences.length === 0 ? (
          <p className="text-sm text-slate-500">아직 저장된 경험이 없습니다.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {experiences.map((exp) => (
              <div
                key={exp.id}
                className="rounded-xl border border-slate-200 bg-white p-4 space-y-2 shadow-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-bold text-slate-900">{exp.title}</h4>
                    <div className="flex items-center gap-2 mt-0.5 text-[11px] text-slate-500">
                      <span>
                        {exp.project_id
                          ? projectNameById[exp.project_id] || `프로젝트 #${exp.project_id}`
                          : "프로젝트 미지정"}
                      </span>
                      <span>·</span>
                      <span className="font-semibold text-emerald-700">
                        완성도 {exp.completeness_score}점
                      </span>
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
