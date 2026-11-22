/**
 * Boczny panel kontraktu (wariant A, 20.11.2026): jedno ostrzeżenie z akcją
 * na górze, w stopce jedna akcja główna „Otwórz kontrakt”, „Dodaj aneks” i menu,
 * status jako kropka z menu w nagłówku. Bramki są TE SAME co na karcie
 * kontraktu (`lib/contract-access`).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  get: vi.fn(),
  documents: vi.fn(),
  activities: vi.fn(),
  update: vi.fn(),
  updateStatus: vi.fn(),
  orderDocuments: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: vi.fn() }),
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
  await screen.findByRole("button", { name: "Więcej akcji kontraktu" });
  return within(await screen.findByTestId("contract-panel-actions"));
}

async function warning() {
  return within(await screen.findByTestId("contract-panel-warning"));
}

async function openMoreMenu() {
  const user = userEvent.setup();
  await user.click((await footer()).getByRole("button", { name: "Więcej akcji kontraktu" }));
  return user;
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.push.mockReset();
  mocks.documents.mockResolvedValue({ data: [] });
  mocks.activities.mockResolvedValue({ data: [] });
  mocks.updateStatus.mockResolvedValue({ data: {} });
  mocks.orderDocuments.mockResolvedValue({ data: { documents: [] } });
  login("admin", ["view_finance", "manage_finance"]);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("ContractSidePanel — jedno ostrzeżenie z akcją", () => {
  it("zakończony kontrakt: „Cofnij zakończenie” i „Powrót po przerwie” w ostrzeżeniu (admin)", async () => {
    renderPanel({
      status: "ended",
      end_date: "2026-08-31",
      terminated_at: "2026-08-31",
      termination_reason: "project_ended",
      agreement_termination_mode: "notice",
      can_reverse_termination: true,
      can_return_after_break: true,
    });
    const box = await warning();
    expect(box.getByText(/Kontrakt zakończony 31\.08\.2026/)).toBeInTheDocument();
    expect(box.getByRole("button", { name: /Cofnij zakończenie/ })).toBeInTheDocument();
    expect(box.getByRole("button", { name: /Powrót po przerwie/ })).toBeInTheDocument();
    // W stopce zostaje jedna akcja główna.
    expect((await footer()).getByRole("link", { name: "Otwórz kontrakt" })).toBeInTheDocument();
  });

  it("zakończony z nierozwiązaną umową B2B: zdanie z paska strony i „Zapisz rozwiązanie umowy”", async () => {
    renderPanel({
      status: "ended",
      end_date: "2026-08-31",
      terminated_at: "2026-08-31",
      can_reverse_termination: true,
      can_return_after_break: false,
    });
    const box = await warning();
    expect(box.getByText("Współpraca zakończona 31.08.2026 — umowa B2B nie jest rozwiązana")).toBeInTheDocument();
    expect(box.getByRole("button", { name: "Zapisz rozwiązanie umowy" })).toBeInTheDocument();
    expect(box.getByRole("button", { name: "Cofnij zakończenie" })).toBeInTheDocument();
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
      agreement_termination_mode: "notice",
      can_reverse_termination: true,
      can_return_after_break: true,
    });
    const box = await warning();
    expect(Boolean(box.queryByRole("button", { name: /Cofnij zakończenie/ }))).toBe(allowed);
    expect((await footer()).getByRole("link", { name: "Otwórz kontrakt" })).toBeInTheDocument();
  });

  it("szkic: „Uzupełnij i aktywuj” i lista braków", async () => {
    renderPanel({ status: "draft", rate_client: null, client_order_start_date: null, client_order_end_date: null });
    const box = await warning();
    expect(box.getByRole("button", { name: "Uzupełnij i aktywuj" })).toBeInTheDocument();
    expect(box.getByText(/Szkic — brakuje: stawka przychodowa/)).toBeInTheDocument();
  });

  it("brak aktywnego zamówienia: „Dodaj zamówienie” do zakładki zamówień klienta", async () => {
    renderPanel({ client_order_start_date: "2025-01-01", client_order_end_date: "2025-12-31" });
    const box = await warning();
    expect(screen.getByRole("alert")).toHaveTextContent(/Brak aktywnego zamówienia/);
    expect(box.getByText(/Ostatnie zamówienie skończyło się 31\.12\.2025/)).toBeInTheDocument();
    expect(box.getByRole("link", { name: "Dodaj zamówienie" })).toHaveAttribute(
      "href",
      "/clients/7?tab=zamowienia",
    );
  });

  it("zaplanowane odejście i brak stawki: jedna ramka, druga sprawa w „Także”", async () => {
    // Daty względem dzisiejszego dnia firmy — test nie starzeje się z kalendarzem.
    const inDays = (n: number) => {
      const d = new Date();
      d.setUTCDate(d.getUTCDate() + n);
      return d.toISOString().slice(0, 10);
    };
    const end = inDays(10);
    renderPanel({
      status: "ending",
      end_date: end,
      terminated_at: end,
      termination_reason: "project_ended",
      client_order_end_date: end,
      rate_client: null,
    });
    const boxes = await screen.findAllByTestId("contract-panel-warning");
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).toHaveTextContent(/Współpraca kończy się \d\d\.\d\d\.\d{4} — za \d+ dni/);
    expect(boxes[0]).toHaveTextContent("Także: Brak stawki klienta");
    // Dawne drugie ostrzeżenie o tym samym („Zaplanowane zakończenie…”) zniknęło.
    expect(screen.queryByText(/Zaplanowane zakończenie współpracy/)).toBeNull();
  });

  it("zwykły aktywny kontrakt: bez ramki, „Otwórz kontrakt” z powrotem do listy", async () => {
    renderPanel();
    const actions = await footer();
    const open = actions.getByRole("link", { name: "Otwórz kontrakt" });
    expect(open.getAttribute("href")).toContain("/contracts/501?from=contracts");
    expect(open.getAttribute("href")).toContain("returnTo=");
    expect(open).toHaveAttribute("data-tour", "contract.panel.open");
    expect(screen.queryByTestId("contract-panel-warning")).toBeNull();
  });
});

describe("ContractSidePanel — okres, kontakt i ostatnie zdarzenia", () => {
  it("okres w dwóch liniach: umowa z wypowiedzeniem i zamówienie", async () => {
    renderPanel();
    await footer();
    expect(screen.getByText(/01\.01\.2026 – bezterminowo/)).toBeInTheDocument();
    expect(screen.getByText(/wypowiedzenie 1 mies\./)).toBeInTheDocument();
    expect(screen.getByText(/01\.01\.2026 – 31\.12\.2031/)).toBeInTheDocument();
  });

  it("„Ostatnio” mówi zdaniem i pomija zdarzenia automatyczne", async () => {
    mocks.activities.mockResolvedValue({
      data: [
        { id: 3, action: "synced_with_orders", details: null, user_name: null, created_at: "2026-11-19T08:00:00Z" },
        { id: 2, action: "status_changed", details: null, user_name: "anna.kowalska@example.com", created_at: "2026-11-18T08:00:00Z" },
        { id: 1, action: "created", details: null, user_name: "jan.nowak@example.com", created_at: "2026-11-01T08:00:00Z" },
      ],
    });
    renderPanel();
    const recent = await screen.findByTestId("contract-panel-recent");
    expect(within(recent).getAllByRole("listitem")).toHaveLength(2);
    expect(recent).toHaveTextContent("Anna Kowalska");
    expect(recent).not.toHaveTextContent("@example.com");
    expect(recent).toHaveTextContent("18.11.2026");
  });
});

describe("ContractSidePanel — aneksy", () => {
  // To samo menu „Dodaj aneks” co w nagłówku strony kontraktu (wariant A).
  it("nigdy nie oferuje przedłużenia bezterminowej umowy B2B", async () => {
    const user = userEvent.setup();
    renderPanel();
    const actions = await footer();
    await user.click(actions.getByRole("button", { name: /Dodaj aneks/ }));
    expect(await screen.findByText("Zmiana zakresu")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Przedłużenie" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByText(/Przedłuż o 3/)).not.toBeInTheDocument();
    expect(screen.getByText(/nie ma czego przedłużać/)).toBeInTheDocument();
  });

  it("przedłużenie umowy zlecenie otwiera zakładkę aneksów od razu z oknem", async () => {
    const user = userEvent.setup();
    renderPanel({ contract_type: "uzlecenie", end_date: "2031-12-31" });
    const actions = await footer();
    await user.click(actions.getByRole("button", { name: /Dodaj aneks/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Przedłużenie" }));
    expect(mocks.push).toHaveBeenCalledWith(expect.stringContaining("tab=amendments"));
    expect(mocks.push).toHaveBeenCalledWith(expect.stringContaining("aneks=extension"));
    expect(mocks.push).toHaveBeenCalledWith(expect.stringContaining("returnTo="));
  });

  // „Zmiana stawki” = uprawnienie „Stawki i kwoty: zmiana” u klienta kontraktu
  // (`lib/contract-rate-amendment.ts`), nie rola.
  async function openAnnexMenu() {
    const user = userEvent.setup();
    renderPanel();
    await user.click((await footer()).getByRole("button", { name: /Dodaj aneks/ }));
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
  it("„Zakończ współpracę…” w menu wymaga prawa do statusu kontraktu", async () => {
    login("delivery_lead");
    renderPanel();
    await openMoreMenu();
    const item = await screen.findByRole("menuitem", { name: "Zakończ współpracę…" });
    expect(item).toHaveAttribute("data-tour", "contract.panel.end");
    // Status to kropka z menu w nagłówku, nie lista w stopce.
    expect(screen.getByRole("button", { name: /Zmień status kontraktu/ })).toBeInTheDocument();
  });

  it("rola bez prawa do statusu nie widzi zakończenia ani menu statusu", async () => {
    login("recruiter");
    renderPanel();
    await openMoreMenu();
    expect(await screen.findByRole("menuitem", { name: "Zamówienia u klienta" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Zakończ współpracę…" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zmień status kontraktu/ })).not.toBeInTheDocument();
  });

  it("„Przepnij na innego klienta” tylko dla admina", async () => {
    renderPanel();
    await openMoreMenu();
    expect(await screen.findByRole("menuitem", { name: /Przepnij na innego klienta/ })).toBeInTheDocument();
  });

  it("Delivery Lead nie widzi przepięcia klienta", async () => {
    login("delivery_lead");
    renderPanel();
    await openMoreMenu();
    expect(await screen.findByRole("menuitem", { name: "Edytuj" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Przepnij na innego klienta/ })).not.toBeInTheDocument();
  });

  it("stawki są zredagowane bez wglądu w finanse klienta", async () => {
    login("delivery_lead");
    renderPanel();
    expect(await screen.findByTestId("contract-panel-finance-redacted")).toBeInTheDocument();
    expect(screen.queryByText(/170,00/)).not.toBeInTheDocument();
  });

  it("admin z `view_finance` widzi pieniądze w jednej linii i marżę miesięcznie", async () => {
    renderPanel();
    const rates = await screen.findByTestId("contract-panel-rates");
    expect(rates).toHaveTextContent(/Koszt\s*120,00\s*zł\/h/);
    expect(rates).toHaveTextContent(/Przychód\s*170,00\s*zł\/h/);
    expect(rates).toHaveTextContent(/Marża\s*50,00\s*zł\/h/);
    expect(screen.getByTestId("contract-panel-monthly-margin")).toHaveTextContent(/29,4%.*marży miesięcznie/);
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
    await user.click(screen.getByRole("button", { name: /Zmień status kontraktu/ }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Zakończony…" }));
    expect(h.onRequestTermination).toHaveBeenCalled();
    expect(mocks.updateStatus).not.toHaveBeenCalled();
  });

  it("zakończony kontrakt nie wraca zmianą statusu — podpowiedź przywrócenia", async () => {
    const user = userEvent.setup();
    const h = renderControl("ended", false);
    await user.click(screen.getByRole("button", { name: /Zmień status kontraktu/ }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Aktywny" }));
    expect(h.onRecoveryHint).toHaveBeenCalledWith(expect.stringContaining("przywraca Admin"));
    expect(mocks.updateStatus).not.toHaveBeenCalled();
  });

  it("zwykła zmiana statusu idzie do API", async () => {
    const user = userEvent.setup();
    renderControl("active");
    await user.click(screen.getByRole("button", { name: /Zmień status kontraktu/ }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Szkic" }));
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
    await user.click(screen.getByRole("button", { name: /Zmień status kontraktu/ }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Szkic" }));
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
