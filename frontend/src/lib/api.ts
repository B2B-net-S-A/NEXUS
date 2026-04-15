import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

// Attach token from localStorage
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-redirect on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

// ── Dashboard ────────────────────────────────────────────────────────────────
export const dashboardApi = {
  getStats: () => api.get("/api/dashboard/stats"),
  getKpis: () => api.get("/api/dashboard/kpis"),
  getRecentActivity: (limit = 20) => api.get(`/api/dashboard/recent-activity?limit=${limit}`),
  getPipelineFunnel: () => api.get("/api/dashboard/pipeline-funnel"),
};

// ── Activities ───────────────────────────────────────────────────────────────
export const activitiesApi = {
  getStats: (params: { user_id?: number; period?: string }) =>
    api.get("/api/activities/stats", { params }),
  getLeaderboard: (params: { period?: string; limit?: number }) =>
    api.get("/api/activities/leaderboard", { params }),
};

// ── Candidates ───────────────────────────────────────────────────────────────
export const candidatesApi = {
  list: (params?: Record<string, unknown>) => api.get("/api/candidates", { params }),
  get: (id: number) => api.get(`/api/candidates/${id}`),
  create: (data: Record<string, unknown>) => api.post("/api/candidates", data),
  update: (id: number, data: Record<string, unknown>) => api.patch(`/api/candidates/${id}`, data),
  delete: (id: number) => api.delete(`/api/candidates/${id}`),
  getTimeline: (id: number, limit = 50) =>
    api.get(`/api/candidates/${id}/timeline?limit=${limit}`),
  getHistory: (id: number) => api.get(`/api/candidates/${id}/history`),
  search: (body: Record<string, unknown>) => api.post("/api/search/candidates", body),
};

// ── Admin ─────────────────────────────────────────────────────────────────────
export const adminApi = {
  listUsers: () => api.get("/api/admin/users"),
  createUser: (data: Record<string, unknown>) => api.post("/api/admin/users", data),
  updateUser: (id: number, data: Record<string, unknown>) => api.put(`/api/admin/users/${id}`, data),
  deactivateUser: (id: number) => api.delete(`/api/admin/users/${id}`),
  resetPassword: (id: number, new_password: string) =>
    api.post(`/api/admin/users/${id}/reset-password`, { new_password }),
  systemStats: () => api.get("/api/admin/system"),
};

// ── Job Postings ──────────────────────────────────────────────────────────────
export const postingsApi = {
  list: (jobId: number) => api.get(`/api/jobs/${jobId}/postings`),
  create: (jobId: number, data: { portal: string; expires_days?: number }) =>
    api.post(`/api/jobs/${jobId}/postings`, data),
  update: (id: number, data: { status?: string; views?: number; applications?: number }) =>
    api.put(`/api/postings/${id}`, data),
  delete: (id: number) => api.delete(`/api/postings/${id}`),
  publishAll: (jobId: number, data: { portals: string[]; expires_days?: number }) =>
    api.post(`/api/jobs/${jobId}/publish-all`, data),
  stats: () => api.get("/api/postings/stats"),
};

// ── Reports ───────────────────────────────────────────────────────────────────
export const reportsApi = {
  recruitment: (params: { period?: string; recruitment_type?: string }) =>
    api.get("/api/reports/recruitment", { params }),
  sales: () => api.get("/api/reports/sales"),
  deliveryLeads: (params: { period?: string }) =>
    api.get("/api/reports/delivery-leads", { params }),
  tenders: (params: { period?: string }) =>
    api.get("/api/reports/tenders", { params }),
  board: () => api.get("/api/reports/board"),
};

// ── Prep Kit ──────────────────────────────────────────────────────────────────
export const prepKitApi = {
  generate: (job_id: number, candidate_id: number) =>
    api.post("/api/prep-kit/generate", { job_id, candidate_id }),
};

// ── AI Writer ─────────────────────────────────────────────────────────────────
export const aiWriterApi = {
  generateJobDescription: (data: {
    title: string;
    client_name?: string;
    requirements?: string;
    seniority?: string;
  }) => api.post("/api/ai/generate-job-description", data),

  generateJob: (data: {
    title: string;
    client?: string;
    seniority?: string;
    skills?: string[];
    description_hint?: string;
  }) => api.post("/api/ai/generate-job", data),
};

// ── AI Matching ───────────────────────────────────────────────────────────────
export const matchingApi = {
  getMatches: (jobId: number, topK = 10) =>
    api.get(`/api/jobs/${jobId}/ai-matches`, { params: { top_k: topK } }),
};

// ── Talent Pools ──────────────────────────────────────────────────────────────
export const talentPoolsApi = {
  list: () => api.get("/api/talent-pools"),
  create: (data: { name: string; description?: string; criteria?: Record<string, unknown> }) =>
    api.post("/api/talent-pools", data),
  addCandidate: (poolId: number, candidateId: number) =>
    api.post(`/api/talent-pools/${poolId}/add`, { candidate_id: candidateId }),
  removeCandidate: (poolId: number, candidateId: number) =>
    api.delete(`/api/talent-pools/${poolId}/remove/${candidateId}`),
  getCandidates: (poolId: number) => api.get(`/api/talent-pools/${poolId}/candidates`),
  getPoolsForCandidate: (candidateId: number) =>
    api.get(`/api/talent-pools/for-candidate/${candidateId}`),
};

// ── Jobs ──────────────────────────────────────────────────────────────────────
export const jobsApi = {
  list: (params?: Record<string, unknown>) => api.get("/api/jobs", { params }),
  get: (id: number) => api.get(`/api/jobs/${id}`),
  create: (data: Record<string, unknown>) => api.post("/api/jobs", data),
  update: (id: number, data: Record<string, unknown>) => api.patch(`/api/jobs/${id}`, data),
  delete: (id: number) => api.delete(`/api/jobs/${id}`),
};

// ── CV Generator ─────────────────────────────────────────────────────────────
export const cvGeneratorApi = {
  generateCV: (
    candidateId: number,
    data: { template: "standard" | "blind"; language: "pl" | "en"; job_id?: number }
  ) => api.post(`/api/candidates/${candidateId}/generate-cv`, data),
  generateBlindProfile: (candidateId: number) =>
    api.post(`/api/candidates/${candidateId}/generate-blind-profile`),
};

// ── Calendar ──────────────────────────────────────────────────────────────────
export const calendarApi = {
  listEvents: (params?: {
    from_date?: string;
    to_date?: string;
    event_type?: string;
    status?: string;
  }) => api.get("/api/calendar/events", { params }),
  createEvent: (data: Record<string, unknown>) => api.post("/api/calendar/events", data),
  getEvent: (id: number) => api.get(`/api/calendar/events/${id}`),
  updateEvent: (id: number, data: Record<string, unknown>) =>
    api.patch(`/api/calendar/events/${id}`, data),
  deleteEvent: (id: number) => api.delete(`/api/calendar/events/${id}`),
};

// ── Notifications ─────────────────────────────────────────────────────────────
export const notificationsApi = {
  list: (limit?: number) =>
    api.get("/api/notifications", { params: limit ? { limit } : undefined }),
  count: () => api.get("/api/notifications/count"),
  markRead: (id: number) => api.patch(`/api/notifications/${id}/read`),
  markAllRead: () => api.patch("/api/notifications/read-all"),
};

// ── Contacts ──────────────────────────────────────────────────────────────────
export const contactsApi = {
  listAll: (search?: string) =>
    api.get("/api/contacts", { params: search ? { search } : undefined }),
  listForClient: (clientId: number) =>
    api.get(`/api/clients/${clientId}/contacts`),
  create: (data: Record<string, unknown>) => api.post("/api/contacts", data),
  update: (id: number, data: Record<string, unknown>) => api.put(`/api/contacts/${id}`, data),
  delete: (id: number) => api.delete(`/api/contacts/${id}`),
};

// ── Contracts ─────────────────────────────────────────────────────────────────
export const contractsApi = {
  list: (params?: Record<string, unknown>) => api.get("/api/contracts", { params }),
  get: (id: number) => api.get(`/api/contracts/${id}`),
  create: (data: Record<string, unknown>) => api.post("/api/contracts", data),
  update: (id: number, data: Record<string, unknown>) => api.patch(`/api/contracts/${id}`, data),
  delete: (id: number) => api.delete(`/api/contracts/${id}`),
  expiring: (days?: number) => api.get("/api/contracts/expiring", { params: days ? { days } : undefined }),
};

export default api;
