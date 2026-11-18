/**
 * Rejestr klienta otwiera TEN SAM boczny panel kontraktu co lista globalna
 * (wersja B, 29.09.2026). Akcje w wierszach (prolongata, ołówek) zostają
 * w wierszu i nie otwierają panelu. „Uzupełnij / Aktywuj” szkicu na liście
 * globalnej sprawdza `ContractsListV2QuickFilters.test.tsx` (18.11.2026).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  panel: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  contractsApi: { update: vi.fn() },
}));

vi.mock("@/components/contracts/ContractSidePanel", () => ({
  ContractSidePanel: (props: { contractId: number; source?: string }) => {
    mocks.panel(props);
    return (
      <div data-testid="contract-side-panel">
        panel {props.contractId} {props.source}
      </div>
    );
  },
}));

vi.mock("@/components/contracts/ContractRegisterDialog", () => ({
  ContractRegisterDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">okno rejestru</div> : null,
}));

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
