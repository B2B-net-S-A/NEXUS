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
import { fireEvent, render, screen, within } from "@testing-library/react";
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
    documentFolders: vi.fn().mockResolvedValue({
      data: {
        folders: [],
        orders_folder_name: "Zamówienia",
        current_contract_number: null,
        suggestions: [],
      },
    }),
  },
  CONTRACT_FIELD_LABELS: {},
  CONTRACT_TERMINATION_REASONS: [],
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
  useOptionalToast: () => null,
}));

vi.mock("@/components/OrderDocumentsSection", () => ({
  OrderDocumentsSection: () => null,
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listContractOrderDocuments: vi.fn().mockResolvedValue({ data: { documents: [] } }),
  },
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

    // Wariant A (19.11.2026): „Usuń plik…” w menu „⋯” przy pliku, nie kosz na wierzchu.
    expect(within(await screen.findByRole("table")).getByText("umowa.pdf")).toBeInTheDocument();
    expect(screen.getByText("Dodaj plik")).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Więcej akcji: umowa.pdf" }), {
      button: 0,
      ctrlKey: false,
    });
    expect(await screen.findByRole("menuitem", { name: "Usuń plik…" })).toBeInTheDocument();
  });

  it("Dokumenty: `readOnly` zostawia pobieranie, chowa wgrywanie i usuwanie", async () => {
    signIn("admin");
    renderWith(<ContractDocumentsTab contractId={3} readOnly />);

    expect(within(await screen.findByRole("table")).getByText("umowa.pdf")).toBeInTheDocument();
    expect(screen.getByTitle("Pobierz")).toBeInTheDocument();
    expect(screen.queryByText("Dodaj plik")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Więcej akcji/ })).not.toBeInTheDocument();
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

  // Wariant A (19.11.2026): jedno menu „Dodaj aneks” zamiast pięciu przycisków.
  it("Aneksy: menu aneksów widzi każdy, komu karta dała zapis", async () => {
    renderWith(<ContractAmendmentsTab contractId={3} clientId={CLIENT_ID} />);

    const menu = await openAddAnnexMenu();
    expect(within(menu).getByRole("menuitem", { name: "Przedłużenie" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Zmiana zakresu" })).toBeInTheDocument();
    expect(
      within(menu).getByRole("menuitem", { name: /Wygeneruj dokument aneksu/ }),
    ).toHaveAttribute("href");
  });

  it("Aneksy: `readOnly` chowa menu aneksów", async () => {
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
    expect(screen.queryByRole("button", { name: /Dodaj aneks/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });

  it("Aneksy: „Zakończenie wcześniej” jest tylko wtedy, gdy karta przekaże zakończenie", async () => {
    const first = renderWith(
      <ContractAmendmentsTab contractId={3} clientId={CLIENT_ID} />,
    );
    const menu = await openAddAnnexMenu();
    expect(within(menu).getByRole("menuitem", { name: "Przedłużenie" })).toBeInTheDocument();
    expect(
      within(menu).queryByRole("menuitem", { name: /Zakończenie wcześniej/ }),
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
      within(await openAddAnnexMenu()).getByRole("menuitem", { name: /Zakończenie wcześniej/ }),
    ).toBeInTheDocument();
  });
});

/** Menu „Dodaj aneks” zakładki „Aneksy” (Radix otwiera je na `pointerdown`). */
async function openAddAnnexMenu() {
  fireEvent.pointerDown(await screen.findByRole("button", { name: /Dodaj aneks/ }), {
    button: 0,
    ctrlKey: false,
  });
  return screen.findByRole("menu");
}

describe("Aneksy — „Zmiana stawki” za uprawnieniem „Stawki i kwoty: zmiana”", () => {
  const rateButton = () => screen.queryByRole("menuitem", { name: "Zmiana stawki" });

  async function renderTab() {
    renderWith(<ContractAmendmentsTab contractId={3} clientId={CLIENT_ID} />);
    await openAddAnnexMenu();
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

  it("rola spoza domyślnych z nadaną zmianą kwot widzi „Zmiana stawki”", async () => {
    signIn("recruiter", ["contracts_orders_edit", "amounts_edit"]);
    await renderTab();

    expect(rateButton()).toBeInTheDocument();
  });

  it("Finanse z wyłączoną zmianą kwot nie widzą „Zmiana stawki”", async () => {
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
    await openAddAnnexMenu();
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
