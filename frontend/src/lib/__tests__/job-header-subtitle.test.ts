/**
 * Podtytuł jobbara (`lib/job-header-subtitle.ts`) — segmenty, nie render.
 */

import { describe, expect, it } from "vitest";

import {
  JOB_HEADER_COLLAPSED_DEFAULT,
  JOB_HEADER_COLLAPSED_STORAGE_KEY,
} from "@/lib/job-header-preferences";
import {
  buildJobHeaderSubtitle,
  formatDeadlineShort,
  shortenPersonName,
} from "@/lib/job-header-subtitle";

describe("shortenPersonName", () => {
  it("skraca nazwisko do inicjału, imię zostaje w całości", () => {
    expect(shortenPersonName("Marta Kowalska")).toBe("Marta K.");
    expect(shortenPersonName("Anna Nowak-Kowalska")).toBe("Anna N.");
    expect(shortenPersonName("  Jan   Maria  Rokita ")).toBe("Jan Maria R.");
  });

  it("jednoczłonowe zostaje bez zmian, puste daje null", () => {
    expect(shortenPersonName("Madonna")).toBe("Madonna");
    expect(shortenPersonName("")).toBeNull();
    expect(shortenPersonName(null)).toBeNull();
    expect(shortenPersonName(undefined)).toBeNull();
  });
});

describe("formatDeadlineShort", () => {
  it("2026-09-30 → 30.09; rok pomijamy", () => {
    expect(formatDeadlineShort("2026-09-30")).toBe("30.09");
    expect(formatDeadlineShort("2026-09-30T12:00:00Z")).toBe("30.09");
  });

  it("brak albo śmieć daje null, nie „Invalid Date”", () => {
    expect(formatDeadlineShort(null)).toBeNull();
    expect(formatDeadlineShort("kiedyś")).toBeNull();
  });
});

describe("buildJobHeaderSubtitle", () => {
  it("składa linię z makiety w podanej kolejności", () => {
    expect(
      buildJobHeaderSubtitle({
        location: "Warszawa",
        remotePolicy: "hybrid",
        rateBudgetHourly: 122.5,
        deadline: "2026-09-30",
        ownerName: "Marta Kowalska",
      }).join(" · "),
    ).toBe("Warszawa / hybryda · budżet do 122,50 PLN/h · deadline 30.09 · Marta K.");
  });

  it("brak właściciela jest nazwany, a nie pominięty", () => {
    // To jedyny segment z wartością zastępczą: brak właściciela znaczy, że
    // nikt nie dostanie alertów deadline'u — czyli jest sprawą, nie ciszą.
    expect(buildJobHeaderSubtitle({})).toEqual(["właściciel: nieprzypisany"]);
  });

  it("zredagowana stawka po prostu nie wychodzi (rola bez uprawnień finansowych)", () => {
    const segments = buildJobHeaderSubtitle({
      location: "Kraków",
      rateBudgetHourly: null,
      ownerName: "Jan Kowalski",
    });
    expect(segments).toEqual(["Kraków", "Jan K."]);
    expect(segments.join(" · ")).not.toContain("PLN");
  });

  it("widełki z ogłoszenia nie znikają — to inna liczba niż sufit budżetu", () => {
    const segments = buildJobHeaderSubtitle({
      rateBudgetHourly: 122.5,
      salaryMin: 15000,
      salaryMax: 20000,
      ownerName: "Marta Kowalska",
    });
    expect(segments[0]).toBe("budżet do 122,50 PLN/h");
    expect(segments[1]).toMatch(/^15\s?000–20\s?000 PLN$/);
  });

  it("sam tryb pracy bez lokalizacji też jest faktem", () => {
    expect(buildJobHeaderSubtitle({ remotePolicy: "remote" })[0]).toBe("zdalnie");
    expect(buildJobHeaderSubtitle({ remotePolicy: "onsite" })[0]).toBe(
      "stacjonarnie",
    );
  });

  it("hiring manager idzie pełnym nazwiskiem, obsada tylko z obiema liczbami", () => {
    const segments = buildJobHeaderSubtitle({
      ownerName: "Marta Kowalska",
      hiringManagerName: "Anna Nowak",
      hired: 1,
      headcount: 2,
    });
    expect(segments).toEqual([
      "Marta K.",
      "HM: Anna Nowak (decydent)",
      "obsada 1 / 2",
    ]);
    // Bez jednej z liczb „obsada" byłaby zdaniem bez sensu.
    expect(
      buildJobHeaderSubtitle({ ownerName: "Marta Kowalska", hired: 1 }),
    ).toEqual(["Marta K."]);
  });
});

describe("preferencja zwiniętego nagłówka", () => {
  it("bez zapisanego wyboru panel „Zespół i priorytet” jest ZWINIĘTY", () => {
    // Rozwinięty zabierał ~40 % ekranu na KAŻDEJ zakładce rekrutacji.
    expect(JOB_HEADER_COLLAPSED_DEFAULT).toBe(true);
  });

  it("klucz zostaje na :v2 — podbicie skasowałoby zapamiętany wybór użytkownikom", () => {
    expect(JOB_HEADER_COLLAPSED_STORAGE_KEY).toBe("nexus:jobHeaderCollapsed:v2");
  });
});
