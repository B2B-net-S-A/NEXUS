/**
 * Długa lista notatek w zakładce „Notatki” profilu (E4, 13.10.2026).
 *
 * Kandydat z kilkoma procesami ma po kilkadziesiąt notatek z kilku lat, a
 * lista szła jednym ciągiem. Tu są czyste reguły podziału: przypięte na
 * górze („Przypięte · N”), reszta od najnowszej w grupach miesięcznych
 * kalendarza firmy (Europe/Warsaw, „Wrzesień 2026 · 9”) i najpierw tylko N
 * najnowszych — „Pokaż starsze (M)” dokłada resztę. `/api/notes` zwraca całą
 * historię, więc dzielimy w przeglądarce, bez nowego zapytania.
 *
 * Link z powiadomienia (`?note=<id>`) do starszej notatki rozwija listę aż do
 * niej — inaczej przewinięcie do notatki nie miałoby celu.
 */

import { threadContainsNote, type CandidateNoteLike } from "@/lib/candidate-notes-view";
import { warsawDateOf } from "@/lib/warsaw-date";

export interface PageableNote extends CandidateNoteLike {
  created_at?: string | null;
  timestamp?: string | null;
}

const MONTH_NAMES = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
] as const;

const NO_DATE_KEY = "no-date";

export interface NoteMonthSection<T> {
  /** „2026-09”, „no-date” albo „all” (lista bez grup). */
  key: string;
  /** „Wrzesień 2026”, „Bez daty”; `null` = lista bez nagłówków. */
  label: string | null;
  /** Ile notatek ma cały miesiąc (także schowanych za „Pokaż starsze”). */
  total: number;
  /** Notatki pokazane teraz. */
  notes: T[];
}

export interface NotesPage<T> {
  pinned: T[];
  sections: NoteMonthSection<T>[];
  /** Ile notatek czeka za „Pokaż starsze”. */
  hidden: number;
}

function noteTime<T extends PageableNote>(note: T): number {
  const raw = note.created_at ?? note.timestamp;
  if (!raw) return Number.NaN;
  return new Date(raw).getTime();
}

/** Miesiąc notatki w kalendarzu firmy: „2026-09” albo `no-date`. */
export function noteMonthKey(note: PageableNote): string {
  const day = warsawDateOf(note.created_at ?? note.timestamp ?? null);
  return day ? day.slice(0, 7) : NO_DATE_KEY;
}

/** „2026-09” → „Wrzesień 2026”. */
export function noteMonthLabel(key: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(key);
  if (!match) return "Bez daty";
  const month = MONTH_NAMES[Number(match[2]) - 1];
  return month ? `${month} ${match[1]}` : "Bez daty";
}

/** Od najnowszej; notatki bez daty na końcu, remis zostaje w kolejności z API. */
function newestFirst<T extends PageableNote>(notes: readonly T[]): T[] {
  return [...notes].sort((a, b) => {
    const ta = noteTime(a);
    const tb = noteTime(b);
    const aMissing = Number.isNaN(ta);
    const bMissing = Number.isNaN(tb);
    if (aMissing || bMissing) return aMissing === bMissing ? 0 : aMissing ? 1 : -1;
    return tb - ta;
  });
}

/**
 * Podział listy notatek (już po filtrach) na przypięte, grupy miesięczne
 * i część schowaną. `limit = null` pokazuje wszystko; notatka wskazana
 * w adresie (także odpowiedź w jej wątku) zawsze jest wśród pokazanych.
 */
export function pageNotes<T extends PageableNote>(
  notes: readonly T[],
  {
    groupByMonth,
    limit,
    focusedNoteId,
  }: { groupByMonth: boolean; limit: number | null; focusedNoteId: number | null },
): NotesPage<T> {
  const pinned = notes.filter((n) => n.pinned_at != null);
  const rest = newestFirst(notes.filter((n) => n.pinned_at == null));

  let visibleCount = limit == null ? rest.length : Math.max(0, limit);
  if (focusedNoteId != null) {
    const focusedIndex = rest.findIndex((n) => threadContainsNote(n, focusedNoteId));
    if (focusedIndex >= visibleCount) visibleCount = focusedIndex + 1;
  }
  const shown = rest.slice(0, visibleCount);
  const hidden = rest.length - shown.length;

  if (!groupByMonth) {
    return {
      pinned,
      sections: shown.length > 0 ? [{ key: "all", label: null, total: rest.length, notes: shown }] : [],
      hidden,
    };
  }

  const totals = new Map<string, number>();
  for (const note of rest) {
    const key = noteMonthKey(note);
    totals.set(key, (totals.get(key) ?? 0) + 1);
  }
  const sections: NoteMonthSection<T>[] = [];
  for (const note of shown) {
    const key = noteMonthKey(note);
    const last = sections[sections.length - 1];
    if (last && last.key === key) {
      last.notes.push(note);
    } else {
      sections.push({ key, label: noteMonthLabel(key), total: totals.get(key) ?? 0, notes: [note] });
    }
  }
  return { pinned, sections, hidden };
}
