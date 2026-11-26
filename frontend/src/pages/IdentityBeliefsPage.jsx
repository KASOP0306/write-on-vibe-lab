import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  AlertTriangle,
  ArrowUpRight,
  BookHeart,
  BookOpen,
  Check,
  CheckCircle2,
  Compass,
  FolderKanban,
  GraduationCap,
  Lightbulb,
  Link2,
  Loader2,
  Newspaper,
  Pencil,
  Plus,
  Quote,
  RefreshCw,
  Save,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { api } from "../api/client.js";

const SOURCE_TYPES = [
  { id: "thought", label: "일상 회고", icon: Lightbulb, badge: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  { id: "book", label: "책 · 독서", icon: BookOpen, badge: "bg-amber-50 text-amber-800 border-amber-200" },
  { id: "lecture", label: "강의 · 세미나", icon: GraduationCap, badge: "bg-indigo-50 text-indigo-800 border-indigo-200" },
  { id: "article", label: "아티클 · 영상", icon: Newspaper, badge: "bg-sky-50 text-sky-800 border-sky-200" },
];

const SOURCE_MAP = Object.fromEntries(SOURCE_TYPES.map((s) => [s.id, s]));

const PILLAR_CATEGORIES = [
  { id: "work_principle", label: "일하는 원칙", cls: "bg-indigo-50 text-indigo-800 border-indigo-200" },
  { id: "problem_lens", label: "문제 정의 관점", cls: "bg-violet-50 text-violet-800 border-violet-200" },
  { id: "collaboration", label: "협업 · 소통 철학", cls: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  { id: "career_direction", label: "커리어 방향성", cls: "bg-amber-50 text-amber-800 border-amber-200" },
];

const PILLAR_CAT_MAP = Object.fromEntries(PILLAR_CATEGORIES.map((c) => [c.id, c]));

const PROOF_STATUS_BADGES = {
  proven: {
    label: "경험 증명됨",
    cls: "bg-emerald-50 text-emerald-800 border-emerald-200",
    icon: CheckCircle2,
  },
  needs_proof: {
    label: "증명 경험 미연결",
    cls: "bg-amber-50 text-amber-800 border-amber-200",
    icon: AlertTriangle,
  },
  needs_tradeoff: {
    label: "트레이드오프 보강 권장",
    cls: "bg-sky-50 text-sky-800 border-sky-200",
    icon: Compass,
  },
  cliche_risk: {
    label: "클리셰 주의",
    cls: "bg-rose-50 text-rose-800 border-rose-200",
    icon: AlertTriangle,
  },
};

const EMPTY_PILLAR = {
  title: "",
  category: "work_principle",
  tradeoff_rule: "",
  origin_story: "",
  linked_project_ids: [],
  linked_experience_ids: [],
  linked_note_ids: [],
};

const EMPTY_NOTE = {
  source_type: "thought",
  source_title: "",
  quote_text: "",
  my_reflection: "",
  tags_text: "",
};

export default function IdentityBeliefsPage({
  profile,
  pillars = [],
  notes = [],
  projects = [],
  experiences = [],
  onRefresh,
  onJumpToCopilot,
}) {
  // Core Identity Profile Form
  const [profileForm, setProfileForm] = useState({
    career_vision: "",
    core_beliefs: "",
    target_roles: "",
    preferred_tone: "",
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileStatus, setProfileStatus] = useState("");
  const [syncingPillars, setSyncingPillars] = useState(false);

  // Belief Pillars CRUD & AI Discovery / Sharpen
  const [showPillarForm, setShowPillarForm] = useState(false);
  const [editingPillarId, setEditingPillarId] = useState(null);
  const [pillarForm, setPillarForm] = useState(EMPTY_PILLAR);
  const [savingPillar, setSavingPillar] = useState(false);

  const [discovering, setDiscovering] = useState(false);
  const [discovery, setDiscovery] = useState(null);
  const [adoptingIdx, setAdoptingIdx] = useState(null);

  const [sharpeningId, setSharpeningId] = useState(null);
  const [sharpenHints, setSharpenHints] = useState({});
  const [sharpenResults, setSharpenResults] = useState({});

  // AI Identity Synthesis from Notes + Pillars
  const [synthesizing, setSynthesizing] = useState(false);
  const [synthesis, setSynthesis] = useState(null);

  // Thought & Quote Journal
  const [filterType, setFilterType] = useState("all");
  const [showNoteForm, setShowNoteForm] = useState(false);
  const [editingNoteId, setEditingNoteId] = useState(null);
  const [noteForm, setNoteForm] = useState(EMPTY_NOTE);
  const [savingNote, setSavingNote] = useState(false);
  const [reflectingId, setReflectingId] = useState(null);

  useEffect(() => {
    if (profile) {
      setProfileForm({
        career_vision: profile.career_vision || "",
        core_beliefs: profile.core_beliefs || "",
        target_roles: profile.target_roles || "",
        preferred_tone: profile.preferred_tone || "",
      });
    }
  }, [profile]);

  const projectById = Object.fromEntries(projects.map((p) => [p.id, p]));
  const expById = Object.fromEntries(experiences.map((e) => [e.id, e]));

  const toggleIdInForm = (field, id) => {
    setPillarForm((prev) => {
      const cur = prev[field] || [];
      return {
        ...prev,
        [field]: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
      };
    });
  };

  const openNewPillar = (prefill = null) => {
    setEditingPillarId(null);
    setPillarForm(prefill ? { ...EMPTY_PILLAR, ...prefill } : EMPTY_PILLAR);
    setShowPillarForm(true);
    window.scrollTo({ top: 120, behavior: "smooth" });
  };

  const openEditPillar = (pillar) => {
    setEditingPillarId(pillar.id);
    setPillarForm({
      title: pillar.title || "",
      category: pillar.category || "work_principle",
      tradeoff_rule: pillar.tradeoff_rule || "",
      origin_story: pillar.origin_story || "",
      linked_project_ids: pillar.linked_project_ids || [],
      linked_experience_ids: pillar.linked_experience_ids || [],
      linked_note_ids: pillar.linked_note_ids || [],
    });
    setShowPillarForm(true);
  };

  const handleSavePillar = async (e) => {
    e.preventDefault();
    if (!pillarForm.title.trim() || savingPillar) return;
    setSavingPillar(true);
    try {
      const payload = {
        title: pillarForm.title.trim(),
        category: pillarForm.category,
        tradeoff_rule: pillarForm.tradeoff_rule.trim(),
        origin_story: pillarForm.origin_story.trim(),
        linked_project_ids: pillarForm.linked_project_ids || [],
        linked_experience_ids: pillarForm.linked_experience_ids || [],
        linked_note_ids: pillarForm.linked_note_ids || [],
      };
      if (editingPillarId) {
        await api.updateBeliefPillar(editingPillarId, payload);
      } else {
        await api.createBeliefPillar(payload);
      }
      setShowPillarForm(false);
      setEditingPillarId(null);
      setPillarForm(EMPTY_PILLAR);
      await onRefresh();
    } catch (err) {
      alert(`신념 카드 저장 실패: ${err.message}`);
    } finally {
      setSavingPillar(false);
    }
  };

  const handleDeletePillar = async (pillar) => {
    if (!window.confirm(`'${pillar.title}' 신념 카드를 삭제할까요?`)) return;
    try {
      await api.deleteBeliefPillar(pillar.id);
      await onRefresh();
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const handleDiscoverFromPortfolio = async () => {
    if (discovering) return;
    setDiscovering(true);
    setDiscovery(null);
    try {
      const res = await api.discoverBeliefsFromPortfolio();
      setDiscovery(res);
    } catch (err) {
      alert(`포트폴리오 기반 신념 역추출 실패: ${err.message}`);
    } finally {
      setDiscovering(false);
    }
  };

  const handleAdoptCandidate = async (cand, idx) => {
    if (adoptingIdx !== null) return;
    setAdoptingIdx(idx);
    try {
      await api.createBeliefPillar({
        title: cand.title,
        category: cand.category || "work_principle",
        tradeoff_rule: cand.tradeoff_rule || "",
        origin_story: cand.origin_story || "",
        linked_project_ids: cand.linked_project_ids || [],
        linked_experience_ids: cand.linked_experience_ids || [],
        linked_note_ids: cand.linked_note_ids || [],
      });
      setDiscovery((prev) =>
        prev
          ? {
              ...prev,
              candidates: prev.candidates.filter((_, i) => i !== idx),
            }
          : null
      );
      await onRefresh();
    } catch (err) {
      alert(`신념 카드 채택 실패: ${err.message}`);
    } finally {
      setAdoptingIdx(null);
    }
  };

  const handleSharpenPillar = async (pillarId) => {
    if (sharpeningId) return;
    setSharpeningId(pillarId);
    try {
      const res = await api.sharpenBeliefPillar(pillarId, sharpenHints[pillarId] || "");
      setSharpenResults((prev) => ({ ...prev, [pillarId]: res }));
    } catch (err) {
      alert(`신념 다듬기 실패: ${err.message}`);
    } finally {
      setSharpeningId(null);
    }
  };

  const handleApplySharpen = async (pillar) => {
    const res = sharpenResults[pillar.id];
    if (!res) return;
    try {
      await api.updateBeliefPillar(pillar.id, {
        title: res.sharpened_title || pillar.title,
        tradeoff_rule: res.sharpened_tradeoff_rule || pillar.tradeoff_rule,
        origin_story: res.sharpened_origin_story || pillar.origin_story,
      });
      setSharpenResults((prev) => {
        const next = { ...prev };
        delete next[pillar.id];
        return next;
      });
      await onRefresh();
    } catch (err) {
      alert(`적용 실패: ${err.message}`);
    }
  };

  const handleSyncPillarsToProfile = async () => {
    if (syncingPillars || pillars.length === 0) return;
    setSyncingPillars(true);
    try {
      const res = await api.syncPillarsToProfile();
      setProfileForm((prev) => ({ ...prev, core_beliefs: res.core_beliefs }));
      setProfileStatus(`신념 카드 ${res.pillar_count}개가 프로필 핵심 신념 요약에 동기화되었습니다.`);
      await onRefresh();
    } catch (err) {
      alert(`동기화 실패: ${err.message}`);
    } finally {
      setSyncingPillars(false);
    }
  };

  const handleSaveProfile = async (e) => {
    e?.preventDefault();
    setSavingProfile(true);
    setProfileStatus("");
    try {
      const updated = await api.updateProfile(profileForm);
      setProfileStatus(
        updated.vector_synced
          ? "저장 및 career_identity 벡터 동기화 완료"
          : "저장 완료 (벡터 동기화 대기)"
      );
      await onRefresh();
    } catch (err) {
      setProfileStatus(`저장 실패: ${err.message}`);
    } finally {
      setSavingProfile(false);
    }
  };

  const handleSynthesizeIdentity = async () => {
    if (synthesizing) return;
    setSynthesizing(true);
    setSynthesis(null);
    try {
      const res = await api.synthesizeIdentityFromNotes();
      setSynthesis(res);
    } catch (err) {
      alert(`신념 정제 실패: ${err.message}`);
    } finally {
      setSynthesizing(false);
    }
  };

  const handleApplySynthesis = () => {
    if (!synthesis) return;
    setProfileForm((prev) => ({
      ...prev,
      career_vision: synthesis.suggested_career_vision || prev.career_vision,
      core_beliefs: synthesis.suggested_core_beliefs || prev.core_beliefs,
    }));
    setSynthesis(null);
    setProfileStatus("정제안이 입력칸에 반영되었습니다. '프로필 저장'을 눌러 확정해 주세요.");
  };

  const openNewNote = (defaultType = "thought") => {
    setEditingNoteId(null);
    setNoteForm({ ...EMPTY_NOTE, source_type: defaultType });
    setShowNoteForm(true);
  };

  const openEditNote = (note) => {
    setEditingNoteId(note.id);
    setNoteForm({
      source_type: note.source_type || "thought",
      source_title: note.source_title || "",
      quote_text: note.quote_text || "",
      my_reflection: note.my_reflection || "",
      tags_text: (note.tags || []).join(", "),
    });
    setShowNoteForm(true);
  };

  const handlePromoteNoteToPillar = (note) => {
    openNewPillar({
      title: note.source_title ? `${note.source_title}에서 정립한 원칙` : "",
      category: "work_principle",
      tradeoff_rule: "",
      origin_story: [note.quote_text ? `"${note.quote_text}"` : "", note.my_reflection]
        .filter(Boolean)
        .join("\n"),
      linked_note_ids: [note.id],
    });
  };

  const handleSaveNote = async (e) => {
    e.preventDefault();
    if (!noteForm.my_reflection.trim() || savingNote) return;
    setSavingNote(true);
    try {
      const payload = {
        source_type: noteForm.source_type,
        source_title: noteForm.source_title.trim(),
        quote_text: noteForm.quote_text.trim(),
        my_reflection: noteForm.my_reflection.trim(),
        tags: noteForm.tags_text
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };
      if (editingNoteId) {
        await api.updateBeliefNote(editingNoteId, payload);
      } else {
        await api.createBeliefNote(payload);
      }
      setShowNoteForm(false);
      setEditingNoteId(null);
      setNoteForm(EMPTY_NOTE);
      await onRefresh();
    } catch (err) {
      alert(`노트 저장 실패: ${err.message}`);
    } finally {
      setSavingNote(false);
    }
  };

  const handleDeleteNote = async (note) => {
    if (!window.confirm("이 구절·생각 노트를 삭제할까요?")) return;
    try {
      await api.deleteBeliefNote(note.id);
      await onRefresh();
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const handleReflectNote = async (noteId) => {
    if (reflectingId) return;
    setReflectingId(noteId);
    try {
      await api.reflectBeliefNote(noteId);
      await onRefresh();
    } catch (err) {
      alert(`AI 생각 심화 회고 실패: ${err.message}`);
    } finally {
      setReflectingId(null);
    }
  };

  const filteredNotes =
    filterType === "all"
      ? notes
      : notes.filter((n) => n.source_type === filterType);

  const provenCount = pillars.filter((p) => p.proof_status === "proven").length;

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <BookHeart className="w-6 h-6 text-indigo-600" />
          <span>1. 나의 신념</span>
        </h2>
      </div>

      {/* SECTION 1: Structured Core Belief Pillars Board */}
      <section className="rounded-2xl border border-indigo-200 bg-white p-6 space-y-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-600" />
            <h3 className="text-base font-bold text-slate-900">
              핵심 신념 카드 · {pillars.length}
            </h3>
            {pillars.length > 0 && (
              <span className="rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 text-[11px] font-bold text-emerald-800">
                증명됨 {provenCount}/{pillars.length}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={discovering}
              onClick={handleDiscoverFromPortfolio}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 shadow-xs"
            >
              {discovering ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Sparkles className="w-3.5 h-3.5" />
              )}
              <span>
                {discovering
                  ? "행동 패턴 분석 중..."
                  : "프로젝트·경험에서 신념 발굴"}
              </span>
            </button>

            <button
              type="button"
              onClick={() => openNewPillar()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>신념 추가</span>
            </button>
          </div>
        </div>

        {/* AI Discovery Candidates Panel */}
        {discovery && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4 space-y-3">
            <div className="flex items-start justify-between gap-2">
              <div className="space-y-0.5">
                <div className="text-xs font-bold text-indigo-950 flex items-center gap-1.5">
                  <Sparkles className="w-4 h-4 text-indigo-600" />
                  <span>
                    포트폴리오·STAR·회고 기반 신념 후보 ({discovery.candidates?.length || 0}건)
                  </span>
                </div>
                <p className="text-xs text-slate-700 leading-relaxed">
                  {discovery.overall_observation}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setDiscovery(null)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {(discovery.candidates || []).length === 0 ? (
              <p className="text-xs text-emerald-700 font-semibold">
                제안된 후보를 모두 채택했습니다!
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {discovery.candidates.map((cand, idx) => {
                  const catMeta = PILLAR_CAT_MAP[cand.category] || PILLAR_CATEGORIES[0];
                  return (
                    <div
                      key={idx}
                      className="rounded-xl bg-white border border-indigo-100 p-4 space-y-2.5 flex flex-col justify-between"
                    >
                      <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${catMeta.cls}`}>
                            {catMeta.label}
                          </span>
                          <span className="text-[10px] font-bold text-emerald-700">
                            실전성 {cand.strength_score || 0}점 · 증명 {cand.proof_count || 0}건 연결
                          </span>
                        </div>
                        <div className="text-sm font-bold text-slate-900 leading-snug">
                          “{cand.title}”
                        </div>
                        {cand.tradeoff_rule && (
                          <div className="rounded-lg bg-slate-50 border border-slate-200 px-2.5 py-1.5 text-[11px] text-slate-700">
                            <strong>트레이드오프 기준:</strong> {cand.tradeoff_rule}
                          </div>
                        )}
                        {cand.origin_story && (
                          <p className="text-[11px] text-slate-600 leading-relaxed">
                            {cand.origin_story}
                          </p>
                        )}
                        <div className="flex flex-wrap gap-1">
                          {(cand.linked_project_ids || []).map((pid) => (
                            <span
                              key={`cp-${pid}`}
                              className="rounded bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-800"
                            >
                              프로젝트: {projectById[pid]?.name || `#${pid}`}
                            </span>
                          ))}
                          {(cand.linked_experience_ids || []).map((eid) => (
                            <span
                              key={`ce-${eid}`}
                              className="rounded bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800"
                            >
                              STAR: {expById[eid]?.title || `#${eid}`}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="flex justify-end pt-2 border-t border-slate-100">
                        <button
                          type="button"
                          disabled={adoptingIdx !== null}
                          onClick={() => handleAdoptCandidate(cand, idx)}
                          className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {adoptingIdx === idx ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Check className="w-3.5 h-3.5" />
                          )}
                          <span>신념 카드로 채택</span>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Create / Edit Pillar Form */}
        {showPillarForm && (
          <form
            onSubmit={handleSavePillar}
            className="rounded-xl border border-indigo-200 bg-slate-50/70 p-5 space-y-4 text-xs"
          >
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-bold text-slate-900">
                {editingPillarId ? "핵심 신념 카드 수정" : "새 핵심 신념 카드 만들기"}
              </h4>
              <button
                type="button"
                onClick={() => setShowPillarForm(false)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {PILLAR_CATEGORIES.map((cat) => (
                <button
                  key={cat.id}
                  type="button"
                  onClick={() => setPillarForm((p) => ({ ...p, category: cat.id }))}
                  className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${
                    pillarForm.category === cat.id
                      ? "border-indigo-600 bg-indigo-600 text-white"
                      : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {cat.label}
                </button>
              ))}
            </div>

            <label className="block space-y-1">
              <span className="font-semibold text-slate-700">핵심 신념 한 줄 선언 *</span>
              <input
                type="text"
                required
                value={pillarForm.title}
                onChange={(e) => setPillarForm((p) => ({ ...p, title: e.target.value }))}
                placeholder="예: 감에 의존하는 최적화보다 측정 가능한 작은 검증 루프를 먼저 만든다"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
              />
            </label>

            <label className="block space-y-1">
              <span className="font-semibold text-slate-700">
                트레이드오프 판단 기준 (A vs B 충돌 시 나는 무엇을 우선하는가?)
              </span>
              <textarea
                rows={2}
                value={pillarForm.tradeoff_rule}
                onChange={(e) => setPillarForm((p) => ({ ...p, tradeoff_rule: e.target.value }))}
                placeholder="예: 기능 출시 속도와 평가 신뢰성이 충돌할 때, 근거 없는 숫자 대신 결정론적 검증 게이트를 먼저 세워 신뢰를 확보한다."
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
            </label>

            <label className="block space-y-1">
              <span className="font-semibold text-slate-700">형성 계기 · 배경 스토리 (선택)</span>
              <textarea
                rows={2}
                value={pillarForm.origin_story}
                onChange={(e) => setPillarForm((p) => ({ ...p, origin_story: e.target.value }))}
                placeholder="어떤 프로젝트 시행착오나 독서·회고에서 이 원칙을 확신하게 되었나요?"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
            </label>

            {/* Proof Linking: Projects & STAR Experiences */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="rounded-lg border border-slate-200 bg-white p-3 space-y-1.5">
                <div className="font-semibold text-slate-700 flex items-center gap-1">
                  <FolderKanban className="w-3.5 h-3.5 text-indigo-600" />
                  <span>이 신념을 증명하는 프로젝트 연결</span>
                </div>
                {projects.length === 0 ? (
                  <p className="text-[11px] text-slate-400">등록된 프로젝트가 없습니다.</p>
                ) : (
                  <div className="space-y-1 max-h-32 overflow-y-auto">
                    {projects.map((proj) => (
                      <label key={proj.id} className="flex items-center gap-2 text-[11px] cursor-pointer">
                        <input
                          type="checkbox"
                          checked={(pillarForm.linked_project_ids || []).includes(proj.id)}
                          onChange={() => toggleIdInForm("linked_project_ids", proj.id)}
                          className="accent-indigo-600"
                        />
                        <span className="truncate font-medium text-slate-800">{proj.name}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-lg border border-slate-200 bg-white p-3 space-y-1.5">
                <div className="font-semibold text-slate-700 flex items-center gap-1">
                  <Sparkles className="w-3.5 h-3.5 text-emerald-600" />
                  <span>이 신념을 증명하는 STAR-L 경험 연결</span>
                </div>
                {experiences.length === 0 ? (
                  <p className="text-[11px] text-slate-400">등록된 STAR 경험이 없습니다.</p>
                ) : (
                  <div className="space-y-1 max-h-32 overflow-y-auto">
                    {experiences.map((exp) => (
                      <label key={exp.id} className="flex items-center gap-2 text-[11px] cursor-pointer">
                        <input
                          type="checkbox"
                          checked={(pillarForm.linked_experience_ids || []).includes(exp.id)}
                          onChange={() => toggleIdInForm("linked_experience_ids", exp.id)}
                          className="accent-emerald-600"
                        />
                        <span className="truncate font-medium text-slate-800">
                          {exp.title} ({exp.completeness_score}점)
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowPillarForm(false)}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-slate-600"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={savingPillar}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                <span>{savingPillar ? "저장 중..." : "신념 카드 저장"}</span>
              </button>
            </div>
          </form>
        )}

        {/* Pillar Cards Grid */}
        {pillars.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 p-8 text-center space-y-2.5">
            <p className="text-sm font-semibold text-slate-700">
              아직 구조화된 핵심 신념 카드가 없습니다.
            </p>
            <p className="text-xs text-slate-500">
              <strong>[내 프로젝트·경험에서 신념 자동 발굴]</strong>을 누르면 이미 하신 프로젝트와 STAR-L 경험에서 증명 가능한 신념 카드 3~4개를 바로 찾아드립니다.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {pillars.map((pillar) => {
              const catMeta = PILLAR_CAT_MAP[pillar.category] || PILLAR_CATEGORIES[0];
              const statusMeta =
                PROOF_STATUS_BADGES[pillar.proof_status] || PROOF_STATUS_BADGES.needs_proof;
              const StatusIcon = statusMeta.icon;
              const sharpened = sharpenResults[pillar.id];
              const isSharpening = sharpeningId === pillar.id;

              return (
                <article
                  key={pillar.id}
                  className="rounded-xl border border-slate-200 bg-slate-50/30 p-4 space-y-3 flex flex-col justify-between"
                >
                  <div className="space-y-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${catMeta.cls}`}>
                          {catMeta.label}
                        </span>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold ${statusMeta.cls}`}
                        >
                          <StatusIcon className="w-3 h-3" />
                          <span>
                            {statusMeta.label} ({pillar.strength_score}점)
                          </span>
                        </span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          onClick={() => openEditPillar(pillar)}
                          className="p-1 rounded text-slate-400 hover:bg-white hover:text-slate-700"
                          title="신념 카드 수정"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeletePillar(pillar)}
                          className="p-1 rounded text-slate-400 hover:bg-red-50 hover:text-red-600"
                          title="신념 카드 삭제"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    <h4 className="text-sm font-bold text-slate-900 leading-snug">
                      “{pillar.title}”
                    </h4>

                    {pillar.tradeoff_rule && (
                      <div className="rounded-lg bg-white border border-slate-200 px-3 py-2 text-xs text-slate-700 leading-relaxed">
                        <strong className="text-indigo-800">트레이드오프 기준:</strong>{" "}
                        {pillar.tradeoff_rule}
                      </div>
                    )}

                    {pillar.origin_story && (
                      <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
                        {pillar.origin_story}
                      </p>
                    )}

                    {/* Linked Proof Projects & STARs */}
                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                      <span className="inline-flex items-center gap-1 text-[10px] font-bold text-slate-500">
                        <Link2 className="w-3 h-3" />
                        증명 근거:
                      </span>
                      {(pillar.linked_project_ids || []).map((pid) => (
                        <span
                          key={`lp-${pid}`}
                          className="rounded-md bg-indigo-50 border border-indigo-200 px-2 py-0.5 text-[10px] font-semibold text-indigo-800"
                        >
                          프로젝트 · {projectById[pid]?.name || `#${pid}`}
                        </span>
                      ))}
                      {(pillar.linked_experience_ids || []).map((eid) => (
                        <span
                          key={`le-${eid}`}
                          className="rounded-md bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[10px] font-semibold text-emerald-800"
                        >
                          STAR · {expById[eid]?.title || `#${eid}`}
                        </span>
                      ))}
                      {(pillar.linked_project_ids || []).length === 0 &&
                        (pillar.linked_experience_ids || []).length === 0 && (
                          <span className="text-[10px] font-semibold text-amber-700">
                            미연결 — 수정해서 기존 경험을 붙이거나 새 프로젝트로 증명하세요
                          </span>
                        )}
                    </div>

                    {pillar.diagnostic_tip && pillar.proof_status !== "proven" && (
                      <div className="rounded-lg bg-amber-50/70 border border-amber-200 px-2.5 py-1.5 text-[11px] text-amber-900">
                        {pillar.diagnostic_tip}
                      </div>
                    )}

                    {/* Sharpened Preview Box */}
                    {sharpened && (
                      <div className="rounded-xl border border-violet-200 bg-violet-50/60 p-3 space-y-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-violet-900 flex items-center gap-1">
                            <Wand2 className="w-3.5 h-3.5 text-violet-600" />
                            <span>AI 트레이드오프 다듬기 제안</span>
                          </span>
                          <button
                            type="button"
                            onClick={() =>
                              setSharpenResults((prev) => {
                                const next = { ...prev };
                                delete next[pillar.id];
                                return next;
                              })
                            }
                            className="text-slate-400 hover:text-slate-700"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        <div className="rounded-lg bg-white border border-violet-100 p-2.5 space-y-1">
                          <div className="font-bold text-slate-900">“{sharpened.sharpened_title}”</div>
                          <div className="text-[11px] text-slate-700">
                            <strong>기준:</strong> {sharpened.sharpened_tradeoff_rule}
                          </div>
                          {sharpened.why_better && (
                            <div className="text-[10px] text-violet-700">{sharpened.why_better}</div>
                          )}
                        </div>
                        <div className="flex justify-end">
                          <button
                            type="button"
                            onClick={() => handleApplySharpen(pillar)}
                            className="inline-flex items-center gap-1 rounded-lg bg-violet-600 px-3 py-1 text-[11px] font-semibold text-white hover:bg-violet-700"
                          >
                            <Check className="w-3 h-3" />
                            <span>이 문장으로 업데이트</span>
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="pt-2.5 border-t border-slate-200/70 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 flex-1 min-w-[160px]">
                      <input
                        type="text"
                        value={sharpenHints[pillar.id] || ""}
                        onChange={(e) =>
                          setSharpenHints((prev) => ({ ...prev, [pillar.id]: e.target.value }))
                        }
                        placeholder="다듬기 힌트 (선택: 겪은 갈등 한 줄)"
                        className="flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px]"
                      />
                      <button
                        type="button"
                        disabled={Boolean(sharpeningId)}
                        onClick={() => handleSharpenPillar(pillar.id)}
                        className="inline-flex items-center gap-1 rounded-md border border-violet-200 bg-violet-50 px-2.5 py-1 text-[11px] font-semibold text-violet-800 hover:bg-violet-100 disabled:opacity-50 shrink-0"
                      >
                        {isSharpening ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Wand2 className="w-3 h-3" />
                        )}
                        <span>날카롭게 다듬기</span>
                      </button>
                    </div>

                    {pillar.proof_status === "needs_proof" && onJumpToCopilot && (
                      <button
                        type="button"
                        onClick={() =>
                          onJumpToCopilot(`'${pillar.title}' 신념을 실제로 증명할 수 있는 포트폴리오 프로젝트`)
                        }
                        className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-900 hover:bg-amber-100"
                      >
                        <ArrowUpRight className="w-3 h-3" />
                        <span>코파일럿으로 증명 기획</span>
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {/* SECTION 2: Core Career Identity Summary & De-AI Tone */}
      <form
        onSubmit={handleSaveProfile}
        className="rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-bold text-slate-900">
            커리어 프로필
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            {profileStatus && (
              <span className="text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-0.5">
                {profileStatus}
              </span>
            )}
            <button
              type="button"
              disabled={synthesizing || (notes.length === 0 && pillars.length === 0)}
              onClick={handleSynthesizeIdentity}
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-800 hover:bg-indigo-100 disabled:opacity-50"
            >
              {synthesizing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Wand2 className="w-3.5 h-3.5" />
              )}
              <span>{synthesizing ? "종합 정제 중..." : "신념 카드·노트로 비전 정제"}</span>
            </button>
          </div>
        </div>

        {/* AI Synthesized Identity Preview */}
        {synthesis && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4 space-y-3 text-xs">
            <div className="flex items-start justify-between gap-2">
              <div className="font-bold text-indigo-950 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
                <span>비전 정제 제안</span>
              </div>
              <button
                type="button"
                onClick={() => setSynthesis(null)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {(synthesis.key_themes || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {synthesis.key_themes.map((t, i) => (
                  <span
                    key={i}
                    className="rounded-full bg-white border border-indigo-200 px-2.5 py-0.5 font-semibold text-indigo-800"
                  >
                    #{t}
                  </span>
                ))}
              </div>
            )}

            <div className="rounded-lg bg-white border border-indigo-100 p-3 space-y-1">
              <div className="text-[11px] font-bold text-indigo-700">제안 커리어 비전</div>
              <p className="text-slate-800 leading-relaxed">{synthesis.suggested_career_vision}</p>
            </div>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setSynthesis(null)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-slate-600"
              >
                닫기
              </button>
              <button
                type="button"
                onClick={handleApplySynthesis}
                className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3.5 py-1.5 font-semibold text-white hover:bg-indigo-700"
              >
                <Check className="w-3.5 h-3.5" />
                <span>입력칸에 반영</span>
              </button>
            </div>
          </div>
        )}

        <div className="space-y-4">
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">커리어 비전</span>
            <textarea
              rows={2}
              value={profileForm.career_vision}
              onChange={(e) =>
                setProfileForm({ ...profileForm, career_vision: e.target.value })
              }
              placeholder="예: 복잡한 문제를 구조화하고, 사용자가 체감하는 가치를 만드는 빌더"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">희망 직무</span>
              <input
                type="text"
                value={profileForm.target_roles}
                onChange={(e) =>
                  setProfileForm({ ...profileForm, target_roles: e.target.value })
                }
                placeholder="예: AI 에이전트 백엔드, 서비스 기획 PM"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">선호 문체</span>
              <input
                type="text"
                value={profileForm.preferred_tone}
                onChange={(e) =>
                  setProfileForm({ ...profileForm, preferred_tone: e.target.value })
                }
                placeholder="예: 과장 없이 담백하게, 실제 근거와 행동 중심"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={savingProfile}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            <span>{savingProfile ? "저장 중..." : "프로필 저장"}</span>
          </button>
        </div>
      </form>

      {/* SECTION 3: Quotes, Lectures & Daily Thought Reflection Journal */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <Quote className="w-5 h-5 text-indigo-600" />
            <span>일상 회고 저널 · {filteredNotes.length}</span>
          </h3>

          <button
            type="button"
            onClick={() => openNewNote("thought")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
          >
            <Plus className="w-4 h-4" />
            <span>일상 회고 기록하기</span>
          </button>
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setFilterType("all")}
            className={`rounded-full px-3 py-1 text-xs font-semibold border ${
              filterType === "all"
                ? "bg-slate-900 text-white border-slate-900"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
            }`}
          >
            전체 ({notes.length})
          </button>
          {SOURCE_TYPES.map((st) => {
            const count = notes.filter((n) => n.source_type === st.id).length;
            return (
              <button
                key={st.id}
                type="button"
                onClick={() => setFilterType(st.id)}
                className={`rounded-full px-3 py-1 text-xs font-semibold border ${
                  filterType === st.id
                    ? "bg-slate-900 text-white border-slate-900"
                    : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                }`}
              >
                {st.label} ({count})
              </button>
            );
          })}
        </div>

        {/* Create / Edit Note Form */}
        {showNoteForm && (
          <form
            onSubmit={handleSaveNote}
            className="rounded-2xl border border-indigo-200 bg-white p-6 space-y-4 shadow-sm"
          >
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-bold text-slate-900">
                {editingNoteId ? "구절 · 생각 노트 수정" : "새 구절 · 생각 기록"}
              </h4>
              <button
                type="button"
                onClick={() => setShowNoteForm(false)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex flex-wrap gap-2">
              {SOURCE_TYPES.map((st) => {
                const Icon = st.icon;
                const active = noteForm.source_type === st.id;
                return (
                  <button
                    key={st.id}
                    type="button"
                    onClick={() => setNoteForm({ ...noteForm, source_type: st.id })}
                    className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold ${
                      active
                        ? "border-indigo-600 bg-indigo-600 text-white"
                        : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{st.label}</span>
                  </button>
                );
              })}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-700">
                  출처 (책 제목/저자 · 강의명 · 생각 주제)
                </span>
                <input
                  type="text"
                  value={noteForm.source_title}
                  onChange={(e) =>
                    setNoteForm({ ...noteForm, source_title: e.target.value })
                  }
                  placeholder="예: 《함께 자라기》 김창준 / 스탠포드 CS183B 강의 / 팀 회의 후 메모"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                />
              </label>

              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-700">
                  주제 태그 (쉼표로 구분)
                </span>
                <input
                  type="text"
                  value={noteForm.tags_text}
                  onChange={(e) =>
                    setNoteForm({ ...noteForm, tags_text: e.target.value })
                  }
                  placeholder="예: 협업, 문제정의, 제품철학, 리더십"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                />
              </label>
            </div>

            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">
                인상 깊은 구절 원문 (선택 — 일상 생각이면 비워도 됩니다)
              </span>
              <textarea
                rows={2}
                value={noteForm.quote_text}
                onChange={(e) =>
                  setNoteForm({ ...noteForm, quote_text: e.target.value })
                }
                placeholder="책이나 강의에서 마음을 울렸던 문장을 그대로 적어두세요."
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">
                나의 생각 &amp; 회고 *
              </span>
              <textarea
                required
                rows={4}
                value={noteForm.my_reflection}
                onChange={(e) =>
                  setNoteForm({ ...noteForm, my_reflection: e.target.value })
                }
                placeholder="왜 이 문장이 인상 깊었는지, 평소 내 경험이나 일하는 방식에 어떻게 연결되는지 자유롭게 회고해 보세요."
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowNoteForm(false)}
                className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-700"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={savingNote}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                <span>{savingNote ? "저장 중..." : "저장 & 신념 벡터 반영"}</span>
              </button>
            </div>
          </form>
        )}

        {/* Notes Feed */}
        {filteredNotes.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center space-y-2.5">
            <p className="text-sm font-semibold text-slate-700">
              아직 기록된 구절이나 생각 노트가 없습니다.
            </p>
            <p className="text-xs text-slate-500">
              인상 깊었던 책 한 줄, 강의의 인사이트, 평소 들었던 커리어 고민을 적어두고 AI와 함께 회고해 보세요.
            </p>
            <button
              type="button"
              onClick={() => openNewNote("book")}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>첫 번째 구절 · 생각 기록하기</span>
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredNotes.map((note) => {
              const meta = SOURCE_MAP[note.source_type] || SOURCE_MAP.thought;
              const Icon = meta.icon;
              const isReflecting = reflectingId === note.id;
              return (
                <article
                  key={note.id}
                  className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3 shadow-sm flex flex-col justify-between"
                >
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2 min-w-0">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${meta.badge}`}
                        >
                          <Icon className="w-3 h-3" />
                          {meta.label}
                        </span>
                        <span className="text-sm font-bold text-slate-900 truncate">
                          {note.source_title || "제목 없는 생각 노트"}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          onClick={() => openEditNote(note)}
                          className="p-1 rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                          title="수정"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteNote(note)}
                          className="p-1 rounded text-slate-400 hover:bg-red-50 hover:text-red-600"
                          title="삭제"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    {note.quote_text && (
                      <blockquote className="rounded-xl border-l-4 border-indigo-400 bg-indigo-50/40 px-3.5 py-2.5 text-xs italic text-slate-800 leading-relaxed">
                        &ldquo;{note.quote_text}&rdquo;
                      </blockquote>
                    )}

                    <p className="text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">
                      {note.my_reflection}
                    </p>

                    {(note.tags || []).length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {note.tags.map((t, i) => (
                          <span
                            key={i}
                            className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600"
                          >
                            #{t}
                          </span>
                        ))}
                      </div>
                    )}

                    {note.ai_reflection && (
                      <div className="rounded-xl border border-violet-200 bg-violet-50/40 p-3.5 prose prose-xs prose-slate max-w-none">
                        <div className="text-[11px] font-bold text-violet-900 mb-1 flex items-center gap-1">
                          <Sparkles className="w-3 h-3 text-violet-600" />
                          <span>AI 신념 연결 심화 회고</span>
                        </div>
                        <ReactMarkdown>{note.ai_reflection}</ReactMarkdown>
                      </div>
                    )}
                  </div>

                  <div className="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[10px] text-slate-400">
                      {new Date(note.created_at).toLocaleDateString("ko-KR")}
                    </span>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => handlePromoteNoteToPillar(note)}
                        className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-800 hover:bg-indigo-100"
                        title="이 회고 노트를 핵심 신념 카드로 승격"
                      >
                        <ShieldCheck className="w-3 h-3" />
                        <span>신념 카드로 승격</span>
                      </button>
                      <button
                        type="button"
                        disabled={isReflecting}
                        onClick={() => handleReflectNote(note.id)}
                        className="inline-flex items-center gap-1 rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-1 text-[11px] font-semibold text-violet-800 hover:bg-violet-100 disabled:opacity-50"
                      >
                        {isReflecting ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Sparkles className="w-3 h-3" />
                        )}
                        <span>
                          {isReflecting
                            ? "회고 생성 중..."
                            : note.ai_reflection
                              ? "AI 회고 다시 받기"
                              : "AI 생각 심화 회고"}
                        </span>
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
