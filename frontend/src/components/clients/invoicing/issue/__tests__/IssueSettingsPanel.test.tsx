import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, put: mocks.put, post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/clients/ClientSinglePicker", () => ({
  ClientSinglePicker: ({ onChange }: { onChange: (c: { id: number; name: string }) => void }) => (
    <button type="button" onClick={() => onChange({ id: 42, name: "Firma Testowa sp. z o.o." })}>
      Wybierz klienta testowego
    </button>
  ),
}));
vi.mock("../ClientRebateEditor", () => ({
  ClientRebateEditor: ({ label, value, onChange }: { label: string; value: unknown; onChange: (v: unknown) => void }) => (
    <button type="button" onClick={() => onChange(value ? undefined : { threshold_currency: "PLN", periods: [], exclude_words: [] })}>
      {value ? `Usuń rabat — ${label}` : `Dodaj rabat — ${label}`}
    </button>
  ),
}));
vi.mock("../ClientBuyersEditor", () => ({
  ClientBuyersEditor: ({ label, buyers, mappedContracts, onChange }: { label: string; buyers: unknown[]; mappedContracts: number; onChange: (b: unknown[]) => void }) => (
    <button type="button" onClick={() => onChange([])}>
      Wyczyść nabywców — {label} ({buyers.length}/{mappedContracts})
    </button>
  ),
}));

import { IssueSettingsPanel } from "../IssueSettingsPanel";
import type { IssueSettings, IssueSettingsPayload } from "@/lib/api/issued-invoices";

const EMPTY_ACCOUNT = { number: "", bank: "", swift: "" };

function settings(overrides: Partial<IssueSettings> = {}): IssueSettings {
  return {
    seller: { name: "Firma Testowa sp. z o.o.", nip: "0000000000", address_l1: "ul. Przykładowa 1, 00-001 Warszawa", address_l2: "", issue_place: "Warszawa" },
    accounts: {
      PLN: { number: "PL00 0000 0000 0000 0000 0000 0000", bank: "Bank Testowy", swift: "" },
      EUR: { ...EMPTY_ACCOUNT },
      USD: { ...EMPTY_ACCOUNT },
    },
    payment_days: 30,
    default_vat: "23",
    exemption_basis: "",
    service_name: "Usługi IT",
    series: { PL: "{n}/{mm}/{yyyy}", UE: "UE/{n}/{mm}/{yyyy}", ZAL: "ZAL/{n}", KOR: "KOR/{n}", BEN: "BEN/{n}", KORUE: "KORUE/{n}" },
    clients: {
      "7": {
        vat_rate: "np",
        payment_days: 45,
        accounts: { EUR: { number: "PL11 1111", bank: "Bank EUR", swift: "" } },
        rebate: { threshold_currency: "EUR", periods: [], exclude_words: [] },
        buyers: [{ name: "Oddział Testowy" } as never],
        contract_buyers: { "501": [{ code: "A", from: "2026-01" }] },
      },
    },
    ...overrides,
  } as IssueSettings;
}

function payload(overrides: Partial<IssueSettingsPayload> = {}): IssueSettingsPayload {
  return {
    settings: settings(),
    client_names: { "7": "Klient Testowy S.A." },
    series: [
      { code: "PL", pattern: "{n}/{mm}/{yyyy}", next_number: 12, next_label: "12/01/2027", highest_issued: 11 },
      { code: "UE", pattern: "UE/{n}/{mm}/{yyyy}", next_number: 1, next_label: "UE/1/01/2027", highest_issued: null },
    ],
    series_period: "2027-01",
    series_labels: { PL: "Krajowa", UE: "Unijna", ZAL: "Zaliczka", KOR: "Korekta", BEN: "BEN", KORUE: "Korekta UE" },
    vat_rates: [
      { code: "23", label: "23%" },
      { code: "8", label: "8%" },
      { code: "zw", label: "zw." },
      { code: "np", label: "np." },
    ],
    ksef: { mode: "test", mode_label: "środowisko testowe", enabled: true, disabled_reason: null },
    missing: [],
    ...overrides,
  };
}

function route(data: IssueSettingsPayload | Error) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url !== "/api/finance/issued-invoices/settings") throw new Error(`nieoczekiwane ${url}`);
    if (data instanceof Error) throw data;
    return { data };
  });
}

function renderPanel(period = "2027-01") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IssueSettingsPanel period={period} />
    </QueryClientProvider>,
  );
}

function savedBody() {
  return mocks.put.mock.calls.find(([url]) => url === "/api/finance/issued-invoices/settings")?.[1] as IssueSettings;
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.put.mockReset();
  mocks.toast.mockReset();
});

describe("IssueSettingsPanel — wczytanie", () => {
  it("pyta o ustawienia z rokiem i miesiącem okresu", async () => {
    route(payload());
    renderPanel("2027-01");
    await screen.findByLabelText("Nazwa");
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/issued-invoices/settings", { params: { year: 2027, month: 1 } });
  });

  it("awaria to błąd z ponowieniem, nie pusty formularz", async () => {
    route(new Error("500"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByLabelText("Nazwa")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz ustawienia" })).not.toBeInTheDocument();
  });

  it("KSeF wyłączony: powód i lista braków do wysyłki", async () => {
    route(
      payload({
        ksef: { mode: "off", mode_label: "wyłączona", enabled: false, disabled_reason: "Brak tokenu KSeF w ustawieniach." },
        missing: ["NIP sprzedawcy", "rachunek PLN"],
      }),
    );
    renderPanel();
    expect(await screen.findByText("Wysyłka do KSeF: wyłączona")).toBeInTheDocument();
    expect(screen.getByText("Brak tokenu KSeF w ustawieniach.")).toBeInTheDocument();
    expect(screen.getByText("Do wysyłki brakuje: NIP sprzedawcy, rachunek PLN.")).toBeInTheDocument();
  });

  it("bez ustawień przy klientach mówi, że wszyscy mają domyślne", async () => {
    route(payload({ settings: settings({ clients: {} }), client_names: {} }));
    renderPanel();
    expect(await screen.findByText("Wszyscy klienci mają ustawienia domyślne.")).toBeInTheDocument();
  });
});

describe("IssueSettingsPanel — zapis", () => {
  it("zapisuje sprzedawcę, rachunek EUR, termin i stawkę domyślną", async () => {
    route(payload());
    mocks.put.mockResolvedValue({ data: { settings: settings() } });
    const user = userEvent.setup();
    renderPanel();
    await user.clear(await screen.findByLabelText("Miejsce wystawienia"));
    await user.type(screen.getByLabelText("Miejsce wystawienia"), "Kraków");
    await user.type(screen.getByLabelText("Rachunek EUR"), "PL22 2222");
    await user.type(screen.getByLabelText("SWIFT EUR"), "TESTPLPW");
    await user.clear(screen.getByLabelText("Termin płatności (dni)"));
    await user.type(screen.getByLabelText("Termin płatności (dni)"), "14");
    await user.selectOptions(screen.getByLabelText("Stawka VAT domyślna"), "8");
    await user.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));
    await waitFor(() => expect(savedBody()).toBeDefined());
    const body = savedBody();
    expect(body.seller.issue_place).toBe("Kraków");
    expect(body.accounts.EUR).toEqual({ number: "PL22 2222", bank: "", swift: "TESTPLPW" });
    expect(body.accounts.PLN.number).toBe("PL00 0000 0000 0000 0000 0000 0000");
    expect(body.payment_days).toBe(14);
    expect(typeof body.payment_days).toBe("number");
    expect(body.default_vat).toBe("8");
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Zapisano ustawienia wystawiania", "success"));
  });

  it("odmowa serwera zostaje na ekranie jako komunikat", async () => {
    route(payload());
    mocks.put.mockRejectedValue({ isAxiosError: true, response: { status: 422, data: { detail: "NIP sprzedawcy ma 10 cyfr." } } });
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Zapisz ustawienia" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("NIP sprzedawcy ma 10 cyfr.");
    expect(mocks.toast).not.toHaveBeenCalled();
  });

  it("dodany klient dostaje domyślną stawkę VAT i nazwę z wyboru", async () => {
    route(payload({ settings: settings({ clients: {} }), client_names: {} }));
    mocks.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderPanel();
    const add = await screen.findByRole("button", { name: "Dodaj klienta" });
    expect(add).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Wybierz klienta testowego" }));
    await user.click(add);
    expect(screen.getByText("Firma Testowa sp. z o.o.", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByLabelText("Stawka VAT — Firma Testowa sp. z o.o.")).toHaveValue("23");
    expect(screen.getByLabelText("Termin (dni) — Firma Testowa sp. z o.o.")).toHaveAttribute("placeholder", "30");
    expect(add).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));
    await waitFor(() => expect(savedBody()).toBeDefined());
    expect(savedBody().clients).toEqual({ "42": { vat_rate: "23" } });
  });

  it("klient: stawka, pusty termin = domyślny, rachunek w walucie, rabat i nabywcy", async () => {
    route(payload());
    mocks.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderPanel();
    const label = "Klient Testowy S.A.";
    await user.selectOptions(await screen.findByLabelText(`Stawka VAT — ${label}`), "zw");
    await user.clear(screen.getByLabelText(`Termin (dni) — ${label}`));
    // Rachunek w EUR jest wybrany, bo tylko on ma numer.
    expect(screen.getByLabelText(`Waluta rachunku — ${label}`)).toHaveValue("EUR");
    expect(screen.getByLabelText(`Rachunek klienta EUR — ${label}`)).toHaveValue("PL11 1111");
    await user.selectOptions(screen.getByLabelText(`Waluta rachunku — ${label}`), "USD");
    await user.type(screen.getByLabelText(`Rachunek klienta USD — ${label}`), "US33");
    await user.type(screen.getByLabelText(`Bank rachunku klienta — ${label}`), "Bank USD");
    expect(screen.getByRole("button", { name: `Wyczyść nabywców — ${label} (1/1)` })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: `Usuń rabat — ${label}` }));
    await user.click(screen.getByRole("button", { name: `Wyczyść nabywców — ${label} (1/1)` }));
    await user.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));
    await waitFor(() => expect(savedBody()).toBeDefined());
    const entry = savedBody().clients["7"];
    expect(entry.vat_rate).toBe("zw");
    expect(entry.payment_days).toBeUndefined();
    expect(entry.accounts).toEqual({
      EUR: { number: "PL11 1111", bank: "Bank EUR", swift: "" },
      USD: { number: "US33", bank: "Bank USD", swift: "" },
    });
    expect(entry).not.toHaveProperty("rebate");
    expect(entry).not.toHaveProperty("buyers");
    expect(entry).not.toHaveProperty("contract_buyers");
  });

  it("wyczyszczony numer rachunku klienta usuwa rachunek tej waluty", async () => {
    route(payload());
    mocks.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderPanel();
    const label = "Klient Testowy S.A.";
    await user.clear(await screen.findByLabelText(`Rachunek klienta EUR — ${label}`));
    await user.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));
    await waitFor(() => expect(savedBody()).toBeDefined());
    expect(savedBody().clients["7"].accounts).toEqual({});
  });

  it("usunięcie ustawień klienta zabiera go z zapisu", async () => {
    route(payload());
    mocks.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Usuń ustawienie klienta Klient Testowy S.A." }));
    expect(screen.getByText("Wszyscy klienci mają ustawienia domyślne.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));
    await waitFor(() => expect(savedBody()).toBeDefined());
    expect(savedBody().clients).toEqual({});
  });
});

describe("IssueSettingsPanel — serie numeracji", () => {
  it("pokazuje następny numer i ostatni wydany; wzór serii idzie w zapisie ustawień", async () => {
    route(payload());
    mocks.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderPanel();
    expect(await screen.findByText(/dotyczy styczeń 2027/)).toBeInTheDocument();
    const row = screen.getByText("Krajowa").closest("li")!;
    expect(row).toHaveTextContent("następna: 12/01/2027 · ostatni wydany 11");
    expect(screen.getByText("Unijna").closest("li")).not.toHaveTextContent("ostatni wydany");
    await user.clear(within(row).getByLabelText("Wzór serii Krajowa"));
    await user.type(within(row).getByLabelText("Wzór serii Krajowa"), "FV/{{n}");
    await user.click(screen.getByRole("button", { name: "Zapisz ustawienia" }));
    await waitFor(() => expect(savedBody()).toBeDefined());
    expect(savedBody().series.PL).toBe("FV/{n}");
  });

  it("„Ustaw” odmawia numeru poniżej 1 i ułamka, a poprawny wysyła z rokiem i miesiącem serii", async () => {
    route(payload());
    mocks.put.mockResolvedValue({ data: { series: [] } });
    const user = userEvent.setup();
    renderPanel();
    const row = (await screen.findByText("Krajowa")).closest("li")!;
    const input = within(row).getByLabelText("Następny numer — Krajowa");
    const apply = within(row).getByRole("button", { name: "Ustaw" });
    expect(apply).toBeDisabled();
    await user.type(input, "0");
    await user.click(apply);
    expect(mocks.toast).toHaveBeenCalledWith("Następny numer to liczba od 1.", "error");
    await user.clear(input);
    await user.type(input, "2.5");
    await user.click(apply);
    expect(mocks.toast).toHaveBeenCalledTimes(2);
    expect(mocks.put).not.toHaveBeenCalled();
    await user.clear(input);
    await user.type(input, "40");
    await user.click(apply);
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/finance/issued-invoices/series/PL", { year: 2027, month: 1, next_number: 40 }),
    );
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Seria „Krajowa”: następny numer 40", "success"));
  });

  it("odmowa ustawienia numeru idzie komunikatem z API", async () => {
    route(payload());
    mocks.put.mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: "Numer 5 jest już wydany." } } });
    const user = userEvent.setup();
    renderPanel();
    const row = (await screen.findByText("Krajowa")).closest("li")!;
    await user.type(within(row).getByLabelText("Następny numer — Krajowa"), "5");
    await user.click(within(row).getByRole("button", { name: "Ustaw" }));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Numer 5 jest już wydany.", "error"));
  });
});
