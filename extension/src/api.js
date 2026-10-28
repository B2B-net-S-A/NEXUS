// Klient API wtyczki (`/api/extension/*`, kontrakt w API.md).
// Każdy błąd zamienia na `ApiError` z `kind`, z którego panel wybiera stan.
// Bez `chrome.*` — połączenie i fetch przychodzą z zewnątrz (testy w node).

export const ERROR_KINDS = Object.freeze({
  NOT_CONNECTED: "not_connected", // brak klucza w storage
  KEY_INVALID: "key_invalid", // 401 → ekran „Połącz”
  FORBIDDEN: "forbidden", // 403 → zdanie z `detail`
  OFF_LIMITS: "off_limits", // 409 off_limits_confirmation_required → pytanie „Jak się zgłosił?”
  CONFLICT: "conflict", // inne 409
  DAILY_LIMIT: "daily_limit", // 429 extension_daily_limit
  RATE_LIMITED: "rate_limited", // inne 429
  BAD_REQUEST: "bad_request", // 400/404/422
  SERVER: "server", // 5xx
  NETWORK: "network", // brak połączenia, timeout
  BAD_RESPONSE: "bad_response", // odpowiedź nie jest oczekiwanym JSON-em
});

export class ApiError extends Error {
  /**
   * @param {string} kind jeden z ERROR_KINDS
   * @param {{status?: number, detail?: unknown, message?: string}} [info]
   */
  constructor(kind, info = {}) {
    super(info.message || kind);
    this.name = "ApiError";
    this.kind = kind;
    this.status = info.status ?? null;
    this.detail = info.detail ?? null;
  }
}

function detailText(detail) {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") return detail.message;
  return null;
}

// Kody maszynowe w `detail` nie są zdaniami dla człowieka.
const looksLikeCode = (text) => /^[a-z0-9_]+$/.test(text);

/** Odpowiedź HTTP z błędem → ApiError. `body` to sparsowany JSON albo null. */
export function errorFromResponse(status, body) {
  const detail = body && typeof body === "object" ? body.detail : null;
  const code = typeof detail === "string" ? detail : detail && typeof detail === "object" ? detail.code : null;
  const text = detailText(detail);
  const human = text && !looksLikeCode(text) ? text : null;

  if (status === 401) {
    return new ApiError(ERROR_KINDS.KEY_INVALID, { status, detail, message: "Połączenie z NEXUSEM wygasło. Połącz wtyczkę ponownie." });
  }
  if (status === 403) {
    return new ApiError(ERROR_KINDS.FORBIDDEN, { status, detail, message: human || "Nie masz uprawnień do tej czynności w NEXUSIE." });
  }
  if (status === 409 && code === "off_limits_confirmation_required") {
    return new ApiError(ERROR_KINDS.OFF_LIMITS, { status, detail, message: "Firma jest off-limits. Wskaż, jak osoba się do nas zgłosiła." });
  }
  if (status === 409) {
    return new ApiError(ERROR_KINDS.CONFLICT, { status, detail, message: human || "NEXUS odrzucił zapis (konflikt danych)." });
  }
  if (status === 429 && code === "extension_daily_limit") {
    return new ApiError(ERROR_KINDS.DAILY_LIMIT, { status, detail, message: "Dzisiejszy limit odczytów wyczerpany, wróć jutro." });
  }
  if (status === 429) {
    return new ApiError(ERROR_KINDS.RATE_LIMITED, { status, detail, message: "Za dużo zapytań naraz. Odczekaj chwilę i spróbuj ponownie." });
  }
  if (status >= 500) {
    return new ApiError(ERROR_KINDS.SERVER, { status, detail, message: `NEXUS odpowiedział błędem (${status}). Spróbuj ponownie za chwilę.` });
  }
  return new ApiError(ERROR_KINDS.BAD_REQUEST, {
    status,
    detail,
    message: human || `NEXUS nie przyjął zapytania (${status}).`,
  });
}

const DEFAULT_TIMEOUT_MS = 25000;

/**
 * @param {{
 *   getConnection: () => Promise<{key: string, apiBase: string} | null>,
 *   fetchImpl?: typeof fetch,
 *   onKeyInvalid?: () => void,
 *   timeoutMs?: number,
 * }} options
 */
export function createApi({ getConnection, fetchImpl = (...a) => fetch(...a), onKeyInvalid = () => {}, timeoutMs = DEFAULT_TIMEOUT_MS }) {
  async function request(method, path, { json, form, query } = {}) {
    const conn = await getConnection();
    if (!conn) throw new ApiError(ERROR_KINDS.NOT_CONNECTED, { message: "Wtyczka nie jest połączona z NEXUSEM." });

    let url = `${conn.apiBase}/api/extension${path}`;
    if (query) {
      const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== ""));
      if ([...qs].length) url += `?${qs}`;
    }
    const headers = { "X-Extension-Key": conn.key, Accept: "application/json" };
    let body;
    if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(json);
    } else if (form) {
      body = form; // przeglądarka sama ustawia boundary multipart
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res;
    try {
      res = await fetchImpl(url, { method, headers, body, signal: controller.signal });
    } catch (err) {
      throw new ApiError(ERROR_KINDS.NETWORK, {
        message: "Nie udało się połączyć z NEXUSEM. Spróbuj ponownie.",
        detail: String(err?.message || err),
      });
    } finally {
      clearTimeout(timer);
    }

    let data = null;
    const text = await res.text().catch(() => "");
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }
    if (!res.ok) {
      const err = errorFromResponse(res.status, data);
      if (err.kind === ERROR_KINDS.KEY_INVALID) onKeyInvalid();
      throw err;
    }
    if (data === null || typeof data !== "object") {
      throw new ApiError(ERROR_KINDS.BAD_RESPONSE, { status: res.status, message: "NEXUS zwrócił nieoczekiwaną odpowiedź." });
    }
    return data;
  }

  const id = (candidateId) => encodeURIComponent(String(candidateId));

  return {
    me: () => request("GET", "/me"),
    lookup: async (profile) => validateLookup(await request("POST", "/lookup", { json: profile })),
    // Bez `job_id` i bez procentów — % dla 50 osób z samego nagłówka to 50 wywołań embeddingów.
    lookupBatch: async (people) => {
      const data = await request("POST", "/lookup-batch", { json: { people } });
      if (!Array.isArray(data.items)) throw new ApiError(ERROR_KINDS.BAD_RESPONSE, { message: "NEXUS zwrócił nieoczekiwaną odpowiedź." });
      return data;
    },
    jobs: (q = "") => request("GET", "/jobs", { query: { q } }),
    addCandidate: (profile, jobIds = [], offLimitsHow = null) =>
      request("POST", "/candidates", { json: { profile, job_ids: jobIds, off_limits_how: offLimitsHow } }),
    addToJobs: (candidateId, jobIds, offLimitsHow = null) =>
      request("POST", `/candidates/${id(candidateId)}/jobs`, { json: { job_ids: jobIds, off_limits_how: offLimitsHow } }),
    refresh: (candidateId, profile) => request("POST", `/candidates/${id(candidateId)}/refresh`, { json: { profile } }),
    addContact: (candidateId, { channel, jobId = null, note = "", remindInDays = null }) =>
      request("POST", `/candidates/${id(candidateId)}/contacts`, {
        json: { channel, job_id: jobId, note, remind_in_days: remindInDays },
      }),
    addNote: (candidateId, text) => request("POST", `/candidates/${id(candidateId)}/notes`, { json: { text } }),
    uploadProfilePdf: (candidateId, file) => {
      const form = new FormData();
      form.append("file", file, file.name || "profil-linkedin.pdf");
      return request("POST", `/candidates/${id(candidateId)}/profile-pdf`, { form });
    },
    draftMessage: (jobId, kind, profile) => request("POST", "/draft-message", { json: { job_id: jobId, kind, profile } }),
  };
}

const LOOKUP_STATUSES = new Set(["found", "not_found", "ambiguous"]);

/**
 * Granica systemu: odpowiedź lookup bez znanego `status` to awaria, a nie
 * „Nie ma w NEXUSIE” — inaczej rekruter dodałby duplikat.
 */
export function validateLookup(data) {
  if (!data || !LOOKUP_STATUSES.has(data.status)) {
    throw new ApiError(ERROR_KINDS.BAD_RESPONSE, { message: "NEXUS zwrócił nieoczekiwaną odpowiedź przy sprawdzaniu osoby." });
  }
  if (data.status === "found" && !data.candidate) {
    throw new ApiError(ERROR_KINDS.BAD_RESPONSE, { message: "NEXUS zwrócił nieoczekiwaną odpowiedź przy sprawdzaniu osoby." });
  }
  return {
    ...data,
    processes: Array.isArray(data.processes) ? data.processes : [],
    contacts: Array.isArray(data.contacts) ? data.contacts : [],
    matches: Array.isArray(data.matches) ? data.matches : [],
    ambiguous: Array.isArray(data.ambiguous) ? data.ambiguous : [],
  };
}
