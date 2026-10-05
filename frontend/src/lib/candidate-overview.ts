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
