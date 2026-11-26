import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  FileUp,
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
import PortfolioDiagnosisPanel from "../components/PortfolioDiagnosisPanel.jsx";
import ProjectWorkspaceView from "../components/ProjectWorkspaceView.jsx";
import StepIndicator from "../components/StepIndicator.jsx";
import {
  DEFAULT_TRACKS,
  TRACK_SHORT_LABELS,
  getSkillsFieldLabel,
  getTrackBadgeClass,
} from "../utils/projectTracks.js";

const EMPTY_PROJECT_FORM = {
  name: "",
  period: "",
  role: "",
  summary: "",
  tech_stack_text: "",
  portfolio_goal_link: "",
  repo_url: "",
  project_types: ["engineering"],
  artifact_links: [],
};

export default function IdentityPortfolioPage({
  profile,
  projects,
  experienceSignature = "",
  onRefresh,
  onJumpToMiner,
}) {
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [tracks, setTracks] = useState(DEFAULT_TRACKS);
  const [filterTrack, setFilterTrack] = useState("all");

  // Career Identity
  const [profileForm, setProfileForm] = useState({
    career_vision: "",
    core_beliefs: "",
    target_roles: "",
    preferred_tone: "",
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileStatus, setProfileStatus] = useState("");
  const [showIdentityEditor, setShowIdentityEditor] = useState(false);

  // Unified 3-Tab Multi-Track Creation Hub
  const [createTab, setCreateTab] = useState("doc"); // "doc" | "github" | "manual"
  const [selectedTracks, setSelectedTracks] = useState(["engineering"]);

  // Tab 1: Document-to-Project Auto Generator
  const [docMode, setDocMode] = useState("file");
  const [docFile, setDocFile] = useState(null);
  const [docPastedText, setDocPastedText] = useState("");
  const [docPastedTitle, setDocPastedTitle] = useState("");
  const [docRoleHint, setDocRoleHint] = useState("");
  const [docExtraContext, setDocExtraContext] = useState("");
  const [docAnalyzing, setDocAnalyzing] = useState(false);

  // Tab 2: GitHub Auto Generator (SSE)
  const [ghUrl, setGhUrl] = useState("");
  const [ghRoleHint, setGhRoleHint] = useState("");
  const [ghExtraContext, setGhExtraContext] = useState("");
  const [showGhToken, setShowGhToken] = useState(false);
  const [ghToken, setGhToken] = useState("");
  const [ghSteps, setGhSteps] = useState([]);
  const [ghAnalyzing, setGhAnalyzing] = useState(false);

  // Shared Auto-Generated Draft Preview (for both Document & GitHub!)
  const [autoError, setAutoError] = useState("");
  const [autoDraft, setAutoDraft] = useState(null);
  const [autoProjectEdit, setAutoProjectEdit] = useState(EMPTY_PROJECT_FORM);
  const [autoSelectedExpIndices, setAutoSelectedExpIndices] = useState(new Set());
  const [autoPreviewTab, setAutoPreviewTab] = useState("sections");
  const [autoImporting, setAutoImporting] = useState(false);
  const [autoCopiedMd, setAutoCopiedMd] = useState(false);

  // Tab 3 / Edit Modal: Direct Project Create & Edit
  const [editingProjectId, setEditingProjectId] = useState(null);
  const [projectForm, setProjectForm] = useState(EMPTY_PROJECT_FORM);
  const [savingProject, setSavingProject] = useState(false);
  const [linkLabelInput, setLinkLabelInput] = useState("");
  const [linkUrlInput, setLinkUrlInput] = useState("");

  useEffect(() => {
    api
      .getProjectTemplates()
      .then((data) => {
        if (data?.tracks?.length) setTracks(data.tracks);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (profile) {
      setProfileForm({
        career_vision: profile.career_vision || "",
        core_beliefs: profile.core_beliefs || "",
        target_roles: profile.target_roles || "",
        preferred_tone: profile.preferred_tone || "",
      });
      if (!profile.career_vision && !profile.core_beliefs) {
        setShowIdentityEditor(true);
      }
    }
  }, [profile]);

  if (activeProjectId !== null) {
    return (
      <ProjectWorkspaceView
        projectId={activeProjectId}
        onBack={() => setActiveProjectId(null)}
        onGlobalRefresh={onRefresh}
        onJumpToMiner={onJumpToMiner}
      />
    );
  }

  const toggleTrackSelection = (trackId) => {
    setSelectedTracks((prev) => {
      if (prev.includes(trackId)) {
        return prev.length === 1 ? prev : prev.filter((t) => t !== trackId);
      }
      return [...prev, trackId];
    });
  };

  const estimatedSectionCount =
    2 +
    selectedTracks.reduce((sum, tId) => {
      const found = tracks.find((t) => t.id === tId);
      return sum + (found?.sections?.length || found?.section_count || 3);
    }, 0);

  const loadDraftIntoPreview = (res, sourceInfo) => {
    setAutoDraft({ ...res, _sourceInfo: sourceInfo });
    setAutoProjectEdit({
      name: res.project?.name || "",
      period: res.project?.period || "",
      role: res.project?.role || "",
      summary: res.project?.summary || "",
      tech_stack_text: (res.project?.tech_stack || []).join(", "),
      portfolio_goal_link: res.project?.portfolio_goal_link || "",
      repo_url: res.project?.repo_url || "",
      project_types: res.project?.project_types || selectedTracks,
      artifact_links: res.project?.artifact_links || [],
    });
    setAutoSelectedExpIndices(
      new Set((res.suggested_experiences || []).map((_, idx) => idx))
    );
    setAutoPreviewTab("sections");
    setAutoCopiedMd(false);
  };

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

  const handleAnalyzeDocument = async (e) => {
    e.preventDefault();
    if (docAnalyzing) return;
    setAutoError("");
    setAutoDraft(null);

    const formData = new FormData();
    if (docMode === "file") {
      if (!docFile) {
        setAutoError("업로드할 기획서·발표자료·보고서 파일을 선택해 주세요.");
        return;
      }
      formData.append("file", docFile);
    } else {
      if (!docPastedText.trim()) {
        setAutoError("문서 내용을 입력해 주세요.");
        return;
      }
      formData.append("pasted_text", docPastedText.trim());
      if (docPastedTitle.trim()) formData.append("doc_title", docPastedTitle.trim());
    }
    formData.append("project_types", JSON.stringify(selectedTracks));
    if (docRoleHint.trim()) formData.append("role_hint", docRoleHint.trim());
    if (docExtraContext.trim()) {
      formData.append("extra_context", docExtraContext.trim());
    }

    setDocAnalyzing(true);
    try {
      const res = await api.analyzeDocumentToProject(formData);
      loadDraftIntoPreview(res, {
        source_filename: res.source_meta?.filename || "uploaded-doc",
        source_type: res.source_meta?.source_type || "file_upload",
        source_format: res.source_meta?.file_format || "md",
        badge: `${res.source_meta?.filename} (${res.source_meta?.parse_info || ""})`,
      });
    } catch (err) {
      setAutoError(err.message);
    } finally {
      setDocAnalyzing(false);
    }
  };

  const handleAnalyzeGithub = async (e) => {
    e.preventDefault();
    if (!ghUrl.trim() || ghAnalyzing) return;
    setGhAnalyzing(true);
    setAutoError("");
    setAutoDraft(null);
    setGhSteps([]);

    try {
      await api.analyzeGithubStream(
        {
          repo_url: ghUrl.trim(),
          project_types: selectedTracks,
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
            loadDraftIntoPreview(res, {
              source_filename: res.project?.repo_url || ghUrl.trim(),
              source_type: "github_repo",
              source_format: "github",
              badge: `${res.repo_meta?.full_name} · 파일 ${res.repo_meta?.files_analyzed?.length || 0}개 · 커밋 ${res.repo_meta?.commits_sampled || 0}건`,
            });
          } else if (ev.event === "error") {
            setAutoError(ev.message);
            setGhSteps((prev) => [
              ...prev,
              { node: "error", status: "error", message: ev.message },
            ]);
          }
        }
      );
    } catch (err) {
      setAutoError(err.message);
    } finally {
      setGhAnalyzing(false);
    }
  };

  const handleImportAutoDraft = async () => {
    if (!autoDraft || autoImporting) return;
    setAutoImporting(true);
    try {
      const srcInfo = autoDraft._sourceInfo || {};
      const res = await api.importStructuredProject({
        project: {
          name: autoProjectEdit.name,
          period: autoProjectEdit.period,
          role: autoProjectEdit.role,
          summary: autoProjectEdit.summary,
          tech_stack: autoProjectEdit.tech_stack_text
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          portfolio_goal_link: autoProjectEdit.portfolio_goal_link,
          repo_url: autoProjectEdit.repo_url,
          project_types: autoProjectEdit.project_types || selectedTracks,
          artifact_links: autoProjectEdit.artifact_links || [],
        },
        sections: autoDraft.sections || [],
        experiences: [],
        source_filename: srcInfo.source_filename || "",
        source_type: srcInfo.source_type || "file_upload",
        source_format: srcInfo.source_format || "md",
        source_summary: srcInfo.badge || "",
      });
      setAutoDraft(null);
      setGhSteps([]);
      setDocFile(null);
      setDocPastedText("");
      setGhUrl("");
      setGhToken("");
      await onRefresh();
      setActiveProjectId(res.project.id);
    } catch (err) {
      alert(`포트폴리오 저장 실패: ${err.message}`);
    } finally {
      setAutoImporting(false);
    }
  };

  const handleCopyAutoMarkdown = async () => {
    if (!autoDraft?.portfolio_markdown) return;
    await navigator.clipboard.writeText(autoDraft.portfolio_markdown);
    setAutoCopiedMd(true);
    setTimeout(() => setAutoCopiedMd(false), 2000);
  };

  const openEditProject = (e, proj) => {
    e.stopPropagation();
    setEditingProjectId(proj.id);
    const pTypes = proj.project_types?.length ? proj.project_types : ["engineering"];
    setSelectedTracks(pTypes);
    setProjectForm({
      name: proj.name || "",
      period: proj.period || "",
      role: proj.role || "",
      summary: proj.summary || "",
      tech_stack_text: (proj.tech_stack || []).join(", "),
      portfolio_goal_link: proj.portfolio_goal_link || "",
      repo_url: proj.repo_url || "",
      project_types: pTypes,
      artifact_links: proj.artifact_links || [],
    });
    setCreateTab("manual");
  };

  const handleAddManualLink = () => {
    const url = linkUrlInput.trim();
    if (!url) return;
    setProjectForm((prev) => ({
      ...prev,
      artifact_links: [
        ...(prev.artifact_links || []),
        { label: linkLabelInput.trim() || url, url },
      ],
    }));
    setLinkLabelInput("");
    setLinkUrlInput("");
  };

  const handleSaveManualProject = async (e) => {
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
      project_types: selectedTracks,
      artifact_links: projectForm.artifact_links || [],
    };

    try {
      let saved;
      if (editingProjectId) {
        saved = await api.updateProject(editingProjectId, payload);
      } else {
        saved = await api.createProject(payload);
      }
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

  const filteredProjects =
    filterTrack === "all"
      ? projects
      : projects.filter((p) =>
          (p.project_types || ["engineering"]).includes(filterTrack)
        );

  const skillsPlaceholder = getSkillsFieldLabel(selectedTracks, tracks);
  const includesCodingTrack =
    selectedTracks.includes("engineering") || selectedTracks.includes("data_research");

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">2. 포트폴리오 &amp; 캐릭터</h2>
        <p className="text-sm text-slate-600 mt-1">
          6축 육각형 포트폴리오 캐릭터 진단(내적 3축 × 외적 3축, 강점 50% : 약점 50%)과{" "}
          <strong>복수 유형 조합형 프로젝트 워크스페이스</strong>를 한곳에서 관리합니다.
        </p>
      </div>

      {/* 6-Axis Portfolio Character & Dual Radar Diagnosis Dashboard */}
      <PortfolioDiagnosisPanel
        projectCount={projects.length}
        experienceSignature={experienceSignature}
        onJumpToMiner={onJumpToMiner}
        onOpenProject={(pid) => setActiveProjectId(pid)}
      />

      {/* Registered Portfolio Projects Hub with Multi-Track Filter */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-slate-900">
              등록된 포트폴리오 프로젝트 ({filteredProjects.length})
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              프로젝트 카드를 클릭하면 <strong>트랙별 섹션 편집 · 문서 자동 업데이트 · AI 노이즈 정리</strong> 워크스페이스가 열립니다.
            </p>
          </div>

          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setFilterTrack("all")}
              className={`rounded-full px-3 py-1 text-xs font-semibold border ${
                filterTrack === "all"
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
            >
              전체 ({projects.length})
            </button>
            {tracks.map((tr) => {
              const cnt = projects.filter((p) =>
                (p.project_types || ["engineering"]).includes(tr.id)
              ).length;
              return (
                <button
                  key={tr.id}
                  type="button"
                  onClick={() => setFilterTrack(tr.id)}
                  className={`rounded-full px-3 py-1 text-xs font-semibold border ${
                    filterTrack === tr.id
                      ? "bg-slate-900 text-white border-slate-900"
                      : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  {tr.short_label} ({cnt})
                </button>
              );
            })}
          </div>
        </div>

        {filteredProjects.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
            해당 유형의 프로젝트가 아직 없습니다. 아래 <strong>새 포트폴리오 만들기</strong>에서 원하는 유형을 조합해 만들어 보세요.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredProjects.map((proj) => {
              const pTypes = proj.project_types || ["engineering"];
              return (
                <div
                  key={proj.id}
                  onClick={() => setActiveProjectId(proj.id)}
                  className="group cursor-pointer rounded-2xl border border-slate-200 hover:border-indigo-400 bg-white p-5 flex flex-col justify-between gap-4 shadow-sm hover:shadow-md transition-all"
                >
                  <div className="space-y-2.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {pTypes.map((tId) => (
                        <span
                          key={tId}
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${getTrackBadgeClass(tId)}`}
                        >
                          {TRACK_SHORT_LABELS[tId] || tId}
                        </span>
                      ))}
                    </div>

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
                          섹션 {proj.filled_section_count || 0}/{proj.total_section_count || 0}
                        </span>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
                          STAR {proj.experience_count}
                        </span>
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
                      <span>워크스페이스 열기</span>
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
              );
            })}
          </div>
        )}
      </div>

      {/* Unified Multi-Track Portfolio Creation Hub (3 Tabs) */}
      <section className="rounded-2xl border border-indigo-200 bg-gradient-to-br from-white to-indigo-50/35 p-6 space-y-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-indigo-600" />
              <span>
                {editingProjectId
                  ? "프로젝트 기본 정보 수정"
                  : "새 포트폴리오 만들기 (복수 유형 조합 지원)"}
              </span>
            </h3>
            <p className="text-xs text-slate-600 mt-0.5">
              한 프로젝트에서 기획+개발, 데이터+개발 등 여러 역할을 했다면 <strong>유형을 여러 개 동시에 선택</strong>하세요. 공통 코어 + 선택한 트랙 섹션이 중복 없이 자동 조합됩니다.
            </p>
          </div>
          {editingProjectId && (
            <button
              type="button"
              onClick={() => {
                setEditingProjectId(null);
                setProjectForm(EMPTY_PROJECT_FORM);
              }}
              className="text-xs text-slate-500 hover:text-slate-900 underline"
            >
              수정 취소
            </button>
          )}
        </div>

        {/* Multi-Select Project Type Picker */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-slate-700">
              1단계: 이 프로젝트에서 수행한 유형 선택 (복수 선택 가능)
            </span>
            <span className="text-indigo-700 font-semibold">
              자동 구성 섹션: 총 {estimatedSectionCount}개 (공통 2 + 선택 트랙)
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
            {tracks.map((tr) => {
              const active = selectedTracks.includes(tr.id);
              return (
                <button
                  key={tr.id}
                  type="button"
                  onClick={() => toggleTrackSelection(tr.id)}
                  className={`rounded-xl border p-3 text-left transition-all ${
                    active
                      ? "border-indigo-500 bg-indigo-50/70 ring-2 ring-indigo-500/20"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-bold text-slate-900">
                      {tr.short_label}
                    </span>
                    {active && <Check className="w-3.5 h-3.5 text-indigo-600" />}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1 line-clamp-2">
                    {tr.description}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        {/* 3 Creation Mode Tabs */}
        <div className="inline-flex flex-wrap rounded-xl border border-slate-200 bg-white p-1 text-xs font-semibold">
          <button
            type="button"
            onClick={() => {
              setCreateTab("doc");
              setEditingProjectId(null);
            }}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 ${
              createTab === "doc"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            <FileUp className="w-3.5 h-3.5" />
            <span>문서·발표자료로 자동 생성 (전 유형)</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setCreateTab("github");
              setEditingProjectId(null);
            }}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 ${
              createTab === "github"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            <Github className="w-3.5 h-3.5" />
            <span>GitHub 링크로 자동 생성 (개발·데이터)</span>
          </button>
          <button
            type="button"
            onClick={() => setCreateTab("manual")}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 ${
              createTab === "manual"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            <Plus className="w-3.5 h-3.5" />
            <span>{editingProjectId ? "기본 정보 수정" : "직접 만들기 (AI 없이 즉시 가능)"}</span>
          </button>
        </div>

        {/* Tab 1: Document / PPTX / PDF Auto Generator */}
        {createTab === "doc" && (
          <form onSubmit={handleAnalyzeDocument} className="space-y-3">
            <div className="inline-flex rounded-lg bg-white border border-slate-200 p-0.5 text-xs font-medium">
              <button
                type="button"
                onClick={() => setDocMode("file")}
                className={`rounded-md px-3 py-1 ${
                  docMode === "file" ? "bg-indigo-600 text-white" : "text-slate-600"
                }`}
              >
                파일 업로드 (.pptx · .pdf · .docx · .md · .ipynb)
              </button>
              <button
                type="button"
                onClick={() => setDocMode("paste")}
                className={`rounded-md px-3 py-1 ${
                  docMode === "paste" ? "bg-indigo-600 text-white" : "text-slate-600"
                }`}
              >
                텍스트 붙여넣기
              </button>
            </div>

            {docMode === "file" ? (
              <label className="block rounded-xl border-2 border-dashed border-slate-300 hover:border-indigo-400 bg-white p-5 text-center cursor-pointer">
                <input
                  type="file"
                  accept=".pdf,.docx,.pptx,.md,.markdown,.txt,.ipynb,.py,.js,.ts,.sql,.json"
                  onChange={(e) => setDocFile(e.target.files?.[0] || null)}
                  className="hidden"
                />
                <FileUp className="w-6 h-6 mx-auto text-indigo-600 mb-1.5" />
                {docFile ? (
                  <span className="text-sm font-semibold text-slate-900">
                    선택됨: {docFile.name} ({(docFile.size / 1024).toFixed(1)} KB)
                  </span>
                ) : (
                  <span className="text-xs text-slate-600">
                    기획서(.pdf/.docx), 발표자료(.pptx), 분석 노트(.ipynb/.md)를 클릭해 선택하세요
                  </span>
                )}
              </label>
            ) : (
              <div className="space-y-2">
                <input
                  type="text"
                  value={docPastedTitle}
                  onChange={(e) => setDocPastedTitle(e.target.value)}
                  placeholder="문서 제목 (예: 공모전 최종 기획안)"
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
                />
                <textarea
                  rows={4}
                  value={docPastedText}
                  onChange={(e) => setDocPastedText(e.target.value)}
                  placeholder="기획안, 활동 보고서, 분석 결과, 회고 메모 등을 붙여넣으세요..."
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
                />
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                type="text"
                value={docRoleHint}
                onChange={(e) => setDocRoleHint(e.target.value)}
                placeholder="본인 역할 힌트 (예: PM & 데이터 분석)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
              />
              <input
                type="text"
                value={docExtraContext}
                onChange={(e) => setDocExtraContext(e.target.value)}
                placeholder="강조할 성과/배경 메모 (선택)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={docAnalyzing}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {docAnalyzing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>문서 구조화 중...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    <span>문서로 포트폴리오 자동 생성</span>
                  </>
                )}
              </button>
            </div>
          </form>
        )}

        {/* Tab 2: GitHub Auto Generator */}
        {createTab === "github" && (
          <form onSubmit={handleAnalyzeGithub} className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                required
                type="text"
                value={ghUrl}
                onChange={(e) => setGhUrl(e.target.value)}
                placeholder="https://github.com/owner/repo *"
                className="md:col-span-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm"
              />
              <input
                type="text"
                value={ghRoleHint}
                onChange={(e) => setGhRoleHint(e.target.value)}
                placeholder="본인 역할 힌트 (예: 기획 + 백엔드)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
              />
            </div>

            <div className="flex flex-col sm:flex-row gap-3">
              <input
                type="text"
                value={ghExtraContext}
                onChange={(e) => setGhExtraContext(e.target.value)}
                placeholder="강조하고 싶은 성과/트러블슈팅 메모 (선택)"
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
                <span>Private 레포 / 한도 우회용 1회용 GitHub 토큰 (선택 · 저장 안 됨)</span>
              </button>
              {showGhToken && (
                <input
                  type="password"
                  value={ghToken}
                  onChange={(e) => setGhToken(e.target.value)}
                  placeholder="ghp_..."
                  className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs"
                />
              )}
            </div>

            <StepIndicator steps={ghSteps} />
          </form>
        )}

        {/* Tab 3: Direct Manual Project Create / Edit */}
        {createTab === "manual" && (
          <form
            onSubmit={handleSaveManualProject}
            className="rounded-xl border border-slate-200 bg-white p-5 space-y-3"
          >
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
                placeholder="담당 역할 (예: 팀장 · 서비스 기획 · 백엔드)"
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </div>

            <textarea
              rows={2}
              value={projectForm.summary}
              onChange={(e) =>
                setProjectForm({ ...projectForm, summary: e.target.value })
              }
              placeholder="프로젝트 핵심 요약 (공통 '개요 & 문제 정의' 섹션에도 자동 초기 입력됩니다)"
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
                placeholder={`${skillsPlaceholder} (쉼표 구분)`}
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
              {includesCodingTrack ? (
                <input
                  type="text"
                  value={projectForm.repo_url}
                  onChange={(e) =>
                    setProjectForm({ ...projectForm, repo_url: e.target.value })
                  }
                  placeholder="GitHub 저장소 URL (선택)"
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
                />
              ) : (
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
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
                />
              )}
            </div>

            {includesCodingTrack && (
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
            )}

            {/* Artifact Links (Figma, Notion, Slides, Blog, Paper, etc.) */}
            <div className="space-y-2 pt-1">
              <div className="text-xs font-semibold text-slate-600">
                참고 링크 추가 (Figma, Notion, 발표자료, 블로그, 논문 등 — 선택)
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  type="text"
                  value={linkLabelInput}
                  onChange={(e) => setLinkLabelInput(e.target.value)}
                  placeholder="이름 (예: 발표자료)"
                  className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs w-40"
                />
                <input
                  type="text"
                  value={linkUrlInput}
                  onChange={(e) => setLinkUrlInput(e.target.value)}
                  placeholder="https://..."
                  className="flex-1 min-w-[180px] rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
                />
                <button
                  type="button"
                  onClick={handleAddManualLink}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  + 추가
                </button>
              </div>
              {(projectForm.artifact_links || []).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {projectForm.artifact_links.map((lk, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] text-indigo-800"
                    >
                      <span>{lk.label}</span>
                      <button
                        type="button"
                        onClick={() =>
                          setProjectForm((prev) => ({
                            ...prev,
                            artifact_links: prev.artifact_links.filter((_, idx) => idx !== i),
                          }))
                        }
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={savingProject}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                <span>
                  {savingProject
                    ? "저장 중..."
                    : editingProjectId
                      ? "기본 정보 저장"
                      : `프로젝트 생성 (${estimatedSectionCount}개 섹션 자동 세팅)`}
                </span>
              </button>
            </div>
          </form>
        )}

        {autoError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-800">
            {autoError}
          </div>
        )}

        {/* Shared Auto-Generated Multi-Track Draft Preview */}
        {autoDraft && (
          <div className="rounded-xl border border-indigo-200 bg-white p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <span className="font-bold text-slate-900">
                  {autoDraft._sourceInfo?.badge || "자동 분석 결과"}
                </span>
                {(autoProjectEdit.project_types || []).map((tId) => (
                  <span
                    key={tId}
                    className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${getTrackBadgeClass(tId)}`}
                  >
                    {TRACK_SHORT_LABELS[tId] || tId}
                  </span>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setAutoDraft(null)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                type="text"
                value={autoProjectEdit.name}
                onChange={(e) =>
                  setAutoProjectEdit({ ...autoProjectEdit, name: e.target.value })
                }
                placeholder="프로젝트명"
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
              />
              <input
                type="text"
                value={autoProjectEdit.period}
                onChange={(e) =>
                  setAutoProjectEdit({ ...autoProjectEdit, period: e.target.value })
                }
                placeholder="개발/진행 기간"
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
              />
              <input
                type="text"
                value={autoProjectEdit.role}
                onChange={(e) =>
                  setAutoProjectEdit({ ...autoProjectEdit, role: e.target.value })
                }
                placeholder="담당 역할"
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
              />
            </div>

            <textarea
              rows={2}
              value={autoProjectEdit.summary}
              onChange={(e) =>
                setAutoProjectEdit({ ...autoProjectEdit, summary: e.target.value })
              }
              className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <input
                type="text"
                value={autoProjectEdit.tech_stack_text}
                onChange={(e) =>
                  setAutoProjectEdit({
                    ...autoProjectEdit,
                    tech_stack_text: e.target.value,
                  })
                }
                placeholder={`${skillsPlaceholder} (쉼표 구분)`}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
              />
              <input
                type="text"
                value={autoProjectEdit.portfolio_goal_link}
                onChange={(e) =>
                  setAutoProjectEdit({
                    ...autoProjectEdit,
                    portfolio_goal_link: e.target.value,
                  })
                }
                placeholder="나의 커리어 비전 연결점"
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
              />
            </div>

            <div className="pt-2 border-t border-slate-100 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="inline-flex rounded-lg bg-slate-100 p-1 text-xs font-semibold">
                  <button
                    type="button"
                    onClick={() => setAutoPreviewTab("sections")}
                    className={`rounded-md px-3 py-1 inline-flex items-center gap-1 ${
                      autoPreviewTab === "sections"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-600"
                    }`}
                  >
                    <Layers className="w-3.5 h-3.5" />
                    <span>멀티트랙 섹션 ({autoDraft.sections?.length || 0})</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setAutoPreviewTab("markdown")}
                    className={`rounded-md px-3 py-1 ${
                      autoPreviewTab === "markdown"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-600"
                    }`}
                  >
                    전체 Markdown
                  </button>
                </div>

                {autoPreviewTab === "markdown" && (
                  <button
                    type="button"
                    onClick={handleCopyAutoMarkdown}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50"
                  >
                    {autoCopiedMd ? (
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

              {autoPreviewTab === "sections" ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-80 overflow-y-auto pr-1">
                  {(autoDraft.sections || []).map((sec, idx) => (
                    <div
                      key={idx}
                      className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5 space-y-1.5 text-xs"
                    >
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${getTrackBadgeClass(sec.track)}`}
                        >
                          {TRACK_SHORT_LABELS[sec.track] || sec.track}
                        </span>
                        <span className="font-bold text-slate-900">{sec.title}</span>
                      </div>
                      <div className="prose prose-xs prose-slate max-w-none text-slate-700">
                        <ReactMarkdown>
                          {sec.content || "_(내용 없음 — 저장 후 워크스페이스에서 보강 가능)_"}
                        </ReactMarkdown>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 max-h-80 overflow-y-auto prose prose-sm prose-slate max-w-none">
                  <ReactMarkdown>{autoDraft.portfolio_markdown || ""}</ReactMarkdown>
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
              <span className="text-[11px] text-slate-500">
                * 경험(STAR-L)은 자동 생성되지 않으며, 저장 후 <strong>3. 경험 채굴</strong>에서 직접 입력하거나 PR·커밋 Diff로 채굴합니다.
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setAutoDraft(null)}
                  className="rounded-lg border border-slate-200 px-3.5 py-2 text-xs font-medium text-slate-700"
                >
                  취소
                </button>
                <button
                  type="button"
                  disabled={autoImporting || !autoProjectEdit.name.trim()}
                  onClick={handleImportAutoDraft}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  <Save className="w-3.5 h-3.5" />
                  <span>
                    {autoImporting
                      ? "저장 중..."
                      : `프로젝트 + 섹션 ${autoDraft.sections?.length || 0}개 저장 후 열기`}
                  </span>
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
