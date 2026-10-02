/**
 * Boczny panel kontraktu (wersja B, 29.09.2026): akcja główna zależy od stanu
 * kontraktu, a bramki są TE SAME co na karcie kontraktu (`lib/contract-access`).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  documents: vi.fn(),
  activities: vi.fn(),
  update: vi.fn(),
  updateStatus: vi.fn(),
  orderDocuments: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/contracts",
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  contractsApi: {
    get: (...args: unknown[]) => mocks.get(...args),
    documents: (...args: unknown[]) => mocks.documents(...args),
    activities: (...args: unknown[]) => mocks.activities(...args),
    update: (...args: unknown[]) => mocks.update(...args),
    updateStatus: (...args: unknown[]) => mocks.updateStatus(...args),
  },
}));

vi.mock("@/lib/api/dlPortal", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/dlPortal")>()),
  dlPortalApi: {
    listContractOrderDocuments: (...args: unknown[]) => mocks.orderDocuments(...args),
  },
}));

import { ContractSidePanel } from "@/components/contracts/ContractSidePanel";
import { ContractStatusControl } from "@/components/contracts/ContractStatusControl";
import { useAuthStore } from "@/store/auth";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

type Role =
  | "admin"
  | "delivery_lead"
  | "finance"
  | "talent_community_manager"
  | "recruiter";

function login(
  role: Role,
  capabilities: string[] = [],
  extra: Record<string, unknown> = {},
) {
  useAuthStore.setState({
    user: {
      id: 1,
      email: `${role}@example.com`,
      name: role,
      role,
      roles: [role],
      profile_completed: true,
      profile_completed_at: null,
      force_password_change: false,
      force_password_change_at: null,
      capabilities,
      analytics_capabilities: capabilities,
      ...extra,
    } as never,
    realUser: null,
    hydrated: true,
  } as never);
}

const baseContract = {
  id: 501,
  candidate_id: 70,
  client_id: 7,
  job_id: null,
  candidate_name: "Anna Przykładowa",
  client_name: "Bank Przykładowy",
  job_title: "Tester",
  start_date: "2026-01-01",
  end_date: null,
  client_order_start_date: "2026-01-01",
  client_order_end_date: "2031-12-31",
  rate_candidate: 120,
  rate_client: 170,
  margin: 50,
  monthly_margin: 8400,
  rate_unit: "hourly",
  billing_hours_per_month: 168,
  currency: "PLN",
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  contract_type: "b2b",
  status: "active",
  work_mode: "remote",
  notice_period_months: 1,
  termination_reason: null,
  terminated_at: null,
  related_contracts: [],
};

function renderPanel(contract: Record<string, unknown> = {}) {
  mocks.get.mockResolvedValue({ data: { ...baseContract, ...contract } });
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ContractSidePanel
        contractId={501}
        onClose={() => {}}
        returnTarget="/contracts?status=active&status=ending&contract=501"
      />
    </QueryClientProvider>,
  );
}

async function footer() {
  return within(await screen.findByTestId("contract-panel-actions"));
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.documents.mockResolvedValue({ data: [] });
  mocks.activities.mockResolvedValue({ data: [] });
  mocks.updateStatus.mockResolvedValue({ data: {} });
  mocks.orderDocuments.mockResolvedValue({ data: { documents: [] } });
  login("admin", ["view_finance", "manage_finance"]);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("ContractSidePanel — akcja główna według stanu", () => {
  it("zakończony kontrakt: „Cofnij zakończenie” i „Powrót po przerwie” (admin)", async () => {
    renderPanel({
      status: "ended",
      end_date: "2026-08-31",
      terminated_at: "2026-08-31",
      termination_reason: "project_ended",
      can_reverse_termination: true,
      can_return_after_break: true,
    });
    const actions = await footer();
    expect(actions.getByRole("button", { name: /Cofnij zakończenie/ })).toBeInTheDocument();
    expect(actions.getByRole("button", { name: /Powrót po przerwie/ })).toBeInTheDocument();
    expect(screen.getByText(/Kontrakt zakończony 31\.08\.2026/)).toBeInTheDocument();
  });

  it.each<[Role, boolean]>([
    ["finance", true],
    ["talent_community_manager", true],
    ["delivery_lead", false],
  ])("przywrócenie zakończonego kontraktu dla roli %s: %s", async (role, allowed) => {
    login(role);
    renderPanel({
      status: "ended",
      end_date: "2026-08-31",
      terminated_at: "2026-08-31",
      can_reverse_termination: true,
      can_return_after_break: true,
    });
    const actions = await footer();
    expect(Boolean(actions.queryByRole("button", { name: /Cofnij zakończenie/ }))).toBe(allowed);
    if (!allowed) {
      expect(actions.getByRole("link", { name: "Otwórz kontrakt" })).toBeInTheDocument();
    }
  });

  it("draft: „Uzupełnij i aktywuj” i lista braków", async () => {
    renderPanel({ status: "draft", rate_client: null, client_order_start_date: null, client_order_end_date: null });
    const actions = await footer();
    expect(actions.getByRole("button", { name: "Uzupełnij i aktywuj" })).toBeInTheDocument();
    expect(screen.getByText(/Draft — brakuje: stawka przychodowa/)).toBeInTheDocument();
  });

  it("brak aktywnego zamówienia: „Dodaj zamówienie u klienta →” do zakładki zamówień", async () => {
    renderPanel({ client_order_start_date: "2025-01-01", client_order_end_date: "2025-12-31" });
    const actions = await footer();
    expect(actions.getByRole("link", { name: "Dodaj zamówienie u klienta →" })).toHaveAttribute(
      "href",
      "/clients/7?tab=zamowienia",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/Brak aktywnego zamówienia/);
  });

  it("zwykły aktywny kontrakt: „Otwórz kontrakt” z powrotem do listy", async () => {
    renderPanel();
    const actions = await footer();
    const open = actions.getByRole("link", { name: "Otwórz kontrakt" });
    expect(open.getAttribute("href")).toContain("/contracts/501?from=contracts");
    expect(open.getAttribute("href")).toContain("returnTo=");
  });
});

describe("ContractSidePanel — aneksy", () => {
  it("nigdy nie oferuje przedłużenia bezterminowej umowy B2B", async () => {
    const user = userEvent.setup();
    renderPanel();
    const actions = await footer();
    await user.click(actions.getByRole("button", { name: "Aneksy" }));
    expect(await screen.findByText("Zmiana zakresu")).toBeInTheDocument();
    expect(screen.queryByText("Przedłużenie")).not.toBeInTheDocument();
    expect(screen.queryByText(/Przedłuż o 3/)).not.toBeInTheDocument();
    expect(screen.getByText(/przedłuża się zamówienie klienta/)).toBeInTheDocument();
  });

  it("oferuje przedłużenie umowy zlecenie (link do zakładki aneksów)", async () => {
    const user = userEvent.setup();
    renderPanel({ contract_type: "uzlecenie", end_date: "2031-12-31" });
    const actions = await footer();
    await user.click(actions.getByRole("button", { name: "Aneksy" }));
    const item = await screen.findByRole("menuitem", { name: "Przedłużenie" });
    expect(item.getAttribute("href")).toContain("tab=amendments");
  });

  // „Zmiana stawki” = uprawnienie „Stawki i kwoty: zmiana” u klienta kontraktu
  // (`lib/contract-rate-amendment.ts`), nie rola.
  async function openAnnexMenu() {
    const user = userEvent.setup();
    renderPanel();
    await user.click((await footer()).getByRole("button", { name: "Aneksy" }));
    await screen.findByText("Zmiana zakresu");
  }

  it("admin (ma zmianę kwot) widzi „Zmiana stawki”", async () => {
    await openAnnexMenu();
    expect(screen.getByRole("menuitem", { name: "Zmiana stawki" })).toBeInTheDocument();
  });

  it("Delivery Lead bez zmiany kwot nie dostaje „Zmiana stawki”", async () => {
    login("delivery_lead");
    await openAnnexMenu();
    expect(screen.queryByRole("menuitem", { name: "Zmiana stawki" })).not.toBeInTheDocument();
  });

  it.each([
    [7, true],
    [99, false],
  ])(
    "Delivery Lead z nadaną zmianą kwot, klient %s w przypisaniu: %s",
    async (assignedClientId, visible) => {
      login("delivery_lead", [], {
        effective_action_access: permissionSnapshot(
          "clients_edit",
          "contracts_orders_edit",
          "contract_status",
          "amounts_edit",
        ),
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [assignedClientId],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
          finance_client_ids: [assignedClientId],
        },
      });
      await openAnnexMenu();
      expect(Boolean(screen.queryByRole("menuitem", { name: "Zmiana stawki" }))).toBe(
        visible,
      );
    },
  );
});

describe("ContractSidePanel — bramki ról", () => {
  it("„Zakończ współpracę…” wymaga prawa do statusu kontraktu", async () => {
    login("delivery_lead");
    renderPanel();
    expect(
      (await footer()).getByRole("button", { name: "Zakończ współpracę…" }),
    ).toBeInTheDocument();
  });

  it("rola bez prawa do statusu nie widzi zakończenia ani listy statusu", async () => {
    login("recruiter");
    renderPanel();
    const actions = await footer();
    expect(actions.queryByRole("button", { name: "Zakończ współpracę…" })).not.toBeInTheDocument();
    expect(actions.queryByRole("combobox", { name: "Zmień status kontraktu" })).not.toBeInTheDocument();
  });

  it("„Przepnij na innego klienta” tylko dla admina", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click((await footer()).getByRole("button", { name: "Więcej akcji kontraktu" }));
    expect(await screen.findByRole("menuitem", { name: /Przepnij na innego klienta/ })).toBeInTheDocument();
  });

  it("Delivery Lead nie widzi przepięcia klienta", async () => {
    const user = userEvent.setup();
    login("delivery_lead");
    renderPanel();
    await user.click((await footer()).getByRole("button", { name: "Więcej akcji kontraktu" }));
    expect(await screen.findByRole("menuitem", { name: "Edytuj" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Przepnij na innego klienta/ })).not.toBeInTheDocument();
  });

  it("stawki są zredagowane bez wglądu w finanse klienta", async () => {
    login("delivery_lead");
    renderPanel();
    expect(await screen.findByTestId("contract-panel-finance-redacted")).toBeInTheDocument();
    expect(screen.queryByText(/170,00/)).not.toBeInTheDocument();
  });

  it("admin z `view_finance` widzi stawki i marżę", async () => {
    renderPanel();
    expect(await screen.findByText(/170,00\s*zł\/h/)).toBeInTheDocument();
    expect(screen.getByText(/50,00\s*zł\/h/)).toBeInTheDocument();
  });
});

describe("ContractStatusControl — ta sama lista na karcie i w panelu", () => {
  function renderControl(status: string, canRecover = true) {
    const qc = new QueryClient();
    const handlers = {
      onRequestTermination: vi.fn(),
      onRecoveryHint: vi.fn(),
      onError: vi.fn(),
    };
    render(
      <QueryClientProvider client={qc}>
        <ContractStatusControl
          contractId={501}
          status={status}
          canRecoverTermination={canRecover}
          {...handlers}
        />
      </QueryClientProvider>,
    );
    return handlers;
  }

  it("„Zakończony” otwiera okno zakończenia zamiast zapisu statusu", async () => {
    const user = userEvent.setup();
    const h = renderControl("active");
    await user.selectOptions(screen.getByRole("combobox", { name: "Zmień status kontraktu" }), "ended");
    expect(h.onRequestTermination).toHaveBeenCalled();
    expect(mocks.updateStatus).not.toHaveBeenCalled();
  });

  it("zakończony kontrakt nie wraca zmianą statusu — podpowiedź przywrócenia", async () => {
    const user = userEvent.setup();
    const h = renderControl("ended", false);
    await user.selectOptions(screen.getByRole("combobox", { name: "Zmień status kontraktu" }), "active");
    expect(h.onRecoveryHint).toHaveBeenCalledWith(expect.stringContaining("przywraca Admin"));
    expect(mocks.updateStatus).not.toHaveBeenCalled();
  });

  it("zwykła zmiana statusu idzie do API", async () => {
    const user = userEvent.setup();
    renderControl("active");
    await user.selectOptions(screen.getByRole("combobox", { name: "Zmień status kontraktu" }), "draft");
    await waitFor(() => expect(mocks.updateStatus).toHaveBeenCalledWith(501, "draft"));
  });

  // Przegląd PR #1932: panel stoi też nad rejestrem klienta, więc zmiana
  // statusu musi odświeżyć jego tabelę, a nie tylko listę /contracts.
  it("zmiana statusu odświeża rejestr klienta", async () => {
    const user = userEvent.setup();
    mocks.updateStatus.mockResolvedValueOnce({});
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    render(
      <QueryClientProvider client={qc}>
        <ContractStatusControl
          contractId={501}
          status="active"
          canRecoverTermination
          onRequestTermination={vi.fn()}
          onRecoveryHint={vi.fn()}
          onError={vi.fn()}
        />
      </QueryClientProvider>,
    );
    await user.selectOptions(screen.getByRole("combobox", { name: "Zmień status kontraktu" }), "draft");
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["client-register"] }));
  });
});

describe("ContractSidePanel — dokumenty zamówień w sekcji Dokumenty", () => {
  const orderDoc = {
    order_id: 9001,
    client_id: 7,
    contract_id: 501,
    title: "OIT/0189/2026",
    filename: "zamowienie-0189.pdf",
    content_type: "application/pdf",
    size_bytes: 1024,
    created_at: "2026-09-01T10:00:00Z",
    order_status: "active",
    uploaded_by_email: null,
    uploaded_at: null,
  };

  it("PDF zamówienia widać obok dokumentów kontraktu", async () => {
    mocks.orderDocuments.mockResolvedValue({ data: { documents: [orderDoc] } });
    renderPanel();
    expect(
      await screen.findByRole("button", { name: "zamowienie-0189.pdf" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Zamówienie OIT/0189/2026")).toBeInTheDocument();
    expect(screen.queryByText("Brak dokumentów.")).toBeNull();
  });

  it("403 z listy zamówień: brak błędu, zwykłe „Brak dokumentów.”", async () => {
    mocks.orderDocuments.mockRejectedValue({ response: { status: 403 } });
    renderPanel();
    expect(await screen.findByText("Brak dokumentów.")).toBeInTheDocument();
    expect(screen.queryByText(/Nie udało się pobrać dokumentów zamówień/)).toBeNull();
  });

  it("inna awaria listy zamówień jest widoczna", async () => {
    mocks.orderDocuments.mockRejectedValue({ response: { status: 500 } });
    renderPanel();
    expect(
      await screen.findByText("Nie udało się pobrać dokumentów zamówień."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak dokumentów.")).toBeNull();
  });
});
