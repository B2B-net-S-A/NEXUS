import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HrConfig, Person } from "@/lib/api/hr";
import type { HrStructure, StructurePerson } from "@/lib/api/hr-structure";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post } }));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
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

function config(peopleAdmin: boolean, payroll = false): HrConfig {
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
      payroll,
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

function structurePerson(id: number, name: string): StructurePerson {
  return {
    user_id: id,
    name,
    email: `osoba-${id}@example.com`,
    job_title: "Konsultant",
    department: null,
    employment_type: "b2b",
    employment_status: "active",
    division: "front_office",
    manager_user_id: null,
    manager_name: null,
    manager_state: "none",
    reports: 0,
    leaving: null,
    m365_hint: null,
    suggested_manager: null,
  };
}

const STRUCTURE: HrStructure = {
  people: [structurePerson(7, "Anna Przykładowa"), structurePerson(8, "Jan Testowy"), structurePerson(9, "Ewa Fikcyjna")],
  outside_managers: [],
  divisions: [
    { key: "front_office", label: "Front office", head_user_id: 7, head_name: "Anna Przykładowa", head_active: true },
    { key: "back_office", label: "Back office", head_user_id: null, head_name: null, head_active: false },
  ],
  total: 3,
  without_manager: 2,
  inactive_manager: 0,
  m365_mismatches: 0,
} as HrStructure;

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

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
      if (url === "/api/hr/structure") return { data: STRUCTURE };
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
    expect(within(ewa).getByText(/^nieobecność do/)).toBeInTheDocument();
    expect(within(ewa).getByText("Ola P.")).toBeInTheDocument();
    const kamil = screen.getByText("Kamil Testowy").closest("tr") as HTMLElement;
    expect(within(kamil).getByText("wyjazd")).toBeInTheDocument();
    // Moduł urlopów otwarty w konfiguracji testu → reszta „w pracy”.
    const ola = screen.getByText("Ola Przykładowa", { selector: "span" }).closest("tr") as HTMLElement;
    expect(within(ola).getByText("dostępny(a)")).toBeInTheDocument();
  });

  it("sam moduł czasu: delegacja zostaje, reszta „—” i bez „Dziś nieobecni”", async () => {
    // Bez urlopów serwer nie czyta nieobecności — „w pracy” byłoby zgadywaniem
    // (audyt 21.10.2026). Wiersz Ewy niesie nieobecność tylko w atrapie.
    renderDirectory(false, { leave: false });
    await screen.findByText("Kamil Testowy");
    const kamil = screen.getByText("Kamil Testowy").closest("tr") as HTMLElement;
    expect(within(kamil).getByText("wyjazd")).toBeInTheDocument();
    const ola = screen.getByText("Ola Przykładowa", { selector: "span" }).closest("tr") as HTMLElement;
    expect(within(ola).queryByText("dostępny(a)")).toBeNull();
    expect(screen.queryByText("dostępny(a)")).toBeNull();
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

describe("PeopleDirectory — Lista | Schemat i filtry w adresie (22.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/hr/people") return { data: { items: PEOPLE, total: PEOPLE.length } };
      if (url === "/api/hr/structure") return { data: STRUCTURE };
      throw new Error(`nieoczekiwane ${url}`);
    });
  });

  it("przełącznik „Lista | Schemat” widzą tylko Kadry i admin", async () => {
    renderDirectory(true);
    await screen.findByText("Jan Testowy");
    const views = screen.getByRole("group", { name: "Widok katalogu" });
    expect(within(views).getByRole("button", { name: "Lista" })).toHaveAttribute("aria-pressed", "true");
    expect(within(views).getByRole("button", { name: "Schemat" })).toBeInTheDocument();
  });

  it("bez Kadr nie ma przełącznika, a `?view=schemat` w adresie zostaje listą", async () => {
    window.history.replaceState(null, "", "/people?view=schemat");
    renderDirectory(false);
    expect(await screen.findByText("Jan Testowy")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Widok katalogu" })).toBeNull();
    expect(screen.queryByTestId("org-card-7")).toBeNull();
    // Bez Kadr nie ma też odczytu struktury.
    expect(mocks.get).not.toHaveBeenCalledWith("/api/hr/structure");
  });

  it("admin bez Kadr też widzi schemat", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const base = config(false);
    render(
      <QueryClientProvider client={client}>
        <PeopleDirectory config={{ ...base, me: { ...base.me, is_admin: true } }} />
      </QueryClientProvider>,
    );
    await screen.findByText("Jan Testowy");
    expect(screen.getByRole("group", { name: "Widok katalogu" })).toBeInTheDocument();
  });

  it("„Schemat” pokazuje drzewo kart i zapisuje widok w adresie", async () => {
    window.history.replaceState(null, "", "/people");
    renderDirectory(true);
    await screen.findByText("Jan Testowy");
    fireEvent.click(screen.getByRole("button", { name: "Schemat" }));
    expect(await screen.findByTestId("org-card-7")).toHaveTextContent("Anna Przykładowa");
    expect(screen.getByRole("button", { name: "Headowie pionów" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(window.location.search).toBe("?view=schemat");

    fireEvent.click(screen.getByRole("button", { name: "Lista" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("filtry wracają z adresu („← Ludzie” z kartoteki)", async () => {
    window.history.replaceState(null, "", "/people?q=Jan&status=no_report");
    renderDirectory(true);
    await screen.findByText("Jan Testowy");
    expect(screen.getByLabelText("Szukaj osoby")).toHaveValue("Jan");
    expect(screen.getByRole("button", { name: /Bez raportu godzin/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByText("Anna Przykładowa")).toBeNull();
  });

  it("zmiana filtra trafia do adresu, inne parametry zostają", async () => {
    window.history.replaceState(null, "", "/people?inny=1");
    renderDirectory(true);
    await screen.findByText("Jan Testowy");
    fireEvent.change(screen.getByLabelText("Szukaj osoby"), { target: { value: "Jan" } });
    fireEvent.click(screen.getByRole("button", { name: /Bez raportu godzin/ }));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBe("Jan");
    expect(params.get("status")).toBe("no_report");
    expect(params.get("inny")).toBe("1");
  });

  it("nieznana wartość w adresie nie filtruje", async () => {
    window.history.replaceState(null, "", "/people?form=etat&status=cos");
    renderDirectory(true);
    expect(await screen.findByText("Anna Przykładowa")).toBeInTheDocument();
    expect(screen.getByText("Jan Testowy")).toBeInTheDocument();
  });

  it("Lista: zaznaczonym Kadry ustawiają pion i koordynatora (dawna lista Struktury)", async () => {
    renderDirectory(true);
    await screen.findByText("Jan Testowy");
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Anna Przykładowa" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Jan Testowy" }));
    const bar = screen.getByRole("region", { name: "Zaznaczone osoby" });
    await waitFor(() =>
      expect(within(bar).getByRole("button", { name: "Ustaw pion (2)" })).toBeInTheDocument(),
    );
    fireEvent.click(within(bar).getByRole("button", { name: "Zmień koordynatora (2)" }));
    const dialog = await screen.findByRole("dialog", { name: "Zmień koordynatora (2)" });
    expect(dialog).toHaveTextContent("Anna Przykładowa, Jan Testowy");
  });
});
