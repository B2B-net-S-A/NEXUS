import { describe, expect, it } from "vitest";

import {
  availabilitySuggestionText,
  notedAtLabel,
  notesWithAvailability,
  rateSuggestionFill,
  rateSuggestionLabel,
} from "@/lib/screening-suggestions";

const rate = (extra = {}) => ({
  value: 175,
  unit: "hour" as const,
  currency: "PLN",
  raw: null,
  source_note_id: 1,
  noted_at: "2026-09-12",
  ...extra,
});

describe("screening-suggestions", () => {
  it("etykieta stawki: kwota, jednostka, dzień notatki", () => {
    expect(rateSuggestionLabel(rate())).toBe("175 zł/h · 12.09");
    expect(rateSuggestionLabel(rate({ unit: "day", value: 1400.5, noted_at: null }))).toBe("1400,50 zł/dzień");
    expect(rateSuggestionLabel(rate({ unit: null, currency: null, noted_at: "wrzesień" }))).toBe("175 zł");
  });

  it("wypełnienie tylko dla PLN i znanej jednostki — bez zgadywania", () => {
    expect(rateSuggestionFill(rate())).toEqual({ rate: "175", unit: "hourly" });
    expect(rateSuggestionFill(rate({ unit: "month", currency: null }))).toEqual({ rate: "175", unit: "monthly" });
    expect(rateSuggestionFill(rate({ currency: "EUR" }))).toBeNull();
    expect(rateSuggestionFill(rate({ unit: null }))).toBeNull();
  });

  it("dostępność: surowy tekst wygrywa, inaczej data i okres wypowiedzenia", () => {
    const base = { raw: null, notice_period: null, available_from: null, source_note_id: null, noted_at: null };
    expect(availabilitySuggestionText({ ...base, raw: " dostępny od razu " })).toBe("dostępny od razu");
    expect(
      availabilitySuggestionText({ ...base, available_from: "2026-10-01", notice_period: "1 miesiąc" }),
    ).toBe("od 01.10.2026 · wypowiedzenie: 1 miesiąc");
    expect(availabilitySuggestionText(base)).toBeNull();
  });

  it("dopisuje linię do notatek, nie nadpisuje i nie dubluje", () => {
    const once = notesWithAvailability("Rozmowa po angielsku.\n", "od razu");
    expect(once).toBe("Rozmowa po angielsku.\nDostępność (z notatek): od razu");
    expect(notesWithAvailability(once, "od razu")).toBe(once);
    expect(notesWithAvailability("", "od razu")).toBe("Dostępność (z notatek): od razu");
  });

  it("data notatki tylko z ISO", () => {
    expect(notedAtLabel("2026-09-12T08:00:00Z")).toBe("12.09");
    expect(notedAtLabel("wczoraj")).toBeNull();
    expect(notedAtLabel(null)).toBeNull();
  });
});
