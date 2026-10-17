import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseCard, CaseList } from "@/lib/api/admin-cases";
import type { HrConfig } from "@/lib/api/hr";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));

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
  };
  return {
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
  mocks.push.mockReset();
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
    expect(screen.getByText("41 w tym miesiącu · na tablicy ostatnie 30 dni")).toBeInTheDocument();
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
});
