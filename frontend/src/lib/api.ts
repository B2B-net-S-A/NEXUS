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

// ── KPI Coach ────────────────────────────────────────────────────────────────

export type KpiPeriod = "day" | "week" | "month";
export type KpiState = "on_track" | "ahead" | "behind" | "hit" | "missed";

export interface KpiResult {
  kpi_id: string;
  period: KpiPeriod;
  title_pl: string;
  description_pl: string;
  target: number;
  current: number;
  progress_pct: number;
  state: KpiState;
  deadline_hours_left: number;
}

export const kpisApi = {
  /** KPI rekrutera dla current usera (pusta lista dla ról nieoperacyjnych). */
  myToday: () => api.get<KpiResult[]>("/api/kpis/me/today"),
  /** KPI dowolnego usera — dla delivery_leada / admina monitorującego team. */
  userToday: (userId: number) =>
    api.get<KpiResult[]>(`/api/kpis/users/${userId}/today`),
};

// ── Candidates ───────────────────────────────────────────────────────────────

/** AI-extracted CV data — Phase D4 adds `companies` and `career_summary`.
 *  The `_source` tag (e.g. "claude:cv_enrichment:v2") lets the UI show an
 *  "AI" badge and helps support debug why a given record is missing fields. */
export interface CvExtractedData {
  years_it_experience?: number | null;
  current_position?: string | null;
  skills?: unknown[];
  education?: unknown[];
  languages?: unknown[];
  /** Phase D4: list of past employers, most recent first. */
  companies?: string[];
  /** Phase D4: 3-4 sentence career trajectory summary in Polish. */
  career_summary?: string | null;
  /** Identifier of the parse source — "regex", "ollama:...", "claude:...". */
  _source?: string;
  /** Set when a recruiter manually edited `candidate.experience`.
   *  Blocks AI from overwriting curated data on subsequent uploads. */
  _manual_override_experience?: boolean;
}

/** Single work-history entry. Mirrors backend `candidate.experience` JSONB
 *  shape: {company, role, start, end, desc}. */
export interface CandidateExperienceEntry {
  company?: string | null;
  role?: string | null;
  start?: string | null;
  end?: string | null;
  desc?: string | null;
}

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
  documents: (id: number) => api.get(`/api/contracts/${id}/documents`),
  uploadDocument: (id: number, formData: FormData) =>
    api.post(`/api/contracts/${id}/documents`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    }),
  deleteDocument: (contractId: number, documentId: number) =>
    api.delete(`/api/contracts/${contractId}/documents/${documentId}`),
  documentDownloadUrl: (contractId: number, documentId: number) =>
    `${API_BASE}/api/contracts/${contractId}/documents/${documentId}/download`,
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
  /** Phase 10: Champion screening layer — optional for backwards-compat. */
  champion_fit?: LayerPoints;
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

// ── Proposal snapshots (Phase 13) ───────────────────────────────────────────

export type ProposalStatus = "pending" | "ready" | "failed";
export type ProposalSource = "create" | "manual_regenerate" | "job_updated";

export interface ProposalCandidateItem {
  candidate: {
    id: number;
    name: string | null;
    lastname: string | null;
    email: string | null;
    phone?: string | null;
    location: string | null;
    avatar_url: string | null;
    competence_category: string | null;
    years_it_experience: number | null;
    salary_expectation: number | null;
    salary_currency: string | null;
    status: string | null;
    champion: boolean | null;
  };
  total_score: number;
  breakdown: ScoreBreakdown;
}

export interface ProposalSnapshot {
  id: number;
  job_id: number;
  status: ProposalStatus;
  source: ProposalSource;
  top_k: number;
  profile_id: number;
  created_at: string;
  error_message: string | null;
  candidates: ProposalCandidateItem[];
}

export interface ProposalSnapshotSummary {
  id: number;
  job_id: number;
  status: ProposalStatus;
  source: ProposalSource;
  top_k: number;
  created_at: string;
  candidate_count: number;
  error_message: string | null;
}

export const proposalsApi = {
  latest: (jobId: number) =>
    api.get<ProposalSnapshot>(`/api/jobs/${jobId}/proposals/latest`),
  list: (jobId: number, page = 1, pageSize = 10) =>
    api.get<{
      items: ProposalSnapshotSummary[];
      total: number;
      page: number;
      page_size: number;
    }>(`/api/jobs/${jobId}/proposals`, { params: { page, page_size: pageSize } }),
  regenerate: (jobId: number, topK = 20) =>
    api.post<ProposalSnapshot>(`/api/jobs/${jobId}/proposals/regenerate`, null, {
      params: { top_k: topK },
    }),
};

// ── Skill taxonomy (Phase B1) ───────────────────────────────────────────────

export interface SkillSuggestion {
  id: number;
  name: string;
  category: string | null;
}

export const skillsApi = {
  autocomplete: (q: string, limit = 20) =>
    api.get<{ items: SkillSuggestion[] }>("/api/skills/autocomplete", {
      params: { q, limit },
    }),
  list: (limit = 100) =>
    api.get<{
      items: Array<{ id: number; name: string; category: string | null; aliases: string[] }>;
      total: number;
    }>("/api/skills", { params: { limit } }),
};

// ── Scoring weight profiles (Phase D1) ──────────────────────────────────────

export interface ScoringWeights {
  semantic: number;
  skills: number;
  salary: number;
  location: number;
  availability: number;
}

export interface ScoringWeightProfile {
  id: number;
  name: string;
  user_id: number | null;
  client_id: number | null;
  weights: ScoringWeights;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ScoringWeightProfileCreate {
  name: string;
  user_id?: number | null;
  client_id?: number | null;
  weights: ScoringWeights;
  active?: boolean;
}

export const scoringWeightsApi = {
  list: () => api.get<ScoringWeightProfile[]>("/api/scoring-weights"),
  create: (payload: ScoringWeightProfileCreate) =>
    api.post<ScoringWeightProfile>("/api/scoring-weights", payload),
  update: (id: number, payload: ScoringWeightProfileCreate) =>
    api.patch<ScoringWeightProfile>(`/api/scoring-weights/${id}`, payload),
  remove: (id: number) => api.delete(`/api/scoring-weights/${id}`),
};

// ── Champion Profile (Phase 10) ─────────────────────────────────────────────

export interface ChampionBasics {
  onsite_days_per_week?: number | null;
  candidate_location_pref?: string | null;
  language?: string | null;
}

export interface ChampionProjectContext {
  about: string;
  responsibilities: string;
  selling_points: string;
}

export interface ScreeningQuestion {
  id: string;
  question: string;
  ideal_answer: string;
  deal_breaker: string;
}

export interface SourcingStrategy {
  sources: Array<"internal_base" | "linkedin" | "ad" | "referrals" | "other">;
  keywords: string;
  target_companies: string;
  notes: string;
}

export interface ChampionProfile {
  basics: ChampionBasics;
  project_context: ChampionProjectContext;
  screening_questions: ScreeningQuestion[];
  historical_client_questions: string;
  internal_consultant_insight: string;
  sourcing: SourcingStrategy;
}

export const EMPTY_CHAMPION_PROFILE: ChampionProfile = {
  basics: { onsite_days_per_week: null, candidate_location_pref: null, language: null },
  project_context: { about: "", responsibilities: "", selling_points: "" },
  screening_questions: [],
  historical_client_questions: "",
  internal_consultant_insight: "",
  sourcing: { sources: [], keywords: "", target_companies: "", notes: "" },
};

export interface ChampionProfileResponse {
  job_id: number;
  job_title?: string;
  champion_profile: ChampionProfile | Record<string, never>;
}

export const championApi = {
  get: (jobId: number) =>
    api.get<ChampionProfileResponse>(`/api/jobs/${jobId}/champion-profile`),
  put: (jobId: number, profile: ChampionProfile) =>
    api.put<ChampionProfileResponse>(`/api/jobs/${jobId}/champion-profile`, profile),
};

// ── Champion Profile AI Intake (Phase 14) ──────────────────────────────────

export type ChampionSuggestionSource =
  | "jd_paste"
  | "fireflies_meeting"
  | "cloudtalk_call"
  | "manual_consultant_note";

export type ChampionSuggestionStatus =
  | "pending"
  | "accepted"
  | "rejected"
  | "partially_accepted"
  | "superseded";

export type ChampionSectionName =
  | "basics"
  | "project_context"
  | "screening_questions"
  | "historical_client_questions"
  | "internal_consultant_insight"
  | "sourcing";

export const CHAMPION_SECTIONS: ChampionSectionName[] = [
  "basics",
  "project_context",
  "screening_questions",
  "historical_client_questions",
  "internal_consultant_insight",
  "sourcing",
];

export interface ChampionSectionPatch {
  section: ChampionSectionName;
  value: unknown;
  confidence: number;
  rationale: string;
}

export interface ChampionProfileSuggestion {
  id: number;
  job_id: number;
  source_type: ChampionSuggestionSource;
  source_ref: string | null;
  status: ChampionSuggestionStatus;
  created_by_id: number | null;
  reviewed_by_id: number | null;
  created_at: string;
  reviewed_at: string | null;
  model_name: string | null;
  prompt_version: number | null;
  error_message: string | null;
  patches: ChampionSectionPatch[];
}

export interface ChampionSuggestionListResponse {
  items: ChampionProfileSuggestion[];
  total: number;
}

export const championSuggestionsApi = {
  generateFromJd: (jobId: number, rawDescription: string) =>
    api.post<ChampionProfileSuggestion>(
      `/api/jobs/${jobId}/champion-profile/generate-from-jd`,
      { raw_description: rawDescription },
    ),
  list: (jobId: number, statusFilter?: ChampionSuggestionStatus) => {
    const qs = statusFilter ? `?status=${statusFilter}` : "";
    return api.get<ChampionSuggestionListResponse>(
      `/api/jobs/${jobId}/champion-profile/suggestions${qs}`,
    );
  },
  get: (suggestionId: number) =>
    api.get<ChampionProfileSuggestion>(`/api/champion-suggestions/${suggestionId}`),
  apply: (suggestionId: number, acceptedSections: ChampionSectionName[]) =>
    api.post<ChampionProfileSuggestion>(
      `/api/champion-suggestions/${suggestionId}/apply`,
      { accepted_sections: acceptedSections },
    ),
  reject: (suggestionId: number) =>
    api.post<ChampionProfileSuggestion>(
      `/api/champion-suggestions/${suggestionId}/reject`,
    ),
};

// Screening answers

export interface ScreeningAnswerItem {
  question_id: string;
  response: string;
  deal_breaker_hit: boolean;
}

export interface ScreeningAnswers {
  answers: ScreeningAnswerItem[];
  overall_fit: "fit" | "uncertain" | "miss";
  notes: string;
  answered_at?: string | null;
  answered_by?: number | null;
}

export interface StageScreeningResponse {
  stage_id: number;
  candidate_id: number;
  job_id: number;
  champion_profile: ChampionProfile | Record<string, never>;
  screening_answers: ScreeningAnswers | null;
}

export const screeningApi = {
  getForStage: (stageId: number) =>
    api.get<StageScreeningResponse>(`/api/pipeline/stages/${stageId}/screening`),
  submit: (stageId: number, answers: ScreeningAnswers) =>
    api.post<{
      stage_id: number;
      match_percent: number;
      screening_answers: ScreeningAnswers;
    }>(`/api/pipeline/stages/${stageId}/screening`, answers),
  // Phase 12 — client-shareable token for the Champion card.
  createShareToken: (stageId: number, expiresInDays = 30) =>
    api.post<{
      token: string;
      expires_at: string;
      share_url_suffix: string;
    }>(`/api/pipeline/stages/${stageId}/share-token?expires_in_days=${expiresInDays}`),
  revokeShareToken: (token: string) =>
    api.delete(`/api/pipeline/stages/share-token/${token}`),
};

// ── Saved searches (used by the candidates list filter toolbar) ──────────────

export interface SavedSearch {
  id: number;
  user_id: number;
  name: string;
  entity: string;
  filters: { qs?: string; [k: string]: unknown };
  shared: boolean;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export default api;
