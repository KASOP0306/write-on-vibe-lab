import { useState } from "react";
import { ChevronDown, ChevronUp, ShieldAlert } from "lucide-react";

const AXIS_META = [
  { id: "situation", code: "S", label: "상황·맥락", maxPoints: 12 },
  { id: "task", code: "T", label: "과제·책임", maxPoints: 14 },
  { id: "action", code: "A", label: "행동·실행·운영", maxPoints: 36 },
  { id: "result", code: "R", label: "결과·검증", maxPoints: 26 },
  { id: "learning", code: "L", label: "회고·전이", maxPoints: 12 },
];

function getTierBadge(score, gradeProp, labelProp) {
  const s = Number(score) || 0;
  const grade =
    gradeProp || (s >= 85 ? "S" : s >= 70 ? "A" : s >= 50 ? "B" : s >= 30 ? "C" : "D");
  const label =
    labelProp ||
    (grade === "S"
      ? "Bar Raiser"
      : grade === "A"
        ? "Clear Signal"
        : grade === "B"
          ? "Mixed Signal"
          : grade === "C"
            ? "Below Bar"
            : "초안·근거 부족");
  const cls =
    grade === "S"
      ? "bg-emerald-100 text-emerald-800 border-emerald-200"
      : grade === "A"
        ? "bg-indigo-100 text-indigo-800 border-indigo-200"
        : grade === "B"
          ? "bg-amber-100 text-amber-800 border-amber-200"
          : grade === "C"
            ? "bg-orange-100 text-orange-800 border-orange-200"
            : "bg-rose-100 text-rose-800 border-rose-200";
  return { grade, label, cls };
}

export default function StarMeter({
  score = 0,
  missingPoints = [],
  starScores = null,
  compact = false,
  defaultShowCheckpoints = false,
}) {
  const [showCheckpoints, setShowCheckpoints] = useState(defaultShowCheckpoints);
  const axes = starScores?.axes || null;
  const checkpoints = starScores?.checkpoints || null;
  const capEvents = starScores?.cap_events || [];
  const clamped = Math.max(
    0,
    Math.min(100, Number(starScores?.weighted_score ?? score) || 0)
  );
  const tier = getTierBadge(clamped, starScores?.grade, starScores?.tier_label);
  const xp = starScores?.xp;
  const rubricVersion = starScores?.rubric_version || "";
  const passedCount = starScores?.passed_checkpoints ?? 0;
  const partialCount = starScores?.partial_checkpoints ?? 0;
  const totalCheckpoints = starScores?.total_checkpoints ?? (checkpoints ? Object.keys(checkpoints).length : 0);

  const barColor =
    clamped >= 70
      ? "bg-emerald-500"
      : clamped >= 50
        ? "bg-indigo-500"
        : clamped >= 30
          ? "bg-amber-500"
          : "bg-rose-500";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-semibold text-slate-700">
            STAR-L 21지표 하이브리드 점수
          </span>
          {rubricVersion && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono font-semibold text-slate-600">
              {rubricVersion}
            </span>
          )}
          {clamped > 0 && (
            <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${tier.cls}`}>
              {tier.grade}등급 · {tier.label}
            </span>
          )}
          {xp !== undefined && xp > 0 && (
            <span className="rounded-full bg-violet-50 border border-violet-200 px-2 py-0.5 text-[10px] font-bold text-violet-800">
              +{xp} XP
            </span>
          )}
        </div>
        <span className="text-sm font-bold text-slate-900">{clamped} / 100</span>
      </div>

      <div className="h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${barColor}`}
          style={{ width: `${clamped}%` }}
        />
      </div>

      {totalCheckpoints > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
          <div className="flex items-center gap-2">
            <span className="text-emerald-700 font-semibold">✅ 입증 {passedCount}</span>
            <span className="text-amber-700 font-semibold">◐ 부분 {partialCount}</span>
            <span className="text-slate-400">
              ○ 미충족 {Math.max(0, totalCheckpoints - passedCount - partialCount)}
            </span>
          </div>
          {capEvents.length > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded bg-rose-50 border border-rose-200 px-1.5 py-0.5 text-[10px] font-semibold text-rose-700"
              title={capEvents.map((e) => `${e.checkpoint_id}: ${e.reason}`).join(" / ")}
            >
              <ShieldAlert className="w-3 h-3" />
              코드 캡 {capEvents.length}건 적용
            </span>
          )}
        </div>
      )}

      {axes && (
        <div className={compact ? "grid grid-cols-5 gap-1.5 pt-1" : "space-y-2 pt-1"}>
          {AXIS_META.map((m) => {
            const entry = axes[m.id] || {};
            const sc = Math.max(0, Math.min(100, Number(entry.score) || 0));
            const maxPts = entry.max_points ?? m.maxPoints;
            const earned = entry.earned !== undefined ? entry.earned : Math.round((sc / 100) * maxPts);
            const color =
              sc >= 75
                ? "bg-emerald-500"
                : sc >= 50
                  ? "bg-indigo-500"
                  : sc >= 25
                    ? "bg-amber-500"
                    : "bg-rose-500";

            if (compact) {
              return (
                <div
                  key={m.id}
                  title={`${m.code} ${m.label}: ${earned}/${maxPts}점 (${sc}%)${entry.tip ? ` — ${entry.tip}` : ""}`}
                  className="rounded-lg border border-slate-100 bg-slate-50 px-2 py-1.5 text-center"
                >
                  <div className="text-[10px] font-bold text-slate-600">{m.code}</div>
                  <div className="text-xs font-extrabold text-slate-900">
                    {earned}/{maxPts}
                  </div>
                  <div className="mt-1 h-1 w-full rounded-full bg-slate-200 overflow-hidden">
                    <div className={`h-full ${color}`} style={{ width: `${sc}%` }} />
                  </div>
                </div>
              );
            }

            return (
              <div key={m.id} className="space-y-1">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-semibold text-slate-700">
                    <span className="inline-block w-4 text-indigo-700 font-bold">{m.code}</span>
                    {m.label}
                  </span>
                  <span className="font-bold text-slate-800">
                    {earned} / {maxPts}점 <span className="text-slate-400 font-normal">({sc}%)</span>
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
                  <div className={`h-full rounded-full ${color}`} style={{ width: `${sc}%` }} />
                </div>
                {(entry.evidence || entry.tip) && (
                  <div className="text-[11px] text-slate-500 leading-snug">
                    {entry.evidence && <span>{entry.evidence}</span>}
                    {entry.tip && sc < 100 && (
                      <span className="text-amber-700 ml-1.5">→ {entry.tip}</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Expandable 21-Checkpoint Audit Table */}
      {checkpoints && Object.keys(checkpoints).length > 0 && (
        <div className="pt-1 border-t border-slate-100">
          <button
            type="button"
            onClick={() => setShowCheckpoints((v) => !v)}
            className="w-full flex items-center justify-between py-1 text-[11px] font-semibold text-indigo-700 hover:text-indigo-900"
          >
            <span>21개 Atomic 체크포인트 감사 상세 보기 ({passedCount}/{totalCheckpoints} 입증)</span>
            {showCheckpoints ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>

          {showCheckpoints && (
            <div className="mt-2 space-y-2 max-h-80 overflow-y-auto pr-1">
              {AXIS_META.map((ax) => {
                const axisCps = Object.values(checkpoints).filter((c) => c.axis === ax.id);
                if (!axisCps.length) return null;
                return (
                  <div key={ax.id} className="space-y-1">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      {ax.code} · {ax.label}
                    </div>
                    <div className="grid grid-cols-1 gap-1">
                      {axisCps.map((cp) => {
                        const icon =
                          cp.status === 2 ? "✅" : cp.status === 1 ? "◐" : "○";
                        const rowBg =
                          cp.status === 2
                            ? "bg-emerald-50/60 border-emerald-200/70"
                            : cp.status === 1
                              ? "bg-amber-50/50 border-amber-200/70"
                              : "bg-slate-50 border-slate-200/70";
                        return (
                          <div
                            key={cp.id}
                            className={`rounded-lg border px-2.5 py-1.5 text-[11px] space-y-0.5 ${rowBg}`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-slate-800">
                                {icon} <span className="font-mono text-indigo-700">{cp.id}</span> {cp.label}
                              </span>
                              <span className="font-bold text-slate-700 shrink-0">
                                {cp.earned}/{cp.weight}점
                              </span>
                            </div>
                            {cp.quote && (
                              <div className="text-[10px] text-slate-600 truncate" title={cp.quote}>
                                근거: “{cp.quote}”
                              </div>
                            )}
                            {cp.capped_reason && (
                              <div className="text-[10px] font-semibold text-rose-700">
                                ⚠ 코드 검증 컷: {cp.capped_reason}
                              </div>
                            )}
                            {cp.status < 2 && cp.tip && (
                              <div className="text-[10px] text-amber-800">보강: {cp.tip}</div>
                            )}
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
      )}

      {missingPoints.length > 0 && (
        <div className="pt-1 space-y-1">
          <div className="text-[11px] font-medium text-slate-500">
            보완이 필요한 핵심 빈틈:
          </div>
          <div className="flex flex-wrap gap-1.5">
            {missingPoints.map((point, idx) => (
              <span
                key={idx}
                className="rounded-md bg-amber-50 border border-amber-200 px-2 py-0.5 text-[11px] text-amber-800"
              >
                {point}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
