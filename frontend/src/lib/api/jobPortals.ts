// Multiposting rekrutacji — lustro `backend/app/api/job_portals.py`
// i kontraktu `docs/job-boards-rocketjobs-contract.md`.
//
// RocketJobs i JustJoin.IT to JEDNO API dostawcy (1EP) i jedno połączone konto
// firmy (OAuth, Ustawienia → Portale ogłoszeniowe), w NEXUSIE — dwa portale.
// Pracuj.pl czeka na dokumentację. Wszystko stoi za flagami: sekcje renderują
// się dopiero, gdy `GET /api/job-portals/config` zgłosi portal gotowy. Treść
// ogłoszenia serwer bierze wyłącznie z zatwierdzonego opisu publicznego,
// a parametry (kategoria, miasto, widełki…) z `PortalListingOptions`.

import { api } from "@/lib/api";

export type JobPortal = "pracuj_pl" | "justjoinit" | "rocketjobs";
/** Portale obsługiwane przez API dostawcy 1EP (słowniki, konto firmy). */
export type JobBoard = "rocketjobs" | "justjoinit";
export type PortalState = "disabled" | "misconfigured" | "not_connected" | "ready";
export type PendingAction = "publish" | "update" | "close" | null;
export type JobPostingStatus =
  | "draft"
  | "publishing"
  | "published"
  | "expired"
  | "removed"
  | "failed";

export interface PortalConfigItem {
  portal: JobPortal;
  label: string;
  state: PortalState;
  enabled: boolean;
}

export interface PortalConfigResponse {
  portals: PortalConfigItem[];
  any_ready: boolean;
}

/** Widełki netto B2B w PLN; `to` najwyżej 3 × `from` (wymóg portalu). */
export interface PortalSalary {
  from: number;
  to: number;
  unit: "hour" | "month";
}

export interface PortalListingOptions {
  /** Klucz ze słownika portalu — wymagany do publikacji. */
  category: string | null;
  experience_level: string | null;
  working_time: string | null;
  workplace_type: string | null;
  /** Tylko przy `hybrid`, 1–4. */
  office_days: number | null;
  /** Portal wymaga co najmniej jednej lokalizacji. */
  city: string | null;
  /** `null` = ogłoszenie bez widełek (decyzja 25.09: nigdy z budżetu). */
  salary: PortalSalary | null;
}

export const EMPTY_LISTING_OPTIONS: PortalListingOptions = {
  category: null,
  experience_level: null,
  working_time: null,
  workplace_type: null,
  office_days: null,
  city: null,
  salary: null,
};

export interface JobPostingRead {
  id: number;
  portal: JobPortal;
  status: JobPostingStatus;
  external_id: string | null;
  url: string | null;
  published_at: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  attempts: number;
  created_at: string | null;
  updated_at: string | null;
  options?: PortalListingOptions | null;
  pending_action?: PendingAction;
}

export interface DictionaryEntry {
  key: string;
  name: string;
}

export interface BoardDictionaries {
  categories: DictionaryEntry[];
  experience_levels: DictionaryEntry[];
  working_times: DictionaryEntry[];
  workplace_types: DictionaryEntry[];
}

export interface JobBoardBalance {
  codes: { name: string; remaining: number; expires_at: string | null; plan_key: string | null }[];
  subscriptions: {
    id: string;
    remaining: number;
    end_date: string | null;
    plan_key: string | null;
    active: boolean;
  }[];
}

export interface JobBoardConnectionBoard {
  board: JobBoard;
  label: string;
  enabled: boolean;
  organization_unit_id: string | null;
  balance: JobBoardBalance | null;
  balance_error: string | null;
}

export interface JobBoardConnectionRead {
  oauth_configured: boolean;
  status: "not_connected" | "active" | "reconnect_required";
  connected_by_name: string | null;
  connected_at: string | null;
  last_error: string | null;
  boards: JobBoardConnectionBoard[];
}

export interface PublicDraftRequest {
  title: string;
  client_id: number | null;
  description?: string | null;
  must_skills?: string[];
  nice_skills?: string[];
  location?: string | null;
  remote_policy?: "onsite" | "hybrid" | "remote" | null;
  onsite_days_per_week?: number | null;
  champion_profile?: Record<string, unknown> | null;
}

export type PublicDraftFindingCode = "client_name" | "money" | "contact" | "person_name";

export interface PublicDraftRead {
  public_title: string;
  subtitle: string;
  about: string;
  findings: { code: PublicDraftFindingCode | string; message: string; excerpt: string }[];
}

export const JOB_PORTALS_CONFIG_KEY = ["job-portals", "config"] as const;
export const JOB_BOARD_CONNECTION_KEY = ["job-boards", "connection"] as const;
export const jobPortalKeys = {
  config: JOB_PORTALS_CONFIG_KEY,
  postings: (jobId: number) => ["job-portals", "postings", jobId] as const,
  listingDefaults: (jobId: number) => ["job-portals", "listing-defaults", jobId] as const,
  dictionaries: (board: JobBoard) => ["job-boards", "dictionaries", board] as const,
  connection: JOB_BOARD_CONNECTION_KEY,
};

export const POSTING_STATUS_LABELS: Record<JobPostingStatus, string> = {
  draft: "Szkic",
  publishing: "Wysyłanie…",
  published: "Opublikowane",
  expired: "Wygasłe",
  removed: "Wycofane",
  failed: "Nieudane",
};

/** Co czeka w kolejce dla żywego ogłoszenia (`publish` pokazuje sam status). */
export const PENDING_ACTION_LABELS: Record<Exclude<PendingAction, null>, string | null> = {
  publish: null,
  update: "Aktualizacja w kolejce",
  close: "Zamykanie w kolejce",
};

export function pendingActionLabel(action: PendingAction | undefined): string | null {
  return action ? PENDING_ACTION_LABELS[action] : null;
}

/** Portal, którego słowniki (kategorie…) daje API dostawcy 1EP. */
export function isJobBoard(portal: JobPortal): portal is JobBoard {
  return portal === "rocketjobs" || portal === "justjoinit";
}

// ── Wywołania ────────────────────────────────────────────────────────────────

export async function fetchPortalConfig(): Promise<PortalConfigResponse> {
  const { data } = await api.get<PortalConfigResponse>("/api/job-portals/config");
  return data;
}

export async function fetchJobPostings(jobId: number): Promise<JobPostingRead[]> {
  const { data } = await api.get<JobPostingRead[]>(`/api/jobs/${jobId}/portals`);
  return data;
}

export async function fetchListingDefaults(jobId: number): Promise<PortalListingOptions> {
  const { data } = await api.get<PortalListingOptions>(
    `/api/jobs/${jobId}/portal-listing-defaults`,
  );
  return { ...EMPTY_LISTING_OPTIONS, ...(data ?? {}) };
}

export async function fetchBoardDictionaries(board: JobBoard): Promise<BoardDictionaries> {
  const { data } = await api.get<Partial<BoardDictionaries>>(`/api/job-boards/${board}/dictionaries`);
  const list = (value: unknown): DictionaryEntry[] => (Array.isArray(value) ? value : []);
  return {
    categories: list(data?.categories),
    experience_levels: list(data?.experience_levels),
    working_times: list(data?.working_times),
    workplace_types: list(data?.workplace_types),
  };
}

export async function publishToPortal(
  jobId: number,
  portal: JobPortal,
  options?: PortalListingOptions,
): Promise<JobPostingRead> {
  const { data } = await api.post<JobPostingRead>(
    `/api/jobs/${jobId}/portals/${portal}/publish`,
    options ? { options } : {},
  );
  return data;
}

export async function updatePostingOptions(
  jobId: number,
  portal: JobPortal,
  options: PortalListingOptions,
): Promise<JobPostingRead> {
  const { data } = await api.patch<JobPostingRead>(`/api/jobs/${jobId}/portals/${portal}/options`, {
    options,
  });
  return data;
}

export async function unpublishFromPortal(jobId: number, portal: JobPortal): Promise<JobPostingRead> {
  const { data } = await api.post<JobPostingRead>(`/api/jobs/${jobId}/portals/${portal}/unpublish`);
  return data;
}

export async function fetchJobBoardConnection(): Promise<JobBoardConnectionRead> {
  const { data } = await api.get<JobBoardConnectionRead>("/api/job-boards/jjit/connection");
  return data;
}

/** Adres zgody OAuth dostawcy — front przechodzi pod niego `window.location`. */
export async function jobBoardAuthorizeUrl(): Promise<string> {
  const { data } = await api.get<{ authorize_url: string }>("/api/job-boards/jjit/authorize");
  return data.authorize_url;
}

export async function disconnectJobBoard(): Promise<void> {
  await api.delete("/api/job-boards/jjit/connection");
}

/** Szkic opisu publicznego z requestu (AI) — niczego nie zapisuje. */
export async function fetchPublicDraft(body: PublicDraftRequest): Promise<PublicDraftRead> {
  const { data } = await api.post<Partial<PublicDraftRead>>("/api/job-intake/public-draft", body, {
    timeout: 120_000,
  });
  return {
    public_title: data?.public_title ?? "",
    subtitle: data?.subtitle ?? "",
    about: data?.about ?? "",
    findings: Array.isArray(data?.findings) ? data.findings : [],
  };
}

// ── Czyste pomocniki ─────────────────────────────────────────────────────────

/** Najnowsza publikacja danego portalu (lista przychodzi od najnowszej). */
export function latestPosting(postings: JobPostingRead[], portal: JobPortal): JobPostingRead | null {
  return postings.find((p) => p.portal === portal) ?? null;
}

/** Czy publikacja jest „żywa” (w kolejce albo na portalu). */
export function isLive(posting: JobPostingRead | null): boolean {
  return posting !== null && (posting.status === "publishing" || posting.status === "published");
}

/** Portale, na które da się dziś wysłać ogłoszenie. */
export function readyPortals(config: PortalConfigResponse | undefined): PortalConfigItem[] {
  return (config?.portals ?? []).filter((p) => p.state === "ready");
}

/**
 * Braki formularza ogłoszenia — lustro walidacji serwera (422 `listing_invalid`),
 * żeby DL zobaczył je przed kliknięciem. Serwer i tak sprawdza drugi raz.
 */
export function validateListingOptions(
  options: PortalListingOptions,
  { board }: { board: JobPortal | null },
): string[] {
  const problems: string[] = [];
  // Lustro `jjit_payload.validate` (backend) — te same braki, te same zdania.
  if (board && isJobBoard(board)) {
    if (!options.category) problems.push("Wybierz kategorię ogłoszenia.");
    if (!options.experience_level) problems.push("Wybierz poziom doświadczenia.");
    if (!options.working_time) problems.push("Wybierz wymiar pracy.");
    if (!options.workplace_type) problems.push("Wybierz tryb pracy (zdalnie, biuro albo hybrydowo).");
  }
  if (!options.city?.trim()) problems.push("Wpisz miasto — portal wymaga lokalizacji.");
  if (options.office_days != null) {
    // Puste przy pracy hybrydowej = elastyczny podział (portal to dopuszcza).
    if (options.workplace_type !== "hybrid") problems.push("Dni w biurze podaje się tylko przy pracy hybrydowej.");
    else if (!Number.isInteger(options.office_days) || options.office_days < 1 || options.office_days > 4)
      problems.push("Przy pracy hybrydowej podaj od 1 do 4 dni w biurze.");
  }
  const salary = options.salary;
  if (salary) {
    if (!(salary.from > 0)) problems.push("Widełki: kwota „od” musi być większa od zera.");
    else if (!(salary.to >= salary.from)) problems.push("Widełki: kwota „do” nie może być niższa niż „od”.");
    else if (salary.to > salary.from * 3)
      problems.push("Widełki: kwota „do” może być najwyżej trzy razy wyższa niż „od”.");
  }
  return problems;
}

/** Lista braków z odmowy serwera (422 `listing_invalid`) albo `null`. */
export function listingProblemsFromError(error: unknown): string[] | null {
  const response = (error as { response?: { status?: unknown; data?: unknown } } | null)?.response;
  if (response?.status !== 422) return null;
  const data = response.data as { detail?: unknown; code?: unknown; problems?: unknown } | null;
  const body = (
    data?.detail && typeof data.detail === "object" && !Array.isArray(data.detail) ? data.detail : data
  ) as { code?: unknown; problems?: unknown } | null;
  if (body?.code !== "listing_invalid" || !Array.isArray(body.problems)) return null;
  return body.problems.filter((p): p is string => typeof p === "string");
}
