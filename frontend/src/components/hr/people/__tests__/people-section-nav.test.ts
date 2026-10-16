import { describe, expect, it } from "vitest";

import type { HrConfig, HrModuleKey } from "@/lib/api/hr";

import { peopleSections } from "../PeopleSectionNav";

const ALL_ON: Record<HrModuleKey, boolean> = {
  people: true,
  leave: true,
  time: true,
  payroll: true,
  lifecycle: true,
  care: true,
  cases: true,
  equipment: true,
};

function config(me: Partial<HrConfig["me"]>, open = ALL_ON): HrConfig {
  return {
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

  it("Sprawy i Płace tylko z uprawnieniem", () => {
    expect(values(config({ cases: true }))).toContain("cases");
    expect(values(config({ cases: true }))).not.toContain("payroll");
    expect(values(config({ payroll: true }))).toContain("payroll");
  });

  it("przypisany do sprawy bez uprawnienia widzi Sprawy", () => {
    expect(values(config({ has_assigned_cases: true }))).toContain("cases");
  });

  it("wyłączony moduł chowa zakładkę mimo uprawnienia", () => {
    const off = { ...ALL_ON, cases: false, leave: false, time: false };
    const got = values(config({ cases: true, is_manager: true }, off));
    expect(got).toEqual(["directory"]);
  });

  it("Kadry bez kartoteki widzą kalendarz i akceptacje", () => {
    expect(values(config({ has_profile: false, people_admin: true }))).toEqual([
      "directory",
      "calendar",
      "approvals",
    ]);
  });
});
