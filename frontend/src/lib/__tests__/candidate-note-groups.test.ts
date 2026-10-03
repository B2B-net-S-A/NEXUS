import { describe, expect, it } from "vitest";

import {
  NOTE_GROUP_BY_VIEW,
  NOTE_GROUPS,
  VIEW_BY_NOTE_GROUP,
  noteGroup,
  noteGroupCounts,
  notesOfGroup,
} from "@/lib/candidate-note-groups";

describe("zakładki notatek w Historii profilu", () => {
  it("każda grupa ma swój widok i odwrotnie", () => {
    for (const group of NOTE_GROUPS) {
      expect(NOTE_GROUP_BY_VIEW[VIEW_BY_NOTE_GROUP[group]]).toBe(group);
    }
    // Klucz `notes` niosą linki z powiadomień — otwiera „Rozmowy”.
    expect(NOTE_GROUP_BY_VIEW.notes).toBe("talks");
    expect(NOTE_GROUP_BY_VIEW.timeline).toBeUndefined();
  });

  it("grupę nadaje serwer; odpowiedź bez pola `group` liczy wpis automatu po `is_system`", () => {
    expect(noteGroup({ group: "contact" })).toBe("contact");
    expect(noteGroup({ group: "cos-nowego", is_system: false })).toBe("talks");
    expect(noteGroup({ is_system: true })).toBe("automat");
    expect(noteGroup({})).toBe("talks");
  });

  it("nic nie znika: każda notatka trafia do dokładnie jednej zakładki", () => {
    const notes = [
      { id: 1, group: "talks" },
      { id: 2, group: "contact" },
      { id: 3, group: "delivery" },
      { id: 4, group: "email" },
      { id: 5, group: "automat" },
      { id: 6 },
    ];
    const total = NOTE_GROUPS.reduce((sum, group) => sum + notesOfGroup(notes, group).length, 0);
    expect(total).toBe(notes.length);
    expect(notesOfGroup(notes, "talks").map((n) => n.id)).toEqual([1, 6]);
  });

  it("liczniki bierze z serwera, a bez nich liczy pobraną listę", () => {
    const notes = [{ group: "talks" }, { group: "contact" }];
    expect(noteGroupCounts({ talks: 40, contact: 3, delivery: 0, email: 4, automat: 9 }, notes)).toEqual({
      talks: 40,
      contact: 3,
      delivery: 0,
      email: 4,
      automat: 9,
    });
    expect(noteGroupCounts(undefined, notes)).toEqual({
      talks: 1,
      contact: 1,
      delivery: 0,
      email: 0,
      automat: 0,
    });
    expect(noteGroupCounts({}, notes).talks).toBe(1);
  });
});
