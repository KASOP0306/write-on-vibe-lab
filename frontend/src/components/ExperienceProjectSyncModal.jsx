import { useEffect, useState } from "react";
import {
  Check,
  CheckCircle2,
  FolderSync,
  Loader2,
  Sparkles,
  X,
} from "lucide-react";
import { api } from "../api/client.js";

export default function ExperienceProjectSyncModal({
  experience,
  projects = [],
  defaultProjectId = null,
  onClose,
  onSynced = null,
}) {
  const initialPid =
    defaultProjectId ??
    experience?.project_id ??
    (projects.length > 0 ? projects[0].id : "");

  const [targetProjectId, setTargetProjectId] = useState(
    initialPid ? String(initialPid) : ""
  );
  const [instruction, setInstruction] = useState("");
  const [proposing, setProposing] = useState(false);
  const [proposal, setProposal] = useState(null);
  const [selectedIndices, setSelectedIndices] = useState(new Set());
  const [applySummary, setApplySummary] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [doneMsg, setDoneMsg] = useState("");

  useEffect(() => {
    setProposal(null);
    setError("");
    setDoneMsg("");
  }, [experience?.id, targetProjectId]);

  if (!experience) return null;

  const handleGenerateProposal = async () => {
    if (!targetProjectId || proposing) return;
    setProposing(true);
    setError("");
    setProposal(null);
    setDoneMsg("");
    try {
      const res = await api.syncProjectFromExperience(
        Number(targetProjectId),
        experience.id,
        instruction.trim()
      );
      setProposal(res);
      setSelectedIndices(
        new Set((res.section_updates || []).map((_, idx) => idx))
      );
      setApplySummary(Boolean(res.suggested_summary?.trim()));
    } catch (err) {
      setError(`프로젝트 정리안 생성 실패: ${err.message}`);
    } finally {
      setProposing(false);
    }
  };

  const toggleSection = (idx) => {
    setSelectedIndices((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleApply = async () => {
    if (!proposal || !targetProjectId || applying) return;
    const chosenUpdates = (proposal.section_updates || [])
      .filter((_, idx) => selectedIndices.has(idx))
      .map((u) => ({
        section_id: u.section_id ?? null,
        section_type: u.section_type,
        track: u.track || "core",
        title: u.title,
        content: u.proposed_content,
      }));

    if (chosenUpdates.length === 0 && !(applySummary && proposal.suggested_summary?.trim())) {
      setError("반영할 섹션 또는 프로젝트 요약을 최소 1개 이상 선택해 주세요.");
      return;
    }

    setApplying(true);
    setError("");
    try {
      const res = await api.applyProjectUpdates(Number(targetProjectId), {
        filename: proposal.filename || `경험채굴 #${experience.id}`,
        source_type: "experience_mining",
        file_format: "star-l",
        document_summary: proposal.document_summary || "",
        raw_char_count: proposal.raw_char_count || 0,
        updated_summary:
          applySummary && proposal.suggested_summary?.trim()
            ? proposal.suggested_summary.trim()
            : null,
        tech_stack_additions: proposal.suggested_tech_stack_additions || [],
        section_updates: chosenUpdates,
        experiences: [],
        link_experience_id: experience.id,
      });
      setDoneMsg(
        `반영 완료! 섹션 ${res.updated_section_types.length}개 정리 및 벡터 ${res.vector_synced_count}건 동기화 완료`
      );
      if (onSynced) {
        await onSynced(Number(targetProjectId));
      }
    } catch (err) {
      setError(`프로젝트 반영 실패: ${err.message}`);
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[90vh] flex flex-col shadow-xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-3">
          <div>
            <div className="inline-flex items-center gap-1.5 text-xs font-bold text-indigo-700">
              <FolderSync className="w-4 h-4" />
              <span>경험 채굴 · 역질문 결과 → 프로젝트 섹션 재정리</span>
            </div>
            <h3 className="text-base font-bold text-slate-900 mt-0.5">
              ‘{experience.title}’ 내용을 프로젝트에 반영하기
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              역질문 답변에서 새로 밝혀진 의사결정·대안 비교·정량 수치·회고를 기존 프로젝트 섹션에 중복 없이 통합합니다.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-4 text-xs">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="font-semibold text-slate-700">반영할 대상 프로젝트</span>
              <select
                value={targetProjectId}
                onChange={(e) => setTargetProjectId(e.target.value)}
                disabled={proposing || applying}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              >
                {projects.length === 0 ? (
                  <option value="">등록된 프로젝트가 없습니다</option>
                ) : (
                  projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} {String(p.id) === String(experience.project_id) ? "(현재 연결됨)" : ""}
                    </option>
                  ))
                )}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="font-semibold text-slate-700">정리 지시사항 (선택)</span>
              <input
                type="text"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                disabled={proposing || applying}
                placeholder="예: 트러블슈팅과 정량 성과 섹션 위주로 보강해줘"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
            </label>
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              disabled={!targetProjectId || proposing || applying}
              onClick={handleGenerateProposal}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {proposing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Sparkles className="w-3.5 h-3.5" />
              )}
              <span>
                {proposing
                  ? "역질문 내용 분석 및 섹션 정리안 생성 중..."
                  : proposal
                    ? "정리안 다시 생성"
                    : "AI 섹션 정리안 생성"}
              </span>
            </button>
          </div>

          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-800">
              {error}
            </div>
          )}

          {doneMsg && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-emerald-900 flex items-center gap-2 font-semibold">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>{doneMsg}</span>
            </div>
          )}

          {/* Diff Proposal Preview */}
          {proposal && (
            <div className="space-y-4 pt-2 border-t border-slate-100">
              {proposal.document_summary && (
                <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-3.5 text-indigo-950">
                  <strong>반영 요약:</strong> {proposal.document_summary}
                </div>
              )}

              {proposal.suggested_summary?.trim() && (
                <label className="block rounded-xl border border-slate-200 bg-slate-50/70 p-3.5 space-y-1.5 cursor-pointer">
                  <div className="flex items-center gap-2 font-bold text-slate-800">
                    <input
                      type="checkbox"
                      checked={applySummary}
                      onChange={(e) => setApplySummary(e.target.checked)}
                    />
                    <span>프로젝트 전체 요약(Summary) 업데이트 반영</span>
                  </div>
                  <p className="text-slate-600 pl-5 whitespace-pre-wrap">
                    {proposal.suggested_summary}
                  </p>
                </label>
              )}

              {(proposal.section_updates || []).length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-slate-500">
                  기존 섹션에 이미 모든 내용이 충분히 반영되어 있어 추가 변경 제안이 없습니다.
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="font-bold text-slate-800">
                    섹션별 정리 제안 ({selectedIndices.size} / {proposal.section_updates.length}개 선택)
                  </div>
                  {proposal.section_updates.map((u, idx) => {
                    const checked = selectedIndices.has(idx);
                    return (
                      <div
                        key={`${u.section_type}-${idx}`}
                        className={`rounded-xl border p-4 space-y-2.5 transition ${
                          checked
                            ? "border-indigo-300 bg-white ring-1 ring-indigo-500/15"
                            : "border-slate-200 bg-slate-50/60 opacity-65"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <label className="flex items-start gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleSection(idx)}
                              className="mt-0.5"
                            />
                            <div>
                              <div className="font-bold text-slate-900 text-xs">
                                {u.title}{" "}
                                <span className="font-mono text-[10px] text-slate-400">
                                  ({u.section_type})
                                </span>
                              </div>
                              {u.change_summary && (
                                <div className="text-[11px] text-indigo-700 mt-0.5">
                                  {u.change_summary}
                                </div>
                              )}
                            </div>
                          </label>
                        </div>

                        {(u.added_facts || []).length > 0 && (
                          <div className="flex flex-wrap gap-1.5 pl-5">
                            {u.added_facts.map((fact, fIdx) => (
                              <span
                                key={fIdx}
                                className="rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[10px] text-emerald-800"
                              >
                                + {fact}
                              </span>
                            ))}
                          </div>
                        )}

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 pl-5">
                          <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
                            <div className="text-[10px] font-bold text-slate-500 mb-1">
                              기존 섹션 내용 (Before)
                            </div>
                            <div className="text-[11px] text-slate-600 whitespace-pre-wrap max-h-40 overflow-y-auto">
                              {u.before_content?.trim() || "(비어 있음 / 신규 섹션)"}
                            </div>
                          </div>
                          <div className="rounded-lg border border-emerald-200 bg-emerald-50/40 p-2.5">
                            <div className="text-[10px] font-bold text-emerald-700 mb-1">
                              재정리 제안 내용 (After)
                            </div>
                            <div className="text-[11px] text-slate-800 whitespace-pre-wrap max-h-40 overflow-y-auto">
                              {u.proposed_content}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            닫기
          </button>
          {proposal && !doneMsg && (
            <button
              type="button"
              disabled={applying}
              onClick={handleApply}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {applying ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Check className="w-3.5 h-3.5" />
              )}
              <span>
                {applying
                  ? "프로젝트 반영 중..."
                  : `선택한 섹션(${selectedIndices.size}개) 프로젝트에 반영`}
              </span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
