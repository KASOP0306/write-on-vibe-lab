import { useState } from "react";
import {
  Briefcase,
  Building2,
  Compass,
  FileEdit,
  FolderKanban,
  Plus,
  Sparkles,
  Tag,
  X,
} from "lucide-react";

const NAV_ITEMS = [
  { id: "identity", label: "신념 & 포트폴리오", icon: Compass },
  { id: "experience", label: "경험 채굴", icon: Sparkles },
  { id: "company", label: "기업 & 관심사", icon: Building2 },
  { id: "cover-letter", label: "자소서 공방", icon: FileEdit },
  { id: "copilot", label: "코파일럿 & 회고", icon: Briefcase },
];

export default function Sidebar({
  activeTab,
  onSelectTab,
  profile,
  projectCount,
  experienceCount,
  interests,
  onAddInterest,
  onDeleteInterest,
}) {
  const [newKeyword, setNewKeyword] = useState("");
  const [adding, setAdding] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmed = newKeyword.trim();
    if (!trimmed || adding) return;
    setAdding(true);
    try {
      await onAddInterest(trimmed, "manual");
      setNewKeyword("");
    } finally {
      setAdding(false);
    }
  };

  return (
    <aside className="w-72 shrink-0 border-r border-slate-200 bg-white flex flex-col justify-between min-h-screen">
      <div className="p-5 space-y-6">
        {/* Brand */}
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-slate-900 text-white flex items-center justify-center">
            <FolderKanban className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-slate-900">
              Career AI Agent
            </h1>
            <p className="text-xs text-slate-500">Closed-Loop Portfolio MVP</p>
          </div>
        </div>

        {/* Career Identity Summary Card */}
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            나의 커리어 신념
          </div>
          <p className="text-xs text-slate-700 leading-relaxed line-clamp-3">
            {profile?.core_beliefs ||
              profile?.career_vision ||
              "아직 신념이 설정되지 않았습니다. '신념 & 포트폴리오'에서 입력해 주세요."}
          </p>
          <div className="flex items-center gap-2 pt-1">
            <span className="inline-flex items-center rounded-md bg-white border border-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700">
              프로젝트 {projectCount}
            </span>
            <span className="inline-flex items-center rounded-md bg-white border border-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700">
              STAR 경험 {experienceCount}
            </span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelectTab(item.id)}
                className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-slate-900 text-white shadow-sm"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Interest Tags Quick Manager */}
        <div className="space-y-2.5 pt-2 border-t border-slate-200">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-600">
            <Tag className="w-3.5 h-3.5" />
            <span>관심 분야 태그 ({interests.length})</span>
          </div>

          <form onSubmit={handleSubmit} className="flex gap-1.5">
            <input
              type="text"
              value={newKeyword}
              onChange={(e) => setNewKeyword(e.target.value)}
              placeholder="키워드 추가 (예: LangGraph)"
              className="flex-1 min-w-0 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-slate-900/15"
            />
            <button
              type="submit"
              disabled={adding || !newKeyword.trim()}
              className="rounded-lg bg-slate-900 px-2.5 py-1.5 text-white hover:bg-slate-800 disabled:opacity-40"
              title="관심 키워드 추가"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </form>

          <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
            {interests.length === 0 ? (
              <span className="text-[11px] text-slate-400">
                등록된 관심 키워드가 없습니다.
              </span>
            ) : (
              interests.map((item) => (
                <span
                  key={item.id}
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                    item.source === "retrospective_suggested"
                      ? "bg-amber-50 text-amber-800 border border-amber-200"
                      : "bg-slate-100 text-slate-700"
                  }`}
                >
                  <span className="truncate max-w-[140px]">{item.keyword}</span>
                  <button
                    type="button"
                    onClick={() => onDeleteInterest(item.id)}
                    className="hover:text-red-600"
                    aria-label={`${item.keyword} 삭제`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="p-4 border-t border-slate-100 text-[11px] text-slate-400">
        AWS Bedrock · LangGraph · pgvector
      </div>
    </aside>
  );
}
