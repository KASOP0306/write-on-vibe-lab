import { useEffect, useState } from "react";
import { api } from "./api/client.js";
import Sidebar from "./components/Sidebar.jsx";
import IdentityBeliefsPage from "./pages/IdentityBeliefsPage.jsx";
import IdentityPortfolioPage from "./pages/IdentityPortfolioPage.jsx";
import ExperienceMinerPage from "./pages/ExperienceMinerPage.jsx";
import CompanyInterestPage from "./pages/CompanyInterestPage.jsx";
import CoverLetterStudioPage from "./pages/CoverLetterStudioPage.jsx";
import ProjectCopilotPage from "./pages/ProjectCopilotPage.jsx";
import ApplicationRetroPage from "./pages/ApplicationRetroPage.jsx";

export default function App() {
  const [activeTab, setActiveTab] = useState("beliefs");
  const [profile, setProfile] = useState(null);
  const [projects, setProjects] = useState([]);
  const [experiences, setExperiences] = useState([]);
  const [beliefNotes, setBeliefNotes] = useState([]);
  const [copilotPrefill, setCopilotPrefill] = useState("");
  const [minerPrefill, setMinerPrefill] = useState(null);
  const [globalError, setGlobalError] = useState("");

  const refreshSharedData = async () => {
    try {
      const [prof, projs, exps, notes] = await Promise.all([
        api.getProfile(),
        api.listProjects(),
        api.listExperiences(),
        api.listBeliefNotes().catch(() => []),
      ]);
      setProfile(prof);
      setProjects(projs || []);
      setExperiences(exps || []);
      setBeliefNotes(notes || []);
      setGlobalError("");
    } catch (err) {
      setGlobalError(`백엔드 연결 확인 필요: ${err.message}`);
    }
  };

  useEffect(() => {
    refreshSharedData();
  }, []);

  const handleJumpToCopilot = (topic) => {
    setCopilotPrefill(topic || "");
    setActiveTab("copilot");
  };

  const handleJumpToMiner = (projectId, focusHint = "") => {
    setMinerPrefill({
      projectId: projectId ? String(projectId) : "",
      focusHint: focusHint || "",
      ts: Date.now(),
    });
    setActiveTab("experience");
  };

  const handleBlueprintCreated = async () => {
    await refreshSharedData();
    setActiveTab("portfolio");
  };

  return (
    <div className="min-h-screen flex bg-slate-50 text-slate-900">
      <Sidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        profile={profile}
        projectCount={projects.length}
        experienceCount={experiences.length}
        beliefNoteCount={beliefNotes.length}
      />

      <main className="flex-1 min-w-0 p-6 lg:p-8 max-w-6xl mx-auto w-full">
        {globalError && (
          <div className="mb-5 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 flex items-center justify-between">
            <span>{globalError}</span>
            <button
              type="button"
              onClick={refreshSharedData}
              className="rounded-lg bg-amber-900 text-white px-3 py-1 text-xs font-medium hover:bg-amber-800"
            >
              다시 연결
            </button>
          </div>
        )}

        {activeTab === "beliefs" && (
          <IdentityBeliefsPage
            profile={profile}
            notes={beliefNotes}
            onRefresh={refreshSharedData}
          />
        )}
        {activeTab === "portfolio" && (
          <IdentityPortfolioPage
            profile={profile}
            projects={projects}
            onRefresh={refreshSharedData}
            onJumpToMiner={handleJumpToMiner}
          />
        )}
        {activeTab === "experience" && (
          <ExperienceMinerPage
            projects={projects}
            experiences={experiences}
            onRefresh={refreshSharedData}
            initialPrefill={minerPrefill}
            onConsumeInitialPrefill={() => setMinerPrefill(null)}
          />
        )}
        {activeTab === "company" && (
          <CompanyInterestPage onRefresh={refreshSharedData} />
        )}
        {activeTab === "cover-letter" && <CoverLetterStudioPage />}
        {activeTab === "copilot" && (
          <ProjectCopilotPage
            projects={projects}
            initialTopic={copilotPrefill}
            onConsumeInitialTopic={() => setCopilotPrefill("")}
            onProjectCreated={handleBlueprintCreated}
          />
        )}
        {activeTab === "retro" && (
          <ApplicationRetroPage onJumpToCopilot={handleJumpToCopilot} />
        )}
      </main>
    </div>
  );
}
