import { useEffect, useState } from "react";
import { api } from "./api/client.js";
import Sidebar from "./components/Sidebar.jsx";
import IdentityPortfolioPage from "./pages/IdentityPortfolioPage.jsx";
import ExperienceMinerPage from "./pages/ExperienceMinerPage.jsx";
import CompanyInterestPage from "./pages/CompanyInterestPage.jsx";
import CoverLetterStudioPage from "./pages/CoverLetterStudioPage.jsx";
import CopilotRetroPage from "./pages/CopilotRetroPage.jsx";

export default function App() {
  const [activeTab, setActiveTab] = useState("identity");
  const [profile, setProfile] = useState(null);
  const [projects, setProjects] = useState([]);
  const [experiences, setExperiences] = useState([]);
  const [interests, setInterests] = useState([]);
  const [globalError, setGlobalError] = useState("");

  const refreshSharedData = async () => {
    try {
      const [prof, projs, exps, ints] = await Promise.all([
        api.getProfile(),
        api.listProjects(),
        api.listExperiences(),
        api.listInterests(),
      ]);
      setProfile(prof);
      setProjects(projs || []);
      setExperiences(exps || []);
      setInterests(ints || []);
      setGlobalError("");
    } catch (err) {
      setGlobalError(`백엔드 연결 확인 필요: ${err.message}`);
    }
  };

  useEffect(() => {
    refreshSharedData();
  }, []);

  const handleAddInterest = async (keyword, source = "manual") => {
    try {
      await api.createInterest(keyword, source);
      const ints = await api.listInterests();
      setInterests(ints || []);
    } catch (err) {
      alert(err.message);
    }
  };

  const handleDeleteInterest = async (id) => {
    try {
      await api.deleteInterest(id);
      setInterests((prev) => prev.filter((item) => item.id !== id));
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <div className="min-h-screen flex bg-slate-50 text-slate-900">
      <Sidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        profile={profile}
        projectCount={projects.length}
        experienceCount={experiences.length}
        interests={interests}
        onAddInterest={handleAddInterest}
        onDeleteInterest={handleDeleteInterest}
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

        {activeTab === "identity" && (
          <IdentityPortfolioPage
            profile={profile}
            projects={projects}
            onRefresh={refreshSharedData}
          />
        )}
        {activeTab === "experience" && (
          <ExperienceMinerPage
            projects={projects}
            experiences={experiences}
            onRefresh={refreshSharedData}
          />
        )}
        {activeTab === "company" && (
          <CompanyInterestPage
            interests={interests}
            onRefresh={refreshSharedData}
          />
        )}
        {activeTab === "cover-letter" && <CoverLetterStudioPage />}
        {activeTab === "copilot" && (
          <CopilotRetroPage
            projects={projects}
            onAddInterest={handleAddInterest}
          />
        )}
      </main>
    </div>
  );
}
