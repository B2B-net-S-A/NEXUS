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
  leave: false,
  time: true,
  payroll: false,
  lifecycle: false,
  care: false,
  cases: false,
  equipment: false,
  settlements: false,
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

function renderDirectory(peopleAdmin = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PeopleDirectory config={config(peopleAdmin)} />
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
    expect(within(row as HTMLElement).getByText("nie składa")).toBeInTheDocument();
    expect(screen.getByText("bez raportu godzin")).toBeInTheDocument();

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
    expect(screen.queryByText("Raport godzin")).toBeNull();
  });
});
