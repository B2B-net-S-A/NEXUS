import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { AbsenceBadge } from "@/components/hr/AbsenceBadge";
import type { AbsentTodayRow, LeaveBalance, LeaveRequestRow, PendingLeaveRow } from "@/lib/api/hr-leave";

import { AbsentTodayPanel } from "../AbsentTodayButton";
import { inboxItems, substituteAbsent, workSummary } from "../approvals-inbox";
import { absentRowText, balanceStats, canToggleForward } from "../leave-format";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const balance = (overrides: Partial<LeaveBalance> = {}): LeaveBalance => ({
  year: 2026,
  employment_type: "uop",
  has_pool: true,
  entitlement_days: "26.0",
  carried_over_days: "2.0",
  used_initial_days: "0.0",
  has_paid_pool: true,
  as_of: "2026-10-22",
  approved_days: "10.0",
  used_days: "8.0",
  planned_days: "2.0",
  pending_days: "5.0",
  unpaid_days: "0.0",
  remaining_days: "13.0",
  on_demand_used: "1.0",
  on_demand_limit: "4.0",
  childcare_used: "0.0",
  childcare_limit: "2.0",
  allowed_types: ["vacation"],
  ...overrides,
});

describe("saldo w „Mój czas → Urlopy”", () => {
  it("umowa o pracę z pulą: zostało, pula, wykorzystane/zaplanowane/czeka, limity Kodeksu", () => {
    const stats = balanceStats(balance());
    expect(stats.map((s) => [s.id, s.value])).toEqual([
      ["remaining", "13 dni"],
      ["pool", "28 dni"],
      ["used", "8 dni"],
      ["planned", "2 dni"],
      ["pending", "5 dni"],
      ["on-demand", "1 / 4"],
      ["childcare", "0 / 2"],
    ]);
  });

  it("B2B z umowną pulą: płatne dni bez „urlopu”, bez na żądanie i opieki", () => {
    const stats = balanceStats(
      balance({
        employment_type: "b2b",
        unpaid_days: "1.0",
        on_demand_used: null,
        on_demand_limit: null,
        childcare_used: null,
        childcare_limit: null,
      }),
    );
    expect(stats.map((s) => s.id)).toEqual(["remaining", "pool", "used", "planned", "pending", "unpaid"]);
    expect(stats.find((s) => s.id === "pool")?.label).toBe("pula z umowy");
    expect(stats.find((s) => s.id === "unpaid")?.label).toBe("bez wynagrodzenia");
    expect(stats.map((s) => String(s.label)).join(" ")).not.toMatch(/urlop/i);
  });

  it("B2B bez puli i zlecenie: same dni nieobecności, bez „zostało” i puli", () => {
    for (const form of ["b2b", "zlecenie"] as const) {
      const stats = balanceStats(
        balance({
          employment_type: form,
          has_pool: false,
          has_paid_pool: false,
          entitlement_days: null,
          remaining_days: null,
          used_days: "1.0",
          planned_days: "3.0",
          pending_days: "1.0",
          unpaid_days: "4.0",
          on_demand_used: null,
          on_demand_limit: null,
          childcare_used: null,
          childcare_limit: null,
        }),
      );
      expect(stats.map((s) => [s.id, s.value])).toEqual([
        ["used", "1 dzień"],
        ["planned", "3 dni"],
        ["pending", "1 dzień"],
      ]);
    }
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
      "/people/calendar",
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
