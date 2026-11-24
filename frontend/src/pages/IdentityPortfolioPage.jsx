import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  FolderOpen,
  Github,
  KeyRound,
  Layers,
  Loader2,
  Pencil,
  Plus,
  Save,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api/client.js";
import ProjectWorkspaceView from "../components/ProjectWorkspaceView.jsx";
import StepIndicator from "../components/StepIndicator.jsx";

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
  // Opened project workspace ID (null = overview list)
  const [activeProjectId, setActiveProjectId] = useState(null);

  const [profileForm, setProfileForm] = useState({
    career_vision: "",
    core_beliefs: "",
    target_roles: "",
    preferred_tone: "",
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileStatus, setProfileStatus] = useState("");
  const [showIdentityEditor, setShowIdentityEditor] = useState(true);

  // GitHub Auto Portfolio Analyzer (SSE)
  const [ghUrl, setGhUrl] = useState("");
  const [ghRoleHint, setGhRoleHint] = useState("");
  const [ghExtraContext, setGhExtraContext] = useState("");
  const [showGhToken, setShowGhToken] = useState(false);
  const [ghToken, setGhToken] = useState("");
  const [ghSteps, setGhSteps] = useState([]);
  const [ghAnalyzing, setGhAnalyzing] = useState(false);
  const [ghError, setGhError] = useState("");
  const [ghDraft, setGhDraft] = useState(null);
  const [ghProjectEdit, setGhProjectEdit] = useState(EMPTY_PROJECT_FORM);
  const [ghSelectedExpIndices, setGhSelectedExpIndices] = useState(new Set());
  const [ghPreviewTab, setGhPreviewTab] = useState("sections");
  const [ghImporting, setGhImporting] = useState(false);
  const [ghCopiedMd, setGhCopiedMd] = useState(false);

  const [showProjectForm, setShowProjectForm] = useState(false);
  const [editingProjectId, setEditingProjectId] = useState(null);
  const [projectForm, setProjectForm] = useState(EMPTY_PROJECT_FORM);
  const [savingProject, setSavingProject] = useState(false);

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

  if (activeProjectId !== null) {
    return (
      <ProjectWorkspaceView
        projectId={activeProjectId}
        onBack={() => setActiveProjectId(null)}
        onGlobalRefresh={onRefresh}
      />
    );
  }

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
    setGhSteps([]);
    setGhCopiedMd(false);

    try {
      await api.analyzeGithubStream(
        {
          repo_url: ghUrl.trim(),
          github_token: ghToken.trim(),
          role_hint: ghRoleHint.trim(),
          extra_context: ghExtraContext.trim(),
        },
        (ev) => {
          if (ev.event === "node_start") {
            setGhSteps((prev) => [
              ...prev,
              { node: ev.node, status: "running", message: ev.message },
            ]);
          } else if (ev.event === "node_end") {
            setGhSteps((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i -= 1) {
                if (next[i].node === ev.node || next[i].status === "running") {
                  let badge;
                  if (ev.data?.file_count !== undefined) {
                    badge = `파일 ${ev.data.file_count}개 분석`;
                  } else if (ev.data?.section_count !== undefined) {
                    badge = `섹션 ${ev.data.section_count}개`;
                  }
                  next[i] = { ...next[i], node: ev.node, status: "done", badge };
                  break;
                }
              }
              return next;
            });
          } else if (ev.event === "done") {
            const res = ev.data;
            setGhDraft(res);
            setGhProjectEdit({
              name: res.project?.name || "",
              period: res.project?.period || "",
              role: res.project?.role || "",
              summary: res.project?.summary || "",
              tech_stack_text: (res.project?.tech_stack || []).join(", "),
              portfolio_goal_link: res.project?.portfolio_goal_link || "",
              repo_url: res.project?.repo_url || ghUrl.trim(),
            });
            setGhSelectedExpIndices(
              new Set((res.suggested_experiences || []).map((_, idx) => idx))
            );
            setGhPreviewTab("sections");
          } else if (ev.event === "error") {
            setGhError(ev.message);
            setGhSteps((prev) => [
              ...prev,
              { node: "error", status: "error", message: ev.message },
            ]);
          }
        }
      );
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
        sections: ghDraft.sections || [],
        experiences: selectedExps,
      });
      setGhDraft(null);
      setGhSteps([]);
      setGhUrl("");
      setGhRoleHint("");
      setGhExtraContext("");
      setGhToken("");
      await onRefresh();
      setActiveProjectId(res.project.id);
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

  const openEditProject = (e, proj) => {
    e.stopPropagation();
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
      let saved;
      if (editingProjectId) {
        saved = await api.updateProject(editingProjectId, payload);
      } else {
        saved = await api.createProject(payload);
      }
      setShowProjectForm(false);
      setEditingProjectId(null);
      setProjectForm(EMPTY_PROJECT_FORM);
      await onRefresh();
      if (!editingProjectId && saved?.id) {
        setActiveProjectId(saved.id);
      }
    } catch (err) {
      alert(`프로젝트 저장 실패: ${err.message}`);
    } finally {
      setSavingProject(false);
    }
  };

  const handleDeleteProject = async (e, proj) => {
    e.stopPropagation();
    if (!window.confirm(`'${proj.name}' 프로젝트와 모든 섹션을 삭제할까요?`)) {
      return;
    }
    try {
      await api.deleteProject(proj.id);
      await onRefresh();
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">1. 신념 &amp; 포트폴리오</h2>
        <p className="text-sm text-slate-600 mt-1">
          나의 커리어 신념을 설정하고, 등록된 프로젝트를 열어 6개 모듈 섹션·문서 자동 업데이트·불필요 내용 정리까지 체계적으로 관리합니다.
        </p>
      </div>

      {/* Collapsible Career Identity Card */}
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <button
          type="button"
          onClick={() => setShowIdentityEditor((v) => !v)}
          className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-slate-50/70"
        >
          <div>
            <h3 className="text-base font-bold text-slate-900">
              커리어 정체성 (신념 · 비전 · 선호 문체)
            </h3>
            {!showIdentityEditor && profileForm.career_vision && (
              <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">
                {profileForm.target_roles ? `[${profileForm.target_roles}] ` : ""}
                {profileForm.career_vision}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {profileStatus && (
              <span className="text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-0.5">
                {profileStatus}
              </span>
            )}
            {showIdentityEditor ? (
              <ChevronUp className="w-4 h-4 text-slate-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-slate-400" />
            )}
          </div>
        </button>

        {showIdentityEditor && (
          <form
            onSubmit={handleSaveProfile}
            className="px-6 pb-6 pt-2 border-t border-slate-100 space-y-4"
          >
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
                rows={2}
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
        )}
      </div>

      {/* Registered Portfolio Projects Hub */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-base font-bold text-slate-900">
              등록된 포트폴리오 프로젝트 ({projects.length})
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              프로젝트 카드를 클릭하면 <strong>6개 모듈 섹션 편집 · 파일/문서 자동 업데이트 · 쓸데없는 내용 정리</strong> 워크스페이스가 열립니다.
            </p>
          </div>
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
                {editingProjectId ? "프로젝트 기본 정보 수정" : "새 프로젝트 등록"}
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
            등록된 프로젝트가 없습니다. 아래 <strong>GitHub 링크 자동 분석</strong> 또는 상단의 <strong>직접 프로젝트 추가</strong>로 첫 포트폴리오를 만들어 보세요.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {projects.map((proj) => (
              <div
                key={proj.id}
                onClick={() => setActiveProjectId(proj.id)}
                className="group cursor-pointer rounded-2xl border border-slate-200 hover:border-indigo-400 bg-white p-5 flex flex-col justify-between gap-4 shadow-sm hover:shadow-md transition-all"
              >
                <div className="space-y-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h4 className="text-base font-bold text-slate-900 group-hover:text-indigo-700 transition-colors">
                        {proj.name}
                      </h4>
                      <p className="text-xs text-slate-500">
                        {[proj.period, proj.role].filter(Boolean).join(" · ") ||
                          "기간/역할 미입력"}
                      </p>
                    </div>
                    <div className="flex flex-wrap justify-end gap-1 shrink-0">
                      <span className="rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                        섹션 {proj.filled_section_count || 0}/{proj.total_section_count || 6}
                      </span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
                        STAR {proj.experience_count}
                      </span>
                      {proj.document_count > 0 && (
                        <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-700">
                          문서 {proj.document_count}
                        </span>
                      )}
                    </div>
                  </div>

                  {proj.summary && (
                    <p className="text-sm text-slate-700 leading-relaxed line-clamp-2">
                      {proj.summary}
                    </p>
                  )}

                  {(proj.tech_stack || []).length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {proj.tech_stack.slice(0, 7).map((tech, idx) => (
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
                  <span className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 group-hover:bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors">
                    <FolderOpen className="w-3.5 h-3.5" />
                    <span>워크스페이스 열기 · 문서 업데이트</span>
                  </span>

                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={(e) => openEditProject(e, proj)}
                      className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                      title="기본 정보 수정"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => handleDeleteProject(e, proj)}
                      className="p-1.5 rounded-lg text-slate-500 hover:bg-red-50 hover:text-red-600"
                      title="프로젝트 삭제"
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

      {/* GitHub Repo Auto Portfolio Generator (Upgraded SSE + 6 Modular Sections) */}
      <section className="rounded-2xl border border-indigo-200 bg-gradient-to-br from-white to-indigo-50/40 p-6 space-y-4 shadow-sm">
        <div>
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Github className="w-5 h-5 text-indigo-700" />
            <span>GitHub 링크로 6개 모듈 포트폴리오 자동 생성</span>
          </h3>
          <p className="text-xs text-slate-600 mt-1">
            GitHub 저장소 URL(또는 <code>owner/repo</code>)을 입력하면 전체 파일 트리·핵심 코드·README·커밋을 분석해 6개 엔지니어링 섹션과 STAR 초안을 자동 구성합니다. (API Rate Limit 방어 적용)
          </p>
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
              placeholder="본인 역할 힌트 (선택: 예: 백엔드 & 데이터)"
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
                  <span>저장소 딥 분석 중...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  <span>GitHub 자동 분석</span>
                </>
              )}
            </button>
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowGhToken((v) => !v)}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500 hover:text-indigo-700"
            >
              <KeyRound className="w-3 h-3" />
              <span>비공개(Private) 저장소 / API 한도 우회용 1회용 토큰 입력 (선택 · 저장 안 됨)</span>
            </button>
            {showGhToken && (
              <input
                type="password"
                value={ghToken}
                onChange={(e) => setGhToken(e.target.value)}
                placeholder="ghp_... (요청 1회에만 사용되며 DB에 저장되지 않습니다)"
                className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs"
              />
            )}
          </div>
        </form>

        <StepIndicator steps={ghSteps} />

        {ghError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-800">
            {ghError}
          </div>
        )}

        {/* GitHub Analysis Editable Preview */}
        {ghDraft && (
          <div className="rounded-xl border border-indigo-200 bg-white p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <span className="font-bold text-slate-900">
                  {ghDraft.repo_meta?.full_name}
                </span>
                <span>·</span>
                <span>트리 {ghDraft.repo_meta?.total_files_in_tree || 0}개 파일 중 핵심 {ghDraft.repo_meta?.files_analyzed?.length || 0}개 분석</span>
                <span>·</span>
                <span>커밋 {ghDraft.repo_meta?.commits_sampled || 0}건</span>
              </div>
              <button
                type="button"
                onClick={() => setGhDraft(null)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <label className="block space-y-1">
                <span className="text-[11px] font-semibold text-slate-600">프로젝트명</span>
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
                <span className="text-[11px] font-semibold text-slate-600">개발 기간</span>
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
                <span className="text-[11px] font-semibold text-slate-600">담당 역할</span>
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
              <span className="text-[11px] font-semibold text-slate-600">프로젝트 핵심 요약</span>
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

            {/* Preview Tabs: 6 Modular Sections / STAR / Markdown */}
            <div className="pt-2 border-t border-slate-100 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="inline-flex rounded-lg bg-slate-100 p-1 text-xs font-semibold">
                  <button
                    type="button"
                    onClick={() => setGhPreviewTab("sections")}
                    className={`rounded-md px-3 py-1 inline-flex items-center gap-1 ${
                      ghPreviewTab === "sections"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-600"
                    }`}
                  >
                    <Layers className="w-3.5 h-3.5" />
                    <span>6개 모듈 섹션 ({ghDraft.sections?.length || 0})</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setGhPreviewTab("star")}
                    className={`rounded-md px-3 py-1 ${
                      ghPreviewTab === "star"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-600"
                    }`}
                  >
                    STAR 경험 ({ghDraft.suggested_experiences?.length || 0})
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
                    전체 Markdown
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
                        <span>복사</span>
                      </>
                    )}
                  </button>
                )}
              </div>

              {ghPreviewTab === "sections" ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-80 overflow-y-auto pr-1">
                  {(ghDraft.sections || []).map((sec, idx) => (
                    <div
                      key={idx}
                      className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5 space-y-1.5 text-xs"
                    >
                      <div className="font-bold text-slate-900">{sec.title}</div>
                      <div className="prose prose-xs prose-slate max-w-none text-slate-700">
                        <ReactMarkdown>
                          {sec.content || "_(내용 없음 — 저장 후 워크스페이스에서 문서 업로드로 보강 가능)_"}
                        </ReactMarkdown>
                      </div>
                    </div>
                  ))}
                </div>
              ) : ghPreviewTab === "star" ? (
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
                    : `프로젝트 + 6개 섹션 + STAR ${ghSelectedExpIndices.size}건 저장 후 열기`}
                </span>
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
