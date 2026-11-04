import { describe, expect, it } from "vitest";

import { noteMonthKey, noteMonthLabel, pageNotes } from "@/lib/candidate-notes-paging";

const note = (id: number, created_at: string | null, extra: object = {}) => ({
  id,
  created_at,
  ...extra,
});

describe("pageNotes", () => {
  it("miesiąc liczy w kalendarzu firmy: 30.09 23:30 UTC to już październik w Warszawie", () => {
    expect(noteMonthKey(note(1, "2026-09-30T23:30:00Z"))).toBe("2026-10");
    expect(noteMonthKey(note(2, "2026-09-30T21:30:00Z"))).toBe("2026-09");
    expect(noteMonthKey(note(3, null))).toBe("no-date");
    expect(noteMonthLabel("2026-10")).toBe("Październik 2026");
    expect(noteMonthLabel("no-date")).toBe("Bez daty");
  });

  it("sortuje od najnowszej, notatki bez daty na końcu, przypięte osobno", () => {
    const page = pageNotes(
      [
        note(1, "2026-08-01T10:00:00Z"),
        note(2, null),
        note(3, "2026-09-02T10:00:00Z", { pinned_at: "2026-09-03T10:00:00Z" }),
        note(4, "2026-09-05T10:00:00Z"),
      ],
      { groupByMonth: true, limit: null, focusedNoteId: null },
    );
    expect(page.pinned.map((n) => n.id)).toEqual([3]);
    expect(page.sections.map((s) => [s.label, s.total, s.notes.map((n) => n.id)])).toEqual([
      ["Wrzesień 2026", 1, [4]],
      ["Sierpień 2026", 1, [1]],
      ["Bez daty", 1, [2]],
    ]);
    expect(page.hidden).toBe(0);
  });

  it("limit tnie najnowsze, a wskazana notatka (albo odpowiedź w jej wątku) rozszerza go", () => {
    const notes = [1, 2, 3, 4, 5].map((id) =>
      note(id, `2026-09-${String(30 - id).padStart(2, "0")}T10:00:00Z`, {
        replies: id === 5 ? [{ id: 50 }] : [],
      }),
    );
    expect(pageNotes(notes, { groupByMonth: false, limit: 2, focusedNoteId: null }).hidden).toBe(3);
    const focused = pageNotes(notes, { groupByMonth: false, limit: 2, focusedNoteId: 4 });
    expect(focused.sections[0].notes.map((n) => n.id)).toEqual([1, 2, 3, 4]);
    expect(focused.hidden).toBe(1);
    expect(pageNotes(notes, { groupByMonth: false, limit: 2, focusedNoteId: 50 }).hidden).toBe(0);
    // Notatka spoza listy (np. innego kandydata) niczego nie rozwija.
    expect(pageNotes(notes, { groupByMonth: false, limit: 2, focusedNoteId: 999 }).hidden).toBe(3);
  });

  it("pusta lista nie ma sekcji", () => {
    expect(pageNotes([], { groupByMonth: true, limit: 10, focusedNoteId: null })).toEqual({
      pinned: [],
      sections: [],
      hidden: 0,
    });
  });
});
