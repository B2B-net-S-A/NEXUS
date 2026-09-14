/**
 * Jedno okno „Nowe zamówienie" (ticket 09.2026): PDF → „Zczytaj i uzupełnij
 * całe zamówienie" → karty wszystkich konsultantów → JEDNO „Utwórz zamówienie".
 * Bez pośredniego, pustego zamówienia i bez osobnego „Uzupełnij zamówienie".
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrderGroupFormModal } from "@/components/client-profile/orders/OrderGroupFormModal";
import type {
  OrderGroupExtraction,
  OrderPlanContract,
  OrderPlanLine,
} from "@/lib/api/orderGroups";
import { orderGroupsApi } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    extractPlan: vi.fn(),
    consultantOptions: vi.fn(),
  },
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: { extractOrderPdf: vi.fn() },
}));

function contract(overrides: Partial<OrderPlanContract> = {}): OrderPlanContract {
  return {
    contract_id: 11,
    candidate_id: 101,
    contractor_name: "Krzysztof Suwała",
    status: "active",
    start_date: "2025-06-01",
    end_date: null,
    rate_cost: 148.75,
    rate_cost_unit: "daily",
    rate_cost_currency: "PLN",
    rate_cost_rate_to_pln: 1,
    rate_cost_per_md_pln: 148.75,
    ...overrides,
  };
}

function line(overrides: Partial<OrderPlanLine> = {}): OrderPlanLine {
  return {
    ordinal: 1,
    document_name: "Krzysztof Suwała",
    position_label: "10",
    rate_revenue: 1080,
    rate_revenue_unit: "day",
    rate_revenue_gross: null,
    md_total: 35,
    start_date: null,
    end_date: null,
    match_status: "auto",
    match_reason: "Zapis identyczny z dokumentem",
    contract: contract(),
    options: [],
    nearest_names: [],
    warnings: [],
    ...overrides,
  };
}

const BIK_PLAN: OrderGroupExtraction = {
  order_number: "4500030845",
  start_date: "2026-09-03",
  end_date: null,
  total_value: 91560,
  currency: "PLN",
  md_total: null,
  suggested_order_type: "md",
  client_policy: null,
  consultant_ref: null,
  title_needs_review: false,
  document_incomplete: false,
  uncertain: false,
  uncertain_reasons: [],
  lines: [
    line(),
    line({
      ordinal: 2,
      document_name: "Paweł Łaski",
      position_label: "20",
      rate_revenue: 1280,
      md_total: 42,
      match_status: "confirm",
      match_reason:
        "W kontrakcie przed imieniem i nazwiskiem jest dopisek „Active” — rdzeń nazwy się zgadza — potwierdź, że to ta sama osoba",
      contract: contract({
        contract_id: 12,
        candidate_id: 102,
        contractor_name: "Active Pawel Laski",
        rate_cost: 160,
      }),
    }),
  ],
};

function renderModal(onSubmit = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <OrderGroupFormModal
        open
        onOpenChange={vi.fn()}
        group={null}
        clientId={18}
        orderType="md"
        onOrderTypeChange={vi.fn()}
        allowedOrderTypes={["periodic", "cost", "md"]}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
        onDeleteFile={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return onSubmit;
}

function renderCost() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <OrderGroupFormModal
        open
        onOpenChange={vi.fn()}
        group={null}
        clientId={18}
        orderType="cost"
        onOrderTypeChange={vi.fn()}
        allowedOrderTypes={["periodic", "cost", "md"]}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
        onDeleteFile={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

async function readPdf(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(
    screen.getByLabelText(/Wgraj PDF zamówienia/),
    new File(["%PDF-1.7"], "4500030845.pdf", { type: "application/pdf" }),
  );
  await user.click(
    screen.getByRole("button", { name: /Zczytaj i uzupełnij całe zamówienie/ }),
  );
}

describe("Nowe zamówienie z PDF-a — jedno okno", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [], total: 0 },
    } as never);
  });

  it("uzupełnia numer, datę i karty obu konsultantów z opisem źródła", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: BIK_PLAN,
    } as never);
    const user = userEvent.setup();
    renderModal();

    // Wszystkie trzy typy są dostępne — BIK nie jest zablokowany na samym MD.
    expect(screen.getByRole("radio", { name: "Okresowe" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Kosztowe" })).toBeInTheDocument();

    await readPdf(user);

    expect(await screen.findByLabelText(/Numer zamówienia/)).toHaveValue(
      "4500030845",
    );
    expect(screen.getByLabelText(/Obowiązuje od/)).toHaveValue("2026-09-03");

    const suwala = screen.getByRole("article", {
      name: "Konsultant: Krzysztof Suwała",
    });
    expect(within(suwala).getByText("Dopasowano automatycznie")).toBeInTheDocument();
    expect(within(suwala).getByLabelText("Stawka kosztowa")).toHaveValue("148.75");
    expect(within(suwala).getByText("z kontraktu")).toBeInTheDocument();
    expect(within(suwala).getByLabelText("Liczba MD")).toHaveValue("35");
    expect(within(suwala).getAllByText("z PDF, poz. 10")).toHaveLength(2);

    const laski = screen.getByRole("article", { name: "Konsultant: Paweł Łaski" });
    expect(within(laski).getByText("Dopasowano — potwierdź")).toBeInTheDocument();
    expect(within(laski).getByText(/„Active Pawel Laski”/)).toBeInTheDocument();
    expect(screen.getByText("1 z 2 pozycji gotowe do zapisania")).toBeInTheDocument();
    expect(screen.getByText(/91\s560,00\s*zł łącznej wartości/)).toBeInTheDocument();
  });

  it("żółta karta blokuje zapis do potwierdzenia, potem tworzy wszystko jednym wywołaniem", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: BIK_PLAN,
    } as never);
    const user = userEvent.setup();
    const onSubmit = renderModal();

    await readPdf(user);
    const create = await screen.findByRole("button", { name: "Utwórz zamówienie" });
    await waitFor(() => expect(screen.getByLabelText(/Numer zamówienia/)).toHaveValue("4500030845"));
    expect(create).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: "To ta osoba — potwierdzam" }),
    );
    expect(screen.getByText("2 z 2 pozycji gotowe do zapisania")).toBeInTheDocument();
    await user.click(create);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [values, file] = onSubmit.mock.calls[0];
    expect(file).toBeInstanceOf(File);
    expect(values).toMatchObject({
      order_number: "4500030845",
      start_date: "2026-09-03",
      order_type: "md",
      md_budget_mode: "per_person",
      status: "active",
    });
    expect(values.lines).toEqual([
      {
        contract_id: 11,
        rate_candidate_currency: "PLN",
        rate_client_currency: "PLN",
        rate_cost: 148.75,
        rate_revenue: 1080,
        input_mode: "md",
        input_value: 35,
        start_date: "2026-09-03",
        end_date: null,
        document_name: "Krzysztof Suwała",
      },
      {
        contract_id: 12,
        rate_candidate_currency: "PLN",
        rate_client_currency: "PLN",
        rate_cost: 160,
        rate_revenue: 1280,
        input_mode: "md",
        input_value: 42,
        start_date: "2026-09-03",
        end_date: null,
        document_name: "Paweł Łaski",
      },
    ]);
  });

  it("dwie osoby o tym samym nazwisku: system nie wybiera, DL wskazuje kontrakt", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: {
        ...BIK_PLAN,
        lines: [
          line({
            match_status: "ambiguous",
            match_reason:
              "Znaleziono 2 różne osoby o tym imieniu i nazwisku u tego klienta — system nie zgaduje",
            contract: null,
            options: [
              contract({ contract_id: 31, candidate_id: 301, start_date: "2024-03-01" }),
              contract({ contract_id: 32, candidate_id: 302, start_date: "2026-02-01" }),
            ],
          }),
        ],
      },
    } as never);
    const user = userEvent.setup();
    const onSubmit = renderModal();

    await readPdf(user);
    const card = await screen.findByRole("article", {
      name: "Konsultant: Krzysztof Suwała",
    });
    expect(within(card).getByText("Kilka osób — wybierz ręcznie")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Utwórz zamówienie" })).toBeDisabled();

    await user.click(within(card).getByRole("button", { name: /kontrakt #32/ }));
    expect(within(card).getByText("Wskazano ręcznie")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    expect(onSubmit.mock.calls[0][0].lines[0]).toMatchObject({ contract_id: 32 });
  });

  it("brak dopasowania pokazuje najbliższy zapis tylko jako podpowiedź", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: {
        ...BIK_PLAN,
        lines: [
          line({
            document_name: "Jan Kowalski",
            match_status: "none",
            match_reason:
              "Brak kontraktu z tym imieniem i nazwiskiem u tego klienta — system nie koryguje literówek ani nie zgaduje podobieństwa",
            contract: null,
            nearest_names: ["Jan Kowalczyk"],
          }),
        ],
      },
    } as never);
    const user = userEvent.setup();
    renderModal();

    await readPdf(user);
    const card = await screen.findByRole("article", { name: "Konsultant: Jan Kowalski" });
    expect(within(card).getByText("Wymaga ręcznego wskazania")).toBeInTheDocument();
    expect(within(card).getByText(/Najbliższy zapis w kontraktach: „Jan Kowalczyk”/)).toBeInTheDocument();
    expect(within(card).getByText("Wskaż tę osobę ręcznie")).toBeInTheDocument();
    // Ticket 09.2026: czerwona karta daje też jawny wybór — zastąp albo usuń.
    expect(within(card).getByRole("button", { name: "Zastąp kimś innym" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Usuń z zamówienia" })).toBeInTheDocument();
    expect(within(card).getByLabelText("Stawka kosztowa")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Utwórz zamówienie" })).toBeDisabled();
  });

  it("ręczna poprawka zmienia opis źródła na „wpisano ręcznie”", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: { ...BIK_PLAN, lines: [line()] },
    } as never);
    const user = userEvent.setup();
    renderModal();

    await readPdf(user);
    const card = await screen.findByRole("article", {
      name: "Konsultant: Krzysztof Suwała",
    });
    const mdInput = within(card).getByLabelText("Liczba MD");
    await user.clear(mdInput);
    await user.type(mdInput, "30");

    expect(within(card).getByText("wpisano ręcznie")).toBeInTheDocument();
    expect(within(card).getByText("z PDF, poz. 10")).toBeInTheDocument();
  });

  it("wgranie innego PDF-a usuwa karty osób z poprzedniego dokumentu", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: BIK_PLAN,
    } as never);
    const user = userEvent.setup();
    renderModal();

    await readPdf(user);
    expect(
      await screen.findByRole("article", { name: "Konsultant: Krzysztof Suwała" }),
    ).toBeInTheDocument();

    await user.upload(
      screen.getByLabelText(/Wgraj PDF zamówienia/),
      new File(["%PDF-1.7"], "inne.pdf", { type: "application/pdf" }),
    );
    expect(
      screen.queryByRole("article", { name: "Konsultant: Krzysztof Suwała" }),
    ).not.toBeInTheDocument();
  });

  it("kwota zamówienia w obcej walucie nie trafia do budżetu w PLN", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: { ...BIK_PLAN, currency: "EUR", total_value: 20000 },
    } as never);
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <OrderGroupFormModal
          open
          onOpenChange={vi.fn()}
          group={null}
          clientId={18}
          orderType="cost"
          onOrderTypeChange={vi.fn()}
          submitting={false}
          error={null}
          onSubmit={vi.fn()}
          onDeleteFile={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await readPdf(user);
    await screen.findByRole("article", { name: "Konsultant: Krzysztof Suwała" });
    expect(screen.getByLabelText(/Budżet całkowity/)).toHaveValue("");
  });

  it("odczyt drugiego PDF-a zastępuje kwotę i numer z poprzedniego dokumentu bez pytania (UAT M07-B02)", async () => {
    vi.mocked(orderGroupsApi.extractPlan)
      .mockResolvedValueOnce({ data: { ...BIK_PLAN, total_value: 107000 } } as never)
      .mockResolvedValueOnce({
        data: { ...BIK_PLAN, order_number: "QA/003/2026", total_value: 150000 },
      } as never);
    const user = userEvent.setup();
    renderCost();

    await readPdf(user);
    await screen.findByRole("article", { name: "Konsultant: Krzysztof Suwała" });
    expect(screen.getByLabelText(/Budżet całkowity/)).toHaveValue("107000");

    await readPdf(user);
    await waitFor(() =>
      expect(screen.getByLabelText(/Budżet całkowity/)).toHaveValue("150000"),
    );
    expect(screen.getByLabelText(/Numer zamówienia/)).toHaveValue("QA/003/2026");
    // Wartości z poprzedniego PDF-a nie są „wpisane” — nie ma o co pytać.
    expect(screen.queryByText(/wpisano:/)).not.toBeInTheDocument();
  });

  it("kwota wpisana ręcznie nie znika po odczycie — pytanie o rozbieżność", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: { ...BIK_PLAN, total_value: 150000 },
    } as never);
    const user = userEvent.setup();
    renderCost();

    await user.type(screen.getByLabelText(/Budżet całkowity/), "5000");
    await readPdf(user);

    expect(await screen.findByText("Kwota zamówienia")).toBeInTheDocument();
    expect(screen.getByLabelText(/Budżet całkowity/)).toHaveValue("5000");
    await user.click(screen.getByRole("button", { name: /Tak — zapisz dane z dokumentu/ }));
    expect(screen.getByLabelText(/Budżet całkowity/)).toHaveValue("150000");
  });

  it("osoba z zakończoną współpracą: komunikat wprost i zapis jako historia", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: {
        ...BIK_PLAN,
        order_number: "SAP 4500987654",
        start_date: "2026-03-30",
        lines: [
          line({
            document_name: "Odeszły Marian",
            match_status: "inactive",
            match_reason:
              "Odwrotna kolejność; „Odeszły Marian” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.08.2026). Zdecyduj: …",
            contract: contract({
              contract_id: 77,
              candidate_id: 707,
              contractor_name: "Marian Odeszły",
              status: "ended",
              end_date: "2026-08-12",
            }),
          }),
        ],
      },
    } as never);
    const user = userEvent.setup();
    const onSubmit = renderModal();

    await readPdf(user);
    const card = await screen.findByRole("article", { name: "Konsultant: Odeszły Marian" });
    expect(within(card).getByText("Zakończył współpracę")).toBeInTheDocument();
    expect(within(card).getByText(/nie ma już aktywnej współpracy/)).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "Utwórz zamówienie" });
    expect(create).toBeDisabled();

    await user.click(within(card).getByRole("button", { name: "Zostaw jako historię" }));
    expect(within(card).getByText("Zapis historyczny")).toBeInTheDocument();
    expect(within(card).getByText(/bez wznawiania kontraktu/)).toBeInTheDocument();
    await user.click(create);

    const [values] = onSubmit.mock.calls[0];
    expect(values.lines).toEqual([
      expect.objectContaining({
        contract_id: 77,
        historical: true,
        start_date: "2026-03-30",
        end_date: "2026-08-12",
        document_name: "Odeszły Marian",
      }),
    ]);
  });

  it("jedna liczba MD na całe zamówienie ustawia wspólny budżet MD", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: {
        ...BIK_PLAN,
        md_total: 38,
        md_scope: "order",
        lines: BIK_PLAN.lines.map((item) => ({ ...item, md_total: null })),
      },
    } as never);
    const user = userEvent.setup();
    renderModal();

    await readPdf(user);
    await screen.findByRole("article", { name: "Konsultant: Krzysztof Suwała" });
    expect(screen.getByRole("checkbox", { name: /Budżet MD na całe zamówienie/ })).toBeChecked();
    expect(screen.getByText(/jedną liczbę MD na całe zamówienie/)).toBeInTheDocument();
  });
});
