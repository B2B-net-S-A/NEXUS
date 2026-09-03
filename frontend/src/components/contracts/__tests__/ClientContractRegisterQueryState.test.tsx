/**
 * Rejestr kontraktów klienta: awaria NIE może zapraszać do duplikatu kontraktu.
 *
 * Zapytanie destrukturyzowało tylko `{ data, isLoading, isFetching }`, więc 500
 * albo 403 (zmienione przypisanie klienta dla Delivery Leada) renderowało
 * „0 kontraktów" nad „Brak kontraktów dla tego klienta." i przycisk „Dodaj
 * pierwszy kontrakt". Skorzystanie z tej zachęty tworzy drugi kontrakt dla
 * konsultanta, który już ma aktywny — a ten wpływa dalej do MRR, skanera
 * wygasania i marży klienta.
 *
 * Bliźniaczy `ContractsListV2` renderowany jako rodzeństwo na tej samej stronie
 * robił to poprawnie przez `resolveViewState` (audyt F-20) — tu domykamy dryf.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ClientContractRegister } from "@/components/contracts/ClientContractRegister";
import { useAuthStore } from "@/store/auth";

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => getMock(...args) },
  contractsApi: { update: vi.fn() },
}));

vi.mock("@/components/contracts/ContractRegisterDialog", () => ({
  ContractRegisterDialog: () => null,
}));

vi.mock("@/lib/session", () => ({
  getAuthenticatedRequestHeaders: () => ({ Authorization: "Bearer tok" }),
}));

const CLIENT_ID = 42;
const EMPTY_TEXT = "Brak kontraktów dla tego klienta.";
const CTA = "Dodaj pierwszy kontrakt";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderRegister() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ClientContractRegister clientId={CLIENT_ID} clientName="Nordea Bank" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
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
    },
    realUser: null,
    hydrated: true,
  });
  getMock.mockReset();
});

function mockListFailure(status: number) {
  getMock.mockImplementation((url: string) => {
    if (url === "/api/contracts/register/subcategories") {
      return Promise.resolve({ data: { subcategories: [] } });
    }
    return Promise.reject(httpError(status));
  });
}

describe("ClientContractRegister — awaria nie udaje pustego rejestru", () => {
  it("403 renderuje brak uprawnień, bez CTA tworzenia kontraktu", async () => {
    mockListFailure(403);

    renderRegister();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByText(CTA)).not.toBeInTheDocument();
  });

  it("500 renderuje awarię i NIE wypisuje „0 kontraktów” w nagłówku", async () => {
    mockListFailure(500);

    renderRegister();

    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeInTheDocument();
    expect(screen.getByText("Nie udało się pobrać rejestru")).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByText(CTA)).not.toBeInTheDocument();
    expect(screen.queryByText(/^0 kontrakt/)).not.toBeInTheDocument();
  });

  it("sukces z zerem kontraktów nadal zachęca do dodania pierwszego", async () => {
    getMock.mockImplementation((url: string) => {
      if (url === "/api/contracts/register/subcategories") {
        return Promise.resolve({ data: { subcategories: [] } });
      }
      return Promise.resolve({
        data: { items: [], total: 0, page: 1, page_size: 50 },
      });
    });

    renderRegister();

    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(screen.getByText(CTA)).toBeInTheDocument();
  });

  it("Delivery read i impersonacja nie pokazują akcji tworzenia", async () => {
    getMock.mockImplementation((url: string) => {
      if (url === "/api/contracts/register/subcategories") {
        return Promise.resolve({ data: { subcategories: [] } });
      }
      return Promise.resolve({
        data: { items: [], total: 0, page: 1, page_size: 50 },
      });
    });
    const baseUser = {
      id: 2,
      email: "dl@example.com",
      name: "Delivery Lead",
      role: "delivery_lead" as const,
      roles: ["delivery_lead" as const],
      profile_completed: true,
      profile_completed_at: null,
      force_password_change: false,
      force_password_change_at: null,
      effective_section_access: { delivery: "read" as const },
    };
    useAuthStore.setState({ user: baseUser, realUser: null });

    const first = renderRegister();
    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(CTA)).not.toBeInTheDocument();

    first.unmount();
    useAuthStore.setState({
      user: {
        ...baseUser,
        effective_section_access: { delivery: "write" },
      },
      realUser: {
        ...baseUser,
        id: 1,
        role: "admin",
        roles: ["admin"],
        effective_section_access: { delivery: "write" },
      },
    });
    renderRegister();
    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(CTA)).not.toBeInTheDocument();
  });
});
