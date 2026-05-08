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

// ── Auth ─────────────────────────────────────────────────────────────────────
export const authApi = {
  /** Self-service password change for the logged-in user. */
  changePassword: (current_password: string, new_password: string) =>
    api.post("/api/auth/change-password", { current_password, new_password }),
  /** Request a password reset link by email. Always returns 200 with a generic
   *  message regardless of whether the email exists (anti-enumeration). */
  forgotPassword: (email: string) =>
    api.post("/api/auth/forgot-password", { email }),
  /** Set new password using a token from the reset email. */
  resetPasswordWithToken: (token: string, new_password: string) =>
    api.post("/api/auth/reset-password", { token, new_password }),
};

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
  /** Send a password reset link to the user's email instead of setting one
   *  manually. User chooses their own password via the link (TTL 60 min). */
  sendResetLink: (id: number) =>
    api.post(`/api/admin/users/${id}/send-reset-link`),
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
  inviteLinks: (params: { period?: string }) =>
    api.get("/api/reports/invite-links", { params }),
};

// ── Prep Kit ──────────────────────────────────────────────────────────────────

export interface PrepKitResponse {
  client_overview: string;
  likely_questions: string[];
  likely_questions_meta: Array<{
    text: string;
    source_tier: string;
    question_id: number | null;
    source_job_id: number | null;
    ideal_answer: string | null;
    deal_breaker: boolean;
    seniority: string | null;
    question_type: string | null;
    skill_tags: string[];
    cosine_score: number | null;
  }>;
  candidate_strengths: string[];
  candidate_gaps: string[];
  selling_points: string[];
  recommended_strategy: string;
}

export const prepKitApi = {
  generate: (job_id: number, candidate_id: number) =>
    api.post<PrepKitResponse>("/api/prep-kit/generate", { job_id, candidate_id }),
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

// ── Competence Categories (5 CC) ──────────────────────────────────────────────
export interface CompetenceCategoryOut {
  id: number;
  slug: string;
  name_pl: string;
  name_en: string;
  description: string;
  keywords: string[];
  display_order: number;
}

export const competenceCategoriesApi = {
  list: (activeOnly = true) =>
    api
      .get<CompetenceCategoryOut[]>("/api/competence-categories", {
        params: { active_only: activeOnly },
      })
      .then((r) => r.data),
};

// ── Targ kandydatów (Candidate Marketplace) ───────────────────────────────────

export interface MarketplaceOwner {
  id: number;
  name: string;
  email: string;
}

export interface MarketplaceCandidate {
  id: number;
  name: string;
  lastname: string;
  email?: string | null;
  avatar_url?: string | null;
  location?: string | null;
  competence_category?: string | null;
  availability_status: string;
  skills?: unknown[] | null;
  added_at: string;
  marketplace_until?: string | null;
  source_event?: string | null;
  owner?: MarketplaceOwner | null;
}

export interface MarketplaceListResponse {
  items: MarketplaceCandidate[];
  total: number;
  page: number;
  page_size: number;
}

export interface MarketplaceMatch {
  job_id: number;
  title: string;
  client_id?: number | null;
  total_score: number;
  seniority?: string | null;
  matching_must: string[];
  gap_must: string[];
}

export interface MarketplaceMatchesResponse {
  candidate_id: number;
  computed_at: string;
  matches: MarketplaceMatch[];
}

export interface MarketplacePoolMeta {
  id: number;
  name: string;
  description?: string | null;
  candidate_count: number;
  is_marketplace: boolean;
  created_at: string;
}

export const marketplaceApi = {
  getPool: () => api.get<MarketplacePoolMeta>("/api/marketplace/pool"),
  list: (params?: { page?: number; page_size?: number; q?: string }) =>
    api.get<MarketplaceListResponse>("/api/marketplace/candidates", { params }),
  add: (candidateId: number, body: { marketplace_until?: string } = {}) =>
    api.post(`/api/marketplace/candidates/${candidateId}/add`, body),
  remove: (candidateId: number) =>
    api.delete(`/api/marketplace/candidates/${candidateId}`),
  matches: (candidateId: number) =>
    api.get<MarketplaceMatchesResponse>(
      `/api/marketplace/candidates/${candidateId}/matches`
    ),
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

// ── Interview Feedback ────────────────────────────────────────────────────────
export const interviewFeedbackApi = {
  list: (params?: {
    calendar_event_id?: number;
    candidate_id?: number;
    job_id?: number;
  }) => api.get("/api/interview-feedback", { params }),
  get: (id: number) => api.get(`/api/interview-feedback/${id}`),
  create: (data: Record<string, unknown>) =>
    api.post("/api/interview-feedback", data),
  update: (id: number, data: Record<string, unknown>) =>
    api.patch(`/api/interview-feedback/${id}`, data),
  delete: (id: number) => api.delete(`/api/interview-feedback/${id}`),
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
export interface ContractTerminateRequest {
  termination_reason: ContractTerminationReason;
  termination_lessons?: string | null;
  terminated_at?: string | null;
}

export type ContractTerminationReason =
  | "poached_by_client"
  | "project_ended"
  | "client_budget_cut"
  | "performance_issue"
  | "consultant_resigned"
  | "better_offer"
  | "personal_reasons"
  | "contract_breach"
  | "mutual_agreement"
  | "other";

export const CONTRACT_TERMINATION_REASONS: {
  value: ContractTerminationReason;
  label: string;
}[] = [
  { value: "project_ended", label: "Koniec projektu" },
  { value: "poached_by_client", label: "Przejście do klienta" },
  { value: "client_budget_cut", label: "Cięcie budżetu klienta" },
  { value: "consultant_resigned", label: "Konsultant zrezygnował" },
  { value: "better_offer", label: "Dostał lepszą ofertę" },
  { value: "performance_issue", label: "Problem jakościowy" },
  { value: "contract_breach", label: "Naruszenie umowy" },
  { value: "personal_reasons", label: "Powody osobiste" },
  { value: "mutual_agreement", label: "Porozumienie stron" },
  { value: "other", label: "Inny" },
];

export type EquipmentItemType =
  | "laptop"
  | "phone"
  | "monitor"
  | "headset"
  | "docking_station"
  | "security_token"
  | "keycard"
  | "sim_card"
  | "other";
export type EquipmentOwner = "ours" | "client";
export type EquipmentReturnStatus =
  | "pending"
  | "returned"
  | "lost"
  | "written_off";

export interface ContractEquipmentItem {
  id: number;
  contract_id: number;
  item_type: EquipmentItemType;
  owner: EquipmentOwner;
  brand_model: string | null;
  serial_number: string | null;
  description: string | null;
  deposit_amount: number | null;
  deposit_currency: string | null;
  handed_over_date: string | null;
  return_due_date: string | null;
  returned_date: string | null;
  return_status: EquipmentReturnStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContractBenchmarkComparison {
  contract_rate_monthly: number | null;
  internal_avg_monthly: number | null;
  internal_median_monthly: number | null;
  internal_sample_size: number;
  market_min: number | null;
  market_median: number | null;
  market_max: number | null;
  market_source: string | null;
  market_source_date: string | null;
  role_used: string | null;
  currency: string;
}

export interface ContractTimelineItem {
  id: number;
  kind: "note" | "call";
  at: string;
  summary: string | null;
  content: string | null;
  sub_type: string | null;
  status: string | null;
  author_id: number | null;
  author_name: string | null;
  duration_seconds: number | null;
}

export interface ContractTemplateBrief {
  id: number;
  name: string;
  contract_type: string;
  is_default: boolean;
}

export interface ContractDraftResponse {
  contract_id: number;
  content_html: string | null;
  template_id: number | null;
  updated_at: string | null;
  updated_by: number | null;
  updated_by_name: string | null;
  available_templates: ContractTemplateBrief[];
  rendered_from_default: boolean;
}

export interface ContractDraftFinalizeResponse {
  contract_id: number;
  status: "draft" | "active" | "ending" | "ended";
  document_id: number | null;
  document_filename: string | null;
}

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
  terminate: (id: number, payload: ContractTerminateRequest) =>
    api.post(`/api/contracts/${id}/terminate`, payload),
  activate: (id: number) => api.post(`/api/contracts/${id}/activate`, {}),
  benchmark: (id: number) =>
    api.get<ContractBenchmarkComparison>(`/api/contracts/${id}/benchmark`),
  notesTimeline: (id: number) =>
    api.get<ContractTimelineItem[]>(`/api/contracts/${id}/notes`),
  // Editable draft (migracja 0058)
  draft: {
    get: (id: number) =>
      api.get<ContractDraftResponse>(`/api/contracts/${id}/draft`),
    update: (
      id: number,
      payload: { template_id?: number; content_html?: string },
    ) =>
      api.patch<ContractDraftResponse>(`/api/contracts/${id}/draft`, payload),
    finalize: (id: number) =>
      api.post<ContractDraftFinalizeResponse>(
        `/api/contracts/${id}/draft/finalize`,
      ),
    printableUrl: (id: number) =>
      `${API_BASE}/api/contracts/${id}/draft/render-pdf`,
  },
  byCandidate: (candidateId: number) =>
    api.get(`/api/contracts`, {
      params: { candidate_id: candidateId, page_size: 100 },
    }),
};

// ── Autenti e-signature integration ─────────────────────────────────────────
// Plan: ~/.claude/plans/zaplanuj-wszystko-zgodnie-z-tranquil-torvalds.md
// Backend mounts /api/autenti/* only when AUTENTI_ENABLED=true; the FE feature
// is gated by the same flag (sourced from a future /api/health/features
// endpoint or an env-injected build flag — Phase 2 just hides the button when
// the request returns 404 / 503).

export type AutentiSignatureType ="SES" | "AdES" | "QES";

export type SignatureStatus =
  |"draft"
  |"sending"
  |"sent"
  |"in_progress"
  |"completed"
  |"rejected"
  |"withdrawn"
  |"failed"
  |"expired";

export interface DocumentSignatureEvent {
  id: number;
  event_id: string;
  event_type: string;
  status: string | null;
  received_at: string;
  processed_at: string | null;
}

export interface DocumentSignature {
  id: number;
  contract_id: number;
  contract_document_id: number;
  autenti_process_id: string | null;
  autenti_signature_type: AutentiSignatureType;
  status: SignatureStatus;
  sent_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  sender_user_id: number;
  signer_email: string;
  signer_first_name: string;
  signer_last_name: string;
  signer_phone: string | null;
  signed_document_id: number | null;
  signed_document_url: string | null;
  last_error: string | null;
  retry_count: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentSignatureDetail extends DocumentSignature {
  events: DocumentSignatureEvent[];
}

export interface AutentiSendRequest {
  signature_type: AutentiSignatureType;
  expires_in_days?: number;
  message_pl?: string | null;
  return_url?: string | null;
}

export interface AutentiSendResponse {
  signature_id: number;
  contract_id: number;
  status: SignatureStatus;
}

export const autentiApi = {
  send: (contractId: number, payload: AutentiSendRequest) =>
    api.post<AutentiSendResponse>(
      `/api/autenti/contracts/${contractId}/send`,
      payload,
    ),
  list: (contractId: number) =>
    api.get<DocumentSignature[]>(
      `/api/autenti/contracts/${contractId}/signatures`,
    ),
  get: (signatureId: number) =>
    api.get<DocumentSignatureDetail>(
      `/api/autenti/signatures/${signatureId}`,
    ),
  withdraw: (signatureId: number) =>
    api.post<DocumentSignature>(
      `/api/autenti/signatures/${signatureId}/withdraw`,
    ),
  remind: (signatureId: number) =>
    api.post<DocumentSignature>(
      `/api/autenti/signatures/${signatureId}/remind`,
    ),
};

// ── Contractors (Delivery module) ───────────────────────────────────────────

export type ContractorStatus = "draft" | "active" | "ending";

export interface ContractorCandidateRef {
  id: number;
  name: string;
  lastname: string;
  email?: string | null;
}

export interface ContractorListItem {
  contract_id: number;
  candidate: ContractorCandidateRef;
  client_name?: string | null;
  job_title?: string | null;
  status: ContractorStatus;
  start_date: string;
  end_date?: string | null;
  rate_candidate?: number | null;
  rate_client?: number | null;
  rate_unit: "hourly" | "daily" | "monthly";
  margin?: number | null;
  contract_type: "b2b" | "uop" | "uzlecenie";
  work_mode?: "remote" | "hybrid" | "onsite" | null;
  missing_fields: string[];
}

export interface ContractorList {
  items: ContractorListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ContractorStats {
  draft: number;
  drafts_incomplete: number;
  active: number;
  ending: number;
}

export const contractorsApi = {
  list: (params?: {
    status?: ContractorStatus;
    page?: number;
    page_size?: number;
  }) => api.get<ContractorList>("/api/contractors", { params }),
  stats: () => api.get<ContractorStats>("/api/contractors/stats"),
};

export const contractEquipmentApi = {
  list: (contractId: number) =>
    api.get<ContractEquipmentItem[]>(`/api/contracts/${contractId}/equipment`),
  create: (contractId: number, data: Partial<ContractEquipmentItem>) =>
    api.post<ContractEquipmentItem>(
      `/api/contracts/${contractId}/equipment`,
      data,
    ),
  update: (
    contractId: number,
    equipmentId: number,
    data: Partial<ContractEquipmentItem>,
  ) =>
    api.patch<ContractEquipmentItem>(
      `/api/contracts/${contractId}/equipment/${equipmentId}`,
      data,
    ),
  delete: (contractId: number, equipmentId: number) =>
    api.delete(`/api/contracts/${contractId}/equipment/${equipmentId}`),
};

// ── Candidate engagement + location ─────────────────────────────────────────
export interface CandidateEngagementPayload {
  is_ambassador?: boolean;
  wants_to_verify_candidates?: boolean;
  open_to_side_projects?: boolean;
  open_to_sales_support?: boolean;
  open_to_expert_consult?: boolean;
  engagement_notes?: string | null;
}

export interface CandidateLocationPayload {
  city?: string | null;
  country?: string | null;
  region?: string | null;
  hub_city?: string | null;
  latitude?: number | null;
  longitude?: number | null;
}

export const candidateProfileApi = {
  updateEngagement: (candidateId: number, data: CandidateEngagementPayload) =>
    api.patch(`/api/candidates/${candidateId}/engagement`, data),
  updateLocation: (candidateId: number, data: CandidateLocationPayload) =>
    api.patch(`/api/candidates/${candidateId}/location`, data),
};

// ── Rate benchmarks ─────────────────────────────────────────────────────────
export type SeniorityLevel =
  | "junior"
  | "mid"
  | "senior"
  | "expert"
  | "principal";

export interface RateBenchmarkRow {
  id: number;
  role: string;
  seniority: SeniorityLevel | null;
  currency: string;
  rate_unit: "hourly" | "daily" | "monthly";
  market_min: number | null;
  market_median: number;
  market_max: number | null;
  source: string;
  source_date: string;
  location: string | null;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface RateBenchmarkImportResult {
  created: number;
  skipped: number;
  errors: string[];
}

export const rateBenchmarksApi = {
  list: (params?: Record<string, unknown>) =>
    api.get<RateBenchmarkRow[]>("/api/rate-benchmarks", { params }),
  create: (data: Partial<RateBenchmarkRow>) =>
    api.post<RateBenchmarkRow>("/api/rate-benchmarks", data),
  update: (id: number, data: Partial<RateBenchmarkRow>) =>
    api.patch<RateBenchmarkRow>(`/api/rate-benchmarks/${id}`, data),
  delete: (id: number) => api.delete(`/api/rate-benchmarks/${id}`),
  importCsv: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return api.post<RateBenchmarkImportResult>(
      "/api/rate-benchmarks/import",
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
  },
};

// ── Contract analytics expansion ────────────────────────────────────────────
export interface RoleClientCell {
  role: string;
  client_id: number;
  client_name: string;
  active_count: number;
  pct_of_total: number;
}

export interface RoleClientMix {
  total_active: number;
  rows: RoleClientCell[];
  roles: string[];
  clients: { id: number; name: string }[];
}

export interface HubDistribution {
  hub_city: string | null;
  count: number;
}

export interface RegionDistribution {
  region: string | null;
  count: number;
}

export interface LocationDistribution {
  total: number;
  total_with_hub: number;
  hubs: HubDistribution[];
  regions: RegionDistribution[];
}

export interface TerminationReasonBucket {
  reason: string;
  count: number;
  avg_contract_days: number | null;
}

export interface ClientRetention {
  client_id: number;
  client_name: string;
  total_ended: number;
  kept_to_end: number;
  ended_early: number;
  retention_pct: number;
}

export interface TerminationAnalysis {
  window_months: number;
  total_terminated: number;
  by_reason: TerminationReasonBucket[];
  client_retention: ClientRetention[];
}

export const contractAnalyticsExpansionApi = {
  roleClientMix: () =>
    api.get<RoleClientMix>("/api/contract-analytics/role-client-mix"),
  locationDistribution: (activeOnly = true) =>
    api.get<LocationDistribution>(
      "/api/contract-analytics/location-distribution",
      { params: { active_only: activeOnly } },
    ),
  terminationAnalysis: (windowMonths = 12) =>
    api.get<TerminationAnalysis>(
      "/api/contract-analytics/termination-analysis",
      { params: { window_months: windowMonths } },
    ),
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

export type RateUnit = "hourly" | "daily" | "monthly";
export type VerificationStatus = "active" | "pending" | "rejected";

export interface PendingVerificationItem {
  candidate_stage_id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  expected_rate_value: string | null;
  expected_rate_unit: RateUnit | null;
  expected_rate_currency: string | null;
  budget_max_at_move: number | null;
  moved_at: string;
  moved_by: number | null;
  moved_by_name: string | null;
  notes: string | null;
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
    expected_rate_value?: number | string;
    expected_rate_unit?: RateUnit;
    expected_rate_currency?: string;
  }) => api.post("/api/pipeline/move", data),
  listPendingVerifications: (jobId?: number) =>
    api.get<PendingVerificationItem[]>("/api/pipeline/pending-verifications", {
      params: jobId !== undefined ? { job_id: jobId } : undefined,
    }),
  acceptVerification: (candidateStageId: number) =>
    api.post(`/api/pipeline/${candidateStageId}/accept-verification`),
  rejectVerification: (candidateStageId: number, note: string) =>
    api.post(`/api/pipeline/${candidateStageId}/reject-verification`, { note }),
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
  // Pending verification (migracja 0056)
  verification_status?: VerificationStatus;
  expected_rate_value?: string | null;
  expected_rate_unit?: RateUnit | null;
  expected_rate_currency?: string | null;
  budget_max_at_move?: number | null;
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

// ── Historical candidates (Phase 14 — from similar past jobs) ──────────────

export type HistoricalTier = "A" | "B";
export type HistoricalTierUsed = "primary" | "extended" | "empty";
export type HistoricalAvailability = "available" | "busy" | "unknown";

export interface HistoricalSource {
  job_id: number;
  job_title: string;
  stage: string;
  similarity: number;
  months_ago: number;
  moved_at: string;
  stage_weight: number;
  contribution: number;
}

export interface HistoricalCandidate {
  candidate_id: number;
  name: string;
  lastname: string;
  avatar_url: string | null;
  competence_category: string | null;
  historical_score: number;
  tier: HistoricalTier;
  negative_signal: boolean;
  recommended_count: number;
  sources: HistoricalSource[];
  current_availability: HistoricalAvailability;
  current_status: string | null;
}

export interface HistoricalSimilarJob {
  job_id: number;
  title: string;
  similarity: number;
  tier: HistoricalTier;
}

export interface CandidatesFromSimilarResponse {
  job_id: number;
  tier_used: HistoricalTierUsed;
  similar_jobs: HistoricalSimilarJob[];
  candidates: HistoricalCandidate[];
  meta: {
    tier_a_count: number;
    tier_b_count: number;
    total_sources: number;
    reason_if_empty: string | null;
  };
}

export const historicalCandidatesApi = {
  forJob: (
    jobId: number,
    opts?: {
      tier?: "primary" | "extended" | "all";
      limit?: number;
      include_negative?: boolean;
    },
  ) =>
    api.get<CandidatesFromSimilarResponse>(
      `/api/jobs/${jobId}/candidates-from-similar`,
      { params: opts },
    ),
};

// ── Request history (Historia requestu) ────────────────────────────────────

export type RequestHistoryOutcome = "filled" | "cancelled";
export type RequestHistorySimilaritySource = "sql_same_client" | "voyage";

export interface RequestHistoryEntry {
  job_id: number;
  title: string;
  train_name: string | null;
  same_train: boolean;
  seniority: string | null;
  status: string;
  is_in_progress: boolean;
  outcome: RequestHistoryOutcome | null;
  close_reason: string | null;
  similarity: number;
  similarity_source: RequestHistorySimilaritySource;
  closed_at: string | null;
  created_at: string;
  tth_days: number | null;
  client_id: number | null;
  client_name: string | null;
  champion_name: string | null;
  champion_candidate_id: number | null;
  champions_count: number;
  candidates_count: number;
  fee_rate: number | null;
  fee_currency: string | null;
  rate_unit: string | null;
  tac_name: string | null;
  delivery_lead_name: string | null;
}

export interface RequestHistoryMeta {
  sql_count: number;
  voyage_count: number;
  total: number;
  skill_freq_sample: number;
}

export interface RequestHistoryResponse {
  closed: RequestHistoryEntry[];
  in_progress: RequestHistoryEntry[];
  skill_frequency: Record<string, unknown>;
  meta: RequestHistoryMeta;
}

export interface RequestHistoryPreviewBody {
  title: string;
  client_id?: number | null;
  raw_description?: string | null;
  train_name?: string | null;
  top_k?: number;
  cross_client?: boolean;
  include_open?: boolean;
}

export const requestHistoryApi = {
  forJob: (
    jobId: number,
    opts?: { cross_client?: boolean; top_k?: number; include_open?: boolean },
  ) =>
    api.get<RequestHistoryResponse>(`/api/jobs/${jobId}/request-history`, {
      params: opts,
    }),
  preview: (body: RequestHistoryPreviewBody) =>
    api.post<RequestHistoryResponse>(
      "/api/jobs/request-history/preview",
      body,
    ),
  addCandidate: (
    jobId: number,
    body: { candidate_id: number; source_job_id?: number | null },
  ) =>
    api.post<{
      candidate_stage_id: number;
      job_id: number;
      candidate_id: number;
      stage: string;
      source_job_id: number | null;
    }>(`/api/jobs/${jobId}/candidates`, body),
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
  seekingContractors: (params?: SeekingContractorsParams) =>
    api.get<SeekingContractorsResponse>(
      "/api/recommendations/seeking-contractors",
      { params },
    ),
  sendCandidateShortlistEmail: (payload: { candidate_id: number; job_ids: number[] }) =>
    api.post<ShortlistEmailDraftResponse>(
      "/api/recommendations/send-candidate-shortlist-email",
      payload,
    ),
  prepareClientProposal: (payload: { candidate_id: number; job_id: number }) =>
    api.post<ClientProposalResponse>(
      "/api/recommendations/prepare-client-proposal",
      payload,
    ),
  cvUploadPreview: (file: File, params?: CvUploadPreviewParams) => {
    const fd = new FormData();
    fd.append("file", file);
    if (params?.location) fd.append("location", params.location);
    if (params?.salary_min !== undefined && params.salary_min !== null) {
      fd.append("salary_min", String(params.salary_min));
    }
    if (params?.salary_max !== undefined && params.salary_max !== null) {
      fd.append("salary_max", String(params.salary_max));
    }
    if (params?.competence_category) {
      fd.append("competence_category", params.competence_category);
    }
    return api.post<CvUploadPreviewResponse>(
      "/api/recommendations/cv-upload-preview",
      fd,
      {
        params: {
          top_k: params?.top_k,
          threshold: params?.threshold,
        },
      },
    );
  },
};

export interface SeekingContractorsParams {
  horizon_days?: number;
  top_k?: number;
  threshold?: number;
  location?: string;
  salary_min?: number;
  salary_max?: number;
  /**
   * One or more competence categories — backend OR-combines them.
   * Sent as repeated `competence_category=X&competence_category=Y` query
   * params via axios's array serializer.
   */
  competence_category?: string[];
  industry_blocklist?: boolean;
  page_size?: number;
}

export interface SeekingContractorRow {
  candidate: {
    id: number;
    name: string;
    lastname: string;
    email: string | null;
    location: string | null;
    competence_category: string | null;
    years_it_experience: number | null;
    salary_expectation: number | null;
    salary_currency: string | null;
    availability_status: string | null;
    champion: boolean;
    avatar_url: string | null;
  };
  source: "ending_contract" | "availability_status";
  contract_end_date: string | null;
  current_client_id: number | null;
  top_matches: Array<{
    job: JobMatch["job"];
    total_score: number;
    breakdown?: ScoreBreakdown;
    warning: string | null;
  }>;
  below_threshold_count: number;
}

export interface SeekingContractorsResponse {
  horizon_days: number;
  total: number;
  items: SeekingContractorRow[];
}

export interface ShortlistEmailDraftResponse {
  candidate_id: number;
  to: string;
  subject: string;
  text_body: string;
  html_body: string;
  job_count: number;
}

export interface ClientProposalResponse {
  candidate_id: number;
  job_id: number;
  client_id: number | null;
  blind_summary: {
    skills_summary: string[];
    experience_years: number;
    education_level: string;
    languages: string[];
    ai_summary: string | null;
    competence_category: string | null;
  };
  draft_email: {
    subject: string;
    text_body: string;
    html_body: string;
  };
}

export interface CvUploadPreviewParams {
  top_k?: number;
  threshold?: number;
  location?: string;
  salary_min?: number;
  salary_max?: number;
  competence_category?: string;
}

export interface CvUploadPreviewResponse {
  parsed_summary: {
    first_name: string | null;
    last_name: string | null;
    email: string | null;
    phone: string | null;
    city: string | null;
    current_position: string | null;
    years_it_experience: number | null;
    skills: Array<{ name?: string; level?: string | null; years?: number | null }>;
    languages: Array<{ name?: string; level?: string | null }>;
    linkedin_url: string | null;
    source: string | null;
  };
  matches: Array<{
    job: JobMatch["job"];
    total_score: number;
    breakdown?: ScoreBreakdown;
    warning: string | null;
  }>;
  search_type: "semantic" | "fallback";
}

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
  | "manual_consultant_note"
  | "historical_jobs";

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
  /** Phase 15 / Phase C: DL feedback, -1|0|1 or null when not yet rated. */
  rating: number | null;
  /** Optional free-text comment attached to the rating. */
  rating_comment: string | null;
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
  // Phase 15: generate draft from top-K similar closed jobs of the same
  // client (or any client when crossClient=true). Emits the same
  // ChampionProfileSuggestion shape as generateFromJd so the existing review
  // modal works without changes.
  generateFromHistory: (
    jobId: number,
    opts: { topK?: number; crossClient?: boolean; rawDescription?: string } = {},
  ) =>
    api.post<ChampionProfileSuggestion>(
      `/api/jobs/${jobId}/champion-profile/generate-from-history`,
      {
        top_k: opts.topK ?? 5,
        cross_client: opts.crossClient ?? false,
        raw_description: opts.rawDescription,
      },
    ),
  // Preview (no LLM): list up to top_k similar closed roles with a populated
  // champion_profile + aggregated skill frequencies. Powers "podobne role z
  // przeszłości" cards before the DL commits to an LLM round-trip.
  fetchHistoricalMatches: (
    jobId: number,
    params: { topK?: number; crossClient?: boolean } = {},
  ) =>
    api.get<HistoricalMatchesResponse>(
      `/api/jobs/${jobId}/champion-profile/historical-matches`,
      {
        params: {
          top_k: params.topK ?? 5,
          cross_client: params.crossClient ?? false,
        },
      },
    ),
  // Same preview but for a job that does NOT exist yet (new-role wizard).
  // Takes title + client_id + free-text description straight from the form.
  previewHistoricalMatchesUnsaved: (payload: {
    title: string;
    client_id?: number | null;
    raw_description?: string | null;
    train_name?: string | null;
    top_k?: number;
    cross_client?: boolean;
  }) =>
    api.post<HistoricalMatchesResponse>(
      `/api/jobs/champion-profile/historical-matches`,
      {
        title: payload.title,
        client_id: payload.client_id ?? null,
        raw_description: payload.raw_description ?? null,
        train_name: payload.train_name ?? null,
        top_k: payload.top_k ?? 5,
        cross_client: payload.cross_client ?? false,
      },
    ),
  // Phase 15 / Phase C — persist DL feedback on a terminated suggestion.
  // Rating: -1 (bezużyteczne) | 0 (nijak) | 1 (trafione). Comment optional.
  rate: (suggestionId: number, rating: -1 | 0 | 1, comment?: string) =>
    api.post<ChampionProfileSuggestion>(
      `/api/champion-suggestions/${suggestionId}/rate`,
      { rating, comment: comment ?? null },
    ),
};

// ── Champion Profile: Historical matches preview (Phase 15) ─────────────────

export interface HistoricalMatchPreview {
  job_id: number;
  title: string;
  similarity: number;
  closed_at: string | null;
  client_id: number | null;
  client_name: string | null;
  seniority: string | null;
  /** Phase 15 / Phase D: programme tag of the historical role (not the
   *  current role). `null` when the closed job was never tagged. */
  train_name: string | null;
  same_train: boolean;
  has_champion_profile: boolean;
  must_skills_count: number;
  nice_skills_count: number;
}

export interface SkillFrequencyEntry {
  name: string;
  count: number;
  fraction: number;
}

export interface HistoricalSkillFrequency {
  n: number;
  must: SkillFrequencyEntry[];
  nice: SkillFrequencyEntry[];
  consistent_must: string[];
  consistent_nice: string[];
  threshold: number;
}

export interface HistoricalMatchesResponse {
  matches: HistoricalMatchPreview[];
  skill_frequency: HistoricalSkillFrequency;
}

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

// ── Microsoft 365 integration (Phase M365.1) ─────────────────────────────────

export interface M365ConnectionStatus {
  connected: boolean;
  mailbox_upn?: string | null;
  last_sync_at?: string | null;
  synced_through?: string | null;
  last_sync_status?: string | null;
  last_error?: string | null;
  backfill_in_progress?: boolean;
  max_attachment_mb?: number;
}

export interface EmailAttachmentPreview {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  is_inline: boolean;
}

export interface EmailMessage {
  id: number;
  m365_message_id: string;
  m365_conversation_id: string;
  subject: string | null;
  from_address: string;
  from_name: string | null;
  to_addresses: Array<{ address: string; name?: string | null }>;
  cc_addresses: Array<{ address: string; name?: string | null }>;
  body_html: string | null;
  body_text: string | null;
  body_preview: string | null;
  sent_at: string | null;
  received_at: string;
  direction: "sent" | "received" | "draft";
  has_attachments: boolean;
  is_read: boolean;
  is_private_filtered: boolean;
  match_method:
    | "strict"
    | "smart_domain"
    | "smart_thread"
    | "smart_name"
    | "manual"
    | "unmatched";
  match_confidence: number | null;
  attachments?: EmailAttachmentPreview[];
}

export interface EmailThreadPreview {
  conversation_id: string;
  subject: string | null;
  latest: EmailMessage;
  message_count: number;
  unread_count: number;
}

export const microsoft365Api = {
  getConnection: () =>
    api.get<M365ConnectionStatus>("/api/microsoft365/connection"),
  getAuthorizeUrl: () =>
    api.get<{ authorize_url: string }>("/api/microsoft365/authorize"),
  disconnect: () => api.delete("/api/microsoft365/connection"),
  triggerSync: () => api.post("/api/microsoft365/sync/trigger"),

  listCandidateThreads: (candidateId: number) =>
    api.get<EmailThreadPreview[]>(`/api/candidates/${candidateId}/emails`),
  getEmail: (emailId: number) =>
    api.get<EmailMessage>(`/api/emails/${emailId}`),
  compose: (
    candidateId: number,
    payload: { to: string[]; cc?: string[]; subject: string; body_html: string },
  ) =>
    api.post<EmailMessage>(
      `/api/candidates/${candidateId}/emails/compose`,
      payload,
    ),
  reply: (
    candidateId: number,
    payload: { email_id: number; body_html: string },
  ) =>
    api.post<EmailMessage>(
      `/api/candidates/${candidateId}/emails/reply`,
      payload,
    ),
  downloadAttachmentUrl: (emailId: number, attachmentId: number) =>
    `${API_BASE}/api/emails/${emailId}/attachments/${attachmentId}/download`,
  createInvite: (payload: {
    candidate_id: number;
    title: string;
    description?: string;
    start: string;
    end: string;
    event_type?: string;
    extra_attendees?: string[];
    invite_candidate?: boolean;
  }) => api.post("/api/calendar/events/m365-invite", payload),
};

// ── Interview Questions (feature "Prepy") ───────────────────────────────────

export type InterviewQuestionSource =
  | "manual"
  | "auto_generated"
  | "imported_from_champion";

export type InterviewQuestionTypeLiteral =
  | "technical"
  | "behavioral"
  | "motivation"
  | "experience";

export type InterviewQuestionSeniority =
  | "junior"
  | "mid"
  | "senior"
  | "lead"
  | "architect";

export type JobQuestionAddedBySource =
  | "manual"
  | "auto_from_similar"
  | "auto_generated";

export type QuestionRating = "up" | "down";

export type SuggestionTier =
  | "pinned"
  | "legacy_champion"
  | "tier_1_same_cc"
  | "tier_2_secondary_cc"
  | "tier_3_client_knowledge"
  | "tier_4_auto_generated";

export interface InterviewQuestion {
  id: number;
  text: string;
  ideal_answer: string | null;
  deal_breaker: boolean;
  competence_category_id: number | null;
  skill_tags: string[];
  seniority: InterviewQuestionSeniority | null;
  question_type: InterviewQuestionTypeLiteral | null;
  source: InterviewQuestionSource;
  client_id: number | null;
  created_by: number | null;
  up_votes: number;
  down_votes: number;
}

export interface JobQuestionLink {
  id: number;
  question: InterviewQuestion;
  is_pinned: boolean;
  added_by_source: JobQuestionAddedBySource;
  order_index: number;
}

export interface SuggestedQuestion {
  text: string;
  source_tier: SuggestionTier;
  question_id: number | null;
  source_job_id: number | null;
  ideal_answer: string | null;
  deal_breaker: boolean;
  seniority: InterviewQuestionSeniority | null;
  question_type: InterviewQuestionTypeLiteral | null;
  skill_tags: string[];
  cosine_score: number | null;
}

export interface CreateInterviewQuestionPayload {
  text: string;
  ideal_answer?: string | null;
  deal_breaker?: boolean;
  competence_category_id?: number | null;
  skill_tags?: string[];
  seniority?: InterviewQuestionSeniority | null;
  question_type?: InterviewQuestionTypeLiteral | null;
  client_id?: number | null;
  job_id?: number | null;
}

export interface ListInterviewQuestionsParams {
  cc_id?: number;
  skill_tag?: string;
  seniority?: InterviewQuestionSeniority;
  question_type?: InterviewQuestionTypeLiteral;
  client_id?: number;
  q?: string;
  limit?: number;
}

export const interviewQuestionsApi = {
  create: (payload: CreateInterviewQuestionPayload) =>
    api.post<InterviewQuestion>("/api/interview-questions", payload),

  list: (params?: ListInterviewQuestionsParams) =>
    api.get<InterviewQuestion[]>("/api/interview-questions", { params }),

  get: (id: number) =>
    api.get<InterviewQuestion>(`/api/interview-questions/${id}`),

  update: (id: number, payload: Partial<CreateInterviewQuestionPayload>) =>
    api.put<InterviewQuestion>(`/api/interview-questions/${id}`, payload),

  delete: (id: number) => api.delete(`/api/interview-questions/${id}`),

  rate: (
    id: number,
    payload: {
      rating: QuestionRating;
      job_id?: number;
      candidate_id?: number;
      notes?: string;
    },
  ) =>
    api.post<{ id: number; up_votes: number; down_votes: number }>(
      `/api/interview-questions/${id}/rate`,
      payload,
    ),

  listForJob: (jobId: number) =>
    api.get<JobQuestionLink[]>(`/api/jobs/${jobId}/questions`),

  pinToJob: (jobId: number, payload: { question_id: number; order_index?: number }) =>
    api.post<JobQuestionLink>(`/api/jobs/${jobId}/questions/pin`, payload),

  unpinFromJob: (jobId: number, questionId: number) =>
    api.delete(`/api/jobs/${jobId}/questions/${questionId}`),

  reorder: (
    jobId: number,
    items: { question_id: number; order_index: number }[],
  ) =>
    api.patch<JobQuestionLink[]>(
      `/api/jobs/${jobId}/questions/reorder`,
      { items },
    ),

  suggestedForJob: (
    jobId: number,
    params?: { candidate_id?: number; target_count?: number },
  ) =>
    api.get<SuggestedQuestion[]>(`/api/jobs/${jobId}/suggested-questions`, {
      params,
    }),
};

// ── Job Chat ─────────────────────────────────────────────────────────────────
//
// Per-recruitment internal team chat. Members: admin / recruiter (owner) /
// delivery_lead / tac / aktywni job_collaborators. Realtime przez WS event
// `chat:message:*` w useNotifications. Patrz: backend/app/api/job_chat.py.

import type {
  CandidateChatMessage,
  CandidateChatMessageListResp,
  ChatMessage,
  ChatMessageListResp,
  ChatPinResponse,
  ChatUnreadCount,
  ChatUserMini,
  GlobalChatList,
  ReactionToggleResponse,
  ReadByUser,
} from "@/types/job-chat";

export const jobChatApi = {
  listMessages: (
    jobId: number,
    params?: { limit?: number; before_id?: number; search?: string },
  ) =>
    api.get<ChatMessageListResp>(`/api/jobs/${jobId}/chat/messages`, {
      params,
    }),
  sendMessage: (
    jobId: number,
    data: { content: string; reply_to_message_id?: number | null },
  ) => api.post<ChatMessage>(`/api/jobs/${jobId}/chat/messages`, data),
  editMessage: (jobId: number, msgId: number, data: { content: string }) =>
    api.patch<ChatMessage>(`/api/jobs/${jobId}/chat/messages/${msgId}`, data),
  deleteMessage: (jobId: number, msgId: number) =>
    api.delete<void>(`/api/jobs/${jobId}/chat/messages/${msgId}`),
  pinMessage: (jobId: number, msgId: number) =>
    api.post<ChatPinResponse>(
      `/api/jobs/${jobId}/chat/messages/${msgId}/pin`,
    ),
  unpinMessage: (jobId: number, msgId: number) =>
    api.delete<ChatPinResponse>(
      `/api/jobs/${jobId}/chat/messages/${msgId}/pin`,
    ),
  getPinned: (jobId: number) =>
    api.get<ChatMessage[]>(`/api/jobs/${jobId}/chat/pinned`),
  markRead: (jobId: number) =>
    api.put<ChatUnreadCount>(`/api/jobs/${jobId}/chat/read`),
  getUnreadCount: (jobId: number) =>
    api.get<ChatUnreadCount>(`/api/jobs/${jobId}/chat/unread-count`),
  getMembers: (jobId: number) =>
    api.get<ChatUserMini[]>(`/api/jobs/${jobId}/chat/members`),
  // Reactions (Feature 7)
  addReaction: (jobId: number, msgId: number, emoji: string) =>
    api.post<ReactionToggleResponse>(
      `/api/jobs/${jobId}/chat/messages/${msgId}/reactions`,
      { emoji },
    ),
  removeReaction: (jobId: number, msgId: number, emoji: string) =>
    api.delete<ReactionToggleResponse>(
      `/api/jobs/${jobId}/chat/messages/${msgId}/reactions/${encodeURIComponent(emoji)}`,
    ),
  // Read receipts (Feature 9)
  getReadBy: (jobId: number, msgId: number) =>
    api.get<ReadByUser[]>(
      `/api/jobs/${jobId}/chat/messages/${msgId}/read-by`,
    ),
};

// ── Candidate Chat (Feature 2) ───────────────────────────────────────────────

export const candidateChatApi = {
  listMessages: (
    candidateId: number,
    params?: { limit?: number; before_id?: number; search?: string },
  ) =>
    api.get<CandidateChatMessageListResp>(
      `/api/candidates/${candidateId}/chat/messages`,
      { params },
    ),
  sendMessage: (
    candidateId: number,
    data: { content: string; reply_to_message_id?: number | null },
  ) =>
    api.post<CandidateChatMessage>(
      `/api/candidates/${candidateId}/chat/messages`,
      data,
    ),
  editMessage: (candidateId: number, msgId: number, data: { content: string }) =>
    api.patch<CandidateChatMessage>(
      `/api/candidates/${candidateId}/chat/messages/${msgId}`,
      data,
    ),
  deleteMessage: (candidateId: number, msgId: number) =>
    api.delete<void>(`/api/candidates/${candidateId}/chat/messages/${msgId}`),
  pinMessage: (candidateId: number, msgId: number) =>
    api.post<ChatPinResponse>(
      `/api/candidates/${candidateId}/chat/messages/${msgId}/pin`,
    ),
  unpinMessage: (candidateId: number, msgId: number) =>
    api.delete<ChatPinResponse>(
      `/api/candidates/${candidateId}/chat/messages/${msgId}/pin`,
    ),
  getPinned: (candidateId: number) =>
    api.get<CandidateChatMessage[]>(
      `/api/candidates/${candidateId}/chat/pinned`,
    ),
  markRead: (candidateId: number) =>
    api.put<ChatUnreadCount>(`/api/candidates/${candidateId}/chat/read`),
  getUnreadCount: (candidateId: number) =>
    api.get<ChatUnreadCount>(
      `/api/candidates/${candidateId}/chat/unread-count`,
    ),
  getMembers: (candidateId: number) =>
    api.get<ChatUserMini[]>(`/api/candidates/${candidateId}/chat/members`),
  addReaction: (candidateId: number, msgId: number, emoji: string) =>
    api.post<ReactionToggleResponse>(
      `/api/candidates/${candidateId}/chat/messages/${msgId}/reactions`,
      { emoji },
    ),
  removeReaction: (candidateId: number, msgId: number, emoji: string) =>
    api.delete<ReactionToggleResponse>(
      `/api/candidates/${candidateId}/chat/messages/${msgId}/reactions/${encodeURIComponent(emoji)}`,
    ),
  getReadBy: (candidateId: number, msgId: number) =>
    api.get<ReadByUser[]>(
      `/api/candidates/${candidateId}/chat/messages/${msgId}/read-by`,
    ),
};

// ── Admin global chats (Feature 10) ──────────────────────────────────────────

export const adminChatsApi = {
  listGlobal: (params?: {
    limit?: number;
    chat_type?: "job" | "candidate";
    search?: string;
  }) => api.get<GlobalChatList>(`/api/admin/global-chats`, { params }),
};

// ── Stage notification rules (migracja 0066) ─────────────────────────────────

export type RecipientType =
  | "job_delivery_lead"
  | "job_recruiter"
  | "client_head_dl"
  | "client_primary_tac"
  | "specific_user"
  | "role"
  | "candidate_creator";

export interface StageNotificationRule {
  id: number;
  stage_def_id: number;
  recipient_type: RecipientType;
  specific_user_id: number | null;
  role: string | null;
  notify_inapp: boolean;
  notify_email: boolean;
  is_active: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface StageNotificationRuleInput {
  recipient_type: RecipientType;
  specific_user_id?: number | null;
  role?: string | null;
  notify_inapp: boolean;
  notify_email: boolean;
  is_active?: boolean;
}

export const stageNotificationRulesApi = {
  list: (templateId: number, stageDefId: number) =>
    api.get<StageNotificationRule[]>(
      `/api/pipeline-templates/${templateId}/stages/${stageDefId}/notification-rules`,
    ),
  create: (templateId: number, stageDefId: number, data: StageNotificationRuleInput) =>
    api.post<StageNotificationRule>(
      `/api/pipeline-templates/${templateId}/stages/${stageDefId}/notification-rules`,
      data,
    ),
  update: (
    templateId: number,
    stageDefId: number,
    ruleId: number,
    data: Partial<StageNotificationRuleInput>,
  ) =>
    api.patch<StageNotificationRule>(
      `/api/pipeline-templates/${templateId}/stages/${stageDefId}/notification-rules/${ruleId}`,
      data,
    ),
  delete: (templateId: number, stageDefId: number, ruleId: number) =>
    api.delete(
      `/api/pipeline-templates/${templateId}/stages/${stageDefId}/notification-rules/${ruleId}`,
    ),
};

export interface ClientStageNotificationOverride extends StageNotificationRule {
  client_id: number;
}

export interface ClientStageOverrideInput extends StageNotificationRuleInput {
  stage_def_id: number;
}

export const clientNotificationOverridesApi = {
  list: (clientId: number, params?: { stage_def_id?: number }) =>
    api.get<ClientStageNotificationOverride[]>(
      `/api/clients/${clientId}/notification-overrides`,
      { params },
    ),
  create: (clientId: number, data: ClientStageOverrideInput) =>
    api.post<ClientStageNotificationOverride>(
      `/api/clients/${clientId}/notification-overrides`,
      data,
    ),
  update: (
    clientId: number,
    overrideId: number,
    data: Partial<StageNotificationRuleInput>,
  ) =>
    api.patch<ClientStageNotificationOverride>(
      `/api/clients/${clientId}/notification-overrides/${overrideId}`,
      data,
    ),
  delete: (clientId: number, overrideId: number) =>
    api.delete(`/api/clients/${clientId}/notification-overrides/${overrideId}`),
};

// ── CV per rekrutacja (PR1+PR2) ────────────────────────────────────────────

export interface CVOriginalSnapshot {
  candidate_stage_id: number;
  candidate_id: number;
  job_id: number;
  has_snapshot: boolean;
  original_cv_filename: string | null;
  original_cv_language: string | null;
  original_snapshot_at: string | null;
  original_snapshot_source: string | null;
  download_url: string | null;
}

export type CVBrandedStatus = "none" | "draft" | "finalized";
export type CVTemplate = "standard" | "blind";
export type CVLanguage = "pl" | "en";

export interface CVBrandedState {
  candidate_stage_id: number;
  status: CVBrandedStatus;
  content_html: string | null;
  template: string | null;
  language: string | null;
  updated_at: string | null;
  updated_by: number | null;
  updated_by_name: string | null;
  finalized_at: string | null;
  finalized_by: number | null;
  finalized_by_name: string | null;
  snapshot_filename: string | null;
  rendered_from_default: boolean;
}

export interface CVBrandedFinalizeResponseT {
  candidate_stage_id: number;
  status: CVBrandedStatus;
  snapshot_filename: string;
  snapshot_size_bytes: number;
}

export interface CVShareTokenResp {
  token: string;
  expires_at: string | null;
  share_url_suffix: string;
  candidate_stage_cv_id: number;
}

export const candidateStageCvApi = {
  original: {
    get: (stageId: number) =>
      api.get<CVOriginalSnapshot>(
        `/api/candidates/stages/${stageId}/cv/original`,
      ),
    downloadUrl: (stageId: number) =>
      `${API_BASE}/api/candidates/stages/${stageId}/cv/original/download`,
    refresh: (stageId: number) =>
      api.post<CVOriginalSnapshot>(
        `/api/candidates/stages/${stageId}/cv/original/refresh`,
      ),
  },
  branded: {
    get: (stageId: number) =>
      api.get<CVBrandedState>(`/api/candidates/stages/${stageId}/cv/branded`),
    update: (
      stageId: number,
      payload:
        | { content_html: string }
        | { template?: CVTemplate; language?: CVLanguage },
    ) =>
      api.patch<CVBrandedState>(
        `/api/candidates/stages/${stageId}/cv/branded`,
        payload,
      ),
    finalize: (stageId: number) =>
      api.post<CVBrandedFinalizeResponseT>(
        `/api/candidates/stages/${stageId}/cv/branded/finalize`,
      ),
    printableUrl: (stageId: number) =>
      `${API_BASE}/api/candidates/stages/${stageId}/cv/branded/render-pdf`,
  },
  share: {
    create: (stageId: number, expiresInDays = 30) =>
      api.post<CVShareTokenResp>(
        `/api/candidates/stages/${stageId}/cv/share-token`,
        null,
        { params: { expires_in_days: expiresInDays } },
      ),
    revoke: (token: string) =>
      api.delete<{ status: string; token: string }>(
        `/api/candidates/stages/cv/share-token/${token}`,
      ),
  },
};

// ── Settings → AI (Traffit gap #5) ───────────────────────────────────────────

export type AIFeatureKey =
  | "scoring"
  | "job_description_generator"
  | "cv_parser"
  | "candidate_summary"
  | "champion_draft";

export interface AIFeatureConfigDto {
  feature: AIFeatureKey;
  enabled: boolean;
  monthly_limit: number;
  label: string;
  data_sent_to_ai: string[];
}

export interface AIFeatureUsageDto {
  feature: AIFeatureKey;
  used: number;
  limit: number;
  period_start: string;
  period_end: string;
}

export interface AISettingsResponse {
  master_enabled: boolean;
  features: AIFeatureConfigDto[];
  usage: AIFeatureUsageDto[];
}

export interface AIFeatureUpdate {
  enabled?: boolean;
  monthly_limit?: number;
}

export const aiSettingsApi = {
  get: () => api.get<AISettingsResponse>("/api/settings/ai"),
  setMaster: (enabled: boolean) =>
    api.patch<AISettingsResponse>("/api/settings/ai/master", { enabled }),
  updateFeature: (feature: AIFeatureKey, payload: AIFeatureUpdate) =>
    api.patch<AISettingsResponse>(
      `/api/settings/ai/features/${feature}`,
      payload,
    ),
};

// ── Settings → API integration / OAuth clients (Traffit gap #6) ──────────────

export interface OAuthClientDto {
  id: number;
  name: string;
  client_id: string;
  scopes: string[];
  enabled: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

export interface OAuthClientCreatePayload {
  name: string;
  scopes: string[];
}

export interface OAuthClientCreateResponse {
  client: OAuthClientDto;
  client_secret: string;
}

export interface OAuthClientUpdate {
  name?: string;
  scopes?: string[];
  enabled?: boolean;
}

export interface ScopeInfoDto {
  value: string;
  label: string;
}

export const oauthClientsApi = {
  list: () => api.get<OAuthClientDto[]>("/api/settings/oauth-clients"),
  scopes: () => api.get<ScopeInfoDto[]>("/api/settings/oauth-clients/scopes"),
  create: (payload: OAuthClientCreatePayload) =>
    api.post<OAuthClientCreateResponse>(
      "/api/settings/oauth-clients",
      payload,
    ),
  update: (id: number, payload: OAuthClientUpdate) =>
    api.patch<OAuthClientDto>(`/api/settings/oauth-clients/${id}`, payload),
  remove: (id: number) =>
    api.delete<void>(`/api/settings/oauth-clients/${id}`),
};

export default api;
