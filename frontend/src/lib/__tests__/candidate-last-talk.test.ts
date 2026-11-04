import { describe, expect, it } from "vitest";

import { lastTalkCell, lastTalkDate } from "@/lib/candidate-last-talk";

describe("„Ostatnia rozmowa” na liście kandydatów", () => {
  it("pokazuje datę i autora najnowszej rozmowy, a w dymku początek notatki", () => {
    expect(
      lastTalkCell({
        last_talk_at: "2026-09-30T10:00:00Z",
        last_talk_by: "Marta Testowa",
        last_talk_preview: "Szuka projektu z Javą 21.",
        contact_attempts: 3,
      }),
    ).toEqual({
      primary: "30.09.2026",
      secondary: "Marta Testowa",
      muted: false,
      title: "Szuka projektu z Javą 21.",
    });
  });

  it("notatka z importu bez autora mówi, skąd jest", () => {
    expect(lastTalkCell({ last_talk_at: "2025-02-03T10:00:00Z", last_talk_by: null }).secondary).toBe(
      "import z Traffita",
    );
  });

  it("bez rozmowy liczą się próby kontaktu — „nie odebrał” rozmową nie jest", () => {
    expect(lastTalkCell({ last_talk_at: null, contact_attempts: 3 })).toMatchObject({
      primary: "bez rozmowy",
      secondary: "3 próby kontaktu",
      muted: true,
    });
    expect(lastTalkCell({})).toEqual({
      primary: "bez rozmowy",
      secondary: null,
      muted: true,
      title: null,
    });
  });

  it("dzień liczy w czasie warszawskim; nieczytelna data to brak rozmowy", () => {
    // 22:30 UTC = 00:30 następnego dnia w Warszawie.
    expect(lastTalkDate("2026-09-30T22:30:00Z")).toBe("01.10.2026");
    expect(lastTalkDate("nie-data")).toBeNull();
    expect(lastTalkCell({ last_talk_at: "nie-data" }).primary).toBe("bez rozmowy");
  });
});
