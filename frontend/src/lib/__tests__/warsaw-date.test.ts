import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";
import { defaultUntil } from "@/components/marketplace/AddToMarketplaceButton";
import { emptyAmendmentForm } from "@/components/ContractAmendmentsTab";

describe("warsawToday", () => {
  it("po północy w Warszawie daje już nowy dzień, choć w UTC jest jeszcze wczoraj", () => {
    // 22:30 UTC 21.09 = 00:30 CEST 22.09.
    expect(warsawToday(new Date("2026-09-21T22:30:00Z"))).toBe("2026-09-22");
  });

  it("zimą (CET, UTC+1) granica doby przesuwa się o godzinę", () => {
    expect(warsawToday(new Date("2026-12-31T22:59:00Z"))).toBe("2026-12-31");
    expect(warsawToday(new Date("2026-12-31T23:00:00Z"))).toBe("2027-01-01");
  });
});

describe("emptyAmendmentForm", () => {
  it("liczy datę wejścia w życie przy otwarciu formularza, nie przy imporcie modułu", () => {
    expect(emptyAmendmentForm("rate_change", "2026-10-01")).toMatchObject({
      amendment_type: "rate_change",
      effective_date: "2026-10-01",
      new_end_date: "",
    });
    expect(emptyAmendmentForm().effective_date).toBe(warsawToday());
  });
});

// FE-N08 (audyt 22.09 r2): domyślne „dziś” w formularzach dat liczy dzień
// w Warszawie. `toISOString().slice(0, 10)` między północą a 1:00/2:00 dawało
// WCZORAJ (np. data wypowiedzenia, zamiany kontraktora, skrót Jarvisa).
describe("formularze z domyślną datą „dziś”", () => {
  const files = [
    "src/components/client-profile/orders/SwapConsultantModal.tsx",
    "src/components/contracts/FinancialRatesCard.tsx",
    // Dzień Jarvisa (skrót, budżet dymków) liczy wspólne `todayKey` stąd.
    "src/lib/jarvis/storage.ts",
    "src/components/contracts/ContractTerminationDialog.tsx",
    "src/components/contracts/ContractRegisterDialog.tsx",
    "src/components/contracts/AddProjectDialog.tsx",
    "src/app/contracts/new/page.tsx",
    "src/components/v2/pages/B2BContractGeneratorV2.tsx",
    "src/components/marketplace/AddToMarketplaceButton.tsx",
    // Runda 10 (R10-X1-4).
    "src/app/settings/rate-benchmarks/page.tsx",
  ];
  it.each(files)("%s nie liczy dnia w UTC", (file) => {
    const source = readFileSync(resolve(process.cwd(), file), "utf8");
    expect(source).not.toMatch(/new Date\(\)\.toISOString\(\)\.slice\(0, 10\)/);
    expect(source).toContain("warsawToday");
  });
});

describe("warsawDateOf (R10-X1-3)", () => {
  it("znacznik czasu z 00:00–02:00 w Warszawie to już nowy dzień", () => {
    expect(warsawDateOf("2026-09-30T22:30:00+00:00")).toBe("2026-10-01");
    expect(warsawDateOf("2026-01-31T23:15:00Z")).toBe("2026-02-01");
  });

  it("sama data wraca bez zmian, pusta i nieczytelna to null", () => {
    expect(warsawDateOf("2026-09-30")).toBe("2026-09-30");
    expect(warsawDateOf(null)).toBeNull();
    expect(warsawDateOf("")).toBeNull();
    expect(warsawDateOf("nie-data")).toBeNull();
  });

  it("ekrany ze znacznikami czasu nie tną ich już `.slice(0, 10)`", () => {
    for (const file of [
      "components/client-profile/orders/OrderGroupCard.tsx",
      "components/settings/B2BRegisterImportPanel.tsx",
      "components/insights/sections/InsightsSeniority.tsx",
      "lib/proposals-merge.ts",
      "components/ChampionProfileEditor.tsx",
    ]) {
      const source = readFileSync(resolve(process.cwd(), "src", file), "utf8");
      expect(source, file).not.toMatch(/(_at|cancelled_at|created_at)\??\.slice\(0, 10\)/);
      expect(source, file).toContain("warsawDateOf");
    }
  });
});

describe("termin „Wrzuć na targ” (R10-X1-4)", () => {
  it("po północy w Warszawie liczy 30 dni od dzisiejszego dnia firmy", () => {
    // 27.09 00:30 w Warszawie = 26.09 22:30 UTC.
    expect(defaultUntil(new Date("2026-09-26T22:30:00Z"))).toBe("2026-10-27");
  });
});

