import { describe, expect, it } from "vitest";

import {
  addedToBaseTitle,
  addedToBaseView,
  formatWarsawDay,
  NEW_IN_BASE_DAYS,
  newInBaseDaysText,
} from "@/lib/added-to-base";

// 13.10.2026 12:00 w Warszawie.
const NOW = new Date("2026-10-13T10:00:00Z");

describe("addedToBaseView", () => {
  it("osoba dodana 10 dni temu jest nowa w bazie", () => {
    const view = addedToBaseView({ at: "2026-10-03T07:30:00Z", exact: true }, NOW);
    expect(view).toEqual({
      dateLabel: "03.10.2026",
      ageLabel: "10 dni temu",
      days: 10,
      exact: true,
      isNew: true,
    });
  });

  it("granica 14 dni: dzień 14 to jeszcze nowa osoba, 15 już nie", () => {
    expect(NEW_IN_BASE_DAYS).toBe(14);
    expect(addedToBaseView({ at: "2026-09-29T10:00:00Z", exact: true }, NOW)?.isNew).toBe(true);
    expect(addedToBaseView({ at: "2026-09-28T10:00:00Z", exact: true }, NOW)?.isNew).toBe(false);
  });

  it("liczy dni kalendarza w Warszawie, nie doby od znacznika", () => {
    // 12.10 23:30 w Warszawie (21:30 UTC) to wczoraj, choć minęło niecałe 13 h.
    const view = addedToBaseView({ at: "2026-10-12T21:30:00Z", exact: true }, NOW);
    expect(view?.days).toBe(1);
    expect(view?.ageLabel).toBe("wczoraj");
    // 13.10 00:30 w Warszawie to 12.10 22:30 UTC — już dziś.
    expect(addedToBaseView({ at: "2026-10-12T22:30:00Z", exact: true }, NOW)?.ageLabel).toBe("dziś");
  });

  it("starsze daty w miesiącach i latach", () => {
    expect(addedToBaseView({ at: "2026-08-02T10:00:00Z", exact: true }, NOW)?.ageLabel).toBe("2 mies. temu");
    expect(addedToBaseView({ at: "2019-05-11T22:00:00Z", exact: true }, NOW)?.ageLabel).toBe("7 lat temu");
    expect(addedToBaseView({ at: "2024-10-01T10:00:00Z", exact: true }, NOW)?.ageLabel).toBe("2 lata temu");
    expect(addedToBaseView({ at: "2025-10-01T10:00:00Z", exact: true }, NOW)?.ageLabel).toBe("1 rok temu");
    // 7 tygodni to jeszcze dni („mniej niż 2 miesiące”).
    expect(addedToBaseView({ at: "2026-08-25T10:00:00Z", exact: true }, NOW)?.ageLabel).toBe("49 dni temu");
  });

  it("data niedokładna (import z Traffita bez daty) mówi „przed …” i nigdy nie jest nowa", () => {
    const view = addedToBaseView({ at: "2026-10-10T10:00:00Z", exact: false }, NOW);
    expect(view).toEqual({
      dateLabel: "przed 10.10.2026",
      ageLabel: "dokładnej daty nie znamy",
      days: null,
      exact: false,
      isNew: false,
    });
  });

  it("brak albo nieczytelna data", () => {
    expect(addedToBaseView({ at: null, exact: true }, NOW)).toBeNull();
    expect(addedToBaseView({ at: "nie-data", exact: true }, NOW)).toBeNull();
  });
});

describe("teksty pigułki", () => {
  it("dni w pigułce", () => {
    expect(newInBaseDaysText(0)).toBe("dziś");
    expect(newInBaseDaysText(1)).toBe("1 dzień");
    expect(newInBaseDaysText(10)).toBe("10 dni");
  });

  it("dymek pomija nieznane człony", () => {
    const view = addedToBaseView({ at: "2026-10-03T07:30:00Z", exact: true }, NOW)!;
    expect(addedToBaseTitle(view, "Marta Nowak", "CV upload")).toBe(
      "W bazie od 03.10.2026 · dodał(a) Marta Nowak · CV upload",
    );
    expect(addedToBaseTitle(view, null, " ")).toBe("W bazie od 03.10.2026");
  });

  it("formatWarsawDay", () => {
    expect(formatWarsawDay("2026-10-12T22:30:00Z")).toBe("13.10.2026");
    expect(formatWarsawDay(null)).toBeNull();
  });
});
