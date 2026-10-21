import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HrConfig, Person } from "@/lib/api/hr";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post } }));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));

import { PeopleDirectory, timesheetRequired } from "../PeopleDirectory";

const MODULES = {
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
};

function config(peopleAdmin: boolean): HrConfig {
  return {
    program: true,
    modules: MODULES,
    open_modules: MODULES,
    me: {
      has_profile: true,
      employment_status: "active",
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: peopleAdmin,
      payroll: false,
      equipment: false,
      cases: false,
    },
  };
}

function person(userId: number, name: string, required: boolean): Person {
  return {
    user_id: userId,
    name,
    email: `osoba-${userId}@example.com`,
    job_title: "Konsultant",
    department: null,
    phone: null,
    default_location: "remote",
    employment_status: "active",
    manager_user_id: null,
    manager_name: null,
    scope: "full",
    employment_type: "b2b",
    hired_on: null,
    work_start_date: null,
    last_working_day: null,
    timesheet_required: required,
    can_log_overtime: false,
    roles: ["employee"],
  };
}

const PEOPLE = [
  person(7, "Anna Przykładowa", true),
  person(8, "Jan Testowy", false),
  person(9, "Ewa Fikcyjna", true),
];

function renderDirectory(peopleAdmin = true, modules: Partial<typeof MODULES> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const base = config(peopleAdmin);
  const open = { ...MODULES, ...modules };
  render(
    <QueryClientProvider client={client}>
      <PeopleDirectory config={{ ...base, modules: open, open_modules: open }} />
    </QueryClientProvider>,
  );
}

describe("PeopleDirectory — „Składa raport godzin”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/hr/people") return { data: { items: PEOPLE, total: PEOPLE.length } };
      throw new Error(`nieoczekiwane ${url}`);
    });
    mocks.post.mockResolvedValue({ data: { changed: [7, 9], unchanged: [] } });
  });

  it("flaga tylko z pełnego zakresu", () => {
    expect(timesheetRequired(PEOPLE[1])).toBe(false);
    const card = { ...PEOPLE[0], scope: "card" as const };
    expect(timesheetRequired(card)).toBeNull();
  });

  it("Kadry zaznaczają osoby i ustawiają „nie” hurtem", async () => {
    renderDirectory();
    const row = (await screen.findByText("Jan Testowy")).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("nie składa raportu godzin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Bez raportu godzin/ })).toHaveTextContent("1");

    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Anna Przykładowa" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Ewa Fikcyjna" }));
    const bar = screen.getByRole("region", { name: "Zaznaczone osoby" });
    expect(bar).toHaveTextContent("Zaznaczono: 2 osoby");
    fireEvent.click(within(bar).getByRole("button", { name: "Nie" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/admin/profiles/timesheet-required", {
        user_ids: [7, 9],
        required: false,
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Zaznaczone osoby" })).toBeNull(),
    );
    expect(mocks.toast).toHaveBeenCalledWith("Nie składa raportu godzin: 2 osoby.", "success");
  });

  it("„zaznacz wszystkich” bierze widoczne po filtrze", async () => {
    renderDirectory();
    await screen.findByText("Jan Testowy");
    fireEvent.change(screen.getByLabelText("Szukaj osoby"), { target: { value: "Jan" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz wszystkich widocznych" }));
    fireEvent.click(screen.getByRole("button", { name: "Tak" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/admin/profiles/timesheet-required", {
        user_ids: [8],
        required: true,
      }),
    );
  });

  it("bez uprawnienia Kadr nie ma zaznaczania ani kolumny", async () => {
    renderDirectory(false);
    await screen.findByText("Jan Testowy");
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByText("nie składa raportu godzin")).toBeNull();
  });
});

describe("PeopleDirectory — makieta 19.10.2026", () => {
  const GROUPED: Person[] = [
    { ...person(1, "Ola Przykładowa", true), department: "Rekrutacja IT" },
    {
      ...person(2, "Ewa Makietowa", true),
      department: "Rekrutacja IT",
      manager_user_id: 1,
      manager_name: "Ola Przykładowa",
      today: { absent_until: "2099-10-21", half_day: null, substitute_name: null, presence: null },
    },
    {
      ...person(3, "Kamil Testowy", true),
      department: "Delivery",
      employment_type: "uop",
      today: { absent_until: null, half_day: null, substitute_name: null, presence: "business_trip" },
    },
    {
      ...person(4, "Adam Wzorcowy", true),
      department: null,
      scope: "card",
    } as Person,
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/hr/people") return { data: { items: GROUPED, total: GROUPED.length } };
      throw new Error(`nieoczekiwane ${url}`);
    });
  });

  it("grupy po dziale, chipy z licznikami i kolumna „Dziś”", async () => {
    renderDirectory(false);
    await screen.findByText("Ewa Makietowa");
    const filters = screen.getByRole("group", { name: "Filtry katalogu" });
    expect(within(filters).getByRole("button", { name: /Rekrutacja IT/ })).toHaveTextContent("2");
    expect(within(filters).getByRole("button", { name: /Delivery/ })).toHaveTextContent("1");
    expect(within(filters).getByRole("button", { name: /Bez działu/ })).toHaveTextContent("1");
    // Forma tylko z pełnej kartoteki (wizytówka bez pigułki).
    expect(within(filters).getByRole("button", { name: /B2B/ })).toHaveTextContent("2");
    expect(within(filters).getByRole("button", { name: /UoP/ })).toHaveTextContent("1");

    const ewa = screen.getByText("Ewa Makietowa").closest("tr") as HTMLElement;
    expect(within(ewa).getByText(/^przerwa do/)).toBeInTheDocument();
    expect(within(ewa).getByText("Ola P.")).toBeInTheDocument();
    const kamil = screen.getByText("Kamil Testowy").closest("tr") as HTMLElement;
    expect(within(kamil).getByText("delegacja")).toBeInTheDocument();
    // Moduł urlopów otwarty w konfiguracji testu → reszta „w pracy”.
    const ola = screen.getByText("Ola Przykładowa", { selector: "span" }).closest("tr") as HTMLElement;
    expect(within(ola).getByText("w pracy")).toBeInTheDocument();
  });

  it("sam moduł czasu: delegacja zostaje, reszta „—” i bez „Dziś nieobecni”", async () => {
    // Bez urlopów serwer nie czyta nieobecności — „w pracy” byłoby zgadywaniem
    // (audyt 21.10.2026). Wiersz Ewy niesie nieobecność tylko w atrapie.
    renderDirectory(false, { leave: false });
    await screen.findByText("Kamil Testowy");
    const kamil = screen.getByText("Kamil Testowy").closest("tr") as HTMLElement;
    expect(within(kamil).getByText("delegacja")).toBeInTheDocument();
    const ola = screen.getByText("Ola Przykładowa", { selector: "span" }).closest("tr") as HTMLElement;
    expect(within(ola).queryByText("w pracy")).toBeNull();
    expect(screen.queryByText("w pracy")).toBeNull();
    const filters = screen.getByRole("group", { name: "Filtry katalogu" });
    expect(within(filters).queryByRole("button", { name: /Dziś nieobecni/ })).toBeNull();
  });

  it("chip działu i „Dziś nieobecni” filtrują listę", async () => {
    renderDirectory(false);
    await screen.findByText("Ewa Makietowa");
    const filters = screen.getByRole("group", { name: "Filtry katalogu" });
    fireEvent.click(within(filters).getByRole("button", { name: /Delivery/ }));
    expect(screen.queryByText("Ewa Makietowa")).toBeNull();
    expect(screen.getByText("Kamil Testowy")).toBeInTheDocument();
    fireEvent.click(within(filters).getByRole("button", { name: /Wszyscy/ }));
    fireEvent.click(within(filters).getByRole("button", { name: /Dziś nieobecni/ }));
    expect(screen.getByText("Ewa Makietowa")).toBeInTheDocument();
    expect(screen.getByText("Kamil Testowy")).toBeInTheDocument();
    expect(screen.queryByText("Adam Wzorcowy")).toBeNull();
  });
});
