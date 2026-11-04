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
  CarriedCardField,
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
import { rateToHourly } from "@/lib/rate-to-hourly";
import { notedAtDateLabel, rateSuggestionFill, type ScreeningSuggestions } from "@/lib/screening-suggestions";
import {
  championScreeningQuestions,
  defaultSkipNote,
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
    skip_reason: null,
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
    internal_note: anySkipped ? (values.internal_note ?? "").trim() || defaultSkipNote(values.skip_reason) : null,
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
  /** Notatka zapisana już w doku (D3, 14.10.2026) — zapis jej nie dubluje. */
  note_id?: number | null;
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
  // Serwer porównuje tylko ze stawką ETAPU (`_same_rate(current.rate, …)`).
  // Stawka z karty (`source: "card"`) stoi w polu, ale etap jej nie ma — do
  // 14.10.2026 porównanie z nią gubiło zapis i etap zostawał bez stawki.
  // Tylko w „Nowych” i „Screeningu”: dalej stawka z karty w polu to
  // podpowiedź, a jej zapis byłby zmianą stawki z dzwonkami do DL
  // (przegląd 14.10.2026) — tam porównujemy z tym, co pole pokazało na start.
  const current =
    state.rate && (state.rate.source === "stage" || !ratePrefillColumn(state))
      ? { amount: state.rate.amount, unit: state.rate.unit, currency: state.rate.currency }
      : null;
  const rate = wanted && !sameRate(wanted, current) ? wanted : null;

  const noteImport = options.noteImport?.text?.trim()
    ? {
        text: options.noteImport.text,
        ...(options.noteImport.source_name ? { source_name: options.noteImport.source_name } : {}),
        // D3 (14.10.2026): notatka już zapisana w doku — serwer jej nie dubluje.
        ...(options.noteImport.note_id != null ? { note_id: options.noteImport.note_id } : {}),
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

// ── Stawka na start (D2, 14.10.2026) ─────────────────────────────────────

/** Kolumny, w których stawka trafia do etapu z rozmowy screeningowej. */
const RATE_PREFILL_COLUMNS: ReadonlySet<string> = new Set(["new", "screening"]);

function ratePrefillColumn(state: Pick<ScreeningFormState, "board_column">): boolean {
  return state.board_column != null && RATE_PREFILL_COLUMNS.has(state.board_column);
}

/** Skąd formularz wziął stawkę wpisaną na start — linijka pod polem. */
export type RatePrefillOrigin =
  | { kind: "note"; quote: string; notedAt: string | null }
  | { kind: "card"; quote: string | null }
  | { kind: "rate_from" }
  /** „Stawka u nas” — stawka z żywej umowy (R1, 17.10.2026). */
  | { kind: "contract" };

export interface RatePrefill {
  rate: FormRate;
  origin: RatePrefillOrigin;
}

type PrefillState = Pick<
  ScreeningFormState,
  "rate" | "rate_hints" | "can_edit_rate" | "suggestions_from_notes" | "board_column"
>;

/** Stawka z notatek, którą da się wpisać bez zgadywania (PLN, znana jednostka, cytat). */
function noteRate(state: Pick<ScreeningFormState, "suggestions_from_notes">): RatePrefill | null {
  const note = (state.suggestions_from_notes as ScreeningSuggestions | undefined)?.rate;
  const quote = note?.raw?.trim();
  const fill = note && quote ? rateSuggestionFill(note) : null;
  if (!note || !quote || !fill) return null;
  return {
    rate: { amount: Number(fill.rate), unit: fill.unit, currency: "PLN" },
    origin: { kind: "note", quote, notedAt: note.noted_at ?? null },
  };
}

function hourlyOf(rate: FormRate | null | undefined): number | null {
  return rate ? rateToHourly(rate.amount, rate.unit, rate.currency) : null;
}

/**
 * Stawka do wpisania, gdy etap pary jej nie ma (R1, 17.10.2026): najpierw
 * stawka z karty TEJ rekrutacji (kandydat powiedział ją o tę rolę), przy żywej
 * umowie „Stawka u nas”, a w pozostałych przypadkach NIŻSZA z dwóch — stawka
 * z notatek z dosłownym cytatem albo „Stawka od”. Do 17.10 wygrywała najnowsza
 * notatka, nawet wyższa — formularz wpisywał 140 przy zadeklarowanych 90.
 * `null` = etap ma stawkę, osoba nie może zmieniać stawek albo nie ma nic
 * pewnego. Wpis idzie jako zmiana formularza — zapisze się z „Zapisz”.
 */
export function ratePrefill(state: PrefillState): RatePrefill | null {
  // Poza „Nowymi” i „Screeningiem” podpowiedź nie staje się stawką sama.
  if (!state.can_edit_rate || state.rate?.source === "stage" || !ratePrefillColumn(state)) return null;
  const card = state.rate_hints?.card;
  if (card && card.amount > 0) {
    return { rate: card, origin: { kind: "card", quote: state.rate_hints.card_raw?.trim() || null } };
  }
  const from = state.rate_hints?.rate_from;
  const fromPick: RatePrefill | null =
    from && from.amount > 0
      ? {
          rate: from,
          origin: state.rate_hints.rate_from_source === "contract" ? { kind: "contract" } : { kind: "rate_from" },
        }
      : null;
  if (fromPick?.origin.kind === "contract") return fromPick;
  const note = noteRate(state);
  if (!note || !fromPick) return note ?? fromPick;
  const noteHourly = hourlyOf(note.rate);
  const fromHourly = hourlyOf(fromPick.rate);
  if (noteHourly === null || fromHourly === null) return note;
  return noteHourly <= fromHourly ? note : fromPick;
}

/** „z notatki 2.04.2025: „150 na B2B”” — bez „· zmień”, które dokłada widok. */
export function ratePrefillCaption(origin: RatePrefillOrigin): string {
  switch (origin.kind) {
    case "note": {
      const date = notedAtDateLabel(origin.notedAt);
      return `z notatki${date ? ` ${date}` : ""}: „${origin.quote}”`;
    }
    case "card":
      return origin.quote ? `z karty rekomendacji: „${origin.quote}”` : "z karty rekomendacji";
    case "rate_from":
      return "Stawka od · najniższa z 18 mies.";
    case "contract":
      return "Stawka u nas · z umowy";
  }
}

/** Niższa znana stawka kandydata, która mieści się w budżecie (R2). */
export interface LowerKnownRate {
  rate: FormRate;
  source: "rate_from" | "declared" | "note";
  at: string | null;
}

/**
 * R2 (17.10.2026): stawka w polu jest ponad budżetem, a kandydat podał też
 * niższą, która się w nim mieści — ostrzeżenie mówi to wprost, żeby nikt nie
 * odrzucił osoby za stawkę, której nie żąda. Kandydaci: „Stawka od” (przy
 * żywej umowie — najniższa zadeklarowana zamiast stawki z umowy) i stawka
 * z notatek. Wygrywa najniższa. `null` = nie ma czego dopowiedzieć.
 */
export function lowerKnownRate(
  state: Pick<ScreeningFormState, "rate_hints" | "suggestions_from_notes">,
  entered: FormRate | null,
  budgetHourly: number | null,
): LowerKnownRate | null {
  const enteredHourly = hourlyOf(entered);
  if (budgetHourly === null || enteredHourly === null || enteredHourly <= budgetHourly) return null;
  const hints = state.rate_hints;
  const contract = hints?.rate_from_source === "contract";
  const note = noteRate(state);
  const known: LowerKnownRate[] = [];
  if (!contract && hints?.rate_from) known.push({ rate: hints.rate_from, source: "rate_from", at: hints.rate_from_at ?? null });
  if (contract && hints?.declared_from) {
    known.push({ rate: hints.declared_from, source: "declared", at: hints.declared_from_at ?? null });
  }
  if (note && note.origin.kind === "note") known.push({ rate: note.rate, source: "note", at: note.origin.notedAt });
  let best: { item: LowerKnownRate; hourly: number } | null = null;
  for (const item of known) {
    const hourly = hourlyOf(item.rate);
    if (hourly === null || hourly >= enteredHourly || hourly > budgetHourly) continue;
    if (!best || hourly < best.hourly) best = { item, hourly };
  }
  return best?.item ?? null;
}

const LOWER_SOURCE_LABEL: Record<LowerKnownRate["source"], string> = {
  rate_from: "Stawka od",
  declared: "deklaracja",
  note: "z notatki",
};

/** „Znana też niższa stawka: 90 zł/h (Stawka od, 8.10.2026) — mieści się w budżecie.” */
export function lowerKnownRateText(lower: LowerKnownRate): string {
  const date = notedAtDateLabel(lower.at);
  const origin = [LOWER_SOURCE_LABEL[lower.source], date].filter(Boolean).join(", ");
  return `Znana też niższa stawka: ${formatFormRate(lower.rate)} (${origin}) — mieści się w budżecie.`;
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

/**
 * Rekrutacja bez pytań screeningowych: przed „Zweryfikowany” serwer zamiast
 * arkusza wymaga „Dlaczego ten kandydat” (12.10.2026, lustro
 * `move_requirements.screening_requirement`). `true` = pole trzeba wpisać,
 * zanim ruszy „Zapisz i przekaż dalej”. Formularz zatrzymuje tylko wtedy, gdy
 * jest pewny — w pozostałych przypadkach rozstrzyga serwer.
 */
export function assessmentMissingForForward(
  state: Pick<ScreeningFormState, "card" | "sheet" | "note_answers" | "questions">,
  questions: readonly ScreeningQuestion[],
  values: Pick<ScreeningFullFormValues, "card">,
): boolean {
  if (questions.length > 0) return false;
  // Odpowiedzi w notatce i arkusz sprzed usunięcia pytań serwerowi wystarczają —
  // arkusz tylko z odpowiedzią (tekst, pominięcie, deal-breaker), lustro
  // `move_requirements.sheet_answered` (audyt 13.10.2026).
  const answeredElsewhere =
    (state.note_answers ?? []).length > 0 ||
    (state.questions ?? []).some((q) => q.source === "note") ||
    (state.sheet?.answers ?? []).some(
      (a) => (a.response ?? "").trim() !== "" || Boolean(a.skipped) || Boolean(a.deal_breaker_hit),
    );
  if (answeredElsewhere) return false;
  if (!editableCardKeys(state).includes("recommendation")) return false;
  if ((values.card?.recommendation ?? "").trim()) return false;
  // Puste pole nie kasuje wartości z notatki — ta dalej się liczy.
  return state.card?.fields?.recommendation?.source !== "note";
}

// ── Minimum dla Delivery Leada (decyzja Artura 21.10.2026) ──────────────

/** „-” w red flags znaczy „brak uwag”; gdzie indziej wpis bez litery i cyfry nie jest wartością. */
const PLACEHOLDER_IS_VALUE: ReadonlySet<string> = new Set(["red_flags"]);

/** Czy tekst pola karty liczy się jako wartość — lustro `has_value` w backendzie. */
export function cardValueCounts(key: string, raw: string | null | undefined): boolean {
  const text = (raw ?? "").trim();
  if (PLACEHOLDER_IS_VALUE.has(key)) return text !== "";
  return /[\p{L}\p{N}]/u.test(text);
}

/**
 * Pola minimum bez wartości — „Zapisz i przekaż dalej” zatrzymuje się na nich
 * (lustro `move_requirements.minimum_missing`). Puste pole nie kasuje wartości
 * z notatki, dostępność liczy się też z profilu. W rekrutacji bez pytań
 * „Dlaczego ten kandydat” pomijamy tylko wtedy, gdy już zatrzymuje
 * `assessmentMissingForForward` — odpowiedzi z notatki albo stary arkusz go
 * nie zastępują (lustro `_why_candidate_reported`, przegląd 21.10.2026).
 */
export function minimumMissingForForward(
  state: Pick<ScreeningFormState, "card" | "sheet" | "note_answers" | "questions">,
  questions: readonly ScreeningQuestion[],
  values: Pick<ScreeningFullFormValues, "card">,
): string[] {
  const editable = new Set(editableCardKeys(state));
  return (state.card?.required ?? []).filter((key) => {
    if (!editable.has(key)) return false;
    if (key === "recommendation" && assessmentMissingForForward(state, questions, values)) return false;
    if (key === "availability" && state.card?.availability_in_profile) return false;
    const typed = values.card?.[key] ?? "";
    if (cardValueCounts(key, typed)) return false;
    const saved = state.card?.fields?.[key];
    return !(typed.trim() === "" && saved?.source === "note" && cardValueCounts(key, saved.raw));
  });
}

/**
 * D2 (21.10.2026): pola o osobie z innej rekrutacji do wpisania w puste pola
 * formularza — jak stawka na start, tylko w „Nowych” i „Screeningu”.
 */
export function carriedPrefill(
  state: Pick<ScreeningFormState, "card" | "board_column" | "editable">,
): Record<string, CarriedCardField> {
  if (!state.editable || !ratePrefillColumn(state)) return {};
  const editable = new Set(editableCardKeys(state));
  const out: Record<string, CarriedCardField> = {};
  for (const [key, value] of Object.entries(state.card?.carried ?? {})) {
    if (!editable.has(key) || !cardValueCounts(key, value.raw)) continue;
    if (cardValueCounts(key, state.card?.fields?.[key]?.raw)) continue;
    out[key] = value;
  }
  return out;
}

/** Linijka pod polem: „z rozmowy 20.10.2026 · Java Developer — Bank A”. */
export function carriedCaption(value: CarriedCardField): string {
  const day = value.at ? new Date(value.at) : null;
  const date =
    day && !Number.isNaN(day.getTime())
      ? day.toLocaleDateString("pl-PL", { day: "numeric", month: "numeric", year: "numeric", timeZone: "Europe/Warsaw" })
      : null;
  return ["z rozmowy" + (date ? ` ${date}` : ""), value.job_title].filter(Boolean).join(" · ");
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
