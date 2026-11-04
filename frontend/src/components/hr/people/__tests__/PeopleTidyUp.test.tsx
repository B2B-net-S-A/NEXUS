/**
 * „Porządki · N” (22.10.2026): jeden przycisk w nagłówku „Ludzi” zamiast
 * paska „Do wyrównania” i panelu „Do uporządkowania”. N = suma sekcji
 * „Struktura” i „Konta i kartoteki”, każda za swoją bramką; awaria odczytu =
 * bez liczby (nigdy „0”); nic do zrobienia = bez przycisku. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { hrConfig } from "@/app/preview/hr-fixtures";
import type { AccountMismatches, HrConfig, Person } from "@/lib/api/hr";
import type { HrStructure, StructurePerson } from "@/lib/api/hr-structure";

const mocks = vi.hoisted(() => ({
  responses: {} as Record<string, unknown>,
  post: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async (url: string) => {
      const value = mocks.responses[url];
      if (value instanceof Error) throw value;
      if (value === undefined) throw new Error(`nieoczekiwane ${url}`);
      return { data: value };
    }),
    post: (...args: unknown[]) => mocks.post(...args),
    put: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { PeopleTidyUp } from "../PeopleTidyUp";
import { tidyTotal } from "../tidy-up";

function structurePerson(id: number, name: string, extra: Partial<StructurePerson> = {}): StructurePerson {
  return {
    user_id: id,
    name,
    email: `osoba${id}@example.com`,
    job_title: "Konsultant",
    department: null,
    employment_type: "b2b",
    employment_status: "active",
    division: "front_office",
    manager_user_id: 1,
    manager_name: "Kamil Testowy",
    manager_state: "ok",
    reports: 0,
    leaving: null,
    m365_hint: null,
    suggested_manager: null,
    ...extra,
  };
}

/** Kamil (head) + Kacper z podpowiedzią + Ola bez pionu = 2 pozycje. */
const STRUCTURE: HrStructure = {
  people: [
    structurePerson(1, "Kamil Testowy", {
      reports: 1,
      manager_user_id: null,
      manager_name: null,
      manager_state: "none",
    }),
    structurePerson(4, "Kacper Nowicjusz", {
      manager_user_id: null,
      manager_name: null,
      manager_state: "none",
      suggested_manager: { user_id: 1, name: "Kamil Testowy" },
    }),
    structurePerson(5, "Ola Przykładowa", { division: null }),
  ],
  outside_managers: [],
  divisions: [
    { key: "front_office", label: "Front office", head_user_id: 1, head_name: "Kamil Testowy", head_active: true },
  ],
  total: 3,
  without_manager: 1,
  inactive_manager: 0,
  m365_mismatches: 0,
} as HrStructure;

const CLEAN_STRUCTURE: HrStructure = {
  ...STRUCTURE,
  people: [STRUCTURE.people[0]],
  total: 1,
};

/** Jeden rozjazd z kontem = 1 pozycja. */
const MISMATCHES: AccountMismatches = {
  items: [
    {
      user_id: 6,
      name: "Marta Fikcyjna",
      email: "marta@example.com",
      account_active: false,
      employment_status: "active",
      proposed_status: "exited",
      last_working_day: null,
      proposed_last_working_day: "2026-10-10",
      kind: "exit",
      reports: 0,
    },
  ],
  total: 1,
  pending: { employment_type: 0, manager: 0 },
};

const NO_MISMATCHES: AccountMismatches = {
  items: [],
  total: 0,
  pending: { employment_type: 0, manager: 0 },
};

const PEOPLE: { items: Person[]; total: number } = { items: [], total: 0 };

function renderTidyUp(config: HrConfig) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PeopleTidyUp config={config} />
    </QueryClientProvider>,
  );
}

const KADRY = hrConfig({ people_admin: true });
const FINANSE = hrConfig({ payroll: true });

describe("„Porządki” — liczba", () => {
  beforeEach(() => {
    mocks.post.mockReset();
    mocks.responses = {
      "/api/hr/people": PEOPLE,
      "/api/hr/structure": STRUCTURE,
      "/api/hr/people/account-mismatches": MISMATCHES,
    };
  });

  it("N = suma struktury i kont", async () => {
    renderTidyUp(KADRY);
    expect(await screen.findByRole("button", { name: "Porządki · 3" })).toBeInTheDocument();
  });

  it("kartoteka „do uzupełnienia” z katalogu liczy się w kontach", async () => {
    mocks.responses["/api/hr/people"] = {
      items: [
        {
          ...STRUCTURE.people[2],
          phone: null,
          default_location: "remote",
          scope: "full",
          employment_type: null,
          employment_type_pending: true,
          hired_on: null,
          work_start_date: null,
          last_working_day: null,
          timesheet_required: true,
          can_log_overtime: false,
        },
      ],
      total: 1,
    };
    renderTidyUp(KADRY);
    expect(await screen.findByRole("button", { name: "Porządki · 4" })).toBeInTheDocument();
  });

  it("nic do zrobienia — przycisku nie ma", async () => {
    mocks.responses["/api/hr/structure"] = CLEAN_STRUCTURE;
    mocks.responses["/api/hr/people/account-mismatches"] = NO_MISMATCHES;
    renderTidyUp(KADRY);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryByRole("button", { name: /Porządki/ })).toBeNull();
  });

  it("awaria odczytu — przycisk bez liczby, nigdy „0”", async () => {
    mocks.responses["/api/hr/structure"] = CLEAN_STRUCTURE;
    mocks.responses["/api/hr/people/account-mismatches"] = Object.assign(new Error("500"), {
      response: { status: 500 },
    });
    renderTidyUp(KADRY);
    const button = await screen.findByRole("button", { name: "Porządki" });
    expect(button).not.toHaveTextContent(/\d/);
  });

  it("Finanse: tylko konta, bez odczytu struktury", async () => {
    renderTidyUp(FINANSE);
    const button = await screen.findByRole("button", { name: "Porządki · 1" });
    await userEvent.setup().click(button);
    const panel = await screen.findByRole("dialog", { name: "Porządki" });
    expect(within(panel).queryByRole("region", { name: "Struktura" })).toBeNull();
    expect(within(panel).getByRole("region", { name: "Konta i kartoteki" })).toBeInTheDocument();
  });

  it("rekruterka bez uprawnień — bez przycisku i bez odczytów", async () => {
    renderTidyUp(hrConfig());
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryByRole("button", { name: /Porządki/ })).toBeNull();
  });

  it("tidyTotal: awaria wygrywa z liczbą, w drodze = bez przycisku", () => {
    expect(tidyTotal([{ status: "ok", count: 2 }, { status: "error" }])).toEqual({ kind: "unknown" });
    expect(tidyTotal([{ status: "ok", count: 2 }, { status: "loading" }])).toEqual({ kind: "hidden" });
    expect(tidyTotal([{ status: "ok", count: 2 }, { status: "off" }])).toEqual({ kind: "count", count: 2 });
    expect(tidyTotal([{ status: "ok", count: 0 }, { status: "ok", count: 0 }])).toEqual({ kind: "hidden" });
    expect(tidyTotal([{ status: "off" }, { status: "off" }])).toEqual({ kind: "hidden" });
  });
});

describe("„Porządki” — panel", () => {
  beforeEach(() => {
    mocks.post.mockReset();
    mocks.responses = {
      "/api/hr/people": PEOPLE,
      "/api/hr/structure": STRUCTURE,
      "/api/hr/people/account-mismatches": MISMATCHES,
    };
  });

  it("dwie sekcje; „Przyjmij” z podpowiedzi i „Wyrównaj wg konta” po potwierdzeniu", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: { changed: [4], unchanged: [] } });
    renderTidyUp(KADRY);
    await user.click(await screen.findByRole("button", { name: "Porządki · 3" }));
    const panel = await screen.findByRole("dialog", { name: "Porządki" });

    const structure = within(panel).getByRole("region", { name: "Struktura" });
    expect(within(structure).getByText(/podpowiedź: Kamil Testowy/)).toBeInTheDocument();
    expect(within(structure).getByText(/bez pionu/)).toBeInTheDocument();
    await user.click(within(structure).getByRole("button", { name: "Przyjmij: Kamil T." }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/structure/reassign", {
        user_ids: [4],
        manager_user_id: 1,
      }),
    );

    const accounts = within(panel).getByRole("region", { name: "Konta i kartoteki" });
    expect(within(accounts).getByText(/Marta Fikcyjna: konto wyłączone/)).toBeInTheDocument();
    mocks.post.mockReset();
    mocks.post.mockResolvedValue({ data: { aligned: { exit: 1, return: 0, missing: 0 } } });
    await user.click(within(accounts).getByRole("button", { name: "Wyrównaj wg konta" }));
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(await screen.findByRole("button", { name: "Wyrównaj" }));
    expect(mocks.post).toHaveBeenCalledWith("/api/hr/people/account-mismatches/align", {
      user_ids: [6],
    });
  });

  it("„Wskaż pion” z panelu otwiera okno nad panelem", async () => {
    const user = userEvent.setup();
    renderTidyUp(KADRY);
    await user.click(await screen.findByRole("button", { name: "Porządki · 3" }));
    const panel = await screen.findByRole("dialog", { name: "Porządki" });
    await user.click(within(panel).getByRole("button", { name: "Wybierz pion" }));
    expect(await screen.findByRole("dialog", { name: "Ustaw pion (1)" })).toBeInTheDocument();
  });

  it("awaria jednej sekcji nie chowa drugiej", async () => {
    const user = userEvent.setup();
    mocks.responses["/api/hr/structure"] = Object.assign(new Error("500"), {
      response: { status: 500 },
    });
    renderTidyUp(KADRY);
    await user.click(await screen.findByRole("button", { name: "Porządki" }));
    const panel = await screen.findByRole("dialog", { name: "Porządki" });
    const structure = within(panel).getByRole("region", { name: "Struktura" });
    expect(within(structure).getByRole("alert")).toBeInTheDocument();
    expect(within(structure).getByRole("button", { name: "Spróbuj ponownie" })).toBeInTheDocument();
    const accounts = within(panel).getByRole("region", { name: "Konta i kartoteki" });
    expect(within(accounts).getByText(/Marta Fikcyjna: konto wyłączone/)).toBeInTheDocument();
  });
});
