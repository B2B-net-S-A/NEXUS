import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SettlementDetail } from "@/lib/api/client-settlements";

import { SettlementCard } from "../SettlementCard";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  askReason: vi.fn(),
  askConfirm: vi.fn(),
  downloadBlob: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: mocks.put } }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askReason: mocks.askReason, askConfirm: mocks.askConfirm, confirmDialog: null }),
}));
vi.mock("@/lib/authenticated-files", () => ({ downloadBlob: mocks.downloadBlob }));
// Sekcje z własnymi zapytaniami mają swoje testy — tu tylko to, czy karta je pokazuje.
vi.mock("../ExtrasSection", () => ({ ExtrasSection: () => <div data-testid="extras" /> }));
vi.mock("../IntegrationCostsSection", () => ({ IntegrationCostsSection: () => <div data-testid="integration" /> }));
vi.mock("../KesuSection", () => ({ KesuSection: () => <div data-testid="kesu" /> }));
vi.mock("../PanelPreviewDialog", () => ({
  PanelPreviewDialog: ({ person, onClose }: { person: string; onClose: () => void }) => (
    <div role="dialog" aria-label={`Panel ${person}`}>
      <button type="button" onClick={onClose}>
        Zamknij podgląd
      </button>
    </div>
  ),
}));

const BASE_DETAIL: SettlementDetail = {
  contract_id: 41,
  settlement_id: 9,
  person: "Anna Przykładowa",
  client_name: "Firma Testowa sp. z o.o.",
  month: "2026-12",
  order_number: "ZAM/12/2026",
  contract_number: "B2B/7",
  status: "ok",
  fix_reason: null,
  documents: [],
  md_regular: "20.000",
  md_extra: "0",
  md_source: "rcp",
  lines: [],
  total_md: null,
  total_net: null,
  checks: [],
  order: null,
};

function detail(patch: Partial<SettlementDetail> = {}): SettlementDetail {
  return { ...BASE_DETAIL, ...patch };
}

function renderCard(
  data: SettlementDetail | Error,
  props: Partial<React.ComponentProps<typeof SettlementCard>> = {},
) {
  mocks.get.mockImplementation((url: string) => {
    if (url.endsWith("/kcp") || url.includes("/documents/")) return Promise.resolve({ data: new Blob(["x"]) });
    return data instanceof Error ? Promise.reject(data) : Promise.resolve({ data });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onBack = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <SettlementCard contractId={41} month="2026-12" canWrite onBack={onBack} {...props} />
    </QueryClientProvider>,
  );
  return { onBack };
}

describe("SettlementCard: stany zapytania", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("awaria zapytania to komunikat błędu z ponowieniem, nie pusta karta", async () => {
    renderCard(Object.assign(new Error("boom"), { response: { status: 500, data: { detail: "Serwer leży" } } }));
    expect(await screen.findByText(/Serwer leży|Nie udało się pobrać rozliczenia osoby/)).toBeInTheDocument();
    expect(screen.queryByText("Kontrole ruszą, gdy wpłynie RCP.")).not.toBeInTheDocument();
    expect(screen.queryByText("Anna Przykładowa")).not.toBeInTheDocument();
  });

  it("w trakcie ładowania pokazuje „Ładowanie…”", () => {
    mocks.get.mockReturnValue(new Promise(() => {}));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SettlementCard contractId={41} month="2026-12" canWrite onBack={() => {}} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
  });

  it("pobiera kartę osoby z miesiącem i rodzajem rozliczenia", async () => {
    renderCard(detail(), { kind: "estimate" });
    await screen.findByText("Anna Przykładowa");
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements/contract/41", {
      params: { month: "2026-12", kind: "estimate" },
    });
    expect(screen.getByText("Plan miesiąca")).toBeInTheDocument();
    // Plan nie ma sekcji z KSeF i kosztami integracji.
    expect(screen.queryByTestId("integration")).not.toBeInTheDocument();
  });
});

describe("SettlementCard: nagłówek i puste sekcje", () => {
  beforeEach(() => vi.clearAllMocks());

  it("nagłówek łączy klienta, miesiąc grudzień, zamówienie i umowę", async () => {
    const { onBack } = renderCard(detail());
    expect(await screen.findByText("Firma Testowa sp. z o.o. · grudzień 2026 · ZAM/12/2026 · umowa B2B/7")).toBeInTheDocument();
    expect(screen.getByText("Bez uwag")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Wróć do listy miesiąca" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("bez zamówienia i umowy pomija puste części nagłówka", async () => {
    renderCard(detail({ order_number: null, contract_number: null }));
    expect(await screen.findByText("Firma Testowa sp. z o.o. · grudzień 2026")).toBeInTheDocument();
  });

  it("puste dokumenty, wyliczenie i kontrole mają własne komunikaty; brak linii zamówienia ostrzega", async () => {
    renderCard(detail());
    expect(await screen.findByText("Nic jeszcze nie wpłynęło ani panelem, ani mailem.")).toBeInTheDocument();
    expect(screen.getByText("Wyliczenie pojawi się po odczycie RCP.")).toBeInTheDocument();
    expect(screen.getByText("Kontrole ruszą, gdy wpłynie RCP.")).toBeInTheDocument();
    expect(screen.getByText("Brak aktywnej linii zamówienia w tym miesiącu.")).toBeInTheDocument();
    expect(screen.getByTestId("integration")).toBeInTheDocument();
  });
});

describe("SettlementCard: wyliczenie z RCP", () => {
  beforeEach(() => vi.clearAllMocks());

  it("linie, mnożnik w procentach, suma i kreska przy kwocie null", async () => {
    renderCard(
      detail({
        lines: [
          { label: "Dni zwykłe", md: "20", multiplier: "1", rate: "800.00", net: "16000.00" },
          { label: "Nadgodziny", md: "1.5", multiplier: "1.5", rate: "800.00", net: null },
        ],
        total_md: "21.5",
        total_net: "17800.50",
        order: { md_total: "60", md_charged: "21.5", md_remaining_after: "0" },
      }),
    );
    await screen.findByText("Ile wychodzi z RCP");
    expect(screen.getByRole("cell", { name: "Dni zwykłe" })).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("150%")).toBeInTheDocument();
    expect(screen.getByText("16 000,00 zł")).toBeInTheDocument();
    expect(screen.getByText("–")).toBeInTheDocument();
    expect(screen.getByText("Razem")).toBeInTheDocument();
    expect(screen.getByText("17 800,50 zł")).toBeInTheDocument();
    expect(screen.getByText("Zamówienie: 60 MD, zejdzie 21,5 MD, zostanie 0 MD.")).toBeInTheDocument();
  });

  it("ujemna kwota w linii (korekta) ma znak minus", async () => {
    renderCard(
      detail({
        lines: [{ label: "Korekta", md: "-1", multiplier: "1", rate: "800.00", net: "-800.00" }],
        total_md: "-1",
        total_net: "-800.00",
      }),
    );
    await screen.findByText("Korekta");
    expect(screen.getAllByText("−800,00 zł")).toHaveLength(2);
  });
});

describe("SettlementCard: przyjęcie i odesłanie RCP", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.post.mockResolvedValue({ data: {} });
  });

  it("„Przyjmij” woła accept z miesiącem i rodzajem", async () => {
    renderCard(detail());
    fireEvent.click(await screen.findByRole("button", { name: "Przyjmij" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/contract/41/accept", null, {
        params: { month: "2026-12", kind: "actual" },
      }),
    );
    expect(mocks.showSuccess).toHaveBeenCalledWith("RCP przyjęte.");
  });

  it("uwagi z kontroli liczą się w etykiecie przycisku; błędy nie", async () => {
    renderCard(
      detail({
        status: "warnings",
        checks: [
          {
            title: "Kalendarz",
            checks: [
              { state: "warn", title: "Praca w święto", detail: "25.12" },
              { state: "warn", title: "Praca w sobotę", detail: null },
              { state: "fail", title: "Stawka różna od zamówienia", detail: "800,00 zł vs 750,00 zł" },
              { state: "ok", title: "Liczba dni", detail: null },
              { state: "none", title: "Podpis klienta", detail: null },
            ],
          },
        ],
      }),
    );
    expect(await screen.findByRole("button", { name: "Przyjmij z uwagami (2)" })).toBeEnabled();
    expect(screen.getByText("Kalendarz")).toBeInTheDocument();
    expect(screen.getByText("800,00 zł vs 750,00 zł")).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Uwaga" })).toHaveLength(2);
    expect(screen.getByRole("img", { name: "Błąd" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Zgodne" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Nie sprawdzono" })).toBeInTheDocument();
  });

  it("„Brak MD”: przycisk przyjęcia wyłączony, „Do poprawy” dostępne", async () => {
    renderCard(detail({ status: "no_md" }));
    expect(await screen.findByRole("button", { name: "Przyjmij" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Do poprawy" })).toBeEnabled();
  });

  it("przyjęte: „Przyjmij ponownie” bez „Do poprawy”, komunikat o nadpisaniu", async () => {
    renderCard(detail({ status: "accepted" }));
    fireEvent.click(await screen.findByRole("button", { name: "Przyjmij ponownie" }));
    expect(screen.queryByRole("button", { name: "Do poprawy" })).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalledWith("RCP przyjęte ponownie, zejście MD nadpisane."));
    expect(screen.getByText(/Zmiana po przyjęciu wymaga ponownego przyjęcia/)).toBeInTheDocument();
  });

  it("błąd przyjęcia idzie do toasta z treścią z API", async () => {
    mocks.post.mockRejectedValueOnce(Object.assign(new Error("x"), { response: { status: 409, data: { detail: "Zamówienie wyczerpane" } } }));
    renderCard(detail());
    fireEvent.click(await screen.findByRole("button", { name: "Przyjmij" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalled());
    expect(mocks.showSuccess).not.toHaveBeenCalled();
  });

  it.each(["missing", "needs_fix"] as const)("stan %s: brak przycisków decyzji", async (status) => {
    renderCard(detail({ status, fix_reason: status === "needs_fix" ? "Brak podpisu klienta" : null }));
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByRole("button", { name: /Przyjmij/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Do poprawy" })).not.toBeInTheDocument();
    if (status === "needs_fix") expect(screen.getByText("Odesłane do poprawy: Brak podpisu klienta")).toBeInTheDocument();
  });

  it("bez prawa zapisu: brak decyzji i formularza MD", async () => {
    renderCard(detail(), { canWrite: false });
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByRole("button", { name: /Przyjmij/ })).not.toBeInTheDocument();
    expect(screen.queryByText("MD z RCP")).not.toBeInTheDocument();
  });

  it("„Do poprawy” wysyła powód z pytania", async () => {
    mocks.askReason.mockResolvedValueOnce("Brak podpisu klienta");
    renderCard(detail());
    fireEvent.click(await screen.findByRole("button", { name: "Do poprawy" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/finance/settlements/contract/41/needs-fix",
        { reason: "Brak podpisu klienta" },
        { params: { month: "2026-12", kind: "actual" } },
      ),
    );
    expect(mocks.askReason).toHaveBeenCalledWith(expect.objectContaining({ field: expect.objectContaining({ minLength: 5 }) }));
    expect(mocks.showSuccess).toHaveBeenCalledWith("Odesłano do poprawy.");
  });

  it("anulowane pytanie o powód niczego nie wysyła", async () => {
    mocks.askReason.mockResolvedValueOnce(null);
    renderCard(detail());
    fireEvent.click(await screen.findByRole("button", { name: "Do poprawy" }));
    await waitFor(() => expect(mocks.askReason).toHaveBeenCalled());
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("błąd odesłania do poprawy idzie do toasta", async () => {
    mocks.askReason.mockResolvedValueOnce("Brak podpisu klienta");
    mocks.post.mockRejectedValueOnce(new Error("x"));
    renderCard(detail());
    fireEvent.click(await screen.findByRole("button", { name: "Do poprawy" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się odesłać RCP."));
  });
});

describe("SettlementCard: informacje o planie i automacie", () => {
  beforeEach(() => vi.clearAllMocks());

  it("przyjęty plan miesiąca mówi, ile MD poszło na fakturę", async () => {
    renderCard(detail({ estimate: { status: "accepted", md_regular: "20", md_charged: "18.5" } }));
    expect(await screen.findByText(/Za ten miesiąc przyjęto plan: 18,5 MD/)).toBeInTheDocument();
  });

  it("plan nieprzyjęty nie pokazuje paska", async () => {
    renderCard(detail({ estimate: { status: "ok", md_regular: "20", md_charged: null } }));
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByText(/przyjęto plan/)).not.toBeInTheDocument();
  });

  it("przyjęcie przez automat pokazuje dzień i godzinę z zapisu", async () => {
    renderCard(detail({ status: "accepted", accepted_auto: true, accepted_at: "2027-01-05T07:10:00+01:00" }));
    expect(await screen.findByText(/Przyjął automat 05\.01 07:10/)).toBeInTheDocument();
  });

  it("automat bez daty przyjęcia nie dokleja pustej godziny", async () => {
    renderCard(detail({ status: "accepted", accepted_auto: true, accepted_at: null }));
    expect(await screen.findByText(/^Przyjął automat \(reguła klienta/)).toBeInTheDocument();
  });
});

describe("SettlementCard: formularz MD", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.put.mockResolvedValue({ data: {} });
  });

  it("wartości z API bez zer po przecinku; zero nadgodzin to puste pole", async () => {
    renderCard(detail({ md_regular: "20.000", md_extra: "0.000" }));
    const regular = await screen.findByLabelText("Dni zwykłe");
    await waitFor(() => expect(regular).toHaveValue("20"));
    expect(screen.getByLabelText("Praca dodatkowa (MD)")).toHaveValue("");
    expect(screen.getByText("odczytane z pliku")).toBeInTheDocument();
  });

  it("przecinek dziesiętny zamienia na kropkę, puste nadgodziny wysyła jako null", async () => {
    renderCard(detail({ md_source: "manual" }));
    const regular = await screen.findByLabelText("Dni zwykłe");
    expect(screen.getByText("wpisane ręcznie, odczyt pliku ich nie zmienia")).toBeInTheDocument();
    fireEvent.change(regular, { target: { value: " 19,5 " } });
    fireEvent.click(screen.getByRole("button", { name: "Przelicz" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(
        "/api/finance/settlements/contract/41/md",
        { md_regular: "19.5", md_extra: null },
        { params: { month: "2026-12", kind: "actual" } },
      ),
    );
    expect(mocks.showSuccess).toHaveBeenCalledWith("MD zapisane, rozliczenie przeliczone.");
  });

  it("nadgodziny z przecinkiem idą jako liczba z kropką", async () => {
    renderCard(detail());
    fireEvent.change(await screen.findByLabelText("Praca dodatkowa (MD)"), { target: { value: "0,25" } });
    fireEvent.click(screen.getByRole("button", { name: "Przelicz" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(
        "/api/finance/settlements/contract/41/md",
        { md_regular: "20", md_extra: "0.25" },
        expect.anything(),
      ),
    );
  });

  it("puste albo nieliczbowe dni zwykłe blokują „Przelicz”", async () => {
    renderCard(detail({ md_regular: null, md_source: null }));
    const regular = await screen.findByLabelText("Dni zwykłe");
    expect(screen.getByRole("button", { name: "Przelicz" })).toBeDisabled();
    fireEvent.change(regular, { target: { value: "abc" } });
    expect(screen.getByRole("button", { name: "Przelicz" })).toBeDisabled();
    fireEvent.change(regular, { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "Przelicz" })).toBeEnabled();
  });

  it("błąd zapisu MD idzie do toasta", async () => {
    mocks.put.mockRejectedValueOnce(new Error("x"));
    renderCard(detail());
    await screen.findByLabelText("Dni zwykłe");
    fireEvent.click(screen.getByRole("button", { name: "Przelicz" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się zapisać MD."));
  });
});

describe("SettlementCard: dokumenty, KCP i sekcje dodatkowe", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lista dokumentów: rodzaj, kanał, data; klik pobiera plik", async () => {
    renderCard(
      detail({
        documents: [
          { id: 1, kind: "report", file_name: "rcp-grudzien.xlsx", channel: "portal", mime: "application/xlsx", received_at: "2027-01-02T09:00:00Z" },
          { id: 2, kind: "report", file_name: null, channel: "mailbox", mime: "message/rfc822", received_at: "2027-01-03T09:00:00Z" },
          { id: 3, kind: "invoice", file_name: "fv.pdf", channel: "mailbox", mime: "application/pdf", received_at: "2027-01-04T09:00:00Z" },
        ],
      }),
    );
    expect(await screen.findByText("rcp-grudzien.xlsx")).toBeInTheDocument();
    expect(screen.getByText(/RCP · panel · 2\.01\.2027/)).toBeInTheDocument();
    expect(screen.getByText(/Mail · mail · 3\.01\.2027/)).toBeInTheDocument();
    expect(screen.getByText(/Faktura · mail · 4\.01\.2027/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Plik bez nazwy" }));
    await waitFor(() => expect(mocks.downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "dokument-2"));
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements/contract/41/documents/2", { responseType: "blob" });
  });

  it("błąd pobrania dokumentu idzie do toasta", async () => {
    renderCard(
      detail({
        documents: [{ id: 5, kind: "report", file_name: "rcp.xlsx", channel: "portal", mime: "x", received_at: "2027-01-02T09:00:00Z" }],
      }),
    );
    await screen.findByText("rcp.xlsx");
    mocks.get.mockRejectedValueOnce(new Error("x"));
    fireEvent.click(screen.getByRole("button", { name: "rcp.xlsx" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się pobrać pliku."));
  });

  it("KCP w PDF pobiera się z miesiącem karty", async () => {
    renderCard(detail({ kcp_pdf: true }));
    fireEvent.click(await screen.findByRole("button", { name: /KCP \(PDF\)/ }));
    await waitFor(() => expect(mocks.downloadBlob).toHaveBeenCalled());
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements/contract/41/kcp", {
      params: { month: "2026-12" },
      responseType: "blob",
    });
  });

  it("błąd pobrania KCP idzie do toasta", async () => {
    renderCard(detail({ kcp_pdf: true }));
    const button = await screen.findByRole("button", { name: /KCP \(PDF\)/ });
    mocks.get.mockRejectedValueOnce(new Error("x"));
    fireEvent.click(button);
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się pobrać KCP."));
  });

  it("bez KCP nie ma przycisku pobrania", async () => {
    renderCard(detail());
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByRole("button", { name: /KCP \(PDF\)/ })).not.toBeInTheDocument();
  });

  it("podgląd panelu konsultanta otwiera się i zamyka", async () => {
    renderCard(detail());
    fireEvent.click(await screen.findByRole("button", { name: "Zobacz panel jak konsultant" }));
    expect(screen.getByRole("dialog", { name: "Panel Anna Przykładowa" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij podgląd" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("KEŚU, dodatki i faktura kontraktora tylko dla rozliczenia faktycznego", async () => {
    const extra = {
      kesu: { state: "to_company", state_label: "x", approver: null, accepted_at: null, hours: null, days: null } as never,
      extras: { items: [] } as never,
      contractor_invoice: { state: "none" as const, invoices: [], checks: [] },
    };
    renderCard(detail(extra));
    expect(await screen.findByTestId("kesu")).toBeInTheDocument();
    expect(screen.getByTestId("extras")).toBeInTheDocument();
    expect(screen.getByText("Faktura kontraktora")).toBeInTheDocument();
    expect(screen.getByText("W KSeF nie ma jeszcze faktury za ten miesiąc.")).toBeInTheDocument();
  });

  it("plan miesiąca chowa KEŚU, dodatki i fakturę kontraktora", async () => {
    renderCard(
      detail({
        kesu: { state: "to_company" } as never,
        extras: { items: [] } as never,
        contractor_invoice: { state: "none", invoices: [], checks: [] },
      }),
      { kind: "estimate" },
    );
    await screen.findByText("Anna Przykładowa");
    expect(screen.queryByTestId("kesu")).not.toBeInTheDocument();
    expect(screen.queryByTestId("extras")).not.toBeInTheDocument();
    expect(screen.queryByText("Faktura kontraktora")).not.toBeInTheDocument();
  });
});

describe("ContractorInvoiceSection: odrzucenie podpowiedzi NIP-u", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.post.mockResolvedValue({ data: {} });
  });

  const block = {
    state: "nip_check" as const,
    invoices: [
      {
        id: 8,
        ksef_number: "KSEF-TEST-0001",
        invoice_number: null,
        issue_date: null,
        acquired_at: "2027-01-03T10:00:00+00:00",
        seller_name: null,
        seller_nip: "0000000000",
        nip_state: "suggested" as const,
        net_amount: "0.00",
        gross_amount: "0.00",
        due_date: null,
      },
    ],
    checks: [{ state: "warn" as const, title: "NIP z KSeF do zatwierdzenia", detail: null }],
  };

  it("bez numeru faktury pokazuje numer KSeF, zero zł netto i „bez nazwy”; kontrola NIP-u schowana", async () => {
    renderCard(detail({ contractor_invoice: block }));
    expect(await screen.findByText("KSEF-TEST-0001")).toBeInTheDocument();
    expect(screen.getByText("0,00 zł netto")).toBeInTheDocument();
    expect(screen.getByText(/Sprzedawca: bez nazwy\./)).toBeInTheDocument();
    expect(screen.queryByText("NIP z KSeF do zatwierdzenia")).not.toBeInTheDocument();
  });

  it("„To nie ta osoba” po potwierdzeniu woła reject-nip", async () => {
    mocks.askConfirm.mockResolvedValueOnce(true);
    renderCard(detail({ contractor_invoice: block }));
    fireEvent.click(await screen.findByRole("button", { name: "To nie ta osoba" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/contractor-invoices/8/reject-nip"),
    );
    expect(mocks.askConfirm).toHaveBeenCalledWith(expect.objectContaining({ variant: "destructive" }));
    expect(mocks.showSuccess).toHaveBeenCalledWith("Podpowiedź odrzucona.");
  });

  it("anulowane potwierdzenie niczego nie wysyła", async () => {
    mocks.askConfirm.mockResolvedValueOnce(false);
    renderCard(detail({ contractor_invoice: block }));
    fireEvent.click(await screen.findByRole("button", { name: "Zatwierdź NIP" }));
    await waitFor(() => expect(mocks.askConfirm).toHaveBeenCalled());
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("błąd decyzji idzie do toasta", async () => {
    mocks.askConfirm.mockResolvedValueOnce(true);
    mocks.post.mockRejectedValueOnce(new Error("x"));
    renderCard(detail({ contractor_invoice: block }));
    fireEvent.click(await screen.findByRole("button", { name: "Zatwierdź NIP" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się zapisać decyzji."));
  });
});
