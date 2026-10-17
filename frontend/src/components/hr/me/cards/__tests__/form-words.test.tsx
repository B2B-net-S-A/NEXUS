/**
 * Karty „Przeglądu” mówią językiem umowy osoby (etap 2, D4–D5): na B2B
 * i zleceniu zgłoszenie jest „zgłoszone”, nie „zatwierdzone”, a raport godzin
 * „potwierdza” koordynator — nikt go nie „akceptuje”. Dane fikcyjne.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LeaveBalance, LeaveRequestRow } from "@/lib/api/hr-leave";
import type { MonthView } from "@/lib/api/hr-time";

const state = vi.hoisted(() => ({
  balance: null as unknown,
  requests: [] as unknown[],
  month: null as unknown,
}));

const ok = (data: unknown) => ({
  data,
  isLoading: false,
  isError: false,
  error: null,
  isSuccess: true,
  refetch: vi.fn(),
});

vi.mock("@/lib/api/hr-leave", () => ({
  useLeaveBalance: () => ok(state.balance),
  useMyLeaveRequests: () => ok(state.requests),
}));
vi.mock("@/lib/api/hr-time", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/hr-time")>("@/lib/api/hr-time");
  return { ...actual, useMyMonth: () => ok(state.month), useMyTimesheetHistory: () => ok([]) };
});
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));

import { AbsenceCard } from "../AbsenceCard";
import { MonthCard } from "../MonthCard";

function balance(over: Partial<LeaveBalance> = {}): LeaveBalance {
  return {
    year: 2026,
    employment_type: "b2b",
    has_pool: true,
    has_paid_pool: true,
    entitlement_days: "10.0",
    carried_over_days: "0.0",
    used_initial_days: "0.0",
    as_of: "2026-10-17",
    approved_days: "2.0",
    used_days: "1.0",
    planned_days: "1.0",
    pending_days: "0.0",
    unpaid_days: "0.0",
    remaining_days: "8.0",
    on_demand_used: null,
    on_demand_limit: null,
    childcare_used: null,
    childcare_limit: null,
    allowed_types: ["vacation"],
    ...over,
  };
}

function request(over: Partial<LeaveRequestRow> = {}): LeaveRequestRow {
  return {
    id: "r1",
    status: "approved",
    is_report: true,
    employment_type: "b2b",
    start_date: "2026-10-26",
    end_date: "2026-10-28",
    substitute_name: null,
    ...over,
  } as LeaveRequestRow;
}

function monthView(form: MonthView["employment_type"]): MonthView {
  return {
    employment_type: form,
    approver_name: "Marta Przykładowa",
    deadline: "2026-11-05",
    totals: {
      work_hours: 40,
      norm_hours: 176,
      days_missing: 0,
      working_days: 22,
      leave_paid_hours: 0,
      overtime_hours: 0,
      leave_days: 0,
    },
    timesheet: null,
    days: [],
  } as unknown as MonthView;
}

const text = () => (document.body.textContent ?? "").replace(/\s/g, " ");

describe("słowa formy w kartach Przeglądu", () => {
  beforeEach(() => {
    state.balance = balance();
    state.requests = [request()];
    state.month = monthView("b2b");
  });

  it("B2B z pulą: najbliższe zgłoszenie jest „zgłoszona”, nie „zatwierdzona”", () => {
    render(<AbsenceCard form="b2b" year={2026} today="2026-10-17" />);
    expect(text()).toContain("Najbliższa nieobecność: 26–28.10.2026 · zgłoszona");
    expect(text()).not.toMatch(/zatwierdzon/i);
  });

  it("B2B bez płatnej puli: bez „czeka na akceptację”, gdy nic nie czeka (D5)", () => {
    state.balance = balance({ has_paid_pool: false, entitlement_days: "0.0", remaining_days: "0.0" });
    render(<AbsenceCard form="b2b" year={2026} today="2026-10-17" />);
    expect(text()).toContain("· zgłoszona");
    expect(text()).not.toMatch(/akceptac/i);
  });

  it("umowa o pracę: zatwierdzony wniosek zostaje „zatwierdzony”", () => {
    state.balance = balance({ employment_type: "uop" });
    state.requests = [request({ is_report: false, employment_type: "uop" })];
    render(<AbsenceCard form="uop" year={2026} today="2026-10-17" />);
    expect(text()).toContain("Najbliższy urlop: 26–28.10.2026 · zatwierdzony");
  });

  it("raport godzin B2B „potwierdza” koordynator, ewidencję UoP „akceptuje” przełożony", () => {
    const { unmount } = render(
      <MonthCard form="b2b" today="2026-10-17" timesheetRequired onOpenTab={() => undefined} />,
    );
    expect(text()).toContain("potwierdza Marta P.");
    expect(text()).not.toMatch(/akceptuje/i);
    unmount();

    state.month = monthView("uop");
    render(<MonthCard form="uop" today="2026-10-17" timesheetRequired onOpenTab={() => undefined} />);
    expect(screen.getByText(/akceptuje Marta P\./)).toBeInTheDocument();
  });
});
