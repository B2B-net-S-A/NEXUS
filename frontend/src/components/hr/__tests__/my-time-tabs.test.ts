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
    ...on,
  },
});

describe("zakładki „Mój czas”", () => {
  it("urlopy tylko przy otwartym module, kartoteka zawsze na końcu", () => {
    expect(myTimeTabs(open({ leave: true })).map((tab) => tab.value)).toEqual([
      "leave",
      "profile",
    ]);
    expect(myTimeTabs(open({})).map((tab) => tab.value)).toEqual(["profile"]);
  });

  it("zakładka modułu bez komponentu się nie pojawia, z komponentem — po włączeniu", () => {
    expect(myTimeTabs(open({ leave: true, time: true, payroll: true })).map((t) => t.value)).toEqual([
      "leave",
      "month",
      "bonuses",
      "profile",
    ]);
    expect(myTimeTabs(open({ leave: true })).map((t) => t.value)).toEqual(["leave", "profile"]);
    const extra: MyTimeModuleTab[] = [
      { value: "leave", label: "Urlopy", module: "leave", render: () => null },
      { value: "month", label: "Mój miesiąc", module: "time", render: () => null },
      { value: "bonuses", label: "Premie", module: "payroll", render: () => null },
    ];
    expect(myTimeTabs(open({ leave: true, time: true }), extra).map((t) => t.value)).toEqual([
      "leave",
      "month",
      "profile",
    ]);
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
