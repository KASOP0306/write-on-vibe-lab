import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  FolderSync,
  MessageSquareText,
  X,
} from "lucide-react";
import StarMeter from "./StarMeter.jsx";

export default function ExperienceDetailModal({
  experience,
  projectName = "",
  onClose,
  onOpenProjectSync = null,
}) {
  const [showRawNotes, setShowRawNotes] = useState(false);

  if (!experience) return null;

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[88vh] flex flex-col shadow-xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-semibold text-slate-700">
                {projectName || (experience.project_id ? `프로젝트 #${experience.project_id}` : "프로젝트 미지정")}
              </span>
              <span className="rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 font-bold text-emerald-800">
                완성도 {experience.completeness_score}점
              </span>
              {experience.star_scores?.grade && (
                <span className="rounded-full bg-indigo-50 border border-indigo-200 px-2.5 py-0.5 font-bold text-indigo-800">
                  {experience.star_scores.grade}등급
                </span>
              )}
              {experience.star_scores?.xp > 0 && (
                <span className="rounded-full bg-violet-50 border border-violet-200 px-2.5 py-0.5 font-bold text-violet-800">
                  +{experience.star_scores.xp} XP
                </span>
              )}
            </div>
            <h3 className="text-lg font-bold text-slate-900">{experience.title}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-5 text-sm">
          {/* Full STAR-L Cards */}
          <div className="space-y-3">
            {[
              { code: "S", title: "Situation (상황 · 맥락)", text: experience.situation, cls: "border-slate-200 bg-slate-50/60" },
              { code: "T", title: "Task (과제 · 책임)", text: experience.task, cls: "border-slate-200 bg-slate-50/60" },
              { code: "A", title: "Action (행동 · 의사결정 · 실행)", text: experience.action, cls: "border-indigo-200/80 bg-indigo-50/30" },
              { code: "R", title: "Result (결과 · 검증)", text: experience.result, cls: "border-emerald-200/80 bg-emerald-50/30" },
              { code: "L", title: "Learning (회고 · 원칙 · 재현성)", text: experience.learning, cls: "border-violet-200/80 bg-violet-50/30" },
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

            {experience.quantified_metrics?.trim() && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 text-xs text-emerald-900">
                <strong className="block mb-0.5">확인된 정량 지표:</strong>
                <span className="whitespace-pre-wrap">{experience.quantified_metrics}</span>
              </div>
            )}
          </div>

          {/* 21-Checkpoint Audit Table */}
          <StarMeter
            score={experience.completeness_score}
            starScores={experience.star_scores}
            defaultShowCheckpoints={true}
          />

          {/* Collapsible Reverse-Question Q&A & Raw Notes History */}
          {experience.raw_notes?.trim() && (
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
                    {experience.raw_notes}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-2">
          <div>
            {onOpenProjectSync && (
              <button
                type="button"
                onClick={() => onOpenProjectSync(experience)}
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
      </div>
    </div>
  );
}
