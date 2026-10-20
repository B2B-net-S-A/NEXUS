import { describe, expect, it } from "vitest";

import type { HrModuleKey } from "@/lib/api/hr";

import { myTimeTabs, yearMonthFromParams, type MyTimeModuleTab } from "../MyTimeScreen";

const open = (on: Partial<Record<HrModuleKey, boolean>>) => ({
  open_modules: {
    people: false,
    leave: false,
    time: false,
    payroll: false,
    lifecycle: false,
    care: false,
    cases: false,
    equipment: false,
    settlements: false,
    approvals: false,
    ...on,
  },
});

describe("zakładki „Mój czas”", () => {
  it("„Przegląd” zawsze pierwszy, urlopy przy otwartym module, kartoteka na końcu", () => {
    expect(myTimeTabs(open({ leave: true })).map((tab) => tab.value)).toEqual([
      "overview",
      "leave",
      "profile",
    ]);
    expect(myTimeTabs(open({})).map((tab) => tab.value)).toEqual(["overview", "profile"]);
  });

  it("zakładka Płac nazywa się „Premie i stawka”", () => {
    const tabs = myTimeTabs(open({ payroll: true }));
    expect(tabs.find((tab) => tab.value === "bonuses")?.label).toBe("Premie i stawka");
    expect(tabs[0]).toEqual({ value: "overview", label: "Przegląd" });
  });

  it("zakładka modułu bez komponentu się nie pojawia, z komponentem — po włączeniu", () => {
    expect(myTimeTabs(open({ leave: true, time: true, payroll: true })).map((t) => t.value)).toEqual([
      "overview",
      "leave",
      "month",
      "bonuses",
      "profile",
    ]);
    expect(myTimeTabs(open({ leave: true })).map((t) => t.value)).toEqual([
      "overview",
      "leave",
      "profile",
    ]);
    const extra: MyTimeModuleTab[] = [
      { value: "leave", label: "Urlopy", module: "leave", render: () => null },
      { value: "month", label: "Mój miesiąc", module: "time", render: () => null },
      { value: "bonuses", label: "Premie", module: "payroll", render: () => null },
    ];
    expect(myTimeTabs(open({ leave: true, time: true }), extra).map((t) => t.value)).toEqual([
      "overview",
      "leave",
      "month",
      "profile",
    ]);
  });
});

describe("nazwy zakładek według formy (etap 2, D4)", () => {
  const labels = (form: "uop" | "b2b" | "zlecenie" | null) =>
    myTimeTabs(open({ leave: true, time: true }), undefined, form).map((tab) => tab.label);

  it("UoP: urlop i ewidencja; B2B: przerwy i raport godzin; zlecenie: nieobecności i potwierdzenie", () => {
    expect(labels("uop")).toEqual(["Przegląd", "Urlop", "Ewidencja czasu pracy", "Kartoteka"]);
    expect(labels("b2b")).toEqual(["Przegląd", "Przerwy", "Raport godzin", "Kartoteka"]);
    expect(labels("zlecenie")).toEqual([
      "Przegląd",
      "Nieobecności",
      "Potwierdzenie godzin",
      "Kartoteka",
    ]);
    expect(labels(null)).toEqual(labels("uop"));
  });
});

describe("miesiąc z adresu", () => {
  const params = (query: string) => new URLSearchParams(query);

  it("czyta rok i miesiąc z linku powiadomienia", () => {
    expect(yearMonthFromParams(params("tab=month&year=2026&month=11"))).toEqual({
      year: 2026,
      month: 11,
    });
  });

  it("zły albo brakujący miesiąc = bieżący (undefined)", () => {
    expect(yearMonthFromParams(params(""))).toBeUndefined();
    expect(yearMonthFromParams(params("year=2026&month=13"))).toBeUndefined();
    expect(yearMonthFromParams(params("year=abc&month=5"))).toBeUndefined();
  });
});
