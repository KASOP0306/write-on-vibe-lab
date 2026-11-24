import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Check,
  Copy,
  FileText,
  Github,
  Loader2,
  Pencil,
  Plus,
  Save,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api/client.js";

const EMPTY_PROJECT_FORM = {
  name: "",
  period: "",
  role: "",
  summary: "",
  tech_stack_text: "",
  portfolio_goal_link: "",
  repo_url: "",
};

export default function IdentityPortfolioPage({ profile, projects, onRefresh }) {
  const [profileForm, setProfileForm] = useState({
    career_vision: "",
    core_beliefs: "",
    target_roles: "",
    preferred_tone: "",
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileStatus, setProfileStatus] = useState("");

  // GitHub Auto Portfolio Analyzer
  const [ghUrl, setGhUrl] = useState("");
  const [ghRoleHint, setGhRoleHint] = useState("");
  const [ghExtraContext, setGhExtraContext] = useState("");
  const [ghAnalyzing, setGhAnalyzing] = useState(false);
  const [ghError, setGhError] = useState("");
  const [ghDraft, setGhDraft] = useState(null);
  const [ghProjectEdit, setGhProjectEdit] = useState(EMPTY_PROJECT_FORM);
  const [ghSelectedExpIndices, setGhSelectedExpIndices] = useState(new Set());
  const [ghPreviewTab, setGhPreviewTab] = useState("star");
  const [ghImporting, setGhImporting] = useState(false);
  const [ghCopiedMd, setGhCopiedMd] = useState(false);

  const [showProjectForm, setShowProjectForm] = useState(false);
  const [editingProjectId, setEditingProjectId] = useState(null);
  const [projectForm, setProjectForm] = useState(EMPTY_PROJECT_FORM);
  const [savingProject, setSavingProject] = useState(false);

  const [recapModal, setRecapModal] = useState(null);
  const [recapLoadingId, setRecapLoadingId] = useState(null);
  const [copiedRecap, setCopiedRecap] = useState(false);

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
    e.preventDefault();
    setSavingProfile(true);
    setProfileStatus("");
    try {
      const updated = await api.updateProfile(profileForm);
      setProfileStatus(
        updated.vector_synced
          ? "저장 및 career_identity 벡터 동기화 완료"
          : "DB 저장 완료 (벡터 동기화는 AWS Bedrock 설정 후 반영)"
      );
      await onRefresh();
    } catch (err) {
      setProfileStatus(`저장 실패: ${err.message}`);
    } finally {
      setSavingProfile(false);
    }
  };

  const handleAnalyzeGithub = async (e) => {
    e.preventDefault();
    if (!ghUrl.trim() || ghAnalyzing) return;
    setGhAnalyzing(true);
    setGhError("");
    setGhDraft(null);
    setGhCopiedMd(false);

    try {
      const res = await api.analyzeGithubRepo({
        repo_url: ghUrl.trim(),
        role_hint: ghRoleHint.trim(),
        extra_context: ghExtraContext.trim(),
      });
      setGhDraft(res);
      setGhProjectEdit({
        name: res.project.name || "",
        period: res.project.period || "",
        role: res.project.role || "",
        summary: res.project.summary || "",
        tech_stack_text: (res.project.tech_stack || []).join(", "),
        portfolio_goal_link: res.project.portfolio_goal_link || "",
        repo_url: res.project.repo_url || ghUrl.trim(),
      });
      setGhSelectedExpIndices(
        new Set((res.suggested_experiences || []).map((_, idx) => idx))
      );
      setGhPreviewTab("star");
    } catch (err) {
      setGhError(err.message);
    } finally {
      setGhAnalyzing(false);
    }
  };

  const toggleGhExperience = (idx) => {
    setGhSelectedExpIndices((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleImportGithub = async () => {
    if (!ghDraft || ghImporting) return;
    setGhImporting(true);
    try {
      const selectedExps = (ghDraft.suggested_experiences || []).filter((_, idx) =>
        ghSelectedExpIndices.has(idx)
      );
      const res = await api.importGithubProject({
        project: {
          name: ghProjectEdit.name,
          period: ghProjectEdit.period,
          role: ghProjectEdit.role,
          summary: ghProjectEdit.summary,
          tech_stack: ghProjectEdit.tech_stack_text
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          portfolio_goal_link: ghProjectEdit.portfolio_goal_link,
          repo_url: ghProjectEdit.repo_url,
        },
        experiences: selectedExps,
      });
      setGhDraft(null);
      setGhUrl("");
      setGhRoleHint("");
      setGhExtraContext("");
      await onRefresh();
      alert(
        `'${res.project.name}' 프로젝트와 STAR 경험 ${res.saved_experience_ids.length}건이 저장되었습니다! (벡터 동기화 ${res.vector_synced_count}건)`
      );
    } catch (err) {
      alert(`GitHub 포트폴리오 저장 실패: ${err.message}`);
    } finally {
      setGhImporting(false);
    }
  };

  const handleCopyGhMarkdown = async () => {
    if (!ghDraft?.portfolio_markdown) return;
    await navigator.clipboard.writeText(ghDraft.portfolio_markdown);
    setGhCopiedMd(true);
    setTimeout(() => setGhCopiedMd(false), 2000);
  };

  const openCreateProject = () => {
    setEditingProjectId(null);
    setProjectForm(EMPTY_PROJECT_FORM);
    setShowProjectForm(true);
  };

  const openEditProject = (proj) => {
    setEditingProjectId(proj.id);
    setProjectForm({
      name: proj.name || "",
      period: proj.period || "",
      role: proj.role || "",
      summary: proj.summary || "",
      tech_stack_text: (proj.tech_stack || []).join(", "),
      portfolio_goal_link: proj.portfolio_goal_link || "",
      repo_url: proj.repo_url || "",
    });
    setShowProjectForm(true);
  };

  const handleSaveProject = async (e) => {
    e.preventDefault();
    setSavingProject(true);
    const payload = {
      name: projectForm.name,
      period: projectForm.period,
      role: projectForm.role,
      summary: projectForm.summary,
      tech_stack: projectForm.tech_stack_text
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      portfolio_goal_link: projectForm.portfolio_goal_link,
      repo_url: projectForm.repo_url,
    };

    try {
      if (editingProjectId) {
        await api.updateProject(editingProjectId, payload);
      } else {
        await api.createProject(payload);
      }
      setShowProjectForm(false);
      setEditingProjectId(null);
      setProjectForm(EMPTY_PROJECT_FORM);
      await onRefresh();
    } catch (err) {
      alert(`프로젝트 저장 실패: ${err.message}`);
    } finally {
      setSavingProject(false);
    }
  };

  const handleDeleteProject = async (proj) => {
    if (!window.confirm(`'${proj.name}' 프로젝트를 삭제할까요?`)) return;
    try {
      await api.deleteProject(proj.id);
      await onRefresh();
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const handleRecap = async (proj) => {
    setRecapLoadingId(proj.id);
    try {
      const res = await api.recapProject(proj.id);
      setRecapModal(res);
      setCopiedRecap(false);
    } catch (err) {
      alert(`리캡 생성 실패: ${err.message}`);
    } finally {
      setRecapLoadingId(null);
    }
  };

  const handleCopyRecap = async () => {
    if (!recapModal?.markdown) return;
    await navigator.clipboard.writeText(recapModal.markdown);
    setCopiedRecap(true);
    setTimeout(() => setCopiedRecap(false), 2000);
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">1. 신념 &amp; 포트폴리오</h2>
        <p className="text-sm text-slate-600 mt-1">
          나의 커리어 비전·신념·문체를 정의하고, GitHub 링크 자동 분석 또는 직접 입력으로 프로젝트 포트폴리오를 관리합니다.
        </p>
      </div>

      {/* Career Identity Form */}
      <form
        onSubmit={handleSaveProfile}
        className="rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900">
            커리어 정체성 (Career Identity)
          </h3>
          {profileStatus && (
            <span className="text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1">
              {profileStatus}
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block space-y-1.5">
            <span className="text-xs font-semibold text-slate-700">희망 직무</span>
            <input
              type="text"
              value={profileForm.target_roles}
              onChange={(e) =>
                setProfileForm({ ...profileForm, target_roles: e.target.value })
              }
              placeholder="예: AI 에이전트 엔지니어 / 데이터 엔지니어"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/15"
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-semibold text-slate-700">
              궁극적 커리어 비전 / 포트폴리오 목표
            </span>
            <input
              type="text"
              value={profileForm.career_vision}
              onChange={(e) =>
                setProfileForm({ ...profileForm, career_vision: e.target.value })
              }
              placeholder="예: AI 도입을 통해 산업 현장의 반복 병목을 해소하는 엔지니어"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/15"
            />
          </label>
        </div>

        <label className="block space-y-1.5">
          <span className="text-xs font-semibold text-slate-700">
            핵심 신념 및 엔지니어링 철학
          </span>
          <textarea
            rows={3}
            value={profileForm.core_beliefs}
            onChange={(e) =>
              setProfileForm({ ...profileForm, core_beliefs: e.target.value })
            }
            placeholder="기술 선택 기준, 문제 해결 철학, 팀워크 가치관 등을 자유롭게 작성하세요."
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/15"
          />
        </label>

        <label className="block space-y-1.5">
          <span className="text-xs font-semibold text-slate-700">
            선호 문체 / 실제 어휘 샘플 (De-AI Humanizer 반영)
          </span>
          <textarea
            rows={2}
            value={profileForm.preferred_tone}
            onChange={(e) =>
              setProfileForm({ ...profileForm, preferred_tone: e.target.value })
            }
            placeholder="예: 과장 없이 담백하게, 지표와 트러블슈팅 과정을 짧은 문장으로 또렷하게 쓰는 스타일"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/15"
          />
        </label>

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

      {/* GitHub Repo Auto Portfolio Generator */}
      <section className="rounded-2xl border border-indigo-200 bg-gradient-to-br from-white to-indigo-50/40 p-6 space-y-4 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Github className="w-5 h-5 text-indigo-700" />
              <span>GitHub 링크로 포트폴리오 &amp; STAR 경험 자동 생성</span>
            </h3>
            <p className="text-xs text-slate-600 mt-1">
              Public GitHub 저장소 링크를 넣으면 README·디렉토리·의존성·최근 커밋을 읽어 프로젝트 요약, 기술 스택, 포트폴리오 Markdown, STAR 경험 초안까지 자동으로 구성합니다.
            </p>
          </div>
        </div>

        <form onSubmit={handleAnalyzeGithub} className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <input
              required
              type="text"
              value={ghUrl}
              onChange={(e) => setGhUrl(e.target.value)}
              placeholder="https://github.com/owner/repo *"
              className="md:col-span-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/25"
            />
            <input
              type="text"
              value={ghRoleHint}
              onChange={(e) => setGhRoleHint(e.target.value)}
              placeholder="본인 역할 힌트 (선택: 예: 백엔드 & AI 설계)"
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
            />
          </div>

          <div className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              value={ghExtraContext}
              onChange={(e) => setGhExtraContext(e.target.value)}
              placeholder="강조하고 싶은 성과/트러블슈팅 메모가 있다면 추가 (선택)"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
            />
            <button
              type="submit"
              disabled={ghAnalyzing || !ghUrl.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 shrink-0"
            >
              {ghAnalyzing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>저장소 코드·README 분석 중...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  <span>GitHub 자동 분석</span>
                </>
              )}
            </button>
          </div>
        </form>

        {ghError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-800">
            {ghError}
          </div>
        )}

        {/* GitHub Analysis Editable Preview */}
        {ghDraft && (
          <div className="rounded-xl border border-indigo-200 bg-white p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2 text-xs text-slate-600">
                <span className="font-bold text-slate-900">
                  {ghDraft.repo_meta?.full_name}
                </span>
                <span>·</span>
                <span>커밋 {ghDraft.repo_meta?.commits_sampled || 0}건 분석</span>
                {(ghDraft.repo_meta?.files_analyzed || []).length > 0 && (
                  <>
                    <span>·</span>
                    <span>
                      확인 파일: {ghDraft.repo_meta.files_analyzed.join(", ")}
                    </span>
                  </>
                )}
              </div>
              <button
                type="button"
                onClick={() => setGhDraft(null)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Editable Project Summary */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <label className="block space-y-1">
                <span className="text-[11px] font-semibold text-slate-600">
                  프로젝트명
                </span>
                <input
                  type="text"
                  value={ghProjectEdit.name}
                  onChange={(e) =>
                    setGhProjectEdit({ ...ghProjectEdit, name: e.target.value })
                  }
                  className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-[11px] font-semibold text-slate-600">
                  개발 기간
                </span>
                <input
                  type="text"
                  value={ghProjectEdit.period}
                  onChange={(e) =>
                    setGhProjectEdit({ ...ghProjectEdit, period: e.target.value })
                  }
                  className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-[11px] font-semibold text-slate-600">
                  담당 역할
                </span>
                <input
                  type="text"
                  value={ghProjectEdit.role}
                  onChange={(e) =>
                    setGhProjectEdit({ ...ghProjectEdit, role: e.target.value })
                  }
                  className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
                />
              </label>
            </div>

            <label className="block space-y-1">
              <span className="text-[11px] font-semibold text-slate-600">
                프로젝트 핵심 요약
              </span>
              <textarea
                rows={2}
                value={ghProjectEdit.summary}
                onChange={(e) =>
                  setGhProjectEdit({ ...ghProjectEdit, summary: e.target.value })
                }
                className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
              />
            </label>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="block space-y-1">
                <span className="text-[11px] font-semibold text-slate-600">
                  기술 스택 (쉼표 구분)
                </span>
                <input
                  type="text"
                  value={ghProjectEdit.tech_stack_text}
                  onChange={(e) =>
                    setGhProjectEdit({
                      ...ghProjectEdit,
                      tech_stack_text: e.target.value,
                    })
                  }
                  className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-[11px] font-semibold text-slate-600">
                  나의 커리어 비전 연결점
                </span>
                <input
                  type="text"
                  value={ghProjectEdit.portfolio_goal_link}
                  onChange={(e) =>
                    setGhProjectEdit({
                      ...ghProjectEdit,
                      portfolio_goal_link: e.target.value,
                    })
                  }
                  className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
                />
              </label>
            </div>

            {/* Tabs: STAR Drafts vs Portfolio Markdown */}
            <div className="pt-2 border-t border-slate-100 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="inline-flex rounded-lg bg-slate-100 p-1 text-xs font-semibold">
                  <button
                    type="button"
                    onClick={() => setGhPreviewTab("star")}
                    className={`rounded-md px-3 py-1 ${
                      ghPreviewTab === "star"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-600"
                    }`}
                  >
                    추출된 STAR 경험 ({ghDraft.suggested_experiences?.length || 0}건)
                  </button>
                  <button
                    type="button"
                    onClick={() => setGhPreviewTab("markdown")}
                    className={`rounded-md px-3 py-1 ${
                      ghPreviewTab === "markdown"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-600"
                    }`}
                  >
                    포트폴리오 Markdown 미리보기
                  </button>
                </div>

                {ghPreviewTab === "markdown" && (
                  <button
                    type="button"
                    onClick={handleCopyGhMarkdown}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50"
                  >
                    {ghCopiedMd ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-emerald-600" />
                        <span>복사됨</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        <span>Markdown 복사</span>
                      </>
                    )}
                  </button>
                )}
              </div>

              {ghPreviewTab === "star" ? (
                <div className="space-y-2.5">
                  {(ghDraft.suggested_experiences || []).map((exp, idx) => (
                    <label
                      key={idx}
                      className={`block rounded-xl border p-3.5 text-xs space-y-1 cursor-pointer transition-colors ${
                        ghSelectedExpIndices.has(idx)
                          ? "border-indigo-300 bg-indigo-50/40"
                          : "border-slate-200 bg-slate-50/50 opacity-65"
                      }`}
                    >
                      <div className="flex items-center gap-2 font-bold text-slate-900">
                        <input
                          type="checkbox"
                          checked={ghSelectedExpIndices.has(idx)}
                          onChange={() => toggleGhExperience(idx)}
                          className="rounded border-slate-300"
                        />
                        <span>{exp.title}</span>
                      </div>
                      <p className="text-slate-700 pl-5">
                        <strong>S:</strong> {exp.situation}
                      </p>
                      <p className="text-slate-700 pl-5">
                        <strong>T:</strong> {exp.task}
                      </p>
                      <p className="text-slate-700 pl-5">
                        <strong>A:</strong> {exp.action}
                      </p>
                      <p className="text-slate-700 pl-5">
                        <strong>R:</strong> {exp.result}
                      </p>
                      {exp.quantified_metrics && (
                        <p className="text-emerald-800 pl-5">
                          <strong>지표:</strong> {exp.quantified_metrics}
                        </p>
                      )}
                    </label>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 max-h-80 overflow-y-auto prose prose-sm prose-slate max-w-none">
                  <ReactMarkdown>{ghDraft.portfolio_markdown || ""}</ReactMarkdown>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setGhDraft(null)}
                className="rounded-lg border border-slate-200 px-3.5 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                취소
              </button>
              <button
                type="button"
                disabled={ghImporting || !ghProjectEdit.name.trim()}
                onClick={handleImportGithub}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                <span>
                  {ghImporting
                    ? "DB & 벡터 저장 중..."
                    : `프로젝트 + 선택한 STAR ${ghSelectedExpIndices.size}건 저장`}
                </span>
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Projects Portfolio */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900">
            포트폴리오 프로젝트 ({projects.length})
          </h3>
          <button
            type="button"
            onClick={openCreateProject}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-medium text-white hover:bg-slate-800"
          >
            <Plus className="w-4 h-4" />
            <span>직접 프로젝트 추가</span>
          </button>
        </div>

        {showProjectForm && (
          <form
            onSubmit={handleSaveProject}
            className="rounded-2xl border border-slate-300 bg-white p-5 space-y-3 shadow-sm"
          >
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-bold text-slate-900">
                {editingProjectId ? "프로젝트 수정" : "새 프로젝트 등록"}
              </h4>
              <button
                type="button"
                onClick={() => setShowProjectForm(false)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                required
                type="text"
                value={projectForm.name}
                onChange={(e) =>
                  setProjectForm({ ...projectForm, name: e.target.value })
                }
                placeholder="프로젝트명 *"
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
              <input
                type="text"
                value={projectForm.period}
                onChange={(e) =>
                  setProjectForm({ ...projectForm, period: e.target.value })
                }
                placeholder="기간 (예: 2026.08 - 2026.11)"
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
              <input
                type="text"
                value={projectForm.role}
                onChange={(e) =>
                  setProjectForm({ ...projectForm, role: e.target.value })
                }
                placeholder="담당 역할 (예: 백엔드 / AI 설계)"
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </div>

            <textarea
              rows={2}
              value={projectForm.summary}
              onChange={(e) =>
                setProjectForm({ ...projectForm, summary: e.target.value })
              }
              placeholder="프로젝트 핵심 요약"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <input
                type="text"
                value={projectForm.tech_stack_text}
                onChange={(e) =>
                  setProjectForm({
                    ...projectForm,
                    tech_stack_text: e.target.value,
                  })
                }
                placeholder="기술 스택 (쉼표 구분: FastAPI, LangGraph, pgvector)"
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
              <input
                type="text"
                value={projectForm.repo_url}
                onChange={(e) =>
                  setProjectForm({ ...projectForm, repo_url: e.target.value })
                }
                placeholder="GitHub / 배포 URL (선택)"
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </div>

            <input
              type="text"
              value={projectForm.portfolio_goal_link}
              onChange={(e) =>
                setProjectForm({
                  ...projectForm,
                  portfolio_goal_link: e.target.value,
                })
              }
              placeholder="나의 커리어 비전과 연결되는 지점"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowProjectForm(false)}
                className="rounded-lg border border-slate-200 px-3.5 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={savingProject}
                className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {savingProject ? "저장 중..." : "저장"}
              </button>
            </div>
          </form>
        )}

        {projects.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
            등록된 프로젝트가 없습니다. 위의 <strong>GitHub 링크 자동 분석</strong> 또는 <strong>직접 프로젝트 추가</strong>로 첫 포트폴리오를 만들어 보세요.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {projects.map((proj) => (
              <div
                key={proj.id}
                className="rounded-2xl border border-slate-200 bg-white p-5 flex flex-col justify-between gap-4 shadow-sm"
              >
                <div className="space-y-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h4 className="text-base font-bold text-slate-900">
                        {proj.name}
                      </h4>
                      <p className="text-xs text-slate-500">
                        {[proj.period, proj.role].filter(Boolean).join(" · ") ||
                          "기간/역할 미입력"}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
                      경험 {proj.experience_count}건
                    </span>
                  </div>

                  {proj.summary && (
                    <p className="text-sm text-slate-700 leading-relaxed">
                      {proj.summary}
                    </p>
                  )}

                  {proj.portfolio_goal_link && (
                    <p className="text-xs text-blue-700 bg-blue-50 rounded-lg px-2.5 py-1.5">
                      비전 연결: {proj.portfolio_goal_link}
                    </p>
                  )}

                  {proj.repo_url && (
                    <a
                      href={proj.repo_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline"
                    >
                      <Github className="w-3.5 h-3.5" />
                      <span>{proj.repo_url}</span>
                    </a>
                  )}

                  {(proj.tech_stack || []).length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {proj.tech_stack.map((tech, idx) => (
                        <span
                          key={idx}
                          className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700"
                        >
                          {tech}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between pt-3 border-t border-slate-100">
                  <button
                    type="button"
                    disabled={recapLoadingId === proj.id}
                    onClick={() => handleRecap(proj)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    <span>
                      {recapLoadingId === proj.id
                        ? "리캡 생성 중..."
                        : "포트폴리오 리캡"}
                    </span>
                  </button>

                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => openEditProject(proj)}
                      className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                      title="수정"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteProject(proj)}
                      className="p-1.5 rounded-lg text-slate-500 hover:bg-red-50 hover:text-red-600"
                      title="삭제"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Portfolio Recap Modal */}
      {recapModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[85vh] flex flex-col shadow-xl">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  {recapModal.project_name} — 포트폴리오 리캡
                </h3>
                <p className="text-xs text-slate-500">
                  반영된 STAR 경험 {recapModal.experience_count}건
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleCopyRecap}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  {copiedRecap ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-600" />
                      <span>복사됨</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5" />
                      <span>Markdown 복사</span>
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setRecapModal(null)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-800"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            <div className="p-6 overflow-y-auto prose prose-sm prose-slate max-w-none">
              <ReactMarkdown>{recapModal.markdown}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
