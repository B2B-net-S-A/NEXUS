/**
 * Regresja klasy „awaria drugiego wywołania udaje awarię pierwszego".
 *
 * Zapis zamówienia z PDF-em to DWA wywołania API pod jedną mutacją. Gdy padnie
 * upload (415 nie-PDF, 413 > 25 MB, 410, timeout axiosa), zamówienie razem
 * z liniami konsultantów JEST już w bazie — a komunikat „Nie udało się zapisać
 * zamówienia." przy otwartym modalu zaprasza do kliknięcia „Zapisz" jeszcze
 * raz. `order_number` jest świadomie BEZ unikalności w bazie, więc ponowienie
 * zakłada DRUGIE zamówienie o tym samym numerze, a niejednoznaczność wychodzi
 * dopiero przy imporcie zużycia MD — daleko od przyczyny.
 *
 * Regresja jest CICHA: wszystkie wywołania API kończą się „poprawnie", nikt nie
 * dostaje 500, a defekt widać dopiero po tygodniach w danych. Dlatego test.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { MultiConsultantOrdersTab } from "@/components/client-profile/orders/MultiConsultantOrdersTab";
import type { OrderGroupRead } from "@/lib/api/orderGroups";

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (s: { user: { role: string; capabilities: string[] } }) => unknown,
  ) => selector({ user: { role: "admin", capabilities: ["manage_finance"] } }),
  canManageMultiConsultantOrders: () => true,
  canManageOrderLifecycle: () => true,
}));

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    consultantOptions: vi.fn(),
    addLine: vi.fn(),
    updateLine: vi.fn(),
    swapLine: vi.fn(),
    events: vi.fn(),
    remove: vi.fn(),
    removeLine: vi.fn(),
    close: vi.fn(),
    reopen: vi.fn(),
    extend: vi.fn(),
    replaceFile: vi.fn(),
    deleteFile: vi.fn(),
  },
  mdConsumptionApi: {},
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listActiveContractsForExtension: vi.fn(),
    extractOrderPdf: vi.fn(),
  },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

const SAVED_GROUP = {
  id: 77,
  client_id: 7,
  order_number: "445",
  start_date: "2026-03-01",
  end_date: null,
  notes: null,
  created_at: "2026-03-01T10:00:00Z",
  status: "active",
  status_label: "Aktywne",
  closure_date: null,
  closure_reason: null,
  is_cost_based: false,
  is_md_budget_based: false,
  budget_amount: null,
  budget_used: null,
  budget_remaining: null,
  budget_manual_adjustment: null,
  md_budget_total: null,
  md_budget_used: null,
  md_budget_remaining: null,
  md_budget_manual_adjustment: null,
  predecessor_group_id: null,
  filename: null,
  has_file: false,
  content_type: null,
  size_bytes: null,
  file_uploaded_at: null,
  can_add_consultant: true,
  lines: [],
  active_consultants: 0,
  event_count: 0,
  future_orders: [],
} as unknown as OrderGroupRead;

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MultiConsultantOrdersTab clientId={7} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/** Wypełnia minimalny formularz nowego zamówienia i dokłada plik PDF. */
async function fillNewOrderForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /Nowe zamówienie/ }));
  await user.type(screen.getByLabelText(/Numer zamówienia/), "445");
  fireEvent.change(screen.getByLabelText(/Obowiązuje od/), {
    target: { value: "2026-03-01" },
  });
  await user.upload(
    screen.getByLabelText(/Zamień plik PDF/),
    new File(["%PDF-1.7"], "zamowienie.pdf", { type: "application/pdf" }),
  );
}

describe("MultiConsultantOrdersTab — zapis zamówienia z PDF-em", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [], total_groups: 0, total_consultants: 0 },
    } as never);
    vi.mocked(orderGroupsApi.create).mockResolvedValue({
      data: SAVED_GROUP,
    } as never);
  });

  it("awaria wgrania PDF-a nie udaje awarii zapisu i zamyka modal", async () => {
    vi.mocked(orderGroupsApi.replaceFile).mockRejectedValue({
      response: { data: { detail: "Plik przekracza 25 MB." } },
    });
    const user = userEvent.setup();
    renderTab();
    await fillNewOrderForm(user);

    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    // Komunikat mówi PRAWDĘ: zamówienie zapisane, plik nie wszedł — razem
    // z powodem odmowy z API i wskazaniem, żeby NIE zakładać go drugi raz.
    const toast = await screen.findByText(/Zapisano zamówienie, ale nie udało się/);
    expect(toast).toHaveTextContent("Plik przekracza 25 MB.");
    expect(toast).toHaveTextContent(/NIE zakładaj go drugi raz/);

    // Modal zamknięty — nie ma czego kliknąć drugi raz, a lista pokaże
    // zamówienie, które faktycznie powstało.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Utwórz zamówienie" }),
      ).not.toBeInTheDocument(),
    );
    // Stary komunikat („Nie udało się zapisać zamówienia.") nie może wrócić:
    // to on wysyłał użytkownika po duplikat.
    expect(
      screen.queryByText(/Nie udało się zapisać zamówienia/),
    ).not.toBeInTheDocument();
    expect(orderGroupsApi.create).toHaveBeenCalledTimes(1);
  });

  it("pełne powodzenie nadal daje zwykły komunikat sukcesu", async () => {
    vi.mocked(orderGroupsApi.replaceFile).mockResolvedValue({
      data: { ...SAVED_GROUP, has_file: true, filename: "zamowienie.pdf" },
    } as never);
    const user = userEvent.setup();
    renderTab();
    await fillNewOrderForm(user);

    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    expect(await screen.findByText("Zapisano zamówienie")).toBeInTheDocument();
    expect(orderGroupsApi.replaceFile).toHaveBeenCalledTimes(1);
  });

  it("awaria samego zapisu nadal zostawia modal i błąd w formularzu", async () => {
    // Kontrola granicy: rozdzielenie komunikatów NIE może zamienić prawdziwej
    // awarii zapisu w cichy sukces — wtedy modal musi zostać otwarty.
    vi.mocked(orderGroupsApi.create).mockRejectedValue({
      response: { data: { detail: "Numer zamówienia jest wymagany." } },
    });
    const user = userEvent.setup();
    renderTab();
    await fillNewOrderForm(user);

    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    expect(
      await screen.findByText("Numer zamówienia jest wymagany."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Utwórz zamówienie" }),
    ).toBeInTheDocument();
    expect(orderGroupsApi.replaceFile).not.toHaveBeenCalled();
  });
});
