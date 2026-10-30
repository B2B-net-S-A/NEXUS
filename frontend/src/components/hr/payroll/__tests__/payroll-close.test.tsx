/**
 * Zamknięcie miesiąca w Płacach (makieta 19.10.2026): stepper blokuje tylko to,
 * co blokuje serwer (propozycje premii, niepotwierdzone ostrzeżenia), „Razem do
 * wypłaty” z podziałem, „Zatwierdź zaznaczone” z sumą i „Przypomnij” w wierszu.
 * Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BonusRow, CloseWarning, PayrollMonthDetail, PayrollPerson } from "@/lib/api/hr-payroll";
import { reminderToast } from "@/lib/api/hr-time";

const mocks = vi.hoisted(() => ({ post: vi.fn(), toast: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), post: mocks.post, put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.toast }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => true, confirmDialog: null }),
}));

import { DecisionPanel } from "../PayrollCloseParts";
import {
  batchSelectable,
  closeSteps,
  needsAttention,
  payoutBreakdown,
  reminderAction,
  selectionSummary,
} from "../payroll-format";

const nbsp = (text: string | null) => (text ?? "").replace(/\s/g, " ");

function person(over: Partial<PayrollPerson> = {}): PayrollPerson {
  return {
    user_id: 1,
    name: "Kamil Testowy",
    employment_type: "b2b",
    timesheet_required: true,
    timesheet_status: "approved",
    hours: "176",
    overtime_hours: "0",
    paid_leave_days: "0",
    other_leave_days: "0",
    rate_missing: false,
    lines: [{ currency: "PLN", hourly_rate: "130", hours_amount: "22880", bonus_total: "772.80", total: "23652.80" }],
    ...over,
  };
}

function bonus(over: Partial<BonusRow> = {}): BonusRow {
  return {
    id: 1,
    recipient_user_id: 10,
    recipient_name: "Julia Próbna",
    proposed_by: null,
    proposed_by_name: null,
    amount: "5000.00",
    currency: "PLN",
    category: "league",
    category_label: "Liga",
    period_year: 2026,
    period_month: 9,
    status: "proposed",
    source: "league",
    contract_id: null,
    eligible_on: null,
    eligible: true,
    description: "Liga Mistrzów Q3 · 1. miejsce",
    assigned_by: null,
    assigned_at: null,
    cancelled_at: null,
    cancel_reason: null,
    edited: false,
    can_approve: true,
    ...over,
  };
}

const WARNING: CloseWarning = {
  code: "unapproved_timesheets",
  message: "2 os. bez zatwierdzonego timesheetu — ich godziny nie wejdą do płac tego miesiąca.",
  count: 2,
  people: [],
};

function detail(over: Partial<PayrollMonthDetail> = {}): PayrollMonthDetail {
  return {
    year: 2026,
    month: 9,
    label: "wrzesień 2026",
    status: "open",
    frozen: false,
    scope: "payroll",
    closed_at: null,
    reopened_at: null,
    reopen_reason: null,
    can_close: true,
    can_reopen: false,
    stats: { people: 3, timesheets_approved: 1, timesheets_submitted: 1, timesheets_missing: 1, proposals: 2 },
    people: [
      person(),
      person({ user_id: 2, timesheet_status: "submitted" }),
      person({ user_id: 3, timesheet_status: null }),
      person({ user_id: 4, timesheet_required: false, timesheet_status: null }),
    ],
    bonuses: [bonus(), bonus({ id: 2, amount: "529.20", eligible: false, eligible_on: "2026-10-30" })],
    in_progress: [],
    totals: { PLN: "23652.80" },
    warnings: [WARNING],
    ...over,
  };
}

describe("stepper zamknięcia", () => {
  it("premie z miesiąca blokują — także ta, która jeszcze liczy się", () => {
    const { steps, ready, needsAcknowledge } = closeSteps(detail(), false);
    expect(steps.map((step) => [step.key, step.state])).toEqual([
      ["hours", "warn"],
      ["bonuses", "current"],
      ["check", "todo"],
      ["close", "todo"],
    ]);
    expect(steps[0].detail).toBe("1 z 3 zaakceptowane");
    expect(steps[0].progress).toBe(33);
    expect(nbsp(steps[1].detail)).toBe("1 do decyzji · 5000,00 zł · 1 jeszcze liczy się");
    expect(steps[2].detail).toBe("2 os. bez zatwierdzonego timesheetu");
    expect(steps[3].detail).toBe("po krokach 1–3");
    expect(ready).toBe(false);
    expect(needsAcknowledge).toBe(true);
  });

  it("premie z decyzją: Kontrola czeka na potwierdzenie, potem „Zamknij” aktywne", () => {
    const decided = detail({
      bonuses: [bonus({ status: "assigned" })],
      stats: { ...detail().stats, proposals: 0 },
    });
    const before = closeSteps(decided, false);
    expect(before.steps.map((step) => step.state)).toEqual(["warn", "done", "current", "todo"]);
    expect(before.ready).toBe(false);

    const after = closeSteps(decided, true);
    expect(after.steps.map((step) => step.state)).toEqual(["warn", "done", "done", "current"]);
    expect(after.steps[2].detail).toBe("ostrzeżenia potwierdzone");
    expect(after.steps[3].detail).toBe("gotowe do zamknięcia");
    expect(after.ready).toBe(true);
  });

  it("bez ostrzeżeń nie trzeba potwierdzać; trwający miesiąc nie da się zamknąć", () => {
    const clean = detail({
      people: [person()],
      bonuses: [],
      warnings: [],
      stats: { ...detail().stats, proposals: 0 },
    });
    expect(closeSteps(clean, false).ready).toBe(true);
    expect(closeSteps(clean, false).steps.every((step) => step.state === "done" || step.key === "close")).toBe(true);
    const running = closeSteps({ ...clean, can_close: false }, false);
    expect(running.ready).toBe(false);
    expect(running.steps[3].detail).toBe("od ostatniego dnia miesiąca");
  });

  it("zamknięty miesiąc: wszystkie kroki zrobione", () => {
    const closed = closeSteps(detail({ status: "closed", closed_at: "2026-10-03T10:00:00Z", can_close: false }), false);
    expect(closed.steps.map((step) => step.state)).toEqual(["done", "done", "done", "done"]);
    expect(closed.steps[3].detail).toBe("zamknięty 03.10");
    expect(closed.ready).toBe(false);
  });
});

describe("Razem do wypłaty", () => {
  it("godziny i premie per waluta, formy w kolejności B2B, UoP, zlecenie", () => {
    const result = payoutBreakdown([
      person({ employment_type: "zlecenie", lines: [{ currency: "PLN", hourly_rate: "60", hours_amount: "5760", bonus_total: "0", total: "5760" }] }),
      person(),
      person({ employment_type: "uop", lines: [{ currency: "PLN", hourly_rate: "95", hours_amount: "15960", bonus_total: "0", total: "15960" }] }),
      person({ employment_type: "b2b", lines: [{ currency: "EUR", hourly_rate: "30", hours_amount: "300", bonus_total: "0", total: "300" }] }),
      person({ timesheet_status: null, lines: [{ currency: "PLN", hourly_rate: "115", hours_amount: "0", bonus_total: "0", total: "0" }] }),
    ]);
    expect(result.currencies.map((c) => [c.currency, c.total, c.hours, c.bonuses])).toEqual([
      ["PLN", 45372.8, 44600, 772.8],
      ["EUR", 300, 300, 0],
    ]);
    expect(result.forms.map((f) => [f.label, f.people, f.totals])).toEqual([
      ["B2B", 2, { PLN: 23652.8, EUR: 300 }],
      ["UoP", 1, { PLN: 15960 }],
      ["Zlecenie", 1, { PLN: 5760 }],
    ]);
  });
});

describe("premie do decyzji — zaznaczanie", () => {
  it("do zbiorczego zatwierdzenia także przed terminem, z prawem, nie własne", () => {
    expect(batchSelectable(bonus(), 7)).toBe(true);
    expect(batchSelectable(bonus({ eligible: false }), 7)).toBe(true);
    expect(batchSelectable(bonus({ can_approve: false }), 7)).toBe(false);
    expect(batchSelectable(bonus({ recipient_user_id: 7 }), 7)).toBe(false);
    expect(batchSelectable(bonus({ status: "assigned" }), 7)).toBe(false);
  });

  it("suma zaznaczonych per waluta", () => {
    const rows = [bonus(), bonus({ id: 2, amount: "529.20" }), bonus({ id: 3, amount: "100", currency: "EUR" })];
    const two = selectionSummary(rows, new Set([1, 2]));
    expect([two.count, nbsp(two.label)]).toEqual([2, "5529,20 zł"]);
    expect(nbsp(selectionSummary(rows, new Set([1, 3])).label)).toBe("5000,00 zł · 100,00 EUR");
    expect(selectionSummary(rows, new Set())).toEqual({ count: 0, label: "—" });
  });
});

describe("osoby: do wyjaśnienia i przypomnienie", () => {
  it("do wyjaśnienia: raport bez akceptacji albo godziny bez stawki", () => {
    expect(needsAttention(person())).toBe(false);
    expect(needsAttention(person({ timesheet_status: "submitted" }))).toBe(true);
    expect(needsAttention(person({ timesheet_status: null }))).toBe(true);
    expect(needsAttention(person({ timesheet_required: false, timesheet_status: null }))).toBe(false);
    expect(needsAttention(person({ rate_missing: true }))).toBe(true);
  });

  it("szkic i brak → osobie; wysłany → akceptującemu, tylko Płace", () => {
    expect(reminderAction(person({ timesheet_status: null }), "payroll")).toBe("Przypomnij");
    expect(reminderAction(person({ timesheet_status: "draft" }), "team")).toBe("Przypomnij");
    expect(reminderAction(person({ timesheet_status: "submitted" }), "payroll")).toBe("Ponagl koordynatora");
    expect(reminderAction(person({ timesheet_status: "submitted", employment_type: "uop" }), "payroll")).toBe(
      "Ponagl przełożonego",
    );
    expect(reminderAction(person({ timesheet_status: "submitted" }), "team")).toBeNull();
    expect(reminderAction(person(), "payroll")).toBeNull();
    expect(reminderAction(person({ timesheet_required: false, timesheet_status: null }), "payroll")).toBeNull();
  });

  it("komunikat po przypomnieniu — drugi raz tego dnia mówi, że już poszło", () => {
    const base = { status: "missing" as const, sent: true, already_today: false };
    expect(reminderToast({ ...base, target: "person" }, "Julia Próbna")).toBe("Przypomnienie poszło do: Julia Próbna.");
    expect(reminderToast({ ...base, target: "approver" }, "Julia Próbna")).toBe(
      "Przypomnienie poszło do akceptującego — Julia Próbna.",
    );
    expect(reminderToast({ ...base, target: "person", sent: false, already_today: true }, "Julia Próbna")).toBe(
      "Julia Próbna: przypomnienie poszło już dziś.",
    );
  });
});

describe("DecisionPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  function renderPanel(rows: BonusRow[]) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const handlers = { onCreate: vi.fn(), onApprove: vi.fn(), onEdit: vi.fn(), onCancel: vi.fn() };
    render(
      <QueryClientProvider client={client}>
        <DecisionPanel rows={rows} meId={7} open canCreate approving={false} {...handlers} />
      </QueryClientProvider>,
    );
    return handlers;
  }

  it("domyślnie zaznaczone wszystko, co da się zatwierdzić; odznaczenie zmienia sumę; jedna trasa", async () => {
    mocks.post.mockResolvedValue({ data: { approved: 1, items: [] } });
    renderPanel([
      bonus(),
      bonus({ id: 2, amount: "529.20", recipient_name: "Adam Wzorcowy" }),
      bonus({ id: 3, recipient_user_id: 7, recipient_name: "Ja Sam" }),
    ]);
    const panel = screen.getByRole("region", { name: "Premie do decyzji" });
    expect(nbsp(panel.textContent)).toContain("Zaznaczono 2 · 5529,20 zł");
    // Własnej premii nie zaznaczysz.
    expect(within(panel).queryByRole("checkbox", { name: /Ja Sam/ })).toBeNull();

    fireEvent.click(within(panel).getByRole("checkbox", { name: /Adam Wzorcowy/ }));
    expect(nbsp(panel.textContent)).toContain("Zaznaczono 1 · 5000,00 zł");

    fireEvent.click(within(panel).getByRole("button", { name: "Zatwierdź zaznaczone" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/payroll/bonuses/approve-batch", { ids: [1] }),
    );
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Premia zatwierdzona", "success"));
  });

  it("„Zaznacz wszystkie” odznacza i zaznacza; bez zaznaczenia przycisk nieaktywny", () => {
    renderPanel([bonus(), bonus({ id: 2, amount: "529.20" })]);
    const panel = screen.getByRole("region", { name: "Premie do decyzji" });
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Zaznacz wszystkie" }));
    expect(nbsp(panel.textContent)).toContain("Zaznaczono 0");
    expect(within(panel).getByRole("button", { name: "Zatwierdź zaznaczone" })).toBeDisabled();
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Zaznacz wszystkie" }));
    expect(nbsp(panel.textContent)).toContain("Zaznaczono 2 · 5529,20 zł");
  });
});
