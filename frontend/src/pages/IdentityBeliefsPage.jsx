import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  BookHeart,
  BookOpen,
  Check,
  GraduationCap,
  Lightbulb,
  Loader2,
  Newspaper,
  Pencil,
  Plus,
  Quote,
  Save,
  Sparkles,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { api } from "../api/client.js";

const SOURCE_TYPES = [
  { id: "book", label: "책 · 독서", icon: BookOpen, badge: "bg-amber-50 text-amber-800 border-amber-200" },
  { id: "lecture", label: "강의 · 세미나", icon: GraduationCap, badge: "bg-indigo-50 text-indigo-800 border-indigo-200" },
  { id: "article", label: "아티클 · 영상", icon: Newspaper, badge: "bg-sky-50 text-sky-800 border-sky-200" },
  { id: "thought", label: "일상 생각 · 회고", icon: Lightbulb, badge: "bg-emerald-50 text-emerald-800 border-emerald-200" },
];

const SOURCE_MAP = Object.fromEntries(SOURCE_TYPES.map((s) => [s.id, s]));

const EMPTY_NOTE = {
  source_type: "book",
  source_title: "",
  quote_text: "",
  my_reflection: "",
  tags_text: "",
};

export default function IdentityBeliefsPage({ profile, notes = [], onRefresh }) {
  // Core Identity Form
  const [profileForm, setProfileForm] = useState({
    career_vision: "",
    core_beliefs: "",
    target_roles: "",
    preferred_tone: "",
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileStatus, setProfileStatus] = useState("");

  // AI Identity Synthesis from Notes
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
    setProfileStatus("정제안이 입력칸에 반영되었습니다. '신념 저장'을 눌러 확정해 주세요.");
  };

  const openNewNote = (defaultType = "book") => {
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

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <BookHeart className="w-6 h-6 text-indigo-600" />
          <span>1. 나의 신념 &amp; 생각 노트</span>
        </h2>
        <p className="text-sm text-slate-600 mt-1">
          커리어 비전·일하는 신념을 다듬고, <strong>책·강의의 인상 깊은 구절과 평소의 생각</strong>을 회고하며 나만의 철학을 축적합니다. 저장된 기록은 기업 매칭과 자소서 공방에 자동 반영됩니다.
        </p>
      </div>

      {/* Section 1: Core Career Identity Card */}
      <form
        onSubmit={handleSaveProfile}
        className="rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-base font-bold text-slate-900">
              커리어 정체성 (비전 · 핵심 신념 · 선호 문체)
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              기업 3각 매칭과 자소서 공방의 중심축이 되는 나의 핵심 가치관입니다.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {profileStatus && (
              <span className="text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-0.5">
                {profileStatus}
              </span>
            )}
            <button
              type="button"
              disabled={synthesizing || notes.length === 0}
              onClick={handleSynthesizeIdentity}
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-800 hover:bg-indigo-100 disabled:opacity-50"
              title="아래에 모은 구절·생각 노트를 종합해 비전과 신념 문장을 정제합니다"
            >
              {synthesizing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Wand2 className="w-3.5 h-3.5" />
              )}
              <span>{synthesizing ? "노트 종합 중..." : "생각 노트로 신념·비전 정제"}</span>
            </button>
          </div>
        </div>

        {/* AI Synthesized Identity Preview */}
        {synthesis && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4 space-y-3 text-xs">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-bold text-indigo-950 flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
                  <span>축적된 생각 노트 {synthesis.note_count}건 기반 신념·비전 정제 제안</span>
                </div>
                <p className="text-slate-600 mt-0.5">{synthesis.synthesis_rationale}</p>
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

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="rounded-lg bg-white border border-indigo-100 p-3 space-y-1">
                <div className="text-[11px] font-bold text-indigo-700">제안 커리어 비전</div>
                <p className="text-slate-800 leading-relaxed">{synthesis.suggested_career_vision}</p>
              </div>
              <div className="rounded-lg bg-white border border-indigo-100 p-3 space-y-1">
                <div className="text-[11px] font-bold text-indigo-700">제안 핵심 신념</div>
                <p className="text-slate-800 leading-relaxed">{synthesis.suggested_core_beliefs}</p>
              </div>
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

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">커리어 비전</span>
            <textarea
              rows={3}
              value={profileForm.career_vision}
              onChange={(e) =>
                setProfileForm({ ...profileForm, career_vision: e.target.value })
              }
              placeholder="예: 복잡한 문제를 구조화하고, 기술과 기획의 경계에서 사용자가 실제로 체감하는 가치를 만드는 빌더"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">
              핵심 신념 · 일하는 원칙
            </span>
            <textarea
              rows={3}
              value={profileForm.core_beliefs}
              onChange={(e) =>
                setProfileForm({ ...profileForm, core_beliefs: e.target.value })
              }
              placeholder="예: 측정할 수 없는 개선은 믿지 않는다 / 완벽한 설계보다 빠른 가설 검증과 투명한 회고를 중시한다"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">희망 직무</span>
            <input
              type="text"
              value={profileForm.target_roles}
              onChange={(e) =>
                setProfileForm({ ...profileForm, target_roles: e.target.value })
              }
              placeholder="예: AI 에이전트 백엔드, 서비스 기획 PM, 데이터 프로덕트 매니저"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">
              선호 문체 (De-AI 기준)
            </span>
            <input
              type="text"
              value={profileForm.preferred_tone}
              onChange={(e) =>
                setProfileForm({ ...profileForm, preferred_tone: e.target.value })
              }
              placeholder="예: 과장 없이 담백하게, 실제 근거와 행동 중심으로 또렷하게 쓰는 스타일"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={savingProfile}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            <span>{savingProfile ? "저장 중..." : "신념 저장 & 벡터 동기화"}</span>
          </button>
        </div>
      </form>

      {/* Section 2: Quotes, Lectures & Daily Thought Reflection Journal */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <Quote className="w-5 h-5 text-indigo-600" />
              <span>책 · 강의 구절 &amp; 일상 생각 회고 저널 ({filteredNotes.length})</span>
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              마음에 남았던 문장이나 평소 떠오른 생각을 기록하고 AI와 함께 나의 신념·경험으로 연결해 보세요.
            </p>
          </div>

          <button
            type="button"
            onClick={() => openNewNote("book")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
          >
            <Plus className="w-4 h-4" />
            <span>구절 · 생각 기록하기</span>
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

                  <div className="pt-2 border-t border-slate-100 flex items-center justify-between">
                    <span className="text-[10px] text-slate-400">
                      {new Date(note.created_at).toLocaleDateString("ko-KR")}
                    </span>
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
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
