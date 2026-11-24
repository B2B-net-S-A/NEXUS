import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SettlementMonth, SettlementRow } from "@/lib/api/client-settlements";

import { SettlementMonthView } from "../SettlementMonthView";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  askConfirm: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: vi.fn() } }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.askConfirm, askReason: vi.fn(), confirmDialog: null }),
}));
// Panele z własnymi zapytaniami mają osobne testy.
vi.mock("../../month-close/ClientMonthStrip", () => ({ ClientMonthStrip: () => <div data-testid="strip" /> }));
vi.mock("../ClientAcceptancePanel", () => ({ ClientAcceptancePanel: () => <div data-testid="acceptance" /> }));
vi.mock("../ClientDocumentsPanel", () => ({ ClientDocumentsPanel: () => <div data-testid="documents" /> }));
vi.mock("../ReportReminders", () => ({
  ReportReminderButton: () => <button type="button">Przypomnij o RCP</button>,
  ReportReminderNotice: () => <p>Przypomnienia o brakującym RCP</p>,
}));

function row(patch: Partial<SettlementRow> = {}): SettlementRow {
  return {
    contract_id: 1,
    settlement_id: 1,
    person: "Anna Przykładowa",
    order_number: "ZAM/1/2026",
    status: "ok",
    issues: null,
    md_regular: "20",
    md_extra: null,
    md_charged: "20",
    md_remaining_after: "40",
    amount_cost: "16000.00",
    amount_revenue: "20000.00",
    margin: "4000.00",
    margin_pct: "20",
    contractor_invoice: "none",
    client_invoice: "waiting",
    ...patch,
  };
}

function month(patch: Partial<SettlementMonth> = {}): SettlementMonth {
  return {
    client_id: 7,
    client_name: "Firma Testowa sp. z o.o.",
    month: "2026-12",
    can_see_amounts: true,
    counts: { todo: 1, missing: 0, needs_fix: 0, accepted: 0, all: 1 },
    batch_ready: 1,
    auto_accept: null,
    rows: [row()],
    ...patch,
  };
}

function renderView(data: SettlementMonth | Error, props: Partial<React.ComponentProps<typeof SettlementMonthView>> = {}) {
  mocks.get.mockImplementation(() => (data instanceof Error ? Promise.reject(data) : Promise.resolve({ data })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onOpen = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <SettlementMonthView clientId={7} month="2026-12" canWrite onOpen={onOpen} {...props} />
    </QueryClientProvider>,
  );
  return { onOpen };
}

describe("SettlementMonthView: stany zapytania", () => {
  beforeEach(() => vi.clearAllMocks());

  it("awaria zapytania to komunikat błędu, nie „nie ma aktywnych kontraktów”", async () => {
    renderView(new Error("boom"));
    expect(await screen.findByText("Nie udało się pobrać rozliczeń miesiąca.")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma w/)).not.toBeInTheDocument();
  });

  it("ładowanie", () => {
    mocks.get.mockReturnValue(new Promise(() => {}));
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <SettlementMonthView clientId={7} month="2026-12" canWrite onOpen={() => {}} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
  });

  it("pusty miesiąc po udanym zapytaniu mówi o braku kontraktów w grudniu", async () => {
    renderView(month({ rows: [], counts: { todo: 0, missing: 0, needs_fix: 0, accepted: 0, all: 0 }, batch_ready: 0 }));
    expect(await screen.findByText("Firma Testowa sp. z o.o. nie ma w grudzień 2026 aktywnych kontraktów.")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements", { params: { client_id: 7, month: "2026-12" } });
  });
});

describe("SettlementMonthView: tabela", () => {
  beforeEach(() => vi.clearAllMocks());

  it("kwoty netto, marża z procentem i odjęta integracja", async () => {
    renderView(month({ rows: [row({ integration_cost: "500.00" })] }));
    expect(await screen.findByText("16 000,00 zł")).toBeInTheDocument();
    expect(screen.getByText("4 000,00 zł")).toBeInTheDocument();
    expect(screen.getByText("20,0%")).toBeInTheDocument();
    expect(screen.getByText("w tym −500,00 zł integracja")).toBeInTheDocument();
  });

  it("bez dostępu do kwot nie ma kolumn Netto i Marża", async () => {
    renderView(month({ can_see_amounts: false, rows: [row({ amount_cost: null, margin: null })] }));
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByRole("columnheader", { name: "Netto" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Marża" })).not.toBeInTheDocument();
  });

  it("null w kwotach i MD to kreska; ujemna marża ma minus", async () => {
    renderView(
      month({
        rows: [row({ md_regular: null, md_remaining_after: null, amount_cost: null, margin: "-250.00", margin_pct: null })],
      }),
    );
    await screen.findByText("Anna Przykładowa");
    expect(screen.getAllByText("–").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("−250,00 zł")).toBeInTheDocument();
  });

  it("mało MD w zamówieniu (≤ 21) podświetla „Zostanie MD”, więcej nie", async () => {
    renderView(
      month({
        counts: { todo: 2, missing: 0, needs_fix: 0, accepted: 0, all: 2 },
        rows: [
          row({ contract_id: 1, md_remaining_after: "21" }),
          row({ contract_id: 2, person: "Jan Testowy", md_remaining_after: "22" }),
        ],
      }),
    );
    expect(await screen.findByText("21")).toHaveClass("text-destructive");
    expect(screen.getByText("22")).not.toHaveClass("text-destructive");
  });

  it("nadgodziny, brak numeru zamówienia, opiekun KEŚU i automat", async () => {
    renderView(
      month({
        counts: { todo: 1, missing: 0, needs_fix: 0, accepted: 0, all: 1 },
        rows: [
          row({
            md_extra: "1.5",
            order_number: null,
            accepted_auto: true,
            kesu: { state: "awaiting_client", state_label: "", approver: "Jan Testowy", accepted_at: null, hours: null, days: null },
          }),
        ],
      }),
    );
    expect(await screen.findByText("+1,5 nadg.")).toBeInTheDocument();
    expect(screen.getByText("Brak numeru zamówienia")).toBeInTheDocument();
    expect(screen.getByText("Opiekun: Jan Testowy")).toBeInTheDocument();
    expect(screen.getByText("przyjął automat")).toBeInTheDocument();
    expect(screen.getByText("KEŚU: czeka na podpis klienta")).toBeInTheDocument();
  });

  it("zero nadgodzin nie dokleja „+0 nadg.”", async () => {
    renderView(month({ rows: [row({ md_extra: "0" })] }));
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByText(/nadg\./)).not.toBeInTheDocument();
  });

  it("stan RCP: błąd, uwaga, brak MD i nieodczytany plik", async () => {
    renderView(
      month({
        counts: { todo: 4, missing: 0, needs_fix: 0, accepted: 0, all: 4 },
        rows: [
          row({ contract_id: 1, status: "warnings", issue_level: "fail", issues: "Stawka inna niż w zamówieniu" }),
          row({ contract_id: 2, person: "B", status: "warnings", issue_level: "warn" }),
          row({ contract_id: 3, person: "C", status: "no_md" }),
          row({ contract_id: 4, person: "D", status: "checking" }),
        ],
      }),
    );
    expect(await screen.findByText("Błąd")).toBeInTheDocument();
    expect(screen.getByText("Stawka inna niż w zamówieniu")).toBeInTheDocument();
    expect(screen.getByText("Uwaga")).toBeInTheDocument();
    expect(screen.getByText("Zamówienie bez MD")).toBeInTheDocument();
    expect(screen.getByText("Nieodczytany plik")).toBeInTheDocument();
  });

  it("faktura do klienta wystawiona przed przyjęciem RCP to ostrzeżenie", async () => {
    renderView(
      month({
        counts: { todo: 1, missing: 0, needs_fix: 0, accepted: 1, all: 2 },
        rows: [row({ contract_id: 1, client_invoice: "issued" })],
      }),
    );
    expect(await screen.findByText("Wystawiona")).toBeInTheDocument();
    expect(screen.getByText("przed przyjęciem RCP")).toBeInTheDocument();
  });

  it("faktura wystawiona przy przyjętym RCP nie ostrzega", async () => {
    renderView(
      month({
        counts: { todo: 0, missing: 0, needs_fix: 0, accepted: 1, all: 1 },
        rows: [row({ status: "accepted", client_invoice: "issued" })],
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Przyjęte/ }));
    expect(screen.getByText("Wystawiona")).toBeInTheDocument();
    expect(screen.queryByText("przed przyjęciem RCP")).not.toBeInTheDocument();
  });

  it("dodatki: jeden i kilka do zatwierdzenia", async () => {
    renderView(
      month({
        counts: { todo: 2, missing: 0, needs_fix: 0, accepted: 0, all: 2 },
        rows: [
          row({ contract_id: 1, extras_pending: 1 }),
          row({ contract_id: 2, person: "Jan Testowy", extras_pending: 3 }),
        ],
      }),
    );
    expect(await screen.findByText("1 dodatek do zatwierdzenia")).toBeInTheDocument();
    expect(screen.getByText("Dodatki do zatwierdzenia: 3")).toBeInTheDocument();
  });

  it("akceptacja klienta: wysłana z dniem wysyłki, zaakceptowana z dniem akceptacji i odpowiedzią", async () => {
    renderView(
      month({
        counts: { todo: 2, missing: 0, needs_fix: 0, accepted: 0, all: 2 },
        rows: [
          row({ contract_id: 1, client_acceptance: { state: "sent", sent_at: "2027-01-04T10:00:00+01:00", accepted_at: null, reply: null, source: null } }),
          row({
            contract_id: 2,
            person: "Jan Testowy",
            client_acceptance: { state: "accepted", sent_at: "2027-01-04T10:00:00+01:00", accepted_at: "2027-01-06T09:00:00+01:00", reply: "Akceptuję", source: "mail" },
          }),
          row({ contract_id: 3, person: "C", client_acceptance: { state: "none", sent_at: null, accepted_at: null, reply: null, source: null } }),
        ],
      }),
    );
    expect(await screen.findByText("Klient: wysłana, czeka 04.01")).toBeInTheDocument();
    expect(screen.getByText("Klient: zaakceptowana 06.01")).toBeInTheDocument();
    expect(screen.getByText("Akceptuję")).toBeInTheDocument();
  });

  it("klik w osobę otwiera jej kartę", async () => {
    const { onOpen } = renderView(month({ rows: [row({ contract_id: 55 })] }));
    fireEvent.click(await screen.findByRole("button", { name: "Anna Przykładowa" }));
    expect(onOpen).toHaveBeenCalledWith(55);
  });
});

describe("SettlementMonthView: filtry i wyszukiwanie", () => {
  beforeEach(() => vi.clearAllMocks());

  const data = () =>
    month({
      counts: { todo: 2, missing: 1, needs_fix: 1, accepted: 1, all: 5 },
      rows: [
        row({ contract_id: 1, person: "Anna Przykładowa", status: "ok", order_number: "ZAM/A" }),
        row({ contract_id: 2, person: "Jan Testowy", status: "missing", order_number: "ZAM/B" }),
        row({ contract_id: 3, person: "Ewa Fikcyjna", status: "needs_fix", order_number: null }),
        row({ contract_id: 4, person: "Piotr Próbny", status: "accepted" }),
        row({ contract_id: 5, person: "Ola Zmyślona", status: "accepted", contractor_invoice: "differs" }),
      ],
    });

  it("domyślnie „Do zrobienia”: RCP do decyzji i faktura z inną kwotą", async () => {
    renderView(data());
    await screen.findByText("Anna Przykładowa");
    expect(screen.getByRole("button", { name: /Do zrobienia/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Ola Zmyślona")).toBeInTheDocument();
    expect(screen.queryByText("Jan Testowy")).not.toBeInTheDocument();
    expect(screen.queryByText("Piotr Próbny")).not.toBeInTheDocument();
  });

  it("filtr „Brak RCP” pokazuje przypomnienie; liczniki z serwera", async () => {
    renderView(data());
    await screen.findByText("Anna Przykładowa");
    const missing = screen.getByRole("button", { name: "Brak RCP 1" });
    fireEvent.click(missing);
    expect(missing).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Jan Testowy")).toBeInTheDocument();
    expect(screen.queryByText("Anna Przykładowa")).not.toBeInTheDocument();
    expect(screen.getByText("Przypomnienia o brakującym RCP")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przypomnij o RCP" })).toBeInTheDocument();
  });

  it("brak licznika w odpowiedzi to 0, nie pusty napis", async () => {
    renderView(month({ counts: { todo: 1 } as SettlementMonth["counts"] }));
    expect(await screen.findByRole("button", { name: "Wszyscy 0" })).toBeInTheDocument();
  });

  it("filtr bez wyników mówi „Nic w tym filtrze.”", async () => {
    renderView(month({ counts: { todo: 1, missing: 0, needs_fix: 0, accepted: 0, all: 1 } }));
    await screen.findByText("Anna Przykładowa");
    fireEvent.click(screen.getByRole("button", { name: /^U konsultanta/ }));
    expect(screen.getByText("Nic w tym filtrze.")).toBeInTheDocument();
  });

  it("szukanie po osobie i numerze zamówienia, bez wielkości liter", async () => {
    renderView(data());
    await screen.findByText("Anna Przykładowa");
    fireEvent.click(screen.getByRole("button", { name: /^Wszyscy/ }));
    const search = screen.getByLabelText("Szukaj osoby albo zamówienia");
    fireEvent.change(search, { target: { value: "  zam/b " } });
    expect(screen.getByText("Jan Testowy")).toBeInTheDocument();
    expect(screen.queryByText("Anna Przykładowa")).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "EWA" } });
    expect(screen.getByText("Ewa Fikcyjna")).toBeInTheDocument();
    expect(screen.queryByText("Jan Testowy")).not.toBeInTheDocument();
  });
});

describe("SettlementMonthView: przyjęcie zbiorcze", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.post.mockResolvedValue({ data: { accepted: 3 } });
  });

  it("po potwierdzeniu wysyła klienta i miesiąc, toast z liczbą przyjętych", async () => {
    mocks.askConfirm.mockResolvedValueOnce(true);
    renderView(month({ batch_ready: 3 }));
    fireEvent.click(await screen.findByRole("button", { name: "Przyjmij RCP bez uwag (3)" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/accept-batch", {
        client_id: 7,
        month: "2026-12",
        kind: "actual",
      }),
    );
    expect(mocks.askConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Przyjąć 3 RCP bez uwag?", description: expect.stringContaining("grudzień 2026") }),
    );
    expect(mocks.showSuccess).toHaveBeenCalledWith("Przyjęto 3 RCP.");
  });

  it("anulowanie niczego nie wysyła", async () => {
    mocks.askConfirm.mockResolvedValueOnce(false);
    renderView(month());
    fireEvent.click(await screen.findByRole("button", { name: "Przyjmij RCP bez uwag (1)" }));
    await waitFor(() => expect(mocks.askConfirm).toHaveBeenCalled());
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("błąd przyjęcia idzie do toasta", async () => {
    mocks.askConfirm.mockResolvedValueOnce(true);
    mocks.post.mockRejectedValueOnce(new Error("x"));
    renderView(month());
    fireEvent.click(await screen.findByRole("button", { name: "Przyjmij RCP bez uwag (1)" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się przyjąć RCP."));
  });

  it("zero gotowych: przycisk wyłączony", async () => {
    renderView(month({ batch_ready: 0 }));
    expect(await screen.findByRole("button", { name: "Przyjmij RCP bez uwag (0)" })).toBeDisabled();
  });

  it("bez prawa zapisu: brak przyjęcia zbiorczego i przypomnień", async () => {
    renderView(month({ counts: { todo: 1, missing: 2, needs_fix: 0, accepted: 0, all: 3 } }), { canWrite: false });
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByRole("button", { name: /Przyjmij RCP bez uwag/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Przypomnij o RCP" })).not.toBeInTheDocument();
  });
});

describe("SettlementMonthView: paski nad tabelą", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("automat przyjęć: termin w przyszłości po przełomie roku", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-12-30T10:00:00+01:00"));
    renderView(month({ auto_accept: { count: 3, workday: 2, from: "2027-01-05" } }));
    expect(await screen.findByRole("status")).toHaveTextContent("3 RCP bez uwag przyjmą się same od 05.01 rano.");
  });

  it("automat przyjęć: termin minął, najbliższy poranny bieg", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2027-01-08T10:00:00+01:00"));
    renderView(month({ auto_accept: { count: 1, workday: 2, from: "2027-01-05" } }));
    expect(await screen.findByRole("status")).toHaveTextContent("1 RCP bez uwag przyjmie się samo przy najbliższym porannym biegu");
  });

  it("KEŚU: liczniki stanów i liczba gotowych do faktury", async () => {
    const kesu = (state: "to_company" | "awaiting_client" | "signed") => ({
      state,
      state_label: "",
      approver: null,
      accepted_at: null,
      hours: null,
      days: null,
    });
    renderView(
      month({
        counts: { todo: 0, missing: 0, needs_fix: 0, accepted: 3, all: 3 },
        rows: [
          row({ contract_id: 1, kesu: kesu("signed"), client_invoice: "ready" }),
          row({ contract_id: 2, kesu: kesu("signed"), client_invoice: "ready" }),
          row({ contract_id: 3, kesu: kesu("to_company") }),
        ],
      }),
    );
    const bar = await screen.findByRole("region", { name: "KEŚU w miesiącu" });
    expect(within(bar).getByText(/Oba podpisy/)).toHaveTextContent("Oba podpisy: 2");
    expect(within(bar).getByText(/Do podpisu spółki/)).toHaveTextContent("Do podpisu spółki: 1");
    expect(within(bar).getByText(/Czeka na podpis klienta/)).toHaveTextContent("Czeka na podpis klienta: 0");
    expect(within(bar).getByText(/Do faktury dla klienta/)).toHaveTextContent("Do faktury dla klienta: 2");
  });

  it("bez KEŚU nie ma paska", async () => {
    renderView(month());
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByRole("region", { name: "KEŚU w miesiącu" })).not.toBeInTheDocument();
  });
});
