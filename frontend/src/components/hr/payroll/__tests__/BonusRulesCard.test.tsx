/**
 * Reguły premii (runda 2, 21.10.2026): progi jako tabela, przykład liczony
 * z pól przed zapisem (lustro `bonus_rules.recruiter_tier` / `dl_bonus`)
 * i pasek zapisu tylko przy niezapisanych zmianach. Dane fikcyjne.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BonusRules } from "@/lib/api/hr-payroll";

const RULES: BonusRules = vi.hoisted(() => ({
  recruiter_tier_bounds: ["40", "50"],
  recruiter_tier_amounts: ["1000", "1500", "2000"],
  dl_percent: "10",
  monthly_hours: 168,
  eligible_business_days: 21,
  currency: "PLN",
  extra_dl: [],
  automation_since: null,
  league_types: [],
}) as BonusRules);

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/lib/api/hr", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr")>()),
  usePeople: () => ({ data: { items: [] } }),
}));
vi.mock("@/lib/api/hr-payroll", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr-payroll")>()),
  useBonusRules: () => ({ data: RULES, isLoading: false, isError: false, error: null, isSuccess: true }),
  useSaveBonusRules: () => ({ mutate: vi.fn(), isPending: false }),
  useRefreshProposals: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { BonusRulesCard, bonusExample, formFromRules } from "../BonusRulesCard";

describe("bonusExample", () => {
  const form = formFromRules(RULES);

  it("progi jak serwer: do 40 włącznie = I, poniżej 50 = II, od 50 = III", () => {
    expect(bonusExample(form, "40")).toMatchObject({ tier: 1, recruiter: 1000 });
    expect(bonusExample(form, "45,5")).toMatchObject({ tier: 2, recruiter: 1500 });
    expect(bonusExample(form, "50")).toMatchObject({ tier: 3, recruiter: 2000 });
  });

  it("DL = marża/h × godziny w miesiącu × procent", () => {
    expect(bonusExample(form, "46")?.dl).toBe(772.8);
  });

  it("zła marża albo zła liczba w polu — bez przykładu", () => {
    expect(bonusExample(form, "")).toBeNull();
    expect(bonusExample({ ...form, tier2: "abc" }, "45")).toBeNull();
  });
});

describe("BonusRulesCard", () => {
  it("progi w tabeli, przykład po wpisaniu marży, pasek zapisu dopiero po zmianie", () => {
    render(<BonusRulesCard />);
    expect(screen.getByLabelText("Próg I do (zł/h)")).toHaveValue("40");
    expect(screen.getByLabelText("Próg III od (zł/h)")).toHaveValue("50");
    expect(screen.queryByRole("button", { name: "Zapisz reguły" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Marża konsultanta (zł/h)"), { target: { value: "46" } });
    expect(screen.getByTestId("rules-example")).toHaveTextContent("Próg II: rekruter dostaje 1500 zł");
    // Przykład nie zmienia reguł — pasek zapisu dalej schowany.
    expect(screen.queryByRole("button", { name: "Zapisz reguły" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Premia progu II"), { target: { value: "1600" } });
    expect(screen.getByText("Niezapisane zmiany w regułach")).toBeInTheDocument();
    expect(screen.getByTestId("rules-example")).toHaveTextContent("1600 zł");

    fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
    expect(screen.getByLabelText("Premia progu II")).toHaveValue("1500");
    expect(screen.queryByRole("button", { name: "Zapisz reguły" })).toBeNull();
  });
});
