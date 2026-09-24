/**
 * Akademia — nabór do programów szkoleniowych (0369).
 *
 * Typy są lustrem `backend/app/api/academy.py` i
 * `backend/app/services/academy.py::application_dict`.
 */

import { api } from "@/lib/api";

export type AcademyStatus =
  | "new"
  | "to_call"
  | "scheduled"
  | "task_given"
  | "task_passed"
  | "contract_sent"
  | "signed"
  | "rejected"
  | "withdrew";

export type AcademyAction =
  | "call"
  | "no_answer"
  | "schedule"
  | "absent"
  | "give_task"
  | "task_passed"
  | "task_failed"
  | "contract_sent"
  | "signed"
  | "reject"
  | "withdraw"
  | "restore"
  | "note"
  | "move_cohort";

export interface ScreeningReason {
  code: string;
  text: string;
  quote?: string | null;
}

export interface AcademyApplication {
  id: number;
  candidate_id: number;
  full_name: string;
  email: string | null;
  phone: string | null;
  city: string | null;
  has_cv: boolean;
  source_job_id: number | null;
  source_job_title: string | null;
  applied_at: string;
  status: AcademyStatus;
  screening_verdict: "call" | "review" | "skip" | null;
  screening_reasons: ScreeningReason[];
  screening_facts: {
    studies_end_year?: number | null;
    still_studying?: boolean;
    experience_years?: number | null;
    experience_basis?: string;
    polish?: string;
  };
  screened_at: string | null;
  experience_years: number | null;
  call_attempts: number;
  last_call_at: string | null;
  session_id: number | null;
  session_starts_at: string | null;
  attended: boolean | null;
  task_due: string | null;
  task_result: "passed" | "failed" | null;
  contract_sent_at: string | null;
  signed_at: string | null;
  cohort_month: string | null;
  closed_stage: string | null;
  closed_reason: string | null;
  closed_at: string | null;
  reapplied_at: string | null;
  note: string | null;
  updated_at: string;
}

export interface AcademyCounts {
  [status: string]: number | undefined;
  luna_skipped?: number;
  unscreened?: number;
  reapplied_excluded?: number;
}

export interface AcademyProgram {
  id: number;
  name: string;
  is_active: boolean;
  max_experience_years: number;
  require_polish: boolean;
  luna_enabled: boolean;
  conditions: string[];
  session_capacity: number;
  task_due_days: number;
  created_at?: string;
}

export interface AcademySource {
  job_id: number;
  title: string;
  status: string;
  since: string | null;
  applicants: number;
}

export interface CohortDates {
  /** Pierwszy dzień miesiąca edycji (RRRR-MM-01). */
  month: string;
  /** Program trwa do 10 dni roboczych — pierwszy i ostatni dzień. */
  start: string;
  end: string;
}

export interface AcademyProgramDetail extends AcademyProgram {
  sources: AcademySource[];
  counts: AcademyCounts;
  can_manage: boolean;
  next_cohort?: CohortDates | null;
}

/** Dane do kompletu dokumentów. PESEL i adres nie są zapisywane w NEXUSIE. */
export interface DocumentsBody {
  signing_date?: string | null;
  address?: string | null;
  pesel?: string | null;
  program_start?: string | null;
  program_end?: string | null;
  handover_name?: string | null;
  protocol_date?: string | null;
}

export interface AcademyProgramListItem extends AcademyProgram {
  counts: AcademyCounts;
  sources_count: number;
}

export interface AcademySessionRow {
  id: number;
  starts_at: string;
  location: string | null;
  capacity: number;
  taken: number;
  people: number;
  cancelled: boolean;
}

export interface ActionBody {
  action: AcademyAction;
  reason?: string | null;
  session_id?: number | null;
  task_due?: string | null;
  cohort_month?: string | null;
  note?: string | null;
}

export interface SyncResult {
  busy: boolean;
  message?: string;
  new?: number;
  reapplied?: number;
  returned?: number;
  call?: number;
  review?: number;
  skip?: number;
}

export interface RhythmInput {
  weekdays: number[];
  time: string;
  weeks: number;
  start_date?: string | null;
  location?: string | null;
  capacity?: number | null;
}

export type ProgramInput = Omit<AcademyProgram, "id" | "created_at">;

export interface JobOption {
  id: number;
  title: string;
  status: string;
  external_source: string | null;
}

export const academyKeys = {
  all: ["academy"] as const,
  programs: () => ["academy", "programs"] as const,
  program: (id: number) => ["academy", "program", id] as const,
  applications: (id: number) => ["academy", "applications", id] as const,
  sessions: (id: number) => ["academy", "sessions", id] as const,
};

/**
 * Odpowiedź `responseType: "blob"` przy błędzie też jest Blobem — bez
 * odczytania go `apiErrorMessage` nie znalazłby `detail` i pokazałby ogólnik.
 */
async function unwrapBlobError(err: unknown): Promise<never> {
  const response = (err as { response?: { data?: unknown } })?.response;
  if (response && response.data instanceof Blob) {
    try {
      response.data = JSON.parse(await response.data.text());
    } catch {
      // zostaw oryginał — apiErrorMessage użyje komunikatu zastępczego
    }
  }
  throw err;
}

export const academyApi = {
  async documents(applicationId: number, body: DocumentsBody) {
    try {
      const res = await api.post<Blob>(
        `/api/academy/applications/${applicationId}/documents`,
        body,
        { responseType: "blob" },
      );
      const disposition = String(res.headers?.["content-disposition"] ?? "");
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? "Akademia_dokumenty.zip";
      return { blob: res.data, filename };
    } catch (err) {
      return unwrapBlobError(err);
    }
  },
  async programs() {
    const { data } = await api.get<{ items: AcademyProgramListItem[]; can_manage: boolean }>(
      "/api/academy/programs",
    );
    return data;
  },
  async program(id: number) {
    const { data } = await api.get<AcademyProgramDetail>(`/api/academy/programs/${id}`);
    return data;
  },
  async createProgram(body: Partial<ProgramInput> & { name: string }) {
    const { data } = await api.post<AcademyProgram>("/api/academy/programs", body);
    return data;
  },
  async updateProgram(id: number, body: Partial<ProgramInput>) {
    const { data } = await api.patch<AcademyProgram>(`/api/academy/programs/${id}`, body);
    return data;
  },
  async addSource(id: number, jobId: number, since: string | null) {
    await api.post(`/api/academy/programs/${id}/sources`, { job_id: jobId, since });
  },
  async removeSource(id: number, jobId: number) {
    await api.delete(`/api/academy/programs/${id}/sources/${jobId}`);
  },
  async searchJobs(q: string) {
    const { data } = await api.get<{ items: JobOption[] }>("/api/academy/jobs", {
      params: { q },
    });
    return data.items;
  },
  async sync(id: number) {
    const { data } = await api.post<SyncResult>(`/api/academy/programs/${id}/sync`);
    return data;
  },
  async applications(id: number) {
    const { data } = await api.get<{ items: AcademyApplication[]; counts: AcademyCounts }>(
      `/api/academy/programs/${id}/applications`,
    );
    return data;
  },
  async action(applicationId: number, body: ActionBody) {
    const { data } = await api.post<AcademyApplication>(
      `/api/academy/applications/${applicationId}/actions`,
      body,
    );
    return data;
  },
  async bulk(programId: number, ids: number[], body: ActionBody) {
    const { data } = await api.post<{ done: number[]; failed: { id: number; message: string }[] }>(
      `/api/academy/programs/${programId}/applications/bulk`,
      { ...body, ids },
    );
    return data;
  },
  async sessions(id: number) {
    const { data } = await api.get<{ items: AcademySessionRow[] }>(
      `/api/academy/programs/${id}/sessions`,
    );
    return data.items;
  },
  async createSession(id: number, body: { starts_at: string; location?: string | null; capacity?: number | null }) {
    const { data } = await api.post<{ id: number }>(`/api/academy/programs/${id}/sessions`, body);
    return data;
  },
  async rhythm(id: number, body: RhythmInput) {
    const { data } = await api.post<{ created: number }>(
      `/api/academy/programs/${id}/sessions/rhythm`,
      body,
    );
    return data;
  },
  async updateSession(sessionId: number, body: { cancelled?: boolean; location?: string | null; capacity?: number | null }) {
    const { data } = await api.patch<{ id: number; cancelled: boolean }>(
      `/api/academy/sessions/${sessionId}`,
      body,
    );
    return data;
  },
};
