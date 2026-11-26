import { useEffect, useState } from "react";
import {
  Check,
  ExternalLink,
  GitCommit,
  GitPullRequest,
  Github,
  KeyRound,
  Loader2,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { api } from "../api/client.js";

function formatShortDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(
      d.getDate()
    ).padStart(2, "0")}`;
  } catch {
    return iso.slice(0, 10);
  }
}

export default function GitHubActivityPickerModal({
  open,
  project,
  onClose,
  onDiffReady,
}) {
  const [tab, setTab] = useState("pulls"); // "pulls" | "commits"
  const [loading, setLoading] = useState(false);
  const [fetchingDiff, setFetchingDiff] = useState(false);
  const [error, setError] = useState("");
  const [activity, setActivity] = useState(null);

  const [selectedPRs, setSelectedPRs] = useState([]);
  const [selectedCommits, setSelectedCommits] = useState([]);

  const [showTokenInput, setShowTokenInput] = useState(false);
  const [githubToken, setGithubToken] = useState("");
  const [repoUrlOverride, setRepoUrlOverride] = useState("");

  const loadActivity = async (overrideToken = null, overrideUrl = null) => {
    if (!project?.id) return;
    setLoading(true);
    setError("");
    try {
      const res = await api.getProjectGithubActivity(project.id, {
        repo_url: (overrideUrl ?? repoUrlOverride).trim(),
        github_token: (overrideToken ?? githubToken).trim(),
        limit: 15,
      });
      setActivity(res);
      setSelectedPRs([]);
      setSelectedCommits([]);
      // PR이 하나도 없고 커밋만 있으면 자동으로 커밋 탭으로 전환
      if ((res.pull_requests || []).length === 0 && (res.commits || []).length > 0) {
        setTab("commits");
      } else {
        setTab("pulls");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && project?.id) {
      setRepoUrlOverride(project.repo_url || "");
      if (project.repo_url) {
        loadActivity("", project.repo_url);
      } else {
        setActivity(null);
      }
    }
  }, [open, project?.id]);

  if (!open || !project) return null;

  const togglePR = (num) => {
    setSelectedPRs((prev) => {
      if (prev.includes(num)) return prev.filter((x) => x !== num);
      if (prev.length >= 3) return prev;
      return [...prev, num];
    });
  };

  const toggleCommit = (sha) => {
    setSelectedCommits((prev) => {
      if (prev.includes(sha)) return prev.filter((x) => x !== sha);
      if (prev.length >= 5) return prev;
      return [...prev, sha];
    });
  };

  const totalSelected = selectedPRs.length + selectedCommits.length;

  const handleLoadDiff = async () => {
    if (totalSelected === 0 || fetchingDiff) return;
    setFetchingDiff(true);
    setError("");
    try {
      const res = await api.getProjectGithubDiffContext(project.id, {
        repo_url: repoUrlOverride.trim(),
        github_token: githubToken.trim(),
        pr_numbers: selectedPRs,
        commit_shas: selectedCommits,
      });
      if (onDiffReady) {
        onDiffReady(res, project);
      }
      onClose();
    } catch (err) {
      setError(`Diff 추출 실패: ${err.message}`);
    } finally {
      setFetchingDiff(false);
    }
  };

  const prs = activity?.pull_requests || [];
  const commits = activity?.commits || [];

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[88vh] flex flex-col shadow-xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-3">
          <div>
            <div className="inline-flex items-center gap-1.5 text-xs font-bold text-indigo-700">
              <Github className="w-4 h-4" />
              <span>GitHub PR · Push 커밋 온디맨드 변경 이력 조회</span>
            </div>
            <h3 className="text-base font-bold text-slate-900 mt-0.5">
              {project.name} — 실제 코드 변경점으로 경험 채굴하기
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              PR(최대 3개) 또는 Push 커밋(최대 5개)을 고르면 실제 코드 Diff와 리뷰 코멘트를 읽어와 의사결정·성과 역질문을 시작합니다.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Repo URL + Optional PAT bar */}
        <div className="px-6 py-3 bg-slate-50 border-b border-slate-200 space-y-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={repoUrlOverride}
              onChange={(e) => setRepoUrlOverride(e.target.value)}
              placeholder="https://github.com/owner/repo"
              className="flex-1 min-w-[220px] rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs"
            />
            <button
              type="button"
              onClick={() => setShowTokenInput((v) => !v)}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
            >
              <KeyRound className="w-3.5 h-3.5 text-amber-600" />
              <span>Private / PAT</span>
            </button>
            <button
              type="button"
              disabled={loading || !repoUrlOverride.trim()}
              onClick={() => loadActivity()}
              className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              <span>불러오기</span>
            </button>
          </div>

          {showTokenInput && (
            <input
              type="password"
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
              placeholder="1회용 GitHub Personal Access Token (DB 미저장 · Private 레포 또는 Rate Limit 우회용)"
              className="w-full rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-xs"
            />
          )}
        </div>

        {/* Tabs */}
        <div className="px-6 pt-3 border-b border-slate-200 flex items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setTab("pulls")}
              className={`inline-flex items-center gap-1.5 px-3 py-2 font-bold border-b-2 transition ${
                tab === "pulls"
                  ? "border-indigo-600 text-indigo-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <GitPullRequest className="w-3.5 h-3.5" />
              <span>Pull Requests ({prs.length})</span>
              {selectedPRs.length > 0 && (
                <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] text-indigo-800">
                  {selectedPRs.length}
                </span>
              )}
            </button>

            <button
              type="button"
              onClick={() => setTab("commits")}
              className={`inline-flex items-center gap-1.5 px-3 py-2 font-bold border-b-2 transition ${
                tab === "commits"
                  ? "border-indigo-600 text-indigo-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <GitCommit className="w-3.5 h-3.5" />
              <span>최근 Push 커밋 ({commits.length})</span>
              {selectedCommits.length > 0 && (
                <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] text-indigo-800">
                  {selectedCommits.length}
                </span>
              )}
            </button>
          </div>

          <span className="text-[11px] text-slate-500">
            선택됨: PR {selectedPRs.length}/3 · 커밋 {selectedCommits.length}/5
          </span>
        </div>

        {/* Body */}
        <div className="p-5 overflow-y-auto flex-1 space-y-2.5 text-xs">
          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-800">
              {error}
            </div>
          )}

          {loading ? (
            <div className="py-12 flex items-center justify-center gap-2 text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
              <span>GitHub PR 및 Push 커밋 이력을 불러오는 중...</span>
            </div>
          ) : !activity ? (
            <div className="py-10 text-center text-slate-500">
              상단에 GitHub 저장소 URL을 입력하고 <strong>[불러오기]</strong>를 눌러주세요.
            </div>
          ) : tab === "pulls" ? (
            prs.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 py-10 px-4 text-center space-y-2 text-slate-500">
                <p>이 저장소에는 Pull Request 기록이 없습니다.</p>
                <button
                  type="button"
                  onClick={() => setTab("commits")}
                  className="rounded-lg bg-indigo-50 border border-indigo-200 px-3 py-1.5 text-xs font-semibold text-indigo-800 hover:bg-indigo-100"
                >
                  최근 Push 커밋 탭으로 보기 ({commits.length}건) →
                </button>
              </div>
            ) : (
              prs.map((pr) => {
                const checked = selectedPRs.includes(pr.number);
                const disabled = !checked && selectedPRs.length >= 3;
                const stateCls =
                  pr.state === "merged"
                    ? "bg-violet-100 text-violet-800"
                    : pr.state === "open"
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-slate-200 text-slate-700";
                const stateLabel =
                  pr.state === "merged" ? "Merged" : pr.state === "open" ? "Open" : "Closed";
                return (
                  <div
                    key={pr.number}
                    onClick={() => !disabled && togglePR(pr.number)}
                    className={`rounded-xl border p-3.5 flex items-start justify-between gap-3 cursor-pointer transition ${
                      checked
                        ? "border-indigo-500 bg-indigo-50/40 ring-2 ring-indigo-500/15"
                        : disabled
                          ? "border-slate-200 bg-slate-50 opacity-50 cursor-not-allowed"
                          : "border-slate-200 bg-white hover:border-slate-300"
                    }`}
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${stateCls}`}>
                          {stateLabel}
                        </span>
                        <span className="font-mono font-bold text-indigo-700">#{pr.number}</span>
                        <span className="font-bold text-slate-900">{pr.title}</span>
                      </div>
                      <div className="text-[11px] text-slate-500 flex flex-wrap items-center gap-2">
                        <span>{pr.head_ref} → {pr.base_ref}</span>
                        <span>·</span>
                        <span>{pr.author}</span>
                        <span>·</span>
                        <span>{formatShortDate(pr.updated_at)}</span>
                        {pr.html_url && (
                          <a
                            href={pr.html_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-0.5 text-indigo-600 hover:underline"
                          >
                            <span>GitHub</span>
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                      {pr.body_preview && (
                        <p className="text-[11px] text-slate-600 line-clamp-2">{pr.body_preview}</p>
                      )}
                    </div>
                    <span
                      className={`w-5 h-5 rounded-md border flex items-center justify-center shrink-0 mt-0.5 ${
                        checked ? "bg-indigo-600 border-indigo-600 text-white" : "border-slate-300 bg-white"
                      }`}
                    >
                      {checked && <Check className="w-3.5 h-3.5" />}
                    </span>
                  </div>
                );
              })
            )
          ) : commits.length === 0 ? (
            <div className="py-10 text-center text-slate-500">커밋 이력이 없습니다.</div>
          ) : (
            commits.map((cm) => {
              const checked = selectedCommits.includes(cm.sha);
              const disabled = !checked && selectedCommits.length >= 5;
              return (
                <div
                  key={cm.sha}
                  onClick={() => !disabled && toggleCommit(cm.sha)}
                  className={`rounded-xl border p-3 flex items-start justify-between gap-3 cursor-pointer transition ${
                    checked
                      ? "border-indigo-500 bg-indigo-50/40 ring-2 ring-indigo-500/15"
                      : disabled
                        ? "border-slate-200 bg-slate-50 opacity-50 cursor-not-allowed"
                        : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <div className="min-w-0 space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-slate-700">
                        {cm.short_sha}
                      </span>
                      <span className="font-semibold text-slate-900 truncate">{cm.first_line}</span>
                    </div>
                    <div className="text-[11px] text-slate-500 flex items-center gap-2">
                      <span>{cm.author}</span>
                      <span>·</span>
                      <span>{formatShortDate(cm.date)}</span>
                      {cm.html_url && (
                        <a
                          href={cm.html_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center gap-0.5 text-indigo-600 hover:underline"
                        >
                          <span>Diff 보기</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  </div>
                  <span
                    className={`w-5 h-5 rounded-md border flex items-center justify-center shrink-0 mt-0.5 ${
                      checked ? "bg-indigo-600 border-indigo-600 text-white" : "border-slate-300 bg-white"
                    }`}
                  >
                    {checked && <Check className="w-3.5 h-3.5" />}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11px] text-slate-500">
            코드 Diff와 리뷰 코멘트를 추출해 <strong>3. 경험 채굴</strong>의 근거 메모로 자동 주입합니다.
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100"
            >
              취소
            </button>
            <button
              type="button"
              disabled={totalSelected === 0 || fetchingDiff}
              onClick={handleLoadDiff}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {fetchingDiff ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Sparkles className="w-3.5 h-3.5" />
              )}
              <span>
                {fetchingDiff
                  ? "실제 코드 Diff 추출 중..."
                  : `선택한 ${totalSelected}건 Diff로 경험 채굴 시작 →`}
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
