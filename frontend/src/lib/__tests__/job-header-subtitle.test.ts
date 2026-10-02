/**
 * Podtytuł jobbara (`lib/job-header-subtitle.ts`) — segmenty, nie render.
 */

import { describe, expect, it } from "vitest";

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
        recruiterLead: "Marta Kowalska",
      }).join(" · "),
    ).toBe(
      "Warszawa / hybryda · budżet do 122,50 PLN/h · deadline 30.09 · Rekruter: Marta K.",
    );
  });

  it("brak rekrutera jest nazwany, a nie pominięty", () => {
    // To jedyny segment z wartością zastępczą: „Bez rekrutera” znaczy, że nikt
    // nad rekrutacją nie pracuje — czyli jest sprawą, nie ciszą.
    expect(buildJobHeaderSubtitle({})).toEqual(["Bez rekrutera"]);
    expect(buildJobHeaderSubtitle({ recruiterLead: "  ", recruiterMore: 2 })).toEqual([
      "Bez rekrutera",
    ]);
  });

  it("kolejne osoby idą jako „+N” przy pierwszym rekruterze", () => {
    expect(
      buildJobHeaderSubtitle({ recruiterLead: "Marta Kowalska", recruiterMore: 2 }),
    ).toEqual(["Rekruter: Marta K. +2"]);
    // Zero i brak liczby nie dokładają „+0”.
    expect(
      buildJobHeaderSubtitle({ recruiterLead: "Marta Kowalska", recruiterMore: 0 }),
    ).toEqual(["Rekruter: Marta K."]);
    expect(
      buildJobHeaderSubtitle({ recruiterLead: "Marta Kowalska", recruiterMore: null }),
    ).toEqual(["Rekruter: Marta K."]);
  });

  it("przyjmuje nazwisko już skrócone (`lead` z `recruitersSummary`) i pełne — wynik ten sam", () => {
    expect(buildJobHeaderSubtitle({ recruiterLead: "Marta K." })).toEqual([
      "Rekruter: Marta K.",
    ]);
    expect(buildJobHeaderSubtitle({ recruiterLead: "Marta Kowalska" })).toEqual([
      "Rekruter: Marta K.",
    ]);
  });

  it("nie używa dawnych nazw („Prowadzi”, „właściciel”)", () => {
    const line = [
      ...buildJobHeaderSubtitle({}),
      ...buildJobHeaderSubtitle({ recruiterLead: "Marta Kowalska", recruiterMore: 1 }),
    ].join(" · ");
    expect(line).not.toMatch(/Prowadzi|właściciel|nieprzypisany/i);
  });

  it("zredagowana stawka po prostu nie wychodzi (rola bez uprawnień finansowych)", () => {
    const segments = buildJobHeaderSubtitle({
      location: "Kraków",
      rateBudgetHourly: null,
      recruiterLead: "Jan Kowalski",
    });
    expect(segments).toEqual(["Kraków", "Rekruter: Jan K."]);
    expect(segments.join(" · ")).not.toContain("PLN");
  });

  it("widełki z ogłoszenia nie znikają — to inna liczba niż sufit budżetu", () => {
    const segments = buildJobHeaderSubtitle({
      rateBudgetHourly: 122.5,
      salaryMin: 15000,
      salaryMax: 20000,
      recruiterLead: "Marta Kowalska",
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
      recruiterLead: "Marta Kowalska",
      hiringManagerName: "Anna Nowak",
      hired: 1,
      headcount: 2,
    });
    expect(segments).toEqual([
      "Rekruter: Marta K.",
      "HM: Anna Nowak (decydent)",
      "obsada 1 / 2",
    ]);
    // Bez jednej z liczb „obsada" byłaby zdaniem bez sensu.
    expect(
      buildJobHeaderSubtitle({ recruiterLead: "Marta Kowalska", hired: 1 }),
    ).toEqual(["Rekruter: Marta K."]);
  });
});

describe("buildJobHeaderSubtitle — Delivery Lead (M03-B03)", () => {
  it("pokazuje DL rekrutacji zaraz po rekruterze", () => {
    expect(
      buildJobHeaderSubtitle({
        recruiterLead: "Marta Kowalska",
        deliveryLeadName: "Jan Nowak",
      }),
    ).toEqual(["Rekruter: Marta K.", "DL: Jan N."]);
  });

  it("brak DL nie dokłada segmentu", () => {
    expect(buildJobHeaderSubtitle({ recruiterLead: "Marta Kowalska" })).toEqual([
      "Rekruter: Marta K.",
    ]);
  });
});
