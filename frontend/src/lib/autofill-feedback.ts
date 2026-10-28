/**
 * Odrzucenie osoby od systemu z powodem (silnik „Nowi na 20”, decyzja Artura
 * 23.10.2026, makieta A3). Lustro listy i reguły serwera
 * (`backend/app/services/autofill_feedback.py`, `StageMove.autofill_*`):
 * odrzucenie osoby od systemu z „Nowych” albo „Screeningu” wymaga powodu
 * ze stałej listy i „skąd wiesz”, inaczej 422 `AUTOFILL_REASON_REQUIRED`.
 */
import type { BoardColumnKey } from "@/lib/board-stages";

export type AutofillReason =
  | "missing_skill"
  | "too_junior"
  | "other_level_or_role"
  | "location_mode"
  | "language"
  | "too_expensive"
  | "outdated_cv"
  | "profile_mismatch"
  | "not_looking"
  | "no_answer"
  | "in_other_process"
  | "client_employed"
  | "client_refused"
  | "other";

export type AutofillLearnedFrom = "profile" | "call";

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
}

/** Powody, przy których okno pyta „na cały klient” (lustro `CLIENT_WIDE_REASONS`). */
export const CLIENT_WIDE_REASONS: ReadonlySet<AutofillReason> = new Set([
  "client_employed",
  "client_refused",
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
      { value: "other_level_or_role", label: "Inny poziom lub inna rola" },
      { value: "location_mode", label: "Lokalizacja lub tryb pracy" },
      { value: "language", label: "Język" },
    ],
  },
  {
    title: "Pieniądze i dane",
    reasons: [
      { value: "too_expensive", label: "Za droga" },
      { value: "outdated_cv", label: "CV nieaktualne" },
      { value: "profile_mismatch", label: "Profil w bazie się nie zgadza" },
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
      { value: "other", label: "Inne — opisz" },
    ],
  },
];

/**
 * Powód z szablonu procesu dla powodu dla systemu (27.10.2026): przy osobie od
 * systemu okno pyta o powód raz, a powód do raportu lejka liczy się z tej mapy.
 * Klucz `rejection_reasons.name` szablonu domyślnego; `null` — „Inne” z nazwą
 * powodu jako opisem, bo w szablonie nie ma odpowiednika.
 */
export const AUTOFILL_TEMPLATE_REASON: Record<AutofillReason, string | null> = {
  missing_skill: "Nie spełnia wymagań technicznych",
  too_junior: "Brak doświadczenia",
  other_level_or_role: "Nie spełnia wymagań technicznych",
  location_mode: "work_mode_mismatch",
  language: null,
  too_expensive: "Za wysokie oczekiwania finansowe",
  outdated_cv: null,
  profile_mismatch: null,
  not_looking: null,
  no_answer: null,
  in_other_process: null,
  client_employed: null,
  client_refused: null,
  other: null,
};

export function autofillReasonLabel(reason: AutofillReason): string {
  for (const group of AUTOFILL_REASON_GROUPS) {
    const found = group.reasons.find((r) => r.value === reason);
    if (found) return found.label;
  }
  return reason;
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

/** Czy ruch na „Odrzucony” tej osoby wymaga powodu dla systemu. */
export function needsAutofillReason(
  item: { entry_source?: string | null },
  fromColumn: BoardColumnKey | null | undefined,
): boolean {
  return item.entry_source === "system" && fromColumn != null && DECISION_COLUMNS.has(fromColumn);
}

/** Pola żądania `/api/pipeline/move` dla wybranego powodu. */
export function autofillMoveFields(choice: AutofillFeedbackChoice | null | undefined): {
  autofill_reason?: AutofillReason;
  autofill_learned_from?: AutofillLearnedFrom;
  autofill_rate_hourly?: number;
  autofill_whole_client?: boolean;
} {
  if (!choice) return {};
  return {
    autofill_reason: choice.reason,
    autofill_learned_from: choice.learnedFrom,
    autofill_rate_hourly: choice.rateHourly ?? undefined,
    autofill_whole_client:
      choice.wholeClient && CLIENT_WIDE_REASONS.has(choice.reason) ? true : undefined,
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
  if (reason === "client_employed") {
    return "Do raportu: „Brak danych” — system nie wiedział, że pracuje u klienta (np. przez inną firmę).";
  }
  if (
    reason === "not_looking" ||
    reason === "no_answer" ||
    reason === "in_other_process" ||
    reason === "client_refused"
  ) {
    return "Do raportu: „Sprawa osoby” — nie liczymy jako błędu wyszukiwania.";
  }
  if (reason === "other") return "Do raportu: „Inne” — z Twoim opisem.";
  return "Do raportu: „Błąd wyszukiwania” — z tego poprawiamy podpowiedzi.";
}
