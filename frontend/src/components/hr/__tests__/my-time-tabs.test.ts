import { describe, expect, it } from "vitest";

import type { HrModuleKey } from "@/lib/api/hr";

import {
  consentsTabVisible,
  myTimeTabs,
  yearMonthFromParams,
  type MyTimeModuleTab,
} from "../MyTimeScreen";

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
  it("„Przegląd” zawsze pierwszy, urlopy przy otwartym module, bez zakładki „Kartoteka”", () => {
    expect(myTimeTabs(open({ leave: true })).map((tab) => tab.value)).toEqual([
      "overview",
      "leave",
    ]);
    expect(myTimeTabs(open({})).map((tab) => tab.value)).toEqual(["overview"]);
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
    ]);
    expect(myTimeTabs(open({ leave: true })).map((t) => t.value)).toEqual([
      "overview",
      "leave",
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
    ]);
  });
});

describe("„Zgody i wydatki” (22.10.2026, dawne „Moje zgody”)", () => {
  const me = (has_profile: boolean, is_admin = false) => ({ has_profile, is_admin });

  it("ostatnia zakładka przy otwartym module „Zgody” — z kartoteką albo dla admina", () => {
    const withProfile = { ...open({ leave: true, approvals: true }), me: me(true) };
    expect(myTimeTabs(withProfile).map((tab) => tab.value)).toEqual([
      "overview",
      "leave",
      "consents",
    ]);
    expect(myTimeTabs(withProfile).at(-1)?.label).toBe("Zgody i wydatki");
    expect(consentsTabVisible({ ...open({ approvals: true }), me: me(false, true) })).toBe(true);
  });

  it("bez modułu, bez kartoteki (nie admin) albo bez danych o osobie — bez zakładki", () => {
    expect(consentsTabVisible({ ...open({}), me: me(true, true) })).toBe(false);
    expect(consentsTabVisible({ ...open({ approvals: true }), me: me(false) })).toBe(false);
    expect(consentsTabVisible(open({ approvals: true }))).toBe(false);
  });
});

describe("nazwy zakładek według formy (etap 2, D4)", () => {
  const labels = (form: "uop" | "b2b" | "zlecenie" | null) =>
    myTimeTabs(open({ leave: true, time: true }), undefined, form).map((tab) => tab.label);

  it("UoP: urlop i ewidencja; B2B: przerwy i raport godzin; zlecenie: nieobecności i potwierdzenie", () => {
    expect(labels("uop")).toEqual(["Przegląd", "Urlop", "Ewidencja czasu pracy"]);
    expect(labels("b2b")).toEqual(["Przegląd", "Przerwy", "Raport godzin"]);
    expect(labels("zlecenie")).toEqual(["Przegląd", "Nieobecności", "Potwierdzenie godzin"]);
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
