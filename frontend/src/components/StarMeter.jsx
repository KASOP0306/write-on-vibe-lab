export default function StarMeter({ score = 0, missingPoints = [] }) {
  const clamped = Math.max(0, Math.min(100, Number(score) || 0));
  const barColor =
    clamped >= 80
      ? "bg-emerald-500"
      : clamped >= 50
        ? "bg-amber-500"
        : "bg-rose-500";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-2.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-700">
          STAR 경험 완성도 게이지
        </span>
        <span className="text-sm font-bold text-slate-900">{clamped} / 100</span>
      </div>

      <div className="h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${barColor}`}
          style={{ width: `${clamped}%` }}
        />
      </div>

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
