import { describe, expect, it } from "vitest";

import { daysSince, latestTalkNote, nextActionOwnerLabel } from "@/lib/candidate-overview";

describe("nextActionOwnerLabel", () => {
  it("nazywa właściciela ruchu bez „Twój ruch” — profil ogląda każda rola", () => {
    expect(nextActionOwnerLabel("recruiter")).toBe("rekruter");
    expect(nextActionOwnerLabel("client")).toBe("klient");
    expect(nextActionOwnerLabel("candidate")).toBe("kandydat");
    expect(nextActionOwnerLabel("delivery")).toBe("Delivery");
    expect(nextActionOwnerLabel("review")).toBe("do przejrzenia");
    expect(nextActionOwnerLabel(null)).toBeNull();
    expect(nextActionOwnerLabel("none")).toBeNull();
  });
});

describe("daysSince", () => {
  const now = new Date("2026-10-04T12:00:00Z");
  it("liczy pełne dni i nie schodzi poniżej zera", () => {
    expect(daysSince("2026-10-01T12:00:00Z", now)).toBe(3);
    expect(daysSince("2026-10-05T12:00:00Z", now)).toBe(0);
    expect(daysSince("nie-data", now)).toBeNull();
    expect(daysSince(null, now)).toBeNull();
  });
});

describe("latestTalkNote", () => {
  it("bierze najnowszą rozmowę po dacie, nie pierwszą (przypiętą) z listy", () => {
    const notes = [
      { id: 1, group: "talks", created_at: "2026-09-01T10:00:00Z", pinned_at: "2026-09-02" },
      { id: 2, group: "contact", created_at: "2026-10-03T10:00:00Z" },
      { id: 3, group: "talks", created_at: "2026-09-20T10:00:00Z" },
      { id: 4, group: "automat", is_system: true, created_at: "2026-10-04T10:00:00Z" },
    ];
    expect(latestTalkNote(notes)?.id).toBe(3);
  });

  it("pomija odpowiedzi i działa bez notatek", () => {
    expect(
      latestTalkNote([
        { id: 5, group: "talks", parent_note_id: 1, created_at: "2026-10-04T10:00:00Z" },
      ]),
    ).toBeNull();
    expect(latestTalkNote([])).toBeNull();
    expect(latestTalkNote(undefined)).toBeNull();
  });

  it("notatka bez pola `group` (starszy serwer) liczy się jako rozmowa, systemowa — nie", () => {
    expect(latestTalkNote([{ id: 6, created_at: "2026-10-01T10:00:00Z" }])?.id).toBe(6);
    expect(
      latestTalkNote([{ id: 7, is_system: true, created_at: "2026-10-01T10:00:00Z" }]),
    ).toBeNull();
  });
});
