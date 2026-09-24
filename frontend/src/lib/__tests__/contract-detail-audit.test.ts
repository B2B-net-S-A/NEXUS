/**
 * Audyt modułu Kontrakty 24.09.2026 (blok D) — czyste reguły frontu.
 *
 * S9 zakładka szczegółów kontraktu w adresie (`?tab=`),
 * W2 harmonogram stawek z formularza: tylko przy realnej zmianie, z notatką,
 *    duplikat daty „od” legalny (rozstrzyga kolejność wpisu).
 */
import { describe, expect, it } from "vitest";

import {
  contractDetailTabHref,
  isContractDetailTab,
} from "@/lib/contract-detail-tab";
import {
  buildScheduleEditSteps,
  scheduleStepsChanged,
  sortSavedSchedule,
} from "@/lib/contract-rate-schedule";

describe("zakładka szczegółów kontraktu w adresie (S9)", () => {
  it("zna klucze używane przez linki z backendu", () => {
    for (const key of ["documents", "equipment", "notes", "invoices", "timeline"]) {
      expect(isContractDetailTab(key)).toBe(true);
    }
    expect(isContractDetailTab("zamowienia")).toBe(false);
    expect(isContractDetailTab(null)).toBe(false);
  });

  it("zapisuje zakładkę, zachowując kontekst powrotu do listy", () => {
    expect(
      contractDetailTabHref("/contracts/5", "?returnTo=%2Fcontracts%3Fpage%3D2", "documents"),
    ).toBe("/contracts/5?returnTo=%2Fcontracts%3Fpage%3D2&tab=documents");
  });

  it("„Szczegóły” zdejmują parametr, a wyjście z notatek — `note=`", () => {
    expect(contractDetailTabHref("/contracts/5", "?tab=notes&note=9", "details")).toBe(
      "/contracts/5",
    );
    expect(contractDetailTabHref("/contracts/5", "?tab=notes&note=9", "equipment")).toBe(
      "/contracts/5?tab=equipment",
    );
  });
});

describe("harmonogram stawek w formularzu edycji (W2)", () => {
  const saved = [
    { rate: 165, effective_from: "2026-01-01", effective_to: null, note: "Aneks od startu" },
    { rate: 150, effective_from: "2026-01-01", effective_to: null, note: "Stawka początkowa" },
  ];

  it("sortuje stabilnie — dwa kroki z tą samą datą zostają w kolejności wpisu", () => {
    expect(sortSavedSchedule(saved).map((s) => s.rate)).toEqual([165, 150]);
  });

  it("niesie notatkę kroku i zapisaną datę końca", () => {
    const steps = buildScheduleEditSteps(
      [
        { rate: "150", effectiveFrom: "", effectiveTo: "", note: "Stawka początkowa" },
        { rate: "160,50", effectiveFrom: "2026-07-01", effectiveTo: "2026-12-31", note: null },
        { rate: "", effectiveFrom: "2026-08-01", effectiveTo: "" },
      ],
      "2026-01-01",
    );
    expect(steps).toEqual([
      { rate: 150, effective_from: "2026-01-01", effective_to: null, note: "Stawka początkowa" },
      { rate: 160.5, effective_from: "2026-07-01", effective_to: "2026-12-31", note: null },
    ]);
  });

  it("niezmieniony harmonogram — także z duplikatem daty — nie jest zmianą", () => {
    const rows = sortSavedSchedule(saved).map((s) => ({
      rate: String(s.rate),
      effectiveFrom: s.effective_from,
      effectiveTo: "",
      note: s.note,
    }));
    const steps = buildScheduleEditSteps(rows, "2026-01-01");
    expect(scheduleStepsChanged(steps, saved)).toBe(false);
  });

  it("zmiana kwoty, daty albo liczby kroków jest zmianą", () => {
    const base = [{ rate: 150, effective_from: "2026-01-01", effective_to: null }];
    expect(
      scheduleStepsChanged([{ rate: 151, effective_from: "2026-01-01", effective_to: null }], base),
    ).toBe(true);
    expect(
      scheduleStepsChanged([{ rate: 150, effective_from: "2026-02-01", effective_to: null }], base),
    ).toBe(true);
    expect(scheduleStepsChanged([], base)).toBe(true);
  });
});
