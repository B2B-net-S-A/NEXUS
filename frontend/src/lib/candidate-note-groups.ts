// Zakładki notatek w Historii profilu — jedna na każdą grupę rodzajów.
// Grupę każdej notatki i liczniki nadaje serwer (`services/note_kinds.py`,
// `NOTE_GROUPS`); tu jest tylko mapowanie na widok i zapas dla odpowiedzi
// sprzed tej zmiany (notatka bez pola `group`).

import type { CandidateActivityView } from "@/components/v2/pages/candidate-profile-navigation";

export const NOTE_GROUPS = ["talks", "contact", "delivery", "email", "automat"] as const;
export type NoteGroup = (typeof NOTE_GROUPS)[number];

/** Widok Historii → grupa notatek, którą pokazuje. */
export const NOTE_GROUP_BY_VIEW: Partial<Record<CandidateActivityView, NoteGroup>> = {
  notes: "talks",
  contact: "contact",
  delivery: "delivery",
  emails: "email",
  automat: "automat",
};

export const VIEW_BY_NOTE_GROUP: Record<NoteGroup, CandidateActivityView> = {
  talks: "notes",
  contact: "contact",
  delivery: "delivery",
  email: "emails",
  automat: "automat",
};

interface GroupedNote {
  group?: string | null;
  is_system?: boolean | null;
}

function isGroup(value: unknown): value is NoteGroup {
  return typeof value === "string" && (NOTE_GROUPS as readonly string[]).includes(value);
}

export function noteGroup(note: GroupedNote): NoteGroup {
  if (isGroup(note.group)) return note.group;
  return note.is_system ? "automat" : "talks";
}

export function notesOfGroup<T extends GroupedNote>(notes: readonly T[], group: NoteGroup): T[] {
  return notes.filter((note) => noteGroup(note) === group);
}

/** Liczniki zakładek: z serwera (cały zakres), a bez nich — z pobranej listy. */
export function noteGroupCounts(
  serverCounts: Record<string, number> | null | undefined,
  notes: readonly GroupedNote[],
): Record<NoteGroup, number> {
  const counts = { talks: 0, contact: 0, delivery: 0, email: 0, automat: 0 };
  if (serverCounts && NOTE_GROUPS.some((group) => typeof serverCounts[group] === "number")) {
    for (const group of NOTE_GROUPS) counts[group] = Number(serverCounts[group] ?? 0);
    return counts;
  }
  for (const note of notes) counts[noteGroup(note)] += 1;
  return counts;
}

export const NOTE_GROUP_EMPTY_TEXT: Record<NoteGroup, string> = {
  talks: "Brak notatek z rozmów.",
  contact: "Brak zapisanych prób kontaktu.",
  delivery: "Brak wpisów Delivery Leada.",
  email: "Brak maili zapisanych w notatkach.",
  automat: "Brak wpisów automatu.",
};
