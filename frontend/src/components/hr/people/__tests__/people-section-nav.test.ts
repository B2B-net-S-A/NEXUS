import { describe, expect, it } from "vitest";

import type { HrConfig, HrModuleKey } from "@/lib/api/hr";

import { peopleSections, sectionCount } from "../PeopleSectionNav";

const ALL_ON: Record<HrModuleKey, boolean> = {
  people: true,
  leave: true,
  time: true,
  payroll: true,
  lifecycle: true,
  care: true,
  cases: true,
  equipment: true,
  settlements: false,
  approvals: false,
};

function config(me: Partial<HrConfig["me"]>, open = ALL_ON): HrConfig {
  return {
    program: true,
    modules: open,
    open_modules: open,
    me: {
      has_profile: true,
      employment_status: "active",
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: false,
      payroll: false,
      equipment: false,
      cases: false,
      ...me,
    },
  };
}

const values = (cfg: HrConfig) => peopleSections(cfg).map((link) => link.value);

describe("zakładki obszaru „Ludzie”", () => {
  it("pracownik bez praw: katalog i kalendarz zespołu", () => {
    expect(values(config({}))).toEqual(["directory", "calendar"]);
  });

  it("przełożony widzi akceptacje", () => {
    expect(values(config({ is_manager: true, direct_reports: 2 }))).toContain("approvals");
  });

  it("Płace tylko z uprawnieniem", () => {
    expect(values(config({ cases: true }))).not.toContain("payroll");
    expect(values(config({ payroll: true }))).toContain("payroll");
  });

  it("Sprawy przeszły do Opieki (22.10.2026) — nie ma ich w Ludziach nawet z uprawnieniem", () => {
    expect(values(config({ cases: true }))).not.toContain("cases");
    expect(values(config({ has_assigned_cases: true }))).not.toContain("cases");
    expect(values(config({ is_admin: true }))).not.toContain("cases");
  });

  it("wyłączony moduł chowa zakładkę mimo uprawnienia", () => {
    const off = { ...ALL_ON, cases: false, leave: false, time: false };
    const got = values(config({ cases: true, is_manager: true }, off));
    // „Mój zespół” zostaje — należy do modułu „Ludzie”, nie do urlopów i czasu.
    expect(got).toEqual(["directory", "team"]);
  });

  it("Kadry bez kartoteki: katalog (ze Schematem), kalendarz i akceptacje", () => {
    expect(values(config({ has_profile: false, people_admin: true }))).toEqual([
      "directory",
      "calendar",
      "approvals",
    ]);
  });

  it("„Mój zespół” tylko u przełożonego, zaraz po katalogu", () => {
    const manager = values(config({ is_manager: true, direct_reports: 2 }));
    expect(manager.slice(0, 2)).toEqual(["directory", "team"]);
    expect(values(config({ people_admin: true }))).not.toContain("team");
  });

  it("stała kolejność: Katalog · Mój zespół · Kalendarz · Akceptacje · Płace", () => {
    expect(values(config({ is_admin: true, is_manager: true, direct_reports: 2 }))).toEqual([
      "directory",
      "team",
      "calendar",
      "approvals",
      "payroll",
    ]);
  });

  it("nie ma już zakładek „Struktura” i „Moje zgody” — Schemat jest w Katalogu, zgody w Moim czasie", () => {
    const withConsents = { ...ALL_ON, approvals: true };
    const got = values(config({ is_admin: true, people_admin: true }, withConsents));
    expect(got).not.toContain("structure");
    expect(got).not.toContain("consents");
  });

  it("wyłączony moduł „Ludzie” chowa Katalog i Mój zespół", () => {
    const off = { ...ALL_ON, people: false };
    const got = values(config({ people_admin: true, is_manager: true }, off));
    expect(got).not.toContain("directory");
    expect(got).not.toContain("team");
  });

  it("etykieta kalendarza to „Kalendarz”", () => {
    const calendar = peopleSections(config({})).find((link) => link.value === "calendar");
    expect(calendar?.label).toBe("Kalendarz");
  });
});

describe("zakładki przy module „Zgody” (0483)", () => {
  const withConsents = { ...ALL_ON, approvals: true };
  const onlyConsents = Object.fromEntries(
    Object.keys(ALL_ON).map((key) => [key, key === "approvals"]),
  ) as Record<HrModuleKey, boolean>;

  it("Akceptacje przy samych zgodach: przełożony i admin (zatwierdzający), zwykła osoba nie", () => {
    expect(values(config({ is_manager: true }, onlyConsents))).toContain("approvals");
    expect(values(config({ is_admin: true }, onlyConsents))).toContain("approvals");
    expect(values(config({}, onlyConsents))).not.toContain("approvals");
  });

  it("liczba przy Akceptacjach = wnioski i timesheety + zgody; brak obu = bez liczby", () => {
    expect(sectionCount("approvals", { approvals: 2, consents: 3, cases: null })).toBe(5);
    expect(sectionCount("approvals", { approvals: null, consents: 3, cases: null })).toBe(3);
    expect(sectionCount("approvals", { approvals: null, consents: null, cases: null })).toBeUndefined();
  });
});
