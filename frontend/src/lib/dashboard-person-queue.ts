/**
 * „Pracuj po kolei” na pulpicie (23.11.2026, decyzja Artura — rekomendacja 3
 * z analizy dnia rekrutera). Jedna kolejka osób z trzech list „Czeka na
 * Ciebie”: Screening bez arkusza → Zweryfikowani czekają na CV → od systemu
 * czeka na decyzję, w każdej najdłużej czekający pierwsi. Panel osoby
 * otwiera się na pulpicie, a „‹ ›” i „Dalej” chodzą przez wszystkie
 * rekrutacje. Zasady: `docs/claude/ui/pracuj-po-kolei-na-pulpicie.md`.
 *
 * Tu tylko czysta logika (kolejność, kto dalej) — bez Reacta, żeby dało się
 * ją sprawdzić testami bez renderu.
 */

import type { MouseEvent } from "react";

import type { FlowBlock } from "@/lib/api/boardTasks";
import { waitingFor } from "@/lib/api/boardTasks";
import { workdaysText } from "@/lib/board-card-badges";

export type PersonQueueList = "screening" | "verified" | "autofill";

export const PERSON_QUEUE_LIST_LABEL: Record<PersonQueueList, string> = {
  screening: "Screening bez arkusza",
  verified: "Przygotowanie CV — czekają na CV",
  autofill: "Od systemu czeka na decyzję",
};

/** Nazwa kolejki obok „N z M” w panelu osoby. */
export const PERSON_QUEUE_LABEL = "Czeka na Ciebie";

export interface PersonQueueEntry {
  /** `job:candidate` — para jest w kolejce raz, nawet gdy przeszła do innej listy. */
  key: string;
  list: PersonQueueList;
  jobId: number;
  candidateId: number;
  candidateName: string;
  jobLabel: string;
  clientName: string | null;
  /** „czeka 3 dni” (Screening, Zweryfikowani) albo „2 dni robocze” (od systemu). */
  waiting: string;
}

export interface PersonPair {
  jobId: number;
  candidateId: number;
}

export function pairKey(pair: PersonPair): string {
  return `${pair.jobId}:${pair.candidateId}`;
}

function label(row: { job_title: string; job_working_title?: string | null }): string {
  return row.job_working_title?.trim() || row.job_title;
}

function bySince<T extends { since: string }>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => a.since.localeCompare(b.since));
}

/** Kolejka w kolejności list pulpitu; para z dwóch list liczy się raz (pierwsza wygrywa). */
export function buildPersonQueue(
  flow: FlowBlock | null | undefined,
  now: Date = new Date(),
): PersonQueueEntry[] {
  if (!flow) return [];
  const out: PersonQueueEntry[] = [];
  const seen = new Set<string>();
  const push = (entry: PersonQueueEntry) => {
    if (seen.has(entry.key)) return;
    seen.add(entry.key);
    out.push(entry);
  };
  for (const list of ["screening", "verified"] as const) {
    for (const row of bySince(flow[list] ?? [])) {
      push({
        key: pairKey({ jobId: row.job_id, candidateId: row.candidate_id }),
        list,
        jobId: row.job_id,
        candidateId: row.candidate_id,
        candidateName: row.candidate_name,
        jobLabel: label(row),
        clientName: row.client_name ?? null,
        waiting: waitingFor(row.since, now),
      });
    }
  }
  const autofill = [...(flow.autofill_decisions ?? [])].sort((a, b) => b.waiting_days - a.waiting_days);
  for (const row of autofill) {
    push({
      key: pairKey({ jobId: row.job_id, candidateId: row.candidate_id }),
      list: "autofill",
      jobId: row.job_id,
      candidateId: row.candidate_id,
      candidateName: row.candidate_name,
      jobLabel: label(row),
      clientName: row.client_name ?? null,
      waiting: workdaysText(row.waiting_days),
    });
  }
  return out;
}

/**
 * Kolejność kolejki trwa przez odświeżenia listy: znane klucze zostają na
 * swoich miejscach (także te, które z listy już wyszły — po nich liczymy, kto
 * stał dalej), nowe dochodzą na koniec. Bez tego odświeżenie po ruchu karty
 * przestawiałoby osoby pod ręką rekrutera.
 */
export function mergeQueueOrder(order: readonly string[], entries: readonly PersonQueueEntry[]): string[] {
  const known = new Set(order);
  const added = entries.map((e) => e.key).filter((k) => !known.has(k));
  return added.length === 0 ? [...order] : [...order, ...added];
}

export interface PersonQueueView {
  /** Osoby, które nadal czekają, w kolejności kolejki. */
  live: PersonQueueEntry[];
  /** Pozycja osoby z panelu (1-based); `null` — osoba poza kolejką. */
  position: number | null;
  current: PersonQueueEntry | null;
  previous: PersonQueueEntry | null;
  /** Kto dalej: następna czekająca za osobą z panelu (albo za kotwicą, gdy osoba wyszła z kolejki). */
  next: PersonQueueEntry | null;
}

/**
 * @param anchorKey ostatnia osoba z kolejki, którą panel pokazywał — gdy
 *   w panelu jest ktoś spoza kolejki (zamknięty, otwarty z wnętrza panelu),
 *   „Dalej” liczymy od niej.
 * @param done klucze zamknięte z panelu w tej sesji — znikają od razu, zanim
 *   lista z serwera się odświeży.
 */
export function personQueueView(
  order: readonly string[],
  entries: readonly PersonQueueEntry[],
  currentKey: string | null,
  anchorKey: string | null,
  done: ReadonlySet<string> = new Set(),
): PersonQueueView {
  const byKey = new Map(entries.map((e) => [e.key, e]));
  const live = order.map((k) => byKey.get(k)).filter((e): e is PersonQueueEntry => !!e && !done.has(e.key));
  const at = currentKey ? live.findIndex((e) => e.key === currentKey) : -1;
  if (at >= 0) {
    return {
      live,
      position: at + 1,
      current: live[at],
      previous: at > 0 ? live[at - 1] : null,
      next: at + 1 < live.length ? live[at + 1] : null,
    };
  }
  const from = anchorKey ?? currentKey;
  const anchorAt = from ? order.indexOf(from) : -1;
  const liveKeys = new Set(live.map((e) => e.key));
  const nextKey = anchorAt >= 0 ? order.slice(anchorAt + 1).find((k) => liveKeys.has(k)) : live[0]?.key;
  return {
    live,
    position: null,
    current: null,
    previous: null,
    next: nextKey ? (byKey.get(nextKey) ?? null) : null,
  };
}

/**
 * Zwykły klik w osobę z listy kolejki otwiera panel na pulpicie (23.11.2026);
 * klik z ⌘/Ctrl/Shift albo środkowym przyciskiem dalej otwiera Tablicę
 * w nowej karcie — link zostaje linkiem.
 */
export function openOnDashboard(e: Pick<MouseEvent, "defaultPrevented" | "button" | "metaKey" | "ctrlKey" | "shiftKey" | "altKey" | "preventDefault">, open: () => void): void {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  open();
}
