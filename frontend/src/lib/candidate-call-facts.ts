/**
 * Fakty z telefonu praktykanta (0374) na profilu kandydata.
 *
 * Zapisuje je ekran praktykanta, a poprawia pasek faktów profilu
 * (`PATCH /api/candidates/{id}/call-facts`, audyt 24.09.2026 — pomyłkowy
 * „Tylko etat” ukrywał kandydata bez drogi powrotu). Przy
 * `call_facts_verified_at` stawka profilu (`expected_rate_hourly`) jest
 * MINIMUM z rozmowy, dopóki nikt jej potem nie zmienił.
 */
export type B2bWillingness = "b2b" | "would_switch" | "employment_only";
export type WorkTimePreference =
  | "full_time_only"
  | "also_part_time"
  | "part_time_only";

export interface CandidateCallFacts {
  b2b_willingness?: B2bWillingness | null;
  accepts_below_min_rate?: boolean | null;
  accepts_more_office_days?: boolean | null;
  work_time_preference?: WorkTimePreference | null;
  call_facts_verified_at?: string | null;
  call_facts_verified_by_name?: string | null;
}

export type CallFactTone = "neutral" | "danger";

export interface CallFact {
  key: string;
  label: string;
  tone: CallFactTone;
}

const B2B_LABELS: Record<B2bWillingness, string> = {
  b2b: "B2B",
  would_switch: "przejdzie na B2B",
  employment_only: "Tylko etat — nie bierzemy pod uwagę",
};

const WORK_TIME_LABELS: Record<WorkTimePreference, string> = {
  full_time_only: "tylko full-time",
  also_part_time: "też part-time",
  part_time_only: "tylko part-time",
};

// Data rozmowy w kalendarzu firmy (znacznik przychodzi w UTC), zawsze DD.MM.RRRR.
const VERIFIED_DATE = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Warsaw",
});

const consent = (value: boolean) => (value ? "dzwonić" : "nie dzwonić");

/** „Zweryfikowane telefonicznie DD.MM.RRRR · Imię Nazwisko” albo null. */
export function callFactsVerifiedLabel(facts: CandidateCallFacts): string | null {
  if (!facts.call_facts_verified_at) return null;
  const parsed = new Date(facts.call_facts_verified_at);
  if (Number.isNaN(parsed.getTime())) return null;
  const date = VERIFIED_DATE.format(parsed);
  const who = facts.call_facts_verified_by_name?.trim();
  return who
    ? `Zweryfikowane telefonicznie ${date} · ${who}`
    : `Zweryfikowane telefonicznie ${date}`;
}

/** Zapas na zapis stawki i znacznika rozmowy w jednej transakcji. */
const SAME_CALL_TOLERANCE_MS = 60_000;

/**
 * Etykieta kafelka stawki: po rozmowie to minimum, nie „oczekiwana” stawka.
 * Stawka zmieniona PO rozmowie (`rateUpdatedAt` z `GET …/profile-rate`) nie
 * jest już minimum z telefonu — wtedy zwykła „Stawka B2B”.
 */
export function rateFactLabel(
  facts: CandidateCallFacts,
  rateUpdatedAt?: string | null,
): string {
  const verified = facts.call_facts_verified_at
    ? Date.parse(facts.call_facts_verified_at)
    : Number.NaN;
  if (Number.isNaN(verified)) return "Stawka B2B";
  const updated = rateUpdatedAt ? Date.parse(rateUpdatedAt) : Number.NaN;
  if (!Number.isNaN(updated) && updated > verified + SAME_CALL_TOLERANCE_MS) {
    return "Stawka B2B";
  }
  return "Minimalna stawka B2B netto";
}

/** Wartości formularza korekty; `""` = „nie wiadomo” (czyści odpowiedź). */
export type CallFactsDraft = {
  b2b_willingness: B2bWillingness | "";
  work_time_preference: WorkTimePreference | "";
  accepts_below_min_rate: "yes" | "no" | "";
  accepts_more_office_days: "yes" | "no" | "";
};

export const B2B_OPTIONS: ReadonlyArray<{ value: B2bWillingness; label: string }> = [
  { value: "b2b", label: "Pracuje na B2B" },
  { value: "would_switch", label: "Przejdzie z etatu na B2B" },
  { value: "employment_only", label: "Tylko umowa o pracę" },
];

export const WORK_TIME_OPTIONS: ReadonlyArray<{
  value: WorkTimePreference;
  label: string;
}> = [
  { value: "full_time_only", label: "Tylko pełny etat" },
  { value: "also_part_time", label: "Pełny etat albo część etatu" },
  { value: "part_time_only", label: "Tylko część etatu" },
];

const consentDraft = (value: boolean | null | undefined): "yes" | "no" | "" =>
  value === true ? "yes" : value === false ? "no" : "";

const consentValue = (value: "yes" | "no" | ""): boolean | null =>
  value === "yes" ? true : value === "no" ? false : null;

export function callFactsDraft(facts: CandidateCallFacts): CallFactsDraft {
  return {
    b2b_willingness: facts.b2b_willingness ?? "",
    work_time_preference: facts.work_time_preference ?? "",
    accepts_below_min_rate: consentDraft(facts.accepts_below_min_rate),
    accepts_more_office_days: consentDraft(facts.accepts_more_office_days),
  };
}

export interface CallFactsPatch {
  b2b_willingness?: B2bWillingness | null;
  work_time_preference?: WorkTimePreference | null;
  accepts_below_min_rate?: boolean | null;
  accepts_more_office_days?: boolean | null;
}

/** Tylko pola, które się zmieniły — PATCH jest częściowy po stronie serwera. */
export function callFactsPatch(
  facts: CandidateCallFacts,
  draft: CallFactsDraft,
): CallFactsPatch {
  const before = callFactsDraft(facts);
  const patch: CallFactsPatch = {};
  if (draft.b2b_willingness !== before.b2b_willingness) {
    patch.b2b_willingness = draft.b2b_willingness || null;
  }
  if (draft.work_time_preference !== before.work_time_preference) {
    patch.work_time_preference = draft.work_time_preference || null;
  }
  if (draft.accepts_below_min_rate !== before.accepts_below_min_rate) {
    patch.accepts_below_min_rate = consentValue(draft.accepts_below_min_rate);
  }
  if (draft.accepts_more_office_days !== before.accepts_more_office_days) {
    patch.accepts_more_office_days = consentValue(draft.accepts_more_office_days);
  }
  return patch;
}

/** Fakty do pokazania, w stałej kolejności; brak odpowiedzi = brak pozycji. */
export function callFactItems(facts: CandidateCallFacts): CallFact[] {
  const items: CallFact[] = [];
  if (facts.b2b_willingness && B2B_LABELS[facts.b2b_willingness]) {
    items.push({
      key: "b2b",
      label: B2B_LABELS[facts.b2b_willingness],
      tone: facts.b2b_willingness === "employment_only" ? "danger" : "neutral",
    });
  }
  if (facts.work_time_preference && WORK_TIME_LABELS[facts.work_time_preference]) {
    items.push({
      key: "work_time",
      label: WORK_TIME_LABELS[facts.work_time_preference],
      tone: "neutral",
    });
  }
  if (typeof facts.accepts_below_min_rate === "boolean") {
    items.push({
      key: "below_min",
      label: `poniżej minimum: ${consent(facts.accepts_below_min_rate)}`,
      tone: "neutral",
    });
  }
  if (typeof facts.accepts_more_office_days === "boolean") {
    items.push({
      key: "office",
      label: `więcej dni w biurze: ${consent(facts.accepts_more_office_days)}`,
      tone: "neutral",
    });
  }
  return items;
}
