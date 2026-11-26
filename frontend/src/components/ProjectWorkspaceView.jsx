import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  ArrowLeft,
  BookOpen,
  Check,
  Copy,
  Download,
  Eraser,
  ExternalLink,
  Eye,
  FileCode2,
  FileText,
  FileUp,
  FolderOpen,
  FolderSync,
  Github,
  HelpCircle,
  Layers,
  Link2,
  Loader2,
  Paperclip,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api/client.js";
import ExperienceDetailModal from "./ExperienceDetailModal.jsx";
import ExperienceProjectSyncModal from "./ExperienceProjectSyncModal.jsx";
import RadarChart, { RubricReferenceModal } from "./RadarChart.jsx";
import StarMeter from "./StarMeter.jsx";
import {
  DEFAULT_TRACKS,
  TRACK_SHORT_LABELS,
  getTrackBadgeClass,
  groupSectionsByTrack,
} from "../utils/projectTracks.js";

const STAR_RADAR_LABELS = [
  { id: "situation", label: "S 상황" },
  { id: "task", label: "T 책임" },
  { id: "action", label: "A 행동" },
  { id: "result", label: "R 성과" },
  { id: "learning", label: "L 회고" },
];

const DEFAULT_SEC_AI = {
  open: false,
  mode: "file", // "file" | "text"
  strategy: "merge", // "merge" | "replace" | "append"
  file: null,
  pastedText: "",
  instruction: "",
  ingesting: false,
  error: "",
  proposal: null,
  applying: false,
};

export default function ProjectWorkspaceView({
  projectId,
  onBack,
  onGlobalRefresh,
  onJumpToMiner = null,
}) {
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Active navigation inside workspace: "section:<id>" | "stars" | "retro" | "docs"
  const [activeKey, setActiveKey] = useState("");
  const [sectionDrafts, setSectionDrafts] = useState(() => {
    try {
      const raw = window.localStorage.getItem(`proj_drafts_${projectId}`);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  });
  const [sectionViewMode, setSectionViewMode] = useState("edit");
  const [savingSection, setSavingSection] = useState(false);
  const [savingAllDirty, setSavingAllDirty] = useState(false);
  const [sectionStatusById, setSectionStatusById] = useState({});

  // Section-Scoped Document AI Update State Map keyed by section.id (QA #3)
  const [secAiStates, setSecAiStates] = useState(() => {
    try {
      const raw = window.sessionStorage.getItem(`proj_sec_ai_${projectId}`);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      const hydrated = {};
      Object.entries(parsed).forEach(([k, v]) => {
        hydrated[k] = { ...DEFAULT_SEC_AI, ...v, file: null, ingesting: false, applying: false };
      });
      return hydrated;
    } catch {
      return {};
    }
  });

  // Add custom section & Add Track Pack & Add Artifact Link
  const [showAddSection, setShowAddSection] = useState(false);
  const [newSecTitle, setNewSecTitle] = useState("");
  const [showAddTrack, setShowAddTrack] = useState(false);
  const [addingTrack, setAddingTrack] = useState(false);
  const [showAddLink, setShowAddLink] = useState(false);
  const [newLinkLabel, setNewLinkLabel] = useState("");
  const [newLinkUrl, setNewLinkUrl] = useState("");

  // Document / GitHub Sync Update Modal
  const [showIngestModal, setShowIngestModal] = useState(false);
  const [ingestMode, setIngestMode] = useState("file");
  const [uploadFile, setUploadFile] = useState(null);
  const [pastedText, setPastedText] = useState("");
  const [pastedTitle, setPastedTitle] = useState("");
  const [ingestInstruction, setIngestInstruction] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState("");

  // Diff Review State
  const [updateProposal, setUpdateProposal] = useState(null);
  const [selectedUpdateIndices, setSelectedUpdateIndices] = useState(new Set());
  const [selectedExpIndices, setSelectedExpIndices] = useState(new Set());
  const [applySummary, setApplySummary] = useState(true);
  const [applyTechStack, setApplyTechStack] = useState(true);
  const [applyingUpdates, setApplyingUpdates] = useState(false);
  const [syncingGithub, setSyncingGithub] = useState(false);

  // AI Noise Prune Modal
  const [pruning, setPruning] = useState(false);
  const [pruneProposal, setPruneProposal] = useState(null);
  const [selectedPruneIds, setSelectedPruneIds] = useState(new Set());
  const [applyingPrune, setApplyingPrune] = useState(false);

  // Full Export / Recap Modal
  const [markdownModal, setMarkdownModal] = useState(null);
  const [recapLoading, setRecapLoading] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);

  // Opt-in STAR Deepening Interview & 5-Axis Evaluation State
  const [dismissedStarBanner, setDismissedStarBanner] = useState(false);
  const [showStarOnboarding, setShowStarOnboarding] = useState(false);
  const [loadingStarQs, setLoadingStarQs] = useState(false);
  const [starOnboardingData, setStarOnboardingData] = useState(null);
  const [starAnswers, setStarAnswers] = useState({});
  const [applyOnboardingPatches, setApplyOnboardingPatches] = useState(true);
  const [submittingStarOnboarding, setSubmittingStarOnboarding] = useState(false);
  const [onboardingError, setOnboardingError] = useState("");
  const [evaluatingStars, setEvaluatingStars] = useState(false);
  const [detailExp, setDetailExp] = useState(null);
  const [syncExp, setSyncExp] = useState(null);
  const [rubricRef, setRubricRef] = useState(null);
  const [showRubricModal, setShowRubricModal] = useState(false);

  // Project Retrospective Interview & Cross-Project Learning Loop State
  const [retroFramework, setRetroFramework] = useState("kpt");
  const [retroQs, setRetroQs] = useState(null);
  const [retroAnswers, setRetroAnswers] = useState({});
  const [loadingRetroQs, setLoadingRetroQs] = useState(false);
  const [submittingRetro, setSubmittingRetro] = useState(false);
  const [syncRetroToOutcomes, setSyncRetroToOutcomes] = useState(true);
  const [retroError, setRetroError] = useState("");

  // Persist per-section unsaved drafts & AI memo inputs across section/page switches (QA #3)
  useEffect(() => {
    try {
      window.localStorage.setItem(`proj_drafts_${projectId}`, JSON.stringify(sectionDrafts));
    } catch {
      // ignore storage quota errors
    }
  }, [projectId, sectionDrafts]);

  useEffect(() => {
    try {
      const serializable = {};
      Object.entries(secAiStates).forEach(([sid, st]) => {
        serializable[sid] = {
          open: Boolean(st.open),
          mode: st.mode || "file",
          strategy: st.strategy || "merge",
          pastedText: st.pastedText || "",
          instruction: st.instruction || "",
          proposal: st.proposal || null,
        };
      });
      window.sessionStorage.setItem(`proj_sec_ai_${projectId}`, JSON.stringify(serializable));
    } catch {
      // ignore storage quota errors
    }
  }, [projectId, secAiStates]);

  const updateSecAi = (secId, patch) => {
    setSecAiStates((prev) => ({
      ...prev,
      [secId]: {
        ...DEFAULT_SEC_AI,
        ...(prev[secId] || {}),
        ...(typeof patch === "function" ? patch(prev[secId] || DEFAULT_SEC_AI) : patch),
      },
    }));
  };

  const loadProject = async (keepActiveKey = true) => {
    setLoading(true);
    setError("");
    try {
      const detail = await api.getProject(projectId);
      setProject(detail);
      const firstSec = detail.sections?.[0];
      if (!keepActiveKey || !activeKey) {
        if (firstSec) {
          setActiveKey(`section:${firstSec.id}`);
        } else {
          setActiveKey("stars");
        }
      } else if (activeKey.startsWith("section:")) {
        const curId = Number(activeKey.split(":")[1]);
        const found = detail.sections?.find((s) => s.id === curId);
        if (!found && firstSec) {
          setActiveKey(`section:${firstSec.id}`);
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Load persisted drafts when switching to a different project
    try {
      const rawDrafts = window.localStorage.getItem(`proj_drafts_${projectId}`);
      setSectionDrafts(rawDrafts ? JSON.parse(rawDrafts) : {});
    } catch {
      setSectionDrafts({});
    }
    try {
      const rawAi = window.sessionStorage.getItem(`proj_sec_ai_${projectId}`);
      if (rawAi) {
        const parsed = JSON.parse(rawAi);
        const hydrated = {};
        Object.entries(parsed).forEach(([k, v]) => {
          hydrated[k] = { ...DEFAULT_SEC_AI, ...v, file: null, ingesting: false, applying: false };
        });
        setSecAiStates(hydrated);
      } else {
        setSecAiStates({});
      }
    } catch {
      setSecAiStates({});
    }
    loadProject(false);
  }, [projectId]);

  const selectSection = (sec) => {
    // Switching sections preserves all typed drafts and per-section AI update states (QA #3)
    setActiveKey(`section:${sec.id}`);
  };

  const activeSection =
    project && activeKey.startsWith("section:")
      ? project.sections.find((s) => s.id === Number(activeKey.split(":")[1]))
      : null;

  const isSectionDirty = (sec) => {
    const d = sectionDrafts[sec.id];
    if (!d) return false;
    return (
      (d.title !== undefined && d.title !== sec.title) ||
      (d.content !== undefined && d.content !== (sec.content || ""))
    );
  };

  const dirtySections = (project?.sections || []).filter((s) => isSectionDirty(s));

  const activeDraft = activeSection ? sectionDrafts[activeSection.id] : null;
  const editTitle = activeSection ? activeDraft?.title ?? activeSection.title : "";
  const editContent = activeSection
    ? activeDraft?.content ?? activeSection.content ?? ""
    : "";
  const sectionStatus = activeSection ? sectionStatusById[activeSection.id] || "" : "";

  const setEditTitle = (val) => {
    if (!activeSection) return;
    setSectionDrafts((prev) => ({
      ...prev,
      [activeSection.id]: {
        title: val,
        content: prev[activeSection.id]?.content ?? activeSection.content ?? "",
      },
    }));
  };

  const setEditContent = (val) => {
    if (!activeSection) return;
    setSectionDrafts((prev) => ({
      ...prev,
      [activeSection.id]: {
        title: prev[activeSection.id]?.title ?? activeSection.title,
        content: val,
      },
    }));
  };

  const curSecAi = activeSection
    ? { ...DEFAULT_SEC_AI, ...(secAiStates[activeSection.id] || {}) }
    : DEFAULT_SEC_AI;

  const handleSaveSection = async () => {
    if (!activeSection || savingSection) return;
    const targetId = activeSection.id;
    const targetTitle = editTitle.trim() || activeSection.title;
    const targetContent = editContent;
    setSavingSection(true);
    setSectionStatusById((prev) => ({ ...prev, [targetId]: "" }));
    try {
      const updated = await api.updateSection(project.id, targetId, {
        title: targetTitle,
        content: targetContent,
      });
      setSectionDrafts((prev) => {
        const next = { ...prev };
        delete next[targetId];
        return next;
      });
      setSectionStatusById((prev) => ({
        ...prev,
        [targetId]: updated.vector_synced ? "저장 및 벡터 동기화 완료" : "DB 저장 완료",
      }));
      await loadProject(true);
      await onGlobalRefresh();
    } catch (err) {
      setSectionStatusById((prev) => ({
        ...prev,
        [targetId]: `저장 실패: ${err.message}`,
      }));
    } finally {
      setSavingSection(false);
    }
  };

  const handleSaveAllDirtySections = async () => {
    if (!project || dirtySections.length === 0 || savingAllDirty) return;
    setSavingAllDirty(true);
    try {
      const savedIds = [];
      for (const sec of dirtySections) {
        const d = sectionDrafts[sec.id] || {};
        await api.updateSection(project.id, sec.id, {
          title: (d.title ?? sec.title).trim() || sec.title,
          content: d.content ?? sec.content ?? "",
        });
        savedIds.push(sec.id);
      }
      setSectionDrafts((prev) => {
        const next = { ...prev };
        savedIds.forEach((id) => delete next[id]);
        return next;
      });
      setSectionStatusById((prev) => {
        const next = { ...prev };
        savedIds.forEach((id) => {
          next[id] = "일괄 저장 및 벡터 동기화 완료";
        });
        return next;
      });
      await loadProject(true);
      await onGlobalRefresh();
    } catch (err) {
      alert(`일괄 저장 중 오류: ${err.message}`);
    } finally {
      setSavingAllDirty(false);
    }
  };

  const handleDeleteSection = async (sec) => {
    if (!window.confirm(`'${sec.title}' 섹션을 삭제할까요? (복구할 수 없습니다)`)) {
      return;
    }
    try {
      await api.deleteSection(project.id, sec.id);
      await loadProject(false);
      await onGlobalRefresh();
    } catch (err) {
      alert(`섹션 삭제 실패: ${err.message}`);
    }
  };

  const handleCreateCustomSection = async (e) => {
    e.preventDefault();
    const title = newSecTitle.trim();
    if (!title) return;
    const slug = `custom-${Date.now().toString(36)}`;
    try {
      const created = await api.createSection(project.id, {
        section_type: slug,
        track: "custom",
        title,
        content: "",
        display_order: 700,
      });
      setNewSecTitle("");
      setShowAddSection(false);
      await loadProject(true);
      selectSection(created);
      await onGlobalRefresh();
    } catch (err) {
      alert(`섹션 추가 실패: ${err.message}`);
    }
  };

  const handleAddTrack = async (trackId) => {
    if (addingTrack) return;
    setAddingTrack(true);
    try {
      const res = await api.addProjectTracks(project.id, [trackId]);
      setShowAddTrack(false);
      await loadProject(true);
      await onGlobalRefresh();
      alert(
        `'${TRACK_SHORT_LABELS[trackId] || trackId}' 트랙이 추가되었습니다! (신규 섹션 ${res.added_section_types.length}개 생성)`
      );
    } catch (err) {
      alert(`트랙 추가 실패: ${err.message}`);
    } finally {
      setAddingTrack(false);
    }
  };

  const handleAddArtifactLink = async (e) => {
    e.preventDefault();
    const url = newLinkUrl.trim();
    if (!url) return;
    const nextLinks = [
      ...(project.artifact_links || []),
      { label: newLinkLabel.trim() || url, url },
    ];
    try {
      await api.updateProject(project.id, { artifact_links: nextLinks });
      setNewLinkLabel("");
      setNewLinkUrl("");
      setShowAddLink(false);
      await loadProject(true);
      await onGlobalRefresh();
    } catch (err) {
      alert(`참고 링크 추가 실패: ${err.message}`);
    }
  };

  const handleDeleteArtifactLink = async (idx) => {
    const nextLinks = (project.artifact_links || []).filter((_, i) => i !== idx);
    try {
      await api.updateProject(project.id, { artifact_links: nextLinks });
      await loadProject(true);
      await onGlobalRefresh();
    } catch (err) {
      alert(`참고 링크 삭제 실패: ${err.message}`);
    }
  };

  const openProposalReview = (proposal) => {
    setUpdateProposal(proposal);
    setSelectedUpdateIndices(
      new Set((proposal.section_updates || []).map((_, i) => i))
    );
    setSelectedExpIndices(
      new Set((proposal.suggested_experiences || []).map((_, i) => i))
    );
    setApplySummary(Boolean(proposal.suggested_summary));
    setApplyTechStack((proposal.suggested_tech_stack_additions || []).length > 0);
  };

  const handleIngestDocument = async (e) => {
    e.preventDefault();
    if (ingesting) return;
    setIngestError("");

    const formData = new FormData();
    if (ingestMode === "file") {
      if (!uploadFile) {
        setIngestError("업로드할 파일을 선택해 주세요.");
        return;
      }
      formData.append("file", uploadFile);
    } else {
      if (!pastedText.trim()) {
        setIngestError("붙여넣을 문서 내용을 입력해 주세요.");
        return;
      }
      formData.append("pasted_text", pastedText.trim());
      if (pastedTitle.trim()) formData.append("doc_title", pastedTitle.trim());
    }
    if (ingestInstruction.trim()) {
      formData.append("instruction", ingestInstruction.trim());
    }

    setIngesting(true);
    try {
      const proposal = await api.ingestProjectDocument(project.id, formData);
      setShowIngestModal(false);
      setUploadFile(null);
      setPastedText("");
      setPastedTitle("");
      setIngestInstruction("");
      openProposalReview(proposal);
    } catch (err) {
      setIngestError(err.message);
    } finally {
      setIngesting(false);
    }
  };

  const handleSyncGithub = async () => {
    if (!project?.repo_url || syncingGithub) return;
    setSyncingGithub(true);
    try {
      const proposal = await api.syncProjectGithub(project.id, {
        repo_url: project.repo_url,
      });
      openProposalReview(proposal);
    } catch (err) {
      alert(`GitHub 동기화 실패: ${err.message}`);
    } finally {
      setSyncingGithub(false);
    }
  };

  const handleApplyUpdates = async () => {
    if (!updateProposal || applyingUpdates) return;
    setApplyingUpdates(true);
    try {
      const chosenSections = (updateProposal.section_updates || [])
        .filter((_, idx) => selectedUpdateIndices.has(idx))
        .map((s) => ({
          section_id: s.section_id,
          section_type: s.section_type,
          track: s.track || "core",
          title: s.title,
          content: s.proposed_content,
        }));
      const chosenExps = (updateProposal.suggested_experiences || []).filter((_, idx) =>
        selectedExpIndices.has(idx)
      );

      const res = await api.applyProjectUpdates(project.id, {
        filename: updateProposal.filename,
        source_type: updateProposal.source_type,
        file_format: updateProposal.file_format,
        document_summary: updateProposal.document_summary,
        raw_char_count: updateProposal.raw_char_count,
        updated_summary:
          applySummary && updateProposal.suggested_summary
            ? updateProposal.suggested_summary
            : null,
        tech_stack_additions: applyTechStack
          ? updateProposal.suggested_tech_stack_additions || []
          : [],
        section_updates: chosenSections,
        experiences: chosenExps,
      });
      setUpdateProposal(null);
      await loadProject(true);
      await onGlobalRefresh();
      alert(
        `업데이트 완료! 섹션 ${res.updated_section_types.length}개 반영 · STAR 경험 ${res.saved_experience_ids.length}건 추가 (벡터 동기화 ${res.vector_synced_count}건)`
      );
    } catch (err) {
      alert(`업데이트 반영 실패: ${err.message}`);
    } finally {
      setApplyingUpdates(false);
    }
  };

  const handleRunPrune = async () => {
    if (pruning) return;
    setPruning(true);
    try {
      const res = await api.pruneProject(project.id);
      setPruneProposal(res);
      setSelectedPruneIds(
        new Set((res.section_prunes || []).map((item) => item.section_id))
      );
    } catch (err) {
      alert(`AI 정리 분석 실패: ${err.message}`);
    } finally {
      setPruning(false);
    }
  };

  const handleApplyPrune = async () => {
    if (!pruneProposal || applyingPrune) return;
    const updates = (pruneProposal.section_prunes || [])
      .filter((item) => selectedPruneIds.has(item.section_id))
      .map((item) => ({
        section_id: item.section_id,
        cleaned_content: item.cleaned_content,
      }));
    if (updates.length === 0) {
      setPruneProposal(null);
      return;
    }

    setApplyingPrune(true);
    try {
      const res = await api.applyProjectPrune(project.id, updates);
      setPruneProposal(null);
      await loadProject(true);
      await onGlobalRefresh();
      alert(
        `정리 완료! ${res.updated_count}개 섹션의 불필요한 내용을 압축·삭제했습니다.`
      );
    } catch (err) {
      alert(`정리 적용 실패: ${err.message}`);
    } finally {
      setApplyingPrune(false);
    }
  };

  const handleDeleteExperience = async (exp) => {
    if (!window.confirm(`'${exp.title}' STAR 경험을 삭제할까요?`)) return;
    try {
      await api.deleteExperience(exp.id);
      await loadProject(true);
      await onGlobalRefresh();
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  const handleDeleteDocument = async (doc) => {
    if (!window.confirm(`'${doc.filename}' 문서 이력을 삭제할까요?`)) return;
    try {
      await api.deleteProjectDocument(project.id, doc.id);
      await loadProject(true);
      await onGlobalRefresh();
    } catch (err) {
      alert(`문서 이력 삭제 실패: ${err.message}`);
    }
  };

  const handleOpenAssembledMarkdown = () => {
    if (!project) return;
    setCopiedMd(false);
    setMarkdownModal({
      title: `${project.name} — 전체 포트폴리오 Markdown`,
      subtitle: "멀티트랙 모듈 섹션에서 즉시 조립된 최신 포트폴리오",
      markdown: project.assembled_markdown || "",
    });
  };

  const handleGenerateRecap = async () => {
    if (!project || recapLoading) return;
    setRecapLoading(true);
    try {
      const res = await api.recapProject(project.id);
      setCopiedMd(false);
      setMarkdownModal({
        title: `${res.project_name} — AI 포트폴리오 리캡`,
        subtitle: `멀티트랙 섹션 + STAR 경험 ${res.experience_count}건 종합`,
        markdown: res.markdown,
      });
    } catch (err) {
      alert(`리캡 생성 실패: ${err.message}`);
    } finally {
      setRecapLoading(false);
    }
  };

  const handleCopyMarkdown = async () => {
    if (!markdownModal?.markdown) return;
    await navigator.clipboard.writeText(markdownModal.markdown);
    setCopiedMd(true);
    setTimeout(() => setCopiedMd(false), 2000);
  };

  const handleDownloadMarkdown = () => {
    if (!markdownModal?.markdown || !project) return;
    const blob = new Blob([markdownModal.markdown], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project.name.replace(/[^\w가-힣-]+/g, "_")}_portfolio.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleOpenRubricModal = async () => {
    setShowRubricModal(true);
    if (!rubricRef) {
      try {
        const ref = await api.getRubricReference();
        setRubricRef(ref);
      } catch (err) {
        console.warn("Failed to load rubric reference:", err);
      }
    }
  };

  const handleRunSectionIngest = async (e) => {
    e.preventDefault();
    if (!activeSection) return;
    const targetSecId = activeSection.id;
    const st = { ...DEFAULT_SEC_AI, ...(secAiStates[targetSecId] || {}) };
    if (st.ingesting) return;

    const formData = new FormData();
    if (st.mode === "file") {
      if (!st.file) {
        updateSecAi(targetSecId, { error: "업로드할 파일을 선택해 주세요." });
        return;
      }
      formData.append("file", st.file);
    } else {
      if (!st.pastedText.trim()) {
        updateSecAi(targetSecId, {
          error: "이 섹션에 반영할 메모나 문서 내용을 입력해 주세요.",
        });
        return;
      }
      formData.append("pasted_text", st.pastedText.trim());
    }
    formData.append("instruction", st.instruction.trim());
    formData.append("update_mode", st.strategy);

    updateSecAi(targetSecId, { error: "", proposal: null, ingesting: true });
    try {
      const proposal = await api.ingestSectionDocument(
        projectId,
        targetSecId,
        formData
      );
      updateSecAi(targetSecId, { proposal, ingesting: false });
    } catch (err) {
      updateSecAi(targetSecId, { error: err.message, ingesting: false });
    }
  };

  const handleApplySectionProposal = async () => {
    if (!activeSection) return;
    const targetSecId = activeSection.id;
    const st = { ...DEFAULT_SEC_AI, ...(secAiStates[targetSecId] || {}) };
    if (!st.proposal || st.applying) return;

    updateSecAi(targetSecId, { applying: true });
    try {
      const updated = await api.updateSection(projectId, targetSecId, {
        title: st.proposal.title || editTitle,
        content: st.proposal.proposed_content,
      });
      setSectionDrafts((prev) => {
        const next = { ...prev };
        delete next[targetSecId];
        return next;
      });
      setSectionStatusById((prev) => ({
        ...prev,
        [targetSecId]: updated.vector_synced
          ? "섹션 AI 업데이트 반영 및 벡터 동기화 완료"
          : "섹션 AI 업데이트 반영 완료",
      }));
      updateSecAi(targetSecId, {
        ...DEFAULT_SEC_AI,
        open: false,
      });
      await loadProject(true);
      onGlobalRefresh?.();
    } catch (err) {
      updateSecAi(targetSecId, { applying: false });
      alert(`섹션 반영 실패: ${err.message}`);
    }
  };

  const handleOpenStarOnboarding = async () => {
    setShowStarOnboarding(true);
    setOnboardingError("");
    if (starOnboardingData) return;
    setLoadingStarQs(true);
    try {
      const data = await api.getStarOnboardingQuestions(projectId);
      setStarOnboardingData(data);
      const init = {};
      (data.questions || []).forEach((q) => {
        init[q.id] = "";
      });
      setStarAnswers(init);
    } catch (err) {
      setOnboardingError(err.message);
    } finally {
      setLoadingStarQs(false);
    }
  };

  const handleSubmitStarOnboarding = async (e) => {
    e.preventDefault();
    if (!starOnboardingData || submittingStarOnboarding) return;
    const answers = (starOnboardingData.questions || [])
      .map((q) => ({
        target_axis: q.target_axis,
        question: q.question,
        answer: (starAnswers[q.id] || "").trim(),
      }))
      .filter((a) => a.answer);

    if (answers.length === 0) {
      setOnboardingError("최소 1개 이상의 질문에 간단히 답변해 주세요.");
      return;
    }

    setSubmittingStarOnboarding(true);
    setOnboardingError("");
    try {
      await api.applyStarOnboarding(projectId, {
        answers,
        apply_section_patches: applyOnboardingPatches,
      });
      setShowStarOnboarding(false);
      setStarOnboardingData(null);
      setStarAnswers({});
      setDismissedStarBanner(true);
      await loadProject(false);
      setActiveKey("stars");
      onGlobalRefresh?.();
    } catch (err) {
      setOnboardingError(err.message);
    } finally {
      setSubmittingStarOnboarding(false);
    }
  };

  const handleEvaluateProjectStars = async () => {
    if (evaluatingStars) return;
    setEvaluatingStars(true);
    try {
      await api.evaluateProjectStars(projectId);
      await loadProject(true);
      onGlobalRefresh?.();
    } catch (err) {
      alert(`5축 BARS 재채점 실패: ${err.message}`);
    } finally {
      setEvaluatingStars(false);
    }
  };

  const handleStartProjectRetro = async (fw = retroFramework) => {
    if (loadingRetroQs) return;
    setLoadingRetroQs(true);
    setRetroError("");
    try {
      const data = await api.getProjectRetroQuestions(projectId, fw);
      setRetroQs(data);
      const init = {};
      (data.questions || []).forEach((q) => {
        init[q.id] = "";
      });
      setRetroAnswers(init);
    } catch (err) {
      setRetroError(err.message);
    } finally {
      setLoadingRetroQs(false);
    }
  };

  const handleApplyProjectRetro = async (e) => {
    e.preventDefault();
    if (!retroQs || submittingRetro) return;
    const answers = (retroQs.questions || [])
      .map((q) => ({
        dimension: q.dimension,
        question: q.question,
        answer: (retroAnswers[q.id] || "").trim(),
      }))
      .filter((a) => a.answer);

    if (answers.length === 0) {
      setRetroError("최소 1개 이상의 회고 질문에 답변을 입력해 주세요.");
      return;
    }

    setSubmittingRetro(true);
    setRetroError("");
    try {
      await api.applyProjectRetrospective(projectId, {
        framework: retroQs.framework || retroFramework,
        answers,
        sync_to_outcomes_section: syncRetroToOutcomes,
      });
      setRetroQs(null);
      setRetroAnswers({});
      await loadProject(true);
      onGlobalRefresh?.();
    } catch (err) {
      setRetroError(err.message);
    } finally {
      setSubmittingRetro(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-12 flex items-center justify-center gap-2 text-sm text-slate-600">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>프로젝트 포트폴리오 워크스페이스 불러오는 중...</span>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="space-y-4">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>포트폴리오 목록으로</span>
        </button>
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          프로젝트를 불러오지 못했습니다: {error}
        </div>
      </div>
    );
  }

  const projectTypes = project.project_types || ["engineering"];
  const availableTracksToAdd = DEFAULT_TRACKS.filter(
    (t) => !projectTypes.includes(t.id)
  );
  const groupedSections = groupSectionsByTrack(project.sections || []);
  const starAvg = project.star_averages || {};
  const starRadarItems = STAR_RADAR_LABELS.map((m) => ({
    id: m.id,
    label: m.label,
    score: starAvg?.axes?.[m.id]?.score || 0,
  }));
  const shouldSuggestStarOnboarding =
    !dismissedStarBanner &&
    ((project.experiences?.length || 0) === 0 ||
      (starAvg.evaluated_count > 0 && (starAvg.weighted_score || 0) < 65));

  return (
    <div className="space-y-6">
      {/* Opt-in Non-blocking STAR Deepening Banner */}
      {shouldSuggestStarOnboarding && (
        <div className="rounded-2xl border border-violet-200 bg-gradient-to-r from-violet-50 to-indigo-50 px-5 py-3.5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-2.5 min-w-0">
            <HelpCircle className="w-4 h-4 text-violet-600 shrink-0 mt-0.5" />
            <div className="text-xs text-slate-700">
              <strong className="text-violet-950">
                이 프로젝트 요약으로 21지표 STAR-L 경험을 채굴해 보세요
              </strong>
              <p className="text-slate-600 mt-0.5">
                프로젝트 요약·섹션을 자동 불러온 뒤, 빠진 체크포인트(대안 비교·본인 주도성·전후 수치·회고)만 멀티턴 역질문으로 정밀 채굴합니다.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => onJumpToMiner && onJumpToMiner(projectId, "")}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet-700"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>경험 채굴 시작 →</span>
            </button>
            <button
              type="button"
              onClick={() => setDismissedStarBanner(true)}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-white/60 hover:text-slate-700"
              title="배너 닫기"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
      {/* Header & Global Action Bar */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1.5 min-w-0">
            <button
              type="button"
              onClick={onBack}
              className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-900"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>포트폴리오 목록으로 돌아가기</span>
            </button>

            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-bold text-slate-900">{project.name}</h2>
              {projectTypes.map((tId) => (
                <span
                  key={tId}
                  className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${getTrackBadgeClass(tId)}`}
                >
                  {TRACK_SHORT_LABELS[tId] || tId}
                </span>
              ))}
              {availableTracksToAdd.length > 0 && (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setShowAddTrack((v) => !v)}
                    className="inline-flex items-center gap-0.5 rounded-full border border-dashed border-slate-300 px-2.5 py-0.5 text-[11px] font-semibold text-slate-600 hover:border-indigo-400 hover:text-indigo-700"
                  >
                    <Plus className="w-3 h-3" />
                    <span>트랙 추가</span>
                  </button>
                  {showAddTrack && (
                    <div className="absolute left-0 mt-1.5 z-30 w-56 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg space-y-1">
                      <div className="px-2 py-1 text-[10px] font-bold uppercase text-slate-400">
                        이 프로젝트에 역할/트랙 추가
                      </div>
                      {availableTracksToAdd.map((tr) => (
                        <button
                          key={tr.id}
                          type="button"
                          disabled={addingTrack}
                          onClick={() => handleAddTrack(tr.id)}
                          className="w-full text-left rounded-lg px-2.5 py-1.5 text-xs hover:bg-slate-50 flex items-center justify-between"
                        >
                          <span className="font-medium text-slate-800">
                            {tr.label}
                          </span>
                          <Plus className="w-3.5 h-3.5 text-indigo-600" />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <span className="rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700">
                섹션 {project.filled_section_count}/{project.total_section_count}
              </span>
            </div>

            <p className="text-xs text-slate-500">
              {[project.period, project.role].filter(Boolean).join(" · ")}
              {project.repo_url && (
                <>
                  {" · "}
                  <a
                    href={project.repo_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-indigo-600 hover:underline inline-flex items-center gap-1"
                  >
                    <Github className="w-3 h-3" />
                    {project.repo_url}
                  </a>
                </>
              )}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onJumpToMiner && onJumpToMiner(projectId, "")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-300 bg-violet-50 px-3 py-2 text-xs font-semibold text-violet-900 hover:bg-violet-100"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>이 프로젝트로 경험 채굴 →</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setIngestError("");
                setShowIngestModal(true);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
            >
              <FileUp className="w-3.5 h-3.5" />
              <span>파일·문서로 자동 업데이트</span>
            </button>

            {project.repo_url && (
              <button
                type="button"
                disabled={syncingGithub}
                onClick={handleSyncGithub}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {syncingGithub ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="w-3.5 h-3.5" />
                )}
                <span>{syncingGithub ? "GitHub 읽는 중..." : "GitHub 동기화"}</span>
              </button>
            )}

            <button
              type="button"
              disabled={pruning}
              onClick={handleRunPrune}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-100 disabled:opacity-50"
            >
              {pruning ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Eraser className="w-3.5 h-3.5" />
              )}
              <span>{pruning ? "노이즈 분석 중..." : "쓸데없는 내용 AI 정리"}</span>
            </button>

            <button
              type="button"
              onClick={handleOpenAssembledMarkdown}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              <FileText className="w-3.5 h-3.5" />
              <span>전체 MD 보기</span>
            </button>

            <button
              type="button"
              disabled={recapLoading}
              onClick={handleGenerateRecap}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>{recapLoading ? "리캡 생성 중..." : "AI 리캡"}</span>
            </button>
          </div>
        </div>

        {/* Skills/Tools & Artifact Links Row */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-100">
          <div className="flex flex-wrap gap-1.5">
            {(project.tech_stack || []).map((tech, idx) => (
              <span
                key={idx}
                className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700"
              >
                {tech}
              </span>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {(project.artifact_links || []).map((link, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1 rounded-full bg-indigo-50 border border-indigo-200 px-2.5 py-0.5 text-[11px] font-medium text-indigo-800"
              >
                <a
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 hover:underline"
                >
                  <ExternalLink className="w-3 h-3" />
                  <span>{link.label || link.url}</span>
                </a>
                <button
                  type="button"
                  onClick={() => handleDeleteArtifactLink(idx)}
                  className="hover:text-rose-600"
                  title="링크 삭제"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}

            <button
              type="button"
              onClick={() => setShowAddLink((v) => !v)}
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2.5 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
            >
              <Link2 className="w-3 h-3" />
              <span>+ 참고 링크 (Figma·Notion 등)</span>
            </button>
          </div>
        </div>

        {showAddLink && (
          <form
            onSubmit={handleAddArtifactLink}
            className="flex flex-wrap gap-2 pt-2 border-t border-slate-100"
          >
            <input
              type="text"
              value={newLinkLabel}
              onChange={(e) => setNewLinkLabel(e.target.value)}
              placeholder="링크 이름 (예: Figma 프로토타입, 발표자료)"
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs w-52"
            />
            <input
              required
              type="url"
              value={newLinkUrl}
              onChange={(e) => setNewLinkUrl(e.target.value)}
              placeholder="https://..."
              className="flex-1 min-w-[200px] rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <button
              type="submit"
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white"
            >
              추가
            </button>
          </form>
        )}
      </div>

      {/* Main 2-Column Multi-Track Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Outline Navigation Grouped by Track */}
        <aside className="lg:col-span-4 rounded-2xl border border-slate-200 bg-white p-4 space-y-4 shadow-sm">
          <div className="flex items-center justify-between px-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1">
              <Layers className="w-3.5 h-3.5" />
              <span>트랙별 포트폴리오 섹션</span>
            </span>
            <button
              type="button"
              onClick={() => setShowAddSection((v) => !v)}
              className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-indigo-600 hover:text-indigo-800"
            >
              <Plus className="w-3 h-3" />
              <span>섹션 추가</span>
            </button>
          </div>

          {showAddSection && (
            <form onSubmit={handleCreateCustomSection} className="flex gap-1.5 pb-1">
              <input
                type="text"
                value={newSecTitle}
                onChange={(e) => setNewSecTitle(e.target.value)}
                placeholder="예: 사용자 인터뷰 요약"
                className="flex-1 min-w-0 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
              />
              <button
                type="submit"
                className="rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white"
              >
                추가
              </button>
            </form>
          )}

          <div className="space-y-3">
            {groupedSections.map((grp) => (
              <div key={grp.track} className="space-y-1">
                <div className="px-1.5 flex items-center gap-1.5">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold border ${getTrackBadgeClass(grp.track)}`}
                  >
                    {grp.label}
                  </span>
                </div>
                {grp.sections.map((sec) => {
                  const isSelected = activeKey === `section:${sec.id}`;
                  const secAi = secAiStates[sec.id];
                  const dirty = isSectionDirty(sec);
                  const draftContent = sectionDrafts[sec.id]?.content;
                  const hasContent = Boolean(
                    ((draftContent !== undefined ? draftContent : sec.content) || "").trim()
                  );
                  return (
                    <button
                      key={sec.id}
                      type="button"
                      onClick={() => selectSection(sec)}
                      className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl text-left text-xs font-medium transition-colors ${
                        isSelected
                          ? "bg-slate-900 text-white"
                          : "text-slate-700 hover:bg-slate-100"
                      }`}
                    >
                      <span className="truncate">
                        {sectionDrafts[sec.id]?.title || sec.title}
                      </span>
                      <span className="flex items-center gap-1 shrink-0">
                        {secAi?.ingesting && (
                          <span className="inline-flex items-center gap-0.5 rounded bg-indigo-500 px-1.5 py-0.5 text-[9px] font-bold text-white">
                            <Loader2 className="w-2.5 h-2.5 animate-spin" />
                            AI
                          </span>
                        )}
                        {!secAi?.ingesting && secAi?.proposal && (
                          <span className="rounded bg-violet-100 text-violet-800 px-1.5 py-0.5 text-[9px] font-bold">
                            제안
                          </span>
                        )}
                        {dirty && (
                          <span className="rounded bg-amber-100 text-amber-800 px-1.5 py-0.5 text-[9px] font-bold">
                            수정중
                          </span>
                        )}
                        <span
                          className={`w-2 h-2 rounded-full ${
                            hasContent
                              ? isSelected
                                ? "bg-emerald-400"
                                : "bg-emerald-500"
                              : isSelected
                              ? "bg-slate-600"
                              : "bg-slate-300"
                          }`}
                          title={hasContent ? "작성됨" : "비어 있음"}
                        />
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>

          {dirtySections.length > 0 && (
            <button
              type="button"
              disabled={savingAllDirty}
              onClick={handleSaveAllDirtySections}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl bg-amber-500 px-3 py-2 text-xs font-bold text-white hover:bg-amber-600 disabled:opacity-50 shadow-xs"
            >
              <Save className="w-3.5 h-3.5" />
              <span>
                {savingAllDirty
                  ? "일괄 저장 중..."
                  : `변경된 섹션 모두 저장 (${dirtySections.length})`}
              </span>
            </button>
          )}

          <div className="pt-3 border-t border-slate-100 space-y-1">
            <button
              type="button"
              onClick={() => setActiveKey("stars")}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-semibold ${
                activeKey === "stars"
                  ? "bg-indigo-600 text-white"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              <span className="inline-flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                <span>연결된 STAR-L 경험</span>
              </span>
              <span>{project.experiences?.length || 0}</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveKey("retro")}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-semibold ${
                activeKey === "retro"
                  ? "bg-indigo-600 text-white"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              <span className="inline-flex items-center gap-1.5">
                <RefreshCw className="w-3.5 h-3.5" />
                <span>프로젝트 회고 (학습 루프)</span>
              </span>
              <span className="text-[10px]">
                {(project.retrospective?.try_items || []).length > 0
                  ? `Try ${project.retrospective.try_items.length}`
                  : "미작성"}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveKey("docs")}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-semibold ${
                activeKey === "docs"
                  ? "bg-indigo-600 text-white"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              <span className="inline-flex items-center gap-1.5">
                <FolderOpen className="w-3.5 h-3.5" />
                <span>업로드 문서 · GitHub 이력</span>
              </span>
              <span>{project.documents?.length || 0}</span>
            </button>
          </div>
        </aside>

        {/* Right Content Canvas */}
        <section className="lg:col-span-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm min-h-[460px]">
          {activeSection ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100">
                <div className="flex items-center gap-2 flex-1 min-w-[200px]">
                  <span
                    className={`rounded-md border px-2 py-0.5 text-[10px] font-bold shrink-0 ${getTrackBadgeClass(activeSection.track)}`}
                  >
                    {TRACK_SHORT_LABELS[activeSection.track] || activeSection.track}
                  </span>
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    className="text-base font-bold text-slate-900 border border-transparent hover:border-slate-200 focus:border-slate-300 rounded-lg px-2 py-1 flex-1 min-w-0 focus:outline-none"
                  />
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      updateSecAi(activeSection.id, (prev) => ({
                        open: !prev.open,
                        error: "",
                      }))
                    }
                    className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                      curSecAi.open
                        ? "border-indigo-500 bg-indigo-600 text-white"
                        : "border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                    }`}
                  >
                    <Paperclip className="w-3.5 h-3.5" />
                    <span>
                      이 섹션 파일·AI 업데이트
                      {curSecAi.ingesting
                        ? " (진행중)"
                        : curSecAi.proposal
                        ? " (제안 대기)"
                        : ""}
                    </span>
                  </button>

                  <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-xs">
                    <button
                      type="button"
                      onClick={() => setSectionViewMode("edit")}
                      className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 font-medium ${
                        sectionViewMode === "edit"
                          ? "bg-white text-slate-900 shadow-sm"
                          : "text-slate-600"
                      }`}
                    >
                      <Pencil className="w-3 h-3" />
                      <span>편집</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setSectionViewMode("preview")}
                      className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 font-medium ${
                        sectionViewMode === "preview"
                          ? "bg-white text-slate-900 shadow-sm"
                          : "text-slate-600"
                      }`}
                    >
                      <Eye className="w-3 h-3" />
                      <span>미리보기</span>
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleDeleteSection(activeSection)}
                    className="p-2 rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600"
                    title="이 섹션 삭제"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Section-Scoped File / Memo AI Update Bar (Per-Section State Preserved) */}
              {curSecAi.open && (
                <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-bold text-indigo-950 flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
                      <span>
                        &apos;{editTitle || activeSection.title}&apos; 섹션 전용 파일·메모 AI 자동 업데이트
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px]">
                      {[
                        { id: "merge", label: "기존 유지 + 병합" },
                        { id: "append", label: "하단 보강" },
                        { id: "replace", label: "문서 기준 재작성" },
                      ].map((m) => (
                        <button
                          key={m.id}
                          type="button"
                          onClick={() => updateSecAi(activeSection.id, { strategy: m.id })}
                          className={`rounded-md px-2 py-0.5 font-semibold border ${
                            curSecAi.strategy === m.id
                              ? "border-indigo-600 bg-indigo-600 text-white"
                              : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {m.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <form onSubmit={handleRunSectionIngest} className="space-y-2.5">
                    <div className="flex items-center gap-2 text-xs">
                      <button
                        type="button"
                        onClick={() => updateSecAi(activeSection.id, { mode: "file" })}
                        className={`rounded-lg px-2.5 py-1 font-medium ${
                          curSecAi.mode === "file"
                            ? "bg-slate-900 text-white"
                            : "bg-white border border-slate-200 text-slate-600"
                        }`}
                      >
                        파일 업로드 (.pdf/.docx/.pptx/.md/.ipynb/코드)
                      </button>
                      <button
                        type="button"
                        onClick={() => updateSecAi(activeSection.id, { mode: "text" })}
                        className={`rounded-lg px-2.5 py-1 font-medium ${
                          curSecAi.mode === "text"
                            ? "bg-slate-900 text-white"
                            : "bg-white border border-slate-200 text-slate-600"
                        }`}
                      >
                        메모·로그 직접 붙여넣기
                      </button>
                    </div>

                    {curSecAi.mode === "file" ? (
                      <div className="space-y-1">
                        <input
                          key={`sec-file-${activeSection.id}`}
                          type="file"
                          accept=".pdf,.docx,.pptx,.md,.markdown,.txt,.ipynb,.py,.js,.jsx,.ts,.tsx,.java,.go,.sql,.yaml,.yml,.json"
                          onChange={(e) =>
                            updateSecAi(activeSection.id, { file: e.target.files?.[0] || null })
                          }
                          className="block w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs"
                        />
                        {curSecAi.file && (
                          <div className="text-[11px] text-indigo-700 font-medium">
                            선택된 파일 유지됨: {curSecAi.file.name}
                          </div>
                        )}
                      </div>
                    ) : (
                      <textarea
                        rows={4}
                        value={curSecAi.pastedText}
                        onChange={(e) =>
                          updateSecAi(activeSection.id, { pastedText: e.target.value })
                        }
                        placeholder="이 섹션에 반영할 트러블슈팅 로그, 회의록, 벤치마크 수치, 인터뷰 메모 등을 붙여넣으세요..."
                        className="w-full rounded-lg border border-slate-200 bg-white p-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                      />
                    )}

                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="text"
                        value={curSecAi.instruction}
                        onChange={(e) =>
                          updateSecAi(activeSection.id, { instruction: e.target.value })
                        }
                        placeholder="선택 지시: 예) Latency 전/후 수치와 원인 중심으로 정리해줘"
                        className="flex-1 min-w-[200px] rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs"
                      />
                      <button
                        type="submit"
                        disabled={curSecAi.ingesting}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                      >
                        {curSecAi.ingesting ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Sparkles className="w-3.5 h-3.5" />
                        )}
                        <span>{curSecAi.ingesting ? "AI 분석 중..." : "이 섹션 Diff 생성"}</span>
                      </button>
                    </div>

                    {curSecAi.error && (
                      <div className="rounded-lg bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">
                        {curSecAi.error}
                      </div>
                    )}
                  </form>

                  {/* Inline Section Before / After Diff Preview */}
                  {curSecAi.proposal && (
                    <div className="rounded-xl border border-emerald-200 bg-white p-4 space-y-3 text-xs">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <div className="font-bold text-slate-900">
                            AI 섹션 업데이트 제안 ({curSecAi.proposal.filename})
                          </div>
                          {curSecAi.proposal.change_summary && (
                            <p className="text-indigo-700 mt-0.5">
                              {curSecAi.proposal.change_summary}
                            </p>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => updateSecAi(activeSection.id, { proposal: null })}
                            className="rounded-lg border border-slate-200 px-2.5 py-1 text-slate-600 hover:bg-slate-50"
                          >
                            취소
                          </button>
                          <button
                            type="button"
                            disabled={curSecAi.applying}
                            onClick={handleApplySectionProposal}
                            className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1 font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                          >
                            <Check className="w-3.5 h-3.5" />
                            <span>{curSecAi.applying ? "반영 중..." : "이 섹션에 반영"}</span>
                          </button>
                        </div>
                      </div>

                      {(curSecAi.proposal.added_facts || []).length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {curSecAi.proposal.added_facts.map((f, i) => (
                            <span
                              key={i}
                              className="rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[11px] text-emerald-800"
                            >
                              + {f}
                            </span>
                          ))}
                        </div>
                      )}

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
                          <div className="text-[10px] font-bold uppercase text-slate-400 mb-1">
                            변경 전 (Before)
                          </div>
                          <pre className="whitespace-pre-wrap font-sans text-slate-600 max-h-48 overflow-y-auto">
                            {curSecAi.proposal.before_content || "(비어 있음)"}
                          </pre>
                        </div>
                        <div className="rounded-lg bg-emerald-50/50 border border-emerald-200 p-3">
                          <div className="text-[10px] font-bold uppercase text-emerald-700 mb-1">
                            업데이트 제안 (After)
                          </div>
                          <pre className="whitespace-pre-wrap font-sans text-slate-800 max-h-48 overflow-y-auto">
                            {curSecAi.proposal.proposed_content}
                          </pre>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {sectionViewMode === "edit" ? (
                <textarea
                  rows={14}
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  placeholder="Markdown 형식으로 이 섹션 내용을 작성하거나, 상단의 '파일·문서로 자동 업데이트'로 기획서·발표자료·코드를 올려 채워 보세요."
                  className="w-full rounded-xl border border-slate-200 p-4 text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-slate-900/15"
                />
              ) : (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-5 min-h-[320px] prose prose-sm prose-slate max-w-none">
                  {editContent.trim() ? (
                    <ReactMarkdown>{editContent}</ReactMarkdown>
                  ) : (
                    <p className="text-slate-400">작성된 내용이 없습니다.</p>
                  )}
                </div>
              )}

              <div className="flex items-center justify-between pt-1">
                <span className="text-xs text-emerald-700 font-medium">
                  {sectionStatus}
                </span>
                <button
                  type="button"
                  disabled={savingSection}
                  onClick={handleSaveSection}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  <Save className="w-3.5 h-3.5" />
                  <span>{savingSection ? "저장 중..." : "섹션 저장 & 벡터 동기화"}</span>
                </button>
              </div>
            </div>
          ) : activeKey === "stars" ? (
            <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-base font-bold text-slate-900">
                    연결된 STAR-L 경험 &amp; 5축 객관 평가 ({project.experiences?.length || 0})
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    DDI BARS × Amazon Bar Raiser × Google XYZ 기준으로 S·T·A·R·L 5축을 계량화합니다.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={handleOpenRubricModal}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <BookOpen className="w-3.5 h-3.5 text-indigo-600" />
                    <span>평가 기준 레퍼런스</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onJumpToMiner && onJumpToMiner(projectId, "")}
                    className="inline-flex items-center gap-1 rounded-lg border border-violet-300 bg-violet-50 px-2.5 py-1.5 text-xs font-semibold text-violet-900 hover:bg-violet-100"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>경험 채굴 시작 →</span>
                  </button>
                  {(project.experiences || []).length > 0 && (
                    <button
                      type="button"
                      disabled={evaluatingStars}
                      onClick={handleEvaluateProjectStars}
                      className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
                    >
                      {evaluatingStars ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <RefreshCw className="w-3.5 h-3.5" />
                      )}
                      <span>{evaluatingStars ? "21지표 채점 중..." : "21지표 하이브리드 재채점"}</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Project-level 5-Axis STAR-L Radar Card */}
              {(project.experiences || []).length > 0 && (
                <div className="rounded-xl border border-indigo-100 bg-indigo-50/30 p-4 grid grid-cols-1 md:grid-cols-2 gap-4 items-center">
                  <div>
                    <RadarChart
                      items={starRadarItems}
                      size={240}
                      strokeColor="#4f46e5"
                      fillColor="rgba(79, 70, 229, 0.16)"
                    />
                  </div>
                  <div className="space-y-2.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-800">
                        프로젝트 평균 STAR-L 종합
                      </span>
                      <span className="text-base font-extrabold text-indigo-700">
                        {starAvg.evaluated_count > 0 ? `${starAvg.weighted_score}점` : "미채점"}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-500">
                      {starAvg.evaluated_count > 0
                        ? `총 ${starAvg.total_count}건 중 ${starAvg.evaluated_count}건이 5축 BARS 기준으로 평가되었습니다.`
                        : "우측 상단 '5축 BARS 재채점'을 누르면 기존 STAR 경험들의 S·T·A·R·L 5축 점수가 산출됩니다."}
                    </p>
                    <div className="grid grid-cols-5 gap-1.5">
                      {starRadarItems.map((it) => (
                        <div
                          key={it.id}
                          className="rounded-lg bg-white border border-slate-200 p-2 text-center"
                        >
                          <div className="text-[10px] font-bold text-slate-500">
                            {it.label}
                          </div>
                          <div className="text-xs font-extrabold text-slate-900 mt-0.5">
                            {it.score}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {(project.experiences || []).length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 py-8 px-4 text-center space-y-2">
                  <p className="text-sm text-slate-500">
                    연결된 STAR 경험이 없습니다.
                  </p>
                  <button
                    type="button"
                    onClick={() => onJumpToMiner && onJumpToMiner(projectId, "")}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-violet-700"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>이 프로젝트 요약으로 경험 채굴 시작 →</span>
                  </button>
                </div>
              ) : (
                <div className="space-y-4">
                  {project.experiences.map((exp) => (
                    <div
                      key={exp.id}
                      className="rounded-xl border border-slate-200 p-4 space-y-3 text-xs"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => setDetailExp(exp)}
                          className="text-left font-bold text-sm text-slate-900 hover:text-indigo-700"
                        >
                          {exp.title}
                        </button>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            type="button"
                            onClick={() => setDetailExp(exp)}
                            className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-100"
                            title="경험 전문 및 역질문 Q&A 보기"
                          >
                            <Eye className="w-3 h-3" />
                            <span>상세 · Q&amp;A</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setSyncExp(exp)}
                            className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-[11px] font-semibold text-indigo-800 hover:bg-indigo-100"
                            title="이 경험·역질문 내용을 프로젝트 섹션에 다시 정리"
                          >
                            <FolderSync className="w-3 h-3" />
                            <span>프로젝트에 정리</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteExperience(exp)}
                            className="p-1 rounded text-slate-400 hover:bg-red-50 hover:text-red-600"
                            title="STAR 경험 삭제"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                      <div className="space-y-1 text-slate-700">
                        <p>
                          <strong>S:</strong> {exp.situation}
                        </p>
                        <p>
                          <strong>T:</strong> {exp.task}
                        </p>
                        <p>
                          <strong>A:</strong> {exp.action}
                        </p>
                        <p>
                          <strong>R:</strong> {exp.result}
                        </p>
                        {exp.learning && (
                          <p className="text-indigo-900">
                            <strong>L (배운 점·회고):</strong> {exp.learning}
                          </p>
                        )}
                      </div>
                      {exp.quantified_metrics && (
                        <div className="rounded-md bg-emerald-50 px-2.5 py-1 text-emerald-800">
                          <strong>정량 지표:</strong> {exp.quantified_metrics}
                        </div>
                      )}
                      <StarMeter
                        score={exp.completeness_score}
                        starScores={exp.star_scores}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : activeKey === "retro" ? (
            <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-base font-bold text-slate-900">
                    프로젝트 회고 인터뷰 &amp; 다음 프로젝트 학습 루프
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    인터뷰 답변으로 KPT / 4Ls / 의사결정 포스트모템을 구조화하면, 도출된{" "}
                    <strong>Try 규칙</strong>이 <strong>7. 새 프로젝트 코파일럿</strong>과{" "}
                    <strong>6축 캐릭터 외적 축</strong>에 자동 연동됩니다.
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {[
                    { id: "kpt", label: "KPT" },
                    { id: "4ls", label: "4Ls" },
                    { id: "postmortem", label: "의사결정 Post-Mortem" },
                  ].map((fw) => (
                    <button
                      key={fw.id}
                      type="button"
                      onClick={() => setRetroFramework(fw.id)}
                      className={`rounded-lg px-2.5 py-1 text-xs font-semibold border ${
                        retroFramework === fw.id
                          ? "border-indigo-600 bg-indigo-600 text-white"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {fw.label}
                    </button>
                  ))}
                  <button
                    type="button"
                    disabled={loadingRetroQs}
                    onClick={() => handleStartProjectRetro(retroFramework)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    {loadingRetroQs ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="w-3.5 h-3.5" />
                    )}
                    <span>
                      {loadingRetroQs
                        ? "맞춤 회고 질문 생성 중..."
                        : project.retrospective?.summary
                          ? "회고 인터뷰 다시 진행"
                          : "AI 회고 인터뷰 시작"}
                    </span>
                  </button>
                </div>
              </div>

              {retroError && (
                <div className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-xs text-rose-700">
                  {retroError}
                </div>
              )}

              {/* Active Retrospective Interview Form */}
              {retroQs && (
                <form
                  onSubmit={handleApplyProjectRetro}
                  className="rounded-2xl border border-indigo-200 bg-indigo-50/40 p-5 space-y-4 text-xs"
                >
                  {retroQs.opening_note && (
                    <div className="rounded-xl bg-white border border-indigo-100 p-3 text-indigo-950">
                      <strong>인터뷰 가이드 ({(retroQs.framework || "kpt").toUpperCase()}):</strong>{" "}
                      {retroQs.opening_note}
                    </div>
                  )}

                  {(retroQs.questions || []).map((q, idx) => {
                    const dimLabels = {
                      decision: "의사결정 · 트레이드오프 복기",
                      time_ops: "외적 축 · 시간/일정/우선순위",
                      people_collab: "외적 축 · 인적/협업/소통",
                      next_try: "학습 루프 · 다음 프로젝트 Try 규칙",
                    };
                    return (
                      <div
                        key={q.id || idx}
                        className="rounded-xl bg-white border border-slate-200 p-4 space-y-2"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-800">
                            {dimLabels[q.dimension] || q.dimension}
                          </span>
                          {q.why_ask && (
                            <span className="text-[11px] text-slate-500">{q.why_ask}</span>
                          )}
                        </div>
                        <div className="text-sm font-bold text-slate-900">
                          Q{idx + 1}. {q.question}
                        </div>
                        {q.example_hint && (
                          <div className="text-[11px] text-slate-500 bg-slate-50 rounded-lg px-2.5 py-1.5">
                            힌트: {q.example_hint}
                          </div>
                        )}
                        <textarea
                          rows={3}
                          value={retroAnswers[q.id] || ""}
                          onChange={(e) =>
                            setRetroAnswers((prev) => ({
                              ...prev,
                              [q.id]: e.target.value,
                            }))
                          }
                          placeholder="솔직한 시행착오와 다음에 바꿀 구체 기준을 적어주세요 (건너뛰기 가능)"
                          className="w-full rounded-lg border border-slate-200 p-2.5 text-xs"
                        />
                      </div>
                    );
                  })}

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                    <label className="flex items-center gap-2 text-xs text-slate-700">
                      <input
                        type="checkbox"
                        checked={syncRetroToOutcomes}
                        onChange={(e) => setSyncRetroToOutcomes(e.target.checked)}
                      />
                      <span>정리된 회고를 &apos;성과, 지표 &amp; 회고&apos; 섹션에도 자동 반영</span>
                    </label>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setRetroQs(null)}
                        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-slate-600"
                      >
                        취소
                      </button>
                      <button
                        type="submit"
                        disabled={submittingRetro}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-1.5 font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                      >
                        {submittingRetro ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Check className="w-3.5 h-3.5" />
                        )}
                        <span>{submittingRetro ? "회고 구조화 & 저장 중..." : "회고 저장 & 학습 루프 연결"}</span>
                      </button>
                    </div>
                  </div>
                </form>
              )}

              {/* Saved Structured Retrospective View */}
              {project.retrospective?.summary ? (
                <div className="space-y-4 text-xs">
                  <div className="rounded-xl bg-slate-900 text-white p-4 space-y-1.5">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-indigo-300">
                      저장된 프로젝트 회고 ({(project.retrospective.framework || "kpt").toUpperCase()})
                    </div>
                    <p className="text-sm leading-relaxed text-slate-100">
                      {project.retrospective.summary}
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3.5 space-y-1.5">
                      <div className="font-bold text-emerald-900">Keep (유지할 강점)</div>
                      <ul className="space-y-1 text-slate-700">
                        {(project.retrospective.keep || []).map((k, i) => (
                          <li key={i}>• {k}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="rounded-xl border border-rose-200 bg-rose-50/40 p-3.5 space-y-1.5">
                      <div className="font-bold text-rose-900">Problem (객관적 문제)</div>
                      <ul className="space-y-1 text-slate-700">
                        {(project.retrospective.problem || []).map((p, i) => (
                          <li key={i}>• {p}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-3.5 space-y-1.5">
                      <div className="font-bold text-indigo-900">
                        Try (다음 프로젝트 학습 루프 인계)
                      </div>
                      <ul className="space-y-1 text-indigo-950 font-medium">
                        {(project.retrospective.try_items || []).map((t, i) => (
                          <li key={i}>→ {t}</li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  {project.retrospective.decision_revisit && (
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 space-y-1">
                      <div className="font-bold text-slate-800">핵심 의사결정 복기</div>
                      <p className="text-slate-700 leading-relaxed">
                        {project.retrospective.decision_revisit}
                      </p>
                    </div>
                  )}

                  {project.retrospective.external_ops_lessons &&
                    Object.values(project.retrospective.external_ops_lessons).some(Boolean) && (
                      <div className="rounded-xl border border-violet-200 bg-violet-50/30 p-3.5 space-y-1.5">
                        <div className="font-bold text-violet-950">
                          외적 운영 역량 교훈 (포트폴리오 캐릭터 외적 3축 자동 반영)
                        </div>
                        {project.retrospective.external_ops_lessons.time_execution && (
                          <p className="text-slate-700">
                            <strong>시간·일정:</strong>{" "}
                            {project.retrospective.external_ops_lessons.time_execution}
                          </p>
                        )}
                        {project.retrospective.external_ops_lessons.people_collaboration && (
                          <p className="text-slate-700">
                            <strong>인적·협업:</strong>{" "}
                            {project.retrospective.external_ops_lessons.people_collaboration}
                          </p>
                        )}
                        {project.retrospective.external_ops_lessons.adaptability_growth && (
                          <p className="text-slate-700">
                            <strong>적응·회복:</strong>{" "}
                            {project.retrospective.external_ops_lessons.adaptability_growth}
                          </p>
                        )}
                      </div>
                    )}
                </div>
              ) : !retroQs ? (
                <div className="rounded-xl border border-dashed border-slate-200 py-10 px-4 text-center space-y-2.5">
                  <p className="text-sm font-semibold text-slate-700">
                    아직 이 프로젝트의 구조화된 회고가 작성되지 않았습니다.
                  </p>
                  <p className="text-xs text-slate-500 max-w-md mx-auto">
                    프레임워크(KPT / 4Ls / 의사결정 Post-Mortem)를 고르고 AI 회고 인터뷰 4문항에 답하면,
                    면접 꼬리질문 방어용 회고와 다음 프로젝트용 Try 규칙이 자동 정리됩니다.
                  </p>
                  <button
                    type="button"
                    disabled={loadingRetroQs}
                    onClick={() => handleStartProjectRetro(retroFramework)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>AI 프로젝트 회고 인터뷰 시작</span>
                  </button>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  반영된 문서 · GitHub 소스 이력 ({project.documents?.length || 0})
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  이 포트폴리오 업데이트에 활용된 파일(.pdf/.docx/.pptx/.md/.ipynb) 및 GitHub 동기화 이력입니다.
                </p>
              </div>

              {(project.documents || []).length === 0 ? (
                <p className="text-sm text-slate-400 py-8 text-center">
                  아직 반영된 문서 이력이 없습니다. 상단의 &apos;파일·문서로 자동 업데이트&apos;로 발표자료나 기획서를 올려 보세요.
                </p>
              ) : (
                <div className="space-y-2.5">
                  {project.documents.map((doc) => (
                    <div
                      key={doc.id}
                      className="rounded-xl border border-slate-200 p-4 flex items-start justify-between gap-3 text-xs"
                    >
                      <div className="space-y-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <FileCode2 className="w-4 h-4 text-indigo-600 shrink-0" />
                          <span className="font-bold text-slate-900 truncate">
                            {doc.filename}
                          </span>
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-600">
                            {doc.file_format}
                          </span>
                        </div>
                        {doc.extracted_summary && (
                          <p className="text-slate-600">{doc.extracted_summary}</p>
                        )}
                        <div className="flex flex-wrap gap-1 pt-0.5">
                          {(doc.applied_sections || []).map((st, i) => (
                            <span
                              key={i}
                              className="rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-700"
                            >
                              {st}
                            </span>
                          ))}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleDeleteDocument(doc)}
                        className="p-1 rounded text-slate-400 hover:bg-red-50 hover:text-red-600 shrink-0"
                        title="이력 삭제"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      {/* Modal 1: File / Document Upload for Auto Update */}
      {showIngestModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
          <form
            onSubmit={handleIngestDocument}
            className="bg-white rounded-2xl max-w-xl w-full p-6 space-y-4 shadow-xl"
          >
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  파일·문서로 포트폴리오 자동 업데이트
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  기획서·발표자료·보고서·코드를 분석해 프로젝트의 멀티트랙 섹션 중 알맞은 곳에 자동 분배합니다.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowIngestModal(false)}
                className="text-slate-400 hover:text-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="inline-flex rounded-lg bg-slate-100 p-1 text-xs font-semibold">
              <button
                type="button"
                onClick={() => setIngestMode("file")}
                className={`rounded-md px-3 py-1.5 ${
                  ingestMode === "file"
                    ? "bg-white text-slate-900 shadow-sm"
                    : "text-slate-600"
                }`}
              >
                파일 업로드 (.pdf · .docx · .pptx · .md · .ipynb · 코드)
              </button>
              <button
                type="button"
                onClick={() => setIngestMode("paste")}
                className={`rounded-md px-3 py-1.5 ${
                  ingestMode === "paste"
                    ? "bg-white text-slate-900 shadow-sm"
                    : "text-slate-600"
                }`}
              >
                문서 텍스트 붙여넣기
              </button>
            </div>

            {ingestMode === "file" ? (
              <label className="block rounded-xl border-2 border-dashed border-slate-300 hover:border-indigo-400 bg-slate-50 p-6 text-center cursor-pointer transition-colors">
                <input
                  type="file"
                  accept=".pdf,.docx,.pptx,.md,.markdown,.txt,.ipynb,.py,.js,.jsx,.ts,.tsx,.sql,.json,.yaml,.yml"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  className="hidden"
                />
                <FileUp className="w-7 h-7 mx-auto text-indigo-600 mb-2" />
                {uploadFile ? (
                  <div className="text-sm font-semibold text-slate-900">
                    선택됨: {uploadFile.name} (
                    {(uploadFile.size / 1024).toFixed(1)} KB)
                  </div>
                ) : (
                  <div className="space-y-1">
                    <div className="text-sm font-semibold text-slate-700">
                      클릭하여 기획서·발표자료·보고서·코드 파일 선택
                    </div>
                    <div className="text-xs text-slate-500">
                      PDF, Word(DOCX), 발표자료(PPTX), Markdown, Jupyter(.ipynb), 소스코드 (최대 15MB)
                    </div>
                  </div>
                )}
              </label>
            ) : (
              <div className="space-y-2.5">
                <input
                  type="text"
                  value={pastedTitle}
                  onChange={(e) => setPastedTitle(e.target.value)}
                  placeholder="문서 이름 (예: 유저 인터뷰 인사이트 정리.md)"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
                />
                <textarea
                  rows={6}
                  value={pastedText}
                  onChange={(e) => setPastedText(e.target.value)}
                  placeholder="기획서, 발표 스크립트, 노션 문서, 트러블슈팅 메모 등을 그대로 붙여넣으세요..."
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
                />
              </div>
            )}

            <input
              type="text"
              value={ingestInstruction}
              onChange={(e) => setIngestInstruction(e.target.value)}
              placeholder="선택 지시사항 (예: 기획 트랙의 리서치·KPI 성과 중심으로 반영해 주세요)"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
            />

            {ingestError && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-800">
                {ingestError}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowIngestModal(false)}
                className="rounded-lg border border-slate-200 px-3.5 py-2 text-xs font-medium text-slate-700"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={ingesting}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {ingesting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>문서 분석 &amp; 트랙별 Diff 생성 중...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>문서 분석하기</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Modal 2: Section-by-Section Update Diff Review */}
      {updateProposal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-4xl w-full max-h-[88vh] flex flex-col shadow-xl">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  포트폴리오 자동 업데이트 제안 검토
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  소스: {updateProposal.filename} ({updateProposal.parse_info}) — 반영할 항목만 체크해 적용하세요.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setUpdateProposal(null)}
                className="text-slate-400 hover:text-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 overflow-y-auto space-y-5 text-xs">
              {updateProposal.document_summary && (
                <div className="rounded-xl bg-indigo-50 border border-indigo-100 p-3.5 text-indigo-950">
                  <strong>문서 핵심 요약:</strong> {updateProposal.document_summary}
                </div>
              )}

              {(updateProposal.suggested_tech_stack_additions || []).length > 0 && (
                <label className="flex items-center gap-2 rounded-xl border border-slate-200 p-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={applyTechStack}
                    onChange={(e) => setApplyTechStack(e.target.checked)}
                  />
                  <span className="font-semibold text-slate-800">
                    신규 기술·도구·역량 키워드 추가:
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {updateProposal.suggested_tech_stack_additions.map((t, i) => (
                      <span
                        key={i}
                        className="rounded bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800"
                      >
                        + {t}
                      </span>
                    ))}
                  </div>
                </label>
              )}

              <div className="space-y-3">
                <div className="font-bold text-slate-800">
                  섹션별 변경 제안 ({updateProposal.section_updates?.length || 0}건)
                </div>
                {(updateProposal.section_updates || []).length === 0 ? (
                  <p className="text-slate-500">
                    기존 섹션에 추가로 업데이트할 신규 정보가 발견되지 않았습니다.
                  </p>
                ) : (
                  updateProposal.section_updates.map((u, idx) => {
                    const checked = selectedUpdateIndices.has(idx);
                    return (
                      <div
                        key={idx}
                        className={`rounded-xl border p-4 space-y-2.5 ${
                          checked
                            ? "border-indigo-300 bg-indigo-50/20"
                            : "border-slate-200 opacity-60"
                        }`}
                      >
                        <label className="flex items-center justify-between gap-2 cursor-pointer">
                          <div className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() =>
                                setSelectedUpdateIndices((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(idx)) next.delete(idx);
                                  else next.add(idx);
                                  return next;
                                })
                              }
                            />
                            <span
                              className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${getTrackBadgeClass(u.track)}`}
                            >
                              {TRACK_SHORT_LABELS[u.track] || u.track}
                            </span>
                            <span className="font-bold text-sm text-slate-900">
                              {u.title}
                            </span>
                            <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-semibold text-indigo-800">
                              {u.action === "create" ? "신규 작성" : "내용 병합"}
                            </span>
                          </div>
                        </label>
                        {u.change_summary && (
                          <p className="text-indigo-800 font-medium">
                            변경 요약: {u.change_summary}
                          </p>
                        )}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
                            <div className="text-[10px] font-bold uppercase text-slate-400 mb-1">
                              변경 전 (Before)
                            </div>
                            <pre className="whitespace-pre-wrap font-sans text-slate-600 max-h-48 overflow-y-auto">
                              {u.before_content || "(비어 있음)"}
                            </pre>
                          </div>
                          <div className="rounded-lg bg-emerald-50/50 border border-emerald-200 p-3">
                            <div className="text-[10px] font-bold uppercase text-emerald-700 mb-1">
                              업데이트 제안 (After)
                            </div>
                            <pre className="whitespace-pre-wrap font-sans text-slate-800 max-h-48 overflow-y-auto">
                              {u.proposed_content}
                            </pre>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              {(updateProposal.suggested_experiences || []).length > 0 && (
                <div className="space-y-2">
                  <div className="font-bold text-slate-800">
                    신규 STAR 경험 추가 제안 ({updateProposal.suggested_experiences.length}건)
                  </div>
                  {updateProposal.suggested_experiences.map((exp, idx) => (
                    <label
                      key={idx}
                      className="block rounded-xl border border-slate-200 p-3 space-y-1 cursor-pointer"
                    >
                      <div className="flex items-center gap-2 font-bold text-slate-900">
                        <input
                          type="checkbox"
                          checked={selectedExpIndices.has(idx)}
                          onChange={() =>
                            setSelectedExpIndices((prev) => {
                              const next = new Set(prev);
                              if (next.has(idx)) next.delete(idx);
                              else next.add(idx);
                              return next;
                            })
                          }
                        />
                        <span>{exp.title}</span>
                      </div>
                      <p className="text-slate-600 pl-5">
                        <strong>A:</strong> {exp.action} / <strong>R:</strong>{" "}
                        {exp.result}
                      </p>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="px-6 py-4 border-t border-slate-200 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setUpdateProposal(null)}
                className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-700"
              >
                취소
              </button>
              <button
                type="button"
                disabled={applyingUpdates}
                onClick={handleApplyUpdates}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                <Check className="w-3.5 h-3.5" />
                <span>
                  {applyingUpdates
                    ? "반영 중..."
                    : `선택한 섹션 ${selectedUpdateIndices.size}개 + STAR ${selectedExpIndices.size}건 반영`}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal 3: AI Noise Prune Review */}
      {pruneProposal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-4xl w-full max-h-[88vh] flex flex-col shadow-xl">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Eraser className="w-4 h-4 text-amber-600" />
                  <span>쓸데없는 내용 AI 정리 (유형 맞춤 Prune)</span>
                </h3>
                <p className="text-xs text-slate-600 mt-0.5">
                  {pruneProposal.overall_assessment}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPruneProposal(null)}
                className="text-slate-400 hover:text-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 overflow-y-auto space-y-4 text-xs">
              {(pruneProposal.section_prunes || []).length === 0 ? (
                <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-4 text-emerald-900 text-center">
                  제거할 중복이나 불필요한 미사여구가 발견되지 않았습니다. 이미 아주 깔끔합니다!
                </div>
              ) : (
                pruneProposal.section_prunes.map((item) => {
                  const checked = selectedPruneIds.has(item.section_id);
                  return (
                    <div
                      key={item.section_id}
                      className={`rounded-xl border p-4 space-y-2.5 ${
                        checked
                          ? "border-amber-300 bg-amber-50/20"
                          : "border-slate-200 opacity-60"
                      }`}
                    >
                      <label className="flex items-center gap-2 font-bold text-sm text-slate-900 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            setSelectedPruneIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(item.section_id)) next.delete(item.section_id);
                              else next.add(item.section_id);
                              return next;
                            })
                          }
                        />
                        <span>{item.title}</span>
                      </label>

                      {item.reason && (
                        <p className="text-amber-900 font-medium">{item.reason}</p>
                      )}

                      {(item.removed_items || []).length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {item.removed_items.map((rem, rIdx) => (
                            <span
                              key={rIdx}
                              className="rounded-md bg-rose-50 border border-rose-200 px-2 py-0.5 text-[11px] text-rose-800 line-through"
                            >
                              {rem}
                            </span>
                          ))}
                        </div>
                      )}

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
                          <div className="text-[10px] font-bold uppercase text-slate-400 mb-1">
                            정리 전
                          </div>
                          <pre className="whitespace-pre-wrap font-sans text-slate-600 max-h-48 overflow-y-auto">
                            {item.before_content}
                          </pre>
                        </div>
                        <div className="rounded-lg bg-emerald-50/50 border border-emerald-200 p-3">
                          <div className="text-[10px] font-bold uppercase text-emerald-700 mb-1">
                            불필요 내용 제거 후
                          </div>
                          <pre className="whitespace-pre-wrap font-sans text-slate-800 max-h-48 overflow-y-auto">
                            {item.cleaned_content}
                          </pre>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            <div className="px-6 py-4 border-t border-slate-200 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPruneProposal(null)}
                className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-700"
              >
                닫기
              </button>
              {(pruneProposal.section_prunes || []).length > 0 && (
                <button
                  type="button"
                  disabled={applyingPrune || selectedPruneIds.size === 0}
                  onClick={handleApplyPrune}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-4 py-2 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  <Eraser className="w-3.5 h-3.5" />
                  <span>
                    {applyingPrune
                      ? "정리 반영 중..."
                      : `선택한 ${selectedPruneIds.size}개 섹션 정리 적용`}
                  </span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal 4: Full Markdown Export / AI Recap */}
      {markdownModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[85vh] flex flex-col shadow-xl">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between gap-2">
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  {markdownModal.title}
                </h3>
                <p className="text-xs text-slate-500">{markdownModal.subtitle}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleCopyMarkdown}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  {copiedMd ? (
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
                <button
                  type="button"
                  onClick={handleDownloadMarkdown}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>.md 다운로드</span>
                </button>
                <button
                  type="button"
                  onClick={() => setMarkdownModal(null)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-800"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            <div className="p-6 overflow-y-auto prose prose-sm prose-slate max-w-none">
              <ReactMarkdown>{markdownModal.markdown}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}

      {/* Modal 5: Opt-in STAR Deepening Interview */}
      {showStarOnboarding && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
          <form
            onSubmit={handleSubmitStarOnboarding}
            className="bg-white rounded-2xl max-w-2xl w-full max-h-[88vh] flex flex-col shadow-xl"
          >
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <HelpCircle className="w-4 h-4 text-violet-600" />
                  <span>STAR 경험 보강 AI 역질문 (선택)</span>
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  답하고 싶은 질문만 간단히 2~3줄씩 적으셔도 5축 BARS 평가 STAR 경험과 관련 섹션이 자동 보강됩니다.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowStarOnboarding(false)}
                className="text-slate-400 hover:text-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 overflow-y-auto space-y-4 text-xs">
              {loadingStarQs ? (
                <div className="py-10 flex items-center justify-center gap-2 text-slate-600">
                  <Loader2 className="w-4 h-4 animate-spin text-violet-600" />
                  <span>프로젝트 기록에서 빈약한 STAR-L 축을 진단하고 맞춤 역질문을 생성하는 중...</span>
                </div>
              ) : starOnboardingData ? (
                <>
                  {starOnboardingData.diagnosis_summary && (
                    <div className="rounded-xl border border-violet-200 bg-violet-50/60 p-3.5 text-violet-950">
                      <strong>진단 요약:</strong> {starOnboardingData.diagnosis_summary}
                    </div>
                  )}

                  {(starOnboardingData.questions || []).map((q, idx) => (
                    <div
                      key={q.id || idx}
                      className="rounded-xl border border-slate-200 p-4 space-y-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold uppercase text-indigo-800">
                          보강 축: {q.target_axis}
                        </span>
                        <span className="text-[11px] text-slate-500">{q.rationale}</span>
                      </div>
                      <div className="text-sm font-bold text-slate-900">
                        Q{idx + 1}. {q.question}
                      </div>
                      {q.example_hint && (
                        <div className="text-[11px] text-slate-500 bg-slate-50 rounded-lg px-2.5 py-1.5">
                          답변 힌트: {q.example_hint}
                        </div>
                      )}
                      <textarea
                        rows={3}
                        value={starAnswers[q.id] || ""}
                        onChange={(e) =>
                          setStarAnswers((prev) => ({
                            ...prev,
                            [q.id]: e.target.value,
                          }))
                        }
                        placeholder="기억나는 사실, 수치, 선택 이유를 편하게 적어주세요 (비워두면 건너뜁니다)"
                        className="w-full rounded-lg border border-slate-200 p-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                      />
                    </div>
                  ))}

                  <label className="flex items-center gap-2 text-xs text-slate-700 pt-1">
                    <input
                      type="checkbox"
                      checked={applyOnboardingPatches}
                      onChange={(e) => setApplyOnboardingPatches(e.target.checked)}
                    />
                    <span>답변에서 나온 핵심 의사결정·성과를 프로젝트 관련 섹션에도 자동 보강</span>
                  </label>
                </>
              ) : null}

              {onboardingError && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-rose-700">
                  {onboardingError}
                </div>
              )}
            </div>

            <div className="px-6 py-4 border-t border-slate-200 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowStarOnboarding(false)}
                className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-700"
              >
                나중에 하기
              </button>
              <button
                type="submit"
                disabled={loadingStarQs || submittingStarOnboarding || !starOnboardingData}
                className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {submittingStarOnboarding ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Sparkles className="w-3.5 h-3.5" />
                )}
                <span>
                  {submittingStarOnboarding ? "STAR 생성 & 5축 채점 중..." : "답변 반영 및 5축 채점"}
                </span>
              </button>
            </div>
          </form>
        </div>
      )}

      <ExperienceDetailModal
        experience={detailExp}
        projectName={project?.name || ""}
        onClose={() => setDetailExp(null)}
        onOpenProjectSync={(exp) => {
          setDetailExp(null);
          setSyncExp(exp);
        }}
      />

      <ExperienceProjectSyncModal
        experience={syncExp}
        projects={project ? [{ id: project.id, name: project.name }] : []}
        defaultProjectId={project?.id ?? null}
        onClose={() => setSyncExp(null)}
        onSynced={async () => {
          await loadProject(true);
          await onGlobalRefresh();
        }}
      />

      <RubricReferenceModal
        open={showRubricModal}
        onClose={() => setShowRubricModal(false)}
        reference={rubricRef}
      />
    </div>
  );
}
