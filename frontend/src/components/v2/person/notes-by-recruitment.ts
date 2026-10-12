/**
 * Notatki osoby w panelu rekrutacji (12.10.2026): co jest z TEJ rekrutacji,
 * a co „wcześniej u nas” — z innych rekrutacji i bez rekrutacji.
 *
 * Do tej daty panel pytał wyłącznie o notatki z `job_id` bieżącej rekrutacji.
 * Pomiar na produkcji: 1 417 z 3 433 otwartych kart pokazywało „Brak notatek”,
 * choć osoba miała notatki gdzie indziej (mediana 7). Tu mieszkają czyste
 * reguły podziału i grupowania; komponent tylko je rysuje.
 */

import { isRecruitmentEnded } from "@/components/v2/candidate-profile/profile-helpers";
import type { RecruitmentOutcomeRow } from "@/components/v2/pages/candidate-outcomes-query";
import { candidateStageLabel } from "@/components/v2/pages/candidate-timeline-labels";
import { noteGroup, type NoteGroup } from "@/lib/candidate-note-groups";
import { humanNoteCount } from "@/lib/candidate-notes-view";
import { countPl } from "@/lib/plural-pl";
import {
  furthestBoardColumnLabel,
  recruitmentOutcome,
  recruitmentStageLabel,
  type RecruitmentOutcomeTone,
} from "@/lib/recruitment-stage-label";

export interface PersonNoteLike {
  id: number;
  job_id?: number | null;
  job_title?: string | null;
  created_at?: string | null;
  is_system?: boolean | null;
  group?: string | null;
}

/** Filtr „Wcześniej u nas”: jeden rodzaj notatek albo wszystko (z wpisami automatów). */
export type EarlierNotesFilter = NoteGroup | "all";

export const NO_RECRUITMENT_KEY = "none";

export interface EarlierNotesGroup<T> {
  key: string;
  /** `null` = notatki bez rekrutacji (głównie import z Traffita). */
  jobId: number | null;
  title: string;
  clientName: string | null;
  /** Kolejność z API: przypięte pierwsze, potem od najnowszej. */
  notes: T[];
  humanCount: number;
  newestAt: string | null;
  oldestAt: string | null;
  /** „03–04.2025” — okres rekrutacji z historii, a bez niej okres notatek. */
  period: string | null;
  /** Wynik zakończonej rekrutacji — tylko z wiersza historii, nigdy zgadywany. */
  outcome: { label: string; tone: RecruitmentOutcomeTone } | null;
  /** Etap, na którym osoba stoi teraz — tylko dla rekrutacji w toku. */
  currentStage: string | null;
  /** Najdalsza kolumna Tablicy, do której osoba doszła. */
  furthest: string | null;
  rejectionReason: string | null;
}

export interface PersonNotesSplit<T> {
  here: T[];
  earlier: T[];
  /** Grupy „wcześniej”, od tej z najnowszą notatką. */
  groups: EarlierNotesGroup<T>[];
  hereHuman: number;
  earlierHuman: number;
  /** Ile innych rekrutacji ma notatki (grupa „bez rekrutacji” się nie liczy). */
  earlierRecruitments: number;
  /** Rok najstarszej notatki człowieka spoza tej rekrutacji. */
  sinceYear: number | null;
}

const timeOf = (iso: string | null | undefined): number => {
  if (!iso) return Number.NaN;
  return Date.parse(iso);
};

function dateRange<T extends PersonNoteLike>(notes: readonly T[]): {
  newestAt: string | null;
  oldestAt: string | null;
} {
  let newest: string | null = null;
  let oldest: string | null = null;
  for (const note of notes) {
    const at = timeOf(note.created_at);
    if (Number.isNaN(at)) continue;
    if (newest == null || at > timeOf(newest)) newest = note.created_at ?? null;
    if (oldest == null || at < timeOf(oldest)) oldest = note.created_at ?? null;
  }
  return { newestAt: newest, oldestAt: oldest };
}

const pad = (n: number) => String(n).padStart(2, "0");

/** „09.2024”, „03–04.2025” albo „11.2024–02.2025”; `null`, gdy brak dat. */
export function periodLabel(startIso: string | null | undefined, endIso: string | null | undefined): string | null {
  const start = Number.isNaN(timeOf(startIso)) ? null : new Date(startIso as string);
  const end = Number.isNaN(timeOf(endIso)) ? null : new Date(endIso as string);
  const first = start ?? end;
  const last = end ?? start;
  if (!first || !last) return null;
  const lastText = `${pad(last.getMonth() + 1)}.${last.getFullYear()}`;
  if (first.getFullYear() !== last.getFullYear()) {
    return `${pad(first.getMonth() + 1)}.${first.getFullYear()}–${lastText}`;
  }
  if (first.getMonth() !== last.getMonth()) return `${pad(first.getMonth() + 1)}–${lastText}`;
  return lastText;
}

function buildGroup<T extends PersonNoteLike>(
  key: string,
  jobId: number | null,
  notes: T[],
  row: RecruitmentOutcomeRow | undefined,
): EarlierNotesGroup<T> {
  const titled = notes.find((note) => note.job_title?.trim());
  const range = dateRange(notes);
  // Bez wiersza historii nie wiemy, jak rekrutacja się skończyła —
  // `recruitmentOutcome` dla nieznanego etapu zwraca „Rekrutacja zamknięta”.
  const ended =
    row != null && isRecruitmentEnded({ job_status: row.job_status, latest_stage: row.latest_stage }) ? row : null;
  return {
    key,
    jobId,
    title:
      jobId == null
        ? "Bez rekrutacji"
        : (row?.job_title ?? titled?.job_title?.trim() ?? `Rekrutacja #${jobId}`),
    clientName: row?.client_name ?? null,
    notes,
    humanCount: humanNoteCount(notes),
    ...range,
    period: periodLabel(row?.first_seen ?? range.oldestAt, row?.last_seen ?? range.newestAt),
    outcome: ended ? recruitmentOutcome(ended) : null,
    currentStage:
      row != null && !ended && row.latest_stage
        ? recruitmentStageLabel(row.latest_stage, row.latest_stage_name, candidateStageLabel)
        : null,
    furthest: row ? furthestBoardColumnLabel(row.stages) : null,
    rejectionReason: ended?.rejection_reason ?? null,
  };
}

/**
 * Podział notatek osoby względem bieżącej rekrutacji. `outcomes` to dodatek:
 * bez nich (ładowanie, awaria, rekrutacja spoza historii) grupy powstają
 * z samych notatek, tylko bez wyniku.
 */
export function splitPersonNotes<T extends PersonNoteLike>(
  notes: readonly T[],
  jobId: number,
  outcomes?: readonly RecruitmentOutcomeRow[] | null,
): PersonNotesSplit<T> {
  const here: T[] = [];
  const earlier: T[] = [];
  for (const note of notes) {
    (note.job_id != null && Number(note.job_id) === jobId ? here : earlier).push(note);
  }

  const rowByJob = new Map<number, RecruitmentOutcomeRow>();
  for (const row of outcomes ?? []) rowByJob.set(row.job_id, row);

  const buckets = new Map<string, { jobId: number | null; notes: T[] }>();
  for (const note of earlier) {
    const noteJobId = note.job_id == null ? null : Number(note.job_id);
    const key = noteJobId == null ? NO_RECRUITMENT_KEY : `job:${noteJobId}`;
    const bucket = buckets.get(key);
    if (bucket) bucket.notes.push(note);
    else buckets.set(key, { jobId: noteJobId, notes: [note] });
  }
  const groups = [...buckets.entries()]
    .map(([key, bucket]) =>
      buildGroup(key, bucket.jobId, bucket.notes, bucket.jobId == null ? undefined : rowByJob.get(bucket.jobId)),
    )
    // Najświeższa rozmowa na górze — także „Bez rekrutacji”, bo notatki
    // z Traffita bez powiązania bywają z ostatnich tygodni.
    .sort((a, b) => (timeOf(b.newestAt) || 0) - (timeOf(a.newestAt) || 0));

  const earlierHumanNotes = earlier.filter((note) => !note.is_system);
  const oldest = dateRange(earlierHumanNotes).oldestAt;
  return {
    here,
    earlier,
    groups,
    hereHuman: humanNoteCount(here),
    earlierHuman: earlierHumanNotes.length,
    earlierRecruitments: groups.filter((group) => group.jobId != null).length,
    sinceYear: oldest ? new Date(oldest).getFullYear() : null,
  };
}

/** Notatki grupy po filtrze. „Wszystko” niesie też wpisy automatów. */
export function notesForFilter<T extends PersonNoteLike>(
  notes: readonly T[],
  filter: EarlierNotesFilter,
): T[] {
  if (filter === "all") return [...notes];
  return notes.filter((note) => noteGroup(note) === filter);
}

export const notesCountLabel = (count: number): string => countPl(count, "notatka", "notatki", "notatek");

/** „14 notatek · 2 rekrutacje · od 2023” — nagłówek sekcji „Wcześniej u nas”. */
export function earlierSummaryLabel(split: PersonNotesSplit<unknown>): string {
  const parts = [notesCountLabel(split.earlierHuman)];
  if (split.earlierRecruitments > 0) {
    parts.push(countPl(split.earlierRecruitments, "rekrutacja", "rekrutacje", "rekrutacji"));
  }
  if (split.sinceYear != null) parts.push(`od ${split.sinceYear}`);
  return parts.join(" · ");
}

/** „N tu · M wcześniej” w wąskim doku; bez historii zostaje dotychczasowy napis. */
export function dockNotesSummary(split: Pick<PersonNotesSplit<unknown>, "hereHuman" | "earlierHuman">): string {
  if (split.earlierHuman === 0) return `${split.hereHuman} w tej rekrutacji`;
  return `${split.hereHuman} tu · ${split.earlierHuman} wcześniej`;
}

/**
 * Podpis grupy: najdalszy etap, powód zakończenia i liczba notatek.
 * Wyświetla tylko to, co wiemy z historii — brak wiersza = sama liczba notatek.
 */
export function groupFactsLine(group: EarlierNotesGroup<unknown>): string {
  const parts: string[] = [];
  if (group.currentStage) parts.push(`w toku: ${group.currentStage}`);
  else if (group.furthest) parts.push(`najdalej: ${group.furthest}`);
  if (group.rejectionReason) parts.push(`powód: ${group.rejectionReason}`);
  parts.push(notesCountLabel(group.humanCount));
  const line = parts.join(" · ");
  return line.charAt(0).toUpperCase() + line.slice(1);
}
