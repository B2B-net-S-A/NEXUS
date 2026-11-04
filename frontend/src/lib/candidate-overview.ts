/**
 * Zakładka „Przegląd” profilu kandydata (04.10.2026) — czyste reguły:
 * kto ma ruch w procesie w toku i która notatka jest „ostatnią rozmową”.
 *
 * Właściciela ruchu liczy serwer (`next_action_owner` w `/history`, ta sama
 * reguła co karta na Tablicy); tu tylko etykieta. Profil ogląda każda rola,
 * więc ruch rekrutera to „rekruter”, a nie „Twój ruch” jak na Tablicy.
 */
import { noteGroup } from "@/lib/candidate-note-groups";

const OWNER_LABEL: Record<string, string> = {
  recruiter: "rekruter",
  review: "do przejrzenia",
  client: "klient",
  candidate: "kandydat",
  delivery: "Delivery",
};

export function nextActionOwnerLabel(owner: string | null | undefined): string | null {
  if (!owner) return null;
  return OWNER_LABEL[owner] ?? null;
}

/** Pełne dni od `iso` do `now` (nigdy ujemne); `null`, gdy daty nie da się odczytać. */
export function daysSince(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  return Math.max(0, Math.floor((now.getTime() - at.getTime()) / 86_400_000));
}

export interface OverviewNote {
  id?: number | string | null;
  group?: string | null;
  is_system?: boolean | null;
  parent_note_id?: number | null;
  created_at?: string | null;
  timestamp?: string | null;
}

function noteTime(note: OverviewNote): number {
  const raw = note.created_at ?? note.timestamp;
  const value = raw ? new Date(raw).getTime() : Number.NaN;
  return Number.isNaN(value) ? -Infinity : value;
}

/**
 * Najnowsza notatka z grupy „Rozmowy” — po dacie, nie po kolejności listy
 * (przypięte stoją na liście pierwsze, a „ostatnia rozmowa” ma być ostatnia).
 */
export function latestTalkNote<T extends OverviewNote>(notes: readonly T[] | null | undefined): T | null {
  let best: T | null = null;
  for (const note of notes ?? []) {
    if (note.parent_note_id != null) continue;
    if (noteGroup(note) !== "talks") continue;
    if (best == null || noteTime(note) > noteTime(best)) best = note;
  }
  return best;
}

/**
 * Przegląd od 13.10.2026 (decyzja E2): „Do zrobienia” pokazuje tylko procesy,
 * w których ruch jest po naszej stronie — rekruter, przegląd albo Delivery.
 * Pełna lista procesów żyje w zakładce „Rekrutacje”.
 */
export const OUR_SIDE_OWNERS: ReadonlySet<string> = new Set(["recruiter", "review", "delivery"]);

export interface OverviewRecruitment {
  job_id?: number | null;
  next_action_owner?: string | null;
  last_seen?: string | null;
}

/** Procesy w toku z ruchem po naszej stronie, najdłużej czekające pierwsze. */
export function recruitmentsAwaitingUs<T extends OverviewRecruitment>(
  active: readonly T[],
  now: Date = new Date(),
): T[] {
  return active
    .filter((job) => job.next_action_owner != null && OUR_SIDE_OWNERS.has(job.next_action_owner))
    .map((job) => ({ job, days: daysSince(job.last_seen, now) ?? -1 }))
    .sort((a, b) => b.days - a.days)
    .map(({ job }) => job);
}

export interface RecentRole {
  role: string;
  company: string;
  period: string;
}

/**
 * Ostatnie stanowiska do Przeglądu — w kolejności z CV (odczyt zapisuje
 * najnowsze pierwsze). Pomija pusty placeholder z backfillu Traffita.
 */
export function recentRoles(
  experience: unknown,
  formatDate: (value: unknown) => string,
  limit = 3,
): RecentRole[] {
  const rows = Array.isArray(experience) ? experience : [];
  const out: RecentRole[] = [];
  for (const entry of rows) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Record<string, unknown>;
    const role = String(e.role ?? e.title ?? "").trim();
    const company = String(e.company ?? "").trim();
    if (!role && !company) continue;
    const start = formatDate(e.start ?? e.start_date ?? null);
    const end = formatDate(e.end ?? e.end_date ?? null);
    const period = start || end ? `${start || "?"} – ${end || "obecnie"}` : "";
    out.push({ role, company, period });
    if (out.length >= limit) break;
  }
  return out;
}
