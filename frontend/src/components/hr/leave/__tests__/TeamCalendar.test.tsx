/**
 * „Ludzie → Kalendarz” — filtry jak w Katalogu (22.10.2026): koordynator
 * otwiera „Mój zespół”, reszta „Wszyscy”; chipy działów i „Dziś nieobecni” /
 * „Zdalnie dziś” filtrują, a stan wraca z adresu. Rodzaj nieobecności tylko
 * z serwera (D6) — ekran nie dopowiada go sam.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...args: unknown[]) => get(...args) },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { harnessMonthDays, hrConfig } from "@/app/preview/hr-fixtures";
import type { TeamCalendar as TeamCalendarData, TeamCalendarPerson } from "@/lib/api/hr-leave";
import { warsawToday } from "@/lib/warsaw-date";

import { TeamCalendar } from "../TeamCalendar";

vi.setConfig({ testTimeout: 20_000 });

const TODAY = warsawToday();
const MONTH = TODAY.slice(0, 7);

function person(
  id: number,
  name: string,
  department: string,
  extra: Partial<TeamCalendarPerson> = {},
): TeamCalendarPerson {
  return {
    user_id: id,
    name,
    department,
    job_title: null,
    is_me: false,
    type_visible: false,
    absences: [],
    presence: [],
    ...extra,
  };
}

/** Ewa (zespół) nieobecna dziś, Tomasz (zespół) zdalnie dziś, Kamil spoza zespołu. */
function people(typeVisible: boolean): TeamCalendarPerson[] {
  return [
    person(1, "Ewa Makietowa", "Rekrutacja", {
      job_title: "Rekruterka",
      type_visible: typeVisible,
      absences: [
        {
          id: typeVisible ? "a-1" : null,
          start_date: TODAY,
          end_date: TODAY,
          half_day: null,
          status: "approved",
          label: typeVisible ? "Zwolnienie lekarskie" : "Nieobecność",
          leave_type: typeVisible ? "sick_leave" : null,
          substitute_user_id: null,
          substitute_name: null,
        },
      ],
    }),
    person(2, "Kamil Testowy", "Delivery", { job_title: "Delivery Lead" }),
    person(3, "Tomasz Podglądowy", "Delivery", {
      job_title: "Tester",
      presence: [{ date: TODAY, kind: "remote" }],
    }),
  ];
}

const TEAM_IDS = new Set([1, 3]);

function calendar(month: string, team: boolean, typeVisible: boolean): TeamCalendarData {
  return {
    month,
    today: TODAY,
    days: harnessMonthDays(month),
    departments: ["Delivery", "Rekrutacja"],
    presence_shown: true,
    people: people(typeVisible).filter((p) => !team || TEAM_IDS.has(p.user_id)),
  };
}

function serve(typeVisible = false) {
  get.mockImplementation((_url: string, config: { params: { month: string; team?: boolean } }) =>
    Promise.resolve({
      data: calendar(config.params.month, Boolean(config.params.team), typeVisible),
    }),
  );
}

function renderCalendar(isManager: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TeamCalendar
        config={hrConfig(isManager ? { is_manager: true, direct_reports: 2 } : {})}
      />
    </QueryClientProvider>,
  );
}

const chip = (name: RegExp) => screen.getByRole("button", { name });
const rowNames = () =>
  within(screen.getByRole("table", { name: "Nieobecności zespołu" }))
    .getAllByRole("rowheader")
    // Wiersz osoby: inicjały + imię; wiersz „Nieobecnych” bez inicjałów.
    .map((row) => row.querySelector("span:last-child")?.textContent ?? row.textContent);

beforeEach(() => {
  get.mockReset();
  window.history.replaceState(null, "", "/people/calendar");
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("Kalendarz — chipy zakresu", () => {
  it("koordynator: domyślnie „Mój zespół” z licznikiem, „Wszyscy” obok", async () => {
    serve();
    renderCalendar(true);
    await screen.findByRole("table", { name: "Nieobecności zespołu" });
    expect(chip(/^Mój zespół/)).toHaveAttribute("aria-pressed", "true");
    expect(chip(/^Mój zespół/)).toHaveTextContent("Mój zespół2");
    expect(chip(/^Wszyscy/)).toHaveAttribute("aria-pressed", "false");
    expect(chip(/^Wszyscy/)).toHaveTextContent("Wszyscy3");
    expect(rowNames()).toEqual(["Ewa Makietowa", "Tomasz Podglądowy", "Nieobecnych"]);
    // Domyślny widok nie dopisuje niczego do adresu.
    expect(window.location.search).toBe("");

    await userEvent.setup().click(chip(/^Wszyscy/));
    expect(rowNames()).toContain("Kamil Testowy");
    expect(window.location.search).toBe("?scope=all");
  });

  it("bez zespołu: bez chipa „Mój zespół”, domyślnie „Wszyscy”, bez zapytania o zespół", async () => {
    serve();
    renderCalendar(false);
    await screen.findByRole("table", { name: "Nieobecności zespołu" });
    expect(screen.queryByRole("button", { name: /^Mój zespół/ })).toBeNull();
    expect(chip(/^Wszyscy/)).toHaveAttribute("aria-pressed", "true");
    expect(rowNames()).toEqual([
      "Ewa Makietowa",
      "Kamil Testowy",
      "Tomasz Podglądowy",
      "Nieobecnych",
    ]);
    expect(get.mock.calls.some(([, config]) => config.params.team)).toBe(false);
  });

  it("chip działu filtruje na danych „Wszyscy” i trafia do adresu", async () => {
    const user = userEvent.setup();
    serve();
    renderCalendar(false);
    await screen.findByRole("table", { name: "Nieobecności zespołu" });
    expect(chip(/^Delivery/)).toHaveTextContent("Delivery2");
    await user.click(chip(/^Delivery/));
    expect(rowNames()).toEqual(["Kamil Testowy", "Tomasz Podglądowy", "Nieobecnych"]);
    expect(window.location.search).toBe("?dept=Delivery");
    // Ponowny klik zdejmuje dział.
    await user.click(chip(/^Delivery/));
    expect(chip(/^Wszyscy/)).toHaveAttribute("aria-pressed", "true");
    expect(window.location.search).toBe("");
  });
});

describe("Kalendarz — chipy stanu i szukanie", () => {
  it("„Dziś nieobecni” zostawia tylko nieobecnych dziś; drugi klik zdejmuje filtr", async () => {
    const user = userEvent.setup();
    serve();
    renderCalendar(false);
    await screen.findByRole("table", { name: "Nieobecności zespołu" });
    expect(chip(/^Dziś nieobecni/)).toHaveTextContent("Dziś nieobecni1");
    expect(chip(/^Zdalnie dziś/)).toHaveTextContent("Zdalnie dziś1");
    await user.click(chip(/^Dziś nieobecni/));
    expect(rowNames()).toEqual(["Ewa Makietowa", "Nieobecnych"]);
    expect(window.location.search).toBe("?status=absent");
    await user.click(chip(/^Dziś nieobecni/));
    expect(rowNames()).toHaveLength(4);
  });

  it("szukanie po stanowisku zmienia też liczniki chipów", async () => {
    const user = userEvent.setup();
    serve();
    renderCalendar(false);
    await screen.findByRole("table", { name: "Nieobecności zespołu" });
    await user.type(screen.getByRole("searchbox", { name: "Znajdź osobę w kalendarzu" }), "tester");
    expect(rowNames()).toEqual(["Tomasz Podglądowy", "Nieobecnych"]);
    expect(chip(/^Wszyscy/)).toHaveTextContent("Wszyscy1");
    expect(window.location.search).toBe("?q=tester");
  });
});

describe("Kalendarz — stan z adresu", () => {
  it("dział, stan, szukanie i widok 2 tygodni wracają z adresu", async () => {
    serve();
    window.history.replaceState(
      null,
      "",
      "/people/calendar?dept=Delivery&status=remote&view=two_weeks&q=tom",
    );
    renderCalendar(true);
    await screen.findByRole("table", { name: "Nieobecności zespołu" });
    expect(chip(/^Delivery/)).toHaveAttribute("aria-pressed", "true");
    expect(chip(/^Mój zespół/)).toHaveAttribute("aria-pressed", "false");
    expect(chip(/^Zdalnie dziś/)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "2 tygodnie" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("searchbox", { name: "Znajdź osobę w kalendarzu" })).toHaveValue("tom");
    expect(rowNames()).toEqual(["Tomasz Podglądowy", "Nieobecnych"]);
  });

  it("link z „Nieobecni dziś”: koordynator widzi wszystkich nieobecnych dziś", async () => {
    serve();
    window.history.replaceState(null, "", "/people/calendar?scope=all&status=absent");
    renderCalendar(true);
    await screen.findByRole("table", { name: "Nieobecności zespołu" });
    expect(chip(/^Wszyscy/)).toHaveAttribute("aria-pressed", "true");
    expect(chip(/^Dziś nieobecni/)).toHaveAttribute("aria-pressed", "true");
    expect(rowNames()).toEqual(["Ewa Makietowa", "Nieobecnych"]);
  });

  it("miesiąc z adresu: kalendarz pyta o ten miesiąc", async () => {
    serve();
    window.history.replaceState(null, "", "/people/calendar?month=2091-03");
    renderCalendar(false);
    await waitFor(() =>
      expect(get.mock.calls.map(([, config]) => config.params.month)).toContain("2091-03"),
    );
    expect(get.mock.calls.map(([, config]) => config.params.month)).not.toContain(MONTH);
  });
});

describe("Kalendarz — D6", () => {
  it("bez rodzaju z serwera ekran mówi „Nieobecność” i pokazuje, kto widzi rodzaj", async () => {
    const user = userEvent.setup();
    serve(false);
    renderCalendar(false);
    await screen.findByRole("table", { name: "Nieobecności zespołu" });
    const bar = screen.getByRole("button", { name: /^Ewa Makietowa: Nieobecność/ });
    expect(screen.queryByText(/zwolnienie|urlop|L4/i)).toBeNull();
    await user.click(bar);
    expect(
      screen.getByText(
        "Rodzaj nieobecności widzą tylko ta osoba, jej przełożony albo koordynator i Kadry.",
      ),
    ).toBeInTheDocument();
  });

  it("rodzaj, gdy serwer go wysłał (krąg D6)", async () => {
    serve(true);
    renderCalendar(true);
    expect(
      await screen.findByRole("button", { name: /^Ewa Makietowa: Zwolnienie lekarskie/ }),
    ).toBeInTheDocument();
  });
});
