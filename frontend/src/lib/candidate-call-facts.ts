/**
 * Fakty z telefonu praktykanta (0373) na profilu kandydata.
 *
 * Zapisuje je wyłącznie ekran praktykanta; profil tylko pokazuje. Przy
 * `call_facts_verified_at` stawka profilu (`expected_rate_hourly`) jest
 * MINIMUM z rozmowy, więc etykieta stawki zmienia się razem z tym polem.
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

/** Etykieta kafelka stawki: po rozmowie to minimum, nie „oczekiwana” stawka. */
export function rateFactLabel(facts: CandidateCallFacts): string {
  return facts.call_facts_verified_at ? "Minimalna stawka B2B netto" : "Stawka B2B";
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
