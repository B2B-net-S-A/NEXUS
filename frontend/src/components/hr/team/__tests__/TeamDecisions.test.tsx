/**
 * „Do Twojej decyzji” w „Moim zespole” (decyzja Artura 19.10.2026): akceptacja
 * wniosku i timesheetu idzie TYMI SAMYMI trasami co „Akceptacje”
 * (`useDecideLeave`, `useDecideTimesheet`), odrzucenie przez `RejectLeaveDialog`
 * z powodem; propozycja premii bez przycisków decyzji (decydują Płace).
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    post: (...args: unknown[]) => post(...args),
    get: vi.fn(),
  },
}));

import { ToastProvider } from "@/components/Toast";
import type { MyTeam, TeamPerson } from "@/lib/api/hr-team";

import { TeamDecisions } from "../TeamDecisions";

function person(extra: Partial<TeamPerson>): TeamPerson {
  return {
    user_id: 1,
    name: "Ola Przykładowa",
    job_title: null,
    employment_type: "uop",
    employment_status: "active",
    last_working_day: null,
    today: { absent: false },
    covering_for: [],
    week: null,
    leave: null,
    month: null,
    timesheet_required: true,
    bonuses: null,
    to_decide: { leave_requests: [], timesheets: [] },
    ...extra,
  };
}

const TEAM: MyTeam = {
  manager: { user_id: 99, name: "Marta Fikcyjna" },
  is_own: true,
  today: "2026-10-23",
  modules: { leave: true, time: true, payroll: true },
  sees_bonuses: true,
  month: { year: 2026, month: 10, norm_hours: 176, deadline: "2026-11-05" },
  week: null,
  people: [
    person({
      user_id: 2,
      name: "Julia Próbna",
      to_decide: {
        leave_requests: [
          {
            id: "lv-1",
            start_date: "2026-11-18",
            end_date: "2026-11-24",
            half_day: null,
            leave_type_label: "Urlop wypoczynkowy",
            days_total: "5.0",
          },
        ],
        timesheets: [],
      },
    }),
    person({
      user_id: 3,
      name: "Tomasz Podglądowy",
      month: { hours: 176, status: "submitted", timesheet_id: 77 },
      to_decide: {
        leave_requests: [],
        timesheets: [{ id: 77, year: 2026, month: 10, link: "/people/approvals?kind=timesheet" }],
      },
    }),
    person({
      user_id: 4,
      name: "Adam Wzorcowy",
      bonuses: {
        count: 1,
        proposals: 1,
        totals: [{ currency: "PLN", amount: "2000.00" }],
        items: [
          { id: 5, amount: "2000.00", currency: "PLN", category_label: "Rekruter", status: "proposed", period_year: 2026, period_month: 10, eligible_on: null, description: null },
        ],
      },
    }),
  ],
  stats: { people: 3, absent_today: 0, leave_requests: 1, timesheets: 1, bonus_proposals: 1 },
};

function renderCards() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <TeamDecisions team={TEAM} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function card(name: RegExp): HTMLElement {
  return screen.getByText(name).closest("li") as HTMLElement;
}

beforeEach(() => {
  post.mockReset();
  post.mockResolvedValue({ data: {} });
});

describe("„Do Twojej decyzji”", () => {
  it("licznik liczy wniosek i timesheet, premia jest do wiadomości bez przycisków", () => {
    renderCards();
    const heading = screen.getByRole("heading", { name: "Do Twojej decyzji" });
    expect(heading.parentElement).toHaveTextContent("2");
    const bonus = card(/Adam Wzorcowy/);
    expect(bonus).toHaveTextContent("premia · do wiadomości");
    expect(bonus).toHaveTextContent("decydują Płace");
    expect(within(bonus).queryByRole("button")).toBeNull();
  });

  it("„Akceptuj” przy wniosku woła trasę „Akceptacji”", async () => {
    const user = userEvent.setup();
    renderCards();
    await user.click(within(card(/Julia Próbna/)).getByRole("button", { name: "Akceptuj" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/leave/approvals/lv-1/approve", { note: null }),
    );
  });

  it("„Odrzuć” otwiera okno z powodem i wysyła odrzucenie dopiero z powodem", async () => {
    const user = userEvent.setup();
    renderCards();
    await user.click(within(card(/Julia Próbna/)).getByRole("button", { name: "Odrzuć" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Julia Próbna · 18–24.11.2026");
    await user.click(within(dialog).getByRole("button", { name: "Odrzuć wniosek" }));
    expect(post).not.toHaveBeenCalled();
    await user.type(within(dialog).getByLabelText(/Powód/), "Termin koliduje z wdrożeniem");
    await user.click(within(dialog).getByRole("button", { name: "Odrzuć wniosek" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/leave/approvals/lv-1/reject", {
        note: "Termin koliduje z wdrożeniem",
      }),
    );
  });

  it("timesheet: potwierdzenie, potem ta sama trasa co w „Akceptacjach”", async () => {
    const user = userEvent.setup();
    renderCards();
    const timesheet = card(/Tomasz Podglądowy/);
    expect(within(timesheet).getByRole("link", { name: "Podgląd" })).toHaveAttribute(
      "href",
      "/people/approvals?kind=timesheet",
    );
    await user.click(within(timesheet).getByRole("button", { name: "Akceptuj" }));
    const confirm = await screen.findByRole("dialog");
    expect(confirm).toHaveTextContent("176 / 176 h");
    expect(post).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole("button", { name: "Akceptuj" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/time/timesheets/77/approve", undefined),
    );
  });
});
