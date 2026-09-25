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
}

export function planReassign(
  jobOrder: readonly number[],
  peopleByJob: Readonly<Record<number, readonly SentPerson[] | undefined>>,
  excluded: ReadonlySet<number>,
): ReassignPlan {
  const seen = new Set<number>();
  const candidateIds: number[] = [];
  const rows: Record<number, PlannedPerson[]> = {};
  for (const jobId of jobOrder) {
    const people = peopleByJob[jobId];
    if (!people) continue;
    rows[jobId] = people.map((person) => {
      if (!person.selectable) return { person, state: "locked" };
      if (seen.has(person.candidate_id)) return { person, state: "duplicate" };
      seen.add(person.candidate_id);
      if (excluded.has(person.candidate_id)) return { person, state: "unselected" };
      candidateIds.push(person.candidate_id);
      return { person, state: "selected" };
    });
  }
  return { rows, candidateIds };
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

/** Ile osób z tej rekrutacji da się przepiąć (nagłówek grupy). */
export function selectableCount(people: readonly SentPerson[] | undefined): number {
  return (people ?? []).filter((p) => p.selectable).length;
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
};

/** „CV wysłane 12.09.2026 · klient odrzucił”. */
export function personStatusLine(person: SentPerson): string {
  const stage = STAGE_LABEL[person.furthest_stage] ?? person.furthest_stage;
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
