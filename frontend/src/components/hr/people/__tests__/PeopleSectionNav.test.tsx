import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { HrConfig, HrCounts, HrModuleKey } from "@/lib/api/hr";
import { parseHrCounts } from "@/lib/api/hr";

import { PeopleSectionNav, sectionCount } from "../PeopleSectionNav";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const countsState = vi.hoisted(() => ({
  current: { isSuccess: false, data: undefined } as {
    isSuccess: boolean;
    data: HrCounts | undefined;
  },
  enabled: [] as boolean[],
}));
vi.mock("@/lib/api/hr", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr")>()),
  useHrCounts: (enabled: boolean) => {
    countsState.enabled.push(enabled);
    return countsState.current;
  },
}));

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

function config(me: Partial<HrConfig["me"]>): HrConfig {
  return {
    program: true,
    modules: ALL_ON,
    open_modules: ALL_ON,
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

const manager = config({ is_manager: true, direct_reports: 2, cases: true });

function tab(name: string) {
  return screen.getByRole("tab", { name: new RegExp(`^${name}`) });
}

beforeEach(() => {
  countsState.current = { isSuccess: false, data: undefined };
  countsState.enabled = [];
});

describe("liczniki zakładek „Ludzie”", () => {
  it("pokazuje liczbę przy Akceptacjach po udanym odczycie; Spraw w Ludziach już nie ma", () => {
    countsState.current = { isSuccess: true, data: { approvals: 3, consents: null, cases: 0 } };
    render(<PeopleSectionNav config={manager} active="directory" />);
    expect(tab("Akceptacje")).toHaveTextContent("Akceptacje3");
    expect(screen.queryByRole("tab", { name: /Sprawy/ })).toBeNull();
    expect(tab("Katalog")).toHaveTextContent(/^Katalog$/);
  });

  it("awaria odczytu nie udaje zera — brak liczby", () => {
    // react-query trzyma stare `data` po nieudanym odświeżeniu.
    countsState.current = { isSuccess: false, data: { approvals: 3, consents: null, cases: 1 } };
    render(<PeopleSectionNav config={manager} active="approvals" />);
    expect(tab("Akceptacje")).toHaveTextContent(/^Akceptacje$/);
  });

  it("„nie dotyczy” (null) to brak liczby", () => {
    expect(sectionCount("approvals", { approvals: 2, consents: null, cases: null })).toBe(2);
    expect(sectionCount("directory", { approvals: 2, consents: null, cases: 4 })).toBeUndefined();
    expect(sectionCount("approvals", undefined)).toBeUndefined();
  });

  it("nie pyta o liczby, gdy żadna zakładka ich nie pokazuje", () => {
    render(<PeopleSectionNav config={config({})} active="directory" />);
    expect(countsState.enabled).toEqual([false]);
  });

  it("odpowiedź w innym kształcie to błąd zapytania, nie liczba", () => {
    expect(parseHrCounts({ approvals: 2, cases: null })).toEqual({
      approvals: 2,
      consents: null,
      cases: null,
    });
    expect(parseHrCounts({ approvals: 2, consents: 3, cases: null }).consents).toBe(3);
    expect(() => parseHrCounts({ approvals: 2, consents: -1, cases: null })).toThrow();
    expect(() => parseHrCounts({ approvals: "2", cases: null })).toThrow();
    expect(() => parseHrCounts({ approvals: 2 })).toThrow();
    expect(() => parseHrCounts(null)).toThrow();
  });
});
