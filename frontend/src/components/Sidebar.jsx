import {
  BookHeart,
  Building2,
  ClipboardCheck,
  FileEdit,
  FolderKanban,
  Rocket,
  Sparkles,
} from "lucide-react";

const NAV_ITEMS = [
  { id: "beliefs", label: "1. 나의 신념", icon: BookHeart },
  { id: "portfolio", label: "2. 포트폴리오", icon: FolderKanban },
  { id: "experience", label: "3. 경험 채굴", icon: Sparkles },
  { id: "company", label: "4. 기업 리서치", icon: Building2 },
  { id: "cover-letter", label: "5. 자소서 공방", icon: FileEdit },
  { id: "retro", label: "6. 지원 회고", icon: ClipboardCheck },
  { id: "copilot", label: "7. 프로젝트 코파일럿", icon: Rocket },
];

export default function Sidebar({
  activeTab,
  onSelectTab,
  profile,
  projectCount,
  experienceCount,
  beliefNoteCount = 0,
}) {
  return (
    <aside className="w-64 shrink-0 border-r border-slate-200 bg-white flex flex-col justify-between min-h-screen">
      <div className="p-5 space-y-6">
        {/* Brand */}
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-slate-900 text-white flex items-center justify-center">
            <FolderKanban className="w-4 h-4" />
          </div>
          <h1 className="text-base font-bold tracking-tight text-slate-900">
            Career AI Agent
          </h1>
        </div>

        {/* Career Identity Summary Card */}
        <div
          onClick={() => onSelectTab("beliefs")}
          className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 space-y-2 cursor-pointer hover:border-indigo-300 transition-colors"
        >
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            나의 커리어 신념
          </div>
          <p className="text-xs text-slate-700 leading-relaxed line-clamp-3">
            {profile?.core_beliefs ||
              profile?.career_vision ||
              "신념을 입력해 주세요."}
          </p>
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="inline-flex items-center rounded-md bg-white border border-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700">
              신념·회고 {beliefNoteCount}
            </span>
            <span className="inline-flex items-center rounded-md bg-white border border-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700">
              프로젝트 {projectCount}
            </span>
            <span className="inline-flex items-center rounded-md bg-white border border-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700">
              STAR-L {experienceCount}
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
                <span className="truncate">{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
