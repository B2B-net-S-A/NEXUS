import { describe, expect, it } from "vitest";

import { splitPersonNotes } from "@/components/v2/person/notes-by-recruitment";
import { humanNoteCount, systemNoteCount } from "@/lib/candidate-notes-view";

// Audyt 13.10.2026: wpisy scrapera i auto-matcha sprzed 03.10 nie mają
// `external_source = 'system'` (więc `is_system: false`), ale serwer daje im
// grupę „automat” z rodzaju notatki. Licznik „notatek ludzi” liczył je jak
// rozmowy — osoba z samymi wpisami automatu miała „3 wcześniej”.
const notes = [
  { id: 1, job_id: 10, group: "talks", is_system: false, created_at: "2024-03-01T10:00:00Z" },
  { id: 2, job_id: 20, group: "automat", is_system: false, created_at: "2021-05-01T10:00:00Z" },
  { id: 3, job_id: 20, group: "automat", is_system: true, created_at: "2021-06-01T10:00:00Z" },
  { id: 4, job_id: null, group: "delivery", is_system: false, created_at: "2025-01-01T10:00:00Z" },
  // Odpowiedź sprzed pola `group` — zapas na `is_system`.
  { id: 5, job_id: 10, is_system: false, created_at: "2024-04-01T10:00:00Z" },
];

describe("humanNoteCount", () => {
  it("nie liczy wpisów automatu rozpoznanych po grupie, nie tylko po is_system", () => {
    expect(humanNoteCount(notes)).toBe(3);
  });

  it("„Pokaż systemowe” zostaje przy is_system", () => {
    expect(systemNoteCount(notes)).toBe(1);
  });
});

describe("splitPersonNotes — licznik i rok „Wcześniej u nas”", () => {
  it("wpis automatu nie liczy się do notatek ludzi ani do roku „od …”", () => {
    const split = splitPersonNotes(notes, 10);
    expect(split.hereHuman).toBe(2);
    expect(split.earlierHuman).toBe(1);
    expect(split.sinceYear).toBe(2025);
    const automatOnly = split.groups.find((group) => group.jobId === 20);
    expect(automatOnly?.humanCount).toBe(0);
  });
});
