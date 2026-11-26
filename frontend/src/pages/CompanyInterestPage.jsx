import { useEffect, useState } from "react";
import {
  Building2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Link2,
  Trash2,
} from "lucide-react";
import { api } from "../api/client.js";
import StepIndicator from "../components/StepIndicator.jsx";

const SOURCE_BADGES = {
  user_reference: { label: "직접 입력 URL", cls: "bg-indigo-100 text-indigo-800" },
  google_news: { label: "Google News", cls: "bg-emerald-100 text-emerald-800" },
  news: { label: "뉴스", cls: "bg-teal-100 text-teal-800" },
  hackernews: { label: "Hacker News", cls: "bg-orange-100 text-orange-800" },
  github: { label: "GitHub", cls: "bg-slate-900 text-white" },
  web: { label: "Web", cls: "bg-slate-100 text-slate-700" },
};

export default function CompanyInterestPage() {
  const [companyName, setCompanyName] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [showAdvancedInput, setShowAdvancedInput] = useState(false);
  const [jdText, setJdText] = useState("");
  const [referenceUrlsText, setReferenceUrlsText] = useState("");
  const [companySteps, setCompanySteps] = useState([]);
  const [companyRunning, setCompanyRunning] = useState(false);
  const [latestCompany, setLatestCompany] = useState(null);
  const [companies, setCompanies] = useState([]);

  const loadData = async () => {
    try {
      const comps = await api.listCompanies();
      setCompanies(comps || []);
    } catch (err) {
      console.warn(err);
    }
  };

  useEffect(() => {
    loadData();
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
            let badge;
            if (ev.data?.source_count !== undefined) {
              badge = `출처 ${ev.data.source_count}건`;
            } else if (ev.data?.query_count !== undefined) {
              badge = `쿼리 ${ev.data.query_count}개`;
            } else if (ev.data?.found_count !== undefined) {
              badge = `${ev.data.found_count}건 수집`;
            }
            next[i] = { ...next[i], node: ev.node, status: "done", badge };
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

  const handleResearchCompany = async (e) => {
    e.preventDefault();
    if (!companyName.trim() || companyRunning) return;
    setCompanyRunning(true);
    setCompanySteps([]);
    setLatestCompany(null);

    const referenceUrls = referenceUrlsText
      .split(/\r?\n/)
      .map((u) => u.trim())
      .filter((u) => u.startsWith("http://") || u.startsWith("https://"));

    try {
      await api.researchCompany(
        {
          company_name: companyName.trim(),
          target_role: targetRole.trim(),
          jd_text: jdText.trim(),
          reference_urls: referenceUrls,
        },
        (ev) => {
          updateStepList(setCompanySteps, ev);
          if (ev.event === "done") {
            setLatestCompany(ev.data);
            loadData();
          }
        }
      );
    } catch (err) {
      setCompanySteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: err.message },
      ]);
    } finally {
      setCompanyRunning(false);
    }
  };

  const handleDeleteCompany = async (comp) => {
    const id = comp.id || comp.company_profile_id;
    if (!id) return;
    if (!window.confirm(`'${comp.company_name}' 기업 리서치 기록을 삭제할까요?`)) {
      return;
    }
    try {
      await api.deleteCompany(id);
      setCompanies((prev) => prev.filter((c) => c.id !== id));
      if (latestCompany && (latestCompany.id === id || latestCompany.company_profile_id === id)) {
        setLatestCompany(null);
      }
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const activeCompany = latestCompany || companies[0] || null;
  const alignmentMap = activeCompany?.value_alignment_map || {};
  const triangularMatches = alignmentMap.triangular_matches || [];
  const bottlenecks = alignmentMap.company_bottlenecks || [];
  const researchSources = alignmentMap.sources || [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">4. 기업 리서치</h2>
      </div>

      {/* Section 1: Company Research */}
      <section className="space-y-4">

        <form
          onSubmit={handleResearchCompany}
          className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3 shadow-sm"
        >
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <input
              required
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="목표 기업명 * (예: 토스, 네이버, 당근)"
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
            <input
              type="text"
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              placeholder="지원 직무 (예: Data Engineer, AI Agent)"
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
            <button
              type="submit"
              disabled={companyRunning || !companyName.trim()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {companyRunning ? "멀티소스 리서치 & 매칭 중..." : "기업 리서치 실행"}
            </button>
          </div>

          <button
            type="button"
            onClick={() => setShowAdvancedInput((v) => !v)}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-700 hover:text-indigo-900"
          >
            <Link2 className="w-3.5 h-3.5" />
            <span>
              채용공고(JD) 본문 / 공식 기술 블로그 URL 직접 추가 (정확도 대폭 상승)
            </span>
            {showAdvancedInput ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>

          {showAdvancedInput && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-100">
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-700">
                  채용공고(JD) 본문 붙여넣기 (선택 · 최우선 근거)
                </span>
                <textarea
                  rows={4}
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  placeholder="주요 업무, 자격 요건, 우대 사항을 그대로 붙여넣으면 직무 병목과 매칭 정확도가 크게 올라갑니다."
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
                />
              </label>

              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-700">
                  직접 분석할 참고 URL (선택 · 줄바꿈으로 여러 개 입력)
                </span>
                <textarea
                  rows={4}
                  value={referenceUrlsText}
                  onChange={(e) => setReferenceUrlsText(e.target.value)}
                  placeholder={"https://toss.tech/...\nhttps://toss.im/career/job-detail?..."}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs font-mono"
                />
              </label>
            </div>
          )}
        </form>

        <StepIndicator steps={companySteps} />

        {/* Company Selector Pills */}
        {companies.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {companies.map((c) => {
              const isSelected =
                activeCompany?.id === c.id ||
                activeCompany?.company_profile_id === c.id;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setLatestCompany(c)}
                  className={`rounded-full px-3 py-1 text-xs font-medium border ${
                    isSelected
                      ? "bg-slate-900 text-white border-slate-900"
                      : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  {c.company_name} {c.target_role ? `(${c.target_role})` : ""}
                </button>
              );
            })}
          </div>
        )}

        {activeCompany && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 space-y-5 shadow-sm">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h4 className="text-lg font-bold text-slate-900">
                  {activeCompany.company_name}{" "}
                  {activeCompany.target_role && (
                    <span className="text-sm font-normal text-slate-500">
                      · {activeCompany.target_role}
                    </span>
                  )}
                </h4>
                {alignmentMap.has_jd_input && (
                  <span className="inline-block mt-1 rounded-full bg-indigo-50 border border-indigo-200 px-2.5 py-0.5 text-[11px] font-semibold text-indigo-800">
                    채용공고(JD) 반영됨
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => handleDeleteCompany(activeCompany)}
                className="p-1.5 rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600"
                title="리서치 기록 삭제"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
              <div className="rounded-xl bg-slate-50 p-3.5 space-y-1">
                <div className="font-bold text-slate-800">미션 &amp; 비전</div>
                <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">
                  {activeCompany.mission_vision}
                </p>
              </div>
              <div className="rounded-xl bg-slate-50 p-3.5 space-y-1">
                <div className="font-bold text-slate-800">핵심 가치</div>
                <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">
                  {activeCompany.core_values}
                </p>
              </div>
              <div className="rounded-xl bg-slate-50 p-3.5 space-y-1">
                <div className="font-bold text-slate-800">최근 동향</div>
                <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">
                  {activeCompany.recent_trends}
                </p>
              </div>
            </div>

            {bottlenecks.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  지원 직무 관점 핵심 과제 / 병목
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {bottlenecks.map((b, idx) => (
                    <span
                      key={idx}
                      className="rounded-lg bg-amber-50 border border-amber-200 px-2.5 py-1 text-xs text-amber-900"
                    >
                      {b}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {triangularMatches.length > 0 && (
              <div className="space-y-2.5">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  신념 × 기업 × 프로젝트 3각 매칭표
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {triangularMatches.map((m, idx) => (
                    <div
                      key={idx}
                      className="rounded-xl border border-blue-100 bg-blue-50/40 p-4 space-y-1.5 text-xs"
                    >
                      <div>
                        <span className="font-bold text-blue-900">기업 과제:</span>{" "}
                        <span className="text-slate-800">
                          {m.company_vision_or_issue}
                        </span>
                      </div>
                      <div>
                        <span className="font-bold text-indigo-900">나의 신념:</span>{" "}
                        <span className="text-slate-800">{m.my_belief}</span>
                      </div>
                      <div>
                        <span className="font-bold text-emerald-900">증명 프로젝트:</span>{" "}
                        <span className="text-slate-800">{m.proof_project}</span>
                      </div>
                      <div className="pt-1 text-slate-700 italic">
                        &ldquo;{m.pitch_angle}&rdquo;
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Evidence Sources List */}
            {researchSources.length > 0 && (
              <div className="space-y-2 pt-3 border-t border-slate-100">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  참고한 웹 출처 ({researchSources.length}건)
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                  {researchSources.map((src, i) => {
                    const badge =
                      SOURCE_BADGES[src.source_type] || SOURCE_BADGES.web;
                    return (
                      <a
                        key={i}
                        href={src.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block rounded-xl border border-slate-200 p-3 hover:border-slate-300 hover:bg-slate-50/70 transition-colors text-xs space-y-1"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className="font-bold text-slate-900">
                              [{src.idx || i + 1}]
                            </span>
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${badge.cls}`}
                            >
                              {badge.label}
                            </span>
                            {src.domain && (
                              <span className="text-[11px] text-slate-500 truncate">
                                {src.domain}
                              </span>
                            )}
                          </div>
                          <ExternalLink className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        </div>
                        <div className="font-semibold text-slate-800 line-clamp-1">
                          {src.title}
                        </div>
                        {src.excerpt && (
                          <p className="text-[11px] text-slate-500 line-clamp-2">
                            {src.excerpt}
                          </p>
                        )}
                      </a>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
