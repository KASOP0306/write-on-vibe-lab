import { useEffect, useState } from "react";
import { BookmarkPlus, Building2, Check, ExternalLink, Search } from "lucide-react";
import { api } from "../api/client.js";
import StepIndicator from "../components/StepIndicator.jsx";

export default function CompanyInterestPage({ interests }) {
  // Top section: Company Research
  const [companyName, setCompanyName] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [companySteps, setCompanySteps] = useState([]);
  const [companyRunning, setCompanyRunning] = useState(false);
  const [latestCompany, setLatestCompany] = useState(null);
  const [companies, setCompanies] = useState([]);

  // Bottom section: Interest Web Search & Clip
  const [searchKeyword, setSearchKeyword] = useState("");
  const [interestSteps, setInterestSteps] = useState([]);
  const [interestRunning, setInterestRunning] = useState(false);
  const [clipCandidates, setClipCandidates] = useState([]);
  const [savedUrls, setSavedUrls] = useState(new Set());
  const [savedClips, setSavedClips] = useState([]);

  const loadData = async () => {
    try {
      const [comps, clips] = await Promise.all([
        api.listCompanies(),
        api.listInterestClips(),
      ]);
      setCompanies(comps || []);
      setSavedClips(clips || []);
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

  const handleResearchCompany = async (e) => {
    e.preventDefault();
    if (!companyName.trim() || companyRunning) return;
    setCompanyRunning(true);
    setCompanySteps([]);
    setLatestCompany(null);

    try {
      await api.researchCompany(
        { company_name: companyName.trim(), target_role: targetRole.trim() },
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

  const handleSearchInterests = async (e) => {
    e.preventDefault();
    const kw = searchKeyword.trim();
    if (!kw || interestRunning) return;
    setInterestRunning(true);
    setInterestSteps([]);
    setClipCandidates([]);

    try {
      await api.searchInterests({ keyword: kw, max_results: 5 }, (ev) => {
        updateStepList(setInterestSteps, ev);
        if (ev.event === "done") {
          setClipCandidates(ev.data?.clips || []);
        }
      });
    } catch (err) {
      setInterestSteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: err.message },
      ]);
    } finally {
      setInterestRunning(false);
    }
  };

  const handleSaveClip = async (clip) => {
    try {
      await api.saveInterestClip({
        keyword: searchKeyword.trim() || "관심 분야",
        title: clip.title,
        url: clip.url,
        summary: clip.summary,
        key_takeaways: clip.key_takeaways || [],
      });
      setSavedUrls((prev) => new Set([...prev, clip.url || clip.title]));
      await loadData();
    } catch (err) {
      alert(`클립 저장 실패: ${err.message}`);
    }
  };

  const activeCompany = latestCompany || companies[0] || null;
  const triangularMatches =
    activeCompany?.value_alignment_map?.triangular_matches || [];

  return (
    <div className="space-y-10">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">3. 기업 &amp; 관심사</h2>
        <p className="text-sm text-slate-600 mt-1">
          목표 기업의 이념·비전을 리서치해 나의 신념·프로젝트와 3각 매칭하고, 관심 기술 지식을 선별 저장합니다.
        </p>
      </div>

      {/* Section 1: Company Research */}
      <section className="space-y-4">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <Building2 className="w-4 h-4" />
          <span>목표 기업 리서치 &amp; 신념 3각 매칭</span>
        </h3>

        <form
          onSubmit={handleResearchCompany}
          className="rounded-2xl border border-slate-200 bg-white p-5 grid grid-cols-1 md:grid-cols-3 gap-3 shadow-sm"
        >
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
            placeholder="지원 직무 (예: AI Agent Engineer)"
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={companyRunning || !companyName.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {companyRunning ? "리서치 & 3각 매칭 중..." : "기업 리서치 실행"}
          </button>
        </form>

        <StepIndicator steps={companySteps} />

        {/* Company Selector Pills */}
        {companies.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {companies.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setLatestCompany(c)}
                className={`rounded-full px-3 py-1 text-xs font-medium border ${
                  activeCompany?.company_name === c.company_name
                    ? "bg-slate-900 text-white border-slate-900"
                    : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                }`}
              >
                {c.company_name} {c.target_role ? `(${c.target_role})` : ""}
              </button>
            ))}
          </div>
        )}

        {activeCompany && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 space-y-5 shadow-sm">
            <div>
              <h4 className="text-lg font-bold text-slate-900">
                {activeCompany.company_name}{" "}
                {activeCompany.target_role && (
                  <span className="text-sm font-normal text-slate-500">
                    · {activeCompany.target_role}
                  </span>
                )}
              </h4>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
              <div className="rounded-xl bg-slate-50 p-3.5 space-y-1">
                <div className="font-bold text-slate-800">미션 &amp; 비전</div>
                <p className="text-slate-700 leading-relaxed">
                  {activeCompany.mission_vision}
                </p>
              </div>
              <div className="rounded-xl bg-slate-50 p-3.5 space-y-1">
                <div className="font-bold text-slate-800">핵심 가치</div>
                <p className="text-slate-700 leading-relaxed">
                  {activeCompany.core_values}
                </p>
              </div>
              <div className="rounded-xl bg-slate-50 p-3.5 space-y-1">
                <div className="font-bold text-slate-800">최근 동향</div>
                <p className="text-slate-700 leading-relaxed">
                  {activeCompany.recent_trends}
                </p>
              </div>
            </div>

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
          </div>
        )}
      </section>

      {/* Section 2: Interest Research & Clip Saving */}
      <section className="space-y-4 pt-6 border-t border-slate-200">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <Search className="w-4 h-4" />
          <span>관심 분야 트렌드 검색 &amp; 선별 클립 저장</span>
        </h3>

        {interests.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {interests.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setSearchKeyword(item.keyword)}
                className="rounded-full bg-white border border-slate-200 px-3 py-1 text-xs text-slate-700 hover:bg-slate-100"
              >
                #{item.keyword}
              </button>
            ))}
          </div>
        )}

        <form onSubmit={handleSearchInterests} className="flex gap-2">
          <input
            type="text"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            placeholder="검색할 기술/도메인 키워드 입력 (예: Corrective RAG, AWS Bedrock)"
            className="flex-1 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={interestRunning || !searchKeyword.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {interestRunning ? "검색·요약 중..." : "최신 자료 검색"}
          </button>
        </form>

        <StepIndicator steps={interestSteps} />

        {clipCandidates.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {clipCandidates.map((clip, idx) => {
              const key = clip.url || clip.title;
              const isSaved = savedUrls.has(key);
              return (
                <div
                  key={idx}
                  className="rounded-xl border border-slate-200 bg-white p-4 flex flex-col justify-between gap-3 shadow-sm"
                >
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="text-sm font-bold text-slate-900">
                        {clip.title}
                      </h4>
                      {clip.url && (
                        <a
                          href={clip.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-slate-400 hover:text-blue-600 shrink-0"
                        >
                          <ExternalLink className="w-4 h-4" />
                        </a>
                      )}
                    </div>
                    <p className="text-xs text-slate-700 leading-relaxed">
                      {clip.summary}
                    </p>
                    {(clip.key_takeaways || []).length > 0 && (
                      <ul className="list-disc pl-4 text-xs text-slate-600 space-y-0.5">
                        {clip.key_takeaways.map((t, tIdx) => (
                          <li key={tIdx}>{t}</li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <button
                    type="button"
                    disabled={isSaved}
                    onClick={() => handleSaveClip(clip)}
                    className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium ${
                      isSaved
                        ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                        : "bg-slate-900 text-white hover:bg-slate-800"
                    }`}
                  >
                    {isSaved ? (
                      <>
                        <Check className="w-3.5 h-3.5" />
                        <span>벡터 DB에 저장됨</span>
                      </>
                    ) : (
                      <>
                        <BookmarkPlus className="w-3.5 h-3.5" />
                        <span>선별 클립으로 저장</span>
                      </>
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {/* Saved Clips List */}
        {savedClips.length > 0 && (
          <div className="space-y-2 pt-2">
            <div className="text-xs font-semibold text-slate-600">
              저장된 지식 클립 ({savedClips.length})
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {savedClips.map((clip) => (
                <div
                  key={clip.ref_id}
                  className="rounded-xl border border-slate-200 bg-white p-3.5 space-y-1 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="rounded bg-slate-100 px-2 py-0.5 font-medium text-slate-700">
                      #{clip.keyword}
                    </span>
                    {clip.url && (
                      <a
                        href={clip.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue-600 hover:underline inline-flex items-center gap-0.5"
                      >
                        원문 <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                  <div className="font-bold text-slate-900">{clip.title}</div>
                  <p className="text-slate-600 line-clamp-2">{clip.summary}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
