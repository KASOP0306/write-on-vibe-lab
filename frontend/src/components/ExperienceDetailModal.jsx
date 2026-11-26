import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  FolderSync,
  Loader2,
  MessageSquareText,
  Pencil,
  Save,
  X,
} from "lucide-react";
import { api } from "../api/client.js";
import StarMeter from "./StarMeter.jsx";

export default function ExperienceDetailModal({
  experience,
  projects = [],
  projectName = "",
  onClose,
  onOpenProjectSync = null,
  onUpdated = null,
}) {
  const [currentExp, setCurrentExp] = useState(experience);
  const [showRawNotes, setShowRawNotes] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const [form, setForm] = useState({
    project_id: "",
    title: "",
    situation: "",
    task: "",
    action: "",
    result: "",
    learning: "",
    quantified_metrics: "",
  });

  useEffect(() => {
    setCurrentExp(experience);
    setEditing(false);
    setEditError("");
    if (experience) {
      setForm({
        project_id: experience.project_id ? String(experience.project_id) : "",
        title: experience.title || "",
        situation: experience.situation || "",
        task: experience.task || "",
        action: experience.action || "",
        result: experience.result || "",
        learning: experience.learning || "",
        quantified_metrics: experience.quantified_metrics || "",
      });
    }
  }, [experience]);

  if (!currentExp) return null;

  const resolvedProjectName =
    (currentExp.project_id &&
      projects.find((p) => p.id === currentExp.project_id)?.name) ||
    projectName ||
    (currentExp.project_id ? `프로젝트 #${currentExp.project_id}` : "프로젝트 미지정");

  const handleSaveEdit = async (e) => {
    e.preventDefault();
    if (!form.title.trim() || saving) return;
    setSaving(true);
    setEditError("");
    try {
      const updated = await api.updateExperience(currentExp.id, {
        project_id: form.project_id ? Number(form.project_id) : null,
        clear_project_id: !form.project_id,
        title: form.title.trim(),
        situation: form.situation,
        task: form.task,
        action: form.action,
        result: form.result,
        learning: form.learning,
        quantified_metrics: form.quantified_metrics,
        re_evaluate: true,
      });
      setCurrentExp(updated);
      setEditing(false);
      if (onUpdated) {
        await onUpdated(updated);
      }
    } catch (err) {
      setEditError(`수정 및 재채점 실패: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[88vh] flex flex-col shadow-xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-semibold text-slate-700">
                {resolvedProjectName}
              </span>
              <span className="rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 font-bold text-emerald-800">
                완성도 {currentExp.completeness_score}점
              </span>
              {currentExp.star_scores?.grade && (
                <span className="rounded-full bg-indigo-50 border border-indigo-200 px-2.5 py-0.5 font-bold text-indigo-800">
                  {currentExp.star_scores.grade}등급
                </span>
              )}
              {currentExp.star_scores?.xp > 0 && (
                <span className="rounded-full bg-violet-50 border border-violet-200 px-2.5 py-0.5 font-bold text-violet-800">
                  +{currentExp.star_scores.xp} XP
                </span>
              )}
            </div>
            <h3 className="text-lg font-bold text-slate-900">
              {editing ? "경험 수정 및 21지표 재채점" : currentExp.title}
            </h3>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {!editing && (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                <Pencil className="w-3.5 h-3.5 text-indigo-600" />
                <span>수정하기</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Body */}
        {editing ? (
          <form onSubmit={handleSaveEdit} className="flex-1 flex flex-col overflow-hidden">
            <div className="p-6 overflow-y-auto space-y-3.5 text-xs">
              {editError && (
                <div className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-rose-800">
                  {editError}
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <label className="block space-y-1">
                  <span className="font-semibold text-slate-700">경험 제목 *</span>
                  <input
                    type="text"
                    required
                    value={form.title}
                    onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
                  />
                </label>

                <label className="block space-y-1">
                  <span className="font-semibold text-slate-700">연결 프로젝트</span>
                  <select
                    value={form.project_id}
                    onChange={(e) => setForm((p) => ({ ...p, project_id: e.target.value }))}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
                  >
                    <option value="">프로젝트 미지정</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {[
                { key: "situation", label: "S · Situation (상황·제약·규모)", rows: 3 },
                { key: "task", label: "T · Task (목표·본인 책임·원인 진단)", rows: 3 },
                { key: "action", label: "A · Action (실행·대안 비교·주도성·장애물 돌파·협업)", rows: 4 },
                { key: "result", label: "R · Result (정량 수치·전후 비교·인과 검증·외부 반응)", rows: 3 },
                { key: "learning", label: "L · Learning (한계 성찰·일반화 원칙·후속 적용)", rows: 3 },
              ].map((field) => (
                <label key={field.key} className="block space-y-1">
                  <span className="font-semibold text-slate-700">{field.label}</span>
                  <textarea
                    rows={field.rows}
                    value={form[field.key]}
                    onChange={(e) =>
                      setForm((p) => ({ ...p, [field.key]: e.target.value }))
                    }
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs leading-relaxed"
                  />
                </label>
              ))}

              <label className="block space-y-1">
                <span className="font-semibold text-emerald-800">확인된 정량 지표 (선택)</span>
                <input
                  type="text"
                  value={form.quantified_metrics}
                  onChange={(e) =>
                    setForm((p) => ({ ...p, quantified_metrics: e.target.value }))
                  }
                  placeholder="예: 응답시간 1,800ms → 180ms (-90%), 오류율 4.2% → 0.3%"
                  className="w-full rounded-lg border border-emerald-200 bg-emerald-50/30 px-3 py-2 text-xs"
                />
              </label>
            </div>

            <div className="px-6 py-3.5 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-2">
              <button
                type="button"
                disabled={saving}
                onClick={() => setEditing(false)}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={saving || !form.title.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                <span>{saving ? "저장 및 21지표 재채점 중..." : "저장 및 21지표 재채점"}</span>
              </button>
            </div>
          </form>
        ) : (
          <>
            <div className="p-6 overflow-y-auto space-y-5 text-sm">
              {/* Full STAR-L Cards */}
              <div className="space-y-3">
                {[
                  { code: "S", title: "Situation (상황 · 맥락)", text: currentExp.situation, cls: "border-slate-200 bg-slate-50/60" },
                  { code: "T", title: "Task (과제 · 책임)", text: currentExp.task, cls: "border-slate-200 bg-slate-50/60" },
                  { code: "A", title: "Action (행동 · 의사결정 · 실행)", text: currentExp.action, cls: "border-indigo-200/80 bg-indigo-50/30" },
                  { code: "R", title: "Result (결과 · 검증)", text: currentExp.result, cls: "border-emerald-200/80 bg-emerald-50/30" },
                  { code: "L", title: "Learning (회고 · 원칙 · 재현성)", text: currentExp.learning, cls: "border-violet-200/80 bg-violet-50/30" },
                ].map((item) => (
                  <div key={item.code} className={`rounded-xl border p-3.5 space-y-1 ${item.cls}`}>
                    <div className="text-xs font-bold text-slate-800">
                      <span className="inline-block w-5 text-indigo-700">{item.code}</span>
                      {item.title}
                    </div>
                    <p className="text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">
                      {item.text?.trim() || "(미기재)"}
                    </p>
                  </div>
                ))}

                {currentExp.quantified_metrics?.trim() && (
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 text-xs text-emerald-900">
                    <strong className="block mb-0.5">확인된 정량 지표:</strong>
                    <span className="whitespace-pre-wrap">{currentExp.quantified_metrics}</span>
                  </div>
                )}
              </div>

              {/* 21-Checkpoint Audit Table */}
              <StarMeter
                score={currentExp.completeness_score}
                starScores={currentExp.star_scores}
                defaultShowCheckpoints={true}
              />

              {/* Collapsible Reverse-Question Q&A & Raw Notes History */}
              {currentExp.raw_notes?.trim() && (
                <div className="rounded-xl border border-slate-200 bg-white">
                  <button
                    type="button"
                    onClick={() => setShowRawNotes((v) => !v)}
                    className="w-full px-4 py-3 flex items-center justify-between text-xs font-bold text-slate-700 hover:bg-slate-50 rounded-xl"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <MessageSquareText className="w-4 h-4 text-indigo-600" />
                      <span>원본 메모 &amp; 역질문 Q&amp;A 이력 보기</span>
                    </span>
                    {showRawNotes ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>
                  {showRawNotes && (
                    <div className="px-4 pb-4 pt-2 border-t border-slate-100">
                      <pre className="text-[11px] text-slate-600 whitespace-pre-wrap font-sans leading-relaxed max-h-72 overflow-y-auto">
                        {currentExp.raw_notes}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-3.5 border-t border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                {onOpenProjectSync && (
                  <button
                    type="button"
                    onClick={() => onOpenProjectSync(currentExp)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
                  >
                    <FolderSync className="w-3.5 h-3.5" />
                    <span>이 경험·역질문으로 프로젝트 다시 정리하기</span>
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100"
              >
                닫기
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
