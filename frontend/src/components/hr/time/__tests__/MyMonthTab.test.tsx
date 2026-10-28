import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HrConfig } from "@/lib/api/hr";
import type { MonthDay, MonthView } from "@/lib/api/hr-time";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: mocks.get,
    post: mocks.post,
    put: mocks.put,
    patch: mocks.patch,
    delete: mocks.del,
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => true, confirmDialog: null }),
}));

import { MyMonthTab } from "../MyMonthTab";

const config: HrConfig = {
  program: true,
  modules: {
    people: true,
    leave: true,
    time: true,
    payroll: false,
    lifecycle: false,
    care: false,
    cases: false,
    equipment: false,
    settlements: false,
    approvals: false,
  },
  open_modules: {
    people: true,
    leave: true,
    time: true,
    payroll: false,
    lifecycle: false,
    care: false,
    cases: false,
    equipment: false,
    settlements: false,
    approvals: false,
  },
  me: {
    has_profile: true,
    employment_status: "active",
    is_manager: false,
    direct_reports: 0,
    is_admin: false,
    people_admin: false,
    payroll: false,
    equipment: false,
    cases: false,
  },
};

function day(date: string, weekday: number, overrides: Partial<MonthDay> = {}): MonthDay {
  return {
    date,
    weekday,
    is_weekend: weekday >= 6,
    holiday: null,
    day_off: null,
    working_day: weekday < 6,
    location: weekday < 6 ? "onsite" : null,
    location_source: weekday < 6 ? "default" : null,
    attendance_status: null,
    attendance_note: null,
    leave: null,
    entries: [],
    hours: 0,
    capacity: 8,
    overtime_hours: 0,
    ...overrides,
  };
}

function month(overrides: Partial<MonthView> = {}): MonthView {
  return {
    user_id: 1,
    name: "Anna Przykładowa",
    year: 2031,
    month: 3,
    deadline: "2031-04-05",
    employment_type: "uop",
    default_location: "onsite",
    can_log_overtime: false,
    approver_name: "Jan Przełożony",
    timesheet: null,
    days: [
      day("2031-03-03", 1, {
        hours: 8,
        entries: [
          {
            id: 11,
            work_date: "2031-03-03",
            hours: 8,
            project: "Alfa",
            description: "Sourcing: Java Developer",
            source: "manual",
            is_overtime: false,
            overtime_reason: null,
          },
        ],
      }),
      day("2031-03-04", 2, {
        location: null,
        location_source: null,
        capacity: null,
        leave: {
          status: "approved",
          fraction: 1,
          full: true,
          paid_work: false,
          paid_hours: 0,
          label: "Urlop wypoczynkowy",
        },
      }),
      day("2031-03-05", 3),
      day("2031-03-08", 6),
    ],
    totals: {
      work_hours: 8,
      leave_paid_hours: 0,
      overtime_hours: 0,
      leave_days: 1,
      working_days: 21,
      norm_hours: 168,
      days_missing: 19,
    },
    ...overrides,
  };
}

function renderTab(props: Partial<Parameters<typeof MyMonthTab>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MyMonthTab config={config} initialMonth={{ year: 2031, month: 3 }} {...props} />
    </QueryClientProvider>,
  );
}

const HISTORY = [
  { id: 31, year: 2031, month: 3, status: "draft", approved_at: null, hours: 8 },
  { id: 30, year: 2031, month: 2, status: "approved", approved_at: "2031-03-03T10:00:00Z", hours: 160 },
];

function routeGet(view: MonthView) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url === "/api/hr/time/me/2031/3") return { data: view };
    if (url === "/api/hr/time/me/templates") return { data: { items: [], role_default: null } };
    if (url === "/api/hr/time/me/history") return { data: { items: HISTORY } };
    if (url === "/api/hr/time/me/suggestion") {
      return { data: { day: "2031-03-05", counts: {}, jobs: [], client_interviews: [], text: "7 rozmów" } };
    }
    throw new Error(`nieoczekiwane ${url}`);
  });
}

describe("MyMonthTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("link z powiadomienia na otwartym ekranie przechodzi na miesiąc z adresu", async () => {
    routeGet(month());
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/hr/time/me/2031/")) return { data: month() };
      if (url === "/api/hr/time/me/templates") return { data: { items: [], role_default: null } };
      throw new Error(`nieoczekiwane ${url}`);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(
      <QueryClientProvider client={client}>
        <MyMonthTab config={config} initialMonth={{ year: 2031, month: 3 }} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/hr/time/me/2031/3"));
    view.rerender(
      <QueryClientProvider client={client}>
        <MyMonthTab config={config} initialMonth={{ year: 2031, month: 4 }} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/hr/time/me/2031/4"));
  });

  it("pokazuje dzień z wpisem, urlop tylko do odczytu i akcje szkicu", async () => {
    routeGet(month());
    renderTab();

    const first = await screen.findByTestId("day-2031-03-03");
    expect(within(first).getByText("Sourcing: Java Developer")).toBeInTheDocument();
    expect(within(first).getByText("Alfa")).toBeInTheDocument();
    const leave = screen.getByTestId("day-2031-03-04");
    expect(within(leave).getByText("Urlop wypoczynkowy")).toBeInTheDocument();
    expect(within(leave).queryByRole("button", { name: /Dodaj wpis/ })).toBeNull();
    expect(screen.getByText("szkic · wyślij do 05.04")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyślij do akceptacji" })).toBeInTheDocument();
    expect(screen.getByText("Jan Przełożony")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pobierz PDF/ })).toBeNull();
  });

  it("B2B: płatny dzień przerwy przed pierwszym zapisem wpisze się ze zgłoszenia, nie z wniosku", async () => {
    const view = month({ employment_type: "b2b" });
    view.days[1] = day("2031-03-04", 2, {
      leave: {
        status: "approved",
        fraction: 1,
        full: true,
        paid_work: true,
        paid_hours: 8,
        label: "Przerwa w świadczeniu usług",
      },
    });
    routeGet(view);
    renderTab();

    const paid = await screen.findByTestId("day-2031-03-04");
    expect(within(paid).getByText(/wpisze się ze zgłoszenia/)).toHaveTextContent(
      "Realizacja usług zgodnie z umową · wpisze się ze zgłoszenia",
    );
    expect(within(paid).queryByText(/wniosk/)).toBeNull();
  });

  it("B2B: pusty dzień wpisuje się opisem „Realizacja usług zgodnie z umową”, nie „Praca standardowa”", async () => {
    routeGet(month({ employment_type: "b2b" }));
    mocks.post.mockResolvedValue({ data: {} });
    renderTab();

    const row = await screen.findByTestId("day-2031-03-05");
    fireEvent.click(within(row).getByRole("button", { name: "Wpisz" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/hr/time/me/2031/3/entries",
        expect.objectContaining({ description: "Realizacja usług zgodnie z umową" }),
      ),
    );
  });

  it("wysłany timesheet nie ma akcji edycji, zaakceptowany ma PDF", async () => {
    const header = {
      id: 5,
      status: "approved" as const,
      submitted_at: "2031-04-01T08:00:00Z",
      return_note: null,
      returned_at: null,
      approved_at: "2031-04-02T08:00:00Z",
      approved_by_name: "Jan Przełożony",
      payroll_locked: false,
      pdf_hash: "a".repeat(64),
    };
    routeGet(month({ timesheet: header }));
    renderTab();

    expect(await screen.findByRole("button", { name: /Pobierz PDF/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyślij do akceptacji" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Dodaj wpis/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sourcing: Java Developer" })).toBeNull();
  });

  it("przełącznik Biuro/Zdalnie zapisuje wyjątek dnia", async () => {
    routeGet(month());
    mocks.put.mockResolvedValue({ data: { date: "2031-03-05", source: "exception" } });
    renderTab();

    const row = await screen.findByTestId("day-2031-03-05");
    fireEvent.click(within(row).getByRole("radio", { name: "Zdalnie" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/hr/time/me/attendance/2031-03-05", {
        status: "active",
        location: "remote",
      }),
    );
  });

  it("ponad 8 h bez prawa do nadgodzin zatrzymuje się w oknie, bez zapytania", async () => {
    routeGet(month());
    renderTab();

    const row = await screen.findByTestId("day-2031-03-05");
    fireEvent.click(within(row).getByRole("button", { name: /Dodaj wpis/ }));
    fireEvent.change(await screen.findByLabelText("Godziny"), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText("Opis"), { target: { value: "Screening" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/uprawnieniem do nadgodzin/);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("podpowiedź z pracy w NEXUSIE wstawia się dopiero po kliknięciu", async () => {
    routeGet(month());
    mocks.post.mockResolvedValue({ data: {} });
    renderTab();

    const row = await screen.findByTestId("day-2031-03-05");
    fireEvent.click(within(row).getByRole("button", { name: /Dodaj wpis/ }));
    const description = (await screen.findByLabelText("Opis")) as HTMLTextAreaElement;
    expect(description.value).toBe("");
    fireEvent.click(await screen.findByRole("button", { name: "Wstaw opis z pracy w NEXUSIE" }));
    expect(description.value).toBe("7 rozmów");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/hr/time/me/2031/3/entries",
        expect.objectContaining({ work_date: "2031-03-05", hours: 8, description: "7 rozmów" }),
      ),
    );
  });

  it("pusty dzień roboczy wpisuje się w wierszu — puste pole opisu = opis domyślny", async () => {
    routeGet(month());
    mocks.post.mockResolvedValue({ data: {} });
    renderTab();

    const row = await screen.findByTestId("day-2031-03-05");
    expect(within(row).getByLabelText("Godziny 2031-03-05")).toHaveValue("8");
    fireEvent.click(within(row).getByRole("button", { name: "Wpisz" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/hr/time/me/2031/3/entries",
        {
          work_date: "2031-03-05",
          hours: 8,
          description: "Praca standardowa",
          project: null,
        },
      ),
    );
    // Dzień z wpisem i dzień pełnego urlopu nie mają pól wpisu.
    expect(
      within(await screen.findByTestId("day-2031-03-03")).queryByRole(
        "button",
        { name: "Wpisz" },
      ),
    ).toBeNull();
    expect(
      within(screen.getByTestId("day-2031-03-04")).queryByRole("button", {
        name: "Wpisz",
      }),
    ).toBeNull();
  });

  it("wpis w wierszu ponad pojemność dnia zatrzymuje się bez zapytania", async () => {
    routeGet(month());
    renderTab();

    const row = await screen.findByTestId("day-2031-03-05");
    fireEvent.change(within(row).getByLabelText("Godziny 2031-03-05"), {
      target: { value: "9" },
    });
    fireEvent.click(within(row).getByRole("button", { name: "Wpisz" }));
    expect(await within(row).findByRole("alert")).toHaveTextContent(
      "Godziny od 0 do 8",
    );
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("tydzień ma nagłówek z sumą godzin wobec normy, a nad siatką baner braków", async () => {
    routeGet(month());
    renderTab();

    expect(await screen.findByTestId("week-2031-03-03")).toHaveTextContent(
      "Tydzień 3–8.03 · 8 / 24 h",
    );
    expect(screen.getByText("Brakuje 19 dni roboczych.")).toBeInTheDocument();
    expect(screen.getByText("8 / 168 h")).toBeInTheDocument();
  });

  it("„Wypełnij puste dni…” otwiera okno i wysyła godziny dziennie", async () => {
    routeGet(month());
    mocks.post.mockResolvedValue({
      data: {
        inserted: 19,
        skipped_existing: 1,
        skipped_leave: 1,
        working_days: 21,
        removed: 0,
        hours_per_day: 7,
        description: "Praca standardowa",
        project: null,
      },
    });
    renderTab();
    await screen.findByTestId("day-2031-03-03");
    expect(mocks.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Wypełnij puste dni…" }));
    fireEvent.change(await screen.findByLabelText("Godziny dziennie"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Wypełnij" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/time/me/2031/3/fill", {
        hours_per_day: 7,
        overwrite: false,
      }),
    );
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(
        "Wpisano 19 dni po 7 h: „Praca standardowa”.",
        "success",
      ),
    );
  });

  it("„Więcej → Szablony opisów” otwiera listę własnych szablonów", async () => {
    const user = userEvent.setup();
    routeGet(month());
    renderTab();
    await screen.findByTestId("day-2031-03-03");
    await user.click(screen.getByRole("button", { name: "Więcej" }));
    expect(await screen.findByRole("menuitem", { name: "Wypełnij miesiąc…" })).toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: "Szablony opisów" }));
    expect(await screen.findByText("Moje szablony opisów")).toBeInTheDocument();
    expect(await screen.findByText(/Nie masz jeszcze szablonów/)).toBeInTheDocument();
  });

  it("archiwum ma eksport własnych godzin do CSV", async () => {
    routeGet(month());
    renderTab();
    await screen.findByTestId("day-2031-03-03");
    fireEvent.click(screen.getByRole("button", { name: /Archiwum timesheetów/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Eksport CSV" }));
    expect(await screen.findByText("Eksport godzin do CSV")).toBeInTheDocument();
    expect((screen.getByLabelText("Od miesiąca") as HTMLInputElement).value).toBe("2031-03");
  });

  it("awaria odczytu nie udaje pustego miesiąca", async () => {
    mocks.get.mockRejectedValue({ response: { status: 500 } });
    renderTab();
    expect(await screen.findByRole("button", { name: /Spróbuj|Ponów/ })).toBeInTheDocument();
    expect(screen.queryByTestId("day-2031-03-03")).toBeNull();
  });

  it("archiwum timesheetów: pobierane po rozwinięciu, PDF tylko przy zaakceptowanym", async () => {
    routeGet(month());
    renderTab();
    await screen.findByTestId("day-2031-03-03");
    expect(mocks.get).not.toHaveBeenCalledWith("/api/hr/time/me/history");

    fireEvent.click(screen.getByRole("button", { name: /Archiwum timesheetów/ }));
    const archive = await screen.findByRole("button", { name: "Pobierz PDF luty 2031" });
    expect(archive).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pobierz PDF marzec 2031" })).toBeNull();
    expect(screen.getByText("160 h")).toBeInTheDocument();

    // Klik miesiąca z archiwum otwiera go w siatce.
    fireEvent.click(screen.getByRole("button", { name: "Luty 2031" }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/hr/time/me/2031/2"));
  });

  it("wyłączony moduł mówi o tym zamiast pytać serwer", () => {
    renderTab({
      config: { ...config, open_modules: { ...config.open_modules, time: false } },
    });
    expect(screen.getByText(/ruszy po włączeniu modułu/)).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
  });
});
