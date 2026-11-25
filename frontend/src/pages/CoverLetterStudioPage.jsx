import { useEffect, useState } from "react";
import {
  AlertCircle,
  BookOpen,
  Check,
  CheckCircle2,
  Compass,
  Copy,
  FolderKanban,
  Layers,
  Loader2,
  Plus,
  Sparkles,
  Target,
  Trash2,
  Wand2,
} from "lucide-react";
import { api } from "../api/client.js";
import StepIndicator from "../components/StepIndicator.jsx";
import { TRACK_SHORT_LABELS, getTrackBadgeClass } from "../utils/projectTracks.js";

export default function CoverLetterStudioPage() {
  const [companies, setCompanies] = useState([]);
  const [projects, setProjects] = useState([]);
  const [experiences, setExperiences] = useState([]);

  const [selectedCompanyId, setSelectedCompanyId] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [question, setQuestion] = useState("");
  const [charLimit, setCharLimit] = useState(800);
  const [extraInstructions, setExtraInstructions] = useState("");

  // Step 1: Question Analysis & Material Recommendation State
  const [recommending, setRecommending] = useState(false);
  const [recommendError, setRecommendError] = useState("");
  const [recommendation, setRecommendation] = useState(null);
  const [selectedProjectIds, setSelectedProjectIds] = useState([]);
  const [selectedExperienceIds, setSelectedExperienceIds] = useState([]);
  const [fusionAngle, setFusionAngle] = useState("");

  // Step 2: Cover Letter Generation SSE State
  const [steps, setSteps] = useState([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState(false);

  // User's own cover letter reference manager
  const [samples, setSamples] = useState([]);
  const [showSampleForm, setShowSampleForm] = useState(false);
  const [sampleForm, setSampleForm] = useState({
    role_category: "백엔드 / AI",
    question_type: "지원동기",
    structure_pattern: "",
    sample_text: "",
  });
  const [savingSample, setSavingSample] = useState(false);

  const loadInitial = async () => {
    try {
      const [comps, smps, projs, exps] = await Promise.all([
        api.listCompanies(),
        api.listSamples(),
        api.listProjects(),
        api.listExperiences(),
      ]);
      setCompanies(comps || []);
      setSamples(smps || []);
      setProjects(projs || []);
      setExperiences(exps || []);
    } catch (err) {
      console.warn(err);
    }
  };

  useEffect(() => {
    loadInitial();
  }, []);

  const handleSelectCompany = (idStr) => {
    setSelectedCompanyId(idStr);
    const found = companies.find((c) => String(c.id) === idStr);
    if (found) {
      setCompanyName(found.company_name);
      if (found.target_role) setTargetRole(found.target_role);
    }
  };

  const toggleProjectId = (pid) => {
    setSelectedProjectIds((prev) =>
      prev.includes(pid) ? prev.filter((id) => id !== pid) : [...prev, pid]
    );
  };

  const toggleExperienceId = (eid) => {
    setSelectedExperienceIds((prev) =>
      prev.includes(eid) ? prev.filter((id) => id !== eid) : [...prev, eid]
    );
  };

  // Step 1: Analyze company's question & recommend 1~2 best projects + STARs
  const handleRecommend = async () => {
    if (!companyName.trim() || !question.trim() || recommending) return;
    setRecommending(true);
    setRecommendError("");
    try {
      const data = await api.recommendCoverLetter({
        company_name: companyName.trim(),
        company_profile_id: selectedCompanyId ? Number(selectedCompanyId) : null,
        target_role: targetRole.trim(),
        question: question.trim(),
        char_limit: Number(charLimit) || 800,
      });
      setRecommendation(data);

      // Auto-select top recommended 1~2 primary projects
      const primaries = (data.recommended_projects || []).filter((p) => p.is_primary);
      const topIds = (primaries.length > 0 ? primaries : (data.recommended_projects || []).slice(0, 2)).map(
        (p) => p.project_id
      );
      setSelectedProjectIds(topIds);

      const recExpIds = (data.recommended_experiences || [])
        .slice(0, 3)
        .map((e) => e.experience_id);
      setSelectedExperienceIds(recExpIds);

      const primaryAngles = (primaries.length > 0 ? primaries : (data.recommended_projects || []).slice(0, 2))
        .map((p) => `[${p.project_name}] ${p.fusion_angle}`)
        .join("\n");
      setFusionAngle(
        [data.overall_strategy, primaryAngles].filter(Boolean).join("\n")
      );
    } catch (err) {
      setRecommendError(err.message);
    } finally {
      setRecommending(false);
    }
  };

  // Step 2: Generate 3-Axis Fused Cover Letter
  const handleGenerate = async (e) => {
    e?.preventDefault();
    if (!companyName.trim() || !question.trim() || running) return;

    setRunning(true);
    setSteps([]);
    setResult(null);
    setCopied(false);

    try {
      await api.generateCoverLetter(
        {
          company_name: companyName.trim(),
          company_profile_id: selectedCompanyId ? Number(selectedCompanyId) : null,
          target_role: targetRole.trim(),
          question: question.trim(),
          char_limit: Number(charLimit) || 800,
          extra_instructions: extraInstructions.trim(),
          selected_project_ids: selectedProjectIds,
          selected_experience_ids: selectedExperienceIds,
          question_analysis: recommendation?.question_analysis || {},
          fusion_angle: fusionAngle.trim(),
        },
        (ev) => {
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
                  let badge;
                  if (ev.node === "critic" && ev.data?.score !== undefined) {
                    badge = `${ev.data.score}점`;
                  } else if (ev.data?.char_count) {
                    badge = `${ev.data.char_count}자`;
                  } else if (
                    ev.node === "multi_source_retriever" &&
                    ev.data?.selected_project_count
                  ) {
                    badge = `선택 프로젝트 ${ev.data.selected_project_count}개`;
                  }
                  next[i] = {
                    ...next[i],
                    node: ev.node,
                    status: "done",
                    badge,
                    message:
                      ev.node === "critic" && ev.data?.feedback
                        ? ev.data.feedback
                        : next[i].message,
                  };
                  break;
                }
              }
              return next;
            });
          } else if (ev.event === "done") {
            setResult(ev.data);
          } else if (ev.event === "error") {
            setSteps((prev) => [
              ...prev,
              { node: "error", status: "error", message: ev.message },
            ]);
          }
        }
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

  const handleCopy = async () => {
    if (!result?.final_text) return;
    await navigator.clipboard.writeText(result.final_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleAddSample = async (e) => {
    e.preventDefault();
    if (!sampleForm.sample_text.trim() || savingSample) return;
    setSavingSample(true);
    try {
      await api.createSample({
        role_category: sampleForm.role_category,
        question_type: sampleForm.question_type,
        structure_pattern: sampleForm.structure_pattern,
        sample_text: sampleForm.sample_text,
      });
      setSampleForm({
        role_category: "백엔드 / AI",
        question_type: "지원동기",
        structure_pattern: "",
        sample_text: "",
      });
      setShowSampleForm(false);
      await loadInitial();
    } catch (err) {
      alert(`레퍼런스 저장 실패: ${err.message}`);
    } finally {
      setSavingSample(false);
    }
  };

  const handleDeleteSample = async (refId) => {
    if (!window.confirm("이 자소서 레퍼런스를 삭제할까요?")) return;
    try {
      await api.deleteSample(refId);
      setSamples((prev) => prev.filter((s) => s.ref_id !== refId));
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const recProjectById = Object.fromEntries(
    (recommendation?.recommended_projects || []).map((p) => [p.project_id, p])
  );
  const recExpById = Object.fromEntries(
    (recommendation?.recommended_experiences || []).map((e) => [e.experience_id, e])
  );
  const qa = recommendation?.question_analysis || null;
  const finalLenWithSpace = (result?.final_text || "").length;
  const finalLenNoSpace = (result?.final_text || "").replace(/\s/g, "").length;

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">
          7. 자소서 공방 v2 (문항 심층 분석 · 소재 추천 · 3축 융합)
        </h2>
        <p className="text-sm text-slate-600 mt-1">
          <strong>1단계</strong>로 기업이 제시한 문항의 숨은 평가 의도를 해부해 내 포트폴리오 중 최적{" "}
          <strong>1~2개 프로젝트 &amp; STAR-L</strong>을 추천받고,{" "}
          <strong>2단계</strong>로 선택한 소재 × 기업 신념 × 나의 신념을 융합해 초안·비평·퇴고·De-AI까지 작성합니다.
        </p>
      </div>

      {/* Step 1 Input Card + Live Progress */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-indigo-700">
              <Target className="w-4 h-4" />
              <span>STEP 1. 기업 정보 &amp; 기업 제공 문항 입력</span>
            </span>
            <span className="text-[11px] text-slate-400">
              등록된 프로젝트 {projects.length}개 · STAR {experiences.length}건 보유
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">
                리서치된 기업 선택 (신념·인재상 자동 연동)
              </span>
              <select
                value={selectedCompanyId}
                onChange={(e) => handleSelectCompany(e.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white"
              >
                <option value="">직접 입력</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.company_name} {c.target_role ? `(${c.target_role})` : ""}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">기업명 *</span>
              <input
                required
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="예: 네이버, 토스, 카카오"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">지원 직무</span>
              <input
                type="text"
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                placeholder="예: AI 에이전트 백엔드, 서비스 기획 PM"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">
                목표 글자 수 (공백 포함): {charLimit}자
              </span>
              <input
                type="number"
                min={200}
                max={3000}
                step={50}
                value={charLimit}
                onChange={(e) => setCharLimit(e.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>

          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">
              기업이 제공한 자기소개서 문항 원문 *
            </span>
            <textarea
              required
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="기업 공고에 나온 자소서 문항을 그대로 붙여넣으세요. (예: 가장 도전적이었던 문제 해결 경험과 그 과정에서 본인이 내린 핵심 의사결정, 그리고 입사 후 기여 방안을 작성해 주세요.)"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          {recommendError && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {recommendError}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <button
              type="button"
              disabled={recommending || !companyName.trim() || !question.trim()}
              onClick={handleRecommend}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {recommending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Compass className="w-4 h-4" />
              )}
              <span>
                {recommending
                  ? "문항 해부 & 프로젝트 매칭 중..."
                  : "1단계: 문항 심층 분석 & 추천 프로젝트 찾기"}
              </span>
            </button>

            <button
              type="button"
              disabled={running || !companyName.trim() || !question.trim()}
              onClick={handleGenerate}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              <Wand2 className="w-3.5 h-3.5" />
              <span>바로 작성하기</span>
            </button>
          </div>
        </div>

        {/* Live Step Indicator */}
        <div>
          <StepIndicator steps={steps} />
        </div>
      </div>

      {/* STEP 2: Question Deconstruction + Project/STAR Recommendation & Manual Picker */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 space-y-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-4">
          <div>
            <div className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-violet-700">
              <FolderKanban className="w-4 h-4" />
              <span>STEP 2. 문항 의도 확인 &amp; 활용할 포트폴리오·STAR-L 선택</span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              선택한 프로젝트의 <strong>전체 섹션 원문</strong>과 <strong>STAR 경험</strong>이 자소서 1급 사실 근거로 직접 주입됩니다.
            </p>
          </div>
          <span className="rounded-full bg-indigo-50 border border-indigo-200 px-3 py-1 text-xs font-semibold text-indigo-700">
            선택됨: 프로젝트 {selectedProjectIds.length}개 · STAR {selectedExperienceIds.length}건
          </span>
        </div>

        {/* Question Analysis Card (if Step 1 ran) */}
        {qa && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-indigo-600 px-2.5 py-0.5 text-xs font-bold text-white">
                  {qa.question_type || "기업 문항 분석"}
                </span>
                <h3 className="text-sm font-bold text-indigo-950">
                  기업 문항 심층 해부 결과
                </h3>
              </div>
              {recommendation?.company_matched ? (
                <span className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2.5 py-0.5">
                  저장된 기업 리서치(이념·인재상) 반영됨
                </span>
              ) : (
                <span className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-0.5">
                  팁: &apos;4. 기업 리서치&apos;에서 기업 리서치를 먼저 하면 신념 매칭이 더 정교해집니다
                </span>
              )}
            </div>

            <p className="text-xs text-slate-800 leading-relaxed bg-white rounded-lg border border-indigo-100 p-3">
              <strong className="text-indigo-900">숨은 평가 의도:</strong> {qa.hidden_intent}
            </p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
              <div className="rounded-lg bg-white border border-indigo-100 p-3 space-y-1.5">
                <div className="font-bold text-slate-900">필수 어필 역량</div>
                <div className="flex flex-wrap gap-1.5">
                  {(qa.core_competencies || []).map((c, i) => (
                    <span
                      key={i}
                      className="rounded-md bg-indigo-50 border border-indigo-200 px-2 py-0.5 text-[11px] font-semibold text-indigo-800"
                    >
                      {c}
                    </span>
                  ))}
                </div>
              </div>

              <div className="rounded-lg bg-white border border-indigo-100 p-3 space-y-1">
                <div className="font-bold text-slate-900">본문 필수 체크포인트</div>
                <ul className="space-y-1 text-[11px] text-slate-700">
                  {(qa.mandatory_checkpoints || []).map((cp, i) => (
                    <li key={i}>• {cp}</li>
                  ))}
                </ul>
              </div>

              <div className="rounded-lg bg-white border border-indigo-100 p-3 space-y-1">
                <div className="font-bold text-slate-900">권장 단락 · 글자수 배분</div>
                <ul className="space-y-1 text-[11px] text-slate-700">
                  {(qa.recommended_structure || []).map((st, i) => (
                    <li key={i}>• {st}</li>
                  ))}
                </ul>
              </div>
            </div>

            {(qa.pitfalls_to_avoid || []).length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-rose-800">
                <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
                <strong>피해야 할 감점 실수:</strong>
                {qa.pitfalls_to_avoid.map((p, i) => (
                  <span
                    key={i}
                    className="rounded-md bg-rose-50 border border-rose-200 px-2 py-0.5"
                  >
                    {p}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Project Material Selector (shows AI recommendations first + all registered projects) */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
              <Layers className="w-4 h-4 text-indigo-600" />
              <span>내 포트폴리오 프로젝트 선택 (1~2개 권장)</span>
            </h4>
            {recommendation && (
              <span className="text-[11px] text-indigo-700 font-medium">
                AI 추천 프로젝트가 자동 체크되었습니다. 원하면 자유롭게 변경하세요.
              </span>
            )}
          </div>

          {projects.length === 0 ? (
            <p className="text-xs text-slate-500 rounded-xl border border-dashed border-slate-200 p-4 text-center">
              등록된 프로젝트가 없습니다. &apos;2. 포트폴리오 &amp; 캐릭터&apos;에서 프로젝트를 먼저 등록하면 여기에서 바로 선택해 자소서에 활용할 수 있습니다.
            </p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[...projects]
                .sort((a, b) => {
                  const ra = recProjectById[a.id];
                  const rb = recProjectById[b.id];
                  if (ra?.is_primary && !rb?.is_primary) return -1;
                  if (!ra?.is_primary && rb?.is_primary) return 1;
                  return (rb?.fit_score || 0) - (ra?.fit_score || 0);
                })
                .map((proj) => {
                  const rec = recProjectById[proj.id];
                  const checked = selectedProjectIds.includes(proj.id);
                  return (
                    <label
                      key={proj.id}
                      className={`block rounded-xl border p-4 cursor-pointer transition-all space-y-2 ${
                        checked
                          ? "border-indigo-500 bg-indigo-50/40 ring-1 ring-indigo-500/30"
                          : "border-slate-200 bg-white hover:border-slate-300"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-start gap-2.5 min-w-0">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleProjectId(proj.id)}
                            className="mt-1 accent-indigo-600"
                          />
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-sm font-bold text-slate-900">
                                {proj.name}
                              </span>
                              {rec?.is_primary && (
                                <span className="rounded-full bg-indigo-600 px-2 py-0.5 text-[10px] font-bold text-white">
                                  AI 최우선 추천 · {rec.fit_score}점
                                </span>
                              )}
                              {!rec?.is_primary && rec && (
                                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700">
                                  적합도 {rec.fit_score}점
                                </span>
                              )}
                            </div>
                            <div className="flex flex-wrap items-center gap-1 mt-1">
                              {(proj.project_types || ["engineering"]).map((t) => (
                                <span
                                  key={t}
                                  className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${getTrackBadgeClass(t)}`}
                                >
                                  {TRACK_SHORT_LABELS[t] || t}
                                </span>
                              ))}
                              <span className="text-[11px] text-slate-500">
                                섹션 {proj.filled_section_count}/{proj.total_section_count} · STAR {proj.experience_count}건
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>

                      {rec ? (
                        <div className="pl-6 space-y-1 text-xs">
                          <p className="text-slate-700">
                            <strong>추천 이유:</strong> {rec.reason}
                          </p>
                          <p className="text-indigo-800 bg-white/80 rounded-lg border border-indigo-100 px-2.5 py-1.5">
                            <strong>기업 신념 × 내 신념 융합 각도:</strong> {rec.fusion_angle}
                          </p>
                        </div>
                      ) : (
                        proj.summary && (
                          <p className="pl-6 text-xs text-slate-500 line-clamp-2">
                            {proj.summary}
                          </p>
                        )
                      )}
                    </label>
                  );
                })}
            </div>
          )}
        </div>

        {/* STAR Experience Selector */}
        {experiences.length > 0 && (
          <div className="space-y-2.5 pt-2 border-t border-slate-100">
            <h4 className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-emerald-600" />
              <span>함께 강조할 STAR-L 경험 선택 (선택 — 미선택 시 선택한 프로젝트의 연결 STAR-L 자동 활용)</span>
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
              {experiences.map((exp) => {
                const rec = recExpById[exp.id];
                const checked = selectedExperienceIds.includes(exp.id);
                return (
                  <label
                    key={exp.id}
                    className={`flex items-start gap-2 rounded-xl border p-3 text-xs cursor-pointer ${
                      checked
                        ? "border-emerald-500 bg-emerald-50/40"
                        : "border-slate-200 hover:border-slate-300"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleExperienceId(exp.id)}
                      className="mt-0.5 accent-emerald-600"
                    />
                    <div className="min-w-0 space-y-0.5">
                      <div className="font-bold text-slate-900 truncate">
                        {exp.title}
                      </div>
                      <div className="flex items-center gap-1.5 text-[10px]">
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-semibold text-slate-700">
                          STAR {exp.completeness_score}점
                        </span>
                        {rec && (
                          <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-bold text-emerald-800">
                            AI 추천
                          </span>
                        )}
                      </div>
                      {rec?.fit_reason && (
                        <p className="text-[11px] text-emerald-800 leading-snug">
                          {rec.fit_reason}
                        </p>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        {/* Fusion Angle & Extra Instructions + Final Generate CTA */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-100">
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">
              기업 신념 × 나의 신념 × 프로젝트 융합 방향 (수정 가능)
            </span>
            <textarea
              rows={3}
              value={fusionAngle}
              onChange={(e) => setFusionAngle(e.target.value)}
              placeholder="1단계 추천을 실행하면 자동 채워집니다. 직접 원하는 스토리 전개 방향을 적으셔도 됩니다."
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">
              추가 강조 요청 / 톤앤매너 지시 (선택)
            </span>
            <textarea
              rows={3}
              value={extraInstructions}
              onChange={(e) => setExtraInstructions(e.target.value)}
              placeholder="예: 첫 문장을 강렬한 문제 의식으로 시작하고, 트레이드오프 근거를 중심으로 서술해 주세요."
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
            />
          </label>
        </div>

        <div className="flex justify-end">
          <button
            type="button"
            disabled={running || !companyName.trim() || !question.trim()}
            onClick={handleGenerate}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-6 py-3 text-sm font-bold text-white hover:bg-slate-800 disabled:opacity-50 shadow-sm"
          >
            {running ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Wand2 className="w-4 h-4" />
            )}
            <span>
              {running
                ? "선택 소재 기반 초안 · 비평 · 퇴고 · De-AI 실행 중..."
                : `2단계: 선택 소재(${selectedProjectIds.length}개 프로젝트)로 자소서 생성`}
            </span>
          </button>
        </div>
      </section>

      {/* Final Output + Question Checkpoints + De-AI Diff Report */}
      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-bold text-slate-900">
                  최종 자소서 (De-AI 완료)
                </h3>
                <span className="rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                  면접관 {result.critic_score}점 · 퇴고 {result.revision_count}회
                </span>
                <span className="text-xs text-slate-500">
                  공백 포함 <strong>{finalLenWithSpace}자</strong> (공백 제외 {finalLenNoSpace}자 / 목표 {charLimit}자)
                </span>
              </div>
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                    <span>복사됨</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>복사</span>
                  </>
                )}
              </button>
            </div>

            {/* Used Projects & STARs Transparency Strip */}
            {((result.used_projects || []).length > 0 ||
              (result.used_experiences || []).length > 0) && (
              <div className="flex flex-wrap items-center gap-1.5 text-[11px] pt-1">
                <span className="font-semibold text-slate-500">반영된 1급 소재:</span>
                {(result.used_projects || []).map((p) => (
                  <span
                    key={`up-${p.id}`}
                    className="rounded-full bg-indigo-50 border border-indigo-200 px-2.5 py-0.5 font-semibold text-indigo-800"
                  >
                    프로젝트: {p.name}
                  </span>
                ))}
                {(result.used_experiences || []).map((e) => (
                  <span
                    key={`ue-${e.id}`}
                    className="rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 font-semibold text-emerald-800"
                  >
                    STAR: {e.title}
                  </span>
                ))}
              </div>
            )}

            <div className="rounded-xl bg-slate-50 p-5 text-sm text-slate-800 leading-7 whitespace-pre-wrap">
              {result.final_text}
            </div>
          </div>

          <div className="space-y-4">
            {/* Question Checkpoint Fulfillment Card */}
            {(result.checkpoint_checks || []).length > 0 && (
              <div className="rounded-2xl border border-emerald-200 bg-white p-5 space-y-3 shadow-sm">
                <h3 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  <span>기업 문항 체크포인트 검증</span>
                </h3>
                <ul className="space-y-1.5 text-xs text-slate-700">
                  {result.checkpoint_checks.map((chk, idx) => (
                    <li
                      key={idx}
                      className={`rounded-lg border p-2 leading-snug ${
                        chk.includes("미흡")
                          ? "bg-amber-50/70 border-amber-200 text-amber-900"
                          : "bg-emerald-50/60 border-emerald-100 text-emerald-900"
                      }`}
                    >
                      {chk}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* De-AI Diff Report */}
            <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm">
              <h3 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
                <Sparkles className="w-4 h-4 text-indigo-600" />
                <span>De-AI 변경 리포트 (Diff Summary)</span>
              </h3>
              <ul className="space-y-2 text-xs text-slate-700">
                {(result.diff_summary || []).length === 0 ? (
                  <li className="text-slate-400">변경 요약 내역이 없습니다.</li>
                ) : (
                  result.diff_summary.map((change, idx) => (
                    <li
                      key={idx}
                      className="rounded-lg bg-indigo-50/60 border border-indigo-100 p-2.5 leading-relaxed"
                    >
                      {change}
                    </li>
                  ))
                )}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* User's Own Jasoseo Reference Manager */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <BookOpen className="w-4 h-4" />
              <span>내 합격 자소서 레퍼런스 ({samples.length})</span>
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              직접 수집한 합격 자소서는 Git에 올라가지 않고 로컬/EC2 DB(doc_type=jasoseo_sample)에만 저장되어 전개 구조·설득 논리 참고용으로 사용됩니다.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowSampleForm((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>레퍼런스 직접 등록</span>
          </button>
        </div>

        {showSampleForm && (
          <form
            onSubmit={handleAddSample}
            className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
              <input
                type="text"
                value={sampleForm.role_category}
                onChange={(e) =>
                  setSampleForm({ ...sampleForm, role_category: e.target.value })
                }
                placeholder="직무군 (예: 백엔드 개발)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
              <input
                required
                type="text"
                value={sampleForm.question_type}
                onChange={(e) =>
                  setSampleForm({ ...sampleForm, question_type: e.target.value })
                }
                placeholder="문항 유형 * (예: 지원동기, 트러블슈팅)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
              <input
                type="text"
                value={sampleForm.structure_pattern}
                onChange={(e) =>
                  setSampleForm({
                    ...sampleForm,
                    structure_pattern: e.target.value,
                  })
                }
                placeholder="전개 구조 메모 (선택)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
            </div>
            <textarea
              required
              rows={4}
              value={sampleForm.sample_text}
              onChange={(e) =>
                setSampleForm({ ...sampleForm, sample_text: e.target.value })
              }
              placeholder="참고할 합격 자소서 본문을 붙여넣어 주세요 (최소 20자)..."
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowSampleForm(false)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={savingSample}
                className="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                {savingSample ? "임베딩 저장 중..." : "벡터 DB에 저장"}
              </button>
            </div>
          </form>
        )}

        {samples.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {samples.map((s) => (
              <div
                key={s.ref_id}
                className="rounded-xl border border-slate-200 p-3.5 space-y-1.5 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="rounded bg-slate-100 px-2 py-0.5 font-semibold text-slate-700">
                      {s.role_category}
                    </span>
                    <span className="rounded bg-blue-50 px-2 py-0.5 font-medium text-blue-800">
                      {s.question_type}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteSample(s.ref_id)}
                    className="text-slate-400 hover:text-red-600"
                    title="삭제"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                <p className="text-slate-600 line-clamp-3 leading-relaxed">
                  {s.sample_text}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
