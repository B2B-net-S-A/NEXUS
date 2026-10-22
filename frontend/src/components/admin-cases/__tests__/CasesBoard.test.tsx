import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseCard, CaseList } from "@/lib/api/admin-cases";
import type { HrConfig } from "@/lib/api/hr";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...args: unknown[]) => mocks.apiGet(...args),
    patch: (...args: unknown[]) => mocks.apiPatch(...args),
  },
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));

import { useAuthStore, type User } from "@/store/auth";

import { CasesBoard } from "../CasesBoard";

function card(overrides: Partial<CaseCard>): CaseCard {
  return {
    id: 1,
    title: "Sprawa",
    area: "administration",
    priority: "P2",
    status: "new",
    due_on: "2026-10-20",
    follow_up_on: null,
    overdue: false,
    assignee: null,
    subject_user: null,
    contract: null,
    source: "manual",
    checklist_done: 0,
    checklist_total: 0,
    created_at: "2026-10-16T08:00:00Z",
    updated_at: "2026-10-16T08:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

function config(cases: boolean): HrConfig {
  const on = {
    people: true,
    leave: true,
    time: true,
    payroll: true,
    lifecycle: true,
    care: true,
    cases: true,
    equipment: true,
    settlements: false,
    approvals: false,
  };
  return {
    program: true,
    modules: on,
    open_modules: on,
    me: {
      has_profile: true,
      employment_status: "active",
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: false,
      payroll: false,
      equipment: false,
      cases,
    },
  };
}

function listResponse(items: CaseCard[], canManage = true): { data: CaseList } {
  return {
    data: {
      items,
      total: items.length,
      truncated: false,
      done_this_month: 41,
      can_manage: canManage,
    },
  };
}

function renderBoard(cfg: HrConfig) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CasesBoard config={cfg} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.apiGet.mockReset();
  mocks.apiPatch.mockReset();
  mocks.push.mockReset();
  useAuthStore.setState({ user: null });
});

describe("tablica spraw administracja@", () => {
  it("rozkłada sprawy po kolumnach i wyróżnia termin po czasie", async () => {
    mocks.apiGet.mockResolvedValue(
      listResponse([
        card({
          id: 1,
          title: "Onboarding: Anna Przykładowa",
          source: "mail",
          priority: "P1",
          overdue: true,
        }),
        card({ id: 2, title: "Post na LinkedIn", status: "in_progress", area: "marketing" }),
        card({
          id: 3,
          title: "Onboarding: Michał Przykładowy",
          status: "done",
          closed_at: "2026-10-04T10:00:00Z",
        }),
      ]),
    );
    renderBoard(config(true));

    expect(await screen.findByText("Onboarding: Anna Przykładowa")).toBeInTheDocument();
    expect(screen.getByText("po terminie · 20.10")).toBeInTheDocument();
    expect(screen.getByText("z maila")).toBeInTheDocument();
    expect(screen.getByText("41 spraw w miesiącu")).toBeInTheDocument();
    for (const column of ["Nowa", "W toku", "Czeka na kogoś", "Zrobione"]) {
      expect(screen.getByRole("heading", { name: column })).toBeInTheDocument();
    }
    expect(screen.queryByRole("heading", { name: "Zamknięta" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Nowa sprawa/ })).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Zakres spraw" })).toBeInTheDocument();
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/cases", { params: {} });
  });

  it("osoba przypisana bez uprawnienia widzi tylko swoje, bez zakładania spraw", async () => {
    mocks.apiGet.mockResolvedValue(listResponse([card({ id: 5, title: "Moja sprawa" })], false));
    renderBoard(config(false));

    expect(await screen.findByText("Moja sprawa")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Nowa sprawa/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Zakres spraw" })).not.toBeInTheDocument();
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/cases", { params: { mine: "true" } });
  });

  it("odmowa dostępu nie wygląda jak pusta tablica", async () => {
    mocks.apiGet.mockRejectedValue({ response: { status: 403 } });
    renderBoard(config(false));

    expect(
      await screen.findByText(
        "Sprawy widzą osoby z uprawnieniem „Sprawy” i osoby przypisane do sprawy.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Nie ma otwartych spraw.")).not.toBeInTheDocument();
  });

  it("awaria serwera nie wygląda jak pusta tablica", async () => {
    mocks.apiGet.mockRejectedValue({ response: { status: 500 } });
    renderBoard(config(true));

    expect(await screen.findByText("Nie udało się wczytać spraw.")).toBeInTheDocument();
    expect(screen.queryByText("Nie ma otwartych spraw.")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Nowa" })).not.toBeInTheDocument();
  });

  it("pusta tablica mówi, że nie ma spraw", async () => {
    mocks.apiGet.mockResolvedValue(listResponse([]));
    renderBoard(config(true));

    expect(await screen.findByText("Nie ma otwartych spraw.")).toBeInTheDocument();
  });

  it("chipy „Na ten tydzień” i „Bez osoby” filtrują po stronie serwera, z licznikami", async () => {
    const user = userEvent.setup();
    mocks.apiGet.mockResolvedValue({
      data: {
        ...listResponse([card({ id: 1, title: "Sprawa A", area: "onboarding" })]).data,
        counts: { areas: { onboarding: 2, marketing: 1 }, week: 2, unassigned: 3 },
        today: "2026-10-20",
        week_end: "2026-10-23",
      },
    });
    renderBoard(config(true));

    // Termin w tym tygodniu jest żółty z „dziś”.
    expect(await screen.findByText("dziś · 20.10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Onboarding 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Marketing 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Negocjacje/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Na ten tydzień 2" }));
    await waitFor(() =>
      expect(mocks.apiGet).toHaveBeenCalledWith("/api/cases", { params: { week: "true" } }),
    );
    await user.click(screen.getByRole("button", { name: "Bez osoby 3" }));
    await waitFor(() =>
      expect(mocks.apiGet).toHaveBeenCalledWith("/api/cases", {
        params: { week: "true", unassigned: "true" },
      }),
    );
  });

  it("„Weź” przypisuje sprawę bez osoby do czytającego, z wersją karty", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({ user: { id: 77, name: "Zofia Recepcyjna" } as unknown as User });
    mocks.apiGet.mockResolvedValue(
      listResponse([
        card({ id: 9, title: "Faktura za szkolenie BHP", updated_at: "2026-10-18T10:00:00Z" }),
        card({ id: 10, title: "Moja", assignee: { id: 77, name: "Zofia Recepcyjna" } }),
      ]),
    );
    mocks.apiPatch.mockResolvedValue({ data: {} });
    renderBoard(config(true));

    const free = await screen.findByRole("listitem", { name: "Faktura za szkolenie BHP" });
    await user.click(within(free).getByRole("button", { name: /^Weź sprawę/ }));
    await waitFor(() =>
      expect(mocks.apiPatch).toHaveBeenCalledWith("/api/cases/9", {
        assignee_user_id: 77,
        expected_updated_at: "2026-10-18T10:00:00Z",
      }),
    );
    const mine = screen.getByRole("listitem", { name: "Moja" });
    expect(within(mine).queryByRole("button", { name: /Weź/ })).toBeNull();
    expect(within(mine).getByText("ZR")).toBeInTheDocument();
  });

  it("osoba bez uprawnienia nie widzi „Weź” ani „Bez osoby”", async () => {
    useAuthStore.setState({ user: { id: 5, name: "Iga Próbna" } as unknown as User });
    mocks.apiGet.mockResolvedValue(listResponse([card({ id: 5, title: "Moja sprawa" })], false));
    renderBoard(config(false));

    expect(await screen.findByText("Moja sprawa")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Weź/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Bez osoby/ })).toBeNull();
    expect(screen.getByText("bez osoby")).toBeInTheDocument();
  });
});
