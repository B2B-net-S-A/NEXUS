/**
 * Shared types + helpers for the B2B CV generator surfaces.
 *
 * Single source of truth for the modal (CVGeneratorV2), the standalone page
 * (CVGeneratorStandaloneV2) and the B2B contract generator — previously each
 * kept its own copy of these utilities and they had already started to drift.
 */

export type RecruitmentOption = {
  stage_id: number;
  job_id: number;
  job_title: string;
  stage: string;
  has_champion: boolean;
  has_notes: boolean;
  has_cv: boolean;
  ready: boolean;
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
      "Tylko fakty z CV kandydata, bez obróbki językowej i bez dopasowania do oferty.",
  },
  {
    value: "polished",
    label: "Redakcja",
    description:
      "Te same fakty, poprawiony język i uporządkowana terminologia. Bez dopasowania do oferty.",
  },
  {
    value: "tailored",
    label: "Pod ofertę",
    description:
      "Treść ułożona pod wymagania z ogłoszenia: kolejność, akcenty i wyróżnienia.",
    caution: "Nie używaj dla klientów wymagających profili nieprofilowanych.",
  },
];

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

export async function extractErrorDetail(err: unknown): Promise<string> {
  if (typeof err !== "object" || err === null) return "";
  const anyErr = err as { response?: { data?: unknown } };
  const data = anyErr.response?.data;
  // With responseType: "blob" axios delivers error bodies as a Blob too, so the
  // backend's JSON {detail} must be read out of the Blob before it can surface.
  if (data instanceof Blob) {
    try {
      const txt = await data.text();
      const parsed = JSON.parse(txt);
      if (typeof parsed?.detail === "string") return parsed.detail;
      return txt;
    } catch {
      return "";
    }
  }
  if (typeof data === "string") return data;
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return "";
}
