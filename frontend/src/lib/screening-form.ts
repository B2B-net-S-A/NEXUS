/**
 * Formularz screeningu (0424, 07.10.2026) — czysta logika bez zapytań.
 *
 * Jeden formularz na parę: pytania z Profilu Championa, warunki (pola karty
 * rekomendacji + stawka kandydata) i ocena (ogólne dopasowanie + pola opisowe
 * karty). Tu: wartości startowe z odpowiedzi serwera, ładunek zapisu (tylko
 * to, co się zmieniło), wypełnienie z notatki, walidacja „Zapisz i przekaż
 * dalej”. Komponenty (`components/v2/screening-form/`) tylko to wołają.
 */

import type { RateUnit, ScreeningQuestion } from "@/lib/api";
import type { NoteProposal } from "@/lib/api/recommendationCards";
import type {
  FormRate,
  RateNotRestoredReason,
  ScreeningFormAnswerOrigin,
  ScreeningFormFieldOrigin,
  ScreeningFormSave,
  ScreeningFormSaveSheet,
  ScreeningFormState,
  ScreeningFormVersionAction,
} from "@/lib/api/screeningForm";
import {
  CARD_FIELD_ORDER,
  CARD_PHRASABLE_FIELDS,
  cardChanges,
  cardFieldLabel,
} from "@/lib/recommendation-card";
import {
  DEFAULT_SKIP_NOTE,
  championScreeningQuestions,
  experienceCheckRows,
  type ScreeningFormAnswer,
  type ScreeningFormValues,
} from "@/components/v2/screening/ScreeningForm";

/** Wartości jednego formularza: arkusz + pola karty + stawka. */
export interface ScreeningFullFormValues extends ScreeningFormValues {
  /** Pola karty rekomendacji (bez stawki) — tekst jak w karcie. */
  card: Record<string, string>;
  /** Pochodzenie pól zmienionych w tej sesji (notatka, zdanie z haseł). */
  card_origins: Record<string, ScreeningFormFieldOrigin | null>;
  rate_amount: string;
  rate_unit: RateUnit;
  rate_currency: string;
  /** „Przenieś do „Dlaczego ten kandydat”” — serwer czyści notatkę z arkusza. */
  clear_legacy_notes: boolean;
}

/** Pola opisowe karty w sekcji „Ocena” — kolejność na ekranie. */
export const CARD_ASSESSMENT_FIELDS = ["recommendation", "motivation", "red_flags"] as const;

const ASSESSMENT: ReadonlySet<string> = new Set(CARD_ASSESSMENT_FIELDS);

/** Etykieta pola karty: z serwera, „Dlaczego ten kandydat” dla notatki. */
export function formFieldLabel(state: Pick<ScreeningFormState, "card">, key: string): string {
  return cardFieldLabel({ labels: state.card?.labels ?? {} }, key);
}

/** Pola karty do zapisu w formularzu — stawka ma własne pole. */
export function editableCardKeys(state: Pick<ScreeningFormState, "card">): string[] {
  return (state.card?.editable_fields ?? []).filter((key) => key !== "rate");
}

/** Sekcja „Warunki”: pola karty spoza oceny, w kolejności wzoru działu. */
export function cardTermsKeys(state: Pick<ScreeningFormState, "card">): string[] {
  const keys = editableCardKeys(state).filter((key) => !ASSESSMENT.has(key));
  const ordered = (CARD_FIELD_ORDER as readonly string[]).filter((key) => keys.includes(key));
  return [...ordered, ...keys.filter((key) => !ordered.includes(key))];
}

/** Sekcja „Ocena”: pola opisowe karty, które serwer pozwala zapisać. */
export function cardAssessmentKeys(state: Pick<ScreeningFormState, "card">): string[] {
  const keys = new Set(editableCardKeys(state));
  return CARD_ASSESSMENT_FIELDS.filter((key) => keys.has(key));
}

export function formQuestions(state: Pick<ScreeningFormState, "champion_profile">): ScreeningQuestion[] {
  return championScreeningQuestions(state.champion_profile);
}

/** Czy para ma już odpowiedź na którekolwiek pytanie (rozmowa się odbyła). */
export function hasSheetContent(state: Pick<ScreeningFormState, "sheet">): boolean {
  return (state.sheet?.answers ?? []).some((a) => (a.response ?? "").trim() !== "");
}

/** Wartości startowe formularza z odpowiedzi `GET /api/screening-form`. */
export function formDefaultsFromState(state: ScreeningFormState): ScreeningFullFormValues {
  const sheet = state.sheet ?? null;
  const saved = sheet?.answers ?? [];
  const answers: Record<string, ScreeningFormAnswer> = {};
  for (const q of formQuestions(state)) {
    const answer = saved.find((a) => a.question_id === q.id);
    answers[q.id] = {
      response: answer?.response ?? "",
      deal_breaker_hit: answer?.deal_breaker_hit ?? false,
      origin: answer?.origin ?? "manual",
      keywords: answer?.keywords ?? null,
    };
  }
  const fields = state.card?.fields ?? {};
  const card = Object.fromEntries(
    editableCardKeys(state).map((key) => [key, String(fields[key]?.raw ?? "")]),
  );
  return {
    answers,
    overall_fit: sheet?.overall_fit ?? "uncertain",
    // Stare pole „Notatki rekrutera” jest tylko do odczytu (`legacy_notes`).
    notes: "",
    skip_missing: saved.some((a) => a.skipped),
    internal_note: sheet?.internal_note ?? "",
    experience_checks: experienceCheckRows(state.champion_profile, sheet?.experience_checks),
    card,
    // Klucz dla każdego pola (null = bez pochodzenia): „Cofnij wypełnienie”
    // przywraca null, więc formularz wraca do wartości domyślnych i nie jest
    // „niezapisany” (brakujący klucz ≠ klucz z undefined w porównaniu RHF).
    card_origins: Object.fromEntries(editableCardKeys(state).map((key) => [key, null])),
    rate_amount: state.rate ? String(state.rate.amount) : "",
    rate_unit: state.rate?.unit ?? "hourly",
    rate_currency: state.rate?.currency ?? "PLN",
    clear_legacy_notes: false,
  };
}

function wireOrigin(origin: ScreeningFormAnswer["origin"]): ScreeningFormAnswerOrigin {
  // Odpowiedź przepisana z notatki przez automat — zapis człowieka przejmuje ją
  // jako odpowiedź z notatki (serwer robi to samo).
  if (origin === "note_sync") return "note_import";
  return origin ?? "manual";
}

/** Arkusz do zapisu — ten sam kształt dla wartości bieżących i startowych. */
export function sheetFromValues(
  questions: readonly ScreeningQuestion[],
  values: ScreeningFullFormValues,
): ScreeningFormSaveSheet {
  const skipMissing = Boolean(values.skip_missing);
  const answers = questions.map((q) => {
    const value = values.answers?.[q.id];
    const response = value?.response ?? "";
    const origin = wireOrigin(value?.origin);
    const keywords = (value?.keywords ?? "").trim();
    const skipped = skipMissing && !response.trim();
    return {
      question_id: q.id,
      response,
      deal_breaker_hit: Boolean(value?.deal_breaker_hit),
      origin,
      ...((origin === "phrased" || origin === "note_import") && keywords ? { keywords } : {}),
      ...(skipped ? { skipped: true } : {}),
    };
  });
  const anySkipped = answers.some((a) => a.skipped);
  return {
    answers,
    experience_checks: (values.experience_checks ?? []).map((row) => ({
      kind: row.kind,
      name: row.name,
      status: row.status,
    })),
    overall_fit: values.overall_fit,
    internal_note: anySkipped ? (values.internal_note ?? "").trim() || DEFAULT_SKIP_NOTE : null,
  };
}

/** Kwota z pola formularza (przecinek dziesiętny dozwolony); `null` = brak albo ≤ 0. */
export function parseRateAmount(raw: string | null | undefined): number | null {
  const normalized = String(raw ?? "").trim().replace(",", ".");
  if (!normalized) return null;
  const value = Number(normalized);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Stawka z wartości formularza albo `null`, gdy pole jest puste lub błędne. */
export function rateFromValues(values: Pick<ScreeningFullFormValues, "rate_amount" | "rate_unit" | "rate_currency">): FormRate | null {
  const amount = parseRateAmount(values.rate_amount);
  if (amount == null) return null;
  const currency = (values.rate_currency || "PLN").trim().toUpperCase() || "PLN";
  return { amount, unit: values.rate_unit, currency };
}

export function sameRate(a: FormRate | null | undefined, b: FormRate | null | undefined): boolean {
  if (!a || !b) return a == null && b == null;
  return (
    Math.abs(a.amount - b.amount) < 0.005 &&
    a.unit === b.unit &&
    a.currency.toUpperCase() === b.currency.toUpperCase()
  );
}

export interface NoteImport {
  text: string;
  source_name?: string | null;
}

export interface SavePlan {
  payload: ScreeningFormSave;
  hasChanges: boolean;
}

/**
 * Ładunek `PUT /api/screening-form` — wyłącznie to, co zmieniło się względem
 * stanu z serwera. Pole karty z notatki nie znika od wyczyszczenia (wartość
 * z notatki zmienia poprawka notatki albo wpisanie innej) — tak jak w karcie.
 */
export function buildSavePayload(
  state: ScreeningFormState,
  values: ScreeningFullFormValues,
  options: { noteImport?: NoteImport | null; expectedVersion?: number; stateToken?: string } = {},
): SavePlan {
  const questions = formQuestions(state);
  const defaults = formDefaultsFromState(state);

  const next = sheetFromValues(questions, values);
  const before = sheetFromValues(questions, defaults);
  const clearLegacy = Boolean(values.clear_legacy_notes) && Boolean(state.legacy_notes?.trim());
  const sheetChanged = JSON.stringify(next) !== JSON.stringify(before);
  const sheet: ScreeningFormSaveSheet | null =
    sheetChanged || clearLegacy ? { ...next, ...(clearLegacy ? { clear_legacy_notes: true } : {}) } : null;

  const editable = editableCardKeys(state);
  const draft = Object.fromEntries(editable.map((key) => [key, values.card?.[key] ?? ""]));
  const fields = state.card?.fields ?? {};
  const changes = cardChanges({ fields, editable_fields: editable }, draft);
  const cardFields: Record<string, string | null> = {};
  const origins: Record<string, ScreeningFormFieldOrigin> = {};
  for (const [key, value] of Object.entries(changes)) {
    if (value == null && fields[key]?.source !== "manual") continue;
    cardFields[key] = value;
    const origin = values.card_origins?.[key];
    if (value != null && origin) {
      // „Zdanie z haseł” serwer przyjmuje tylko w polach opisowych.
      if (origin.origin === "phrased" && !CARD_PHRASABLE_FIELDS.has(key)) continue;
      origins[key] = origin.keywords ? { origin: origin.origin, keywords: origin.keywords } : { origin: origin.origin };
    }
  }
  const card = Object.keys(cardFields).length
    ? { fields: cardFields, ...(Object.keys(origins).length ? { origins } : {}) }
    : null;

  const wanted = state.can_edit_rate ? rateFromValues(values) : null;
  const current = state.rate
    ? { amount: state.rate.amount, unit: state.rate.unit, currency: state.rate.currency }
    : null;
  const rate = wanted && !sameRate(wanted, current) ? wanted : null;

  const noteImport = options.noteImport?.text?.trim()
    ? {
        text: options.noteImport.text,
        ...(options.noteImport.source_name ? { source_name: options.noteImport.source_name } : {}),
      }
    : null;

  const payload: ScreeningFormSave = {
    candidate_id: state.candidate_id,
    job_id: state.job_id,
    expected_version: options.expectedVersion ?? state.version,
    // Odcisk stanu, z którego wzięte są wartości startowe (różnice liczymy
    // względem tego samego stanu) — serwer odmawia, gdy para zmieniła się obok.
    state_token: options.stateToken ?? state.state_token,
    sheet,
    card,
    rate,
    note_import: noteImport,
  };
  return { payload, hasChanges: Boolean(sheet || card || rate || noteImport) };
}

/** Pytania bez odpowiedzi blokujące „Zapisz i przekaż dalej” (pominięte przy przepięciu — nie). */
export function missingAnswersForForward(
  questions: readonly ScreeningQuestion[],
  values: Pick<ScreeningFullFormValues, "answers" | "skip_missing">,
): string[] {
  if (values.skip_missing) return [];
  return questions
    .filter((q) => !(values.answers?.[q.id]?.response ?? "").trim())
    .map((q) => q.id);
}

// ── Wypełnienie z notatki ────────────────────────────────────────────────

/** Zmiana jednego miejsca formularza wynikająca z notatki. */
export type NoteFill =
  | { kind: "card"; key: string; value: string; origin: "note_ai" | "note_rule" }
  | {
      kind: "answer";
      questionId: string;
      response: string;
      origin: "phrased" | "note_import";
      keywords: string;
    }
  | { kind: "rate"; rate: FormRate };

/** Wartość z notatki inna niż wpisana — „Użyj” zamiast nadpisania. */
export type NoteOffer = NoteFill & { id: string; label: string; text: string };

/** Wartość z notatki, której nie da się wpisać bez zgadywania (stawka tekstem). */
export interface NoteHint {
  id: string;
  label: string;
  text: string;
}

export interface NoteApplication {
  fills: NoteFill[];
  offers: NoteOffer[];
  hints: NoteHint[];
}

const RATE_UNIT_SUFFIX: Record<RateUnit, string> = { hourly: "/h", daily: "/dzień", monthly: "/mc" };

/** „150 zł/h”, „1 200 zł/dzień”, „40 EUR/h”. */
export function formatFormRate(rate: FormRate): string {
  const amount = Number.isInteger(rate.amount)
    ? rate.amount.toLocaleString("pl-PL")
    : rate.amount.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const currency = !rate.currency || rate.currency.toUpperCase() === "PLN" ? "zł" : rate.currency.toUpperCase();
  return `${amount} ${currency}${RATE_UNIT_SUFFIX[rate.unit] ?? ""}`;
}

function sameText(a: string | null | undefined, b: string | null | undefined): boolean {
  return String(a ?? "").trim() === String(b ?? "").trim();
}

/**
 * Notatka wypełnia PUSTE miejsca formularza; tam, gdzie coś już jest, zostaje
 * propozycja „Użyj”. Nic się nie zapisuje — zapis to dalej „Zapisz”.
 */
export function applyNoteProposal(
  values: ScreeningFullFormValues,
  proposal: Pick<NoteProposal, "fields" | "answers">,
  options: { editableCardKeys: readonly string[]; canEditRate: boolean; questionIds: readonly string[] },
): NoteApplication {
  const fills: NoteFill[] = [];
  const offers: NoteOffer[] = [];
  const hints: NoteHint[] = [];
  const editable = new Set(options.editableCardKeys);
  const questions = new Set(options.questionIds);

  for (const field of proposal.fields ?? []) {
    const proposed = String(field.proposed ?? "").trim();
    if (!proposed) continue;
    if (field.key === "rate") {
      if (!options.canEditRate) continue;
      const rate = field.rate ?? null;
      if (!rate || !(rate.amount > 0)) {
        hints.push({ id: "rate", label: field.label || "Stawka", text: proposed });
        continue;
      }
      const structured: FormRate = { amount: rate.amount, unit: rate.unit, currency: rate.currency || "PLN" };
      const current = rateFromValues(values);
      if (!current) fills.push({ kind: "rate", rate: structured });
      else if (!sameRate(current, structured)) {
        offers.push({ kind: "rate", rate: structured, id: "rate", label: field.label || "Stawka", text: formatFormRate(structured) });
      }
      continue;
    }
    if (!editable.has(field.key)) continue;
    const current = values.card?.[field.key] ?? "";
    if (!current.trim()) {
      fills.push({ kind: "card", key: field.key, value: proposed, origin: field.origin });
    } else if (!sameText(current, proposed)) {
      offers.push({
        kind: "card",
        key: field.key,
        value: proposed,
        origin: field.origin,
        id: `card:${field.key}`,
        label: field.label || field.key,
        text: proposed,
      });
    }
  }

  for (const answer of proposal.answers ?? []) {
    if (!questions.has(answer.question_id)) continue;
    const sentence = answer.sentence?.trim() || null;
    const response = sentence ?? String(answer.keywords ?? "").trim();
    if (!response) continue;
    const fill: Extract<NoteFill, { kind: "answer" }> = {
      kind: "answer",
      questionId: answer.question_id,
      response,
      origin: sentence ? "phrased" : "note_import",
      keywords: String(answer.keywords ?? "").trim(),
    };
    const current = values.answers?.[answer.question_id]?.response ?? "";
    if (!current.trim()) fills.push(fill);
    else if (!sameText(current, response)) {
      offers.push({
        ...fill,
        id: `answer:${answer.question_id}`,
        label: `Pytanie ${answer.number}`,
        text: response,
      });
    }
  }
  return { fills, offers, hints };
}

/** Ścieżki pól formularza do ustawienia dla jednej zmiany z notatki. */
export function fillPatches(fill: NoteFill): Array<[string, unknown]> {
  switch (fill.kind) {
    case "card":
      return [
        [`card.${fill.key}`, fill.value],
        [`card_origins.${fill.key}`, { origin: fill.origin }],
      ];
    case "answer":
      return [
        [`answers.${fill.questionId}.response`, fill.response],
        [`answers.${fill.questionId}.origin`, fill.origin],
        [`answers.${fill.questionId}.keywords`, fill.keywords || null],
      ];
    case "rate":
      return [
        ["rate_amount", String(fill.rate.amount)],
        ["rate_unit", fill.rate.unit],
        ["rate_currency", fill.rate.currency || "PLN"],
      ];
  }
}

/** Klucz miejsca, które zmiana wypełnia — plakietka „z notatki”. */
export function fillTarget(fill: NoteFill): string {
  if (fill.kind === "card") return `card:${fill.key}`;
  if (fill.kind === "answer") return `answer:${fill.questionId}`;
  return "rate";
}

/** Te same zmiany na zwykłym obiekcie (testy, podgląd). */
export function applyFillsToValues(
  values: ScreeningFullFormValues,
  fills: readonly NoteFill[],
): ScreeningFullFormValues {
  const next: ScreeningFullFormValues = {
    ...values,
    answers: { ...values.answers },
    card: { ...values.card },
    card_origins: { ...values.card_origins },
  };
  for (const fill of fills) {
    if (fill.kind === "card") {
      next.card[fill.key] = fill.value;
      next.card_origins[fill.key] = { origin: fill.origin };
    } else if (fill.kind === "answer") {
      next.answers[fill.questionId] = {
        ...(next.answers[fill.questionId] ?? { deal_breaker_hit: false }),
        response: fill.response,
        origin: fill.origin,
        keywords: fill.keywords || null,
      };
    } else {
      next.rate_amount = String(fill.rate.amount);
      next.rate_unit = fill.rate.unit;
      next.rate_currency = fill.rate.currency || "PLN";
    }
  }
  return next;
}

// ── Pochodzenie po ręcznej poprawce ──────────────────────────────────────

/** Odpowiedź poprawiona ręcznie jest już odpowiedzią z tej rozmowy. */
export function answerOriginAfterEdit(
  origin: ScreeningFormAnswer["origin"],
  response: string,
): ScreeningFormAnswer["origin"] | null {
  if (origin === "reassign_suggested" || origin === "note_import" || origin === "note_sync") return "manual";
  if (origin === "phrased" && !response.trim()) return "manual";
  return null;
}

/** Pole karty poprawione ręcznie traci pochodzenie z notatki; zdanie z haseł — dopiero po wyczyszczeniu. */
export function cardOriginAfterEdit(
  origin: ScreeningFormFieldOrigin | null | undefined,
  value: string,
): "keep" | "clear" {
  if (!origin) return "keep";
  if (origin.origin === "note_ai" || origin.origin === "note_rule") return "clear";
  if (origin.origin === "phrased" && !value.trim()) return "clear";
  return "keep";
}

/** „Przenieś do „Dlaczego ten kandydat”” — dopisuje notatkę z arkusza pod tekstem pola. */
export function mergeLegacyNote(current: string, legacy: string): string {
  const text = legacy.trim();
  if (!current.trim()) return text;
  return `${current.trimEnd()}\n\n${text}`;
}

// ── Historia wersji ──────────────────────────────────────────────────────

export function versionActionLabel(action: ScreeningFormVersionAction, restoredFrom?: number | null): string {
  switch (action) {
    case "baseline":
      return "Stan przed formularzem";
    case "external":
      return "Zmiana spoza formularza";
    case "restore":
      return restoredFrom != null ? `Przywrócono wersję ${restoredFrom}` : "Przywrócenie wersji";
    case "undo":
      return "Cofnięto zapis";
    case "fix_requested":
      return "Wróciło do poprawy";
    case "save":
    default:
      return "Zapis";
  }
}

/**
 * Zdanie po przywróceniu, gdy stawka kandydata została bez zmian
 * (`rate_not_restored`). `null` = stawka wróciła albo nie było czego zmieniać.
 */
export function rateNotRestoredMessage(
  result: { rate_not_restored: boolean; rate_not_restored_reason?: RateNotRestoredReason | null },
  mode: "restore" | "undo",
): string | null {
  if (!result.rate_not_restored) return null;
  if (result.rate_not_restored_reason === "not_in_version") {
    return mode === "undo"
      ? "Cofnięto zapis — stawka kandydata została, zmień ją w formularzu."
      : "Stawka kandydata została — ta wersja jej nie miała. Zmień ją w formularzu.";
  }
  return "Stawka nie wróciła — od „Zweryfikowany” zmianą stawki zarządza Delivery Lead.";
}

/** Kolumny, od których zmiana w formularzu trafia do Delivery Leada i do kolejnego CV firmowego (D8). */
export const AFTER_CV_SENT_COLUMNS: ReadonlySet<string> = new Set([
  "cv_sent",
  "client_interview",
  "contract",
  "hired",
]);
