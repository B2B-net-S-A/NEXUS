import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// „Zespół” (25.10.2026): Head of Recruitment widzi, czyja lista „Moi ludzie”
// leży, i otwiera ją do podglądu — bez uśpień i dodawania.

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const http = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: http, default: http }));

import type { TeamMember } from "@/lib/api/myPeople";
import { TeamListsView, isStale, roleLabel, teamRows } from "../TeamListsView";

function member(over: Partial<TeamMember>): TeamMember {
  return {
    user_id: 1,
    name: "Anna Przykładowa",
    roles: ["recruiter"],
    total: 10,
    working: 0,
    idle: 2,
    new_matches: 3,
    jobs_with_matches: 1,
    ...over,
  };
}

const MEMBERS = [
  member({ user_id: 1, name: "Anna Przykładowa", total: 100, idle: 90 }),
  member({ user_id: 2, name: "Jan Testowy", roles: ["delivery_lead", "recruiter"], total: 40, idle: 5 }),
  member({ user_id: 3, name: "Pusta Lista", total: 0, idle: 0 }),
  member({ user_id: 7, name: "Ja Sam", roles: ["head_of_recruitment"], total: 20, idle: 15 }),
];

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => http.get.mockReset());

describe("team helpers", () => {
  it("drops me and empty lists, biggest backlog first", () => {
    expect(teamRows(MEMBERS, 7).map((m) => m.user_id)).toEqual([1, 2]);
  });

  it("names the most senior role", () => {
    expect(roleLabel(["recruiter", "delivery_lead"])).toBe("Delivery Lead");
    expect(roleLabel(["recruiter"])).toBe("Rekruter");
    expect(roleLabel([])).toBe("");
  });

  it("flags a list where most people wait", () => {
    expect(isStale({ idle: 90, total: 100 })).toBe(true);
    expect(isStale({ idle: 5, total: 40 })).toBe(false);
    expect(isStale({ idle: 0, total: 0 })).toBe(false);
  });
});

describe("TeamListsView", () => {
  it("sums who waits and names the biggest backlog", () => {
    wrap(<TeamListsView members={MEMBERS} idleDays={30} selfId={7} categories={[]} />);
    expect(screen.getByText(/95 osób czeka ponad 30 dni/)).toBeInTheDocument();
    expect(screen.getByText(/Najwięcej u: Anna Przykładowa \(90 z 100\)/)).toBeInTheDocument();
    expect(screen.queryByText("Ja Sam")).not.toBeInTheDocument();
    expect(screen.queryByText("Pusta Lista")).not.toBeInTheDocument();
  });

  it("opens a member's list read-only", async () => {
    const user = userEvent.setup();
    http.get.mockResolvedValueOnce({
      data: {
        rows: [
          {
            candidate_id: 501,
            full_name: "Piotr Próbny",
            category_id: null,
            furthest_stage: "cv_sent",
            last_sent_at: null,
            last_sent_job_title: null,
            last_sent_client_name: "Bank Przykładowy",
            sent_count: 1,
            days_since_last_send: 40,
            expected_rate_hourly: null,
            availability_status: null,
            city: null,
            source: "auto",
            active_processes: 0,
            working: false,
            snoozed: false,
            snooze_reason: null,
            snoozed_at: null,
            new_matches: 0,
          },
        ],
        total: 1,
        active_count: 1,
        working_count: 0,
        snoozed_count: 0,
        truncated: false,
      },
    });
    wrap(<TeamListsView members={MEMBERS} idleDays={30} selfId={7} categories={[]} />);
    await user.click(screen.getByRole("button", { name: /Anna Przykładowa: 100 na liście/ }));
    expect(http.get).toHaveBeenCalledWith("/api/my-people/team/1");
    expect(await screen.findByText("Piotr Próbny")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj do rekrutacji/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Uśpij/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Cały zespół/ }));
    expect(screen.getByText(/Najwięcej u/)).toBeInTheDocument();
  });

  it("says when nobody has anyone yet", () => {
    wrap(<TeamListsView members={[MEMBERS[2]]} idleDays={30} selfId={7} categories={[]} />);
    expect(screen.getByText(/Nikt w zespole nie ma jeszcze nikogo/)).toBeInTheDocument();
  });
});
