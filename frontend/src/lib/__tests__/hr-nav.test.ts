import { describe, expect, it } from "vitest";

import { hrNavState, type HrConfig } from "@/lib/api/hr";
import { visibleNavEntries, visiblePrimaryGroups } from "@/lib/nav-registry";
import { postLoginDestination } from "@/store/auth";

const MODULES = {
  people: true,
  leave: true,
  time: false,
  payroll: false,
  lifecycle: false,
  care: false,
  cases: false,
  equipment: true,
  settlements: false,
  approvals: false,
};

function config(me: Partial<HrConfig["me"]>, open = MODULES): HrConfig {
  return {
    program: true,
    modules: open,
    open_modules: open,
    me: {
      has_profile: false,
      employment_status: null,
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

describe("menu modułu „Ludzie w NEXUSIE”", () => {
  it("wyłączony program ukrywa wszystko, także adminowi z otwartymi modułami", () => {
    const all = Object.fromEntries(Object.keys(MODULES).map((k) => [k, true])) as typeof MODULES;
    const off = { ...config({ is_admin: true, has_profile: true, people_admin: true }, all), program: false };
    expect(hrNavState(off)).toEqual({ myTime: false, people: false, equipment: false, care: false });
  });

  it("bez odczytu konfiguracji wszystko ukryte", () => {
    expect(hrNavState(undefined)).toEqual({
      myTime: false,
      people: false,
      equipment: false,
      care: false,
    });
  });

  it("osoba z kartoteką widzi „Mój czas” i „Ludzie”, ale nie „Sprzęt”", () => {
    expect(hrNavState(config({ has_profile: true }))).toEqual({
      myTime: true,
      people: true,
      equipment: false,
      care: false,
    });
  });

  it("recepcja z uprawnieniem „Sprzęt” bez kartoteki widzi Ludzi i Sprzęt", () => {
    expect(hrNavState(config({ equipment: true }))).toEqual({
      myTime: false,
      people: true,
      equipment: true,
      care: false,
    });
  });

  it("„Opieka”: moduł care i rola opieki", () => {
    expect(hrNavState(config({}, { ...MODULES, care: true }), true).care).toBe(true);
    expect(hrNavState(config({}, { ...MODULES, care: true })).care).toBe(false);
    expect(hrNavState(config({}), true).care).toBe(false);
  });

  it("„Opieka” bez roli opieki dla osoby ze sprawami administracja@ (Sprawy przeszły z Ludzi, 22.10.2026)", () => {
    const withCases = { ...MODULES, care: true, cases: true };
    expect(hrNavState(config({ cases: true }, withCases)).care).toBe(true);
    expect(hrNavState(config({ has_assigned_cases: true }, withCases)).care).toBe(true);
    // Moduł spraw wyłączony — nie ma czego pokazać.
    expect(hrNavState(config({ cases: true }, { ...MODULES, care: true })).care).toBe(false);
    // Bez spraw i bez roli — nic.
    expect(hrNavState(config({ has_profile: true }, withCases)).care).toBe(false);
  });

  it("menu: rekruter z uprawnieniem „Sprawy” widzi „Opiekę”, bez niego nie", () => {
    const recruiter = { role: "recruiter" as const, roles: ["recruiter" as const] };
    const withCases = { ...MODULES, care: true, cases: true };
    const ids = (me: Partial<HrConfig["me"]>) =>
      visibleNavEntries(recruiter, { contactQueueEnabled: true, hr: hrNavState(config(me, withCases)) }).map(
        (entry) => entry.id,
      );
    expect(ids({ cases: true })).toContain("care");
    expect(ids({ has_profile: true })).not.toContain("care");
  });

  it("wyłączony moduł chowa pozycję mimo kartoteki", () => {
    const off = { ...MODULES, people: false, leave: false, equipment: false, settlements: false };
    expect(hrNavState(config({ has_profile: true }, off))).toEqual({
      myTime: false,
      people: false,
      equipment: false,
      care: false,
    });
  });

  it("„Pracownik” ma w menu tylko „Mój czas”, „Ludzie” i pozycje systemowe", () => {
    const employee = { role: "employee" as const, roles: ["employee" as const] };
    const hr = hrNavState(config({ has_profile: true }));
    const ids = visibleNavEntries(employee, { contactQueueEnabled: true, hr }).map(
      (entry) => entry.id,
    );
    expect(ids).toEqual(["my-time", "people", "help", "settings"]);
    expect(
      visiblePrimaryGroups(employee, { contactQueueEnabled: true, hr }).map((group) => [
        group.title,
        group.items.map((item) => item.id),
      ]),
    ).toEqual([
      ["Praca", ["my-time"]],
      ["Firma", ["people"]],
    ]);
  });

  it("rekruter bez stanu modułu nie widzi nowych pozycji (dotychczasowe menu bez zmian)", () => {
    const recruiter = { role: "recruiter" as const, roles: ["recruiter" as const] };
    const ids = visibleNavEntries(recruiter, { contactQueueEnabled: true }).map(
      (entry) => entry.id,
    );
    expect(ids).not.toContain("my-time");
    expect(ids).not.toContain("people");
    expect(ids).not.toContain("equipment");
  });
});

describe("lądowanie „Pracownika”", () => {
  const employee = {
    role: "employee" as const,
    roles: ["employee" as const],
    profile_completed: true,
    force_password_change: false,
  };

  it("pulpit i strona główna prowadzą do „Mój czas”", () => {
    expect(postLoginDestination(employee)).toBe("/my-time");
    expect(postLoginDestination(employee, "/dashboard")).toBe("/my-time");
  });

  it("jawny adres ekranu „Ludzie” zostaje", () => {
    expect(postLoginDestination(employee, "/people/12")).toBe("/people/12");
  });
});
