import { X, BookOpen, ShieldAlert } from "lucide-react";

/**
 * 경량 Pure SVG 다축 레이더 차트 (5축 STAR-L 오각형 / 6축 포트폴리오 캐릭터 육각형 공용)
 * items: [{ id, label, score (0~100), subLabel?, domain?: 'internal'|'external', status?: 'verified'|'partial'|'missing' }]
 */
export default function RadarChart({
  items = [],
  size = 270,
  strokeColor = "#4f46e5",
  fillColor = "rgba(79, 70, 229, 0.18)",
  emptyText = "아직 평가 데이터가 없습니다.",
}) {
  if (!items || items.length < 3) {
    return (
      <div className="flex items-center justify-center h-48 text-xs text-slate-400">
        {emptyText}
      </div>
    );
  }

  const cx = size / 2;
  const cy = size / 2;
  const radius = size * 0.31;
  const count = items.length;
  const levels = [20, 40, 60, 80, 100];

  const polarToXY = (index, ratio) => {
    const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
    return {
      x: cx + Math.cos(angle) * radius * ratio,
      y: cy + Math.sin(angle) * radius * ratio,
    };
  };

  const dataPoints = items.map((item, idx) => {
    const clamped = Math.max(0, Math.min(100, Number(item.score) || 0));
    return polarToXY(idx, clamped / 100);
  });
  const polygonStr = dataPoints.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className="w-full max-w-[300px] mx-auto overflow-visible select-none"
      role="img"
      aria-label="다축 역량 레이더 그래프"
    >
      {/* 동심 다각형 눈금 (20~100) */}
      {levels.map((lvl) => {
        const ring = items
          .map((_, idx) => {
            const p = polarToXY(idx, lvl / 100);
            return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
          })
          .join(" ");
        return (
          <polygon
            key={lvl}
            points={ring}
            fill="none"
            stroke={lvl === 100 ? "#cbd5e1" : "#e2e8f0"}
            strokeWidth={lvl === 100 ? 1.2 : 0.9}
            strokeDasharray={lvl === 60 ? "3 3" : undefined}
          />
        );
      })}

      {/* 방사형 축 선 */}
      {items.map((item, idx) => {
        const end = polarToXY(idx, 1);
        const isExternal = item.domain === "external";
        return (
          <line
            key={`axis-${item.id || idx}`}
            x1={cx}
            y1={cy}
            x2={end.x}
            y2={end.y}
            stroke={isExternal ? "#d8b4fe" : "#cbd5e1"}
            strokeWidth={1}
            strokeDasharray={item.status === "missing" ? "3 2" : undefined}
          />
        );
      })}

      {/* 데이터 면적 폴리곤 */}
      <polygon
        points={polygonStr}
        fill={fillColor}
        stroke={strokeColor}
        strokeWidth={2.2}
        strokeLinejoin="round"
      />

      {/* 데이터 꼭짓점 */}
      {dataPoints.map((pt, idx) => {
        const item = items[idx];
        const isMissing = item.status === "missing";
        const dotColor = isMissing
          ? "#f43f5e"
          : item.domain === "external"
            ? "#7c3aed"
            : strokeColor;
        return (
          <circle
            key={`dot-${item.id || idx}`}
            cx={pt.x}
            cy={pt.y}
            r={isMissing ? 4.2 : 3.6}
            fill={isMissing ? "#fff1f2" : dotColor}
            stroke={dotColor}
            strokeWidth={1.8}
          />
        );
      })}

      {/* 축 라벨 & 점수 */}
      {items.map((item, idx) => {
        const lp = polarToXY(idx, 1.24);
        const score = Math.round(Number(item.score) || 0);
        const anchor =
          Math.abs(lp.x - cx) < 10 ? "middle" : lp.x > cx ? "start" : "end";
        const isMissing = item.status === "missing";
        return (
          <g key={`lbl-${item.id || idx}`}>
            <text
              x={lp.x}
              y={lp.y - 4}
              textAnchor={anchor}
              className="fill-slate-700 text-[10px] font-semibold"
            >
              {item.label}
            </text>
            <text
              x={lp.x}
              y={lp.y + 9}
              textAnchor={anchor}
              className={`text-[10px] font-bold ${
                isMissing
                  ? "fill-rose-600"
                  : item.domain === "external"
                    ? "fill-violet-700"
                    : "fill-indigo-700"
              }`}
            >
              {isMissing ? `${score} (미검증)` : `${score}점`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/**
 * 글로벌 HR 평가 레퍼런스 기준표 모달 (DDI BARS × Amazon Bar Raiser × Google XYZ + KFLA × Spencer)
 */
export function RubricReferenceModal({ open, onClose, reference }) {
  if (!open) return null;

  const starRef = reference?.star_rubric;
  const pfRef = reference?.portfolio_rubric;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-xs">
      <div className="w-full max-w-3xl max-h-[85vh] overflow-y-auto rounded-2xl bg-white shadow-2xl border border-slate-200 p-6 space-y-6">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 pb-4">
          <div>
            <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-700">
              <BookOpen className="w-4 h-4" /> 객관적 평가 기준 레퍼런스
            </div>
            <h3 className="text-lg font-bold text-slate-900 mt-1">
              5축 STAR-L (BARS) &amp; 6축 포트폴리오 캐릭터 평가 기준표
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 1. STAR-L 5축 */}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-bold text-slate-900">
              ① 개별 경험 평가: {starRef?.name || "5축 STAR-L BARS 루브릭"}
            </h4>
            <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] font-semibold text-indigo-700">
              {starRef?.formula || "0.15×S + 0.15×T + 0.35×A + 0.25×R + 0.10×L"}
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {(starRef?.frameworks || []).map((fw) => (
              <div
                key={fw.name}
                className="rounded-xl border border-slate-200 bg-slate-50 p-2.5"
              >
                <div className="text-xs font-bold text-slate-800">{fw.name}</div>
                <div className="text-[11px] text-slate-600 mt-0.5">{fw.role}</div>
              </div>
            ))}
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-3 py-2">축 (가중치)</th>
                  <th className="px-3 py-2">Lv.1 (20점)</th>
                  <th className="px-3 py-2">Lv.3 (60점)</th>
                  <th className="px-3 py-2">Lv.5 (100점)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(starRef?.axes || []).map((ax) => (
                  <tr key={ax.id}>
                    <td className="px-3 py-2 font-semibold text-slate-800 whitespace-nowrap">
                      {ax.code} · {ax.label}
                      <span className="ml-1 text-[10px] text-indigo-600">
                        ({Math.round((ax.weight || 0) * 100)}%)
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-600">{ax.bars?.["1"]}</td>
                    <td className="px-3 py-2 text-slate-600">{ax.bars?.["3"]}</td>
                    <td className="px-3 py-2 text-slate-700 font-medium">{ax.bars?.["5"]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 2. 포트폴리오 6축 */}
        <div className="space-y-3 pt-2 border-t border-slate-100">
          <h4 className="text-sm font-bold text-slate-900">
            ② 전체 포트폴리오 캐릭터 진단: {pfRef?.name || "6축 육각형 (내적 3 × 외적 3)"}
          </h4>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {(pfRef?.frameworks || []).map((fw) => (
              <div
                key={fw.name}
                className="rounded-xl border border-violet-100 bg-violet-50/50 p-2.5"
              >
                <div className="text-xs font-bold text-violet-900">{fw.name}</div>
                <div className="text-[11px] text-slate-600 mt-0.5">{fw.role}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
            {(pfRef?.axes || []).map((ax) => (
              <div
                key={ax.id}
                className={`rounded-xl border p-3 ${
                  ax.domain === "external"
                    ? "border-violet-200 bg-violet-50/30"
                    : "border-indigo-200 bg-indigo-50/30"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-bold text-slate-900">{ax.label}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      ax.domain === "external"
                        ? "bg-violet-100 text-violet-700"
                        : "bg-indigo-100 text-indigo-700"
                    }`}
                  >
                    {ax.domain === "external" ? "외적 역량" : "내적 역량"}
                  </span>
                </div>
                <div className="text-[11px] text-slate-600 mt-1">{ax.description}</div>
                <div className="text-[10px] text-slate-400 mt-1">기준: {ax.reference}</div>
              </div>
            ))}
          </div>

          <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs text-rose-800">
            <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5 text-rose-600" />
            <span>
              <strong>객관성 안전장치:</strong>{" "}
              {pfRef?.honesty_rule ||
                "근거가 없는 외적 축은 추측 채점하지 않고 '근거 부족(사각지대)'으로 표기합니다."}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
