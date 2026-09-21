/**
 * Shared types + helpers for the B2B CV generator surfaces.
 *
 * Single source of truth for the modal (CVGeneratorV2), the standalone page
 * (CVGeneratorStandaloneV2) and the B2B contract generator — previously each
 * kept its own copy of these utilities and they had already started to drift.
 */

import { apiErrorMessage } from "@/lib/api-error";

/**
 * Interaktywne CV (kafelki wymagań, czat, przełącznik widoku) — wyłączone
 * 21.09.2026 razem z backendowym `CV_INTERACTIVE_ENABLED`. Ukrywa kontrolki,
 * których wynik i tak by nie powstał; powrót = `true` tu i flaga w Coolify.
 */
export const CV_INTERACTIVE_UI_ENABLED = false;

/**
 * Linki do CV dla klienta (udostępnianie wygenerowanego / brandowanego CV,
 * link do karty Championa w wysyłce, mail do klienta) — wyłączone 21.09.2026:
 * CV nie są dziś wysyłane klientom przez NEXUS. Kod zostaje; powrót = `true`.
 */
export const CV_CLIENT_LINKS_UI_ENABLED = false;

export type RecruitmentOption = {
  stage_id: number;
  job_id: number;
  job_title: string;
  stage: string;
  has_champion: boolean;
  has_notes: boolean;
  has_cv: boolean;
  // Długość notatek, które poszłyby do modelu — reguła klienta może wymagać
  // minimum, a formularz ma to pokazać PRZED kliknięciem (0267).
  notes_chars?: number;
  ready: boolean;
  content_mode?: CvContentMode;
  required_champion?: boolean;
  required_notes_min_chars?: number;
  missing_inputs?: string[];
  // Klient tej rekrutacji — wyprowadzany z oferty po stronie serwera. Front go
  // POKAZUJE, nigdy nie wybiera: możliwość rozjazdu z ofertą oznaczałaby
  // zastosowanie reguł (nazwa pliku, język) innego klienta niż widać na ekranie.
  client_id?: number | null;
  client_name?: string | null;
  /** Czy wołający może przypiąć do tej rekrutacji wydarzenie (członkostwo). */
  can_schedule?: boolean;
};

export const CV_ACCEPT = ".pdf,.docx";
export const CHAMPION_ACCEPT = ".docx";
export const MAX_UPLOAD_MB = 50;

/**
 * Jak mocno generator ma obrabiać treść CV. Wysyłane jako `content_mode`
 * (pole JSON w trybie „new", pole formularza multipart w trybie „old").
 */
export type CvContentMode = "basic" | "polished" | "tailored";

/**
 * Domyślny tryb wysyłany przez UI. Świadomie „polished", NIE „tailored":
 * wariant najmocniej dopasowany do ogłoszenia nie może być tym, który dostajesz
 * bez podjęcia decyzji — część klientów wymaga profili nieprofilowanych.
 */
export const DEFAULT_CV_CONTENT_MODE: CvContentMode = "polished";

export type CvContentModeOption = {
  value: CvContentMode;
  label: string;
  description: string;
  /**
   * Ograniczenie zastosowania. Trzymane osobno od `description`, żeby dało się
   * je wyróżnić wizualnie — ma być czytelne wprost, nie schowane pod ikonką.
   */
  caution?: string;
};

/**
 * Trzy RÓWNORZĘDNE zastosowania, nie trzy poziomy jakości — stąd brak numeracji,
 * gwiazdek i nazw typu „basic/pro". Kolejność odpowiada wartościom kontraktu API.
 */
export const CV_CONTENT_MODES: readonly CvContentModeOption[] = [
  {
    value: "basic",
    label: "Przepisanie",
    description:
      "Tylko fakty z CV kandydata, bez obróbki językowej i bez dopasowania do rekrutacji.",
  },
  {
    value: "polished",
    label: "Redakcja",
    description:
      "Te same fakty, poprawiony język i uporządkowana terminologia. Bez dopasowania do rekrutacji.",
  },
  {
    value: "tailored",
    label: "Pod rekrutację",
    description:
      "Treść ułożona pod wymagania z ogłoszenia: kolejność, akcenty i wyróżnienia.",
    caution: "Nie używaj dla klientów wymagających profili nieprofilowanych.",
  },
];

/**
 * Prefiksy, którymi backend oznacza PEWNE trafienia bezpiecznika — liczbę albo
 * twierdzenie, którego w źródłowym CV po prostu nie ma. Miękkie podpowiedzi
 * („WERYFIKUJ" / „VERIFY") nie są tu wymienione celowo: klasyfikujemy po tym,
 * co jest pewne, a wszystko inne traktujemy jako do sprawdzenia.
 *
 * MUSI być zgodne z `_HIGH_PREFIX` w
 * `backend/app/services/cv_generator_b2b/standalone_service.py`.
 *
 * Obie wersje językowe są wymagane, bo o języku decyduje generacja, nie stan
 * komponentu: wiersz wygenerowany po angielsku ma uwagi „NOT IN SOURCE", a
 * lista bywa oglądana długo po tym, jak przełącznik języka wrócił na polski.
 */
export const CV_CERTAIN_WARNING_PREFIXES = [
  "BRAK POKRYCIA",
  "NOT IN SOURCE",
] as const;

/** Czy uwaga bezpiecznika jest trafieniem pewnym (a nie podpowiedzią). */
export function isCertainWarning(warning: string): boolean {
  return CV_CERTAIN_WARNING_PREFIXES.some((p) => warning.startsWith(p));
}

/**
 * Client-side upload precheck. Mirrors the server's `_validate_upload`
 * (`standalone_service.py`) so a file the backend would reject never costs the
 * recruiter a round trip — the server remains the authority.
 *
 * Returns a Polish message, or `null` when the file is acceptable.
 */
export function fileValidationError(file: File, accept: string): string | null {
  // `lastIndexOf` (not `split(".").pop()`): an extensionless "ProfilChampiona"
  // used to report a nonsense extension of '.profilchampiona'. Trim first so a
  // trailing space in the filename does not defeat the allowlist.
  const name = file.name.trim().toLowerCase();
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? name.slice(dot) : "";
  const allowed = accept.split(",").map((s) => s.trim().toLowerCase());
  if (!ext) {
    return `Plik nie ma rozszerzenia. Dozwolone: ${allowed.join(", ")}.`;
  }
  if (ext === ".doc") {
    return "Format .doc (Word 97-2003) nie jest obsługiwany — zapisz plik jako .docx lub PDF.";
  }
  if (!allowed.includes(ext)) {
    return `Nieobsługiwany format '${ext}'. Dozwolone: ${allowed.join(", ")}.`;
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `Plik za duży (${Math.round(file.size / 1024 / 1024)} MB). Maksymalny rozmiar to ${MAX_UPLOAD_MB} MB.`;
  }
  return null;
}

export const STAGE_LABELS: Record<string, string> = {
  new: "Nowy",
  contacted: "Kontakt",
  screening: "Screening",
  verified: "Zweryfikowany",
  interview: "Interview",
  client_review: "U klienta",
  cv_sent: "CV wysłane",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  active: "Aktywny",
  hired: "Zatrudniony",
  rejected: "Odrzucony",
  withdrawn: "Rezygnacja",
  on_hold: "Wstrzymany",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export function parseDispositionFilename(
  disposition: string,
  fallback: string,
): string {
  // Prefer the RFC 5987 `filename*=UTF-8''<percent-encoded>` parameter — it
  // carries the real name including Polish characters (ł, ą, ż…). Fall back to
  // the ASCII `filename="…"` for responses that don't set the extended form.
  const extended = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (extended) {
    try {
      return decodeURIComponent(extended[1]);
    } catch {
      // Malformed percent-encoding — fall through to the plain parameter.
    }
  }
  const match = disposition.match(/filename="?([^";]+)"?/);
  return match ? match[1] : fallback;
}

export function parseWarningsHeader(header: unknown): string[] {
  if (typeof header !== "string") return [];
  try {
    const parsed = JSON.parse(header);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Kwota AI / AI wyłączone: `503 {detail: {feature, reason, used, limit}}`
 * (`_charge_cv_generation_quota` w `cv_generator_b2b.py`). `reason` jest po
 * polsku i mówi, CZY to decyzja administratora — bez tej gałęzi rekruter
 * widział ogólne „Nie udało się uruchomić generacji" i szukał awarii.
 */
function quotaMessage(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return undefined;
  const { reason, used, limit } = detail as {
    reason?: unknown;
    used?: unknown;
    limit?: unknown;
  };
  if (typeof reason !== "string" || !reason.trim()) return undefined;
  if (typeof used === "number" && typeof limit === "number") {
    return `${reason} (wykorzystano ${used}/${limit})`;
  }
  return reason;
}

function messageFromBody(status: number | undefined, data: unknown): string {
  if (typeof data === "string") return data;
  const detail = (data as { detail?: unknown } | null | undefined)?.detail;
  const quota = quotaMessage(detail);
  if (quota) return quota;
  // String, `{message}` i TABLICA błędów walidacji — wspólne tłumaczenie,
  // żeby obiekt nigdy nie dotarł do toasta jako „[object Object]".
  return apiErrorMessage({ response: { status, data } }, "");
}

/**
 * Tekst błędu generatora CV dla użytkownika — zawsze string, `""` gdy nie ma
 * nic do pokazania (wołający podstawia własny komunikat).
 */
export async function extractErrorDetail(err: unknown): Promise<string> {
  if (typeof err !== "object" || err === null) return "";
  const response = (err as { response?: { status?: unknown; data?: unknown } })
    .response;
  const status = typeof response?.status === "number" ? response.status : undefined;
  const data = response?.data;
  // With responseType: "blob" axios delivers error bodies as a Blob too, so the
  // backend's JSON {detail} must be read out of the Blob before it can surface.
  if (data instanceof Blob) {
    try {
      const parsed: unknown = JSON.parse(await data.text());
      return messageFromBody(status, parsed);
    } catch {
      return "";
    }
  }
  return messageFromBody(status, data);
}

/** Sufit `q` w `GET /api/cv-generator/candidates` (`max_length=120`). */
export const CANDIDATE_SEARCH_MAX_LENGTH = 120;

/**
 * Komunikat pola wyszukiwania kandydata albo `null`. Za długie zapytanie
 * kończyło się 422, które combobox pokazywał jako „Brak wyników" — czyli
 * jako fakt o bazie, a nie jako błąd wpisu.
 */
export function candidateSearchMessage(query: string, error: unknown): string | null {
  if (query.trim().length > CANDIDATE_SEARCH_MAX_LENGTH) {
    return `Wpisz najwyżej ${CANDIDATE_SEARCH_MAX_LENGTH} znaków — skróć wyszukiwaną frazę.`;
  }
  if (!error) return null;
  return apiErrorMessage(error, "Nie udało się wyszukać kandydatów — spróbuj ponownie.");
}

/** Pola reguły klienta, od których zależą wymagane wejścia generacji. */
export type CvRequirementRule = {
  require_screening_notes_min_chars?: number | null;
  require_project_ref?: boolean;
  require_position?: boolean;
  require_champion?: boolean;
  filename_pattern?: string | null;
};

/** Czy formularz musi pokazać pole „Numer / nazwa projektu". */
export function ruleNeedsProjectRef(rule: CvRequirementRule | null | undefined): boolean {
  return !!rule && (!!rule.filename_pattern?.includes("{PROJEKT}") || !!rule.require_project_ref);
}

/**
 * Braki względem OBOWIĄZUJĄCEJ reguły klienta — te same zdania, które zwróci
 * 422 serwera (`required_input_problems`), pokazane przed kliknięciem.
 * Jedno źródło dla strony generatora i okna z profilu kandydata.
 */
export function clientRuleRequirementProblems(
  rule: CvRequirementRule | null | undefined,
  input: {
    mode: "new" | "old";
    notesChars: number;
    projectRef: string;
    position: string;
    hasChampionInput: boolean;
  },
): string[] {
  if (!rule) return [];
  const problems: string[] = [];
  const min = rule.require_screening_notes_min_chars ?? 0;
  if (min > 0 && input.notesChars < min) {
    problems.push(
      `Ten klient wymaga notatek ze screeningu o długości co najmniej ${min} znaków — jest ${input.notesChars}.`,
    );
  }
  if (rule.require_project_ref && !input.projectRef.trim()) {
    problems.push("Ten klient wymaga numeru projektu — uzupełnij pole „Numer / nazwa projektu”.");
  }
  if (rule.require_position && input.mode === "old" && !input.position.trim()) {
    problems.push("Ten klient wymaga stanowiska — uzupełnij pole „Stanowisko”.");
  }
  if (rule.require_champion && !input.hasChampionInput) {
    problems.push(
      input.mode === "new"
        ? "Ten klient wymaga Profilu Championa — uzupełnij go na karcie rekrutacji przed generacją."
        : "Ten klient wymaga wymagań z Profilu Championa — wgraj plik championa albo wpisz wymagania must-have / nice-to-have.",
    );
  }
  return problems;
}
