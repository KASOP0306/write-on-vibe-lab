import { useState } from "react";
import IdentityPortfolioPage from "./pages/IdentityPortfolioPage.jsx";
import ExperienceMinerPage from "./pages/ExperienceMinerPage.jsx";
import CompanyInterestPage from "./pages/CompanyInterestPage.jsx";
import CoverLetterStudioPage from "./pages/CoverLetterStudioPage.jsx";
import CopilotRetroPage from "./pages/CopilotRetroPage.jsx";

const MENU = [
  { id: "identity", label: "1. 신념 & 포트폴리오", component: IdentityPortfolioPage },
  { id: "experience", label: "2. 경험 채굴", component: ExperienceMinerPage },
  { id: "company", label: "3. 기업 & 관심사", component: CompanyInterestPage },
  { id: "cover-letter", label: "4. 자소서 공방", component: CoverLetterStudioPage },
  { id: "copilot", label: "5. 코파일럿 & 회고", component: CopilotRetroPage },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("identity");
  const ActiveComponent =
    MENU.find((item) => item.id === activeTab)?.component ?? IdentityPortfolioPage;

  return (
    <div className="min-h-screen flex bg-slate-50 text-slate-900">
      <aside className="w-64 border-r border-slate-200 bg-white p-4 flex flex-col gap-2">
        <h1 className="text-lg font-bold mb-4">Career AI Agent</h1>
        {MENU.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setActiveTab(item.id)}
            className={`text-left px-3 py-2 rounded-lg text-sm font-medium ${
              activeTab === item.id
                ? "bg-slate-900 text-white"
                : "text-slate-700 hover:bg-slate-100"
            }`}
          >
            {item.label}
          </button>
        ))}
      </aside>
      <main className="flex-1 p-6">
        <ActiveComponent />
      </main>
    </div>
  );
}
