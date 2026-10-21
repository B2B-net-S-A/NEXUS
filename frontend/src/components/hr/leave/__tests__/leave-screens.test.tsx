import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { AbsenceBadge } from "@/components/hr/AbsenceBadge";
import type { AbsentTodayRow, LeaveRequestRow, PendingLeaveRow } from "@/lib/api/hr-leave";

import { AbsentTodayPanel } from "../AbsentTodayButton";
import { inboxItems, substituteAbsent, workSummary } from "../approvals-inbox";
import { absentRowText, canToggleForward, yearMonths } from "../leave-format";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("„Mój rok” w zakładce nieobecności (runda 2, 21.10.2026)", () => {
  const row = (id: string, start: string, end: string, status: "approved" | "pending" | "rejected" | "cancelled") => ({
    id,
    start_date: start,
    end_date: end,
    status,
    leave_type_label: "Urlop wypoczynkowy",
  });

  it("12 miesięcy; nieobecność przez przełom miesiąca w obu, odrzucone i anulowane pominięte", () => {
    const months = yearMonths(
      [
        row("a", "2026-07-28", "2026-08-04", "approved"),
        row("b", "2026-11-12", "2026-11-13", "pending"),
        row("c", "2026-12-01", "2026-12-02", "rejected"),
        row("d", "2026-12-21", "2026-12-23", "cancelled"),
      ],
      2026,
      "2026-10-21",
    );
    expect(months).toHaveLength(12);
    expect(months[6].items.map((i) => i.id)).toEqual(["a"]);
    expect(months[7].items.map((i) => i.id)).toEqual(["a"]);
    expect(months[10].items).toEqual([{ id: "b", label: "Urlop wypoczynkowy", status: "pending" }]);
    expect(months[11].items).toEqual([]);
  });

  it("miesiące przed bieżącym są przeszłe, bieżący zaznaczony", () => {
    const months = yearMonths([], 2026, "2026-10-21");
    expect(months.filter((m) => m.past).map((m) => m.month)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(months.find((m) => m.current)?.label).toBe("paź");
  });
});

const request = (overrides: Partial<LeaveRequestRow> = {}): LeaveRequestRow => ({
  id: "r1",
  user_id: 1,
  user_name: "Anna Przykładowa",
  leave_type: "vacation",
  leave_type_label: "Urlop wypoczynkowy",
  status: "approved",
  start_date: "2026-11-02",
  end_date: "2026-11-06",
  half_day: null,
  days_total: "5.0",
  paid_days: "5.0",
  unpaid_days: "0.0",
  note: null,
  substitute_user_id: 2,
  substitute_name: "Jan Testowy",
  forward_mail_consent: false,
  oof_internal_message: null,
  oof_external_message: null,
  decided_by_name: null,
  decided_at: null,
  decision_note: null,
  source: "self",
  created_at: null,
  can_cancel: true,
  ...overrides,
});

describe("przekierowanie poczty przy własnym wniosku", () => {
  it("tylko z zastępcą, przy otwartym wniosku, który jeszcze trwa", () => {
    expect(canToggleForward(request(), "2026-11-03")).toBe(true);
    expect(canToggleForward(request({ substitute_user_id: null }), "2026-11-03")).toBe(false);
    expect(canToggleForward(request({ status: "cancelled" }), "2026-11-03")).toBe(false);
    expect(canToggleForward(request(), "2026-11-07")).toBe(false);
  });
});

describe("kolejka akceptacji", () => {
  const pending = (overrides: Partial<PendingLeaveRow> = {}): PendingLeaveRow => ({
    ...request({ status: "pending" }),
    department: "Rekrutacja",
    manager_name: "Ewa Przykładowa",
    work_total: 2,
    work_by_kind: [{ kind: "client_interview", label: "Rozmowa u klienta", count: 2 }],
    department_absent: [
      { user_id: 9, name: "Jan Testowy", start_date: "2026-11-04", end_date: "2026-11-06" },
    ],
    ...overrides,
  });

  it("skrzynka mówi o pracy w tym czasie i nieobecnych z działu (kolizja)", () => {
    const { decide } = inboxItems([pending()], [], "2026-11-03");
    expect(decide[0].chips).toContainEqual({ tone: "warning", text: "kolizja: Jan 4–6.11" });
    expect(workSummary(pending())).toBe("Rozmowa u klienta: 2");
    // Zastępca Jan Testowy (id 9) też jest wtedy nieobecny.
    expect(substituteAbsent(pending({ substitute_user_id: 9 }))).toBe(true);
    expect(substituteAbsent(pending({ substitute_user_id: null }))).toBe(false);
  });

  it("zgłoszenie bez zastępcy: „bez zastępcy” w wierszu, kolizja zgłoszona jako plakietka", () => {
    const { info } = inboxItems(
      [],
      [pending({ substitute_name: null, department_absent: [], conflict: { at: null, by_name: null, note: "x" } })],
      "2026-11-03",
    );
    expect(info[0].line).toMatch(/bez zastępcy$/);
    expect(info[0].chips).toEqual([{ tone: "danger", text: "kolizja zgłoszona" }]);
  });
});

describe("„Nieobecni dziś” (D6: bez rodzaju nieobecności)", () => {
  const row = (overrides: Partial<AbsentTodayRow> = {}): AbsentTodayRow => ({
    user_id: 1,
    name: "Anna Przykładowa",
    until: "2026-10-23",
    half_day: null,
    substitute_user_id: 2,
    substitute_name: "Jan Testowy",
    substitute_absent: false,
    i_substitute: false,
    is_me: false,
    ...overrides,
  });

  it("wiersz mówi do kiedy i kto zastępuje", () => {
    expect(absentRowText(row(), "2026-10-22")).toBe(
      "Nieobecność do pt 23.10 · zastępuje Jan Testowy",
    );
    expect(absentRowText(row({ i_substitute: true }), "2026-10-22")).toBe(
      "Nieobecność do pt 23.10 · zastępujesz Ty",
    );
    expect(absentRowText(row({ substitute_name: null, until: "2026-10-22" }), "2026-10-22")).toBe(
      "Nieobecność dziś · bez zastępcy",
    );
  });

  it("okienko pokazuje osoby i ostrzeżenie o nieobecnym zastępcy", () => {
    render(
      <AbsentTodayPanel
        date="2026-10-22"
        items={[row(), row({ user_id: 3, name: "Ola Testowa", substitute_absent: true })]}
        onNavigate={() => undefined}
      />,
    );
    expect(screen.getByText("Anna Przykładowa")).toBeTruthy();
    expect(screen.getByText("zastępca nieobecny")).toBeTruthy();
    expect(screen.queryByText(/urlop|L4|zwolnienie/i)).toBeNull();
    expect(screen.getByRole("link", { name: "Kalendarz zespołu" }).getAttribute("href")).toBe(
      "/people/calendar?scope=all&status=absent",
    );
  });
});

describe("plakietka przy osobie", () => {
  it("nic nie rysuje bez nieobecności", () => {
    const { container } = render(<AbsenceBadge absence={undefined} today="2026-10-20" />);
    expect(container.innerHTML).toBe("");
  });

  it("rysuje tekst bez rodzaju nieobecności", () => {
    render(
      <AbsenceBadge
        today="2026-10-20"
        absence={{
          user_id: 1,
          until: "2026-10-24",
          half_day: null,
          substitute_user_id: 2,
          substitute_name: "Jan Testowy",
        }}
      />,
    );
    expect(screen.getByText("Nieobecność do 24.10 · zastępuje Jan T.")).toBeTruthy();
  });
});
