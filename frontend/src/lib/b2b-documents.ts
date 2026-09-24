// Czyste reguły generatora dokumentów pochodnych (aneksy, rozwiązania, umowa
// przedwstępna) — wyniesione z komponentów, żeby dało się je sprawdzić bez
// montowania formularza. Definicje pól są lustrem
// `backend/app/services/b2b_documents/registry.py` (przychodzą z API).

import type {
  DocumentFamily,
  DocumentFieldDef,
  DocumentFieldGroup,
  DocumentItem,
  DocumentRequestBody,
  DocumentTypeDef,
  DocumentValue,
  DocumentValues,
} from "@/lib/api/b2bDocuments";
import { messageFromApiResponse } from "@/lib/api-error";

// ── Etykiety ────────────────────────────────────────────────────────────────

export const FAMILY_ORDER: readonly DocumentFamily[] = [
  "annex",
  "termination",
  "preliminary",
] as const;

export const FAMILY_LABELS: Record<DocumentFamily, string> = {
  annex: "Aneksy",
  termination: "Rozwiązanie umowy",
  preliminary: "Umowa przedwstępna",
};

export const GROUP_LABELS: Record<DocumentFieldGroup, string> = {
  document: "Dokument",
  partner: "Partner",
  base: "Umowa bazowa",
};

const GROUP_ORDER: readonly DocumentFieldGroup[] = ["document", "partner", "base"];

export const LANGUAGE_LABELS: Record<string, string> = {
  pl: "Polski",
  en: "Angielski",
};

/** Zdanie przy polach, których serwer nie zapisuje. */
export const SENSITIVE_NOTE = "Nie zapisujemy — trafi tylko do dokumentu";

/** Typy pogrupowane w rodziny, w stałej kolejności kart kreatora. */
export function typesByFamily(
  types: DocumentTypeDef[],
): { family: DocumentFamily; label: string; types: DocumentTypeDef[] }[] {
  return FAMILY_ORDER.map((family) => ({
    family,
    label: FAMILY_LABELS[family],
    types: types.filter((t) => t.family === family),
  })).filter((group) => group.types.length > 0);
}

// ── Widoczność i wymagane pola ──────────────────────────────────────────────

/** Lustro `registry.visible`: `show_if` = (klucz, wartość) porównane wprost. */
export function isFieldVisible(
  field: Pick<DocumentFieldDef, "show_if">,
  values: DocumentValues,
): boolean {
  if (!field.show_if) return true;
  const [key, expected] = field.show_if;
  // Dokładnie jak serwer (`values.get(key) == expected`) — inna reguła
  // widoczności dałaby formularz, który serwer waliduje inaczej, niż wygląda.
  return values[key] === expected;
}

export function visibleFields(
  type: DocumentTypeDef,
  values: DocumentValues,
): DocumentFieldDef[] {
  return type.fields.filter((f) => isFieldVisible(f, values));
}

/** Widoczne pola w grupach Dokument → Partner → Umowa bazowa (puste odpadają). */
export function groupedFields(
  type: DocumentTypeDef,
  values: DocumentValues,
): { group: DocumentFieldGroup; label: string; fields: DocumentFieldDef[] }[] {
  const visible = visibleFields(type, values);
  return GROUP_ORDER.map((group) => ({
    group,
    label: GROUP_LABELS[group],
    fields: visible.filter((f) => (f.group ?? "document") === group),
  })).filter((g) => g.fields.length > 0);
}

function isEmpty(value: DocumentValue | undefined): boolean {
  return (
    value === undefined ||
    value === null ||
    (typeof value === "string" && value.trim() === "")
  );
}

/** Lustro `registry.missing_required`: etykiety widocznych pól bez wartości. */
export function missingRequired(
  type: DocumentTypeDef,
  values: DocumentValues,
): string[] {
  return visibleFields(type, values)
    .filter((f) => f.required && f.kind !== "bool" && isEmpty(values[f.key]))
    .map((f) => f.label);
}

/** Klucze pól o podanych etykietach (serwer zwraca w `missing[]` etykiety). */
export function fieldKeysForLabels(
  type: DocumentTypeDef,
  labels: readonly string[],
): string[] {
  const wanted = new Set(labels);
  return type.fields.filter((f) => wanted.has(f.label)).map((f) => f.key);
}

// ── Kwoty ───────────────────────────────────────────────────────────────────

/**
 * „1 234,50” / „150” → liczba. Serwer robi `float(raw)`, więc przecinek
 * dziesiętny w stringu dałby w dokumencie „…”. `null` = nie da się odczytać.
 */
export function parseMoney(value: DocumentValue | undefined): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const normalized = value.replace(/[\s ]/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  return Number(normalized);
}

/** Etykiety pól kwot, których nie da się odczytać jako liczby. */
export function invalidMoneyFields(
  type: DocumentTypeDef,
  values: DocumentValues,
): string[] {
  return visibleFields(type, values)
    .filter(
      (f) =>
        f.kind === "money" &&
        !isEmpty(values[f.key]) &&
        parseMoney(values[f.key]) === null,
    )
    .map((f) => f.label);
}

// ── Ciało żądania ───────────────────────────────────────────────────────────

export interface RequestSubject {
  parentGeneratedContractId?: number | null;
  candidateId?: number | null;
  jobId?: number | null;
}

/**
 * Wartości do wysłania: tylko pola typu, tylko WIDOCZNE (ukryte `show_if`
 * nie mogą przemycić starej wartości do dokumentu), bez pustych; kwoty jako
 * liczby, teksty przycięte.
 */
export function cleanValues(
  type: DocumentTypeDef,
  values: DocumentValues,
): DocumentValues {
  const out: DocumentValues = {};
  for (const field of visibleFields(type, values)) {
    const raw = values[field.key];
    if (field.kind === "bool") {
      if (raw === true) out[field.key] = true;
      continue;
    }
    if (isEmpty(raw)) continue;
    if (field.kind === "money") {
      const number = parseMoney(raw);
      if (number !== null) out[field.key] = number;
      continue;
    }
    out[field.key] = typeof raw === "string" ? raw.trim() : raw;
  }
  return out;
}

/** Numery paragrafów bez pustych wpisów; `null`, gdy nic nie zostało. */
export function cleanRefs(
  refs: Record<string, string> | null | undefined,
): Record<string, string> | null {
  if (!refs) return null;
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(refs)) {
    const v = (value ?? "").trim();
    if (v) out[key] = v;
  }
  return Object.keys(out).length ? out : null;
}

export function buildDocumentRequest(input: {
  type: DocumentTypeDef;
  language: string;
  subject: RequestSubject;
  values: DocumentValues;
  needsRefs: boolean;
  refs?: Record<string, string> | null;
}): DocumentRequestBody {
  const { type, subject } = input;
  const body: DocumentRequestBody = {
    document_type: type.key,
    language: type.languages.includes(input.language)
      ? input.language
      : (type.languages[0] ?? "pl"),
    values: cleanValues(type, input.values),
  };
  if (subject.parentGeneratedContractId) {
    body.parent_generated_contract_id = subject.parentGeneratedContractId;
  }
  // Umowa przedwstępna nie ma umowy bazowej — wiąże ją kandydat i rekrutacja.
  if (subject.candidateId) body.candidate_id = subject.candidateId;
  if (subject.jobId) body.job_id = subject.jobId;
  // Numery paragrafów wysyłamy wyłącznie, gdy serwer o nie prosi: przy znanej
  // wersji wzoru i tak ich nie czyta, a mylące nadpisanie byłoby niewidoczne.
  const refs = input.needsRefs ? cleanRefs(input.refs) : null;
  if (refs) body.refs = refs;
  return body;
}

// ── Błędy API ───────────────────────────────────────────────────────────────

export interface DocumentApiError {
  message: string;
  code: string | null;
  /** Etykiety brakujących pól (`document_fields_missing`, `sensitive_values_required`). */
  missing: string[];
  status: number | undefined;
}

/**
 * Błąd żądania dokumentu. DOCX idzie z `responseType: "blob"`, więc ciało
 * błędu też jest Blobem — trzeba je przeczytać, zanim da się pokazać `detail`.
 */
export async function readDocumentError(
  error: unknown,
  fallback: string,
): Promise<DocumentApiError> {
  const response = (
    error as { response?: { status?: unknown; data?: unknown } } | null
  )?.response;
  const status = typeof response?.status === "number" ? response.status : undefined;
  let data: unknown = response?.data;
  if (typeof Blob !== "undefined" && data instanceof Blob) {
    try {
      data = JSON.parse(await data.text());
    } catch {
      data = undefined;
    }
  }
  const detail = (data as { detail?: unknown } | null | undefined)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { code?: unknown; message?: unknown; missing?: unknown };
    const missing = Array.isArray(d.missing)
      ? d.missing.filter((m): m is string => typeof m === "string")
      : [];
    return {
      message: typeof d.message === "string" && d.message ? d.message : fallback,
      code: typeof d.code === "string" ? d.code : null,
      missing,
      status,
    };
  }
  const message =
    (detail === undefined || detail === null || detail === "") && status !== 429
      ? fallback
      : (messageFromApiResponse(status, data) ?? fallback);
  return { message, code: null, missing: [], status };
}

// ── Adres (`?tab=documents&new=…&parent=…`) ─────────────────────────────────

export interface DocumentsUrlIntent {
  newType: string | null;
  parentId: number | null;
  /** Kontrakt z modułu Kontrakty — umowę bazową kreator szuka po nim. */
  contractId: number | null;
}

function positiveInt(value: string | null | undefined): number | null {
  if (!value || !/^\d+$/.test(value.trim())) return null;
  const n = Number(value.trim());
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}

const TYPE_KEY_RE = /^[a-z][a-z0-9_]{1,60}$/;

export function parseDocumentsIntent(params: {
  get(name: string): string | null;
} | null | undefined): DocumentsUrlIntent {
  const raw = params?.get("new")?.trim() ?? "";
  return {
    newType: TYPE_KEY_RE.test(raw) ? raw : raw === "1" ? "" : null,
    parentId: positiveInt(params?.get("parent")),
    contractId: positiveInt(params?.get("contract")),
  };
}

/** Czy adres prosi o otwarcie kreatora. */
export function intentOpensWizard(intent: DocumentsUrlIntent): boolean {
  return intent.newType !== null || intent.parentId !== null || intent.contractId !== null;
}

export function documentsHref(intent: {
  newType?: string | null;
  parentId?: number | null;
  contractId?: number | null;
}): string {
  const params = new URLSearchParams({ tab: "documents" });
  params.set("new", intent.newType || "1");
  if (intent.parentId) params.set("parent", String(intent.parentId));
  if (intent.contractId) params.set("contract", String(intent.contractId));
  return `/contracts/b2b-generator?${params.toString()}`;
}

/** Klucze parametrów kreatora — zdejmowane z adresu po wczytaniu. */
export const DOCUMENTS_INTENT_KEYS = ["new", "parent", "contract"] as const;

// ── Wiersz listy ────────────────────────────────────────────────────────────

export type DocumentStatusTone = "success" | "warning" | "neutral" | "danger";

export function documentStatusLabel(
  item: Pick<DocumentItem, "status" | "signature_status">,
): { label: string; tone: DocumentStatusTone } {
  if (item.status === "cancelled") return { label: "Anulowany", tone: "neutral" };
  if (item.status === "signed" || item.signature_status === "signed_both") {
    return { label: "Podpisany", tone: "success" };
  }
  return { label: "Niepodpisany", tone: "warning" };
}

/** Czy ponowne pobranie wymaga podania danych wrażliwych (okno z polami). */
export function redownloadNeedsInput(
  item: Pick<DocumentItem, "requires_sensitive_input" | "sensitive_fields">,
): boolean {
  return item.requires_sensitive_input && item.sensitive_fields.length > 0;
}

/** Pola wrażliwe typu (do okna ponownego pobrania). */
export function sensitiveFieldsOf(
  type: DocumentTypeDef | undefined,
  keys: readonly string[],
): DocumentFieldDef[] {
  if (!type) return [];
  const wanted = new Set(keys);
  return type.fields.filter((f) => f.sensitive && wanted.has(f.key));
}

/** Umowa bazowa kontraktu: wiersz rejestru o danym `contract_id`. */
export function findRegisterRowForContract<
  T extends { contract_id: number | null; contract_status?: string },
>(rows: readonly T[], contractId: number): T | null {
  const matches = rows.filter((r) => r.contract_id === contractId);
  if (!matches.length) return null;
  // Obowiązująca umowa wygrywa z anulowaną/zakończoną tej samej osoby.
  return (
    matches.find((r) => r.contract_status === "active") ??
    matches.find((r) => r.contract_status !== "cancelled") ??
    matches[0]
  );
}

/** Czy typ wymaga wyboru umowy bazowej przed formularzem. */
export function parentRequired(type: Pick<DocumentTypeDef, "parent">): boolean {
  return type.parent === "b2b";
}
