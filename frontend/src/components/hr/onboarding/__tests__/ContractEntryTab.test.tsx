/**
 * Zakładka „Wejście” kontraktu (etap 3, M6): jedna lista ze ścieżki, pakietu
 * i formy; odhacza ten, komu pozwala serwer; zestaw sprzętu prowadzi Sprzęt;
 * wyłączony moduł = stara lista onboardingu; awaria ≠ pusta lista.
 * Dane fikcyjne.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ContractEntryView, LifecycleTask } from "@/lib/api/hr-lifecycle";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    patch: (...a: unknown[]) => mocks.patch(...a),
    put: vi.fn(),
    delete: vi.fn(),
  };
  return { api: client, default: client };
});
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.toast }) }));
vi.mock("../WelcomeMailCard", () => ({
  WelcomeMailCard: ({ contractId }: { contractId: number }) => (
    <div>Mail powitalny {contractId}</div>
  ),
}));

import { ContractEntryTab } from "../ContractEntryTab";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

function task(patch: Partial<LifecycleTask>): LifecycleTask {
  return {
    id: 1,
    title: "Zadanie",
    category: "other",
    assignee_kind: "care_owner",
    assignee_user_id: 5,
    assignee_name: "Zofia Opiekuńska",
    due_date: "2026-11-02",
    status: "open",
    overdue: false,
    done_at: null,
    done_by_name: null,
    note: null,
    source: "path",
    source_label: null,
    from_template: true,
    can_toggle: true,
    ...patch,
  };
}

function view(patch: Partial<ContractEntryView> = {}): ContractEntryView {
  return {
    contract_id: 7,
    module_on: true,
    start_date: "2026-11-03",
    case: {
      id: 90,
      kind: "onboarding",
      status: "active",
      user_id: null,
      person_name: "Marek Nowy",
      pending_email: null,
      template_id: 3,
      template_name: "Konsultant u klienta",
      audience: "consultant",
      contract_id: 7,
      template_version: 4,
      template_current_version: 5,
      start_date: "2026-11-03",
      last_working_day: null,
      deactivate_on: null,
      handover_at: null,
      manager_user_id: null,
      manager_name: null,
      owner_name: null,
      started_at: null,
      handover_executed_at: null,
      account_closed_at: null,
      account_close_result: null,
      completed_at: null,
      cancelled_at: null,
      scope: "manager",
      can_manage: false,
      can_cancel: false,
      can_add_task: true,
      tasks: [
        task({
          id: 11,
          title: "Umowa podpisana, dane do faktur",
          assignee_kind: "administration",
          assignee_name: null,
          source: "form",
          source_label: "B2B",
          due_date: "2026-10-23",
          status: "done",
          can_toggle: false,
        }),
        task({
          id: 12,
          title: "Przygotuj zestaw sprzętu",
          assignee_kind: "reception",
          assignee_name: null,
          description: "Od nas: laptop 14 cali, słuchawki.",
          mirror: { module: "equipment", task_id: 3, status: "open", note: "Odhacza recepcja w Sprzęcie." },
          can_toggle: false,
        }),
        task({
          id: 13,
          title: "Zaświadczenie o niekaralności",
          source: "client",
          source_label: "Nordline Bank",
          requires_file: true,
        }),
        task({ id: 14, title: "Rozmowa po pierwszym dniu", due_date: "2026-11-04" }),
      ],
      progress: { done: 1, total: 4, overdue: 0 },
    },
    composition: {
      client_id: 2,
      client_name: "Nordline Bank",
      employment_type: "b2b",
      employment_label: "B2B",
      equipment: "ours",
      care_owner: { id: 5, name: "Zofia Opiekuńska", source: "contract" },
      delivery_lead: { id: 6, name: "Kamil Przykładowy" },
      client_manager: "Piotr Przykładowy",
    },
    missing_reason: null,
    can_create: false,
    can_add_task: true,
    legacy_items: 0,
    ...patch,
  };
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <ContractEntryTab contractId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
});

describe("ContractEntryTab", () => {
  it("pokazuje kroki, źródła i kartę „Z czego to powstało”", async () => {
    mocks.get.mockResolvedValue({ data: view() });
    renderTab();
    expect(await screen.findByText("Przygotuj zestaw sprzętu")).toBeInTheDocument();
    const steps = screen.getByRole("list", { name: "Kroki wejścia" });
    expect(within(steps).getByText("Przed startem").parentElement).toHaveTextContent(
      "Przed startem 1 / 3",
    );
    expect(screen.getByText("B2B", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("Nordline Bank", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText(/Odhacza recepcja w Sprzęcie/)).toBeInTheDocument();
    expect(screen.getByText(/z plikiem/)).toBeInTheDocument();
    expect(screen.getByText("Konsultant u klienta · wersja 4")).toBeInTheDocument();
    expect(screen.getByText(/aktualna to wersja 5/)).toBeInTheDocument();
    expect(screen.getByText("Mail powitalny 7")).toBeInTheDocument();
    // Zestaw prowadzi Sprzęt, umowę administracja — nie da się ich odhaczyć tutaj.
    expect(screen.getByRole("checkbox", { name: /Przygotuj zestaw sprzętu/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /Umowa podpisana/ })).toBeDisabled();
  });

  it("odhaczenie idzie do zadania sprawy", async () => {
    mocks.get.mockResolvedValue({ data: view() });
    mocks.patch.mockResolvedValue({ data: {} });
    renderTab();
    fireEvent.click(await screen.findByRole("checkbox", { name: /Zaświadczenie o niekaralności/ }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/hr/lifecycle/tasks/13", { status: "done" }),
    );
  });

  it("wyłączony moduł (404) zostawia starą listę onboardingu", async () => {
    mocks.get.mockImplementation((url: string) =>
      url.includes("/entry")
        ? Promise.reject(httpError(404))
        : Promise.resolve({ data: [] }),
    );
    renderTab();
    expect(await screen.findByText(/Wygeneruj domyślny checklist/)).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/contracts/7/onboarding");
  });

  it("awaria nie udaje pustej listy ani starej zakładki", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderTab();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByText(/Wygeneruj domyślny checklist/)).not.toBeInTheDocument();
    expect(screen.queryByText("Lista wejścia jest pusta.")).not.toBeInTheDocument();
  });

  it("bez listy mówi dlaczego i pozwala ją założyć", async () => {
    mocks.get.mockResolvedValue({
      data: view({ case: null, missing_reason: "past_start", can_create: true }),
    });
    mocks.post.mockResolvedValue({ data: view() });
    renderTab();
    expect(await screen.findByText(/Start kontraktu już minął/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Załóż listę wejścia" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/lifecycle/contracts/7/entry"),
    );
  });

  it("stare pozycje są pod listą tylko do odczytu", async () => {
    mocks.get.mockImplementation((url: string) =>
      url.includes("/entry")
        ? Promise.resolve({ data: view({ legacy_items: 1 }) })
        : Promise.resolve({
            data: [
              {
                id: 1,
                contract_id: 7,
                label: "BHP — szkolenie",
                status: "pending",
                assigned_to: null,
                due_date: null,
                notes: null,
                order: 0,
                created_at: "2026-10-01T10:00:00Z",
                updated_at: "2026-10-01T10:00:00Z",
              },
            ],
          }),
    );
    renderTab();
    expect(await screen.findByText("BHP — szkolenie")).toBeInTheDocument();
    expect(screen.getByText("Wcześniejsza lista onboardingu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usuń pozycję/ })).not.toBeInTheDocument();
  });
});
