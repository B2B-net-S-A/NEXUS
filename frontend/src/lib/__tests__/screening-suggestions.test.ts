import { describe, expect, it } from "vitest";

import {
  availabilityProfilePatch,
  availabilitySuggestionText,
  notedAtLabel,
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

  it("zapis w profilu tylko przy PEWNYM mapowaniu: data ISO albo jednoznaczne „od razu”", () => {
    const base = { raw: null, notice_period: null, available_from: null, source_note_id: null, noted_at: null };
    const today = new Date(2026, 8, 21, 15, 0);
    expect(availabilityProfilePatch({ ...base, available_from: "2026-10-01" }, today)).toEqual({ availability_date: "2026-10-01" });
    expect(availabilityProfilePatch({ ...base, raw: "Dostępny od razu" }, today)).toEqual({ availability_date: "2026-09-21" });
    expect(availabilityProfilePatch({ ...base, raw: "ASAP" }, today)).toEqual({ availability_date: "2026-09-21" });
    // Niepewne → człowiek uzupełnia w profilu.
    expect(availabilityProfilePatch({ ...base, raw: "za 2 tygodnie" }, today)).toBeNull();
    expect(availabilityProfilePatch({ ...base, raw: "od razu", notice_period: "1 miesiąc" }, today)).toBeNull();
    expect(availabilityProfilePatch({ ...base, available_from: "październik" }, today)).toBeNull();
    expect(availabilityProfilePatch({ ...base, available_from: "2026-02-31" }, today)).toBeNull();
    expect(availabilityProfilePatch(base, today)).toBeNull();
  });

  it("data notatki tylko z ISO", () => {
    expect(notedAtLabel("2026-09-12T08:00:00Z")).toBe("12.09");
    expect(notedAtLabel("wczoraj")).toBeNull();
    expect(notedAtLabel(null)).toBeNull();
  });
});
