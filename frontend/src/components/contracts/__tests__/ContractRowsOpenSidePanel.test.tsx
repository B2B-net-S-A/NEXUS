/**
 * „Obsługa kontraktorów” i rejestr klienta otwierają TEN SAM boczny panel
 * kontraktu co rejestr globalny (wersja B, 29.09.2026). Akcje w wierszach
 * (Uzupełnij/Aktywuj, Zakończ projekt, prolongata, ołówek) zostają w wierszu
 * i nie otwierają panelu.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  list: vi.fn(),
  stats: vi.fn(),
  panel: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("view=operations&tab=draft"),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  contractsApi: { update: vi.fn() },
  contractorsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    stats: (...args: unknown[]) => mocks.stats(...args),
  },
}));

vi.mock("@/components/contracts/ContractSidePanel", () => ({
  ContractSidePanel: (props: {
    contractId: number;
    source?: string;
    contractorItem?: { contract_id: number } | null;
  }) => {
    mocks.panel(props);
    return (
      <div data-testid="contract-side-panel">
        panel {props.contractId} {props.source}
      </div>
    );
  },
}));

vi.mock("@/components/v2/modals/DraftCompletionModal", () => ({
  DraftCompletionModal: () => <div role="dialog">okno uzupełnienia</div>,
}));

vi.mock("@/components/contracts/ContractRegisterDialog", () => ({
  ContractRegisterDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">okno rejestru</div> : null,
}));

import { ContractorsListV2 } from "@/components/v2/pages/ContractorsListV2";
import { ClientContractRegister } from "@/components/contracts/ClientContractRegister";
import { useAuthStore } from "@/store/auth";

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/contracts");
  useAuthStore.setState({
    user: {
      id: 1,
      email: "admin@example.com",
      name: "Admin",
      role: "admin",
      roles: ["admin"],
      profile_completed: true,
      profile_completed_at: null,
      force_password_change: false,
      force_password_change_at: null,
      capabilities: [],
      analytics_capabilities: [],
    } as never,
    realUser: null,
    hydrated: true,
  } as never);
});

describe("ContractorsListV2 — wiersz otwiera boczny panel", () => {
  beforeEach(() => {
    mocks.stats.mockResolvedValue({
      data: { draft: 1, drafts_incomplete: 1, active: 0, active_contracts: 0, ending: 0 },
    });
    mocks.list.mockResolvedValue({
      data: {
        items: [
          {
            contract_id: 801,
            candidate: { id: 9, name: "Ewa", lastname: "Przykładowa", email: null },
            client_name: "Bank Przykładowy",
            job_title: "Tester",
            status: "draft",
            start_date: "2026-10-01",
            end_date: null,
            rate_candidate: null,
            rate_client: null,
            rate_unit: "hourly",
            currency: "PLN",
            margin: null,
            contract_type: "b2b",
            work_mode: null,
            missing_fields: ["rate_client"],
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      },
    });
  });

  it("klik w wiersz otwiera panel z wierszem kontraktora (braki draftu)", async () => {
    wrap(<ContractorsListV2 />);
    const cell = await screen.findByText("Bank Przykładowy");
    fireEvent.click(cell);
    expect(await screen.findByTestId("contract-side-panel")).toHaveTextContent(
      "panel 801 contractors",
    );
    expect(mocks.panel).toHaveBeenLastCalledWith(
      expect.objectContaining({
        contractorItem: expect.objectContaining({ contract_id: 801 }),
      }),
    );
  });

  it("„Uzupełnij” w wierszu zostaje i nie otwiera panelu", async () => {
    wrap(<ContractorsListV2 />);
    fireEvent.click(await screen.findByRole("button", { name: "Uzupełnij" }));
    expect(await screen.findByText("okno uzupełnienia")).toBeInTheDocument();
    expect(screen.queryByTestId("contract-side-panel")).not.toBeInTheDocument();
  });
});

describe("ClientContractRegister — wiersz otwiera boczny panel", () => {
  beforeEach(() => {
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/api/contracts/register/subcategories") {
        return Promise.resolve({ data: { subcategories: [] } });
      }
      return Promise.resolve({
        data: {
          items: [
            {
              id: 901,
              candidate_id: 5,
              candidate_name: "Adam Przykładowy",
              project_code: "PRJ-1",
              project_name: "Projekt przykładowy",
              engagement_model: "time_based",
              start_date: "2026-01-01",
              end_date: null,
              prolongation_status: "unknown",
              status: "active",
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        },
      });
    });
  });

  it("klik w wiersz otwiera panel, ołówek otwiera edycję bez panelu", async () => {
    wrap(<ClientContractRegister clientId={42} clientName="Bank Przykładowy" />);
    fireEvent.click(await screen.findByText("Projekt przykładowy"));
    expect(await screen.findByTestId("contract-side-panel")).toHaveTextContent(
      "panel 901 client-register",
    );

    fireEvent.click(screen.getByTitle("Edytuj kontrakt"));
    expect(await screen.findByText("okno rejestru")).toBeInTheDocument();
  });
});
