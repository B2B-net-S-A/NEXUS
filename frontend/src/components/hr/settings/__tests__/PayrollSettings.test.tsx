import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: async () => ({ data: { items: [] } }) },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
// Karty z własnymi zapytaniami — tu liczy się tylko, GDZIE stoją reguły premii.
vi.mock("@/components/hr/payroll/BonusRulesCard", () => ({
  BonusRulesCard: () => <div>karta reguł premii</div>,
}));
vi.mock("@/components/hr/settings/M365Card", () => ({ M365Card: () => null }));
vi.mock("@/components/hr/lifecycle/LifecycleTemplatesCard", () => ({
  LifecycleTemplatesCard: () => null,
}));

import { HrSettings } from "@/components/hr/settings/HrSettings";
import { PayrollSettings, canEditPayrollSettings } from "@/components/hr/settings/PayrollSettings";
import type { HrConfig, HrModuleKey } from "@/lib/api/hr";

const MODULES: HrModuleKey[] = ["people", "leave", "time", "payroll", "lifecycle", "care", "cases", "equipment"];

function config(me: Partial<HrConfig["me"]>, payrollOpen = true): HrConfig {
  const modules = Object.fromEntries(
    MODULES.map((key) => [key, key === "payroll" ? payrollOpen : true]),
  ) as Record<HrModuleKey, boolean>;
  return {
    modules,
    open_modules: modules,
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

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("Ustawienia → Płace", () => {
  it("osoba z samymi „Płacami” (Finanse) dochodzi do reguł premii", () => {
    expect(canEditPayrollSettings(config({ payroll: true }))).toBe(true);
    renderWith(<PayrollSettings config={config({ payroll: true })} />);
    expect(screen.getByRole("heading", { name: "Płace" })).toBeInTheDocument();
    expect(screen.getByText("karta reguł premii")).toBeInTheDocument();
  });

  it("Kadry bez „Płac” nie zmieniają reguł — zdanie zamiast karty", () => {
    expect(canEditPayrollSettings(config({ people_admin: true }))).toBe(false);
    renderWith(<PayrollSettings config={config({ people_admin: true })} />);
    expect(
      screen.getByText("Reguły premii zmienia osoba z uprawnieniem „Płace” albo administrator."),
    ).toBeInTheDocument();
    expect(screen.queryByText("karta reguł premii")).toBeNull();
  });

  it("wyłączony moduł płac: zdanie, bez karty (zapisy i tak dostałyby 404)", () => {
    renderWith(<PayrollSettings config={config({ payroll: true }, false)} />);
    expect(screen.getByText(/Moduł płac nie jest jeszcze włączony/)).toBeInTheDocument();
    expect(screen.queryByText("karta reguł premii")).toBeNull();
  });
});

describe("Ustawienia → Kadry po przeniesieniu reguł premii", () => {
  it("karty reguł już tu nie ma; Kadry z „Płacami” dostają link do Ustawienia → Płace", () => {
    renderWith(<HrSettings config={config({ people_admin: true, payroll: true })} />);
    expect(screen.queryByText("karta reguł premii")).toBeNull();
    expect(screen.getByRole("link", { name: "Ustawienia → Płace" })).toHaveAttribute(
      "href",
      "/settings/payroll",
    );
  });

  it("Kadry bez „Płac” widzą, gdzie są reguły i kto je zmienia — bez linku", () => {
    renderWith(<HrSettings config={config({ people_admin: true })} />);
    expect(
      screen.getByText("Reguły premii są w Ustawienia → Płace — zmienia je osoba z uprawnieniem „Płace”."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ustawienia → Płace" })).toBeNull();
  });

  it("wyłączony moduł płac — bez drogowskazu", () => {
    renderWith(<HrSettings config={config({ people_admin: true }, false)} />);
    expect(screen.queryByText(/Reguły premii są w/)).toBeNull();
  });
});
