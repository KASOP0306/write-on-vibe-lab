/**
 * REST fetch, Multipart 파일 업로드, ReadableStream 기반 SSE 스트림 파서 클라이언트
 */

export async function apiRequest(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = isFormData
    ? { ...(options.headers || {}) }
    : {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      };

  const response = await fetch(path, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errJson = await response.json();
      detail = errJson.detail || JSON.stringify(errJson);
    } catch {
      const text = await response.text();
      if (text) detail = text;
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

export async function streamSSE(path, body, onEvent) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok || !response.body) {
    let detail = `SSE HTTP ${response.status}`;
    try {
      const text = await response.text();
      if (text) detail = text;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const processChunk = (chunkText) => {
    const lines = chunkText.split(/\r?\n/);
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line.startsWith("data:")) continue;
      const jsonText = line.slice(5).trim();
      if (!jsonText) continue;
      try {
        onEvent(JSON.parse(jsonText));
      } catch (err) {
        console.warn("Failed to parse SSE event:", jsonText, err);
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() || "";

    for (const part of parts) {
      if (part.trim()) processChunk(part);
    }
  }

  if (buffer.trim()) {
    processChunk(buffer);
  }
}

export const api = {
  // Profile & Belief Notes (Quotes / Lectures / Thoughts)
  getProfile: () => apiRequest("/api/profile"),
  updateProfile: (data) =>
    apiRequest("/api/profile", { method: "PUT", body: JSON.stringify(data) }),
  listBeliefNotes: (sourceType = null) =>
    apiRequest(
      sourceType
        ? `/api/beliefs/notes?source_type=${encodeURIComponent(sourceType)}`
        : "/api/beliefs/notes"
    ),
  createBeliefNote: (data) =>
    apiRequest("/api/beliefs/notes", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateBeliefNote: (id, data) =>
    apiRequest(`/api/beliefs/notes/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteBeliefNote: (id) =>
    apiRequest(`/api/beliefs/notes/${id}`, { method: "DELETE" }),
  reflectBeliefNote: (id) =>
    apiRequest(`/api/beliefs/notes/${id}/reflect`, { method: "POST" }),
  synthesizeIdentityFromNotes: () =>
    apiRequest("/api/beliefs/synthesize-identity", { method: "POST" }),

  // Projects, Modular Sections, Documents, Rubrics, STAR Onboarding & Diagnosis
  getProjectTemplates: () => apiRequest("/api/projects/templates"),
  getRubricReference: () => apiRequest("/api/projects/rubric-reference"),
  getProjectsLearningLoop: () => apiRequest("/api/projects/learning-loop"),
  getPortfolioDiagnosis: () => apiRequest("/api/projects/portfolio-diagnosis"),
  runPortfolioDiagnosis: (externalNotes = null) =>
    apiRequest("/api/projects/portfolio-diagnosis", {
      method: "POST",
      body: JSON.stringify({ external_notes: externalNotes }),
    }),
  listProjects: (projectType = null) =>
    apiRequest(
      projectType
        ? `/api/projects?project_type=${encodeURIComponent(projectType)}`
        : "/api/projects"
    ),
  getProject: (id) => apiRequest(`/api/projects/${id}`),
  createProject: (data) =>
    apiRequest("/api/projects", { method: "POST", body: JSON.stringify(data) }),
  updateProject: (id, data) =>
    apiRequest(`/api/projects/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProject: (id) =>
    apiRequest(`/api/projects/${id}`, { method: "DELETE" }),
  addProjectTracks: (projectId, addTypes) =>
    apiRequest(`/api/projects/${projectId}/tracks`, {
      method: "POST",
      body: JSON.stringify({ add_types: addTypes }),
    }),
  recapProject: (id) =>
    apiRequest(`/api/projects/${id}/recap`, { method: "POST" }),
  exportProjectMarkdown: (id) =>
    apiRequest(`/api/projects/${id}/export-markdown`),

  createSection: (projectId, data) =>
    apiRequest(`/api/projects/${projectId}/sections`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateSection: (projectId, sectionId, data) =>
    apiRequest(`/api/projects/${projectId}/sections/${sectionId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteSection: (projectId, sectionId) =>
    apiRequest(`/api/projects/${projectId}/sections/${sectionId}`, {
      method: "DELETE",
    }),

  analyzeDocumentToProject: (formData) =>
    apiRequest("/api/projects/analyze-document", {
      method: "POST",
      body: formData,
    }),
  analyzeGithubRepo: (data) =>
    apiRequest("/api/projects/analyze-github", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  analyzeGithubStream: (data, onEvent) =>
    streamSSE("/api/projects/analyze-github/stream", data, onEvent),
  importStructuredProject: (data) =>
    apiRequest("/api/projects/import-structured", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  importGithubProject: (data) =>
    apiRequest("/api/projects/import-github", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  syncProjectGithub: (projectId, data = {}) =>
    apiRequest(`/api/projects/${projectId}/sync-github`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  ingestProjectDocument: (projectId, formData) =>
    apiRequest(`/api/projects/${projectId}/ingest-document`, {
      method: "POST",
      body: formData,
    }),
  ingestSectionDocument: (projectId, sectionId, formData) =>
    apiRequest(`/api/projects/${projectId}/sections/${sectionId}/ingest-document`, {
      method: "POST",
      body: formData,
    }),
  getStarOnboardingQuestions: (projectId) =>
    apiRequest(`/api/projects/${projectId}/star-onboarding/questions`, {
      method: "POST",
    }),
  applyStarOnboarding: (projectId, data) =>
    apiRequest(`/api/projects/${projectId}/star-onboarding/apply`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  evaluateProjectStars: (projectId) =>
    apiRequest(`/api/projects/${projectId}/evaluate-stars`, {
      method: "POST",
    }),
  getProjectRetroQuestions: (projectId, framework = "kpt") =>
    apiRequest(`/api/projects/${projectId}/retrospective/questions`, {
      method: "POST",
      body: JSON.stringify({ framework }),
    }),
  applyProjectRetrospective: (projectId, data) =>
    apiRequest(`/api/projects/${projectId}/retrospective/apply`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  applyProjectUpdates: (projectId, data) =>
    apiRequest(`/api/projects/${projectId}/apply-updates`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteProjectDocument: (projectId, docId) =>
    apiRequest(`/api/projects/${projectId}/documents/${docId}`, {
      method: "DELETE",
    }),

  pruneProject: (projectId) =>
    apiRequest(`/api/projects/${projectId}/prune`, { method: "POST" }),
  applyProjectPrune: (projectId, updates) =>
    apiRequest(`/api/projects/${projectId}/prune/apply`, {
      method: "POST",
      body: JSON.stringify({ updates }),
    }),

  listExperiences: (projectId = null) =>
    apiRequest(projectId ? `/api/experiences?project_id=${projectId}` : "/api/experiences"),
  deleteExperience: (id) =>
    apiRequest(`/api/experiences/${id}`, { method: "DELETE" }),

  // Companies & Clips & Samples & Applications
  listCompanies: () => apiRequest("/api/companies"),
  deleteCompany: (id) =>
    apiRequest(`/api/companies/${id}`, { method: "DELETE" }),
  listInterestClips: () => apiRequest("/api/interests/clips"),
  saveInterestClip: (data) =>
    apiRequest("/api/agents/interests/clip", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listSamples: () => apiRequest("/api/samples"),
  createSample: (data) =>
    apiRequest("/api/samples", { method: "POST", body: JSON.stringify(data) }),
  deleteSample: (refId) =>
    apiRequest(`/api/samples/${encodeURIComponent(refId)}`, { method: "DELETE" }),
  listCoverLetters: (companyName = "") =>
    apiRequest(
      companyName
        ? `/api/cover-letters?company_name=${encodeURIComponent(companyName)}`
        : "/api/cover-letters"
    ),
  createCoverLetter: (data) =>
    apiRequest("/api/cover-letters", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateCoverLetter: (id, data) =>
    apiRequest(`/api/cover-letters/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteCoverLetter: (id) =>
    apiRequest(`/api/cover-letters/${id}`, { method: "DELETE" }),
  listApplications: () => apiRequest("/api/applications"),
  deleteApplication: (id) =>
    apiRequest(`/api/applications/${id}`, { method: "DELETE" }),

  // SSE Agent Streams
  startInterview: (body, onEvent) =>
    streamSSE("/api/agents/interview/start", body, onEvent),
  replyInterview: (body, onEvent) =>
    streamSSE("/api/agents/interview/reply", body, onEvent),
  researchCompany: (body, onEvent) =>
    streamSSE("/api/agents/company/research", body, onEvent),
  searchInterests: (body, onEvent) =>
    streamSSE("/api/agents/interests/search", body, onEvent),
  recommendCoverLetter: (body) =>
    apiRequest("/api/agents/cover-letter/recommend", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  generateCoverLetter: (body, onEvent) =>
    streamSSE("/api/agents/cover-letter/generate", body, onEvent),
  proposeNewProjects: (body) =>
    apiRequest("/api/agents/copilot/propose-projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  copilotChat: (body, onEvent) =>
    streamSSE("/api/agents/copilot/chat", body, onEvent),
  getCopilotHistory: (threadId) =>
    apiRequest(`/api/agents/copilot/history/${encodeURIComponent(threadId)}`),
  listCopilotMemories: () => apiRequest("/api/agents/copilot/memories"),
  deleteCopilotMemory: (key) =>
    apiRequest(`/api/agents/copilot/memories/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),
  retrospectApplication: (body, onEvent) =>
    streamSSE("/api/agents/applications/retrospect", body, onEvent),
};
