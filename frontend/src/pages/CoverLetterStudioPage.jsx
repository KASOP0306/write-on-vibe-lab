import { useEffect, useState } from "react";
import {
  AlertCircle,
  Archive,
  ArrowUpRight,
  BookHeart,
  BookOpen,
  Check,
  CheckCircle2,
  Compass,
  Copy,
  FolderKanban,
  Layers,
  Loader2,
  Plus,
  Quote,
  Save,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  Wand2,
} from "lucide-react";
import { api } from "../api/client.js";
import StepIndicator from "../components/StepIndicator.jsx";
import { TRACK_SHORT_LABELS, getTrackBadgeClass } from "../utils/projectTracks.js";

const PILLAR_CAT_LABELS = {
  work_principle: "일하는 원칙",
  problem_lens: "문제 정의",
  collaboration: "협업·소통",
  career_direction: "커리어 방향",
};

export default function CoverLetterStudioPage({
  profile: propProfile = null,
  beliefPillars: propPillars = [],
  beliefNotes: propNotes = [],
  onJumpToBeliefs = null,
}) {
  const [companies, setCompanies] = useState([]);
  const [projects, setProjects] = useState([]);
  const [experiences, setExperiences] = useState([]);
  const [profile, setProfile] = useState(propProfile);
  const [beliefPillars, setBeliefPillars] = useState(propPillars);
  const [beliefNotes, setBeliefNotes] = useState(propNotes);

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
  const [selectedBeliefIds, setSelectedBeliefIds] = useState([]);
  const [selectedBeliefNoteIds, setSelectedBeliefNoteIds] = useState([]);
  const [fusionAngle, setFusionAngle] = useState("");

  // Step 2: Cover Letter Generation SSE State + Archive Editor
  const [steps, setSteps] = useState([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [editableText, setEditableText] = useState("");
  const [archiveMemo, setArchiveMemo] = useState("");
  const [activeArchiveId, setActiveArchiveId] = useState(null);
  const [savingArchive, setSavingArchive] = useState(false);
  const [archiveStatus, setArchiveStatus] = useState("");
  const [copied, setCopied] = useState(false);

  // Saved Cover Letter Archive
  const [archivedLetters, setArchivedLetters] = useState([]);
  const [archiveFilter, setArchiveFilter] = useState("");
  const [copiedArchiveId, setCopiedArchiveId] = useState(null);

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

  useEffect(() => {
    if (propProfile) setProfile(propProfile);
  }, [propProfile]);

  useEffect(() => {
    if (propPillars?.length) setBeliefPillars(propPillars);
  }, [propPillars]);

  useEffect(() => {
    if (propNotes?.length) setBeliefNotes(propNotes);
  }, [propNotes]);

  const loadArchive = async () => {
    try {
      const list = await api.listCoverLetters();
      setArchivedLetters(list || []);
    } catch (err) {
      console.warn(err);
    }
  };

  const loadInitial = async () => {
    try {
      const [comps, smps, projs, exps, savedCls, prof, pillars, notes] = await Promise.all([
        api.listCompanies(),
        api.listSamples(),
        api.listProjects(),
        api.listExperiences(),
        api.listCoverLetters().catch(() => []),
        api.getProfile().catch(() => null),
        api.listBeliefPillars().catch(() => []),
        api.listBeliefNotes().catch(() => []),
      ]);
      setCompanies(comps || []);
      setSamples(smps || []);
      setProjects(projs || []);
      setExperiences(exps || []);
      setArchivedLetters(savedCls || []);
      if (prof) setProfile(prof);
      setBeliefPillars(pillars || []);
      setBeliefNotes(notes || []);
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

  const toggleBeliefId = (bid) => {
    setSelectedBeliefIds((prev) =>
      prev.includes(bid) ? prev.filter((id) => id !== bid) : [...prev, bid]
    );
  };

  const toggleBeliefNoteId = (nid) => {
    setSelectedBeliefNoteIds((prev) =>
      prev.includes(nid) ? prev.filter((id) => id !== nid) : [...prev, nid]
    );
  };

  // Step 1: Analyze company's question & recommend best projects + STARs + Belief Pillars + Notes
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

      const primaries = (data.recommended_projects || []).filter((p) => p.is_primary);
      const topIds = (primaries.length > 0 ? primaries : (data.recommended_projects || []).slice(0, 2)).map(
        (p) => p.project_id
      );
      setSelectedProjectIds(topIds);

      const recExpIds = (data.recommended_experiences || [])
        .slice(0, 3)
        .map((e) => e.experience_id);
      setSelectedExperienceIds(recExpIds);

      const recBeliefIds = (data.recommended_belief_pillars || [])
        .slice(0, 2)
        .map((b) => b.belief_id);
      setSelectedBeliefIds(recBeliefIds);

      const recNoteIds = (data.recommended_belief_notes || [])
        .slice(0, 2)
        .map((n) => n.note_id);
      setSelectedBeliefNoteIds(recNoteIds);

      const primaryAngles = (primaries.length > 0 ? primaries : (data.recommended_projects || []).slice(0, 2))
        .map((p) => `[${p.project_name}] ${p.fusion_angle}`)
        .join("\n");
      const beliefBridges = (data.recommended_belief_pillars || [])
        .map((b) => `[신념: ${b.title}] ${b.belief_to_company_bridge}`)
        .join("\n");
      setFusionAngle(
        [data.overall_strategy, beliefBridges, primaryAngles].filter(Boolean).join("\n")
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
          selected_belief_ids: selectedBeliefIds,
          selected_belief_note_ids: selectedBeliefNoteIds,
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
                  } else if (ev.node === "multi_source_retriever") {
                    const pCnt = ev.data?.selected_project_count || 0;
                    const bCnt = ev.data?.selected_belief_count || 0;
                    badge = `프로젝트 ${pCnt} · 신념 ${bCnt}`;
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
            setEditableText(ev.data?.final_text || "");
            setArchiveMemo("");
            setActiveArchiveId(ev.data?.saved_cover_letter_id || null);
            setArchiveStatus(
              ev.data?.saved_cover_letter_id
                ? `보관함에 자동 저장됨 (#${ev.data.saved_cover_letter_id})`
                : ""
            );
            loadArchive();
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
    const text = editableText || result?.final_text || "";
    if (!text) return;
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSaveArchive = async (asNew = false) => {
    const textToSave = (editableText || result?.final_text || "").trim();
    if (!textToSave || savingArchive) return;
    setSavingArchive(true);
    setArchiveStatus("");
    try {
      if (!asNew && activeArchiveId) {
        await api.updateCoverLetter(activeArchiveId, {
          company_name: companyName.trim() || "기업 미지정",
          target_role: targetRole.trim(),
          question: question.trim(),
          final_text: textToSave,
          memo: archiveMemo.trim(),
        });
        setArchiveStatus(`보관함 수정본 저장 완료 (#${activeArchiveId})`);
      } else {
        const created = await api.createCoverLetter({
          company_name: companyName.trim() || "기업 미지정",
          target_role: targetRole.trim(),
          question: question.trim() || "(문항 미입력)",
          char_limit: Number(charLimit) || 800,
          final_text: textToSave,
          critic_score: Number(result?.critic_score || 0),
          revision_count: Number(result?.revision_count || 0),
          used_projects: result?.used_projects || [],
          used_experiences: result?.used_experiences || [],
          used_beliefs: result?.used_beliefs || [],
          diff_summary: result?.diff_summary || [],
          checkpoint_checks: result?.checkpoint_checks || [],
          memo: archiveMemo.trim(),
        });
        setActiveArchiveId(created.id);
        setArchiveStatus(`새 버전으로 보관함 저장 완료 (#${created.id})`);
      }
      await loadArchive();
    } catch (err) {
      setArchiveStatus(`보관함 저장 실패: ${err.message}`);
    } finally {
      setSavingArchive(false);
    }
  };

  const handleLoadArchived = (cl) => {
    setCompanyName(cl.company_name || "");
    setTargetRole(cl.target_role || "");
    setQuestion(cl.question || "");
    setCharLimit(cl.char_limit || 800);
    setActiveArchiveId(cl.id);
    setEditableText(cl.final_text || "");
    setArchiveMemo(cl.memo || "");
    setArchiveStatus(`보관함 #${cl.id} 불러옴`);
    setResult({
      saved_cover_letter_id: cl.id,
      final_text: cl.final_text || "",
      critic_score: cl.critic_score || 0,
      revision_count: cl.revision_count || 0,
      used_projects: cl.used_projects || [],
      used_experiences: cl.used_experiences || [],
      used_beliefs: cl.used_beliefs || [],
      diff_summary: cl.diff_summary || [],
      checkpoint_checks: cl.checkpoint_checks || [],
    });
    window.scrollTo({ top: 380, behavior: "smooth" });
  };

  const handleDeleteArchived = async (id) => {
    if (!window.confirm("이 보관 자소서를 삭제할까요?")) return;
    try {
      await api.deleteCoverLetter(id);
      setArchivedLetters((prev) => prev.filter((item) => item.id !== id));
      if (activeArchiveId === id) {
        setActiveArchiveId(null);
        setArchiveStatus("보관함에서 삭제됨");
      }
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const handleCopyArchived = async (cl) => {
    await navigator.clipboard.writeText(cl.final_text || "");
    setCopiedArchiveId(cl.id);
    setTimeout(() => setCopiedArchiveId(null), 1800);
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
  const recBeliefById = Object.fromEntries(
    (recommendation?.recommended_belief_pillars || []).map((b) => [b.belief_id, b])
  );
  const recNoteById = Object.fromEntries(
    (recommendation?.recommended_belief_notes || []).map((n) => [n.note_id, n])
  );

  const qa = recommendation?.question_analysis || null;
  const finalLenWithSpace = (editableText || result?.final_text || "").length;
  const finalLenNoSpace = (editableText || result?.final_text || "").replace(/\s/g, "").length;
  const filteredArchived = archivedLetters.filter((cl) => {
    const q = archiveFilter.trim().toLowerCase();
    if (!q) return true;
    return (
      (cl.company_name || "").toLowerCase().includes(q) ||
      (cl.target_role || "").toLowerCase().includes(q) ||
      (cl.question || "").toLowerCase().includes(q) ||
      (cl.memo || "").toLowerCase().includes(q)
    );
  });

  const hasAnyBelief =
    beliefPillars.length > 0 ||
    beliefNotes.length > 0 ||
    Boolean((profile?.core_beliefs || "").trim()) ||
    Boolean((profile?.career_vision || "").trim());

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">5. 자소서 공방</h2>
      </div>

      {/* Connected Personal Beliefs Live Status Banner */}
      <div
        className={`rounded-2xl border px-5 py-3.5 flex flex-wrap items-center justify-between gap-3 text-xs ${
          hasAnyBelief
            ? "border-violet-200 bg-violet-50/50 text-violet-950"
            : "border-amber-200 bg-amber-50/70 text-amber-950"
        }`}
      >
        <div className="flex items-start gap-2.5 min-w-0">
          <BookHeart className={`w-4 h-4 mt-0.5 shrink-0 ${hasAnyBelief ? "text-violet-600" : "text-amber-600"}`} />
          <div className="space-y-0.5 min-w-0">
            <div className="font-bold flex flex-wrap items-center gap-2">
              <span>연동된 나의 신념 현황</span>
              <span className="rounded-full bg-white border border-violet-200 px-2 py-0.5 text-[10px] font-bold text-violet-800">
                신념 카드 {beliefPillars.length}개
              </span>
              <span className="rounded-full bg-white border border-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-700">
                회고 저널 {beliefNotes.length}건
              </span>
            </div>
            <p className="text-[11px] opacity-85 line-clamp-1">
              {hasAnyBelief
                ? profile?.career_vision ||
                  beliefPillars[0]?.title ||
                  profile?.core_beliefs ||
                  "등록된 신념 카드와 회고 노트가 1단계 추천과 2단계 생성·퇴고 전 과정에 자동 반영됩니다."
                : "아직 등록된 신념 카드나 커리어 비전이 없습니다. '1. 나의 신념'에서 포트폴리오 기반 신념을 먼저 발굴하면 자소서 차별화가 훨씬 강해집니다."}
            </p>
          </div>
        </div>
        {onJumpToBeliefs && (
          <button
            type="button"
            onClick={onJumpToBeliefs}
            className="inline-flex items-center gap-1 rounded-lg border border-violet-300 bg-white px-3 py-1.5 text-[11px] font-semibold text-violet-800 hover:bg-violet-50 shrink-0"
          >
            <span>1. 나의 신념 편집·발굴</span>
            <ArrowUpRight className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Step 1 Input Card + Live Progress */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-indigo-700">
              <Target className="w-4 h-4" />
              <span>STEP 1. 기업 정보 &amp; 기업 제공 문항 입력</span>
            </span>
            <span className="text-[11px] text-slate-400">
              프로젝트 {projects.length} · STAR {experiences.length} · 신념 카드 {beliefPillars.length}
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
                  ? "문항 해부 & 프로젝트·신념 매칭 중..."
                  : "1단계: 문항 심층 분석 & 추천 프로젝트·신념 찾기"}
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

      {/* STEP 2: Question Deconstruction + Project/STAR/Belief Pickers */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 space-y-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-4">
          <div className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-violet-700">
            <FolderKanban className="w-4 h-4" />
            <span>STEP 2. 소재 및 신념 선택</span>
          </div>
          <span className="rounded-full bg-indigo-50 border border-indigo-200 px-3 py-1 text-xs font-semibold text-indigo-700">
            프로젝트 {selectedProjectIds.length} · STAR {selectedExperienceIds.length} · 신념 {selectedBeliefIds.length + selectedBeliefNoteIds.length}
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

        {/* Belief Pillar & Belief Note Selector (NEW 1st-class axis!) */}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4 text-violet-600" />
              <span>반영할 나의 핵심 신념 카드 선택 (1~2개 권장)</span>
            </h4>
            {beliefPillars.length === 0 && onJumpToBeliefs && (
              <button
                type="button"
                onClick={onJumpToBeliefs}
                className="text-[11px] font-semibold text-violet-700 hover:underline"
              >
                + 1번 탭에서 신념 카드 자동 발굴하기 →
              </button>
            )}
          </div>

          {beliefPillars.length === 0 ? (
            <div className="rounded-xl border border-dashed border-violet-200 bg-violet-50/30 p-4 text-xs text-slate-600">
              등록된 핵심 신념 카드가 없습니다. 현재 프로필 요약(
              {profile?.core_beliefs ? "등록됨" : "미등록"})이 기본으로 사용되며,{" "}
              <strong>1. 나의 신념</strong>에서 신념 카드를 만들면 문항별로 최적 신념을 골라 3단 융합할 수 있습니다.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[...beliefPillars]
                .sort((a, b) => (recBeliefById[b.id] ? 1 : 0) - (recBeliefById[a.id] ? 1 : 0))
                .map((pillar) => {
                  const rec = recBeliefById[pillar.id];
                  const checked = selectedBeliefIds.includes(pillar.id);
                  return (
                    <label
                      key={pillar.id}
                      className={`block rounded-xl border p-3.5 cursor-pointer transition-all space-y-1.5 text-xs ${
                        checked
                          ? "border-violet-500 bg-violet-50/50 ring-1 ring-violet-500/30"
                          : "border-slate-200 bg-white hover:border-slate-300"
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleBeliefId(pillar.id)}
                          className="mt-0.5 accent-violet-600"
                        />
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-bold text-violet-800">
                              {PILLAR_CAT_LABELS[pillar.category] || pillar.category}
                            </span>
                            {rec && (
                              <span className="rounded-full bg-violet-600 px-2 py-0.5 text-[10px] font-bold text-white">
                                AI 문항 추천
                              </span>
                            )}
                            {pillar.proof_status === "proven" && (
                              <span className="rounded bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                                경험 증명됨
                              </span>
                            )}
                          </div>
                          <div className="font-bold text-slate-900 leading-snug">
                            “{pillar.title}”
                          </div>
                          {pillar.tradeoff_rule && (
                            <p className="text-[11px] text-slate-600 line-clamp-2">
                              기준: {pillar.tradeoff_rule}
                            </p>
                          )}
                          {rec && (
                            <div className="rounded-lg bg-white/90 border border-violet-100 px-2.5 py-1.5 text-[11px] text-violet-900 space-y-0.5">
                              <div><strong>추천 사유:</strong> {rec.fit_reason}</div>
                              {rec.belief_to_company_bridge && (
                                <div><strong>기업·행동 연결:</strong> {rec.belief_to_company_bridge}</div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </label>
                  );
                })}
            </div>
          )}

          {/* Optional Belief Notes Picker */}
          {beliefNotes.length > 0 && (
            <div className="space-y-2 pt-1">
              <div className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                <Quote className="w-3.5 h-3.5 text-amber-600" />
                <span>함께 녹일 일상 회고 · 독서/강의 구절 노트 (선택)</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                {beliefNotes.slice(0, 9).map((note) => {
                  const rec = recNoteById[note.id];
                  const checked = selectedBeliefNoteIds.includes(note.id);
                  return (
                    <label
                      key={note.id}
                      className={`flex items-start gap-2 rounded-xl border p-2.5 text-xs cursor-pointer ${
                        checked
                          ? "border-amber-500 bg-amber-50/50"
                          : "border-slate-200 hover:border-slate-300"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleBeliefNoteId(note.id)}
                        className="mt-0.5 accent-amber-600"
                      />
                      <div className="min-w-0 space-y-0.5">
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-slate-900 truncate">
                            {note.source_title || "일상 회고 노트"}
                          </span>
                          {rec && (
                            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-bold text-amber-800 shrink-0">
                              AI 추천
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-slate-600 line-clamp-2">
                          {rec?.fit_reason || note.quote_text || note.my_reflection}
                        </p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Project Material Selector */}
        <div className="space-y-3 pt-2 border-t border-slate-100">
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
              등록된 프로젝트가 없습니다. &apos;2. 포트폴리오&apos;에서 프로젝트를 먼저 등록하면 여기에서 바로 선택해 자소서에 활용할 수 있습니다.
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
                ? "선택 소재·신념 기반 초안 · 비평 · 퇴고 · De-AI 실행 중..."
                : `2단계: 선택 소재(프로젝트 ${selectedProjectIds.length} · 신념 ${selectedBeliefIds.length + selectedBeliefNoteIds.length})로 자소서 생성`}
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

            {/* Used Projects, STARs & Beliefs Transparency Strip */}
            {((result.used_projects || []).length > 0 ||
              (result.used_experiences || []).length > 0 ||
              (result.used_beliefs || []).length > 0) && (
              <div className="flex flex-wrap items-center gap-1.5 text-[11px] pt-1">
                <span className="font-semibold text-slate-500">반영된 1급 소재:</span>
                {(result.used_beliefs || []).map((b, bIdx) => (
                  <span
                    key={`ub-${b.kind}-${b.id}-${bIdx}`}
                    className={`rounded-full border px-2.5 py-0.5 font-semibold ${
                      b.kind === "pillar"
                        ? "bg-violet-50 border-violet-200 text-violet-800"
                        : "bg-amber-50 border-amber-200 text-amber-800"
                    }`}
                  >
                    {b.kind === "pillar" ? "신념" : "회고"}: {b.title}
                  </span>
                ))}
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

            <textarea
              rows={13}
              value={editableText}
              onChange={(e) => setEditableText(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50/70 p-4 text-sm text-slate-800 leading-7 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />

            <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-100">
              <input
                type="text"
                value={archiveMemo}
                onChange={(e) => setArchiveMemo(e.target.value)}
                placeholder="보관함 메모 (예: 최종 제출본 / 2차 수정 / 상반기 공채용)"
                className="flex-1 min-w-[200px] rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
              />
              <button
                type="button"
                disabled={savingArchive}
                onClick={() => handleSaveArchive(false)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                <span>
                  {savingArchive
                    ? "저장 중..."
                    : activeArchiveId
                    ? "수정본 저장"
                    : "보관함에 저장"}
                </span>
              </button>
              {activeArchiveId && (
                <button
                  type="button"
                  disabled={savingArchive}
                  onClick={() => handleSaveArchive(true)}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>새 버전으로 보관</span>
                </button>
              )}
            </div>
            {archiveStatus && (
              <div className="text-xs font-medium text-emerald-700">
                {archiveStatus}
              </div>
            )}
          </div>

          <div className="space-y-4">
            {/* Question & Belief Checkpoint Fulfillment Card */}
            {(result.checkpoint_checks || []).length > 0 && (
              <div className="rounded-2xl border border-emerald-200 bg-white p-5 space-y-3 shadow-sm">
                <h3 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  <span>문항 · 신념 연결 체크포인트 검증</span>
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

      {/* Saved Cover Letter Archive */}
      <section className="rounded-2xl border border-indigo-200/80 bg-white p-6 space-y-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Archive className="w-4 h-4 text-indigo-600" />
            <span>자소서 보관함 · {archivedLetters.length}</span>
          </h3>
          <input
            type="text"
            value={archiveFilter}
            onChange={(e) => setArchiveFilter(e.target.value)}
            placeholder="기업명·직무·문항 검색..."
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs w-60"
          />
        </div>

        {filteredArchived.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-6 text-center text-xs text-slate-400">
            {archivedLetters.length === 0
              ? "아직 보관된 자소서가 없습니다. 위에서 자소서를 생성하면 자동으로 보관됩니다."
              : "검색 조건에 맞는 보관 자소서가 없습니다."}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {filteredArchived.map((cl) => {
              const isCurrent = activeArchiveId === cl.id;
              return (
                <div
                  key={cl.id}
                  className={`rounded-xl border p-4 space-y-2 text-xs transition-colors ${
                    isCurrent
                      ? "border-indigo-400 bg-indigo-50/30"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-bold text-slate-900">
                          {cl.company_name}
                        </span>
                        {cl.target_role && (
                          <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                            {cl.target_role}
                          </span>
                        )}
                        <span className="rounded bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                          {cl.critic_score}점 · {(cl.final_text || "").length}자
                        </span>
                      </div>
                      <p className="font-medium text-slate-700 line-clamp-1">
                        Q. {cl.question}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDeleteArchived(cl.id)}
                      className="text-slate-400 hover:text-rose-600 shrink-0"
                      title="보관함에서 삭제"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  {(cl.used_beliefs || []).length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {cl.used_beliefs.slice(0, 3).map((b, bi) => (
                        <span
                          key={bi}
                          className="rounded bg-violet-50 border border-violet-200 px-1.5 py-0.5 text-[10px] font-medium text-violet-800 truncate max-w-[200px]"
                        >
                          신념: {b.title}
                        </span>
                      ))}
                    </div>
                  )}

                  {cl.memo && (
                    <div className="rounded-md bg-amber-50 border border-amber-200/70 px-2 py-1 text-[11px] text-amber-900">
                      메모: {cl.memo}
                    </div>
                  )}

                  <p className="text-slate-600 line-clamp-3 leading-relaxed">
                    {cl.final_text}
                  </p>

                  <div className="flex items-center justify-between pt-1 border-t border-slate-100 text-[11px]">
                    <span className="text-slate-400">
                      {cl.updated_at
                        ? new Date(cl.updated_at).toLocaleString("ko-KR", {
                            month: "2-digit",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : ""}
                    </span>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => handleCopyArchived(cl)}
                        className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-slate-600 hover:bg-slate-50"
                      >
                        {copiedArchiveId === cl.id ? (
                          <>
                            <Check className="w-3 h-3 text-emerald-600" />
                            <span>복사됨</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3 h-3" />
                            <span>복사</span>
                          </>
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleLoadArchived(cl)}
                        className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 font-semibold text-white hover:bg-indigo-700"
                      >
                        <span>불러오기 · 편집</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* User's Own Jasoseo Reference Manager */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <BookOpen className="w-4 h-4" />
            <span>자소서 레퍼런스 · {samples.length}</span>
          </h3>
          <button
            type="button"
            onClick={() => setShowSampleForm((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>레퍼런스 등록</span>
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
