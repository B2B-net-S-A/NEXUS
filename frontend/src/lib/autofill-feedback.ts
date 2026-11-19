/**
 * Odrzucenie osoby od systemu z powodem (silnik „Nowi na 20”, decyzja Artura
 * 23.10.2026, makieta A3). Lustro listy i reguły serwera
 * (`backend/app/services/autofill_feedback.py`, `StageMove.autofill_*`):
 * odrzucenie osoby od systemu z „Nowych” albo „Screeningu” wymaga powodu
 * ze stałej listy i „skąd wiesz”, inaczej 422 `AUTOFILL_REASON_REQUIRED`.
 */
import type { BoardColumnKey } from "@/lib/board-stages";
import { warsawToday } from "@/lib/warsaw-date";

export type AutofillReason =
  | "missing_skill"
  | "too_junior"
  | "overqualified"
  | "other_level_or_role"
  | "location_mode"
  | "language"
  | "too_expensive"
  | "outdated_cv"
  | "profile_mismatch"
  | "wrong_phone"
  | "not_looking"
  | "no_answer"
  | "in_other_process"
  | "client_employed"
  | "client_refused"
  | "client_other_vendor"
  | "no_polish"
  | "weak_english"
  | "contract_form"
  | "cleanup"
  | "other";

export type AutofillLearnedFrom = "profile" | "call";

/**
 * Brak przy pozycji wymagania (12.11.2026, 0686): przy „Brak umiejętności”
 * rekruter klika przy pozycji, zamiast pisać. Z tych braków reguła rekrutacji
 * uczy się, czego wymagać w kolejnej porcji.
 */
export type AutofillGapKind = "missing" | "mention" | "too_few_years";
export interface AutofillGap {
  label: string;
  kind: AutofillGapKind;
}
export const GAP_KIND_LABEL: Record<AutofillGapKind, string> = {
  missing: "brak",
  mention: "tylko wzmianka",
  too_few_years: "za mało lat",
};

/**
 * Szczegół powodu z porcji (16.11.2026, 0717; lustro `clean_detail` serwera).
 * 13.11 „Inna rola” była 49× bez słowa, a 22 z 45 „Inne” to porządki tablicy.
 */
/**
 * „Co nie gra z rolą?” (16.11.2026, profil „Kogo szukamy”): 8 odpowiedzi pod
 * klawiszami 1–8. `level` zostaje dla starych wpisów, na ekranie go nie ma.
 */
export type AutofillRoleKind =
  | "profession"
  | "specialty"
  | "technology"
  | "lead_not_ic"
  | "ic_not_lead"
  | "past_role"
  | "side_role"
  | "domain"
  | "level";
export type AutofillAvailability = "not_looking" | "notice" | "from_date";
export type AutofillCleanupKind = "duplicate" | "stale_process" | "cv_broken";
export interface AutofillDetail {
  role_kind?: AutofillRoleKind;
  role_wanted?: string;
  /** „Osoba to:” — z tego uczy się „Nie proponujemy” rekrutacji. */
  person_role?: string;
  availability?: AutofillAvailability;
  cleanup?: AutofillCleanupKind;
}

export const ROLE_KIND_LABEL: Record<AutofillRoleKind, string> = {
  profession: "Inny zawód",
  specialty: "Inna specjalizacja",
  technology: "Inna technologia w tej roli",
  lead_not_ic: "Lider zamiast wykonawcy",
  ic_not_lead: "Wykonawca zamiast lidera",
  past_role: "Robił to dawno, teraz co innego",
  side_role: "Rola poboczna w CV",
  domain: "Inna branża / domena",
  level: "Za wysoki poziom / za senior",
};

/** Odpowiedzi na ekranie, w kolejności klawiszy 1–8. */
export const ROLE_KIND_CHOICES: AutofillRoleKind[] = [
  "profession",
  "specialty",
  "technology",
  "lead_not_ic",
  "ic_not_lead",
  "past_role",
  "side_role",
  "domain",
];
export const CLEANUP_KIND_LABEL: Record<AutofillCleanupKind, string> = {
  duplicate: "Duplikat",
  stale_process: "Nieaktualny proces / porządki",
  cv_broken: "CV się nie otwiera",
};

/** „Inne” = choć 3 litery opisu (lustro `OTHER_NOTE_MIN_LETTERS`); kropka to 11 z 45 „Inne” z 13.11. */
export const OTHER_NOTE_MIN_LETTERS = 3;
export function otherNoteHasWords(note: string): boolean {
  return (note.match(/\p{L}/gu) ?? []).length >= OTHER_NOTE_MIN_LETTERS;
}

export interface AutofillFeedbackChoice {
  reason: AutofillReason;
  learnedFrom: AutofillLearnedFrom;
  /** „Ile chce?” z rozmowy (PLN/h) — trafia do „Stawki od”. */
  rateHourly: number | null;
  /**
   * 27.10.2026: powód „klient” dotyczy wszystkich rekrutacji klienta — serwer
   * zdejmuje nietknięte karty tej osoby od systemu z pozostałych i więcej jej
   * temu klientowi nie podsuwa.
   */
  wholeClient?: boolean;
  /**
   * 28.10.2026: „Nie szuka pracy” — do kiedy („RRRR-MM-DD”). Serwer zapisuje
   * w profilu „Nie szuka” i „Dostępny od”, zdejmuje nietknięte karty osoby od
   * systemu z innych rekrutacji i nie podsuwa jej do tej daty.
   */
  notLookingUntil?: string | null;
  /** Braki przy pozycjach — tylko przy „Brak umiejętności”. */
  gaps?: AutofillGap[];
  /** Szczegół powodu (porcja): rodzaj „Innej roli”, dostępność, rodzaj porządków. */
  detail?: AutofillDetail | null;
}

/** Powody, przy których okno pyta „na cały klient” (lustro `CLIENT_WIDE_REASONS`). */
export const CLIENT_WIDE_REASONS: ReadonlySet<AutofillReason> = new Set([
  "client_employed",
  "client_refused",
  "client_other_vendor",
]);

export const AUTOFILL_REASON_GROUPS: {
  title: string;
  reasons: { value: AutofillReason; label: string }[];
}[] = [
  {
    title: "Nie pasuje do wymagań",
    reasons: [
      { value: "missing_skill", label: "Brak kluczowej umiejętności" },
      { value: "too_junior", label: "Za mało doświadczenia" },
      { value: "overqualified", label: "Za wysoki poziom (overqualified)" },
      { value: "other_level_or_role", label: "Inny poziom lub inna rola" },
      { value: "location_mode", label: "Lokalizacja lub tryb pracy" },
      { value: "no_polish", label: "Brak polskiego" },
      { value: "weak_english", label: "Angielski za słaby" },
    ],
  },
  {
    title: "Pieniądze i dane",
    reasons: [
      { value: "too_expensive", label: "Za droga" },
      { value: "outdated_cv", label: "CV nieaktualne" },
      { value: "profile_mismatch", label: "Profil w bazie się nie zgadza" },
      { value: "wrong_phone", label: "Błędny numer telefonu" },
    ],
  },
  {
    title: "Sprawa osoby",
    reasons: [
      { value: "not_looking", label: "Nie szuka pracy" },
      { value: "no_answer", label: "Nie odbiera (3 próby)" },
      { value: "in_other_process", label: "Już u nas w innym procesie" },
      { value: "client_employed", label: "Pracuje u tego klienta (też przez inną firmę)" },
      { value: "client_refused", label: "Nie chce do tego klienta" },
      { value: "client_other_vendor", label: "Zgłoszony do klienta przez inną firmę" },
      { value: "contract_form", label: "Forma umowy (UoP / B2B)" },
      { value: "other", label: "Inne — opisz" },
    ],
  },
];

/**
 * Powód z szablonu procesu dla powodu dla systemu (27.10.2026): przy osobie od
 * systemu okno pyta o powód raz, a powód do raportu lejka liczy się z tej mapy.
 * Klucz `rejection_reasons.name` szablonu domyślnego; `null` — „Inne” z nazwą
 * powodu jako opisem, bo w szablonie nie ma odpowiednika. Od 04.11.2026 (0646)
 * sprawy osoby mają własne powody; koszyki raportu liczy serwer z powodu dla
 * systemu (`autofill_feedback.bucket_for`), więc ta mapa ich nie zmienia.
 */
export const AUTOFILL_TEMPLATE_REASON: Record<AutofillReason, string | null> = {
  missing_skill: "Nie spełnia wymagań technicznych",
  too_junior: "Brak doświadczenia",
  overqualified: null,
  other_level_or_role: "Nie spełnia wymagań technicznych",
  location_mode: "work_mode_mismatch",
  language: null,
  too_expensive: "Za wysokie oczekiwania finansowe",
  outdated_cv: null,
  profile_mismatch: null,
  wrong_phone: "no_contact",
  not_looking: "not_looking_for_work",
  no_answer: "no_contact",
  in_other_process: null,
  client_employed: "client_conflict",
  client_refused: "client_conflict",
  client_other_vendor: "client_conflict",
  no_polish: null,
  weak_english: null,
  contract_form: null,
  cleanup: null,
  other: null,
};

/**
 * Powód z szablonu jest tu szerszy niż wybór w oknie („Brak kontaktu” przy
 * złym numerze), więc nazwa powodu zostaje w opisie, żeby historia nie straciła
 * szczegółu, który dotąd niosło „Inne”.
 */
const COARSER_TEMPLATE_REASON: ReadonlySet<AutofillReason> = new Set([
  "wrong_phone",
  "client_employed",
  "client_refused",
  "client_other_vendor",
]);

export function autofillReasonKeepsLabel(reason: AutofillReason): boolean {
  return COARSER_TEMPLATE_REASON.has(reason);
}

export function autofillReasonLabel(reason: AutofillReason): string {
  for (const group of AUTOFILL_REASON_GROUPS) {
    const found = group.reasons.find((r) => r.value === reason);
    if (found) return found.label;
  }
  // „Język” zastąpiły 12.11.2026 „Brak polskiego” i „Angielski za słaby”;
  // stare wpisy dalej mają tę nazwę.
  if (reason === "language") return "Język";
  // „Porządki” (16.11.2026) są tylko w porcji, poza listą okna odrzucenia.
  if (reason === "cleanup") return "Porządki (nie ocena osoby)";
  return reason;
}

/** „Brak: bigquery (tylko wzmianka), sql” — opis do historii procesu. */
export function gapsNote(gaps: readonly AutofillGap[], extra = ""): string {
  const parts = gaps.map((g) => (g.kind === "missing" ? g.label : `${g.label} (${GAP_KIND_LABEL[g.kind]})`));
  const text = [parts.join(", "), extra.trim()].filter(Boolean).join("; ");
  return text ? `Brak: ${text}` : "";
}

/** Powód z listy rekrutacji dla powodu dla systemu; bez odpowiednika — „Inne”. */
export function templateReasonFor<T extends { name?: string; label: string }>(
  reason: AutofillReason | null,
  reasons: T[],
): T | undefined {
  if (!reason) return undefined;
  const name = AUTOFILL_TEMPLATE_REASON[reason];
  return (
    (name ? reasons.find((r) => r.name?.trim() === name) : undefined) ??
    reasons.find((r) => r.label.trim() === "Inne")
  );
}

const DECISION_COLUMNS: ReadonlySet<BoardColumnKey> = new Set(["new", "screening"]);

/**
 * Czy odrzucenie z tej kolumny pyta o powód z listy okna („Nie pasuje do
 * wymagań” / „Pieniądze i dane” / „Sprawa osoby”). Od 19.11.2026 tak samo przy
 * karcie dodanej ręcznie — zespół wolał tę listę od krótkiej z szablonu.
 */
export function isDecisionColumn(fromColumn: BoardColumnKey | null | undefined): boolean {
  return fromColumn != null && DECISION_COLUMNS.has(fromColumn);
}

/** Czy ruch na „Odrzucony” tej osoby wymaga powodu dla systemu. */
export function needsAutofillReason(
  item: { entry_source?: string | null },
  fromColumn: BoardColumnKey | null | undefined,
): boolean {
  return item.entry_source === "system" && isDecisionColumn(fromColumn);
}

/** Pola żądania `/api/pipeline/move` dla wybranego powodu. */
export function autofillMoveFields(choice: AutofillFeedbackChoice | null | undefined): {
  autofill_reason?: AutofillReason;
  autofill_learned_from?: AutofillLearnedFrom;
  autofill_rate_hourly?: number;
  autofill_whole_client?: boolean;
  autofill_not_looking_until?: string;
  autofill_gaps?: AutofillGap[];
  autofill_detail?: AutofillDetail;
} {
  if (!choice) return {};
  return {
    autofill_reason: choice.reason,
    autofill_learned_from: choice.learnedFrom,
    autofill_rate_hourly: choice.rateHourly ?? undefined,
    autofill_whole_client:
      choice.wholeClient && CLIENT_WIDE_REASONS.has(choice.reason) ? true : undefined,
    autofill_not_looking_until:
      choice.reason === "not_looking" && choice.notLookingUntil ? choice.notLookingUntil : undefined,
    autofill_gaps:
      choice.reason === "missing_skill" && choice.gaps && choice.gaps.length > 0 ? choice.gaps : undefined,
    autofill_detail: choice.detail && Object.keys(choice.detail).length > 0 ? choice.detail : undefined,
  };
}

/**
 * Do którego kosza raportu trafi odrzucenie — podpowiedź w oknie. Kosz liczy
 * serwer z migawki; tu tylko zdanie dla rekrutera.
 */
export function autofillBucketHint(reason: AutofillReason | null, rateKnown: boolean): string | null {
  if (!reason) return null;
  if (reason === "too_expensive") {
    return rateKnown
      ? "Do raportu: system znał stawkę — porówna ją z budżetem rekrutacji."
      : "Do raportu: „Brak danych”, nie błąd wyszukiwania — system nie znał stawki.";
  }
  if (reason === "outdated_cv" || reason === "profile_mismatch") {
    return "Do raportu: „Brak danych” — to poprawiamy w bazie, nie w wyszukiwaniu.";
  }
  if (reason === "client_employed" || reason === "client_other_vendor") {
    return "Do raportu: „Brak danych” — system nie wiedział, że pracuje u klienta albo zgłosiła go inna firma.";
  }
  if (reason === "wrong_phone") {
    return "Do raportu: „Brak danych” — numer w profilu trzeba poprawić.";
  }
  if (
    reason === "not_looking" ||
    reason === "no_answer" ||
    reason === "in_other_process" ||
    reason === "client_refused" ||
    reason === "contract_form"
  ) {
    return "Do raportu: „Sprawa osoby” — nie liczymy jako błędu wyszukiwania.";
  }
  if (reason === "other") return "Do raportu: „Inne” — z Twoim opisem.";
  if (reason === "cleanup") return "Nie liczy się do raportu — to porządki, nie ocena osoby.";
  return "Do raportu: „Błąd wyszukiwania” — z tego poprawiamy podpowiedzi.";
}

/** Do kiedy „Nie szuka pracy” — gotowe odcinki w oknie odrzucenia (28.10.2026). */
export const NOT_LOOKING_SPANS: { months: number; label: string }[] = [
  { months: 3, label: "3 miesiące" },
  { months: 6, label: "6 miesięcy" },
  { months: 12, label: "Rok (ma projekt)" },
];
export const NOT_LOOKING_DEFAULT_MONTHS = 3;

/**
 * „RRRR-MM-DD” za `months` miesięcy od dziś w kalendarzu firmy. Dzień ponad
 * długość miesiąca spada na jego ostatni dzień (31.08 + 6 mies. = 28.02).
 */
export function notLookingUntil(months: number, today: string = warsawToday()): string {
  const [y, m, d] = today.split("-").map(Number);
  const target = new Date(Date.UTC(y, m - 1 + months, 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(d, lastDay));
  return target.toISOString().slice(0, 10);
}
