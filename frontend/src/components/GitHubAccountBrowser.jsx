import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Github,
  KeyRound,
  Loader2,
  Lock,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  Unlink,
} from "lucide-react";
import { api } from "../api/client.js";

export default function GitHubAccountBrowser({
  projectCount = 0,
  onSelectRepoForAnalysis,
  onOpenLinkedProject,
}) {
  const [status, setStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [tokenInput, setTokenInput] = useState("");
  const [savingToken, setSavingToken] = useState(false);
  const [error, setError] = useState("");

  const [showBrowser, setShowBrowser] = useState(false);
  const [reposData, setReposData] = useState(null);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [filterMode, setFilterMode] = useState("unlinked"); // "unlinked" | "all"
  const [includeForks, setIncludeForks] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const loadRepos = async (forks = includeForks) => {
    setLoadingRepos(true);
    setError("");
    try {
      const data = await api.listGithubRepos({ includeForks: forks, limit: 60 });
      setReposData(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingRepos(false);
    }
  };

  const loadStatus = async () => {
    setLoadingStatus(true);
    try {
      const st = await api.getGithubStatus();
      setStatus(st);
      if (st?.connected) {
        loadRepos(includeForks);
      } else {
        setReposData(null);
      }
    } catch {
      setStatus({ connected: false });
    } finally {
      setLoadingStatus(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, [projectCount]);

  const handleConnect = async (e) => {
    e.preventDefault();
    if (!tokenInput.trim() || savingToken) return;
    setSavingToken(true);
    setError("");
    try {
      const res = await api.saveGithubToken(tokenInput.trim());
      setStatus(res);
      setTokenInput("");
      setShowBrowser(true);
      await loadRepos(includeForks);
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingToken(false);
    }
  };

  const handleDisconnect = async () => {
    if (!window.confirm("저장된 GitHub 계정 연결을 해제할까요?")) return;
    try {
      await api.deleteGithubToken();
      setStatus({ connected: false, source: "none" });
      setReposData(null);
      setShowBrowser(false);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleToggleForks = async (checked) => {
    setIncludeForks(checked);
    await loadRepos(checked);
  };

  const allRepos = reposData?.repos || [];
  const visibleRepos = allRepos.filter((r) => {
    if (filterMode === "unlinked" && r.is_linked) return false;
    const q = searchQuery.trim().toLowerCase();
    if (!q) return true;
    return (
      r.name.toLowerCase().includes(q) ||
      r.full_name.toLowerCase().includes(q) ||
      (r.description || "").toLowerCase().includes(q) ||
      (r.language || "").toLowerCase().includes(q)
    );
  });

  if (loadingStatus) {
    return null;
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 space-y-3 shadow-sm">
      {!status?.connected ? (
        <form onSubmit={handleConnect} className="space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-slate-900">
              <Github className="w-4 h-4 text-slate-900" />
              <span>GitHub 계정 연결</span>
            </div>
            <a
              href="https://github.com/settings/tokens?type=beta"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11px] font-medium text-indigo-700 hover:underline"
            >
              <span>PAT 발급</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[220px]">
              <KeyRound className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="GitHub Personal Access Token (암호화 저장 · Private 레포/자동 생성 지원)"
                className="w-full rounded-lg border border-slate-200 pl-8 pr-3 py-2 text-xs font-mono"
              />
            </div>
            <button
              type="submit"
              disabled={savingToken || !tokenInput.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {savingToken ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Github className="w-3.5 h-3.5" />}
              <span>{savingToken ? "확인 중..." : "연결"}</span>
            </button>
          </div>

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs text-rose-700">
              {error}
            </div>
          )}
        </form>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {status.avatar_url ? (
                <img
                  src={status.avatar_url}
                  alt={status.username}
                  className="w-6 h-6 rounded-full border border-slate-200"
                />
              ) : (
                <Github className="w-4 h-4 text-slate-900" />
              )}
              <span className="font-bold text-slate-900">
                @{status.username || "GitHub"}
              </span>
              {status.token_hint && (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-500">
                  {status.token_hint}
                </span>
              )}
              {reposData && reposData.unlinked_count > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    setFilterMode("unlinked");
                    setShowBrowser(true);
                  }}
                  className="rounded-full bg-indigo-50 border border-indigo-200 px-2.5 py-0.5 text-[11px] font-bold text-indigo-800 hover:bg-indigo-100"
                >
                  미연결 레포 {reposData.unlinked_count}개
                </button>
              )}
              {reposData && (
                <span className="text-[11px] text-slate-500">
                  연결됨 {reposData.linked_count} / 전체 {reposData.total_count}
                </span>
              )}
            </div>

            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setShowBrowser((v) => !v)}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-800 hover:bg-slate-100"
              >
                <Github className="w-3.5 h-3.5" />
                <span>내 레포 불러오기</span>
                {showBrowser ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>
              <button
                type="button"
                disabled={loadingRepos}
                onClick={() => loadRepos(includeForks)}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                title="레포 목록 새로고침"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loadingRepos ? "animate-spin" : ""}`} />
              </button>
              {status.source === "db" && (
                <button
                  type="button"
                  onClick={handleDisconnect}
                  className="p-1.5 rounded-lg border border-slate-200 text-slate-400 hover:text-rose-600 hover:border-rose-200"
                  title="GitHub 연결 해제"
                >
                  <Unlink className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs text-rose-700">
              {error}
            </div>
          )}

          {showBrowser && (
            <div className="pt-3 border-t border-slate-100 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setFilterMode("unlinked")}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-semibold border ${
                      filterMode === "unlinked"
                        ? "bg-slate-900 text-white border-slate-900"
                        : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    미연결 ({reposData?.unlinked_count ?? 0})
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilterMode("all")}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-semibold border ${
                      filterMode === "all"
                        ? "bg-slate-900 text-white border-slate-900"
                        : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    전체 ({reposData?.total_count ?? 0})
                  </button>
                  <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-600 ml-1 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={includeForks}
                      onChange={(e) => handleToggleForks(e.target.checked)}
                      className="accent-indigo-600"
                    />
                    <span>Fork 포함</span>
                  </label>
                </div>

                <div className="relative min-w-[180px]">
                  <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="레포 검색..."
                    className="w-full rounded-lg border border-slate-200 pl-8 pr-2.5 py-1 text-xs"
                  />
                </div>
              </div>

              {loadingRepos && !reposData ? (
                <div className="py-6 flex items-center justify-center gap-2 text-xs text-slate-500">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>GitHub 레포지토리 조회 중...</span>
                </div>
              ) : visibleRepos.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 py-6 text-center text-xs text-slate-400">
                  표시할 레포지토리가 없습니다.
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 max-h-[340px] overflow-y-auto pr-1">
                  {visibleRepos.map((repo) => (
                    <div
                      key={repo.id || repo.full_name}
                      className={`rounded-xl border p-3 flex flex-col justify-between gap-2 text-xs ${
                        repo.is_linked
                          ? "border-emerald-200 bg-emerald-50/30"
                          : "border-slate-200 bg-slate-50/40 hover:border-indigo-300"
                      }`}
                    >
                      <div className="space-y-1">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-1.5 min-w-0">
                            {repo.private && <Lock className="w-3 h-3 text-amber-600 shrink-0" />}
                            <a
                              href={repo.html_url}
                              target="_blank"
                              rel="noreferrer"
                              className="font-bold text-slate-900 hover:text-indigo-700 truncate"
                            >
                              {repo.name}
                            </a>
                            {repo.language && (
                              <span className="rounded bg-white border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 shrink-0">
                                {repo.language}
                              </span>
                            )}
                          </div>
                          {repo.stargazers_count > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-[10px] text-slate-500 shrink-0">
                              <Star className="w-3 h-3" />
                              {repo.stargazers_count}
                            </span>
                          )}
                        </div>
                        {repo.description && (
                          <p className="text-[11px] text-slate-600 line-clamp-2">
                            {repo.description}
                          </p>
                        )}
                      </div>

                      <div className="flex items-center justify-between pt-1.5 border-t border-slate-200/60">
                        <span className="text-[10px] text-slate-400">
                          {repo.pushed_at
                            ? new Date(repo.pushed_at).toLocaleDateString("ko-KR")
                            : ""}
                        </span>

                        {repo.is_linked ? (
                          <button
                            type="button"
                            onClick={() => onOpenLinkedProject?.(repo.linked_project_id)}
                            className="inline-flex items-center gap-1 rounded-md bg-emerald-100 px-2 py-1 text-[11px] font-semibold text-emerald-800 hover:bg-emerald-200"
                          >
                            <CheckCircle2 className="w-3 h-3" />
                            <span>연결됨 · 열기</span>
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => {
                              setShowBrowser(false);
                              onSelectRepoForAnalysis?.(repo);
                            }}
                            className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-indigo-700"
                          >
                            <Sparkles className="w-3 h-3" />
                            <span>포트폴리오로 가져오기</span>
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
