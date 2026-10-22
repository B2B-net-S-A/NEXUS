/**
 * Zakładka „Podobni” (22.10.2026) — reguły widoku bez Reacta.
 *
 * Podobny ≠ pasujący (decyzja Artura): kolejność listy nie zależy od
 * rekrutacji, a wynik sprawdzenia pod rekrutację tylko się na nią nakłada.
 * Przy dodaniu osoba bez umiejętności krytycznej jest domyślnie odznaczona,
 * a zaznaczona wymaga zdania „dlaczego mimo to” (serwer pilnuje tego samego).
 */

import { foldSkillName } from "@/lib/skill-display";
import { jobNameText } from "@/lib/job-name-text";
import type { JobNames } from "@/lib/job-names";
import type {
  CandidateCheck,
  JobCheck,
  SimilarPerson,
} from "@/lib/api/similarCandidates";

/** Imię i nazwisko, a bez nich numer — nigdy pusty napis. */
export function personName(person: Pick<SimilarPerson, "id" | "name" | "lastname">): string {
  return `${person.name ?? ""} ${person.lastname ?? ""}`.trim() || `Osoba #${person.id}`;
}

export function personFirstName(person: Pick<SimilarPerson, "id" | "name" | "lastname">): string {
  return person.name?.trim() || personName(person);
}

/**
 * Nazwa umiejętności do pokazania: kanoniczna ze słownika (`GET /api/skills`),
 * a bez wpisu — zapis z serwera z wielką literą.
 */
export function prettySkill(name: string, dictionary: Map<string, string>): string {
  const known = dictionary.get(foldSkillName(name));
  if (known) return known;
  return name ? name.charAt(0).toUpperCase() + name.slice(1) : name;
}

/** „1 wspólna umiejętność”, „3 wspólne umiejętności”, „5 wspólnych umiejętności”. */
export function sharedSkillsText(count: number): string {
  if (count === 1) return "1 wspólna umiejętność";
  const lastTwo = count % 100;
  const last = count % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return `${count} wspólne umiejętności`;
  }
  return `${count} wspólnych umiejętności`;
}

/** Stawka „70 zł/h”; inna waluta zostaje ze swoim kodem. */
export function rateText(amount: number | null, currency: string | null): string {
  if (amount == null) return "—";
  const value = Math.round(amount).toLocaleString("pl-PL");
  return !currency || currency === "PLN" ? `${value} zł/h` : `${value} ${currency}/h`;
}

/** Rekrutacja do wyboru w oknie i w „Sprawdź pod rekrutację”. */
export interface PickableJob {
  id: number;
  names: JobNames;
  clientName: string | null;
  group: "source" | "mine" | "search";
}

export function jobLabel(job: PickableJob): string {
  return jobNameText(job.names);
}

/** Rekrutacje osoby z profilu na górze, potem moje — bez powtórzeń. */
export function mergePickableJobs(...groups: PickableJob[][]): PickableJob[] {
  const seen = new Set<number>();
  const out: PickableJob[] = [];
  for (const group of groups) {
    for (const job of group) {
      if (seen.has(job.id)) continue;
      seen.add(job.id);
      out.push(job);
    }
  }
  return out;
}

export function checksByCandidate(job: JobCheck | undefined): Map<number, CandidateCheck> {
  return new Map((job?.candidates ?? []).map((c) => [c.candidate_id, c]));
}

/** Kogo dodać od razu: bez braku krytycznej i bez karty w tej rekrutacji. */
export function defaultSelected(
  ids: number[],
  checks: Map<number, CandidateCheck>,
): Set<number> {
  return new Set(
    ids.filter((id) => {
      const check = checks.get(id);
      return check != null && !check.in_job && check.missing.length === 0;
    }),
  );
}

export interface AddPlan {
  /** Osoby do wysłania. */
  ids: number[];
  /** Zdania dla osób bez krytycznej (tylko zaznaczonych). */
  reasons: Record<number, string>;
  /** Zaznaczone bez krytycznej i bez zdania — przycisk czeka na nie. */
  waitingForReason: number[];
}

export function addPlan(
  selected: Set<number>,
  checks: Map<number, CandidateCheck>,
  reasons: Record<number, string>,
): AddPlan {
  const ids: number[] = [];
  const out: Record<number, string> = {};
  const waiting: number[] = [];
  for (const id of selected) {
    const check = checks.get(id);
    if (check?.in_job) continue;
    ids.push(id);
    if (check && check.missing.length > 0) {
      const reason = (reasons[id] ?? "").trim();
      if (reason) out[id] = reason;
      else waiting.push(id);
    }
  }
  return { ids, reasons: out, waitingForReason: waiting };
}
