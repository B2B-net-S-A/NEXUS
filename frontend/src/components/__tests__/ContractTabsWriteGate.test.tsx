/**
 * Zakładki kontraktu (Dokumenty, Aneksy, Onboarding) mają JEDNĄ bramkę zapisu:
 * `readOnly` z karty kontraktu (`lib/contract-access.ts` — uprawnienie
 * „Kontrakty i zamówienia: tworzenie i edycja”, tryb podglądu).
 *
 * Do 02.10.2026 każda z nich miała w środku drugą bramkę,
 * `RequireRole admin/delivery_lead`. Posiadacz uprawnienia spoza tych ról
 * (domyślnie Finanse, każda osoba z nadanym uprawnieniem) był wpuszczany przez
 * kartę i dostawał zakładkę bez ani jednego przycisku.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  documents: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  contractsApi: {
    documents: (...args: unknown[]) => mocks.documents(...args),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
  CONTRACT_FIELD_LABELS: {},
  CONTRACT_TERMINATION_REASONS: [],
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));

vi.mock("@/components/OrderDocumentsSection", () => ({
  OrderDocumentsSection: () => null,
}));

import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";
import { ContractDocumentsTab } from "@/components/ContractDocumentsTab";
import { ContractOnboardingTab } from "@/components/ContractOnboardingTab";
import type { Permission } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

const CLIENT_ID = 7;

function signIn(role: string, granted?: Permission[], extra: Record<string, unknown> = {}) {
  useAuthStore.setState({
    user: {
      id: 3,
      email: `${role}@example.com`,
      name: role,
      role,
      roles: [role],
      capabilities: [],
      analytics_capabilities: [],
      ...(granted ? { effective_action_access: permissionSnapshot(...granted) } : {}),
      ...extra,
    },
    realUser: null,
    hydrated: true,
  } as never);
}

function renderWith(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const DOCUMENT = {
  id: 9,
  contract_id: 3,
  filename: "umowa.pdf",
  doc_type: "contract",
  content_type: "application/pdf",
  size_bytes: 128,
  expiry_date: null,
  uploaded_by: 1,
  uploaded_by_email: "ktos@example.com",
  created_at: "2026-09-01T10:00:00Z",
};

const ONBOARDING_ITEM = {
  id: 1,
  contract_id: 3,
  label: "Karta dostępu",
  status: "pending",
  assigned_to: null,
  due_date: null,
  notes: null,
  order: 0,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.documents.mockResolvedValue({ data: [DOCUMENT] });
  mocks.get.mockImplementation((url: string) =>
    Promise.resolve({
      data: url.endsWith("/onboarding") ? [ONBOARDING_ITEM] : [],
    }),
  );
  // Finanse: rola spoza dawnej pary admin/Delivery Lead, z edycją kontraktów.
  signIn("finance");
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("zakładki kontraktu — zapis rozstrzyga `readOnly`, nie rola", () => {
  it("Dokumenty: wgrywanie i usuwanie widzi każdy, komu karta dała zapis", async () => {
    renderWith(<ContractDocumentsTab contractId={3} />);

    expect(await screen.findByText("umowa.pdf")).toBeInTheDocument();
    expect(screen.getByText("Wgraj plik")).toBeInTheDocument();
    expect(screen.getByTitle("Usuń")).toBeInTheDocument();
  });

  it("Dokumenty: `readOnly` zostawia pobieranie, chowa wgrywanie i usuwanie", async () => {
    signIn("admin");
    renderWith(<ContractDocumentsTab contractId={3} readOnly />);

    expect(await screen.findByText("umowa.pdf")).toBeInTheDocument();
    expect(screen.getByTitle("Pobierz")).toBeInTheDocument();
    expect(screen.queryByText("Wgraj plik")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń")).not.toBeInTheDocument();
  });

  it("Onboarding: dodawanie, status i usuwanie widzi każdy, komu karta dała zapis", async () => {
    renderWith(<ContractOnboardingTab contractId={3} />);

    expect(await screen.findByText("Karta dostępu")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dodaj/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Karta dostępu: zmień status/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Usuń pozycję Karta dostępu" }),
    ).toBeInTheDocument();
  });

  it("Onboarding: `readOnly` chowa wszystkie akcje, lista zostaje", async () => {
    signIn("admin");
    renderWith(<ContractOnboardingTab contractId={3} readOnly />);

    expect(await screen.findByText("Karta dostępu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /zmień status/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Usuń pozycję/ }),
    ).not.toBeInTheDocument();
  });

  it("Aneksy: przyciski aneksów widzi każdy, komu karta dała zapis", async () => {
    renderWith(<ContractAmendmentsTab contractId={3} clientId={CLIENT_ID} />);

    expect(await screen.findByRole("button", { name: /Przedłuż/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zmień zakres/ })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Wygeneruj dokument aneksu/ }),
    ).toBeInTheDocument();
  });

  it("Aneksy: `readOnly` chowa wszystkie przyciski aneksów", async () => {
    signIn("admin");
    renderWith(
      <ContractAmendmentsTab
        contractId={3}
        clientId={CLIENT_ID}
        readOnly
        onRequestTermination={() => {}}
      />,
    );

    expect(await screen.findByText(/Brak aneksów/)).toBeInTheDocument();
    for (const name of [/Przedłuż/, /Zmień stawkę/, /Zmień zakres/, /Zakończ wcześniej/]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("Aneksy: „Zakończ wcześniej” jest tylko wtedy, gdy karta przekaże zakończenie", async () => {
    const first = renderWith(
      <ContractAmendmentsTab contractId={3} clientId={CLIENT_ID} />,
    );
    expect(await screen.findByRole("button", { name: /Przedłuż/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Zakończ wcześniej/ }),
    ).not.toBeInTheDocument();
    first.unmount();

    renderWith(
      <ContractAmendmentsTab
        contractId={3}
        clientId={CLIENT_ID}
        onRequestTermination={() => {}}
      />,
    );
    expect(
      await screen.findByRole("button", { name: /Zakończ wcześniej/ }),
    ).toBeInTheDocument();
  });
});

describe("Aneksy — „Zmień stawkę” za uprawnieniem „Stawki i kwoty: zmiana”", () => {
  const rateButton = () => screen.queryByRole("button", { name: /Zmień stawkę/ });

  async function renderTab() {
    renderWith(<ContractAmendmentsTab contractId={3} clientId={CLIENT_ID} />);
    await screen.findByRole("button", { name: /Zmień zakres/ });
  }

  it.each(["admin", "finance"])("%s ma zmianę kwot domyślnie", async (role) => {
    signIn(role);
    await renderTab();

    expect(rateButton()).toBeInTheDocument();
  });

  it("Delivery Lead domyślnie nie zmienia stawek aneksem", async () => {
    signIn("delivery_lead");
    await renderTab();

    expect(rateButton()).not.toBeInTheDocument();
  });

  it("rola spoza domyślnych z nadaną zmianą kwot widzi „Zmień stawkę”", async () => {
    signIn("recruiter", ["contracts_orders_edit", "amounts_edit"]);
    await renderTab();

    expect(rateButton()).toBeInTheDocument();
  });

  it("Finanse z wyłączoną zmianą kwot nie widzą „Zmień stawkę”", async () => {
    signIn("finance", ["contracts_orders_edit", "finance_module"]);
    await renderTab();

    expect(rateButton()).not.toBeInTheDocument();
  });

  it("Delivery Lead z nadaną zmianą kwot — tylko u klienta z przypisania", async () => {
    const scope = (clientIds: number[]) => ({
      data_scope: {
        kind: "delivery_clients",
        user_id: 3,
        allowed_client_ids: clientIds,
        allowed_tac_user_ids: [],
        allowed_operator_user_ids: [],
        finance_client_ids: clientIds,
      },
    });
    signIn("delivery_lead", ["contracts_orders_edit", "amounts_edit"], scope([99]));
    const first = renderWith(
      <ContractAmendmentsTab contractId={3} clientId={CLIENT_ID} />,
    );
    await screen.findByRole("button", { name: /Zmień zakres/ });
    expect(rateButton()).not.toBeInTheDocument();
    first.unmount();

    signIn(
      "delivery_lead",
      ["contracts_orders_edit", "amounts_edit"],
      scope([CLIENT_ID]),
    );
    await renderTab();
    expect(rateButton()).toBeInTheDocument();
  });
});
