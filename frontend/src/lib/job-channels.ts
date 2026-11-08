/**
 * Koszyki „Baza” / „LinkedIn” w zespole rekrutacji (decyzja Artura 06.11.2026,
 * wariant B z makiet). Lustro `backend/app/services/job_channels.py`.
 *
 * - Osoba z zespołu jest w koszyku `base` (szuka w bazie NEXUSA), `linkedin`
 *   albo jeszcze w żadnym.
 * - Do koszyka dołącza sam rekruter albo Olaf / Delivery Lead / admin; plan
 *   liczby osób ustawia tylko ta druga grupa.
 * - Rekruter spoza zespołu, który rusza karty, nie jest blokowany — ekrany
 *   pokazują go jako „pracuje bez przypisania”.
 */
import api from "@/lib/api";
import { countPl } from "@/lib/plural-pl";
import type { RecruiterChannel } from "@/lib/job-team";

export type { RecruiterChannel };

export const CHANNELS: readonly RecruiterChannel[] = ["base", "linkedin"];

export const CHANNEL_LABELS: Record<RecruiterChannel, string> = {
  base: "Baza",
  linkedin: "LinkedIn",
};

/** Ile osób może mieć plan koszyka — lustro `PLAN_MAX` na serwerze. */
export const PLAN_MAX = 20;

export interface ChannelPlan {
  base: number | null;
  linkedin: number | null;
}

export interface UnassignedWorker {
  user_id: number;
  name: string;
  /** Ilu różnych kandydatów osoba dodała albo przesunęła w ostatnich 30 dniach. */
  cards: number;
}

interface Channeled {
  proposed: boolean;
  channel?: RecruiterChannel | null;
}

export interface ChannelBuckets<T> {
  base: T[];
  linkedin: T[];
  /** Pracują, ale nikt nie wybrał koszyka. */
  none: T[];
}

/** Pracujący podzieleni na koszyki; propozycje automatu pomija (to nie praca). */
export function channelBuckets<T extends Channeled>(
  people: readonly T[],
): ChannelBuckets<T> {
  const out: ChannelBuckets<T> = { base: [], linkedin: [], none: [] };
  for (const person of people) {
    if (person.proposed) continue;
    if (person.channel === "base") out.base.push(person);
    else if (person.channel === "linkedin") out.linkedin.push(person);
    else out.none.push(person);
  }
  return out;
}

/** Ilu osób brakuje do planu koszyka; 0 = plan spełniony albo go nie ma. */
export function planShortfall(plan: number | null | undefined, count: number): number {
  if (plan == null) return 0;
  return Math.max(0, plan - count);
}

export function planOf(job: {
  channel_plan_base?: number | null;
  channel_plan_linkedin?: number | null;
}): ChannelPlan {
  return {
    base: job.channel_plan_base ?? null,
    linkedin: job.channel_plan_linkedin ?? null,
  };
}

/** Pole planu z formularza: puste = bez planu, liczba spoza 0–20 = błąd. */
export function parsePlanInput(raw: string): number | null | "invalid" {
  const value = raw.trim();
  if (value === "") return null;
  if (!/^\d+$/.test(value)) return "invalid";
  const n = Number(value);
  return n > PLAN_MAX ? "invalid" : n;
}

export function unassignedWorkersKey(jobId: number) {
  return ["job-unassigned-workers", jobId] as const;
}

export interface JobNewProfiles {
  added: number;
  reached_cv: number;
}

export function jobNewProfilesKey(jobId: number) {
  return ["job-new-profiles", jobId] as const;
}

export async function fetchJobNewProfiles(jobId: number): Promise<JobNewProfiles> {
  return api.get(`/api/jobs/${jobId}/new-profiles`).then((r) => r.data);
}

/** „Nowe profile w 7 dni: 4, doszły do CV: 3” — okienko zespołu i wiersz Daily. */
export function newProfilesText(added: number, reachedCv: number): string {
  return `Nowe profile w 7 dni: ${added}, doszły do CV: ${reachedCv}`;
}

export async function setRecruiterChannel(
  jobId: number,
  userId: number,
  channel: RecruiterChannel | null,
): Promise<void> {
  await api.put(`/api/jobs/${jobId}/channels/${userId}`, { channel });
}

/** Dopisanie osoby do zespołu od razu w koszyku („Dołącz do bazy”, „+ Dodaj do LinkedIna”). */
export async function joinChannel(
  jobId: number,
  userId: number,
  channel: RecruiterChannel,
): Promise<void> {
  await api.post(`/api/jobs/${jobId}/collaborators`, { user_id: userId, channel });
}

export async function setChannelPlan(jobId: number, plan: ChannelPlan): Promise<void> {
  await api.put(`/api/jobs/${jobId}/channel-plan`, plan);
}

export async function fetchUnassignedWorkers(jobId: number): Promise<UnassignedWorker[]> {
  return api.get(`/api/jobs/${jobId}/unassigned-workers`).then((r) => r.data);
}

const CHANNEL_ORDER: Record<string, number> = { base: 0, linkedin: 1 };

/** Osoby w kolejności koszyków: Baza, LinkedIn, bez koszyka (stabilnie w obrębie). */
export function sortByChannel<T extends { channel?: RecruiterChannel | null }>(
  people: readonly T[],
): T[] {
  return people
    .map((person, index) => ({ person, index }))
    .sort(
      (a, b) =>
        (CHANNEL_ORDER[a.person.channel ?? ""] ?? 2) -
          (CHANNEL_ORDER[b.person.channel ?? ""] ?? 2) || a.index - b.index,
    )
    .map(({ person }) => person);
}

/**
 * Ostrzeżenia wiersza pulpitu: brak do planu koszyka, osoby bez koszyka,
 * rekruterzy ruszający karty bez przypisania. Request z championem — nic
 * (nikt już nie szuka).
 */
export function boardChannelNotes(request: {
  champion?: boolean;
  people: readonly Channeled[];
  channel_plan_base?: number | null;
  channel_plan_linkedin?: number | null;
  unassigned_workers?: readonly unknown[] | null;
}): string[] {
  if (request.champion) return [];
  const buckets = channelBuckets(request.people);
  const plan = planOf(request);
  const notes: string[] = [];
  for (const channel of CHANNELS) {
    const missing = planShortfall(plan[channel], buckets[channel].length);
    if (missing > 0) {
      notes.push(`${CHANNEL_LABELS[channel]}: brakuje ${missing} z ${plan[channel]}`);
    }
  }
  if (buckets.none.length > 0) {
    notes.push(`bez koszyka: ${countPl(buckets.none.length, "osoba", "osoby", "osób")}`);
  }
  const unassigned = request.unassigned_workers?.length ?? 0;
  if (unassigned > 0) {
    notes.push(`bez przypisania: ${countPl(unassigned, "osoba", "osoby", "osób")}`);
  }
  return notes;
}
