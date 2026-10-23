import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { BonusRow, PayrollMonthDetail, PayrollPerson } from "@/lib/api/hr-payroll";

import { BonusTable } from "../BonusTable";
import { PayrollPeopleTable } from "../PayrollPeopleTable";
import { assignedBonusActions, monthStats, splitBonuses } from "../payroll-format";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const worker: PayrollPerson = {
  user_id: 7,
  name: "Anna Przykładowa",
  employment_type: "b2b",
  timesheet_required: true,
  timesheet_status: "approved",
  hours: "176.00",
  overtime_hours: "2.00",
  paid_leave_days: "1.0",
  other_leave_days: "0.0",
  rate_missing: false,
  lines: [
    {
      currency: "PLN",
      hourly_rate: "130.00",
      hours_amount: "22880.00",
      bonus_total: "772.80",
      total: "23652.80",
    },
  ],
};

function proposal(overrides: Partial<BonusRow> = {}): BonusRow {
  return {
    id: 11,
    recipient_user_id: 7,
    recipient_name: "Anna Przykładowa",
    proposed_by: null,
    proposed_by_name: null,
    amount: "1500.00",
    currency: "PLN",
    category: "recruiter",
    category_label: "Rekruter",
    period_year: 2026,
    period_month: 10,
    status: "proposed",
    source: "contract_placement",
    contract_id: 3,
    eligible_on: "2026-10-30",
    eligible: false,
    description: "Premia rekrutera — placement: Jan Przykładowy (Firma Przykładowa)",
    assigned_by: null,
    assigned_at: null,
    cancelled_at: null,
    cancel_reason: null,
    edited: false,
    business_days_elapsed: 10,
    business_days_required: 21,
    ...overrides,
  };
}

describe("Płace — tabela osób", () => {
  it("Płace widzą stawkę, kwotę za godziny i razem", () => {
    render(<PayrollPeopleTable people={[worker]} scope="payroll" />);
    expect(screen.getByText("Stawka /h")).toBeInTheDocument();
    expect(screen.getByText(/23\s652,80 zł/)).toBeInTheDocument();
    expect(screen.getByText(/w tym 2 ponad normę/)).toBeInTheDocument();
  });

  it("przełożony widzi godziny i premie, bez stawek i kwot wynagrodzenia (D2)", () => {
    const teamRow: PayrollPerson = {
      ...worker,
      lines: undefined,
      rate_missing: undefined,
      bonuses: [{ currency: "PLN", bonus_total: "772.80" }],
    };
    render(<PayrollPeopleTable people={[teamRow]} scope="team" />);
    expect(screen.queryByText("Stawka /h")).not.toBeInTheDocument();
    expect(screen.queryByText("Razem")).not.toBeInTheDocument();
    expect(screen.getByText("176")).toBeInTheDocument();
    expect(screen.getByText(/772,80 zł/)).toBeInTheDocument();
  });
});

describe("Płace — premie", () => {
  it("propozycja przed terminem pokazuje postęp dni roboczych", () => {
    render(<BonusTable rows={[proposal()]} showProgress />);
    expect(screen.getByText(/10 z 21 dni/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "48");
  });

  it("przyznana premia z kontraktu zakończonego przed terminem ma ostrzeżenie", () => {
    render(
      <BonusTable
        rows={[proposal({ status: "assigned", contract_ended_early: true })]}
      />,
    );
    expect(screen.getByText(/kontrakt skończył się przed terminem/)).toBeInTheDocument();
  });

  it("dzieli premie na decyzje, przyznane i liczbę anulowanych", () => {
    const parts = splitBonuses([
      proposal(),
      proposal({ id: 12, status: "assigned" }),
      proposal({ id: 13, status: "cancelled" }),
    ]);
    expect(parts.toDecide.map((b) => b.id)).toEqual([11]);
    expect(parts.assigned.map((b) => b.id)).toEqual([12]);
    expect(parts.cancelled).toBe(1);
  });

  it("przyznana premia: przełożony nie zmienia kwoty, ale może anulować swoją (decyzja 22.10.2026)", () => {
    const boss = { open: true, payroll: false, meId: 5 };
    const assignedByBoss = proposal({ status: "assigned", source: "manual", proposed_by: 5 });
    expect(assignedBonusActions(assignedByBoss, boss)).toEqual({ edit: false, cancel: true });
    expect(assignedBonusActions({ ...assignedByBoss, status: "proposed" }, boss)).toEqual({
      edit: true,
      cancel: true,
    });
    expect(assignedBonusActions({ ...assignedByBoss, proposed_by: 9 }, boss)).toEqual({
      edit: false,
      cancel: false,
    });
    expect(assignedBonusActions(assignedByBoss, { ...boss, open: false })).toEqual({
      edit: false,
      cancel: false,
    });
    const payroll = { open: true, payroll: true, meId: 2 };
    expect(assignedBonusActions({ ...assignedByBoss, proposed_by: 9 }, payroll)).toEqual({
      edit: true,
      cancel: true,
    });
    expect(assignedBonusActions({ ...assignedByBoss, recipient_user_id: 2 }, payroll)).toEqual({
      edit: false,
      cancel: false,
    });
  });

  it("sumy miesiąca tylko dla Płac", () => {
    const base = {
      stats: {
        people: 1,
        timesheets_approved: 1,
        timesheets_submitted: 0,
        timesheets_missing: 0,
        proposals: 1,
      },
    } as PayrollMonthDetail;
    expect(monthStats(base).some((s) => s.id === "totals")).toBe(false);
    expect(monthStats({ ...base, totals: { PLN: "100.00" } }).some((s) => s.id === "totals")).toBe(
      true,
    );
  });
});
