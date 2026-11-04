/**
 * Panel przepięć (25.09.2026) — reguły zaznaczania, bez Reacta.
 *
 * Decyzje Artura:
 *  - rekrutacja nigdy nie jest zaznaczona sama (incydent 23.09.2026: zapis
 *    szkicu przepiął 41 osób, których nikt nie wybrał);
 *  - kliknięcie rekrutacji zaznacza WSZYSTKICH wysłanych w niej do klienta,
 *    także odrzuconych przez klienta;
 *  - zatrudnionych i osoby już w tej rekrutacji widać, ale nie da się ich
 *    przepiąć (serwer zwraca je z `selectable: false`).
 *
 * Osoba wysłana w dwóch wybranych rekrutacjach liczy się raz — przy pierwszej
 * klikniętej.
 *
 * „Pozostali” (02.10.2026): osoby z tej samej rekrutacji, których klient nie
 * widział (`sent: false`). Nie zaznaczają się same — wybiera je człowiek —
 * i nie idą przez przepięcie, tylko przez zwykłe dodanie do „Nowych”.
 */

import type { SentOutcome, SentPerson, SimilarJobsPayload } from "@/lib/similar-jobs-api";

/** Sufit jednego przepięcia — lustro `candidate_ids` (≤ 100) w API. */
export const MAX_REASSIGN_PEOPLE = 100;

export type PersonRowState = "selected" | "unselected" | "locked" | "duplicate";

export interface PlannedPerson {
  person: SentPerson;
  state: PersonRowState;
}

export interface ReassignPlan {
  /** Wiersze per rekrutacja, w kolejności kliknięcia. */
  rows: Record<number, PlannedPerson[]>;
  /** Kto zostanie przepięty, bez powtórzeń. */
  candidateIds: number[];
  /** Zaznaczeni „pozostali” — dodawani zwykłą drogą, nie przepięciem. */
  restIds: number[];
}

const EMPTY_IDS: ReadonlySet<number> = new Set();

export function planReassign(
  jobOrder: readonly number[],
  peopleByJob: Readonly<Record<number, readonly SentPerson[] | undefined>>,
  excluded: ReadonlySet<number>,
  /** „Pozostali” wybrani ręcznie (domyślnie nikt). */
  included: ReadonlySet<number> = EMPTY_IDS,
): ReassignPlan {
  // Osoba wysłana do klienta w KTÓREJKOLWIEK wybranej rekrutacji jest
  // przepięciem — także wtedy, gdy wcześniej stoi na liście „pozostałych”.
  const sentSomewhere = new Set<number>();
  for (const jobId of jobOrder) {
    for (const person of peopleByJob[jobId] ?? []) {
      if (person.selectable && person.sent !== false) sentSomewhere.add(person.candidate_id);
    }
  }
  const seen = new Set<number>();
  const candidateIds: number[] = [];
  const restIds: number[] = [];
  const rows: Record<number, PlannedPerson[]> = {};
  for (const jobId of jobOrder) {
    const people = peopleByJob[jobId];
    if (!people) continue;
    rows[jobId] = people.map((person) => {
      if (!person.selectable) return { person, state: "locked" };
      const rest = person.sent === false;
      if (seen.has(person.candidate_id) || (rest && sentSomewhere.has(person.candidate_id))) {
        return { person, state: "duplicate" };
      }
      seen.add(person.candidate_id);
      if (rest) {
        if (!included.has(person.candidate_id)) return { person, state: "unselected" };
        restIds.push(person.candidate_id);
        return { person, state: "selected" };
      }
      if (excluded.has(person.candidate_id)) return { person, state: "unselected" };
      candidateIds.push(person.candidate_id);
      return { person, state: "selected" };
    });
  }
  return { rows, candidateIds, restIds };
}

export interface PreviewEntry {
  jobId: number;
  person: SentPerson;
}

/**
 * Kolejność podglądu osób (‹ ›, „2 z 10”): rekrutacje tak, jak stoją na
 * ekranie, w każdej osoby w kolejności wierszy. Osoba wysłana w dwóch
 * rekrutacjach wchodzi raz — przy pierwszej widocznej.
 */
export function previewSequence(
  jobOrder: readonly number[],
  rows: Readonly<Record<number, readonly PlannedPerson[] | undefined>>,
): PreviewEntry[] {
  const seen = new Set<number>();
  const out: PreviewEntry[] = [];
  for (const jobId of jobOrder) {
    for (const { person } of rows[jobId] ?? []) {
      if (seen.has(person.candidate_id)) continue;
      seen.add(person.candidate_id);
      out.push({ jobId, person });
    }
  }
  return out;
}

/**
 * Ile RÓŻNYCH osób z podpowiadanych, niepołączonych rekrutacji da się
 * przepiąć tutaj — liczy serwer tą samą regułą co panel (bez zatrudnionych
 * i obecnych w rekrutacji). `null` = nie wiadomo (stary serwer, brak danych):
 * nagłówek, pasek i „Najbliższy krok” wtedy milczą.
 */
export function similarPeopleWaiting(
  payload: Pick<SimilarJobsPayload, "reassignable_people"> | null | undefined,
): number | null {
  const n = payload?.reassignable_people;
  return typeof n === "number" && n >= 0 ? n : null;
}

/**
 * Liczba na kaflu „Podobne rekrutacje”: wysłani do klienta + pozostali
 * (od Screeningu wzwyż). `null` = nie wiadomo — kafel wtedy milczy.
 */
export function similarPeopleTotal(
  payload: Pick<SimilarJobsPayload, "reassignable_people" | "other_people"> | null | undefined,
): { sent: number; other: number; total: number } | null {
  const sent = similarPeopleWaiting(payload);
  if (sent === null) return null;
  const rawOther = payload?.other_people;
  const other = typeof rawOther === "number" && rawOther >= 0 ? rawOther : 0;
  return { sent, other, total: sent + other };
}

/** Ile osób z tej rekrutacji da się przepiąć (nagłówek grupy). */
export function selectableCount(people: readonly SentPerson[] | undefined): number {
  return (people ?? []).filter((p) => p.selectable && p.sent !== false).length;
}

export const OUTCOME_LABEL: Record<SentOutcome, string> = {
  in_progress: "proces trwa",
  rejected_by_client: "klient odrzucił",
  rejected: "odrzucony",
  withdrawn: "zrezygnował",
  hired: "zatrudniony",
};

const STAGE_LABEL: Record<string, string> = {
  cv_sent: "CV wysłane",
  client_interview: "rozmowa u klienta",
  acceptance: "akceptacja klienta",
  negotiation: "negocjacje",
  onboarding: "onboarding",
  hired: "zatrudniony",
  // „Pozostali” — najdalszy etap przed wysłaniem do klienta.
  prep_call: "screening",
  screening: "screening",
  verified: "zweryfikowany",
  interview: "QC CV",
};

/** „CV wysłane 12.09.2026 · klient odrzucił”; pozostali: „najdalej: screening · proces trwa”. */
export function personStatusLine(person: SentPerson): string {
  const stage = STAGE_LABEL[person.furthest_stage] ?? person.furthest_stage;
  if (person.sent === false) {
    const rest = [`najdalej: ${stage}`, OUTCOME_LABEL[person.outcome]];
    if (person.already_in_job) rest.push("już w tej rekrutacji");
    return rest.join(" · ");
  }
  const when = person.sent_at ? ` ${formatDate(person.sent_at)}` : "";
  const parts = [`${stage}${person.furthest_stage === "cv_sent" ? when : ""}`];
  if (person.outcome !== "hired" || person.furthest_stage !== "hired") {
    parts.push(OUTCOME_LABEL[person.outcome]);
  }
  if (person.already_in_job) parts.push("już w tej rekrutacji");
  return parts.join(" · ");
}

function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return d && m && y ? `${d}.${m}.${y}` : iso;
}

export function pluralPeople(n: number): string {
  if (n === 1) return "osobę";
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return "osoby";
  return "osób";
}

export function pluralJobs(n: number): string {
  if (n === 1) return "rekrutację";
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return "rekrutacje";
  return "rekrutacji";
}
