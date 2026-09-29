/**
 * Panel osoby na zamówieniu MD/kosztowym (wersja B, 29.09.2026) — to, czego
 * dawniej pilnowały testy karty `OrderGroupCard` i karty osoby zakończonej
 * (`EndedLineCard`): historia osoby, zakresy MD, decyzje, zamiana i usuwanie.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { EndedLineDecisionDialog } from "@/components/client-profile/orders/EndedLineDecisionDialog";
import { OrderLinePanel } from "@/components/client-profile/orders/OrderLinePanel";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  makeOffboardingCase as offboardingCase,
  makeOrderGroup as group,
  makeOrderLine as line,
} from "@/components/client-profile/orders/__tests__/fixtures/order-groups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    history: vi.fn().mockResolvedValue({ data: { entries: [], people: [] } }),
    listConsumptions: vi.fn().mockResolvedValue({ data: { rows: [] } }),
  },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

function renderPanel(
  value: OrderGroupRead,
  target: OrderLineRead,
  options: {
    clientId?: number;
    canManage?: boolean;
    canEditAmounts?: boolean;
    canManageLifecycle?: boolean;
  } = {},
) {
  const handlers = {
    onClose: vi.fn(),
    onEditLine: vi.fn(),
    onSwapLine: vi.fn(),
    onDeleteLine: vi.fn(),
    onDecide: vi.fn(),
    onSelectLine: vi.fn(),
    onSelectGroup: vi.fn(),
  };
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <OrderLinePanel
          clientId={options.clientId ?? 18}
          group={value}
          line={target}
          canManage={options.canManage ?? true}
          canEditAmounts={options.canEditAmounts ?? true}
          canManageLifecycle={options.canManageLifecycle ?? true}
          {...handlers}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return handlers;
}

async function showDetails(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("tab", { name: "Szczegóły" }));
}

describe("OrderLinePanel — osoba w obsadzie", () => {
  beforeEach(() => vi.clearAllMocks());

  it("MD per osoba otwiera się na „Zużycie MD”, z drogą do kontraktu i zamówienia", async () => {
    const user = userEvent.setup();
    const value = group();
    const handlers = renderPanel(value, value.lines[0]);

    expect(screen.getByRole("tab", { name: "Zużycie MD" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(orderGroupsApi.listConsumptions).toHaveBeenCalledWith(18, 15, 1));
    expect(screen.getByRole("link", { name: "Otwórz kontrakt →" })).toHaveAttribute(
      "href",
      "/contracts/100",
    );
    await user.click(screen.getByRole("button", { name: "4599030067" }));
    expect(handlers.onSelectGroup).toHaveBeenCalledWith(15);
  });

  it("zamówienie kosztowe nie ma zakładki zużycia MD", () => {
    const value = group({
      is_cost_based: true,
      budget_amount: 1000,
      budget_used: 0,
      budget_remaining: 1000,
      lines: [line({ md_total: null, md_remaining: null })],
    });
    renderPanel(value, value.lines[0]);
    expect(screen.queryByRole("tab", { name: "Zużycie MD" })).toBeNull();
    expect(screen.getByRole("tab", { name: "Szczegóły" })).toHaveAttribute("aria-selected", "true");
    expect(orderGroupsApi.listConsumptions).not.toHaveBeenCalled();
  });

  it("osoba dodana ręcznie ma swoją historię w szczegółach", async () => {
    const user = userEvent.setup();
    const substitute = line({
      id: 8,
      consultant_name: "Tadeusz Zastępca",
      origin: "manual",
      added_by_name: "Anna Przykładowa",
      added_at: "2026-08-13T09:00:00Z",
      replaces_name: "Marian Odeszły",
      md_total: null,
      md_remaining: null,
    });
    const value = group({
      is_cost_based: true,
      budget_amount: 40000,
      budget_used: 0,
      budget_remaining: 40000,
      has_file: true,
      lines: [substitute],
    });
    renderPanel(value, substitute);
    await showDetails(user);

    expect(
      screen.getByText(
        /Dodany ręcznie 13\.08\.2026 przez Anna Przykładowa jako zastępstwo za Marian Odeszły\./,
      ),
    ).toHaveTextContent(/PDF\) podpięto także do profilu tej osoby/);
  });

  it("delivery lead: edycja linii, zamiana i usunięcie osoby bez rozliczeń", async () => {
    const user = userEvent.setup();
    const value = group({ lines: [line({ md_used: 0 })] });
    const handlers = renderPanel(value, value.lines[0]);

    await user.click(screen.getByRole("button", { name: "Edytuj linię" }));
    expect(handlers.onEditLine).toHaveBeenCalledWith(value, value.lines[0]);
    await user.click(screen.getByRole("button", { name: "Zamień kontraktora" }));
    expect(handlers.onSwapLine).toHaveBeenCalledWith(value, value.lines[0]);

    await user.click(screen.getByRole("button", { name: "Więcej akcji konsultanta" }));
    await user.click(await screen.findByRole("menuitem", { name: /Usuń konsultanta z zamówienia/ }));
    await waitFor(() => expect(handlers.onDeleteLine).toHaveBeenCalledWith(value, value.lines[0]));
  });

  it("osoba z zaraportowanymi MD: usunięcie wyłączone z wyjaśnieniem", async () => {
    const user = userEvent.setup();
    const value = group({ lines: [line({ md_used: 12 })] });
    const handlers = renderPanel(value, value.lines[0]);

    await user.click(screen.getByRole("button", { name: "Więcej akcji konsultanta" }));
    const item = await screen.findByRole("menuitem", { name: /Usuń konsultanta z zamówienia/ });
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(item).toHaveAttribute("title", expect.stringContaining("ma rozliczenia"));
    await user.click(item);
    expect(handlers.onDeleteLine).not.toHaveBeenCalled();
  });

  it("Finanse: same stawki — bez zamiany i bez pełnej edycji", () => {
    const value = group();
    renderPanel(value, value.lines[0], { canManage: false, canEditAmounts: true });
    expect(screen.getByRole("button", { name: "Edytuj stawki" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edytuj linię" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Zamień kontraktora" })).toBeNull();
  });

  it("zaplanowane zastępstwo ma plakietkę i opis, kto przejmie pulę", async () => {
    const user = userEvent.setup();
    const incoming = line({
      id: 4,
      consultant_name: "Kamila Przejmująca",
      status: "draft",
      is_active: false,
      start_date: "2026-11-01",
      assignment_kind: "takeover",
      takeover_scheduled: true,
      takeover_from_name: "Konrad Odchodzący",
      takeover_md: 187,
      takeover_method: "one_to_one",
    });
    renderPanel(group({ lines: [incoming] }), incoming);
    expect(screen.getByText("Zaplanowane zastępstwo od 01.11.2026")).toBeInTheDocument();
    await showDetails(user);
    expect(screen.getByText(/Przejmie po: Konrad Odchodzący · 187 MD/)).toBeInTheDocument();
  });
});

describe("OrderLinePanel — osoba zakończona", () => {
  beforeEach(() => vi.clearAllMocks());

  it("czeka na decyzję: plakietka, okres, wykorzystanie i przycisk decyzji", async () => {
    const departed = line({
      id: 2,
      consultant_name: "Marian Odeszły",
      is_active: false,
      start_date: "2026-05-01",
      end_date: "2026-08-31",
      cooperation_ended_on: "2026-08-31",
      md_used: 25.45,
      rate_revenue: 1000,
      contract_type: "b2b",
    });
    const value = group({ lines: [departed] });
    const user = userEvent.setup();
    const handlers = renderPanel(value, departed);

    // Z decyzją panel otwiera się na szczegółach, nie na zużyciu.
    expect(screen.getByRole("tab", { name: "Szczegóły" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Zakończył projekt")).toBeInTheDocument();
    expect(screen.getByText("Okres").nextElementSibling).toHaveTextContent("01.05.2026 – 31.08.2026");
    expect(screen.getByText("Wykorzystanie").nextElementSibling).toHaveTextContent(
      /25,45 MD · 25\s450,00\szł/,
    );
    expect(screen.getByText("Umowa B2B nadal obowiązuje")).toBeInTheDocument();
    // Dopóki decyzja nie zapadła, zwykłe usunięcie jest schowane.
    expect(screen.queryByRole("button", { name: "Więcej akcji konsultanta" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Podejmij decyzję" }));
    expect(handlers.onDecide).toHaveBeenCalledWith(value, departed);
  });

  it("umowa rozwiązana: ostatni dzień i tryb, po decyzji „Zmień decyzję”", async () => {
    const user = userEvent.setup();
    const kept = line({
      id: 2,
      consultant_name: "Marian Odeszły",
      is_active: false,
      cooperation_ended_on: "2026-08-31",
      history_kept_at: "2026-09-01T09:00:00Z",
      history_kept_by_name: "Anna Wzorcowa",
      contract_type: "b2b",
      agreement_termination_mode: "mutual_agreement",
      agreement_last_day: "2026-08-31",
    });
    const value = group({ lines: [kept] });
    const handlers = renderPanel(value, kept);
    await showDetails(user);

    expect(screen.getByText("Zakończył współpracę")).toBeInTheDocument();
    expect(screen.getByText("Decyzja").nextElementSibling).toHaveTextContent(
      "Zostawiony jako historia",
    );
    expect(screen.getByText("Ostatni dzień umowy: 31.08.2026 · Porozumienie stron")).toBeInTheDocument();
    expect(screen.getByText(/Zostawiony jako historia 01\.09\.2026 — Anna Wzorcowa/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Podejmij decyzję" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Zmień decyzję" }));
    expect(handlers.onDecide).toHaveBeenCalledWith(value, kept);
  });

  it("czekająca pula MD: komunikat z liczbą MD, a rola bez obsady tylko czeka na DL", () => {
    const pending = line({
      id: 2,
      consultant_name: "Anna Zejście",
      is_active: false,
      cooperation_ended_on: "2026-08-31",
      offboarding_case: offboardingCase({ remaining_md_snapshot: 20 }),
    });
    renderPanel(group({ lines: [pending] }), pending, { canManage: false });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Wymagana decyzja o pozostałej puli MD: pozostało 20 MD.",
    );
    expect(screen.getByText("Oczekuje na decyzję Delivery Leada")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Podejmij decyzję" })).toBeNull();
  });

  it("zastąpiony: przejście do następcy i brak pytania o decyzję", async () => {
    const user = userEvent.setup();
    const replaced = line({
      id: 1,
      consultant_name: "Tomasz Zastąpiony",
      status: "completed",
      is_active: false,
      cooperation_ended_on: "2026-06-30",
      replaced_by_order_id: 2,
      replaced_by_consultant_name: "Marcin Następca",
      replaced_by_kind: "swap",
      replaced_by_md: 10,
    });
    const value = group({ lines: [replaced, line({ id: 2, consultant_name: "Marcin Następca" })] });
    const handlers = renderPanel(value, replaced);
    await showDetails(user);

    expect(screen.getByText("Decyzja").nextElementSibling).toHaveTextContent(
      "Zastąpiony przez Marcin Następca",
    );
    await user.click(screen.getByRole("button", { name: "Marcin Następca" }));
    expect(handlers.onSelectLine).toHaveBeenCalledWith(15, 2);
    expect(screen.getByText("Marcin Następca przejął(a) 10 MD.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Podejmij decyzję|Zmień decyzję/ })).toBeNull();
  });

  it("zamiana zostaje dostępna, dopóki linia jest aktywna w bazie", () => {
    // Serwer (`swap_consultant`) pyta o status linii, nie o obsadę.
    const departed = line({ id: 2, consultant_name: "Marian Odeszły", is_active: false, end_date: "2026-08-31" });
    renderPanel(group({ lines: [departed] }), departed);
    expect(screen.getByRole("button", { name: "Zamień kontraktora" })).toBeEnabled();
  });

  it("linia domknięta nie ma zamiany", () => {
    const closed = line({ id: 3, consultant_name: "Domknięta Linia", status: "completed", is_active: false });
    renderPanel(group({ lines: [closed] }), closed);
    expect(screen.queryByRole("button", { name: "Zamień kontraktora" })).toBeNull();
  });

  it("żaden panel nie używa starych nazw zakończenia", async () => {
    const user = userEvent.setup();
    const pending = line({
      id: 2,
      consultant_name: "Anna Zejście",
      is_active: false,
      cooperation_ended_on: "2026-08-31",
      offboarding_case: offboardingCase(),
    });
    renderPanel(group({ lines: [pending] }), pending);
    await showDetails(user);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/Zakończenie współpracy/);
    expect(text).not.toMatch(/Zakończony\b/);
  });
});

describe("OrderLinePanel — zakresy MD (umowy wykonawcze)", () => {
  const scopedGroup = () =>
    group({
      client_id: 115,
      executive_contract: {
        id: 71,
        number: "UW/242/2031",
        status: "active",
        framework_contract_id: 12,
        project_part: "cz2",
      },
      md_positions_total: 360,
      md_used_total: 154,
      lines: [
        line({
          id: 2,
          consultant_name: "Marcin Następca",
          md_total: 190,
          md_remaining: 206,
          md_used: 154,
          md_optional_total: 170,
          md_base_used: 154,
          md_optional_used: 0,
        }),
        line({
          id: 1,
          consultant_name: "Tomasz Zastąpiony",
          status: "completed",
          is_active: false,
          cooperation_ended_on: "2026-06-30",
          md_total: 100,
          md_used: 100,
          md_base_used: 100,
          replaced_by_order_id: 2,
          replaced_by_consultant_name: "Marcin Następca",
        }),
      ],
    });

  it("Centrum e-Zdrowia: jawne „pozostało” dla podstawy, opcji i łącznie", () => {
    const value = scopedGroup();
    renderPanel(value, value.lines[0], { clientId: 115 });
    const panel = screen.getByTestId("order-line-panel");
    expect(panel.querySelector('[aria-label="Podstawa — wykorzystano MD"]')).not.toBeNull();
    expect(panel.querySelector('[aria-label="Opcja — wykorzystano MD"]')).not.toBeNull();
    expect(panel.querySelector('[aria-label="Łącznie — wykorzystano MD"]')).not.toBeNull();
    // 190 − 154 = 36 w podstawie, cała opcja 170, łącznie 206 (serwerowe md_remaining).
    expect(panel).toHaveTextContent(/Pozostało 36 MD/);
    expect(panel).toHaveTextContent(/Pozostało 170 MD/);
    expect(panel).toHaveTextContent(/pozostało 206 MD/);
    expect(panel).not.toHaveTextContent(/Wykorzystano łącznie/);
  });

  it("bez opcji w umowie: komunikat zamiast paska opcji", () => {
    const value = scopedGroup();
    renderPanel(value, value.lines[1], { clientId: 115 });
    const panel = screen.getByTestId("order-line-panel");
    expect(panel).toHaveTextContent("Brak opcji w umowie");
    expect(panel.querySelector('[aria-label="Opcja — wykorzystano MD"]')).toBeNull();
    expect(panel).toHaveTextContent(/100 \/ 100 MD \(100%\)/);
  });

  it("ta sama linia u innego klienta zostaje przy zwartych paskach", () => {
    const value = scopedGroup();
    renderPanel(value, value.lines[0], { clientId: 18 });
    const panel = screen.getByTestId("order-line-panel");
    expect(panel).toHaveTextContent(/Wykorzystano łącznie 154 \/ 360 MD 43%/);
    expect(panel.querySelector('[aria-label="Łącznie — wykorzystano MD"]')).toBeNull();
  });
});

describe("EndedLineDecisionDialog — decyzja o osobie zakończonej", () => {
  function renderDialog(target: OrderLineRead, value = group({ lines: [target] })) {
    const handlers = {
      onClose: vi.fn(),
      onKeepHistory: vi.fn(),
      onReplaceLine: vi.fn(),
      onDeleteLine: vi.fn(),
      onResolveOffboarding: vi.fn(),
    };
    render(
      <EndedLineDecisionDialog
        group={value}
        line={target}
        canManage
        canManageLifecycle
        {...handlers}
      />,
    );
    return handlers;
  }

  it("trzy decyzje wołają swoje okna; osoba z fakturami nie da się usunąć", async () => {
    const user = userEvent.setup();
    const ended = line({
      id: 7,
      consultant_name: "Marian Odeszły",
      is_active: false,
      status: "completed",
      cooperation_ended_on: "2026-08-12",
      invoiced_total: 25720,
      md_total: null,
      md_remaining: null,
    });
    const handlers = renderDialog(ended);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Współpraca na tym zamówieniu zakończyła się 12.08.2026.");

    await user.click(within(dialog).getByRole("button", { name: /Zostaw jako historię/ }));
    expect(handlers.onKeepHistory).toHaveBeenCalledWith(expect.anything(), ended);
    await user.click(within(dialog).getByRole("button", { name: /Zastąp kimś innym/ }));
    expect(handlers.onReplaceLine).toHaveBeenCalledWith(expect.anything(), ended);
    // Usunięcie kasuje linię trwale — serwer odmówiłby (409).
    expect(within(dialog).getByRole("button", { name: /Usuń z zamówienia/ })).toBeDisabled();
    expect(handlers.onDeleteLine).not.toHaveBeenCalled();
  });

  it("czekająca pula MD ma jedną drogę — formularz puli", async () => {
    const user = userEvent.setup();
    const pending = line({
      id: 2,
      is_active: false,
      cooperation_ended_on: "2026-08-31",
      offboarding_case: offboardingCase(),
    });
    const handlers = renderDialog(pending);
    expect(screen.queryByRole("button", { name: /Zostaw jako historię/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: /Zdecyduj o pozostałej puli MD/ }));
    expect(handlers.onResolveOffboarding).toHaveBeenCalledWith(expect.anything(), pending);
  });
});
