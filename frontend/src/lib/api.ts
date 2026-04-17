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
export interface ImportTaskStatus {
  task_id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  started_at: string;
  finished_at: string | null;
  progress: {
    candidates?: {
      processed: number;
      inserted: number;
      updated: number;
      skipped: number;
      errors: number;
      total: number;
      error_samples: string[];
    };
    embeddings?: {
      processed: number;
      copied: number;
      missing_source: number;
      errors: number;
      total: number;
      error_samples: string[];
    };
  };
  error: string | null;
}

export const adminApi = {
  listUsers: () => api.get("/api/admin/users"),
  createUser: (data: Record<string, unknown>) => api.post("/api/admin/users", data),
  updateUser: (id: number, data: Record<string, unknown>) => api.put(`/api/admin/users/${id}`, data),
  deactivateUser: (id: number) => api.delete(`/api/admin/users/${id}`),
  resetPassword: (id: number, new_password: string) =>
    api.post(`/api/admin/users/${id}/reset-password`, { new_password }),
  systemStats: () => api.get("/api/admin/system"),
  // Phase 7a: talent-radar import
  startTalentRadarImport: (data: {
    dry_run?: boolean;
    batch_size?: number;
    copy_embeddings?: boolean;
  }) => api.post<ImportTaskStatus>("/api/admin/import-talent-radar", data),
  getTalentRadarImportStatus: (taskId: string) =>
    api.get<ImportTaskStatus>(`/api/admin/import-talent-radar/${taskId}`),
  listImportTasks: () => api.get<ImportTaskStatus[]>("/api/admin/import-tasks"),
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
  activities: (id: number) => api.get(`/api/contracts/${id}/activities`),
  rateHistory: (id: number) => api.get(`/api/contracts/${id}/rate-history`),
};

// ── Pipeline Templates (Phase 1) ─────────────────────────────────────────────
export interface PipelineTemplateSummary {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  archived: boolean;
  stage_count: number;
  created_at: string;
  updated_at: string;
}

export interface StageDef {
  id: number;
  template_id: number;
  name: string;
  order: number;
  category: "internal" | "external" | "terminal";
  is_terminal: boolean;
  terminal_type: "hired" | "rejected" | "withdrawn" | null;
  tracker_enabled: boolean;
  tracker_public_name: string | null;
  sla_max_days: number | null;
  legacy_enum_value: string | null;
  scorecard_schema?: { title?: string | null; questions?: unknown[] } | null;
  created_at: string;
  updated_at: string;
}

export interface RejectionReasonDef {
  id: number;
  template_id: number;
  stage_def_id: number | null;
  name: string;
  order: number;
  category: "hired" | "rejected" | "withdrawn";
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PipelineTemplateDetail {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  archived: boolean;
  created_at: string;
  updated_at: string;
  stages: StageDef[];
  rejection_reasons: RejectionReasonDef[];
}

export const pipelineTemplatesApi = {
  list: (include_archived = false) =>
    api.get<PipelineTemplateSummary[]>("/api/pipeline-templates", {
      params: { include_archived },
    }),
  get: (id: number) => api.get<PipelineTemplateDetail>(`/api/pipeline-templates/${id}`),
  create: (data: { name: string; description?: string; is_default?: boolean }) =>
    api.post<PipelineTemplateDetail>("/api/pipeline-templates", data),
  update: (id: number, data: Partial<{ name: string; description: string; is_default: boolean; archived: boolean }>) =>
    api.patch(`/api/pipeline-templates/${id}`, data),
  archive: (id: number) => api.delete(`/api/pipeline-templates/${id}`),
  clone: (id: number, newName: string) =>
    api.post<PipelineTemplateDetail>(`/api/pipeline-templates/${id}/clone`, null, {
      params: { new_name: newName },
    }),
  addStage: (
    id: number,
    data: {
      name: string;
      order: number;
      category: "internal" | "external" | "terminal";
      is_terminal?: boolean;
      terminal_type?: "hired" | "rejected" | "withdrawn" | null;
    }
  ) => api.post<StageDef>(`/api/pipeline-templates/${id}/stages`, data),
  updateStage: (id: number, stageId: number, data: Partial<StageDef>) =>
    api.patch(`/api/pipeline-templates/${id}/stages/${stageId}`, data),
  reorderStages: (id: number, items: { stage_id: number; order: number }[]) =>
    api.patch(`/api/pipeline-templates/${id}/stages/reorder`, items),
  deleteStage: (id: number, stageId: number) =>
    api.delete(`/api/pipeline-templates/${id}/stages/${stageId}`),
  addRejectionReason: (
    id: number,
    data: { name: string; category: "hired" | "rejected" | "withdrawn"; order?: number; stage_def_id?: number | null }
  ) => api.post<RejectionReasonDef>(`/api/pipeline-templates/${id}/rejection-reasons`, data),
  deactivateRejectionReason: (id: number, reasonId: number) =>
    api.delete(`/api/pipeline-templates/${id}/rejection-reasons/${reasonId}`),
  assignToJob: (jobId: number, templateId: number) =>
    api.post(`/api/pipeline-templates/assign-to-job/${jobId}`, { template_id: templateId }),
};

// ── Pipeline stages (server-driven) ──────────────────────────────────────────
export interface StageInfo {
  stage: string;
  category: "internal" | "external" | "terminal";
  label: string;
  order: number;
  stage_def_id: number | null;
  is_terminal: boolean;
}

export const pipelineApi = {
  stagesForJob: (jobId?: number) =>
    api.get<StageInfo[]>("/api/pipeline/stages", {
      params: jobId !== undefined ? { job_id: jobId } : undefined,
    }),
  kanban: (jobId: number) => api.get(`/api/pipeline/kanban/${jobId}`),
  move: (data: {
    candidate_id: number;
    job_id: number;
    stage?: string;
    stage_def_id?: number;
    notes?: string;
    rating?: number;
    rejection_reason_id?: number;
  }) => api.post("/api/pipeline/move", data),
};

// ── Recommendations (Phase 2) ────────────────────────────────────────────────
export interface LayerPoints {
  points: number;
  max: number;
  reason: string;
}

export interface ScoreBreakdown {
  candidate_id: number;
  job_id: number;
  total: number;
  semantic: LayerPoints;
  skills: LayerPoints;
  salary: LayerPoints;
  location: LayerPoints;
  availability: LayerPoints;
  matching_must: string[];
  gap_must: string[];
  matching_nice: string[];
  gap_nice: string[];
  penalties: string[];
}

export interface CandidateMatch {
  candidate: {
    id: number;
    name: string;
    lastname: string;
    email: string | null;
    location: string | null;
    champion: boolean;
    salary_expectation: number | null;
    salary_currency: string | null;
    years_it_experience: number | null;
    competence_category: string | null;
    tags?: unknown;
    skills?: unknown;
    ai_summary?: string | null;
    avatar_url?: string | null;
  };
  total_score: number;
  breakdown?: ScoreBreakdown;
}

export interface JobMatch {
  job: {
    id: number;
    title: string;
    client_id: number | null;
    location: string | null;
    salary_min: number | null;
    salary_max: number | null;
    remote_policy: string | null;
    status: string | null;
    priority: string | null;
    seniority: string | null;
    industry: string | null;
    deadline: string | null;
  };
  total_score: number;
  breakdown?: ScoreBreakdown;
}

// ── Phase 3 ─────────────────────────────────────────────────────────────────

export interface ScorecardQuestion {
  id: string;
  label: string;
  type: "rating" | "text" | "checkbox" | "select";
  options?: string[];
  required?: boolean;
  description?: string;
}

export interface ScorecardSchema {
  title?: string | null;
  questions: ScorecardQuestion[];
}

export interface ScorecardAnswer {
  question_id: string;
  value: unknown;
}

export interface CandidatePipelineRow {
  candidate_stage_id: number;
  job_id: number;
  job_title: string | null;
  client_id: number | null;
  stage_name: string | null;
  stage_category: string | null;
  is_terminal: boolean;
  moved_at: string | null;
  days_in_stage: number;
  rating: number | null;
  has_scorecard: boolean;
}

// ── Phase 5 ─────────────────────────────────────────────────────────────────

export interface RateHistoryRow {
  id: number;
  candidate_id: number;
  client_id: number | null;
  job_id: number | null;
  rate: number;
  currency: string;
  contract_type: "b2b" | "uop" | "zlecenie";
  start_date: string;
  end_date: string | null;
  notes: string | null;
  recorded_by: number | null;
  created_at: string | null;
}

export interface ConflictRow {
  id: number;
  candidate_id: number;
  client_id: number;
  type: "blacklist" | "current_employment" | "nda" | "competitor";
  reason: string | null;
  active: boolean;
  expires_at: string | null;
  created_by: number | null;
  created_at: string | null;
}

export const phase5Api = {
  diagnostics: () => api.get("/api/embed-diagnostics"),
  initCollections: () => api.post("/api/embed-init"),
  clientsLookup: () => api.get<{ id: number; name: string }[]>("/api/clients-lookup"),
  jobsLookup: () => api.get<{ id: number; title: string }[]>("/api/jobs-lookup"),
  rateHistory: {
    list: (candidateId: number) =>
      api.get<RateHistoryRow[]>(`/api/candidates/${candidateId}/rate-history`),
    create: (
      candidateId: number,
      data: {
        rate: number;
        currency?: string;
        contract_type: "b2b" | "uop" | "zlecenie";
        start_date: string;
        end_date?: string | null;
        client_id?: number | null;
        job_id?: number | null;
        notes?: string | null;
      },
    ) => api.post<RateHistoryRow>(`/api/candidates/${candidateId}/rate-history`, data),
    delete: (rateId: number) => api.delete(`/api/rate-history/${rateId}`),
  },
  conflicts: {
    list: (candidateId: number, active_only = true) =>
      api.get<ConflictRow[]>(`/api/candidates/${candidateId}/conflicts`, {
        params: { active_only },
      }),
    create: (
      candidateId: number,
      data: {
        client_id: number;
        type: "blacklist" | "current_employment" | "nda" | "competitor";
        reason?: string;
        expires_at?: string;
      },
    ) => api.post<ConflictRow>(`/api/candidates/${candidateId}/conflicts`, data),
    deactivate: (conflictId: number) =>
      api.patch(`/api/conflicts/${conflictId}/deactivate`),
  },
};

export const phase3Api = {
  getScorecardSchema: (stageDefId: number) =>
    api.get<{ stage_def_id: number; stage_name: string; schema: ScorecardSchema }>(
      `/api/pipeline-stages/${stageDefId}/scorecard`,
    ),
  setScorecardSchema: (stageDefId: number, schema: ScorecardSchema) =>
    api.put(`/api/pipeline-stages/${stageDefId}/scorecard`, schema),
  submitAnswers: (
    candidateStageId: number,
    data: {
      stage_id: number;
      stage_def_id: number;
      answers: ScorecardAnswer[];
      overall_rating?: number;
      notes?: string;
    },
  ) => api.patch(`/api/pipeline/${candidateStageId}/scorecard`, data),
  slaAlerts: () => api.get<{ count: number; alerts: unknown[] }>("/api/pipeline/overview-sla"),
  candidatePipelines: (candidateId: number) =>
    api.get<{
      candidate_id: number;
      candidate_name: string;
      count: number;
      pipelines: CandidatePipelineRow[];
    }>(`/api/candidates/${candidateId}/pipelines`),
  funnel: (templateId?: number) =>
    api.get("/api/reports/funnel", { params: templateId ? { template_id: templateId } : {} }),
  timeToHire: (daysLookback = 180) =>
    api.get("/api/reports/time-to-hire", { params: { days_lookback: daysLookback } }),
  embedAllJobs: (limit = 200) =>
    api.post("/api/jobs/embed-all", null, { params: { limit } }),
};

// ── Saved searches + match history (Phase 4) ────────────────────────────────

export interface SavedSearchRow {
  id: number;
  user_id: number;
  name: string;
  entity: string;
  filters: Record<string, unknown>;
  shared: boolean;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export const savedSearchesApi = {
  list: (entity?: string) =>
    api.get<SavedSearchRow[]>("/api/saved-searches", {
      params: entity ? { entity } : undefined,
    }),
  create: (data: {
    name: string;
    entity: string;
    filters: Record<string, unknown>;
    shared?: boolean;
    description?: string;
  }) => api.post<SavedSearchRow>("/api/saved-searches", data),
  update: (
    id: number,
    data: Partial<{ name: string; filters: Record<string, unknown>; shared: boolean; description: string }>,
  ) => api.patch<SavedSearchRow>(`/api/saved-searches/${id}`, data),
  delete: (id: number) => api.delete(`/api/saved-searches/${id}`),
};

export interface MatchHistoryRow {
  id: number;
  job_id: number;
  candidate_id: number;
  total_score: number;
  breakdown: ScoreBreakdown | null;
  triggered_by: number | null;
  created_at: string | null;
}

export const matchHistoryApi = {
  list: (jobId: number, candidateId: number, limit = 10) =>
    api.get<MatchHistoryRow[]>(`/api/match-history/${jobId}/${candidateId}`, {
      params: { limit },
    }),
  log: (data: { job_id: number; candidate_id: number; total_score: number; breakdown?: ScoreBreakdown }) =>
    api.post("/api/match-history", data),
};

export const recommendationsApi = {
  forJob: (jobId: number, opts?: { top_k?: number; include_breakdown?: boolean }) =>
    api.get<{ job_id: number; job_title: string; search_type: string; matches: CandidateMatch[] }>(
      `/api/jobs/${jobId}/recommendations`,
      { params: opts },
    ),
  forCandidate: (candidateId: number, opts?: { top_k?: number; include_breakdown?: boolean }) =>
    api.get<{ candidate_id: number; candidate_name: string; matches: JobMatch[] }>(
      `/api/candidates/${candidateId}/recommendations`,
      { params: opts },
    ),
  refreshCriteria: (jobId: number) =>
    api.post<{ job_id: number; must_skills: unknown; nice_skills: unknown; criteria_generated_at: string }>(
      `/api/jobs/${jobId}/refresh-criteria`,
    ),
  previewCriteria: (jobId: number) =>
    api.post<{
      job_id: number;
      must_skills: Array<{ name: string; level?: string | null }>;
      nice_skills: Array<{ name: string; level?: string | null }>;
      source: "ollama" | "heuristic";
      current_must_skills: Array<{ name: string; level?: string | null }>;
      current_nice_skills: Array<{ name: string; level?: string | null }>;
    }>(`/api/jobs/${jobId}/generate-criteria-preview`),
  recomputeScores: (jobId: number, topK = 200) =>
    api.post(`/api/jobs/${jobId}/recompute-scores`, null, { params: { top_k: topK } }),
  assignToJob: (candidateId: number, jobId: number) =>
    api.post(`/api/candidates/${candidateId}/assign-to-job/${jobId}`),
};

export default api;
