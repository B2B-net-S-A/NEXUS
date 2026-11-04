import { describe, expect, it } from "vitest";

import {
  criticalBriefLine,
  criticalStatusLine,
  normalizeMust,
  pruneCritical,
  statSentence,
  suggestionButtonLabel,
  toggleCritical,
} from "@/lib/critical-skills";
import { overBudgetLabel } from "@/lib/fit-badges";
import { cvYearBadge } from "@/lib/proposal-facts";

describe("krytyczne — wybór 0–3", () => {
  it("dodaje najwyżej trzy pozycje", () => {
    let value = toggleCritical(null, "Java");
    value = toggleCritical(value, "Angular");
    value = toggleCritical(value, "Kafka");
    expect(value).toEqual(["Java", "Angular", "Kafka"]);
    expect(toggleCritical(value, "Docker")).toBe(value);
  });

  it("odznaczenie ostatniej wraca do „nie zdecydowano”, nie do „Brak krytycznych”", () => {
    expect(toggleCritical(["Java"], "java")).toBeNull();
    expect(toggleCritical(["Java", "Kafka"], "Java")).toEqual(["Kafka"]);
  });

  it("pruneCritical: null i [] zostają, znikająca pozycja wypada, pusto = null", () => {
    expect(pruneCritical(null, ["Java"])).toBeNull();
    expect(pruneCritical([], ["Java"])).toEqual([]);
    expect(pruneCritical(["java", "Kafka"], ["Java"])).toEqual(["Java"]);
    expect(pruneCritical(["Kafka"], ["Java"])).toBeNull();
    const same = ["Java"];
    expect(pruneCritical(same, ["Java", "Kafka"])).toBe(same);
  });

  it("normalizeMust usuwa puste i powtórki bez względu na wielkość liter", () => {
    expect(normalizeMust([" Java ", "java", "", "Kafka"])).toEqual(["Java", "Kafka"]);
  });
});

describe("krytyczne — zdania", () => {
  it("status przy braku decyzji mówi, co działa", () => {
    expect(criticalStatusLine(null, ["Java"])).toBe("Nie zdecydowano — działa podpowiedź: Java");
    expect(criticalStatusLine(null, [])).toBe(
      "Nie zdecydowano — brak podpowiedzi, bramka MUST nie ukrywa nikogo",
    );
    expect(criticalStatusLine([], ["Java"])).toMatch(/^Brak krytycznych/);
    expect(criticalStatusLine(["Java", "Angular"], [])).toBe("Krytyczne: Java, Angular");
  });

  it("podpowiedź i statystyka", () => {
    expect(suggestionButtonLabel(["Java", "Angular"])).toBe(
      "Użyj podpowiedzi: Java, Angular (z historii)",
    );
    expect(statSentence({ rate: 0.956, jobs: 41 })).toBe("96% wysłanych ją miało");
    expect(statSentence(undefined)).toBeNull();
  });

  it("linia Podglądu rozróżnia decyzję, brak krytycznych i podpowiedź", () => {
    const base = { effective: [], source: "none" as const, suggested: [] };
    expect(criticalBriefLine({ ...base, stored: ["Java"], decided: true })).toBe("Krytyczne: Java");
    expect(criticalBriefLine({ ...base, stored: [], decided: true })).toBe("Brak krytycznych");
    expect(
      criticalBriefLine({ ...base, stored: null, decided: false, suggested: ["Java"] }),
    ).toBe("Nie zdecydowano (podpowiedź: Java)");
    expect(criticalBriefLine({ ...base, stored: null, decided: false })).toBe(
      "Nie zdecydowano (brak podpowiedzi)",
    );
    expect(criticalBriefLine(null)).toBeNull();
  });
});

describe("plakietki budżetu i CV", () => {
  it("ponad budżet: z procentem, gdy znamy obie liczby", () => {
    expect(overBudgetLabel(170, 150)).toBe("oczekuje +13% ponad budżet");
    expect(overBudgetLabel(150.5, 150)).toBe("oczekuje +1% ponad budżet");
    expect(overBudgetLabel(null, 150)).toBe("ponad budżet");
    expect(overBudgetLabel(170, null)).toBe("ponad budżet");
    expect(overBudgetLabel(170, 0)).toBe("ponad budżet");
  });

  it("CV z RRRR: rok z daty, starsze niż 2 lata ostrzegają, bez daty nic", () => {
    const now = new Date(2026, 8, 30);
    expect(cvYearBadge("2025-03-01", now)).toEqual({ label: "CV z 2025", stale: false });
    expect(cvYearBadge("2024-10-01", now)).toEqual({ label: "CV z 2024", stale: false });
    expect(cvYearBadge("2024-09-29", now)).toEqual({ label: "CV z 2024", stale: true });
    expect(cvYearBadge("2019-01-15", now)).toEqual({ label: "CV z 2019", stale: true });
    expect(cvYearBadge(null, now)).toBeNull();
    expect(cvYearBadge(undefined, now)).toBeNull();
    expect(cvYearBadge("", now)).toBeNull();
    expect(cvYearBadge("nie-data", now)).toBeNull();
  });
});
