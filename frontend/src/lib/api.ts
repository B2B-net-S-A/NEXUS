import axios, { AxiosError } from "axios";

import { SLOW_ENDPOINT_TIMEOUT_MS } from "./http-timeouts";
import { clearSessionArtifacts, getAccessToken } from "./session";
import type {
  RoleActionPermissionChange,
  RoleSectionPermissionChange,
  SectionPermissionMutationResponse,
  SectionPermissionsResponse,
  UserActionPermissionChange,
  UserSectionPermissionChange,
  UserSectionPermissionsResponse,
} from "./section-access";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// 30s global request timeout. Before this was unset → axios default = infinite
// → user-visible "hangs forever" on Graph API endpoints or slow reports.
// 30s daje wystarczająco czasu na heavy SQL (e.g. /api/reports/time-to-hire
// pre-PR7 brał ~15s) ale ogranicza worst case do tractable wartości.
// QA 2026-05-27 zaobserwował "API timeout" na /microsoft365/connection
// i /teams-channels — diagnostykę poprawia 30s timeout zamiast wiecznego
// hangu.
// Wywołania, w których liczy model (LLM / scoring / generacja dokumentu),
// nadpisują ten domyślny sufit per-request `SLOW_ENDPOINT_TIMEOUT_MS`
// — powód w `lib/http-timeouts.ts`.
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

export const api = axios.create({
  baseURL: API_BASE,
  timeout: DEFAULT_REQUEST_TIMEOUT_MS,
  headers: { "Content-Type": "application/json" },
});

/**
 * Extract user-facing error message from any thrown value.
 *
 * Order of preference:
 *  1. AxiosError with `response.data.detail` (FastAPI validation/HTTPException format)
 *  2. AxiosError with `response.data.message`
 *  3. Error.message (generic JS error)
 *  4. String(e) fallback
 *
 * Usage:
 *   try { await api.post(...) } catch (e) {
 *     setStatus({ type: "error", msg: extractErrorMsg(e) });
 *   }
 *
 * Quality check finding MEDIUM #23 — most onError handlers used String(e)
 * which produces "Error: Request failed with status code 422" instead of
 * the actionable Pydantic validation message that the user needs.
 */
// Polskie etykiety pól kontraktu — wspólne dla formularzy i dla tłumaczenia
// backendowego 409 {message: "Missing required fields", missing: [...]}
// (ACTIVATION_REQUIRED_FIELDS w backend/app/services/contract_service.py).
export const CONTRACT_FIELD_LABELS: Record<string, string> = {
  candidate_id: "Kandydat",
  client_id: "Klient",
  start_date: "Data rozpoczęcia",
  end_date: "Data zakończenia",
  rate_candidate: "Stawka kosztowa (kandydata)",
  rate_client: "Stawka przychodowa (klienta)",
  contract_type: "Typ kontraktu",
  work_mode: "Tryb pracy",
  rate_unit: "Jednostka stawki",
};

export function extractErrorMsg(error: unknown): string {
  if (error instanceof AxiosError && error.response) {
    // 429 = limit zapytań. slowapi odpowiada ciałem {"error": "Rate limit
    // exceeded: N per 1 minute"} — BEZ klucza `detail`, więc bez tej gałęzi
    // wołający spadał na surowe `error.message` i użytkownik dostawał
    // „Request failed with status code 429" (zgłoszenie: Wiktoria Denka).
    if (error.response.status === 429) {
      console.error("[api] rate limited:", error.response.data);
      return "Zbyt wiele prób w krótkim czasie — odczekaj minutę i spróbuj ponownie.";
    }
    const data = error.response.data;
    if (data && typeof data === "object") {
      // `require_roles` (backend/app/api/deps.py) zwraca detail w formie
      // "Requires one of roles: ['admin', 'tac', ...]" — to nazwy ról z modelu
      // danych, nie komunikat dla użytkownika. Wyciekał wprost do toasta
      // (zgłoszenie generatora umów: użytkownik zobaczył surową listę ról).
      // Tłumimy jak surowe `loc` niżej: raw do konsoli, człowiekowi zdanie.
      if (
        error.response.status === 403 &&
        typeof data.detail === "string" &&
        data.detail.startsWith("Requires one of roles:")
      ) {
        console.error("[api] role gate:", data.detail);
        return "Nie masz uprawnień do tej operacji — poproś administratora o dostęp.";
      }
      // FastAPI HTTPException(detail="...") → string detail
      if (typeof data.detail === "string") return data.detail;
      // Lifecycle kontraktu: 409 {message: "Missing required fields",
      // missing: [...]}. Surowy `message` gubił LISTĘ pól — użytkownik widział
      // goły angielski banner bez wskazania, czego brakuje (zgłoszenie:
      // formularz „Nowy kontrakt", Jakub Jedynak / CARDIF). Tłumaczymy nazwy
      // pól na etykiety z formularza.
      if (
        data.detail &&
        typeof data.detail === "object" &&
        !Array.isArray(data.detail) &&
        // Jawny match na message lifecycle'u — sam klucz `missing` mógłby
        // w przyszłości znaczyć co innego w innym endpointzie.
        (data.detail as { message?: unknown }).message ===
          "Missing required fields" &&
        Array.isArray((data.detail as { missing?: unknown }).missing) &&
        (data.detail as { missing: unknown[] }).missing.length > 0
      ) {
        const missing = (data.detail as { missing: string[] }).missing;
        const labels = missing.map(
          (field) => CONTRACT_FIELD_LABELS[field] ?? field,
        );
        return `Uzupełnij brakujące pola: ${labels.join(", ")}`;
      }
      // Domenowe konflikty mogą zwracać ustrukturyzowany detail, np.
      // {message, contract_ids}. Użytkownik powinien zobaczyć komunikat, nie
      // "[object Object]" ani ogólny status HTTP.
      if (
        data.detail &&
        typeof data.detail === "object" &&
        !Array.isArray(data.detail) &&
        typeof (data.detail as { message?: unknown }).message === "string"
      ) {
        return (data.detail as { message: string }).message;
      }
      // FastAPI Pydantic ValidationError → list of { msg, loc, ... }
      if (Array.isArray(data.detail) && data.detail.length > 0) {
        const first = data.detail[0];
        if (typeof first?.msg === "string") {
          const loc = Array.isArray(first.loc) ? first.loc : [];
          // Tylko `body` to dane wpisane przez użytkownika — tam nazwa pola
          // + komunikat są actionable (quality finding MEDIUM #23).
          if (loc[0] === "body") {
            const field = loc.slice(1).join(".") || "pole";
            return `${field}: ${first.msg}`;
          }
          // query/path/header ustawia kod aplikacji, nie użytkownik — surowy
          // loc to wyciek wewnętrznego kontraktu (M3-UI-02, np.
          // "query.current_user: Field required" na zakładce Dopasowanie).
          console.error("[api] request contract error:", data.detail);
          return "Błąd żądania — odśwież stronę lub spróbuj ponownie.";
        }
      }
      if (typeof data.message === "string") return data.message;
    }
    return error.message || `HTTP ${error.response.status}`;
  }
  if (error instanceof Error) return error.message;
  return String(error);
}

// Attach token from localStorage.
//
// **Explicit beats implicit**: a call that passes its own `Authorization`
// header wins over whatever still sits in localStorage. Axios has already
// merged per-request headers into `config.headers` (an AxiosHeaders instance)
// by the time this interceptor runs, so an unconditional assignment here
// silently CLOBBERS the caller's token.
//
// That clobbering locked users out of BOTH login paths. Each one authenticates
// first and then calls `/api/auth/me` with the freshly minted token passed
// explicitly — BEFORE `setAuth` has persisted it:
//   - Microsoft SSO   → src/app/login/microsoft/callback/page.tsx (after
//                       trading the one-time code for a JWT)
//   - e-mail + hasło  → src/app/login/page.tsx::handleSubmit (after
//                       /api/auth/login)
// Anyone who still had an expired token in localStorage got that dead token
// pinned onto the request instead, so `/api/auth/me` answered 401 "Could not
// validate credentials" — surfaced as a bounce back to /login (SSO) or as an
// error banner over a correct password. The lockout was permanent: the 401
// handler below declines to clear storage while on a `/login*` path, so the
// stale token survived every retry. A user with no stored token logged in
// fine, which is why this looked user-specific.
//
// It also prevented a subtler identity mix-up: on a shared browser a *valid*
// token for another user would have made `/api/auth/me` describe THEM while we
// stored the SSO user's token.
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = getAccessToken();
    const headers = config.headers as unknown as {
      has?: (name: string) => boolean;
      Authorization?: unknown;
    };
    const hasExplicitAuth =
      typeof headers?.has === "function"
        ? headers.has("Authorization")
        : headers?.Authorization != null;
    if (token && !hasExplicitAuth) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    // Admin „podgląd jako użytkownik": gdy aktywny, dokleja nagłówek z id
    // podglądanego usera. Backend (admin-only, read-only) podmienia wtedy
    // efektywnego current_user — patrz backend/app/api/deps.py.
    //
    // NIGDY nie doklejaj podglądu do endpointów uwierzytelniania (/api/auth/*):
    // login, /me, verify, refresh itd. muszą działać na tożsamości zalogowanego
    // admina, a nie podglądanego usera — inaczej „podgląd jako" wyciekłby do
    // samego uwierzytelniania (np. /api/auth/me opisałoby podglądanego usera).
    const impersonateId = localStorage.getItem("nexus_impersonate_id");
    const isAuthEndpoint = (config.url ?? "").startsWith("/api/auth/");
    if (impersonateId && !isAuthEndpoint) {
      config.headers["X-Impersonate-User-Id"] = impersonateId;
    }
  }
  return config;
});

// Retry transient backend unavailability — Coolify big-bang deploys leave a
// ~30-90s window where Traefik returns 502/503 with no CORS headers, so saves
// fail with a cryptic "Nie udało się zapisać" toast. Retry up to 2× with
// exponential backoff (1.5s, 3s) so users don't lose their input.
//
// Powtarzanie jest ZAWĘŻONE po czasowniku HTTP, bo to jedyna warstwa retry dla
// zapisów (QueryProvider ustawia `retry` tylko pod `queries`, mutacje mają
// w react-query domyślne 0). Bez guardu najszersza gałąź (`!err.response`)
// powtarzała POST/PATCH/DELETE — a ta gałąź jest prawdziwa NIE tylko dla okna
// deployu: backendowe 500 traci nagłówki CORS na najbardziej zewnętrznym
// ServerErrorMiddleware Starlette, więc w przeglądarce wygląda identycznie jak
// zerwane połączenie. Wyjątek rzucony PO commicie INSERT-a dawał trzy notatki,
// trzech kandydatów albo trzy pozycje faktury i jeden generyczny toast.
//
// Dla zapisów powtarzamy WYŁĄCZNIE 502/503 z realną (widoczną dla przeglądarki)
// odpowiedzią — brama odpowiedziała ZA aplikacją, więc żądanie dowodliwie do
// niej nie dotarło. Świadomie NIE 504: to znaczy „czekałem za długo", a backend
// mógł pracę dokończyć. I świadomie NIE `!err.response`: ta gałąź nie odróżnia
// niedostępnej bramy od 500 po zapisie. Cena jest znana i przyjęta: jeśli
// w oknie deployu Traefik odpowie 502/503 BEZ nagłówków CORS, zapis nie
// zostanie powtórzony i użytkownik zobaczy błąd — utrata wpisanych danych jest
// odwracalna (ponowne kliknięcie), zduplikowany kandydat albo pozycja faktury
// nie jest.
const TRANSIENT_RETRY_STATUSES = new Set([502, 503, 504]);
/** Zapisu nie da się bezpiecznie powtórzyć poza tymi dwoma kodami. */
const NEVER_REACHED_APP_STATUSES = new Set([502, 503]);
const IDEMPOTENT_METHODS = new Set(["get", "head", "options"]);
const TRANSIENT_RETRY_MAX = 2;
const TRANSIENT_RETRY_BASE_MS = 1500;

type RetryableConfig = { _transientRetryCount?: number };

/**
 * Timeout po stronie PRZEGLĄDARKI (sufit instancji albo per-request
 * `SLOW_ENDPOINT_TIMEOUT_MS`). Żądanie dotarło i backend nadal je liczy —
 * powtórka nie skraca oczekiwania, tylko mnoży pracę i koszt modelu
 * (`lib/http-timeouts.ts` opisuje dokładnie ten tryb awarii). Nie powtarzamy
 * takiego błędu żadnym czasownikiem.
 */
function isClientTimeout(err: AxiosError): boolean {
  return err.code === "ECONNABORTED" || err.code === "ETIMEDOUT";
}

function isRetryable(err: AxiosError, method: string): boolean {
  if (isClientTimeout(err)) return false;
  if (IDEMPOTENT_METHODS.has(method)) {
    return !err.response || TRANSIENT_RETRY_STATUSES.has(err.response.status);
  }
  return !!err.response && NEVER_REACHED_APP_STATUSES.has(err.response.status);
}

api.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const config = err.config as (typeof err.config & RetryableConfig) | undefined;
    if (!config) return Promise.reject(err);

    const attempts = config._transientRetryCount ?? 0;
    // Axios domyślnie wysyła GET, gdy `method` nie podano.
    const method = (config.method ?? "get").toLowerCase();
    if (!isRetryable(err, method) || attempts >= TRANSIENT_RETRY_MAX) {
      return Promise.reject(err);
    }

    config._transientRetryCount = attempts + 1;
    const delay = TRANSIENT_RETRY_BASE_MS * Math.pow(2, attempts);
    await new Promise((r) => setTimeout(r, delay));
    return api.request(config);
  }
);

// Session-expired auto-redirect.
//
// A dead session — expired JWT, or a deploy that rotated SECRET_KEY — is always
// reported by the backend as **401 Unauthorized**: `get_current_user` raises 401
// for any token it cannot validate. That is the single, unambiguous "your
// session is gone" signal, so it is the only trigger for an automatic
// logout+redirect (otherwise the user is stranded — UserMenu doesn't render when
// user=null, leaving no way to reach /login).
//
// A **403 Forbidden** means the opposite: the user IS authenticated, they just
// lack permission for that one resource (a recruiter opening the Chat tab of a
// candidate they aren't assigned to, an admin previewing-as-role hitting
// /api/admin/*, etc.). A 403 must NEVER log the user out. An earlier heuristic
// treated a burst of 403s as an expired session and logged people out whenever
// several forbidden endpoints fired together — e.g. the candidate Chat tab fans
// out members + pinned + messages + read on mount, all 403 for a non-member.
// 403s are now surfaced to the caller and handled in place by the component.
let sessionRedirectInFlight = false;

function triggerSessionExpiredRedirect(): void {
  if (typeof window === "undefined") return;
  if (sessionRedirectInFlight) return;
  // Already on the login flow (or any /login/* sub-route) — nothing to do.
  if (window.location.pathname.startsWith("/login")) return;
  sessionRedirectInFlight = true;
  // Wyczyść WSZYSTKIE artefakty sesji (JWT, cache usera ORAZ markery podglądu
  // „jako użytkownik") — inaczej nexus_impersonate_id/nexus_real_user przeżyłyby
  // martwą sesję i wyciekły do następnego logowania (nagłówek impersonacji
  // jechałby dalej). clearSessionArtifacts jest no-op poza przeglądarką i sam
  // łapie wyjątki storage.
  clearSessionArtifacts();
  const next = encodeURIComponent(
    window.location.pathname + window.location.search,
  );
  window.location.href = `/login?reason=session_expired&next=${next}`;
}

// Defense in depth: a 403 whose detail is exactly "Not authenticated" is
// FastAPI's `HTTPBearer` reporting a **missing** Authorization header, i.e. a
// dead session wearing a 403 costume. Backend now returns 401 for that case
// (backend/app/api/deps.py — `HTTPBearer(auto_error=False)`), but this guard
// stays so a stale backend, a cached response, or any future dependency that
// re-enables `auto_error` can't strand the user inside the app shell again.
// Every *real* 403 ("Requires one of roles: …", capability guards) is
// untouched and still handled in place by the component.
function isMissingCredentials403(err: AxiosError): boolean {
  if (err.response?.status !== 403) return false;
  const detail = (err.response.data as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" && detail.trim() === "Not authenticated";
}

api.interceptors.response.use(
  (res) => res,
  (err: AxiosError) => {
    if (typeof window === "undefined") return Promise.reject(err);
    if (err.response?.status === 401 || isMissingCredentials403(err)) {
      triggerSessionExpiredRedirect();
    }
    return Promise.reject(err);
  },
);

// ── Clients directory ────────────────────────────────────────────────────────

/**
 * Portfolio category is an explicit business classification stored on a
 * client scope. It is intentionally separate from both MSA dates and the
 * legacy client lifecycle status (`active | inactive | prospect`).
 */
export type ClientDirectoryCategory = "active" | "relationship" | "inactive";

export interface ClientDirectoryItem {
  /** Stable row identity. One client may have more than one directory scope. */
  scope_id: number;
  client_id: number;
  msa_id: number | null;
  display_name: string;
  legal_name: string | null;
  scope_label: string | null;
  industry: string | null;
  active_consultants_count: number;
  active_contracts_count: number;
  /** EFFECTIVE values: a manual placement override wins over the manifest/MSA. */
  effective_date: string | null;
  expiry_date: string | null;
  category: ClientDirectoryCategory;
  /** Manifest/base category before any override — used to detect a real
   *  manual placement and to clear an override that matches the manifest. */
  category_base: ClientDirectoryCategory;
  client_status: "active" | "inactive" | "prospect";
  /** Raw override state — non-null means the row was manually placed. */
  category_override: ClientDirectoryCategory | null;
  contract_start_override: string | null;
  contract_end_override: string | null;
}

export interface ClientDirectoryCategoryCounts {
  /** Unique clients in each category, never the number of scope rows. */
  active: number;
  relationship: number;
  inactive: number;
}

export interface ClientDirectoryResponse {
  items: ClientDirectoryItem[];
  total_rows: number;
  total_clients: number;
  page: number;
  page_size: number;
  category_counts: ClientDirectoryCategoryCounts;
  as_of: string;
}

export interface ClientDirectoryParams {
  category: ClientDirectoryCategory;
  q?: string;
  page: number;
  page_size: number;
}

/**
 * Manual placement of a directory scope — moves a client between the
 * Aktywni/Relacyjni/Nieaktywni tabs and/or pins a contract period WITHOUT
 * touching the manifest-owned columns (so it never causes portfolio drift /
 * an unhealthy `/api/health/deep`). A field sent as `null` clears that
 * override; an absent field is left unchanged (partial update).
 */
export interface PortfolioScopePlacementUpdate {
  category?: ClientDirectoryCategory | null;
  contract_start?: string | null;
  contract_end?: string | null;
}

export interface PortfolioScope {
  id: number;
  client_id: number;
  framework_contract_id: number | null;
  category: ClientDirectoryCategory;
  category_override: ClientDirectoryCategory | null;
  contract_start_override: string | null;
  contract_end_override: string | null;
  label: string | null;
  source_system: string;
}

export const clientsDirectoryApi = {
  list: (params: ClientDirectoryParams, signal?: AbortSignal) =>
    api.get<ClientDirectoryResponse>("/api/clients/directory", {
      params,
      signal,
    }),
  updateScopePlacement: (
    clientId: number,
    scopeId: number,
    payload: PortfolioScopePlacementUpdate,
  ) =>
    api.patch<PortfolioScope>(
      `/api/clients/${clientId}/portfolio-scopes/${scopeId}/placement`,
      payload,
    ),
};

// ── Client team / request ownership ───────────────────────────────────────

export interface ClientTeamTacAssignment {
  id: number;
  user_id: number;
  name: string;
  email: string;
  role?: string | null;
  created_at: string;
  /**
   * Personal work preference of this TAC. Several TACs assigned to the same
   * client may all mark that client as their first priority; it is not a
   * client-level leader flag and must never choose a request owner implicitly.
   * Optional during the one-release expand window.
   */
  is_first_priority_for_tac?: boolean | null;
}

export interface ClientTeamDeliveryLeadAssignment {
  id: number;
  user_id: number;
  name: string;
  email: string;
  role?: string | null;
  created_at: string;
  is_head: boolean;
}

export interface ClientTeamResponse {
  tacs: ClientTeamTacAssignment[];
  delivery_leads: ClientTeamDeliveryLeadAssignment[];
}

export interface ClientTacAssignmentInput {
  user_id: number;
  /** Nullable/optional while old and new application revisions overlap. */
  is_first_priority_for_tac?: boolean | null;
}

export interface ClientTacFirstPriorityInput {
  enabled: boolean;
  successor_client_id?: number;
}

export const clientTeamApi = {
  get: (clientId: number) =>
    api.get<ClientTeamResponse>(`/api/clients/${clientId}/team`),
  addTac: (clientId: number, payload: ClientTacAssignmentInput) =>
    api.post(`/api/clients/${clientId}/tacs`, payload),
  removeTac: (
    clientId: number,
    userId: number,
    successorClientId?: number,
  ) =>
    api.delete(`/api/clients/${clientId}/tacs/${userId}`, {
      params:
        successorClientId === undefined
          ? undefined
          : { successor_client_id: successorClientId },
    }),
  setTacFirstPriority: (
    clientId: number,
    userId: number,
    payload: ClientTacFirstPriorityInput,
  ) =>
    api.put(
      `/api/clients/${clientId}/tacs/${userId}/first-priority`,
      payload,
    ),
};

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
  /** Self-service registration. Creates a read-only (viewer) account restricted
   *  to whitelisted corporate domains; an activation link is emailed and the
   *  account cannot log in until verified. Returns 201 with a generic message. */
  register: (name: string, email: string, password: string) =>
    api.post("/api/auth/register", { name, email, password }),
  /** Confirm the email address using the token from the activation link. */
  verifyEmail: (token: string) => api.post("/api/auth/verify-email", { token }),
  /** Re-send the activation link. Always 200 with a generic message
   *  (anti-enumeration). */
  resendVerification: (email: string) =>
    api.post("/api/auth/resend-verification", { email }),
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
  // Stawka do klienta (sell rate) dla konkretnej rekrutacji. rate_value=null
  // czyści stawkę. Zapis ląduje na najnowszym etapie tej (candidate, job).
  setRecruitmentClientRate: (
    candidateId: number,
    jobId: number,
    payload: {
      rate_value: number | null;
      rate_unit?: RateUnit;
      rate_currency?: string;
    },
  ) =>
    api.patch(
      `/api/candidates/${candidateId}/recruitments/${jobId}/client-rate`,
      payload,
    ),
  // Stawka kandydata (expected rate — oczekiwania kandydata) dla konkretnej
  // rekrutacji. rate_value=null czyści stawkę. Lustrzane do client-rate; zapis
  // ląduje na najnowszym etapie tej (candidate, job).
  setRecruitmentExpectedRate: (
    candidateId: number,
    jobId: number,
    payload: {
      rate_value: number | null;
      rate_unit?: RateUnit;
      rate_currency?: string;
    },
  ) =>
    api.patch(
      `/api/candidates/${candidateId}/recruitments/${jobId}/expected-rate`,
      payload,
    ),
  // Usuń kandydata z rekrutacji — kasuje całą obecność w pipeline tej oferty
  // (wszystkie etapy + kaskadowo snapshoty CV / share-tokeny / maile odrzucenia).
  // Operacja korekcyjna, odrębna od reject/withdrawn.
  removeFromRecruitment: (candidateId: number, jobId: number) =>
    api.delete(`/api/candidates/${candidateId}/recruitments/${jobId}`),
};

export type CandidateLanguageCefrLevel =
  | "A1"
  | "A2"
  | "B1"
  | "B2"
  | "C1"
  | "C2";

export type CandidateLanguageProvenance =
  | "manual"
  | "cv"
  | "traffit"
  | "talent_radar"
  | "tr_legacy"
  | "csv"
  | "legacy"
  | "unknown";

export interface CandidateLanguage {
  id: number;
  language_code: string;
  language_name: string;
  cefr_level: CandidateLanguageCefrLevel | null;
  is_native: boolean;
  is_level_unknown: boolean;
  provenance: CandidateLanguageProvenance;
  manual_lock: boolean;
  version: number;
}

export interface CandidateLanguagesResponse {
  candidate_id: number;
  version: number;
  languages: CandidateLanguage[];
}

export interface CandidateLanguageInput {
  language_code: string;
  language_name: string;
  cefr_level: CandidateLanguageCefrLevel | null;
  is_native: boolean;
  is_level_unknown: boolean;
}

export interface CandidateProfileRate {
  candidate_id: number;
  amount: string | null;
  currency: "PLN";
  unit: "hour";
  tax_basis: "net";
  contract_type: "b2b";
  version: number;
  updated_at: string | null;
}

export interface CandidateRecentRecruitment {
  job_id: number;
  job_title: string;
  client_id: number | null;
  client_name: string | null;
  latest_stage_id: number;
  stage: string;
  stage_label: string;
  last_activity_at: string;
}

export interface CandidateRecentRecruitmentsResponse {
  candidate_id: number;
  items: CandidateRecentRecruitment[];
}

function responseEtag(headers: Record<string, unknown>): string | null {
  const value = headers.etag ?? headers.ETag;
  return typeof value === "string" && value.trim() ? value : null;
}

/**
 * Deterministic, profile-wide candidate facts. The edit endpoints use ETags
 * instead of silent last-write-wins so a stale drawer cannot overwrite a
 * recruiter's newer correction.
 */
export const candidateFactsApi = {
  getLanguages: async (candidateId: number) => {
    const response = await api.get<CandidateLanguagesResponse>(
      `/api/candidates/${candidateId}/languages`,
    );
    return { data: response.data, etag: responseEtag(response.headers) };
  },
  updateLanguages: async (
    candidateId: number,
    languages: CandidateLanguageInput[],
    etag: string,
  ) => {
    const response = await api.put<CandidateLanguagesResponse>(
      `/api/candidates/${candidateId}/languages`,
      { languages },
      { headers: { "If-Match": etag } },
    );
    return { data: response.data, etag: responseEtag(response.headers) };
  },
  getProfileRate: async (candidateId: number) => {
    const response = await api.get<CandidateProfileRate>(
      `/api/candidates/${candidateId}/profile-rate`,
    );
    return { data: response.data, etag: responseEtag(response.headers) };
  },
  updateProfileRate: async (
    candidateId: number,
    amount: string | null,
    etag: string,
  ) => {
    const response = await api.patch<CandidateProfileRate>(
      `/api/candidates/${candidateId}/profile-rate`,
      { amount },
      { headers: { "If-Match": etag } },
    );
    return { data: response.data, etag: responseEtag(response.headers) };
  },
  getRecentRecruitments: (candidateId: number, limit = 5) =>
    api
      .get<CandidateRecentRecruitmentsResponse>(
        `/api/candidates/${candidateId}/recent-recruitments`,
        { params: { limit: Math.min(5, Math.max(1, limit)) } },
      )
      .then((response) => response.data),
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
  /** Admin „podgląd jako użytkownik": rozpoczyna sesję podglądu wskazanego
   *  usera. Zwraca jego autorytatywny profil (UserResponse) + zapisuje audyt.
   *  Faktyczna podmiana danych dzieje się przez nagłówek X-Impersonate-User-Id. */
  startImpersonation: (id: number) => api.post(`/api/admin/impersonate/${id}`),
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
  getSectionPermissions: () =>
    api.get<SectionPermissionsResponse>("/api/admin/section-permissions"),
  searchUserSectionPermissions: (search = "") =>
    api.get<UserSectionPermissionsResponse>(
      "/api/admin/section-permissions/users",
      { params: search.trim() ? { search: search.trim() } : undefined },
    ),
  updateRoleSectionPermissions: (
    revision: number,
    changes: RoleSectionPermissionChange[],
    actionChanges: RoleActionPermissionChange[] = [],
  ) =>
    api.put<SectionPermissionMutationResponse>(
      "/api/admin/section-permissions/roles",
      {
        revision,
        changes,
        ...(actionChanges.length > 0
          ? { action_changes: actionChanges }
          : {}),
      },
    ),
  updateUserSectionPermissions: (
    userId: number,
    revision: number,
    changes: UserSectionPermissionChange[],
    actionChanges: UserActionPermissionChange[] = [],
  ) =>
    api.put<SectionPermissionMutationResponse>(
      `/api/admin/section-permissions/users/${userId}`,
      {
        revision,
        changes,
        ...(actionChanges.length > 0
          ? { action_changes: actionChanges }
          : {}),
      },
    ),
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
  /**
   * Czy lista pytań jest KOMPLETNA. Gdy wyszukiwanie podobnych rekrutacji nie
   * odpowie, tier 4 (auto-generator) dolewa pytania jako bezpiecznik — kit
   * wygląda wtedy normalnie i po awarii nie ma żadnego śladu. Patrz #408.
   */
  degraded?: boolean;
  degraded_reason?: string | null;
  candidate_strengths: string[];
  candidate_gaps: string[];
  selling_points: string[];
  recommended_strategy: string;
}

export const prepKitApi = {
  // Generacja LLM — użytkownik czeka przy ekranie, więc 120 s zamiast
  // domyślnych 30 s instancji (patrz `lib/http-timeouts.ts`).
  generate: (job_id: number, candidate_id: number) =>
    api.post<PrepKitResponse>(
      "/api/prep-kit/generate",
      { job_id, candidate_id },
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
    ),
};

// ── AI Writer ─────────────────────────────────────────────────────────────────
export const aiWriterApi = {
  // Obie generacje idą do modelu, a formularz stoi otwarty i czeka na wynik —
  // stąd wspólny sufit 120 s (patrz `lib/http-timeouts.ts`).
  generateJobDescription: (data: {
    title: string;
    client_name?: string;
    requirements?: string;
    seniority?: string;
  }) =>
    api.post("/api/ai/generate-job-description", data, {
      timeout: SLOW_ENDPOINT_TIMEOUT_MS,
    }),

  generateJob: (data: {
    title: string;
    client?: string;
    seniority?: string;
    skills?: string[];
    description_hint?: string;
  }) =>
    api.post("/api/ai/generate-job", data, {
      timeout: SLOW_ENDPOINT_TIMEOUT_MS,
    }),
};

// ── AI Matching ───────────────────────────────────────────────────────────────
export const matchingApi = {
  // Returns ALL candidates that match the job (score >= backend threshold),
  // ranked best-first. Optional overrides: `minScore` (0-1), `limit`, and
  // `location` (restrict to candidates whose location matches this place —
  // falls back to the job's own location server-side when omitted).
  getMatches: (
    jobId: number,
    opts?: { minScore?: number; limit?: number; location?: string },
  ) =>
    api.get<{
      job_id: number;
      job_title: string;
      required_skills: string[];
      /**
       * Skąd wzięło się `required_skills` (0278): kolumna oferty →
       * Tier 0 Championa (sekcja „Stack") → narracja/JD Championa (wywiedzione)
       * → ostatni fallback, regex po treści wymagań. Opcjonalne dla parytetu
       * ze starszym backendem.
       */
      required_skills_source?:
        | "must_skills"
        | "champion_stack"
        | "champion_narrative"
        | "requirements_text";
      // Nice-to-have skill labels from the job's `nice_skills` JSON — drive the
      // "Mile widziane" column in the C2 workspace. Display-only (never scored).
      nice_skills?: string[];
      search_type: string;
      min_score: number | null;
      location_filter: string | null;
      /** Rubryki strony OFERTY (0278) — te same trzy, które dealbreakery
       *  egzekwują na wierszach poniżej. Opcjonalne dla parytetu ze starszym
       *  backendem. */
      rubrics?: {
        budget_hourly: number | null;
        onsite_days_per_week: number | null;
        office_location: string | null;
        must_skills: string[];
      };
      matches: Array<{
        candidate: {
          id: number;
          name: string;
          lastname: string;
          email?: string | null;
          location?: string | null;
          competence_category?: string | null;
          // C2 workspace: candidate hourly rate (compared with the job budget
          // in the dock), current role + company (row subtitle). Nullable.
          expected_rate_hourly?: number | null;
          expected_rate_currency?: string | null;
          expected_rate_unit?: "hour" | null;
          current_title?: string | null;
          current_company?: string | null;
        };
        match_score: number | null;
        matching_skills: string[];
        gaps: string[];
        // Nice-to-have coverage (parallel to matching_skills/gaps for must).
        nice_matching?: string[];
        nice_gaps?: string[];
        eligibility?: MatchEligibility | null;
        /** Rubryki 0278 na WIERSZU — status dealbreakerów dla TEGO kandydata,
         *  widoczny nawet gdy wiersz przetrwał tylko dzięki `warn`-exemption.
         *  Opcjonalne: starszy backend ich nie wysyła. */
        rate_fit?: "ok" | "over_budget" | "unknown";
        office_fit?:
          | "ok"
          | "days_exceeded"
          | "city_mismatch"
          | "unknown"
          | "not_required";
        /** Must-have z `rubrics.must_skills`, których TEMU kandydatowi brakuje
         *  — węższe niż `gaps` (to porównuje z `required_skills`, który bywa
         *  wywiedziony regexem; `missing_must` tylko z jawnym must bramki). */
        missing_must?: string[];
      }>;
      meta?: RecommendationMeta;
    }>(`/api/jobs/${jobId}/ai-matches`, {
      params: {
        min_score: opts?.minScore,
        limit: opts?.limit,
        location: opts?.location?.trim() || undefined,
      },
    }),
  // Hybrid AI match scores (0-100) for the candidates currently in a job's
  // pipeline — powers the score ring on kanban cards. Cache-first server-side.
  pipelineScores: (jobId: number) =>
    api.get<{
      job_id: number;
      profile_id: number;
      scores: Record<string, number>;
    }>(`/api/jobs/${jobId}/pipeline-scores`),
};

// ── AI scoring justification ("Dopasowanie" tab) ────────────────────────────
export interface MatchJustification {
  candidate_id: number;
  job_id: number;
  job_title: string | null;
  /** Hybrid composite score, 0-100 (same number the kanban ring shows). */
  score: number;
  /** "Podsumowanie" — prose verdict. */
  summary: string;
  /** "Może być dobrym wyborem, ponieważ" — positive bullets. */
  pros: string[];
  /** "Do weryfikacji / luki" — gaps and things to confirm. */
  watchouts: string[];
  /** Braki potwierdzone w notatkach rekruterskich, pokrywające się z
   * wymaganiami oferty. Liczone deterministycznie po stronie serwera
   * (nigdy przez LLM) — mogą być nieobecne na starszym backendzie. */
  notes_warnings?: Array<{ skill: string; evidence?: string | null }>;
  model: string | null;
  /** "Oceń ten scoring": -1 (down) / +1 (up) / null (not rated). */
  rating: number | null;
  rating_comment: string | null;
  generated_at: string | null;
}

export const matchScoringApi = {
  // AI justification of a candidate↔job match score. Cached per pair server-side;
  // `refresh: true` forces a fresh (paid) LLM generation.
  get: (candidateId: number, jobId: number, opts?: { refresh?: boolean }) =>
    api.get<MatchJustification>(
      `/api/candidates/${candidateId}/scoring/${jobId}`,
      {
        params: { refresh: opts?.refresh ? true : undefined },
        // `refresh: true` to ŚWIEŻA, płatna generacja Sonnetem — 30 s bywa za
        // mało, a zerwane połączenie i tak jest opłacone (http-timeouts.ts).
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      },
    ),
  // "Oceń ten scoring" feedback. rating: -1 | 0 (reset) | 1.
  feedback: (
    candidateId: number,
    jobId: number,
    body: { rating: number; comment?: string },
  ) =>
    api.post<MatchJustification>(
      `/api/candidates/${candidateId}/scoring/${jobId}/feedback`,
      body,
    ),
};

// ── AI activity summary ("Podsumowanie aktywności" card) ────────────────────
export interface CandidateActivitySummary {
  candidate_id: number;
  /** Krótka notatka AI; null = jeszcze nie wygenerowana. */
  summary: string | null;
  model: string | null;
  generated_at: string | null;
  /** Version of the exact, visibility-scoped source set used for this row. */
  source_version: string | null;
  /** Version calculated from the source set visible to the current user now. */
  current_source_version: string;
  is_stale: boolean;
  /** Opaque scope identifier. Never contains job ids or user-visible secrets. */
  visibility_scope_hash: string;
  source_manifest: {
    content_policy_version: string;
    sources: Array<{
      name: string;
      included_items: number;
      truncated_items: number;
      redacted_financial_fragments: number;
      redacted_instruction_fragments: number;
    }>;
  };
  /**
   * Tylko po refresh: false = historia bez zmian, zwrócono notatkę z cache
   * (bez płatnego wywołania AI).
   */
  refreshed?: boolean | null;
}

export const activitySummaryApi = {
  // Cached read — never triggers a paid generation (profile views stay free).
  get: (candidateId: number) =>
    api.get<CandidateActivitySummary>(
      `/api/candidates/${candidateId}/activity-summary`,
    ),
  // "Aktualizuj notatkę" — re-gathers history; regenerates only when it changed.
  // Gdy historia się zmieniła, to pełne wywołanie LLM pod kliknięciem
  // użytkownika — stąd 120 s (patrz `lib/http-timeouts.ts`).
  refresh: (candidateId: number) =>
    api.post<CandidateActivitySummary>(
      `/api/candidates/${candidateId}/activity-summary/refresh`,
      undefined,
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
    ),
};

// ── Talent Pools ──────────────────────────────────────────────────────────────
export const talentPoolsApi = {
  list: () => api.get("/api/talent-pools"),
  create: (data: {
    name: string;
    description?: string;
    criteria?: Record<string, unknown>;
    /** True = pula osobista (widoczna dla zespołu, zarządzana tylko przez Ciebie). */
    is_personal?: boolean;
  }) => api.post("/api/talent-pools", data),
  addCandidate: (poolId: number, candidateId: number) =>
    api.post(`/api/talent-pools/${poolId}/add`, { candidate_id: candidateId }),
  removeCandidate: (poolId: number, candidateId: number) =>
    api.delete(`/api/talent-pools/${poolId}/remove/${candidateId}`),
  deletePool: (poolId: number) => api.delete(`/api/talent-pools/${poolId}`),
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
  /** Próg alertowania z backendu. NIE hardkoduj go w UI — do 2026-07-28 dwa
   *  miejsca mówiły „≥ 70", a `MARKETPLACE_SCORE_THRESHOLD` był 80. */
  score_threshold: number;
}

export const marketplaceApi = {
  getPool: () => api.get<MarketplacePoolMeta>("/api/marketplace/pool"),
  list: (params?: {
    page?: number;
    page_size?: number;
    q?: string;
    source_event?: "manual" | "auto_availability";
  }) =>
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

/**
 * Liczniki sześciu filtrów „Szybkie" w lewej kolumnie listy rekrutacji.
 *
 * GLOBALNE — dotyczą całej bazy w zakresie widoczności użytkownika, nie
 * wczytanej strony. Każdy liczony tym samym predykatem, co odpowiadający mu
 * filtr listy (`jobs_*_clause` w `backend/app/api/jobs.py`).
 */
export interface JobQuickCounts {
  mine: number;
  open: number;
  needs_sourcing: number;
  active_in_search: number;
  owner_missing: number;
  deadline_7d: number;
}

export const jobsApi = {
  list: (params?: Record<string, unknown>) => api.get("/api/jobs", { params }),
  /**
   * `deadline_from`/`deadline_to` przekazuje WOŁAJĄCY — lista wysyła dokładnie
   * to okno, którego używa jej własny preset „Najbliższe 7 dni". Liczone tu po
   * stronie serwera mogłoby wypaść o dzień inaczej niż w przeglądarce
   * użytkownika (strefa czasowa), a licznik ma zgadzać się z listą co do
   * wiersza.
   */
  quickCounts: (params?: { deadline_from?: string; deadline_to?: string }) =>
    api.get<JobQuickCounts>("/api/jobs/quick-counts", { params }),
  get: (id: number) => api.get(`/api/jobs/${id}`),
  create: (data: Record<string, unknown>) => api.post("/api/jobs", data),
  update: (id: number, data: Record<string, unknown>) => api.patch(`/api/jobs/${id}`, data),
  delete: (id: number) => api.delete(`/api/jobs/${id}`),
  /** "Przekaż do searchu" — DL assigns a recruiter and starts the ranking.
   *  422 body carries `{ message, blockers: string[] }` when the recruitment
   *  is not ready (Champion required). */
  handoff: (id: number, recruiterId: number, topK?: number, channel: "linkedin" | "database" | "mixed" = "linkedin") =>
    api.post(`/api/jobs/${id}/handoff`, {
      recruiter_id: recruiterId,
      channel,
      ...(topK ? { top_k: topK } : {}),
    }),
  /**
   * Zamknięcie rekrutacji z powodem (`TacPlus`). Powody i etykiety PL —
   * `JOB_CLOSE_REASONS` w `types/client-profile`. Drugim konsumentem tej trasy
   * jest „Zamknij jako przegraną" w profilu klienta; ten helper istnieje, żeby
   * krok 08 nie wołał surowego `api.post` obok niego.
   */
  close: (id: number, reason: string, notes?: string | null) =>
    api.post(`/api/jobs/${id}/close`, {
      reason,
      notes: notes?.trim() || null,
    }),
};

// ── Werdykt hiring managera (krok 07 „Rozmowy i decyzja") ────────────────────
//
// Lustro `POST|GET /api/jobs/{id}/hiring-manager-feedback`
// (`backend/app/api/hiring_manager_feedback.py`). Endpoint zapisuje TO, CO
// MANAGER POWIEDZIAŁ — nie tworzy weta. Weto powstaje dopiero przy terminalnym
// ruchu z powodem oznaczonym `disqualifies_person`, dlatego odpowiedź niesie
// trzy różne pola zamiast jednego „zablokowany".
export type HiringManagerDecision = "advance" | "reject" | "on_hold";

export interface HiringManagerFeedbackPayload {
  candidate_id: number;
  decision: HiringManagerDecision;
  rejection_reason_id?: number | null;
  note?: string | null;
  technical_fit?: number | null;
  soft_fit?: number | null;
  overall_fit?: number | null;
}

export interface HiringManagerFeedback {
  id: number;
  job_id: number;
  candidate_id: number;
  decision: HiringManagerDecision | "";
  rejection_reason_id: number | null;
  rejection_reason_name: string | null;
  note: string | null;
  technical_fit: number | null;
  soft_fit: number | null;
  overall_fit: number | null;
  hiring_manager_contact_id: number | null;
  hiring_manager_name: string | null;
  /** Czy WYBRANY POWÓD w ogóle może zablokować kolejne propozycje. */
  blocks_future_proposals: boolean;
  /** Czy weto już STOI (kandydat odrzucony takim powodem na tej rekrutacji). */
  veto_recorded: boolean;
  /** Czego brakuje, żeby weto stanęło — po polsku, gotowe do wyświetlenia. */
  veto_blockers: string[];
}

export const hiringManagerFeedbackApi = {
  list: (jobId: number) =>
    api
      .get<HiringManagerFeedback[]>(`/api/jobs/${jobId}/hiring-manager-feedback`)
      .then((r) => r.data),
  record: (jobId: number, payload: HiringManagerFeedbackPayload) =>
    api
      .post<HiringManagerFeedback>(
        `/api/jobs/${jobId}/hiring-manager-feedback`,
        payload,
      )
      .then((r) => r.data),
};

// ── Calendar ──────────────────────────────────────────────────────────────────
export interface CalendarEventResponse {
  id: number;
  title: string;
  description: string | null;
  event_type: string;
  start_time: string;
  end_time: string | null;
  all_day: boolean;
  candidate_id: number | null;
  candidate_name: string | null;
  job_id: number | null;
  job_title: string | null;
  client_id: number | null;
  client_name: string | null;
  attendees: Array<{ address: string }> | null;
  location: string | null;
  teams_link: string | null;
  online_meeting_url: string | null;
  recording_url: string | null;
  created_by: number | null;
  reminder_minutes: number;
  status: string;
  created_at: string | null;
}

export const calendarApi = {
  listEvents: (params?: {
    from_date?: string;
    to_date?: string;
    event_type?: string;
    status?: string;
    mine_only?: boolean;
    limit?: number;
  }) => api.get("/api/calendar/events", { params }),
  createEvent: (data: Record<string, unknown>) => api.post("/api/calendar/events", data),
  getEvent: (id: number) => api.get(`/api/calendar/events/${id}`),
  updateEvent: (id: number, data: Record<string, unknown>) =>
    api.patch(`/api/calendar/events/${id}`, data),
  deleteEvent: (id: number) => api.delete(`/api/calendar/events/${id}`),
  // Phase 5.4 — overlap check used by ScheduleInterviewModal before booking.
  conflicts: (params: {
    start: string;
    end: string;
    exclude_event_id?: number;
    user_id?: number;
  }) => api.get("/api/calendar/conflicts", { params }),
  conflictsSummary: (params: {
    start: string;
    end: string;
    user_id?: number;
  }) => api.get("/api/calendar/conflicts-summary", { params }),
};

// ── Notifications ─────────────────────────────────────────────────────────────
export interface NotificationResponse {
  id: number;
  user_id: number;
  title: string;
  message: string;
  link: string | null;
  notification_type: string;
  is_read: boolean;
  created_at: string | null;
}

export interface NotificationListResponse {
  items: NotificationResponse[];
  unread_count: number;
}

export const notificationsApi = {
  list: (limit?: number) =>
    api.get<NotificationListResponse>("/api/notifications", {
      params: limit ? { limit } : undefined,
    }),
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

// Konsolidacja kontraktorów wieloklientowych: jedna umowa w zgrupowanym
// wierszu listy (`group_by_candidate=true`) — rozbicie okresu/stawek per
// klient. Kwoty przychodzą zredagowane (null) dla ról bez VIEW_FINANCE.
export interface ContractGroupMember {
  id: number;
  client_id: number;
  client_name: string | null;
  status: "draft" | "ready_for_signature" | "active" | "ending" | "ended" | "void";
  contract_type: "b2b" | "uop" | "uzlecenie";
  start_date: string | null;
  end_date: string | null;
  latest_order_end_date: string | null;
  job_title: string | null;
  rate_candidate: number | null;
  rate_client: number | null;
  margin: number | null;
  rate_unit: "hourly" | "daily" | "monthly" | null;
  currency: string | null;
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
}

// Inny kontrakt tej samej osoby (szczegóły kontraktu → zakładki per klient).
export interface ContractSiblingRef {
  id: number;
  client_id: number;
  client_name: string | null;
  status: "draft" | "ready_for_signature" | "active" | "ending" | "ended" | "void";
  contract_type: "b2b" | "uop" | "uzlecenie";
  start_date: string | null;
  end_date: string | null;
}

export const contractsApi = {
  list: (params?: Record<string, unknown>) => api.get("/api/contracts", { params }),
  get: (id: number) => api.get(`/api/contracts/${id}`),
  create: (data: Record<string, unknown>) => api.post("/api/contracts", data),
  update: (id: number, data: Record<string, unknown>) => api.patch(`/api/contracts/${id}`, data),
  updateStatus: (id: number, status: string) =>
    api.patch(`/api/contracts/${id}/status`, { status }),
  delete: (id: number) => api.delete(`/api/contracts/${id}`),
  forceDeleteSigned: (id: number, confirmation: string) =>
    api.post(`/api/contracts/${id}/force-delete-signed`, { confirmation }),
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

export type ContractorStatus =
  | "draft"
  | "ready_for_signature"
  | "active"
  | "ending";

export interface ContractorCandidateRef {
  id: number;
  name: string;
  lastname: string;
  email?: string | null;
}

export interface ContractorListItem {
  contract_id: number;
  candidate: ContractorCandidateRef;
  /** Potrzebny akcji „Zakończ projekt" (invalidacje cache per-klient). */
  client_id?: number | null;
  client_name?: string | null;
  job_title?: string | null;
  status: ContractorStatus;
  start_date: string;
  end_date?: string | null;
  rate_candidate?: number | null;
  rate_client?: number | null;
  rate_unit: "hourly" | "daily" | "monthly";
  currency?: string;
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
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
  active_contracts: number;
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
  total_active_contracts: number;
  role_totals: Record<string, number>;
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

// ── Cortex (central intelligence — skill-fact store) ─────────────────────────

export interface CortexTechMapCell {
  skill: string;
  seniority: "junior" | "mid" | "senior" | "unknown";
  count: number;
}

export interface CortexTechMap {
  cells: CortexTechMapCell[];
  skills: string[];
  seniorities: string[];
  candidates_covered: number;
  candidates_total: number;
  fill_rate_pct: number;
  /** Per-source distinct-candidate counts that MAY OVERLAP (a candidate present
   *  in two sources counts in both) — never sum these for a headline. */
  sources: Record<string, number>;
  /** TRUE per-skill total (distinct candidates), NOT filtered by min_count and
   *  NOT the sum of visible cells — use for the "Σ" column. */
  skill_totals: Record<string, number>;
  /** Canonical skill name → skill id for the visible skills — enables drill-down
   *  from a heatmap cell (the heatmap works on names, drill-down needs the id). */
  skill_ids: Record<string, number>;
  /** Active employment filter echoed back by the backend (null = all). */
  employment: string | null;
  /** ISO timestamp of the freshest underlying fact (null = unknown). */
  data_as_of: string | null;
  min_count: number;
}

export interface CortexCoverage {
  candidates: {
    total: number;
    with_cv_file: number;
    with_cv_file_pct: number;
    with_raw_cv_text: number;
    with_raw_cv_text_pct: number;
    with_traffit_tech: number;
    with_traffit_tech_pct: number;
    with_any_fact: number;
    with_any_fact_pct: number;
    availability_known: number;
    availability_known_pct: number;
  };
  facts: {
    by_source: Record<string, { facts: number; candidates: number }>;
    freshness: Record<"lt_1y" | "y1_3" | "gt_3y" | "unknown", number>;
  };
  processes: {
    jobs_closed: number;
    jobs_closed_with_reason: number;
    jobs_close_reason_pct: number;
    contracts_ended: number;
    contracts_ended_with_reason: number;
    contracts_natural_expiry: number;
  };
  unmatched_terms: CortexUnmatchedTerm[];
  /** ISO timestamp of the freshest underlying fact (null = unknown). */
  data_as_of: string | null;
}

export interface CortexUnmatchedTerm {
  /** Row id — needed by the admin curation actions (map/ignore). Both
   *  `/unmatched-terms` and `coverage.unmatched_terms` serialize it. */
  id: number;
  term: string;
  occurrences: number;
  status: "new" | "mapped" | "ignored";
  last_seen_at: string | null;
}

// ── Cortex Action Layer (Etap 1): drill-down, search, client×stack, successors ──

export interface CortexSkillListItem {
  id: number;
  canonical_name: string;
  category: string | null;
  candidates: number;
}

export interface CortexSkillList {
  skills: CortexSkillListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface CortexSkillCandidate {
  id: number;
  name: string;
  lastname: string;
  availability_status: string | null;
  seniority: string;
  confidence: number;
  level: string | null;
  years: number | null;
  evidence: string | null;
  sources: string[];
  at_client: boolean;
  observed_at: string | null;
  /** Freshness bucket of the strongest fact: lt_1y | y1_3 | gt_3y | unknown. */
  freshness: string;
}

export interface CortexSkillCandidates {
  candidates: CortexSkillCandidate[];
  total: number;
  limit: number;
  offset: number;
}

export interface CortexClientStackCell {
  client_id: number;
  client: string;
  skill: string;
  count: number;
}

export interface CortexClientStackClient {
  id: number;
  name: string;
  consultants: number;
}

export interface CortexClientStack {
  cells: CortexClientStackCell[];
  clients: CortexClientStackClient[];
  min_count: number;
}

export interface CortexSuccessorCandidate {
  id: number;
  name: string;
  lastname: string;
  availability_status: string | null;
  /** Number of overlapping skills with the departing consultant. */
  overlap: number;
}

export interface CortexEndingContract {
  contract_id: number;
  candidate_id: number;
  candidate_name: string | null;
  candidate_lastname: string | null;
  client_id: number;
  client_name: string | null;
  end_date: string | null;
  skill_count: number;
  successors: CortexSuccessorCandidate[];
}

export interface CortexSuccessors {
  days: number;
  ending_contracts: CortexEndingContract[];
}

export interface CortexCreatedSkill {
  id: number;
  canonical_name: string;
  mapped_term: string | null;
}

/** Multi-value seniority filter for the drill-down. */
export type CortexSeniority = "junior" | "mid" | "senior" | "unknown";

export interface CortexBackfillStatus {
  running: boolean;
  total: number;
  processed: number;
  facts_upserted: number;
  unmatched_tokens: number;
  errors: number;
  started_at: string | null;
  finished_at: string | null;
  limit: number | null;
  last_error: string | null;
}

// ── Cortex Intelligence Layer (Etap 2): supply/demand, resolved skills, ──────
//    title normalization, CV-LLM extraction backfill.

export interface CortexSupplyDemandSkill {
  skill: string;
  /** Distinct candidates with a fact for the skill. */
  supply: number;
  /** Open jobs that require the skill. */
  demand: number;
  /** demand − supply; positive = shortage ("niedobór"). */
  gap: number;
}

export interface CortexSupplyDemand {
  /** Already sorted by gap desc (biggest shortage first). */
  skills: CortexSupplyDemandSkill[];
  open_jobs: number;
  only_must: boolean;
}

/** One resolved fact per skill, picked by source precedence × freshness. */
export interface CortexResolvedSkill {
  skill_id: number;
  skill: string;
  source: string;
  effective_confidence: number;
  level: string | null;
  years: number | null;
  observed_at: string | null;
}

export interface CortexResolvedSkills {
  candidate_id: number;
  skills: CortexResolvedSkill[];
}

export interface CortexNormalizedTitle {
  title: string;
  seniority: string | null;
  technologies: string[];
}

export interface CortexCvLlmStatus {
  running: boolean;
  status: string;
  run_id?: number;
  source?: string;
  total: number;
  processed: number;
  facts_upserted: number;
  errors: number;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  /** FALSE when CORTEX_CV_LLM_ENABLED=false → trigger returns 503. */
  enabled: boolean;
}

export interface CortexCvLlmTrigger {
  status: string;
  run_id: number;
  /** Echoed back; null when no cap was passed. */
  limit: number | null;
}

export const cortexApi = {
  techMap: (params: {
    source?: string;
    employment?: string;
    min_count?: number;
  }) => api.get<CortexTechMap>("/api/cortex/tech-map", { params }),
  coverage: () => api.get<CortexCoverage>("/api/cortex/coverage"),
  unmatchedTerms: (params?: {
    status?: "new" | "mapped" | "ignored" | "all";
    limit?: number;
  }) =>
    api.get<CortexUnmatchedTerm[]>("/api/cortex/unmatched-terms", {
      params: { status: params?.status ?? "new", limit: params?.limit ?? 100 },
    }),
  triggerTraffitBackfill: (limit?: number) =>
    api.post("/api/cortex/admin/backfill-traffit", null, {
      params: limit ? { limit } : {},
    }),
  traffitBackfillStatus: () =>
    api.get<CortexBackfillStatus>("/api/cortex/admin/backfill-traffit/status"),

  // ── Action Layer (Etap 1) ──────────────────────────────────────────────────
  /** Full, searchable, paginated skill list (replaces the top-40 heatmap cap). */
  skills: (params?: {
    q?: string;
    source?: string;
    limit?: number;
    offset?: number;
  }) => api.get<CortexSkillList>("/api/cortex/skills", { params }),
  /** Drill-down: concrete candidates who have a fact for `skillId`. */
  skillCandidates: (
    skillId: number,
    params?: {
      seniority?: string[];
      source?: string;
      employment?: "at_client" | "available";
      min_confidence?: number;
      limit?: number;
      offset?: number;
    },
  ) =>
    api.get<CortexSkillCandidates>(`/api/cortex/skill/${skillId}/candidates`, {
      params,
      // FastAPI `Query(list)` needs repeated `seniority=a&seniority=b` — the
      // axios default bracket form (`seniority[]=a`) is NOT parsed as a list.
      paramsSerializer: { indexes: null },
    }),
  /** Matrix client × skill × #consultants embedded at the client. */
  clientStack: (params?: { client_id?: number; min_count?: number }) =>
    api.get<CortexClientStack>("/api/cortex/client-stack", { params }),
  /** Ending contracts within `days` and their available successors. */
  successors: (days = 30) =>
    api.get<CortexSuccessors>("/api/cortex/successors", { params: { days } }),

  // ── Curation (admin-only) ──────────────────────────────────────────────────
  mapTerm: (termId: number, skillId: number) =>
    api.post(`/api/cortex/unmatched-terms/${termId}/map`, {
      skill_id: skillId,
    }),
  ignoreTerm: (termId: number) =>
    api.post(`/api/cortex/unmatched-terms/${termId}/ignore`),
  createSkill: (payload: {
    canonical_name: string;
    category?: string;
    aliases?: string[];
    from_term_id?: number;
  }) => api.post<CortexCreatedSkill>("/api/cortex/skills", payload),
  addAlias: (skillId: number, alias: string) =>
    api.post(`/api/cortex/skills/${skillId}/aliases`, { alias }),

  // ── Intelligence Layer (Etap 2) ─────────────────────────────────────────────
  /** Supply (candidates) vs demand (open jobs) per skill, sorted by gap desc. */
  supplyDemand: (only_must?: boolean) =>
    api.get<CortexSupplyDemand>("/api/cortex/supply-demand", {
      params: only_must != null ? { only_must } : {},
    }),
  /** One resolved fact per skill for a candidate (source precedence × freshness). */
  resolvedSkills: (candidateId: number) =>
    api.get<CortexResolvedSkills>(
      `/api/cortex/candidate/${candidateId}/resolved-skills`,
    ),
  /** Normalize a free-text job title → seniority + technologies. */
  normalizeTitle: (title: string) =>
    api.get<CortexNormalizedTitle>("/api/cortex/normalize-title", {
      params: { title },
    }),
  /** Admin-only CV-LLM extraction backfill. 503 when disabled, 409 if running. */
  triggerCvLlmBackfill: (params?: { limit?: number; only_active?: boolean }) =>
    api.post<CortexCvLlmTrigger>("/api/cortex/admin/backfill-cv-llm", null, {
      params: params ?? {},
    }),
  cvLlmStatus: () =>
    api.get<CortexCvLlmStatus>("/api/cortex/admin/backfill-cv-llm/status"),
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
  /**
   * Whether this reason is a verdict about the *person*. Only flagged reasons
   * block re-submitting a candidate to the hiring manager who rejected them.
   */
  disqualifies_person: boolean;
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
  updateRejectionReason: (
    id: number,
    reasonId: number,
    data: { name?: string; order?: number; active?: boolean; disqualifies_person?: boolean }
  ) =>
    api.patch<RejectionReasonDef>(
      `/api/pipeline-templates/${id}/rejection-reasons/${reasonId}`,
      data
    ),
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
  listMyPendingVerifications: () =>
    api.get<PendingVerificationItem[]>("/api/pipeline/pending-verifications", {
      params: { mine: true },
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
  /**
   * Phase 14: bonus za obecność kandydata w semantycznie podobnych
   * historycznych projektach. Wchodzi do `total`, więc MUSI być widoczny w
   * rozbiciu — inaczej suma warstw nie zgadza się z totalem (M3-SCORE-01).
   */
  historical_boost?: number;
  historical_sources_count?: number;
  fit_confidence?: number;
}

export interface CandidateMatch {
  candidate: {
    id: number;
    name: string;
    lastname: string;
    email: string | null;
    location: string | null;
    champion: boolean;
    years_it_experience: number | null;
    competence_category: string | null;
    tags?: unknown;
    skills?: unknown;
    ai_summary?: string | null;
    avatar_url?: string | null;
  };
  /**
   * Null when semantic retrieval is unavailable and the backend returns an
   * explicitly degraded lexical (BM25) ranking.  A lexical rank is not a
   * calibrated 0-100 match score and must not be presented as one.
   */
  total_score: number | null;
  breakdown?: ScoreBreakdown | null;
}

/**
 * Dealbreaker-switche: pięć rubryk-powodów, dla których kandydat mógł zostać
 * ukryty (0278: must-have / dni w biurze / miasto biura dołączają do
 * istniejących budżetu i „wyłącznie zdalnie"). Kolejność jest tu tylko
 * deklaratywna — backend liczy je w STAŁEJ kolejności (budżet → must-have →
 * dni → miasto → zdalnie), pierwszy pasujący powód wygrywa.
 */
export type HiddenReason =
  | "over_budget"
  | "missing_must"
  | "office_days_exceeded"
  | "office_city_mismatch"
  | "remote_only";

/** `meta.hidden` / `snapshot.hidden` — liczniki per powód, wszystkie opcjonalne
 *  (starszy backend albo snapshot sprzed 0237/0278 może nie znać części kluczy). */
export type HiddenCounters = Partial<Record<HiddenReason, number>>;

/** Etykiety PL renderowane jako chipy „Ukryto N — <etykieta>" wszędzie tam,
 *  gdzie `meta.hidden`/`snapshot.hidden` się pojawia — ukrywanie nigdy nie
 *  jest ciche (reguła „awaria ≠ pustka"). */
export const HIDDEN_LABELS_PL: Record<HiddenReason, string> = {
  over_budget: "powyżej budżetu oferty",
  missing_must: "bez technologii must-have",
  office_days_exceeded: "za mało dni w biurze",
  office_city_mismatch: "inne miasto niż biuro",
  remote_only: "tylko-zdalnych",
};

/** Suma wszystkich liczników ukrytych, niezależnie od tego, ile rubryk backend
 *  akurat zna — `undefined`/`null` liczy się jako zero na każdym kluczu. */
export function hiddenTotal(hidden?: HiddenCounters | null): number {
  if (!hidden) return 0;
  return (Object.keys(HIDDEN_LABELS_PL) as HiddenReason[]).reduce(
    (sum, reason) => sum + (hidden[reason] ?? 0),
    0,
  );
}

export interface RecommendationMeta {
  mode: string;
  degraded: boolean;
  reason: string | null;
  index_version?: string | null;
  scoring_version?: string | null;
  /** Dealbreaker-switche: liczniki ukrytych per powód (0278: pięć rubryk). */
  hidden?: HiddenCounters;
  /**
   * Ilu kandydatów odsiała bramka dopuszczalności (blacklista klienta / NDA /
   * konflikt / weto). P-B (decyzja Artura, 2026-09-03): publikowane w /ai-matches
   * mimo tradeoffu „wyroczni na NDA" — mirror Talent Radaru (`eligible_size`).
   */
  eligibility_filtered?: number;
  /**
   * Operacyjny (kandydacki) budżet godzinowy oferty — ten sam sufit, który
   * bramka egzekwuje jako `over_budget`. Warsztat C2 pokazuje go w pasku
   * kontekstu i porównuje z nim stawki w doku. `null`, gdy oferta nie ma
   * budżetu godzinowego (wtedy stawki nie są kolorowane).
   */
  budget_hourly?: number | null;
}

/**
 * Anotacja dopuszczalności na wierszu rankingu (`/ai-matches`). Obecna tylko dla
 * kandydatów, których dopuszczalność nie jest „czysta": `warn` (aktywny konflikt
 * klienta / NDA / konkurent / weto hiring managera) — pokazywani z powodem
 * i `assignment_allowed=false` — oraz miękkie ostrzeżenia (`current_employment`,
 * `excluded_client`). Kandydaci `hidden` (globalna blacklista, duplikat) nie
 * trafiają na listę w ogóle, więc nigdy nie mają tej anotacji. `reason` jest
 * gotową polską etykietą z `_REASON_LABELS_PL`.
 */
export interface MatchEligibility {
  reason_code: string;
  reason: string;
  assignment_allowed: boolean;
  visibility: "visible" | "warn" | "hidden";
  severity: "warning" | "blocking" | string;
  secondary: string[];
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
  total_score: number | null;
  breakdown?: ScoreBreakdown | null;
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
  // Saved-search alerts (V1): bell subscription + unseen badge. The scanner
  // needs `filters.api` (output of filtersToApiParams) stored next to the
  // classic `filters.qs` — the menu writes both on create/toggle.
  notify_new_matches: boolean;
  requires_reapproval: boolean;
  unseen_count: number;
  last_viewed_at: string | null;
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
    notify_new_matches?: boolean;
  }) => api.post<SavedSearchRow>("/api/saved-searches", data),
  update: (
    id: number,
    data: Partial<{
      name: string;
      filters: Record<string, unknown>;
      shared: boolean;
      description: string;
      notify_new_matches: boolean;
      confirm_reapproval: boolean;
    }>,
  ) => api.patch<SavedSearchRow>(`/api/saved-searches/${id}`, data),
  delete: (id: number) => api.delete(`/api/saved-searches/${id}`),
  // Resets the unseen badge + rolls last_viewed_at forward; returns the
  // PREVIOUS last_viewed_at — the list highlights rows created after it.
  markViewed: (id: number) =>
    api.post<{ previous_viewed_at: string | null }>(
      `/api/saved-searches/${id}/viewed`,
    ),
};

// ── Candidate Pins (Phase 4 — short-list workflow) ─────────────────────────

export interface CandidatePinBrief {
  id: number;
  name: string | null;
  lastname: string | null;
  email: string | null;
  avatar_url: string | null;
}

export interface CandidatePinRow {
  id: number;
  candidate_id: number;
  note: string | null;
  pinned_at: string;
  candidate: CandidatePinBrief;
}

export interface CandidatePinToggleResponse {
  pinned: boolean;
  pin: CandidatePinRow | null;
}

// ── Generator Umów B2B ────────────────────────────────────────────────────────

export interface B2BRole {
  id: number;
  category_key: string;
  category_label_pl: string;
  category_label_en: string;
  slug: string;
  name_pl: string;
  name_en: string;
  area_label_pl: string;
  area_label_en: string;
  scope_pl: string[];
  scope_en: string[];
  display_order: number;
  is_active: boolean;
}

/** Jeden etap „stawki progresywnej" (kwota + „Obowiązuje od/do"). */
export interface B2BRateStage {
  rate: number;
  effective_from?: string | null;
  effective_to?: string | null;
}

export interface B2BGeneratePayload {
  candidate_id?: number;
  client_id?: number;
  job_id?: number;
  contract_id?: number;
  role_id: number;
  language: string;
  contract_number?: string | null;
  signing_date?: string | null;
  start_date: string;
  project_city?: string | null;
  project_description?: string | null;
  correspondence_address?: string | null;
  rate_candidate?: number | null;
  currency: string;
  rate_in_words?: string | null;
  // Stawka progresywna — null/brak = pojedyncza stawka z `rate_candidate`.
  rate_stages?: B2BRateStage[] | null;
  scope_items_override?: string[] | null;
}

export interface B2BGenerateResult {
  contract_id: number;
  draft_template_id: number | null;
  language: string;
}

// ── In-house QES signing (drop Autenti) ─────────────────────────────────────
export interface SignForSignatureResult {
  signature_id: number;
  contract_id: number;
  status: string;
  sign_url: string;
}

export const signingApi = {
  sendForSignature: (
    contractId: number,
    body?: {
      provider?: "szafir_sdk" | "mszafir_oneshot" | "upload_validate";
      signature_type?: "SES" | "AdES" | "QES";
      expires_in_days?: number;
      company_signer_user_id?: number;
      message_pl?: string;
    },
  ) =>
    api
      .post<SignForSignatureResult>(
        `/api/signing/contracts/${contractId}/send-for-signature`,
        body ?? {},
      )
      .then((r) => r.data),
  listSignatures: (contractId: number) =>
    api
      .get(`/api/signing/contracts/${contractId}/signatures`)
      .then((r) => r.data),
  // Offline (e-mail) flow: record the contract as sent → pipeline "Umowa wysłana".
  markSentOffline: (contractId: number) =>
    api
      .post(`/api/signing/contracts/${contractId}/mark-sent-offline`, {})
      .then((r) => r.data),
  // Offline (e-mail) flow: recruiter uploads a signed PDF → validate. Moves to
  // "Umowa podpisana", or "Zatrudniony" when both parties signed (>=2 sigs).
  uploadSigned: (contractId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api
      .post<{
        status: string;
        is_qes: boolean;
        signature_level: string | null;
        signed_by: string | null;
        indication: string | null;
        dss_verified: boolean;
        signature_count: number | null;
        signers: string[];
        both_parties_signed: boolean;
        pipeline_stage: string;
      }>(`/api/signing/contracts/${contractId}/upload-signed`, form, {
        // Bez jawnego multipartu axios serializuje FormData do JSON-a
        // (instancja `api` ma domyślne application/json) → backend widzi puste
        // ciało i odpowiada 422 „file Field required", czyli podpisana umowa
        // nigdy nie przechodzi na „Umowa podpisana".
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },
};

export interface B2BRenderPayload {
  candidate_id?: number | null;
  job_id?: number | null;
  role_id?: number | null;
  language: string;
  gender?: string;
  partner_name?: string | null;
  partner_instrumental?: string | null;
  partner_legal_name?: string | null;
  partner_business_address?: string | null;
  partner_correspondence_address?: string | null;
  partner_nip?: string | null;
  /**
   * Typ podmiotu rozpoznany przez rejestr przy lookupie NIP-u. Steruje
   * WYŁĄCZNIE tym, czy lista pokazuje drugą linię z osobą kontaktową — treść
   * dokumentu jest od tego niezależna. Backend zapisuje to jako snapshot
   * i nie przelicza później.
   */
  partner_entity_type?: "sole_trader" | "company" | null;
  partner_regon?: string | null;
  partner_email?: string | null;
  partner_phone?: string | null;
  client_name?: string | null;
  project_city?: string | null;
  project_description?: string | null;
  contract_number?: string | null;
  signing_date?: string | null;
  start_date?: string | null;
  start_date_mode?: string;
  rate_candidate?: number | null;
  // Stawka progresywna — null/brak = pojedyncza stawka z `rate_candidate`.
  rate_stages?: B2BRateStage[] | null;
  currency: string;
  scope_items_override?: string[] | null;
}

export const b2bGeneratorApi = {
  roles: (includeInactive = false) =>
    api
      .get<B2BRole[]>("/api/b2b-generator/roles", {
        params: includeInactive ? { include_inactive: true } : undefined,
      })
      .then((r) => r.data),
  updateRole: (id: number, body: Partial<B2BRole>) =>
    api.patch<B2BRole>(`/api/b2b-generator/roles/${id}`, body).then((r) => r.data),
  generate: (body: B2BGeneratePayload) =>
    api
      .post<B2BGenerateResult>("/api/b2b-generator/generate", body)
      .then((r) => r.data),
  docxBlob: (contractId: number, language: string) =>
    api.get(`/api/b2b-generator/contracts/${contractId}/docx`, {
      params: { language },
      responseType: "blob",
    }),
  nextNumber: () =>
    api
      .get<{ contract_number: string; year: number; seq: number }>(
        "/api/b2b-generator/next-number",
      )
      .then((r) => r.data),
  renderDocx: (body: B2BRenderPayload) =>
    api.post("/api/b2b-generator/render", body, {
      params: { format: "docx" },
      responseType: "blob",
    }),
  renderHtml: (body: B2BRenderPayload) =>
    api
      .post<{ html: string; contract_number: string | null }>(
        "/api/b2b-generator/render",
        body,
        { params: { format: "html" } },
      )
      .then((r) => r.data),
  companyLookup: (params: { nip?: string; krs?: string }) =>
    api
      .get<{
        name: string | null;
        person: string | null;
        nip: string | null;
        regon: string | null;
        krs: string | null;
        address: string | null;
        source: string | null;
        // Gotowa klasyfikacja z backendu, nie `source`/`krs` do interpretacji
        // tutaj: `source` przychodzi w czterech niespójnych formatach, a wiedzę
        // o obu rejestrach jednocześnie ma tylko warstwa serwisowa.
        entity_type: "sole_trader" | "company" | null;
      }>("/api/b2b-generator/company-lookup", { params })
      .then((r) => r.data),
  clientsLookup: () =>
    api
      .get<{ id: number; name: string }[]>("/api/clients-lookup", {
        // „na razie" tylko wyselekcjonowane nazwy (klienci z display_name)
        params: { featured: true },
      })
      .then((r) => r.data),
  generated: (limit = 50, params: B2BGeneratedListParams = {}) =>
    api
      .get<B2BGeneratedContractRow[]>("/api/b2b-generator/generated", {
        // Wyszukiwanie i filtr statusu liczy backend (nie filtrujemy pobranych
        // `limit` wierszy w przeglądarce) — inaczej fraza nie znalazłaby umów
        // spoza widocznej strony listy.
        params: {
          limit,
          ...(params.q?.trim() ? { q: params.q.trim() } : {}),
          ...(params.contractStatus?.length
            ? { contract_status: params.contractStatus }
            : {}),
          ...(params.closureReason
            ? { closure_reason: params.closureReason }
            : {}),
          ...(params.startFrom ? { start_from: params.startFrom } : {}),
          ...(params.startTo ? { start_to: params.startTo } : {}),
          ...(params.jobId ? { job_id: params.jobId } : {}),
        },
        // `repeat`, nie domyślny `brackets`: FastAPI czyta listę wyłącznie jako
        // powtórzony parametr. Axios domyślnie wysłałby `contract_status[]=…`,
        // co po stronie serwera jest INNĄ nazwą pola — filtr po cichu nie
        // zadziałałby i zakładka pokazałaby pełną listę umów.
        paramsSerializer: { indexes: null },
      })
      .then((r) => r.data),
  statusHistory: (id: number) =>
    api
      .get<B2BStatusEvent[]>(
        `/api/b2b-generator/generated/${id}/status-history`,
      )
      .then((r) => r.data),
  updateGenerated: (id: number, body: B2BGeneratedContractUpdate) =>
    api
      .patch<B2BGeneratedContractRow>(
        `/api/b2b-generator/generated/${id}`,
        body,
      )
      .then((r) => r.data),
  deleteGenerated: (id: number) =>
    api.delete(`/api/b2b-generator/generated/${id}`).then((r) => r.data),
  downloadGenerated: (id: number) =>
    api.get(`/api/b2b-generator/generated/${id}/docx`, {
      responseType: "blob",
    }),
  confirmFullySigned: (
    id: number,
    body: B2BConfirmFullySignedRequest = {},
  ) =>
    api
      .post<B2BConfirmFullySignedResult>(
        `/api/b2b-generator/generated/${id}/confirm-fully-signed`,
        body,
      )
      .then((r) => r.data),
  checkUop: (body: { text: string; language: string }) =>
    api
      // Sonnet po tekście do 6000 znaków, w serwisie DWIE próby przy
      // nieparsowalnym JSON-ie. Zmierzone na prodzie: 15,4 s dla jednego
      // zdania — domyślne 30 s instancji to za mało, a zerwane połączenie
      // nie anuluje generacji, tylko każe użytkownikowi kliknąć ponownie
      // i zapłacić drugi raz (`lib/http-timeouts.ts`).
      .post<B2BUopCheckResult>("/api/b2b-generator/check-uop", body, {
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      })
      .then((r) => r.data),
};

export type B2BSignatureStatus = "unsigned" | "signed_both";
export type B2BSignatureSource =
  | "manual_confirmation"
  | "validated_upload";

/**
 * Status handlowy umowy — niezależny od `B2BSignatureStatus`.
 *
 * `in_progress` ustawia system automatycznie przy generowaniu umowy, a `active`
 * przy potwierdzeniu podpisu obustronnego. Użytkownik nie może wybrać
 * `in_progress` — backend odrzuca to 422 (patrz `B2BGeneratedContractUpdate`).
 */
export type B2BContractStatus =
  | "active"
  | "in_progress"
  | "suspended"
  | "closed";
/**
 * Powody zakończenia PROJEKTU. Trzy ostatnie to katalog sprzed migracji 0226
 * (opisywał rozstanie z Partnerem, nie koniec projektu) — zniknęły z pickera,
 * ale MUSZĄ zostać w typie: produkcja ma wiersze `closed`, które je niosą,
 * i bez nich odczyt takiego wpisu nie typowałby się.
 */
export type B2BClosureReason =
  | "no_client_budget"
  | "contractor_found_other_project"
  | "contractor_health_reasons"
  | "contractor_underperformance"
  | "project_completed"
  | "internalization"
  | "other"
  | "resignation_before_signing"
  | "termination"
  | "mutual_agreement";

// Etykiety PL dla powyższych żyją w warstwie prezentacji
// (`components/v2/pages/B2BContractGeneratorV2.tsx`) — tutaj tylko kontrakt
// wartości wysyłanych na backend.

export interface B2BGeneratedListParams {
  q?: string;
  /**
   * Tablica — zakładka „Umowy aktywne i w trakcie podpisu" prosi o DWA statusy
   * naraz. Axios serializuje ją jako powtórzony parametr, tak jak czyta go
   * FastAPI (`contract_status=active&contract_status=in_progress`).
   */
  contractStatus?: B2BContractStatus[];
  closureReason?: B2BClosureReason;
  /** Zakres daty ROZPOCZĘCIA USŁUG (`YYYY-MM-DD`), obie granice włącznie. */
  startFrom?: string;
  startTo?: string;
  /**
   * Umowy jednej rekrutacji — krok 08 „Umowa". Filtr jest SERWEROWY: bez niego
   * karta zamknięcia czytałaby tylko najnowsze `limit` wierszy rejestru
   * i gubiła umowę starszą niż widoczna strona.
   */
  jobId?: number;
}

/** Wpis dziennika zmian statusu — dialog „Historia statusów". */
export interface B2BStatusEvent {
  id: number;
  from_status: string | null;
  to_status: string;
  effective_date: string | null;
  reason: string | null;
  reason_other: string | null;
  job_id: number | null;
  job_title: string | null;
  client_id: number | null;
  client_name: string | null;
  changed_by_name: string | null;
  created_at: string | null;
}

/**
 * Pola pominięte zostają bez zmian (backend rozróżnia je po `model_fields_set`),
 * więc zmiana statusu nie kasuje nazwy Klienta i odwrotnie.
 */
export interface B2BGeneratedContractUpdate {
  client_name?: string | null;
  contract_status?: B2BContractStatus;
  closure_reason?: B2BClosureReason | null;
  closure_reason_other?: string | null;
  closure_date?: string | null;
  /**
   * Projekt przypisywany przy przywracaniu umowy z zawieszenia. Klienta
   * wyprowadza backend z wybranego projektu — front go nie przesyła, żeby nie
   * dało się zapisać pary projekt/klient, która w bazie do siebie nie należy.
   */
  job_id?: number;
}

export interface B2BGeneratedContractRow {
  id: number;
  contract_number: string;
  /** Imię i nazwisko osoby fizycznej — NIE nazwa firmy (ta jest niżej). */
  partner_name: string | null;
  /**
   * Gotowe linie kolumny „Partner", policzone na backendzie: nazwa firmy
   * z rejestru, a dla wiersza bez zapisanej nazwy — awaryjnie osoba.
   * Rozpoznanie JDG vs spółka i kasowanie duplikacji nazwiska zawartego już
   * w nazwie firmy NIE są tu odtwarzane — ten sam słownik form prawnych
   * decyduje o zapisie snapshotu, więc druga kopia reguły rozjechałaby się
   * cicho z pierwszą.
   */
  partner_display_name: string | null;
  /** Osoba kontaktowa spółki; `null` dla JDG i gdy powtarzałaby nazwę firmy. */
  partner_secondary_line: string | null;
  /** NIP kanonicznie w samych cyfrach (kolumna „NIP"). */
  partner_nip: string | null;
  /** Data rozpoczęcia USŁUG (`YYYY-MM-DD`), nie data podpisania. */
  start_date: string | null;
  client_name: string | null;
  language: string | null;
  signing_date: string | null;
  created_at: string | null;
  created_by_name: string | null;
  signature_status: B2BSignatureStatus;
  signature_source: B2BSignatureSource | null;
  contract_status: B2BContractStatus;
  closure_reason: B2BClosureReason | null;
  closure_reason_other: string | null;
  closure_date: string | null;
  can_change_status: boolean;
  candidate_id: number | null;
  job_id: number | null;
  client_id: number | null;
  contract_id: number | null;
  candidate_name: string | null;
  job_title: string | null;
  canonical_client_name: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
  can_confirm_signed: boolean;
  blocked_reason: string | null;
  can_delete: boolean;
  can_edit: boolean;
  can_download: boolean;
}

export interface B2BConfirmFullySignedRequest {
  candidate_id?: number;
  job_id?: number;
  /**
   * Świadome potwierdzenie mimo różnic między dokumentem a istniejącym
   * kontraktem tej pary (kandydat, rekrutacja): serwer wiąże umowę, ale nie
   * zmienia niczego, co na kontrakcie jest już wpisane. Wysyłane WYŁĄCZNIE po
   * 409 z `can_keep_existing_terms` — bez różnic flaga nic nie zmienia, a
   * pozostałych odmów (duplikaty, inny klient, umowa podpisana) nie obchodzi.
   */
  keep_existing_contract_terms?: boolean;
}

export interface B2BConfirmFullySignedResult {
  outcome: "created" | "linked_existing" | "already_processed";
  contract_id: number;
  order_id: number | null;
  candidate_id: number;
  job_id: number;
  client_id: number;
  message: string;
  generated_contract: B2BGeneratedContractRow;
  /** Różnice zaakceptowane flagą `keep_existing_contract_terms` (etykiety PL). */
  acknowledged_conflicts?: string[];
  /**
   * Dlaczego `order_id` jest puste mimo udanego podpisu: `cost_client` (typ
   * zamówienia wybiera Delivery Lead) albo `open_group_line` (osoba jest już
   * na otwartej linii zamówienia MD/kosztowego). `null` przy wypełnionym
   * `order_id`.
   */
  order_skipped_reason?: string | null;
}

export interface B2BUopIssue {
  phrase: string;
  why: string;
  suggestion: string;
}

export interface B2BUopCheckResult {
  ok: boolean;
  issues: B2BUopIssue[];
  rewritten: string;
  summary: string;
}

export const candidatePinsApi = {
  list: () => api.get<CandidatePinRow[]>("/api/candidates/pins"),
  getState: (candidateId: number) =>
    api.get<CandidatePinToggleResponse>(`/api/candidates/${candidateId}/pin`),
  toggle: (candidateId: number, note?: string) =>
    api.post<CandidatePinToggleResponse>(
      `/api/candidates/${candidateId}/pin`,
      note ? { note } : {},
    ),
  remove: (candidateId: number) =>
    api.delete(`/api/candidates/${candidateId}/pin`),
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
// „degraded" to nie próg podobieństwa, tylko odpowiedź „nie wiem": wyszukiwanie
// podobnych ofert nie odpowiedziało, więc pusta lista NIE znaczy braku historii.
export type HistoricalTierUsed =
  | "primary"
  | "extended"
  | "empty"
  | "degraded";
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
  client_id: number | null;
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
  /** Kandydat był już rozważany u klienta tego joba (szybkie przepinanie). */
  same_client: boolean;
  /** Ten sam klient go wcześniej odrzucił — mocne ostrzeżenie, poza select-all. */
  rejected_by_same_client: boolean;
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
    /**
     * Ilu kandydatów odsiała bramka dopuszczalności (NDA / blacklista tego
     * klienta / konflikt konkurencyjny / weto hiring managera). Opcjonalne,
     * bo kontrakt jest addytywny — starsza odpowiedź bez tego pola czyta się
     * jako 0. Sekcja MUSI rozróżniać „historii nie ma" od „historia jest, ale
     * zablokowana u tego klienta": bez tego bramka wygląda jak utrata danych.
     */
    hidden_ineligible?: number;
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
  forJob: (
    jobId: number,
    opts?: {
      top_k?: number;
      include_breakdown?: boolean;
      location?: string;
      location_source?: "all" | "cv" | "notes";
      /**
       * Domyślnie true po stronie backendu (decyzja 19.08): znany budżet
       * oferty ukrywa znane stawki powyżej. false = pokaż też przekraczających.
       */
      exclude_over_budget?: boolean;
      exclude_remote_only?: boolean;
      /** Dealbreakery 0278 (domyślnie WŁĄCZONE po stronie backendu — pomiń,
       *  żeby zostawić domyślne zachowanie). */
      exclude_missing_must?: boolean;
      exclude_office_days_exceeded?: boolean;
      exclude_office_city_mismatch?: boolean;
    },
  ) =>
    api.get<{
      job_id: number;
      job_title: string;
      search_type: string;
      location_filter?: string | null;
      matches: CandidateMatch[];
      /** Optional for one-release compatibility with older backends. */
      meta?: RecommendationMeta;
    }>(`/api/jobs/${jobId}/recommendations`, { params: opts }),
  forCandidate: (candidateId: number, opts?: { top_k?: number; include_breakdown?: boolean }) =>
    api.get<{
      candidate_id: number;
      candidate_name: string;
      matches: JobMatch[];
      meta?: RecommendationMeta;
    }>(
      `/api/candidates/${candidateId}/recommendations`,
      { params: opts },
    ),
  // Cztery wywołania poniżej liczą po stronie modelu (kryteria, klasyfikacja
  // technologii) albo przeliczają scoring całej puli, a użytkownik czeka na
  // wynik przy otwartym ekranie — 120 s zamiast domyślnych 30 s instancji
  // (uzasadnienie: `lib/http-timeouts.ts`).
  refreshCriteria: (jobId: number) =>
    api.post<{ job_id: number; must_skills: unknown; nice_skills: unknown; criteria_generated_at: string }>(
      `/api/jobs/${jobId}/refresh-criteria`,
      undefined,
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
    ),
  previewCriteria: (jobId: number) =>
    api.post<{
      job_id: number;
      must_skills: Array<{ name: string; level?: string | null }>;
      nice_skills: Array<{ name: string; level?: string | null }>;
      source: "ollama" | "heuristic";
      current_must_skills: Array<{ name: string; level?: string | null }>;
      current_nice_skills: Array<{ name: string; level?: string | null }>;
    }>(`/api/jobs/${jobId}/generate-criteria-preview`, undefined, {
      timeout: SLOW_ENDPOINT_TIMEOUT_MS,
    }),
  classifyTechnologies: (names: string[]) =>
    api.post<{ technologies: Record<string, boolean> }>(
      "/api/cv-generator/classify-technologies",
      { names },
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
    ),
  recomputeScores: (jobId: number, topK = 200) =>
    api.post(`/api/jobs/${jobId}/recompute-scores`, null, {
      params: { top_k: topK },
      timeout: SLOW_ENDPOINT_TIMEOUT_MS,
    }),
  assignToJob: (candidateId: number, jobId: number) =>
    api.post(`/api/candidates/${candidateId}/assign-to-job/${jobId}`),
  seekingContractors: (params?: SeekingContractorsParams) =>
    api.get<SeekingContractorsResponse>(
      "/api/recommendations/seeking-contractors",
      { params },
    ),
  // Oba zwracają wygenerowaną przez LLM treść, na którą użytkownik patrzy
  // w oknie — dlatego 120 s (patrz `lib/http-timeouts.ts`).
  sendCandidateShortlistEmail: (payload: { candidate_id: number; job_ids: number[] }) =>
    api.post<ShortlistEmailDraftResponse>(
      "/api/recommendations/send-candidate-shortlist-email",
      payload,
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
    ),
  prepareClientProposal: (payload: { candidate_id: number; job_id: number }) =>
    api.post<ClientProposalResponse>(
      "/api/recommendations/prepare-client-proposal",
      payload,
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
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
        // Obiekt konfiguracji tu BYŁ, ale niósł same `params` — a bez jawnego
        // multipartu axios serializuje FormData do JSON-a (instancja ma
        // domyślne application/json) i plik nie dojeżdża: 422 „file Field
        // required". Ten sam defekt co w #1209, dwa tygodnie później.
        headers: { "Content-Type": "multipart/form-data" },
        params: {
          top_k: params?.top_k,
          threshold: params?.threshold,
        },
        // Parse CV + scoring puli — użytkownik czeka (http-timeouts.ts).
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
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
  /** Ilu konsultantów JEST w horyzoncie — nie ilu zmieściło się na stronie.
   *  Do 2026-07-28 backend zwracał tu długość obciętej listy, więc licznik
   *  zawsze zgadzał się z tym, co widać, i obcięcie było niewidoczne. */
  total: number;
  /** Ile pozycji faktycznie zwrócono (≤ `page_size`). */
  returned: number;
  /** `total > returned` — lista jest przycięta i ktoś może nie być widoczny. */
  truncated: boolean;
  items: SeekingContractorRow[];
  /**
   * Stan wyszukiwania, którym powstała ta lista.
   *
   * `degraded: true` znaczy, że dla CO NAJMNIEJ JEDNEGO konsultanta warstwa
   * semantyczna nie odpowiedziała — jego pusty `top_matches` mówi „nie wiemy",
   * a nie „nic dla tej osoby nie ma". Bez odczytania tej flagi awaria renderuje
   * się identycznie jak zero trafień, czyli dokładnie tak, jak nie wolno.
   *
   * Pole jest OPCJONALNE, bo w oknie wdrożenia przeglądarka może dostać
   * odpowiedź ze starszej wersji backendu, która tego klucza nie niosła.
   * Brak `meta` czytamy jak `degraded: false` — to jedyna interpretacja, która
   * nie zamienia normalnego pustego stanu w fałszywy alarm.
   */
  meta?: {
    degraded: boolean;
    /**
     * `semantic_unavailable` — padł dostawca (Qdrant/Voyage), lista jest
     * niepełna. `no_candidates` / `no_open_jobs` — nie było czego szukać, czyli
     * NORMALNY pusty stan, nie awaria. Rozstrzyga `degraded`, nie ten napis.
     */
    reason: "semantic_unavailable" | "no_candidates" | "no_open_jobs" | null;
  };
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
    total_score: number | null;
    breakdown?: ScoreBreakdown | null;
    warning: string | null;
  }>;
  // Wartości faktycznie wysyłane przez backend. Do sierpnia 2026 unia
  // deklarowała "bm25", którego nikt nie wysyła, i NIE zawierała
  // "fallback", które leci z `cv_match_preview` — więc rozjazd nie
  // wychodził na type-checku, a front i tak nie miał gałęzi dla stanu,
  // który dostawał.
  search_type: "semantic" | "fallback" | "unavailable";
  meta?: RecommendationMeta;
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
  /** True when the ranking used a degraded semantic leg (Qdrant/Voyage down or
   *  the job unindexed) — the UI flags it instead of presenting it as healthy. */
  degraded: boolean;
  /** True when a brief/Champion edit changed a matching input after this ranking
   *  was produced — the UI prompts a re-run instead of showing it as current. */
  stale: boolean;
  /** Liczniki dealbreakerów z generacji — budżet oferty działa z automatu
   *  jako twardy sufit (decyzja 19.08); null/brak = snapshot sprzed 0237. */
  hidden?: HiddenCounters | null;
  /** Correlates this ranking with match telemetry (impressions/outcomes). */
  run_id: string | null;
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
  /**
   * Szósta warstwa silnika (Champion fit, backend built-in = 10). Opcjonalna,
   * bo historyczne profile mają tylko 5 kluczy; brak klucza ≠ 0 — legacy
   * runtime dolicza wtedy domyślne 10 pkt PONAD budżet 100 (AI-P0-05).
   * Edytor zawsze wysyła jawną wartość, żeby suma = dokładnie 100.
   */
  champion_fit?: number;
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

/** Sekcja 1 — podstawowe informacje. */
export interface ChampionBasics {
  role_name?: string | null;
  seniority_min_years?: number | null;
  /** PLN/h DLA KANDYDATA — zasila twardy sufit stawki w filtrach. */
  rate_value?: number | null;
  rate_raw?: string | null;
  work_mode?: string | null;
  onsite_days_per_week?: number | null;
  /** LOKALIZACJA BIURA — gdzie jest praca. Nazwa klucza jest historyczna. */
  candidate_location_pref?: string | null;
  /** JĘZYK PRACY wymagany od kandydata. Język dokumentu CV to `ClientCvRule.cv_language`. */
  language?: string | null;
  start_date?: string | null;
  /** Termin na dostarczenie kandydatów do TEJ oferty. */
  deadline?: string | null;
  contract_length?: string | null;
}

/** Sekcja 2 — co wpisać w wyszukiwarkę. */
export interface ChampionSearch {
  keywords: string;
  target_companies: string;
  disqualifiers: string[];
  notes: string;
  /** Kanały ze starego szablonu — bez UI, trzymane dla zgodności danych. */
  sources?: Array<"internal_base" | "linkedin" | "ad" | "referrals" | "other">;
}

export interface StackItem {
  name: string;
}

/** Sekcja 3 — stack technologiczny. Zapis synchronizuje go do must/nice oferty. */
export interface ChampionStack {
  must: StackItem[];
  nice: StackItem[];
  notes: string;
}

/** Sekcja 4 — o projekcie (2 zdania) + obowiązki. */
export interface ChampionProject {
  about: string;
  responsibilities: string;
}

/** Sekcja 6 — o kliencie. */
export interface ChampionClient {
  about: string;
  selling_points: string;
  priority_rules: string;
  offlimit?: boolean | null;
  contract_type?: string | null;
  cv_language?: string | null;
  consultant_insight: string;
  historical_questions: string;
  sectors: string[];
}

/** Sekcja 7 — dokumenty. Wskaźnik na SharePoint, nie plik w NEXUSIE. */
export interface ChampionDocument {
  name: string;
  url: string;
}

/** @deprecated Kształt sprzed 09.2026 — migrowany po stronie serwera przy odczycie. */
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

export type ChampionVerificationMethod = "call" | "meeting" | "email" | "other";

export interface ChampionClientVerification {
  status: "pending" | "verified";
  verified_by_id?: number | null;
  verified_by_name?: string | null;
  verified_at?: string | null;
  method?: ChampionVerificationMethod | null;
  key_corrections: string;
  confirmed_as_is: boolean;
}

export interface ChampionConsultantVerification {
  status: "pending" | "verified" | "skipped";
  verified_by_id?: number | null;
  verified_by_name?: string | null;
  verified_at?: string | null;
  consultant_candidate_id?: number | null;
  consultant_name?: string | null;
  insights: string;
  skip_reason: string;
}

export interface ChampionVerification {
  client: ChampionClientVerification;
  consultant: ChampionConsultantVerification;
}

export const EMPTY_CHAMPION_VERIFICATION: ChampionVerification = {
  client: { status: "pending", key_corrections: "", confirmed_as_is: false },
  consultant: { status: "pending", insights: "", skip_reason: "" },
};

export interface ChampionBriefing {
  status: "pending" | "attached";
  note_id?: number | null;
  title?: string | null;
  audio_storage_key?: string | null;
  attached_by_id?: number | null;
  attached_by_name?: string | null;
  attached_at?: string | null;
}

export const EMPTY_CHAMPION_BRIEFING: ChampionBriefing = { status: "pending" };

/**
 * Profil Championa — siedem sekcji szablonu (09.2026).
 *
 * `verification`, `briefing` i `recommended_searches` NIE są sekcjami: serwer
 * stempluje je własnymi endpointami, a zwykły zapis profilu ich nie dotyka.
 */
export interface ChampionProfile {
  basics: ChampionBasics;
  search: ChampionSearch;
  stack: ChampionStack;
  project: ChampionProject;
  screening_questions: ScreeningQuestion[];
  client: ChampionClient;
  documents: ChampionDocument[];
  verification?: ChampionVerification;
  briefing?: ChampionBriefing;
  recommended_searches?: RecommendedSearch[];
  /**
   * Ingest provenance (`app/schemas/champion.py::ChampionProfile.provenance`,
   * flattened back onto the top level by its custom `model_dump`). Present
   * ONLY when the profile was populated by the document parser
   * (`champion_profile_ingest.py`, LLM-based) — `_source` is
   * `"champion_upload"` or `"traffit_recruitment_file:<id>"`. Absent on a
   * hand-written profile. This is the ONLY real "was this AI?" signal in the
   * data — krok 02's section-state chips read it, never guess.
   */
  _source?: string | null;
  _parsed_at?: string | null;
  _parser?: string | null;
}

export const EMPTY_CHAMPION_PROFILE: ChampionProfile = {
  basics: {
    role_name: null,
    seniority_min_years: null,
    rate_value: null,
    rate_raw: null,
    work_mode: null,
    onsite_days_per_week: null,
    candidate_location_pref: null,
    language: null,
    start_date: null,
    deadline: null,
    contract_length: null,
  },
  search: { keywords: "", target_companies: "", disqualifiers: [], notes: "" },
  stack: { must: [], nice: [], notes: "" },
  project: { about: "", responsibilities: "" },
  screening_questions: [],
  client: {
    about: "",
    selling_points: "",
    priority_rules: "",
    offlimit: null,
    contract_type: null,
    cv_language: null,
    consultant_insight: "",
    historical_questions: "",
    sectors: [],
  },
  documents: [],
  verification: EMPTY_CHAMPION_VERIFICATION,
  briefing: EMPTY_CHAMPION_BRIEFING,
};

export interface ChampionProfileResponse {
  job_id: number;
  job_title?: string;
  champion_profile: ChampionProfile | Record<string, never>;
}

export interface ChampionVerificationRequest {
  side: "client" | "consultant";
  reset?: boolean;
  client?: {
    method: ChampionVerificationMethod;
    key_corrections: string;
    confirmed_as_is: boolean;
  };
  consultant?: {
    consultant_candidate_id?: number | null;
    consultant_name?: string;
    insights?: string;
    skipped?: boolean;
    skip_reason?: string;
  };
}

export interface ChampionConsultantSuggestion {
  candidate_id: number;
  name: string;
  job_title: string | null;
  since: string | null;
}

export const championApi = {
  get: (jobId: number) =>
    api.get<ChampionProfileResponse>(`/api/jobs/${jobId}/champion-profile`),
  put: (jobId: number, profile: ChampionProfile) =>
    api.put<ChampionProfileResponse>(`/api/jobs/${jobId}/champion-profile`, profile),
  verify: (jobId: number, payload: ChampionVerificationRequest) =>
    api.post<ChampionProfileResponse>(
      `/api/jobs/${jobId}/champion-profile/verification`,
      payload
    ),
  consultantSuggestions: (jobId: number) =>
    api.get<ChampionConsultantSuggestion[]>(
      `/api/jobs/${jobId}/champion-profile/consultant-suggestions`
    ),
  // Synchroniczne wywołanie Claude w requeście — z map-reduce transkryptu
  // (jeden sekwencyjny call na 30k znaków), więc sufit CRUD-a 30 s realnego
  // spotkania nie obejmuje. Kwota `champion_draft` jest commitowana PRZED
  // wywołaniem modelu, więc zerwanie po stronie przeglądarki pali limit
  // i płaci za generację, której nikt nie zobaczy.
  setBriefing: (jobId: number, noteId: number, enrich = true) =>
    api.post<ChampionProfileResponse & { suggestion_id?: number | null }>(
      `/api/jobs/${jobId}/champion-profile/briefing`,
      { note_id: noteId, enrich },
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS }
    ),
  clearBriefing: (jobId: number) =>
    api.delete<ChampionProfileResponse>(
      `/api/jobs/${jobId}/champion-profile/briefing`
    ),
  briefingAudioUrl: (jobId: number) =>
    api.get<{ url: string }>(
      `/api/jobs/${jobId}/champion-profile/briefing/audio-url`
    ),
  generateRecommendedSearches: (jobId: number) =>
    api.post<ChampionProfileResponse>(
      `/api/jobs/${jobId}/champion-profile/recommended-searches/generate`,
      undefined,
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS }
    ),
  decideRecommendedSearch: (
    jobId: number,
    searchId: string,
    action: "approve" | "reject" | "reset"
  ) =>
    api.post<ChampionProfileResponse>(
      `/api/jobs/${jobId}/champion-profile/recommended-searches/decision`,
      { search_id: searchId, action }
    ),
};

// ── Champion recommended searches (AI-proposed, DL-approved) ────────────────

export interface RecommendedSearchParams {
  q_all?: string[];
  q_any_groups?: string[][];
  q_none?: string[];
  skills_must?: string[];
  skills_any?: string[];
  skills_none?: string[];
  experience_years_min?: number | null;
  experience_years_max?: number | null;
  location_cities?: string[];
}

export interface RecommendedSearch {
  id: string;
  name: string;
  rationale: string;
  params: RecommendedSearchParams;
  status: "proposed" | "approved" | "rejected";
  saved_search_id?: number | null;
  generated_at?: string | null;
  decided_by_id?: number | null;
  decided_by_name?: string | null;
  decided_at?: string | null;
}

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

/** Siedem sekcji szablonu — musi zgadzać się z `VALID_SECTIONS` po stronie backendu. */
export type ChampionSectionName =
  | "basics"
  | "search"
  | "stack"
  | "project"
  | "screening_questions"
  | "client"
  | "documents";

export const CHAMPION_SECTIONS: ChampionSectionName[] = [
  "basics",
  "search",
  "stack",
  "project",
  "screening_questions",
  "client",
  "documents",
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
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
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
      { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
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
  // True when a previously-connected mailbox needs the user to re-run OAuth
  // (e.g. server-side encryption key rotated). Renders an amber CTA banner.
  requires_reconnect?: boolean;
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
  is_archived: boolean;
  is_private_filtered: boolean;
  match_method:
    | "strict"
    | "smart_domain"
    | "smart_thread"
    | "smart_name"
    | "manual"
    | "unmatched";
  match_confidence: number | null;
  candidate_id?: number | null;
  attachments?: EmailAttachmentPreview[];
}

export type BulkEmailAction =
  | "archive"
  | "mark_read"
  | "mark_unread"
  | "link_to_candidate"
  | "unlink";

export interface BulkEmailActionItemError {
  id: number;
  reason: string;
}

export interface BulkEmailActionResponse {
  action: BulkEmailAction;
  updated_count: number;
  skipped_count: number;
  errors: BulkEmailActionItemError[];
}

export interface EmailThreadPreview {
  conversation_id: string;
  subject: string | null;
  latest: EmailMessage;
  message_count: number;
  unread_count: number;
}

export type FreeBusyStatus =
  | "free"
  | "tentative"
  | "busy"
  | "oof"
  | "workingElsewhere"
  | "unknown";

export interface FreeBusySlot {
  start: string;
  end: string;
  status: FreeBusyStatus;
}

export interface FreeBusyResponse {
  attendees: Record<string, FreeBusySlot[]>;
  requested_window: { start: string; end: string };
}

export interface EmailSearchHit {
  id: number;
  m365_conversation_id: string;
  candidate_id: number | null;
  subject: string | null;
  from_address: string;
  from_name: string | null;
  received_at: string;
  has_attachments: boolean;
  is_read: boolean;
  snippet: string | null;
}

export interface EmailSearchResponse {
  items: EmailSearchHit[];
  total: number;
  limit: number;
  offset: number;
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
  listThreadMessages: (candidateId: number, conversationId: string) =>
    api.get<EmailMessage[]>(
      `/api/candidates/${candidateId}/emails/thread/${encodeURIComponent(conversationId)}`,
    ),
  searchEmails: (q: string, limit = 50, offset = 0) =>
    api.get<EmailSearchResponse>("/api/microsoft365/emails/search", {
      params: { q, limit, offset },
    }),
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
  createInvite: (payload: {
    candidate_id: number;
    title: string;
    description?: string;
    start: string;
    end: string;
    event_type?: string;
    extra_attendees?: string[];
    invite_candidate?: boolean;
    add_teams_meeting?: boolean;
  }) =>
    api.post<CalendarEventResponse>(
      "/api/calendar/events/m365-invite",
      payload,
    ),
  bulkAction: (payload: {
    email_ids: number[];
    action: BulkEmailAction;
    candidate_id?: number;
  }) =>
    api.post<BulkEmailActionResponse>(
      "/api/microsoft365/emails/bulk",
      payload,
    ),
  checkFreeBusy: (payload: {
    start: string;
    end: string;
    attendees: string[];
  }) => api.post<FreeBusyResponse>("/api/microsoft365/free-busy", payload),
};

// ── User Email Templates (Phase 4.5 — M365 outreach library) ────────────────

export interface UserEmailTemplate {
  id: number;
  user_id: number;
  name: string;
  subject: string | null;
  body_html: string;
  variables: string[];
  is_shared: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserEmailTemplateInput {
  name: string;
  subject?: string | null;
  body_html: string;
  is_shared?: boolean;
}

export interface UserEmailTemplateRenderRequest {
  candidate_id?: number;
  request_id?: number;
  job_id?: number;
}

export interface UserEmailTemplateRenderResponse {
  rendered_subject: string;
  rendered_body_html: string;
  unresolved_vars: string[];
}

export const userEmailTemplatesApi = {
  list: () =>
    api.get<UserEmailTemplate[]>("/api/user-email-templates"),
  get: (id: number) =>
    api.get<UserEmailTemplate>(`/api/user-email-templates/${id}`),
  create: (data: UserEmailTemplateInput) =>
    api.post<UserEmailTemplate>("/api/user-email-templates", data),
  update: (id: number, data: Partial<UserEmailTemplateInput>) =>
    api.put<UserEmailTemplate>(`/api/user-email-templates/${id}`, data),
  delete: (id: number) =>
    api.delete<void>(`/api/user-email-templates/${id}`),
  render: (id: number, ctx: UserEmailTemplateRenderRequest) =>
    api.post<UserEmailTemplateRenderResponse>(
      `/api/user-email-templates/${id}/render`,
      ctx,
    ),
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

export interface SuggestedQuestionsMeta {
  returned: number;
  degraded: boolean;
  reason: string | null;
}

export interface SuggestedQuestionsEnvelope {
  items: SuggestedQuestion[];
  meta: SuggestedQuestionsMeta;
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

  /**
   * Zwraca kopertę `{ items, meta }`, nie gołą listę.
   *
   * Do #408 endpoint oddawał `SuggestedQuestion[]`, przez co awaria
   * wyszukiwania podobnych rekrutacji była NIEODRÓŻNIALNA od oferty, która po
   * prostu nie ma podobnych: oba tiery milkły, tier 4 dolewał pytania
   * z auto-generatora i odpowiedź wyglądała normalnie. `meta.degraded`
   * niesie tę różnicę do UI.
   */
  suggestedForJob: (
    jobId: number,
    params?: { candidate_id?: number; target_count?: number },
  ) =>
    api.get<SuggestedQuestionsEnvelope>(
      `/api/jobs/${jobId}/suggested-questions`,
      { params },
    ),
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
  // M4 PR-04 (token v2)
  revoke_key?: string | null;
  max_views?: number | null;
}

export interface CVShareTokenListItem {
  revoke_key: string;
  token_preview: string;
  is_v2: boolean;
  created_at?: string | null;
  created_by_name?: string | null;
  expires_at?: string | null;
  revoked: boolean;
  revoked_at?: string | null;
  revoke_reason?: string | null;
  view_count: number;
  max_views?: number | null;
  last_viewed_at?: string | null;
  purpose?: string | null;
  share_url_suffix?: string | null;
}

export const candidateStageCvApi = {
  original: {
    get: (stageId: number) =>
      api.get<CVOriginalSnapshot>(
        `/api/candidates/stages/${stageId}/cv/original`,
      ),
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
    // Finalizacja renderuje dokument po stronie serwera, a rekruter czeka na
    // plik — 120 s zamiast domyślnych 30 s (patrz `lib/http-timeouts.ts`).
    finalize: (stageId: number) =>
      api.post<CVBrandedFinalizeResponseT>(
        `/api/candidates/stages/${stageId}/cv/branded/finalize`,
        undefined,
        { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
      ),
  },
  share: {
    // M4 PR-04: default TTL 14 dni (backend max 90), opcjonalny limit wyświetleń.
    create: (stageId: number, expiresInDays = 14, maxViews?: number) =>
      api.post<CVShareTokenResp>(
        `/api/candidates/stages/${stageId}/cv/share-token`,
        null,
        {
          params: {
            expires_in_days: expiresInDays,
            ...(maxViews ? { max_views: maxViews } : {}),
          },
        },
      ),
    list: (stageId: number) =>
      api.get<CVShareTokenListItem[]>(
        `/api/candidates/stages/${stageId}/cv/share-tokens`,
      ),
    revoke: (tokenOrKey: string, reason?: string) =>
      api.delete<{ status: string; token: string }>(
        `/api/candidates/stages/cv/share-token/${tokenOrKey}`,
        reason ? { params: { reason } } : undefined,
      ),
    revokeAll: (stageId: number, reason?: string) =>
      api.delete<{ status: string; count: number }>(
        `/api/candidates/stages/${stageId}/cv/share-tokens`,
        reason ? { params: { reason } } : undefined,
      ),
  },
};

// ── Generator CV B2B — publiczny link (interaktywne CV) ─────────────────────

export interface CvGeneratedShareCreateResp {
  token: string;
  expires_at: string;
  share_url_suffix: string;
  generated_id: number;
  revoke_key: string;
  max_views?: number | null;
  interactive_available: boolean;
}

export interface CvGeneratedShareListItem {
  revoke_key: string;
  token_preview: string;
  created_at?: string | null;
  created_by_name?: string | null;
  expires_at?: string | null;
  revoked: boolean;
  revoked_at?: string | null;
  revoke_reason?: string | null;
  view_count: number;
  max_views?: number | null;
  last_viewed_at?: string | null;
}

export const cvGeneratedShareApi = {
  // Token v2-only: sekret zwracany raz, w DB tylko SHA-256.
  create: (generatedId: number, expiresInDays = 14, maxViews?: number) =>
    api.post<CvGeneratedShareCreateResp>(
      `/api/cv-generator/generated/${generatedId}/share-token`,
      null,
      {
        params: {
          expires_in_days: expiresInDays,
          ...(maxViews ? { max_views: maxViews } : {}),
        },
      },
    ),
  list: (generatedId: number) =>
    api.get<CvGeneratedShareListItem[]>(
      `/api/cv-generator/generated/${generatedId}/share-tokens`,
    ),
  revoke: (tokenOrKey: string, reason?: string) =>
    api.delete<{ ok: boolean; already_revoked: boolean }>(
      `/api/cv-generator/generated/share-token/${tokenOrKey}`,
      reason ? { params: { reason } } : undefined,
    ),
};

// ── Settings → AI (Traffit gap #5) ───────────────────────────────────────────

export type AIFeatureKey =
  | "scoring"
  | "job_description_generator"
  | "cv_parser"
  | "candidate_summary"
  | "champion_draft"
  | "order_parser"
  | "cv_requirement_map"
  | "cv_interactive_chat"
  | "cv_backfill"
  | "notes_extraction"
  | "champion_profile_parse"
  | "cv_generator"
  | "mindy_chat"
  | "cv_rule_lint"
  | "uop_check"
  | "cv_name_backfill";

export interface AIFeatureConfigDto {
  feature: AIFeatureKey;
  enabled: boolean;
  monthly_limit: number;
  /** Efektywny model LLM z rejestru backendu (funkcja → model). */
  model: string;
  label: string;
  data_sent_to_ai: string[];
}

export interface AIFeatureUsageDto {
  feature: AIFeatureKey;
  used: number;
  provider_calls?: number;
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
  estimated_cost_usd?: number | null;
  unpriced_calls?: number;
  legacy_usage_present?: boolean;
  operations_without_response?: number;
  input_tokens: number;
  output_tokens: number;
  limit: number;
  period_start: string;
  period_end: string;
}

export interface AISettingsResponse {
  spend_alerts?: { in_app_enabled: boolean; slack_configured: boolean; pending_deliveries: number; last_delivered_at: string | null };
  master_enabled: boolean;
  features: AIFeatureConfigDto[];
  usage: AIFeatureUsageDto[];
}

export interface AIFeatureUpdate {
  enabled?: boolean;
  monthly_limit?: number;
}

export const aiSettingsApi = {
  testAlert: () => api.post<{ delivered: boolean; alert_id: number }>("/api/settings/ai/alerts/test"),
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

// ── Multi-source attribution (Traffit gap #4) ────────────────────────────────

export type SourceChannel =
  | "manual"
  | "aktywny_search"
  | "cv_upload"
  | "email"
  | "posting"
  | "referral"
  | "import_csv";

export interface CandidateSourceEventDto {
  id: number;
  candidate_id: number;
  channel: SourceChannel;
  channel_label: string;
  job_id: number | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  utm_term: string | null;
  utm_content: string | null;
  note: string | null;
  captured_at: string;
  created_at: string;
}

export interface CandidateSourceCreatePayload {
  channel: SourceChannel;
  job_id?: number | null;
  utm_source?: string | null;
  utm_medium?: string | null;
  utm_campaign?: string | null;
  utm_term?: string | null;
  utm_content?: string | null;
  note?: string | null;
  captured_at?: string | null;
}

export interface SourceFunnelRow {
  channel: SourceChannel;
  channel_label: string;
  utm_source: string | null;
  utm_campaign: string | null;
  candidates_total: number;
  hired: number;
  hire_rate_pct: number;
}

export interface SourceReportResponse {
  period_start: string;
  period_end: string;
  rows: SourceFunnelRow[];
}

export const candidateSourcesApi = {
  list: (candidateId: number) =>
    api.get<CandidateSourceEventDto[]>(
      `/api/candidates/${candidateId}/sources`,
    ),
  create: (candidateId: number, payload: CandidateSourceCreatePayload) =>
    api.post<CandidateSourceEventDto>(
      `/api/candidates/${candidateId}/sources`,
      payload,
    ),
};

export const sourcesReportApi = {
  funnel: (days: number = 30, groupByUtm: boolean = false) =>
    api.get<SourceReportResponse>("/api/reports/sources", {
      params: { days, group_by_utm: groupByUtm },
    }),
};

// ── Bulk candidate actions (Traffit gap #3) ──────────────────────────────────

export type BulkActionType =
  | "add_tags"
  | "assign_talent_pool"
  | "assign_to_job"
  | "anonymize_pii";

export interface BulkActionRequest {
  action: BulkActionType;
  candidate_ids: number[];
  params?: Record<string, unknown>;
}

export interface BulkActionItemResult {
  candidate_id: number;
  ok: boolean;
  reason?: string | null;
}

export interface BulkActionResponse {
  action: BulkActionType;
  requested: number;
  succeeded: number;
  skipped: number;
  items: BulkActionItemResult[];
}

export const candidatesBulkApi = {
  dispatch: (payload: BulkActionRequest) =>
    api.post<BulkActionResponse>("/api/candidates/bulk", payload),
};

// ── Editable dictionaries (Traffit gap #8) ───────────────────────────────────

export interface DictionaryItemDto {
  id: number;
  key: string;
  label_pl: string;
  label_en: string | null;
  ordinal: number;
  archived: boolean;
  last_edited_at: string | null;
}

export interface DictionaryDto {
  id: number;
  slug: string;
  label_pl: string;
  description: string | null;
  enforced: boolean;
  items: DictionaryItemDto[];
}

export interface DictionarySummaryDto {
  slug: string;
  label_pl: string;
  description: string | null;
  enforced: boolean;
  item_count: number;
}

export interface DictionaryItemCreatePayload {
  key: string;
  label_pl: string;
  label_en?: string | null;
  ordinal?: number;
}

export interface DictionaryItemUpdatePayload {
  key?: string;
  label_pl?: string;
  label_en?: string | null;
  ordinal?: number;
  archived?: boolean;
}

// ── Custom field schema editor (Traffit gap #7) ──────────────────────────────

export type EntityType = "candidate" | "job";
export type FieldType =
  | "text"
  | "long_text"
  | "number"
  | "checkbox"
  | "radio"
  | "select"
  | "multi_select"
  | "date"
  | "datetime"
  | "file"
  | "files"
  | "location"
  | "link";

export interface EntityFieldDefDto {
  id: number;
  entity_type: EntityType;
  key: string;
  label_pl: string;
  label_en: string | null;
  help_text: string | null;
  field_type: FieldType;
  options: Record<string, unknown>;
  required: boolean;
  section: string | null;
  ordinal: number;
  archived: boolean;
  last_edited_at: string | null;
}

export interface EntityFieldDefCreatePayload {
  entity_type: EntityType;
  key: string;
  label_pl: string;
  label_en?: string | null;
  help_text?: string | null;
  field_type: FieldType;
  options?: Record<string, unknown>;
  required?: boolean;
  section?: string;
  ordinal?: number;
}

export interface EntityFieldDefUpdatePayload {
  label_pl?: string;
  label_en?: string | null;
  help_text?: string | null;
  options?: Record<string, unknown>;
  required?: boolean;
  section?: string;
  ordinal?: number;
  archived?: boolean;
}

export interface FieldTypeInfoDto {
  value: FieldType;
  label: string;
}

export interface SchemaListResponseDto {
  entity_type: EntityType;
  fields: EntityFieldDefDto[];
}

export const entityFieldsApi = {
  schema: (entity: EntityType, includeArchived = false) =>
    api.get<SchemaListResponseDto>(`/api/entity-schema/${entity}`, {
      params: { include_archived: includeArchived },
    }),
  fieldTypes: () =>
    api.get<FieldTypeInfoDto[]>("/api/settings/entity-fields/types"),
  create: (payload: EntityFieldDefCreatePayload) =>
    api.post<EntityFieldDefDto>("/api/settings/entity-fields", payload),
  update: (id: number, payload: EntityFieldDefUpdatePayload) =>
    api.patch<EntityFieldDefDto>(
      `/api/settings/entity-fields/${id}`,
      payload,
    ),
};

export const dictionariesApi = {
  // Public-ish (any authenticated user) — used by form pickers.
  itemsBySlug: (slug: string, includeArchived = false) =>
    api.get<DictionaryItemDto[]>(`/api/dictionaries/${slug}/items`, {
      params: { include_archived: includeArchived },
    }),

  // Admin
  list: () =>
    api.get<DictionarySummaryDto[]>("/api/settings/dictionaries"),
  get: (slug: string) =>
    api.get<DictionaryDto>(`/api/settings/dictionaries/${slug}`),
  createItem: (slug: string, payload: DictionaryItemCreatePayload) =>
    api.post<DictionaryItemDto>(
      `/api/settings/dictionaries/${slug}/items`,
      payload,
    ),
  updateItem: (
    slug: string,
    itemId: number,
    payload: DictionaryItemUpdatePayload,
  ) =>
    api.patch<DictionaryItemDto>(
      `/api/settings/dictionaries/${slug}/items/${itemId}`,
      payload,
    ),
};

// ── CloudTalk telephony (Phase CloudTalk.2+) ────────────────────────────────

export type CallDirection = "inbound" | "outbound";
export type CallStatus =
  | "completed"
  | "missed"
  | "voicemail"
  | "failed"
  | "initiated";

export interface Call {
  id: number;
  candidate_id: number;
  user_id: number | null;
  direction: CallDirection;
  duration_seconds: number | null;
  status: CallStatus;
  transcript: string | null;
  summary: string | null;
  recording_url: string | null;
  cloudtalk_call_id: string | null;
  cloudtalk_agent_id: number | null;
  started_at: string | null;
  created_at: string;
}

export interface CallStats {
  user: {
    total_calls: number;
    avg_duration_seconds: number | null;
    avg_duration_formatted: string;
    calls_this_week: number;
    calls_this_month: number;
  };
  global: {
    calls_this_week: number;
    avg_duration_seconds: number | null;
    avg_duration_formatted: string;
  };
  cloudtalk_status: "live" | "disabled";
}

export interface CloudTalkAgent {
  id: number;
  firstname: string | null;
  lastname: string | null;
  email: string | null;
  default_number: string | null;
  linked_user_id: number | null;
  linked_user_email: string | null;
}

export interface InitiateCallResponse {
  call_id: number;
  candidate_id: number;
  phone: string;
  cloudtalk_response: Record<string, unknown>;
}

export interface SyncAgentsResponse {
  linked: number;
  already_linked: number;
  unmatched: CloudTalkAgent[];
}

export const callsApi = {
  getForCandidate: (candidateId: number) =>
    api.get<Call[]>(`/api/candidates/${candidateId}/calls`).then((r) => r.data),
  getStats: () => api.get<CallStats>("/api/calls/stats").then((r) => r.data),
};

// ── Teams notifications (Phase 7.6) ─────────────────────────────────────────

export type TeamsNotificationType =
  | "candidate_added"
  | "decision_accepted"
  | "decision_rejected"
  | "contract_signed";

export interface TeamsChannel {
  id: number;
  workspace_label: string;
  team_id: string;
  channel_id: string;
  notification_types: TeamsNotificationType[];
  enabled: boolean;
  created_by_user_id: number;
  created_at: string;
  updated_at: string;
}

export interface TeamsChannelCreateInput {
  workspace_label: string;
  team_id: string;
  channel_id: string;
  notification_types: TeamsNotificationType[];
}

export interface TeamsChannelUpdateInput {
  workspace_label?: string;
  notification_types?: TeamsNotificationType[];
  enabled?: boolean;
}

export interface TeamsChannelTestResponse {
  sent: boolean;
  detail?: string | null;
}

// ── Traffit — stan zaplanowanego importu Traffit → NEXUS (admin) ────────────

export interface TraffitPhaseState {
  phase: string;
  last_synced_at: string | null;
  last_run_started_at: string | null;
  last_run_finished_at: string | null;
  last_status: string | null;
  stats: Record<string, unknown> | null;
}

/** Wiersz, który nie zaimportował się N razy z rzędu i przestał blokować
 *  znacznik delty. Wymaga ręcznego rozstrzygnięcia — nie zniknie sam. */
export interface TraffitQuarantinedRow {
  phase: string;
  ref: string;
  attempts: number | null;
  last_seen: string | null;
}

export interface TraffitSyncStatus {
  enabled: boolean;
  running: boolean;
  max_row_attempts: number;
  quarantined: TraffitQuarantinedRow[];
  states: TraffitPhaseState[];
}

export const traffitSyncApi = {
  status: () =>
    api
      .get<TraffitSyncStatus>("/api/admin/traffit/sync/status")
      .then((r) => r.data),
};

// ── Zgłoszenia z publicznych aplikacji czekające na decyzję ────────────────

export interface ApplicationSubmission {
  id: number;
  status: string;
  submitted_first_name: string;
  submitted_last_name: string;
  submitted_email: string;
  submitted_phone: string | null;
  submitted_linkedin: string | null;
  submitted_message: string | null;
  matched_candidate_id: number | null;
  job_id: number | null;
  cv_filename: string | null;
  created_at: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
}

export type ApplicationResolveAction = "link" | "merge" | "create" | "reject";

export interface ApplicationResolveResult {
  id: number;
  status: string;
  candidate_id: number | null;
}

/** Backend twardo ogranicza `limit` do 500 (`Query(le=500)`). Bierzemy sufit,
 *  a UI mówi wprost, gdy lista dobiła do limitu — cicha truncacja w kolejce,
 *  której celem jest „nic nie ginie", byłaby sprzeczna sama ze sobą. */
export const APPLICATION_SUBMISSIONS_PAGE_LIMIT = 500;

export const applicationSubmissionsApi = {
  list: (status = "pending_review") =>
    api
      .get<ApplicationSubmission[]>("/api/application-submissions", {
        params: { status, limit: APPLICATION_SUBMISSIONS_PAGE_LIMIT },
      })
      .then((r) => r.data),
  resolve: (id: number, action: ApplicationResolveAction) =>
    api
      .post<ApplicationResolveResult>(
        `/api/application-submissions/${id}/resolve`,
        { action },
      )
      .then((r) => r.data),
};

export const teamsChannelsApi = {
  list: () => api.get<TeamsChannel[]>("/api/teams-channels").then((r) => r.data),
  create: (data: TeamsChannelCreateInput) =>
    api.post<TeamsChannel>("/api/teams-channels", data).then((r) => r.data),
  update: (id: number, data: TeamsChannelUpdateInput) =>
    api
      .patch<TeamsChannel>(`/api/teams-channels/${id}`, data)
      .then((r) => r.data),
  delete: (id: number) =>
    api.delete<void>(`/api/teams-channels/${id}`).then((r) => r.data),
  test: (id: number) =>
    api
      .post<TeamsChannelTestResponse>(`/api/teams-channels/${id}/test`)
      .then((r) => r.data),
};

export const cloudtalkApi = {
  listAgents: () =>
    api.get<CloudTalkAgent[]>("/api/cloudtalk/agents").then((r) => r.data),
  assignAgent: (agentId: number, userId: number) =>
    api.post(`/api/cloudtalk/agents/${agentId}/assign`, { user_id: userId }),
  unassignAgent: (agentId: number) =>
    api.delete(`/api/cloudtalk/agents/${agentId}/assign`),
  syncAgents: () =>
    api
      .post<SyncAgentsResponse>("/api/cloudtalk/sync-agents")
      .then((r) => r.data),
  initiateCall: (candidateId: number) =>
    api
      .post<InitiateCallResponse>("/api/cloudtalk/initiate-call", {
        candidate_id: candidateId,
      })
      .then((r) => r.data),
};

// ── DynaReporter (Faza B.1, migracja 0111+0112) ─────────────────────────────
// API client dla migracji DynaReportera. B.1 = tylko profile endpoint
// (walidacja wzorca). Kolejne moduły (KPI BL, Sales, Liga, etc.) w B.2.

export interface DynaReporterProfile {
  user_id: number;
  email: string;
  full_name: string;
  role: string;
  allowed_sections: string[];
  dynareporter_legacy_id: number | null;
}

export const dynareporterApi = {
  profile: () =>
    api
      .get<DynaReporterProfile>("/api/dynareporter/profile/me")
      .then((r) => r.data),
};

// ── B.2.1 KPI Body Leasing ─────────────────────────────────────────────────




// ── B.2.2 KPI Sales ────────────────────────────────────────────────────────



// `dynareporterSalesApi` usunięty 2026-07-20 — obsługiwał wyłącznie stronę raportową,
// której katalog został skasowany (następcą jest moduł Insights).

// ============================================================
// DynaReporter Rekrutacja mega-dashboard (port z artur-t-96/InfraReporter)
// ============================================================
export type DrRekrutacjaMetricValue = {
  value: number;
  target: number;
  percentage: number;
};

export type DrRekrutacjaUserMetrics = {
  verifications: DrRekrutacjaMetricValue;
  recommendations: DrRekrutacjaMetricValue;
  interviews: DrRekrutacjaMetricValue;
  placements: DrRekrutacjaMetricValue;
  quality_score: DrRekrutacjaMetricValue;
};

export type DrRekrutacjaTeamMember = {
  id: number;
  first_name: string;
  last_name: string;
  role: string;
  is_active: boolean;
  metrics: DrRekrutacjaUserMetrics;
  league_points: number;
  /**
   * Warunek udziału w Lidze Mistrzów — placement >= month_in_quarter
   * (1 placement/mc kalendarzowy = min 3/kwartał).
   */
  is_qualified?: boolean;
};

export type DrQuarterlyEntryRequirement = {
  min_placements: number;
  total_required: number;
  month_in_quarter: number;
  description: string;
};

export type DrRekrutacjaFunnelStage = {
  label: string;
  short_label: string;
  percentage: number;
  numerator: number;
  denominator: number;
};

export type DrRekrutacjaDashboard = {
  period: "week" | "month" | "year";
  period_label: string;
  period_start: string;
  period_end: string;
  team_summary: {
    total_verifications: number;
    total_recommendations: number;
    total_interviews: number;
    total_placements: number;
    average_quality_score: number;
  };
  funnel: DrRekrutacjaFunnelStage[];
  users: DrRekrutacjaTeamMember[];
  league_ranking: DrRekrutacjaTeamMember[];
  // Liga Mistrzów aggregowana po kwartale (Apr-Jun for Q2 2026) niezależnie
  // od filtru `period`. DR pokazuje quarterly podium.
  league_ranking_quarterly: DrRekrutacjaTeamMember[];
  quarter_label: string;  // np. "Q2 2026"
  quarter_start: string | null;
  quarter_end: string | null;
  /** Dni do końca kwartału (0 jeśli zakończony). */
  quarter_days_remaining: number;
  /** Procent kwartału ukończony (0-100). */
  quarter_progress: number;
  quarter_is_completed: boolean;
  quarter_entry_requirement: DrQuarterlyEntryRequirement | null;
  scoring: {
    placement: number;
    interview: number;
    recommendation: number;
    verification: number;
    // Prize amounts (PLN) — admin editable via /dynareporter/admin-dashboard
    // → Ustawienia. Previously hardcoded (Finding 30 from QA review).
    prize_1: number;
    prize_2: number;
    prize_3: number;
    // Business thresholds — admin editable.
    power_calling_min_per_day?: number;
    linkedin_cv_per_md_target?: number;
  };
};

export type DrRekrutacjaAvailableWeek = {
  week_number: number;
  year: number;
  label: string;
  has_data: boolean;
};

// ============================================================
// DynaReporter Delivery Lead dashboard (Session 2 port)
// ============================================================
export type DrDLMember = {
  id: number;
  name: string;
  is_active: boolean;
  requests: number;
  placements: number;
  vacancies: number;
  open_requests: number;
  open_vacancies: number;
  hit_ratio: number;
  fill_rate: number;
  avg_vacancies_per_request: number;
  hit_ratio_target: number;
  target_achieved: boolean;
  rank: number;
};

export type DrDLTeamStats = {
  active_dls_count?: number;
  total_requests: number;
  total_placements: number;
  total_vacancies: number;
  total_open_requests: number;
  total_open_vacancies: number;
  average_hit_ratio: number;
  average_fill_rate: number;
  achieving_target: number;
};

export type DrDLTeamHistoryRow = {
  month: string;
  requests: number;
  vacancies: number;
  placements: number;
  hit_ratio: number;
  fill_rate: number;
};



// ============================================================
// DynaReporter Rada Nadzorcza (Board) dashboard (Session 3 port)
// ============================================================
export type DrBoardPlacementClient = {
  client_name: string;
  count: number;
};

export type DrBoardMonthlyRow = {
  report_month: string; // YYYY-MM
  revenue: number;
  consultant_costs: number;
  other_costs: number;
  margin: number;
  profit: number;
  active_consultants: number;
  departures: number;
  placements: number;
  avg_margin_per_hour: number;
  hit_ratio: number;
  placement_clients: DrBoardPlacementClient[];
};

// ============================================================
// DynaReporter Admin dashboard (Session 4 port)
// ============================================================
export type DrAdminUserRow = {
  id: number;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
  allowed_sections: string[];
  dynareporter_legacy_id: number | null;
  kpi_entries_count: number;
};

export type DrUploadHistoryRow = {
  id: number;
  uploaded_by_id: number;
  uploaded_by_name: string;
  file_type: string;
  file_name: string;
  records_count: number;
  status: string;
  error_message: string | null;
  created_at: string;
};

export type DrAuditLogRow = {
  id: number;
  table_name: string;
  action: string;
  records_count: number;
  performed_by_id: number | null;
  performed_by_name: string | null;
  created_at: string;
  details: Record<string, unknown> | null;
};

export const dynareporterAdminApi = {
  users: () =>
    api
      .get<DrAdminUserRow[]>("/api/dynareporter/admin-dashboard/users")
      .then((r) => r.data),
  uploadHistory: (limit = 50) =>
    api
      .get<DrUploadHistoryRow[]>("/api/dynareporter/admin-dashboard/upload-history", {
        params: { limit },
      })
      .then((r) => r.data),
  auditLog: (limit = 100) =>
    api
      .get<DrAuditLogRow[]>("/api/dynareporter/admin-dashboard/audit-log", {
        params: { limit },
      })
      .then((r) => r.data),
};

// `dynareporterBoardApi` usunięty 2026-07-20 — obsługiwał wyłącznie stronę raportową,
// której katalog został skasowany (następcą jest moduł Insights).

// `DrDLUpsertPayload` usunięty 2026-07-20 — był bodym jedynej trasy zapisu
// (POST /delivery-lead-dashboard/entry), która zniknęła razem z ręcznym
// wprowadzaniem statystyk.

// `dynareporterDeliveryLeadApi` usunięty 2026-07-20 — obsługiwał wyłącznie stronę raportową,
// której katalog został skasowany (następcą jest moduł Insights).

// === Board Admin — USUNIĘTE 2026-07-20 =================================
// `dynareporterBoardAdminApi` (upsert + deleteMonthly) i typ `DrBoardUpsertPayload`
// znikły razem z ręcznym wprowadzaniem statystyk — endpointy zapisu nie istnieją
// już po stronie backendu. Odczyt (`GET /board-dashboard/monthly`) zostaje wyżej,
// bo karmi widoki historyczne. Typy `DrBoardMonthlyRow` i `DrBoardPlacementClient`
// ZOSTAJĄ — używa ich odczyt (7 miejsc poza tym plikiem).

// === Admin Config (Session 2) — Liga Mistrzów scoring ====================
export type DrScoringConfig = {
  placement: number;
  interview: number;
  recommendation: number;
  verification: number;
  // Prize amounts (PLN) — admin editable via ScoringConfig form.
  prize_1: number;
  prize_2: number;
  prize_3: number;
  // Business thresholds — admin editable.
  power_calling_min_per_day: number;
  linkedin_cv_per_md_target: number;
};

export const dynareporterAdminConfigApi = {
  getScoring: () =>
    api
      .get<DrScoringConfig>("/api/dynareporter/admin-config/scoring")
      .then((r) => r.data),
  updateScoring: (payload: DrScoringConfig) =>
    api
      .post<DrScoringConfig>("/api/dynareporter/admin-config/scoring", payload)
      .then((r) => r.data),
};

// === Admin HoF Manager (Session 3) ======================================
export type DrHoFWinnerCreatePayload = {
  competition_type: "quarterly" | "monthly_recommendations" | "monthly_placements";
  period: string;
  user_id: number;
  rank: 1 | 2 | 3;
  points?: number;
  metric_value?: number;
  prize?: string | null;
};

export const dynareporterAdminHofApi = {
  addWinner: (payload: DrHoFWinnerCreatePayload) =>
    api
      .post<{ id: number; ok: boolean }>("/api/dynareporter/admin-hof/winner", payload)
      .then((r) => r.data),
  deleteWinner: (winnerId: number) =>
    api.delete(`/api/dynareporter/admin-hof/winner/${winnerId}`).then((r) => r.data),
};

// === Admin Master Data Manager (Session 3) ==============================
export type DrAdminClientRow = {
  id: number;
  name: string;
  is_active: boolean;
  placements_count: number;
};
export type DrAdminConsultantRow = {
  id: number;
  name: string;
  is_active: boolean;
  default_cost_rate: number;
  default_revenue_rate: number;
};

export const dynareporterAdminMasterDataApi = {
  clients: () =>
    api
      .get<DrAdminClientRow[]>("/api/dynareporter/admin-master-data/clients")
      .then((r) => r.data),
  consultants: () =>
    api
      .get<DrAdminConsultantRow[]>("/api/dynareporter/admin-master-data/consultants")
      .then((r) => r.data),
  createClient: (payload: { name: string; is_active?: boolean }) =>
    api
      .post<DrAdminClientRow>(
        "/api/dynareporter/admin-master-data/clients",
        payload,
      )
      .then((r) => r.data),
  updateClient: (
    clientId: number,
    payload: { name?: string; is_active?: boolean },
  ) =>
    api
      .patch<DrAdminClientRow>(
        `/api/dynareporter/admin-master-data/clients/${clientId}`,
        payload,
      )
      .then((r) => r.data),
  deleteClient: (clientId: number) =>
    api
      .delete<void>(`/api/dynareporter/admin-master-data/clients/${clientId}`)
      .then((r) => r.data),
  createConsultant: (payload: {
    name: string;
    is_active?: boolean;
    default_cost_rate?: number;
    default_revenue_rate?: number;
  }) =>
    api
      .post<DrAdminConsultantRow>(
        "/api/dynareporter/admin-master-data/consultants",
        payload,
      )
      .then((r) => r.data),
  updateConsultant: (
    consultantId: number,
    payload: {
      name?: string;
      is_active?: boolean;
      default_cost_rate?: number;
      default_revenue_rate?: number;
    },
  ) =>
    api
      .patch<DrAdminConsultantRow>(
        `/api/dynareporter/admin-master-data/consultants/${consultantId}`,
        payload,
      )
      .then((r) => r.data),
  deleteConsultant: (consultantId: number) =>
    api
      .delete<void>(
        `/api/dynareporter/admin-master-data/consultants/${consultantId}`,
      )
      .then((r) => r.data),
};

// --- Admin Users / Team / DL Clients --------------------------------------
export type DrEmployeeRow = {
  id: number;
  email: string;
  name: string;  // Nexus users.name (single column)
  first_name: string | null;  // derived split (compat z DR)
  last_name: string | null;
  role: string;
  department: string | null;
  is_active: boolean;
  allowed_sections: string[];
  seniority_level: "junior" | "senior" | "expert" | null;
  acceleration_start_date: string | null;
  senior_since: string | null;
  expert_since: string | null;
};

export type DrTeamMember = {
  id: number;
  name: string;
  email: string;
  role: string;
};

export type DrTacDlAssignment = {
  tac_user_id: number;
  delivery_lead_user_id: number;
  tac_name: string;
  delivery_lead_name: string;
};

export type DrSourcerCategoryAssignment = {
  user_id: number;
  sourcer_name: string;
  category_id: number;
  category_name: string;
  priority: number;
};

export type DrDLClientAssignment = {
  id: number;
  delivery_lead_user_id: number;
  delivery_lead_name: string;
  client_id: number;
  client_name: string;
  is_head: boolean;
};

export const dynareporterAdminUsersApi = {
  employees: () =>
    api
      .get<DrEmployeeRow[]>("/api/dynareporter/admin-users/employees")
      .then((r) => r.data),
  setSeniority: (
    userId: number,
    payload: {
      seniority_level: "junior" | "senior" | "expert";
      acceleration_start_date?: string | null;
      senior_since?: string | null;
      expert_since?: string | null;
    },
  ) =>
    api
      .post<{ ok: boolean }>(
        `/api/dynareporter/admin-users/employees/${userId}/seniority`,
        payload,
      )
      .then((r) => r.data),
  toggleActive: (userId: number, isActive: boolean) =>
    api
      .post<{ ok: boolean; is_active: boolean }>(
        `/api/dynareporter/admin-users/employees/${userId}/active`,
        { is_active: isActive },
      )
      .then((r) => r.data),
  updateAllowedSections: (userId: number, sections: string[]) =>
    api
      .post<{ ok: boolean; allowed_sections: string[] }>(
        `/api/dynareporter/admin-users/employees/${userId}/allowed-sections`,
        { allowed_sections: sections },
      )
      .then((r) => r.data),
  teamMembers: () =>
    api
      .get<DrTeamMember[]>("/api/dynareporter/admin-users/team/members")
      .then((r) => r.data),
  tacDl: () =>
    api
      .get<DrTacDlAssignment[]>("/api/dynareporter/admin-users/team/tac-dl")
      .then((r) => r.data),
  sourcerCategories: () =>
    api
      .get<DrSourcerCategoryAssignment[]>(
        "/api/dynareporter/admin-users/team/sourcer-categories",
      )
      .then((r) => r.data),
  dlClients: () =>
    api
      .get<DrDLClientAssignment[]>("/api/dynareporter/admin-users/dl-clients")
      .then((r) => r.data),
  addDlClient: (payload: {
    delivery_lead_user_id: number;
    client_id: number;
    is_head?: boolean;
  }) =>
    api
      .post<{ id: number | null; ok: boolean }>(
        "/api/dynareporter/admin-users/dl-clients",
        payload,
      )
      .then((r) => r.data),
  patchDlClient: (assignmentId: number, isHead: boolean) =>
    api
      .patch<{ id: number; is_head: boolean; ok: boolean }>(
        `/api/dynareporter/admin-users/dl-clients/${assignmentId}`,
        { is_head: isHead },
      )
      .then((r) => r.data),
  deleteDlClient: (assignmentId: number) =>
    api
      .delete<void>(`/api/dynareporter/admin-users/dl-clients/${assignmentId}`)
      .then((r) => r.data),
  // === Recruitment Team — Categories + TAC-DL + Sourcer-Category CRUD ====
  competenceCategories: () =>
    api
      .get<DrCompetenceCategoryRow[]>(
        "/api/dynareporter/admin-users/team/categories",
      )
      .then((r) => r.data),
  addTacDl: (payload: { tac_user_id: number; delivery_lead_user_id: number }) =>
    api
      .post<{ ok: boolean }>(
        "/api/dynareporter/admin-users/team/tac-dl",
        payload,
      )
      .then((r) => r.data),
  deleteTacDl: (tacUserId: number, dlUserId: number) =>
    api
      .delete<void>(
        `/api/dynareporter/admin-users/team/tac-dl/${tacUserId}/${dlUserId}`,
      )
      .then((r) => r.data),
  upsertSourcerCategory: (payload: {
    user_id: number;
    category_id: number;
    priority: number;
  }) =>
    api
      .post<{ ok: boolean }>(
        "/api/dynareporter/admin-users/team/sourcer-categories",
        payload,
      )
      .then((r) => r.data),
  deleteSourcerCategory: (userId: number, categoryId: number) =>
    api
      .delete<void>(
        `/api/dynareporter/admin-users/team/sourcer-categories/${userId}/${categoryId}`,
      )
      .then((r) => r.data),
};

export type DrCompetenceCategoryRow = {
  id: number;
  name: string;
  color: string;
  sort_order: number;
  is_active: boolean;
};

// Sales mgmt + Przetargi admin API clients usunięte 2026-05-19 — Nexus nie ma
// głównych dashboardów Sales/Przetargi, więc admin entry dla tych modułów
// nie był potrzebny. Backend endpointy `/api/dynareporter/sales-mgmt/*` i
// `/api/dynareporter/przetargi/*` (read-only) zostają na backend dla MINDY AI
// kontekstu (jeśli kiedyś dashboardy wrócą).

// Sub-sections: Hall of Fame, Yearly Stats, Monthly Race, Power Calling, LinkedIn
export type DrHallOfFameEntry = {
  id: number;  // PK z dr_competition_winners — używane przez admin delete UI
  competition_type:
    | "quarterly"
    | "monthly_recommendations"
    | "monthly_placements";
  period: string;
  rank: 1 | 2 | 3;
  user_id: number;
  user_name: string;
  points: number;
  metric_value: number;
  prize: string | null;
};

export type DrYearlyStatsRow = {
  week_label: string;
  week_number: number;
  year: number;
  verifications: number;
  recommendations: number;
  interviews: number;
  placements: number;
};

export type DrMonthlyRaceEntry = {
  user_id: number;
  user_name: string;
  role: string;
  metric_value: number;
  per_day: number;
  verifications: number;
  days_worked: number;
  verifications_per_day: number;
  precision_rate: number;
  meets_verification_requirement: boolean;
  meets_precision_requirement: boolean;
  is_qualified: boolean;
  is_excluded: boolean;
};

export type DrMonthlyRace = {
  competition_type: "recommendations" | "placements";
  month: string;
  voucher: string;
  requirement: string;
  entries: DrMonthlyRaceEntry[];
  period: string;
  month_name: string;
  year: number;
  days_remaining: number;
  is_completed: boolean;
  min_qualification: number | null;
  verification_requirement: number | null;
  precision_rate_requirement: number | null;
  is_precision_rate_active: boolean;
  tie_breaker: string;
  is_last_month_of_quarter: boolean;
  excluded_user_id: number | null;
  current_leader_id: number | null;
  prize: string;
};

export type DrPowerCallingEntry = {
  user_id: number;
  user_name: string;
  role: string;
  verifications: number;
  days_worked: number;
  per_day: number;
  week_label: string;
};

export type DrLinkedInPerformanceRow = {
  user_id: number;
  user_name: string;
  role: string;
  cv_added: number;
  messages_sent: number;
  responses_received: number;
  response_rate: number;
  cv_per_md: number;
};

export const dynareporterRekrutacjaApi = {
  dashboard: (params: {
    period: "week" | "month" | "year";
    date?: string; // YYYY-MM-DD for month/year
    weekNumber?: number;
    year?: number;
  }) =>
    api
      .get<DrRekrutacjaDashboard>("/api/dynareporter/rekrutacja/dashboard", { params })
      .then((r) => r.data),

  availableWeeks: (params?: { limit?: number }) =>
    api
      .get<DrRekrutacjaAvailableWeek[]>("/api/dynareporter/rekrutacja/available-weeks", {
        params,
      })
      .then((r) => r.data),

  hallOfFame: (limit = 100) =>
    api
      .get<DrHallOfFameEntry[]>("/api/dynareporter/rekrutacja/hall-of-fame", {
        params: { limit },
      })
      .then((r) => r.data),

  yearlyStats: (year?: number) =>
    api
      .get<DrYearlyStatsRow[]>("/api/dynareporter/rekrutacja/yearly-stats", {
        params: year !== undefined ? { year } : undefined,
      })
      .then((r) => r.data),

  monthlyRace: (
    competition_type: "recommendations" | "placements",
    month?: string,
  ) =>
    api
      .get<DrMonthlyRace>("/api/dynareporter/rekrutacja/monthly-race", {
        params: { competition_type, month },
      })
      .then((r) => r.data),

  powerCalling: (params?: { week_number?: number; year?: number }) =>
    api
      .get<DrPowerCallingEntry[]>("/api/dynareporter/rekrutacja/power-calling", {
        params,
      })
      .then((r) => r.data),

  linkedinPerformance: (params: {
    period: "week" | "month" | "year";
    date?: string;
    weekNumber?: number;
    year?: number;
  }) =>
    api
      .get<DrLinkedInPerformanceRow[]>(
        "/api/dynareporter/rekrutacja/linkedin-performance",
        { params },
      )
      .then((r) => r.data),

  accelerationPath: () =>
    api
      .get<DrAccelerationPath>("/api/dynareporter/rekrutacja/acceleration-path")
      .then((r) => r.data),
  placementAnalysis: (params?: {
    period?: "week" | "month" | "year";
    date?: string;
    week_number?: number;
    year?: number;
  }) =>
    api
      .get<DrPlacementAnalysis>(
        "/api/dynareporter/rekrutacja/placement-analysis",
        { params },
      )
      .then((r) => r.data),
  teamPanel: () =>
    api
      .get<DrTeamPanel>("/api/dynareporter/rekrutacja/team-panel")
      .then((r) => r.data),
};

export type DrPlacementByPerson = {
  user_id: number;
  user_name: string;
  role: string;
  count: number;
};
export type DrPlacementByClient = {
  client_id: number;
  client_name: string;
  count: number;
};
export type DrPlacementAnalysis = {
  by_person: DrPlacementByPerson[];
  by_client: DrPlacementByClient[];
  total: number;
};
export type DrTeamPanelSourcer = {
  user_id: number;
  name: string;
  priority: number;
};
export type DrTeamPanelCategory = {
  category_id: number;
  category_name: string;
  first_priority: DrTeamPanelSourcer[];
  second_priority: DrTeamPanelSourcer[];
};
export type DrTeamPanelTacDl = {
  dl_user_id: number;
  dl_name: string;
  tac_names: string[];
};
export type DrTeamPanel = {
  sourcer_categories: DrTeamPanelCategory[];
  tac_dl: DrTeamPanelTacDl[];
};

export type DrAccelerationPathEntry = {
  user_id: number;
  user_name: string;
  role: string;
  start_date: string;
  months_elapsed: number;
  placements_6m: number;
  placements_12m: number;
  threshold_6m: number;
  threshold_12m: number;
  status: string;
  next_promotion_date: string | null;
};

export type DrAccelerationPath = {
  junior_to_senior: DrAccelerationPathEntry[];
  senior_to_expert: DrAccelerationPathEntry[];
  junior_count: number;
  senior_count: number;
  expert_count: number;
  ready_for_promotion: number;
};

// `dynareporterBodyLeasingApi` usunięty 2026-07-20 — obsługiwał wyłącznie stronę raportową,
// której katalog został skasowany (następcą jest moduł Insights).

// `dynareporterPlacementsApi.createWithDl` i typ `DrPlacementWithDlPayload`
// usunięte 2026-07-20. Modal „Dodaj placement" zapisywał zdarzenie biznesowe
// (sourcer + DL + klient + data umowy) do dr_placement_details i doliczał +1
// do panelu DL. Źródłem prawdy o placementach jest teraz model Contract
// w NEXUS-ie (481 kontraktów od 2022), a liczby pokazuje /insights.

export default api;
