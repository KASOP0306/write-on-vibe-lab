const AXIS_META = [
  { id: "situation", code: "S", label: "상황·제약", weight: "15%" },
  { id: "task", code: "T", label: "본인 책임", weight: "15%" },
  { id: "action", code: "A", label: "행동·의사결정", weight: "35%" },
  { id: "result", code: "R", label: "정량·객관 성과", weight: "25%" },
  { id: "learning", code: "L", label: "회고·확장성", weight: "10%" },
];

function getTierBadge(score, gradeProp, labelProp) {
  const s = Number(score) || 0;
  const grade =
    gradeProp || (s >= 90 ? "S" : s >= 80 ? "A" : s >= 65 ? "B" : s >= 45 ? "C" : "D");
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
            : "근거 부족");
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
}) {
  const axes = starScores?.axes || null;
  const clamped = Math.max(
    0,
    Math.min(100, Number(starScores?.weighted_score ?? score) || 0)
  );
  const tier = getTierBadge(clamped, starScores?.grade, starScores?.tier_label);
  const barColor =
    clamped >= 80
      ? "bg-emerald-500"
      : clamped >= 55
        ? "bg-amber-500"
        : "bg-rose-500";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-semibold text-slate-700">
            5축 STAR-L 객관 완성도
          </span>
          {clamped > 0 && (
            <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${tier.cls}`}>
              {tier.grade}등급 · {tier.label}
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

      {axes && (
        <div className={compact ? "grid grid-cols-5 gap-1.5 pt-1" : "space-y-2 pt-1"}>
          {AXIS_META.map((m) => {
            const entry = axes[m.id] || {};
            const sc = Math.max(0, Math.min(100, Number(entry.score) || 0));
            const lvl = entry.level || Math.max(1, Math.round(sc / 20));
            const color =
              sc >= 80
                ? "bg-emerald-500"
                : sc >= 60
                  ? "bg-indigo-500"
                  : sc >= 40
                    ? "bg-amber-500"
                    : "bg-rose-500";

            if (compact) {
              return (
                <div
                  key={m.id}
                  title={`${m.code} ${m.label} (${sc}점, Lv.${lvl})${entry.tip ? ` — 팁: ${entry.tip}` : ""}`}
                  className="rounded-lg border border-slate-100 bg-slate-50 px-2 py-1.5 text-center"
                >
                  <div className="text-[10px] font-bold text-slate-600">{m.code}</div>
                  <div className="text-xs font-extrabold text-slate-900">{sc}</div>
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
                    {m.label}{" "}
                    <span className="text-[10px] text-slate-400">({m.weight})</span>
                  </span>
                  <span className="font-bold text-slate-800">
                    Lv.{lvl} · {sc}점
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
                  <div className={`h-full rounded-full ${color}`} style={{ width: `${sc}%` }} />
                </div>
                {(entry.evidence || entry.tip) && (
                  <div className="text-[11px] text-slate-500 leading-snug">
                    {entry.evidence && <span>{entry.evidence}</span>}
                    {entry.tip && (
                      <span className="text-amber-700 ml-1.5">→ {entry.tip}</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {missingPoints.length > 0 && (
        <div className="pt-1 space-y-1">
          <div className="text-[11px] font-medium text-slate-500">
            보완이 필요한 빈틈:
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
