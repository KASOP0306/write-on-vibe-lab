/**
 * REST fetch 및 ReadableStream 기반 SSE 스트림 파서 클라이언트
 */

export async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
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
  // Profile & Interests
  getProfile: () => apiRequest("/api/profile"),
  updateProfile: (data) =>
    apiRequest("/api/profile", { method: "PUT", body: JSON.stringify(data) }),
  listInterests: () => apiRequest("/api/interests"),
  createInterest: (keyword, source = "manual") =>
    apiRequest("/api/interests", {
      method: "POST",
      body: JSON.stringify({ keyword, source }),
    }),
  deleteInterest: (id) =>
    apiRequest(`/api/interests/${id}`, { method: "DELETE" }),

  // Projects & Experiences
  listProjects: () => apiRequest("/api/projects"),
  getProject: (id) => apiRequest(`/api/projects/${id}`),
  createProject: (data) =>
    apiRequest("/api/projects", { method: "POST", body: JSON.stringify(data) }),
  updateProject: (id, data) =>
    apiRequest(`/api/projects/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProject: (id) =>
    apiRequest(`/api/projects/${id}`, { method: "DELETE" }),
  recapProject: (id) =>
    apiRequest(`/api/projects/${id}/recap`, { method: "POST" }),
  analyzeGithubRepo: (data) =>
    apiRequest("/api/projects/analyze-github", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  importGithubProject: (data) =>
    apiRequest("/api/projects/import-github", {
      method: "POST",
      body: JSON.stringify(data),
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
  generateCoverLetter: (body, onEvent) =>
    streamSSE("/api/agents/cover-letter/generate", body, onEvent),
  copilotChat: (body, onEvent) =>
    streamSSE("/api/agents/copilot/chat", body, onEvent),
  retrospectApplication: (body, onEvent) =>
    streamSSE("/api/agents/applications/retrospect", body, onEvent),
};
