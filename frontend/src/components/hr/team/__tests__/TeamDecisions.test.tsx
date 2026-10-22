/**
 * „Do Twojej decyzji” w „Moim zespole” (decyzja Artura 19.10.2026, zwarte
 * wiersze 22.10.2026): akceptacja wniosku i timesheetu idzie TYMI SAMYMI
 * trasami co „Akceptacje” (`useDecideLeave`, `useDecideTimesheet`), odrzucenie
 * przez `RejectLeaveDialog` z powodem; propozycja premii bez przycisków
 * decyzji i bez kwoty (decydują Płace). Najwyżej trzy wiersze, reszta
 * w „Akceptacjach”.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    post: (...args: unknown[]) => post(...args),
    get: (...args: unknown[]) => get(...args),
  },
}));

import { ToastProvider } from "@/components/Toast";
import { teamKeys, useMyTeam, type MyTeam, type TeamPerson } from "@/lib/api/hr-team";

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
            created_at: "2026-10-18T09:00:00+02:00",
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

function renderCards(team: MyTeam = TEAM) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <TeamDecisions team={team} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function card(name: string): HTMLElement {
  return screen.getByText(name).closest("li") as HTMLElement;
}

beforeEach(() => {
  post.mockReset();
  post.mockResolvedValue({ data: {} });
  get.mockReset();
});

/** Zespół z jednym wnioskiem do decyzji (bez timesheetów i premii). */
function teamWithLeave(id: string, name: string): MyTeam {
  const julia = TEAM.people[0];
  return {
    ...TEAM,
    people: [
      {
        ...julia,
        name,
        to_decide: {
          leave_requests: [{ ...julia.to_decide.leave_requests[0], id }],
          timesheets: [],
        },
      },
    ],
    stats: { ...TEAM.stats, leave_requests: 1, timesheets: 0, bonus_proposals: 0 },
  };
}

const EMPTY_TEAM: MyTeam = {
  ...TEAM,
  people: [],
  stats: { people: 0, absent_today: 0, leave_requests: 0, timesheets: 0, bonus_proposals: 0 },
};

/**
 * Karty z prawdziwego zapytania „Mojego zespołu”, jak na ekranie: decyzja
 * odświeża zespół i karta znika. Druga, wolniejsza lista pod tym samym
 * kluczem (`teamKeys.managers`) sprawia, że odświeżenie zespołu kończy się
 * przed końcem mutacji — jak na produkcji, gdzie odświeża się kilka list.
 */
function LiveDecisions() {
  const team = useMyTeam(null);
  useQuery({ queryKey: teamKeys.managers, queryFn: () => get("managers") });
  return team.data ? <TeamDecisions team={team.data} /> : null;
}

function renderLive(server: { team: MyTeam }) {
  let managerCalls = 0;
  get.mockImplementation((url: string) => {
    if (url === "managers") {
      managerCalls += 1;
      return managerCalls === 1
        ? Promise.resolve([])
        : new Promise((resolve) => setTimeout(() => resolve([]), 100));
    }
    return Promise.resolve({ data: server.team });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <LiveDecisions />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return client;
}

describe("„Do Twojej decyzji”", () => {
  it("licznik liczy wniosek i timesheet, premia jest do wiadomości bez przycisków i kwoty", () => {
    renderCards();
    const heading = screen.getByRole("heading", { name: "Do Twojej decyzji" });
    expect(heading.parentElement).toHaveTextContent("Do Twojej decyzji· 2");
    const bonus = card("Adam Wzorcowy");
    expect(bonus).toHaveTextContent("do wiadomości");
    expect(bonus).toHaveTextContent("wynagrodzenie dodatkowe · 1 propozycja — decydują Płace");
    expect(bonus).not.toHaveTextContent(/2[\s\u00a0]?000/);
    expect(within(bonus).queryByRole("button")).toBeNull();
  });

  it("wiersze: znacznik rodzaju, imię, podsumowanie, wiek i link do „Akceptacji”", () => {
    renderCards();
    const section = screen.getByRole("region", { name: "Do Twojej decyzji" });
    expect(within(section).getByRole("link", { name: "Wszystkie w Akceptacjach →" })).toHaveAttribute(
      "href",
      "/people/approvals",
    );
    const leave = card("Julia Próbna");
    expect(leave).toHaveTextContent("nieobecność");
    expect(leave).toHaveTextContent("18–24.11.2026 · 5 dni");
    expect(leave).toHaveTextContent("czeka 5 dni");
    // Imię wniosku prowadzi do szczegółów w „Akceptacjach”.
    expect(within(leave).getByRole("link", { name: "Julia Próbna" })).toHaveAttribute(
      "href",
      "/people/approvals",
    );
    expect(within(leave).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Odrzuć",
      "Akceptuj",
    ]);
    const timesheet = card("Tomasz Podglądowy");
    expect(timesheet).toHaveTextContent("raport godzin");
    expect(timesheet).toHaveTextContent("październik 2026 · 176 / 176 h");
  });

  it("najwyżej trzy wiersze; reszta jako link do „Akceptacji”", () => {
    const many: MyTeam = {
      ...TEAM,
      people: [1, 2, 3, 4, 5].map((n) =>
        person({
          user_id: 10 + n,
          name: `Osoba Testowa ${n}`,
          to_decide: {
            leave_requests: [
              {
                id: `lv-${n}`,
                start_date: "2026-11-02",
                end_date: "2026-11-03",
                half_day: null,
                leave_type_label: "Urlop wypoczynkowy",
                days_total: "2.0",
              },
            ],
            timesheets: [],
          },
        }),
      ),
    };
    renderCards(many);
    const section = screen.getByRole("region", { name: "Do Twojej decyzji" });
    expect(within(section).getAllByRole("listitem")).toHaveLength(3);
    expect(section).toHaveTextContent("Do Twojej decyzji· 5");
    expect(within(section).getByRole("link", { name: "i jeszcze 2 — w Akceptacjach" })).toHaveAttribute(
      "href",
      "/people/approvals",
    );
  });

  it("„Akceptuj” przy wniosku woła trasę „Akceptacji”", async () => {
    const user = userEvent.setup();
    renderCards();
    await user.click(within(card("Julia Próbna")).getByRole("button", { name: "Akceptuj" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/leave/approvals/lv-1/approve", { note: null }),
    );
  });

  it("„Odrzuć” otwiera okno z powodem i wysyła odrzucenie dopiero z powodem", async () => {
    const user = userEvent.setup();
    renderCards();
    await user.click(within(card("Julia Próbna")).getByRole("button", { name: "Odrzuć" }));
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
    const timesheet = card("Tomasz Podglądowy");
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

  it("odrzucenie ostatniej sprawy: toast „Wniosek odrzucony”, choć sekcja znika", async () => {
    // Bez kart sekcja zwraca `null` przed oknem — okno się odmontowuje, a
    // callback `mutate()` z okna przepadał (audyt 21.10.2026).
    const user = userEvent.setup();
    const server = { team: teamWithLeave("lv-1", "Julia Próbna") };
    post.mockImplementation(async () => {
      server.team = EMPTY_TEAM;
      return { data: {} };
    });
    renderLive(server);
    await user.click(
      within(await screen.findByText("Julia Próbna").then((el) => el.closest("li")!)).getByRole(
        "button",
        { name: "Odrzuć" },
      ),
    );
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Powód/), "Termin koliduje z wdrożeniem");
    await user.click(within(dialog).getByRole("button", { name: "Odrzuć wniosek" }));

    expect(await screen.findByText("Wniosek odrzucony")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Do Twojej decyzji" })).toBeNull();
  });

  it("akceptacja ostatniej sprawy: toast z `mutateAsync`, choć wiersz znika", async () => {
    const user = userEvent.setup();
    const server = { team: teamWithLeave("lv-1", "Julia Próbna") };
    post.mockImplementation(async () => {
      server.team = EMPTY_TEAM;
      return { data: { payroll_warning: null } };
    });
    renderLive(server);
    await user.click(
      within(await screen.findByText("Julia Próbna").then((el) => el.closest("li")!)).getByRole(
        "button",
        { name: "Akceptuj" },
      ),
    );
    expect(await screen.findByText("Wniosek zaakceptowany")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Do Twojej decyzji" })).toBeNull(),
    );
  });

  it("sprawa znika przy otwartym oknie: nowa karta nie otwiera okna sama", async () => {
    const user = userEvent.setup();
    const server = { team: teamWithLeave("lv-1", "Julia Próbna") };
    const client = renderLive(server);
    await user.click(
      within(await screen.findByText("Julia Próbna").then((el) => el.closest("li")!)).getByRole(
        "button",
        { name: "Odrzuć" },
      ),
    );
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    // Ktoś inny zdecydował — karty nie ma.
    server.team = EMPTY_TEAM;
    await client.invalidateQueries({ queryKey: teamKeys.team(null) });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    // Nowy wniosek innej osoby — okno odrzucenia nie wraca samo.
    server.team = teamWithLeave("lv-2", "Kamil Testowy");
    await client.invalidateQueries({ queryKey: teamKeys.team(null) });
    expect(await screen.findByText("Kamil Testowy")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(post).not.toHaveBeenCalled();
  });
});
