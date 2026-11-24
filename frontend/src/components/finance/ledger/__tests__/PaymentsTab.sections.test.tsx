import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  showToast: vi.fn(),
  askConfirm: vi.fn(),
  askReason: vi.fn(),
  fetchAuthenticatedDownload: vi.fn(),
  downloadBlob: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: (...a: unknown[]) => mocks.put(...a),
    patch: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({
    askConfirm: mocks.askConfirm,
    askReason: mocks.askReason,
    confirmDialog: null,
  }),
}));
vi.mock("@/lib/authenticated-files", () => ({
  fetchAuthenticatedDownload: (...a: unknown[]) => mocks.fetchAuthenticatedDownload(...a),
  downloadBlob: (...a: unknown[]) => mocks.downloadBlob(...a),
}));

import { PaymentsTab } from "@/components/finance/ledger/PaymentsTab";
import type {
  BatchDetail,
  BatchSummary,
  PaymentPlan,
  PlanItem,
  StatementOverview,
  UnmatchedDebit,
} from "@/lib/api/finance-payments";

const PAY = "/api/finance/payments";

function item(id: number, patch: Partial<PlanItem> = {}): PlanItem {
  return {
    entry_id: id,
    invoice_number: `FV/${id}/11/2026`,
    ksef_number: null,
    seller_name: `Dostawca ${id}`,
    seller_nip: "1234563218",
    category: "office",
    due_date: "2026-11-20",
    currency: "PLN",
    gross_amount: "100.00",
    vat_amount: "18.70",
    to_pay: "100.00",
    amount_note: null,
    account_note: null,
    mode: "standard",
    mode_label: "Zwykły",
    mode_suggested: false,
    account: "90109000000000000000004242",
    account_source: "manual",
    account_source_label: "wpisany na karcie",
    title: `FV/${id}/11/2026`,
    white_list: { state: "listed", label: "W wykazie VAT" },
    selectable: true,
    block: null,
    block_label: null,
    acks: [],
    hints: [],
    batch_id: null,
    preselect: true,
    contract_id: null,
    period_month: null,
    settlement_id: null,
    hold: null,
    contractor_amount: null,
    garnishments: [],
    ...patch,
  };
}

function plan(items: PlanItem[]): PaymentPlan {
  return {
    until: "2026-11-25",
    items,
    count: items.length,
    selectable: items.filter((i) => i.selectable).length,
    blocked: items.filter((i) => !i.selectable).length,
    totals: {},
  };
}

function batch(id: number, patch: Partial<BatchSummary> = {}): BatchSummary {
  return {
    id,
    currency: "PLN",
    format: "elixir",
    execution_date: "2026-11-25",
    created_at: null,
    created_by_name: "Anna Przykładowa",
    count: 2,
    total: "300.00",
    status: "active",
    status_label: "Czeka na bank",
    file_sha256: "abcdef1234567890",
    downloaded_at: null,
    changed_at: null,
    file_stale: false,
    ...patch,
  };
}

function debit(id: number, patch: Partial<UnmatchedDebit> = {}): UnmatchedDebit {
  return {
    id,
    booked_on: "2026-11-21",
    amount: "250.00",
    currency: "PLN",
    title: "Zapłata za FV/9/11/2026",
    counterparty_name: "Firma Testowa sp. z o.o.",
    counterparty_last4: "4242",
    reason: null,
    hints: [],
    ...patch,
  } as UnmatchedDebit;
}

interface Server {
  plan?: PaymentPlan | Error | "pending";
  settings?: { sender_name: string | null; sender_account: string | null };
  batches?: BatchSummary[] | Error | "pending";
  detail?: BatchDetail | Error | "pending";
  statements?: StatementOverview | Error;
}

function serve(server: Server = {}) {
  const never = new Promise(() => {});
  mocks.get.mockImplementation(async (url: string) => {
    if (url === `${PAY}/settings`) {
      return { data: server.settings ?? { sender_name: null, sender_account: null } };
    }
    if (url === `${PAY}/batches`) {
      const value = server.batches ?? [];
      if (value === "pending") return never;
      if (value instanceof Error) throw value;
      return { data: { items: value } };
    }
    if (url.startsWith(`${PAY}/batches/`)) {
      const value = server.detail;
      if (value === "pending") return never;
      if (!value || value instanceof Error) throw value ?? new Error("brak");
      return { data: value };
    }
    if (url === `${PAY}/statements`) {
      const value = server.statements ?? { unmatched: [], recent: [] };
      if (value instanceof Error) throw value;
      return { data: value };
    }
    if (url === `${PAY}/garnishments` || url === `${PAY}/holds`) return { data: { items: [] } };
    throw new Error(`nieoczekiwany GET ${url}`);
  });
  mocks.post.mockImplementation(async (url: string) => {
    if (url === `${PAY}/plan`) {
      const value = server.plan ?? plan([]);
      if (value === "pending") return never;
      if (value instanceof Error) throw value;
      return { data: value };
    }
    throw new Error(`nieoczekiwany POST ${url}`);
  });
}

function renderTab(canWrite = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PaymentsTab canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

const apiError = (detail: string) => ({ response: { status: 400, data: { detail } } });

/** Zachowuje domyślne odpowiedzi i dokłada jedną ścieżkę POST. */
function onPost(path: string, handler: (body: unknown) => unknown) {
  const base = mocks.post.getMockImplementation()!;
  mocks.post.mockImplementation(async (url: string, body?: unknown) =>
    url === path ? handler(body) : base(url, body),
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-25T09:00:00Z"));
  for (const fn of Object.values(mocks)) fn.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("PaymentsTab — rachunek nadawcy", () => {
  it("bez rachunku: ostrzeżenie o samym CSV i zapis nazwy z rachunkiem", async () => {
    const user = userEvent.setup();
    serve();
    mocks.put.mockResolvedValue({
      data: { sender_name: "Spółka Przykładowa", sender_account: "11111111111111111111111111" },
    });
    renderTab();
    expect(await screen.findByText("nie ustawiony — paczka tylko jako CSV")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ustaw" }));
    await user.type(screen.getByLabelText("Nazwa nadawcy"), "Spółka Przykładowa");
    await user.type(screen.getByLabelText("Rachunek nadawcy"), "11111111111111111111111111");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(`${PAY}/settings`, {
        sender_name: "Spółka Przykładowa",
        sender_account: "11111111111111111111111111",
      }),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith("Rachunek nadawcy zapisany.", "success"),
    );
    await waitFor(() => expect(screen.queryByLabelText("Nazwa nadawcy")).not.toBeInTheDocument());
  });

  it("ustawiony rachunek: nazwa i rachunek w grupach, formularz wypełniony; błąd zapisu idzie toastem", async () => {
    const user = userEvent.setup();
    serve({
      settings: { sender_name: "Spółka Przykładowa", sender_account: "90109000000000000000004242" },
    });
    mocks.put.mockRejectedValue(apiError("Rachunek nadawcy ma złą sumę kontrolną."));
    renderTab();
    expect(
      await screen.findByText("Spółka Przykładowa · PL90 1090 0000 0000 0000 0000 4242"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zmień" }));
    expect(screen.getByLabelText("Rachunek nadawcy")).toHaveValue("90109000000000000000004242");
    expect(screen.getByRole("button", { name: "Zamknij" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Rachunek nadawcy ma złą sumę kontrolną."),
        "error",
      ),
    );
    // Formularz zostaje otwarty, żeby poprawić rachunek.
    expect(screen.getByLabelText("Rachunek nadawcy")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(screen.queryByLabelText("Rachunek nadawcy")).not.toBeInTheDocument();
  });

  it("podgląd jako inna osoba: bez przycisku ustawienia rachunku", async () => {
    serve();
    renderTab(false);
    expect(await screen.findByText("nie ustawiony — paczka tylko jako CSV")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ustaw" })).not.toBeInTheDocument();
  });
});

describe("PaymentsTab — lista do zapłaty", () => {
  it("w trakcie sprawdzania planu widać komunikat, nie pustą listę", async () => {
    serve({ plan: "pending" });
    renderTab();
    expect(await screen.findByText("Sprawdzanie faktur i rachunków…")).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma faktur z terminem/)).not.toBeInTheDocument();
  });

  it("pusty plan: komunikat z dzisiejszą datą; wyczyszczony termin wraca na dziś", async () => {
    serve();
    renderTab();
    expect(await screen.findByText("Nie ma faktur z terminem do 25.11.2026.")).toBeInTheDocument();
    expect(mocks.post).toHaveBeenCalledWith(`${PAY}/plan`, { until: "2026-11-25" });
    const until = screen.getByLabelText("Termin płatności do");
    fireEvent.change(until, { target: { value: "2026-12-31" } });
    expect(await screen.findByText("Nie ma faktur z terminem do 31.12.2026.")).toBeInTheDocument();
    expect(mocks.post).toHaveBeenCalledWith(`${PAY}/plan`, { until: "2026-12-31" });
    fireEvent.change(until, { target: { value: "" } });
    expect(until).toHaveValue("2026-11-25");
    // Pusty plan nie pokazuje paska paczki.
    expect(screen.queryByRole("button", { name: "Utwórz paczkę" })).not.toBeInTheDocument();
  });

  it("wiersz bez danych: „—” zamiast terminu, sprzedawcy, tytułu i trybu; numer zastępczy; kwota brutto, gdy brak „do zapłaty”", async () => {
    serve({
      plan: plan([
        item(4, {
          due_date: null,
          seller_name: null,
          seller_nip: null,
          invoice_number: null,
          title: "",
          mode: null,
          mode_label: null,
          account: null,
          account_source_label: null,
          to_pay: null,
          gross_amount: "321.00",
          selectable: false,
          block: "no_due_date",
          block_label: "Brak terminu płatności — wpisz go na karcie faktury.",
          preselect: false,
        }),
      ]),
    });
    renderTab();
    expect(await screen.findByText("Faktura #4")).toHaveAttribute("href", "/finance/costs/4");
    expect(screen.getByText("bez NIP-u")).toBeInTheDocument();
    expect(screen.getByText("321,00 zł")).toBeInTheDocument();
    expect(screen.getByText(/Brak terminu płatności/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Zaznacz fakturę" })).toBeDisabled();
    // termin, sprzedawca, tytuł, tryb, rachunek i biała lista
    expect(screen.getAllByText("—")).toHaveLength(6);
  });

  it("uwagi pod wierszem: korekta kwoty, zmiana rachunku, podpowiedzi i biała lista faktora", async () => {
    serve({
      plan: plan([
        item(5, {
          amount_note: "Pomniejszona o korektę KOR/1/11/2026",
          account_note: "Rachunek zmieniony ręcznie przez Annę Przykładową dnia 20.11.2026.",
          hints: [{ code: "split", label: "Faktura w dwóch ratach" }],
          mode: "mpp",
          mode_label: "MPP",
          white_list: {
            state: "not_listed",
            label: "Poza wykazem VAT",
            request_id: "req-123",
            informational: true,
          },
        }),
      ]),
    });
    renderTab();
    expect(await screen.findByText("Pomniejszona o korektę KOR/1/11/2026")).toBeInTheDocument();
    expect(screen.getByText(/Rachunek zmieniony ręcznie/)).toBeInTheDocument();
    expect(screen.getByText("Faktura w dwóch ratach")).toBeInTheDocument();
    expect(screen.getByText("MPP")).toBeInTheDocument();
    expect(screen.getByText(/Poza wykazem VAT/)).toHaveTextContent(
      "Poza wykazem VAT (informacyjnie — faktor)",
    );
    expect(screen.getByText("req-123")).toBeInTheDocument();
  });

  it("suma zaznaczonych liczy się w groszach po kliknięciach", async () => {
    const user = userEvent.setup();
    serve({
      plan: plan([
        item(1, { to_pay: "0.10" }),
        item(2, { to_pay: "0.20" }),
        item(3, { to_pay: "1000.00", preselect: false }),
      ]),
    });
    renderTab();
    await screen.findByRole("checkbox", { name: "Zaznacz FV/1/11/2026" });
    expect(screen.getByText("0,30 zł")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz FV/3/11/2026" }));
    expect(screen.getByText("1000,30 zł")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz FV/1/11/2026" }));
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz FV/2/11/2026" }));
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz FV/3/11/2026" }));
    const create = screen.getByRole("button", { name: "Utwórz paczkę" });
    expect(create).toBeDisabled();
    expect(create).toHaveAttribute("title", "Zaznacz faktury do paczki.");
    // Przy zerze zaznaczonych podpowiedź nie wisi pod paskiem.
    expect(screen.queryByText("Zaznacz faktury do paczki.")).not.toBeInTheDocument();
  });

  it("dwie waluty w zaznaczeniu blokują paczkę z powodem", async () => {
    serve({ plan: plan([item(1), item(2, { currency: "EUR", to_pay: "50.00" })]) });
    renderTab();
    expect(
      await screen.findByText("Jedna paczka to jedna waluta — zaznacz faktury w jednej walucie."),
    ).toBeInTheDocument();
    // Pasek pokazuje sumę osobno dla każdej waluty (wiersz + suma).
    expect(screen.getAllByText("100,00 zł")).toHaveLength(2);
    expect(screen.getAllByText("50,00 EUR")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Utwórz paczkę" })).toBeDisabled();
  });

  it("paczka w euro idzie zawsze jako CSV, z datą wykonania i nazwą od serwera w toaście", async () => {
    const user = userEvent.setup();
    serve({ plan: plan([item(8, { currency: "EUR", to_pay: "1250.50" })]) });
    onPost(`${PAY}/batches`, () => ({
      data: { id: 12, count: 1, total: "1250.50", currency: "EUR", items: [] },
    }));
    renderTab();
    const formatSelect = await screen.findByLabelText("Format pliku");
    expect(formatSelect).toHaveValue("csv");
    expect(formatSelect).toBeDisabled();
    const execution = screen.getByLabelText("Data wykonania");
    expect(execution).toHaveAttribute("min", "2026-11-25");
    fireEvent.change(execution, { target: { value: "2026-11-27" } });
    await user.click(screen.getByRole("button", { name: "Utwórz paczkę" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(`${PAY}/batches`, {
        entry_ids: [8],
        acknowledged: [],
        execution_date: "2026-11-27",
        format: "csv",
      }),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringMatching(/^Paczka #12 utworzona: 1 · 1250,50\sEUR\.$/),
        "success",
      ),
    );
  });

  it("paczka w złotych: wybrany CSV, pusta data wykonania wraca na dziś; błąd utworzenia toastem", async () => {
    const user = userEvent.setup();
    serve({ plan: plan([item(1)]) });
    onPost(`${PAY}/batches`, () => {
      throw apiError("Faktura jest już w paczce #3.");
    });
    renderTab();
    const formatSelect = await screen.findByLabelText("Format pliku");
    expect(formatSelect).toHaveValue("elixir");
    await user.selectOptions(formatSelect, "csv");
    fireEvent.change(screen.getByLabelText("Data wykonania"), { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: "Utwórz paczkę" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        `${PAY}/batches`,
        expect.objectContaining({ format: "csv", execution_date: "2026-11-25" }),
      ),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Faktura jest już w paczce #3."),
        "error",
      ),
    );
  });

  it("faktura kontraktora bez rozliczenia: tylko „Zajęcie”, okno z nazwą kontraktu i Anuluj je zamyka", async () => {
    const user = userEvent.setup();
    serve({ plan: plan([item(6, { contract_id: 42, seller_name: null, settlement_id: null })]) });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Zajęcie" }));
    expect(screen.queryByRole("button", { name: "Spór / wstrzymaj" })).not.toBeInTheDocument();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Zajęcie wierzytelności —/)).toHaveTextContent("Kontrakt #42");
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("okno sporu z wiersza zamyka się przez Anuluj", async () => {
    const user = userEvent.setup();
    serve({ plan: plan([item(6, { contract_id: 42, settlement_id: 9 })]) });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Spór / wstrzymaj" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("PaymentsTab — paczki", () => {
  it("w trakcie wczytywania paczek widać komunikat", async () => {
    serve({ batches: "pending" });
    renderTab();
    expect(await screen.findByText("Wczytywanie paczek…")).toBeInTheDocument();
  });

  it("awaria paczek pokazuje błąd, nie „Nie ma jeszcze paczek”", async () => {
    serve({ batches: new Error("500") });
    renderTab();
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Spróbuj ponownie/ }).length).toBeGreaterThan(0));
    expect(screen.queryByText("Nie ma jeszcze paczek przelewów.")).not.toBeInTheDocument();
  });

  it("pusty stan paczek po udanym zapytaniu", async () => {
    serve();
    renderTab();
    expect(await screen.findByText("Nie ma jeszcze paczek przelewów.")).toBeInTheDocument();
  });

  it("paczka: data, liczba, kwota, format i skrót pliku; zamknięta bez pobrania i anulowania", async () => {
    serve({
      batches: [
        batch(5),
        batch(6, {
          status: "done",
          status_label: "Zapłacona",
          format: "csv",
          total: "1234.56",
          currency: "EUR",
          created_by_name: null,
          file_sha256: null,
        }),
      ],
    });
    renderTab();
    expect(await screen.findByText("#5")).toBeInTheDocument();
    expect(screen.getByText("2 · 300,00 zł · Elixir-O")).toBeInTheDocument();
    expect(screen.getByText("plik abcdef12")).toBeInTheDocument();
    expect(screen.getByText("2 · 1234,56 EUR · CSV")).toBeInTheDocument();
    expect(screen.getByText("Zapłacona")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Pobierz plik" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Anuluj" })).toHaveLength(1);
  });

  it("pobranie pliku: nazwa od serwera albo zapasowa; nieaktualny plik ostrzega o wymianie w banku", async () => {
    const user = userEvent.setup();
    serve({ batches: [batch(5, { file_stale: true })] });
    const blob = new Blob(["x"]);
    mocks.fetchAuthenticatedDownload.mockResolvedValueOnce({ blob, filename: null });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Pobierz plik" }));
    await waitFor(() =>
      expect(mocks.downloadBlob).toHaveBeenCalledWith(blob, "przelewy-kosztow-5"),
    );
    expect(mocks.fetchAuthenticatedDownload).toHaveBeenCalledWith(`${PAY}/batches/5/file`);
    expect(mocks.showToast).toHaveBeenCalledWith(
      expect.stringContaining("Pobrano NOWY plik paczki"),
      "info",
    );
  });

  it("pobranie aktualnego pliku bez ostrzeżenia; błąd pobrania toastem", async () => {
    const user = userEvent.setup();
    serve({ batches: [batch(5)] });
    const blob = new Blob(["x"]);
    mocks.fetchAuthenticatedDownload
      .mockResolvedValueOnce({ blob, filename: "elixir_5.txt" })
      .mockRejectedValueOnce(apiError("Paczka anulowana."));
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Pobierz plik" }));
    await waitFor(() => expect(mocks.downloadBlob).toHaveBeenCalledWith(blob, "elixir_5.txt"));
    expect(mocks.showToast).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Pobierz plik" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Paczka anulowana."),
        "error",
      ),
    );
  });

  it("anulowanie paczki wymaga potwierdzenia", async () => {
    const user = userEvent.setup();
    serve({ batches: [batch(5)] });
    mocks.askConfirm.mockResolvedValue(false);
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Anuluj" }));
    expect(mocks.askConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Anulować paczkę #5?", variant: "destructive" }),
    );
    expect(mocks.post).not.toHaveBeenCalledWith(`${PAY}/batches/5/cancel`);
  });

  it("potwierdzone anulowanie mówi, ile faktur wróciło; błąd toastem", async () => {
    const user = userEvent.setup();
    serve({ batches: [batch(5)] });
    mocks.askConfirm.mockResolvedValue(true);
    let calls = 0;
    onPost(`${PAY}/batches/5/cancel`, () => {
      calls += 1;
      if (calls === 1) return { data: { id: 5, released: 2 } };
      throw apiError("Bank wykonał już paczkę.");
    });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Anuluj" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith("Paczka anulowana, zwolnione: 2.", "success"),
    );
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Bank wykonał już paczkę."),
        "error",
      ),
    );
  });

  it("podgląd jako inna osoba: pobranie zostaje, anulowania nie ma", async () => {
    serve({ batches: [batch(5)] });
    renderTab(false);
    expect(await screen.findByRole("button", { name: "Pobierz plik" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anuluj" })).not.toBeInTheDocument();
  });
});

describe("PaymentsTab — pozycje paczki", () => {
  const detail = (items: Partial<BatchDetail["items"][number]>[]): BatchDetail =>
    ({
      ...batch(5),
      items: items.map((patch, i) => ({
        entry_id: i + 1,
        invoice_number: `FV/${i + 1}/11/2026`,
        recipient_name: `Dostawca ${i + 1}`,
        account: "90109000000000000000004242",
        account_source: "manual",
        account_source_label: "wpisany na karcie",
        amount: "100.00",
        currency: "PLN",
        mode: "standard",
        mode_label: "Zwykły",
        title: "FV",
        white_list: { state: "listed", label: "W wykazie VAT" },
        acknowledged: false,
        status: "active",
        contractor_amount: null,
        garnishments: [],
        ...patch,
      })),
    }) as BatchDetail;

  it("wczytywanie i awaria pozycji", async () => {
    const user = userEvent.setup();
    serve({ batches: [batch(5)], detail: "pending" });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Pozycje" }));
    expect(screen.getByRole("button", { name: "Pozycje" })).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("Wczytywanie…")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pozycje" }));
    expect(screen.queryByText("Wczytywanie…")).not.toBeInTheDocument();
  });

  it("awaria pozycji pokazuje błąd", async () => {
    const user = userEvent.setup();
    serve({ batches: [batch(5)], detail: new Error("500") });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Pozycje" }));
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
  });

  it("pozycje: podział na organ i kontraktora, statusy zapłacona/zdjęta, zdejmowanie tylko aktywnych", async () => {
    const user = userEvent.setup();
    serve({
      batches: [batch(5)],
      detail: detail([
        {
          amount: "1230.00",
          contractor_amount: "180.00",
          garnishments: [
            {
              garnishment_id: 1,
              case_number: "KM 1/26",
              authority_name: "Komornik Przykładowy",
              authority_kind: "bailiff",
              authority_label: "Komornik",
              account: "11111111111111111111111111",
              amount: "1050.00",
              due_before: "1050.00",
              title: "Sygn. KM 1/26",
            },
          ],
        },
        { status: "done", invoice_number: null },
        { status: "released" },
      ]),
    });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Pozycje" }));
    expect(
      await screen.findByText("→ Komornik Przykładowy (sygn. KM 1/26): 1050,00 zł"),
    ).toBeInTheDocument();
    expect(screen.getByText("→ kontraktor: 180,00 zł")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(screen.getByText("zapłacona")).toBeInTheDocument();
    expect(screen.getByText("zdjęta")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Zdejmij z paczki" })).toHaveLength(1);
  });

  it("zdjęcie z paczki: bez potwierdzenia nic, po potwierdzeniu toast, błąd toastem", async () => {
    const user = userEvent.setup();
    serve({ batches: [batch(5)], detail: detail([{}]) });
    mocks.askConfirm.mockResolvedValueOnce(false).mockResolvedValue(true);
    let calls = 0;
    onPost(`${PAY}/batches/5/items/1/release`, () => {
      calls += 1;
      if (calls === 1) return { data: { released: 1, batch_cancelled: false, file_stale: true } };
      throw apiError("Faktura już zapłacona.");
    });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Pozycje" }));
    const release = await screen.findByRole("button", { name: "Zdejmij z paczki" });
    await user.click(release);
    expect(calls).toBe(0);
    await user.click(release);
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        "Faktura zdjęta z paczki — pobierz plik ponownie.",
        "success",
      ),
    );
    await user.click(await screen.findByRole("button", { name: "Zdejmij z paczki" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Faktura już zapłacona."),
        "error",
      ),
    );
  });
});

describe("PaymentsTab — zapłaty z wyciągu", () => {
  it("awaria przeglądu wyciągów pokazuje błąd, nie „Nic nie czeka”", async () => {
    serve({ statements: new Error("500") });
    renderTab();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /Spróbuj ponownie/ }).length).toBeGreaterThan(0),
    );
    expect(screen.queryByText("Nic nie czeka na sprawdzenie.")).not.toBeInTheDocument();
  });

  it("pusty stan wyciągu po udanym zapytaniu", async () => {
    serve();
    renderTab();
    expect(await screen.findByText("Nic nie czeka na sprawdzenie.")).toBeInTheDocument();
  });

  it("wgranie wyciągu wysyła plik i pokazuje podsumowanie; błąd toastem", async () => {
    const user = userEvent.setup();
    serve();
    let calls = 0;
    onPost(`${PAY}/statements`, () => {
      calls += 1;
      if (calls === 1) {
        return {
          data: {
            format: "mt940",
            statement: "11/2026",
            operations: 5,
            debits: 4,
            matched: 2,
            partial: 1,
            unmatched: 1,
            duplicates: 0,
            known: 0,
            team: 0,
            skipped: 0,
          },
        };
      }
      throw apiError("Nieznany format pliku.");
    });
    renderTab();
    const input = await screen.findByLabelText("Wyciąg MT940 albo CAMT.053");
    const file = new File([":20:TEST"], "wyciag.sta", { type: "text/plain" });
    await user.upload(input, file);
    expect(
      await screen.findByText("Zapłacone: 2, częściowo: 1, do sprawdzenia: 1. Obciążeń w pliku: 4."),
    ).toBeInTheDocument();
    const sent = mocks.post.mock.calls.find(([url]) => url === `${PAY}/statements`);
    expect((sent?.[1] as FormData).get("file")).toBe(file);
    await user.upload(input, file);
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Nieznany format pliku."),
        "error",
      ),
    );
  });

  it("wybór pliku anulowany w oknie systemowym nic nie wysyła", async () => {
    serve();
    renderTab();
    const input = await screen.findByLabelText("Wyciąg MT940 albo CAMT.053");
    fireEvent.change(input, { target: { files: [] } });
    expect(mocks.post).not.toHaveBeenCalledWith(
      `${PAY}/statements`,
      expect.anything(),
      expect.anything(),
    );
  });

  it("operacja z wyciągu: data, kwota, kontrahent, powód i przypisanie podpowiedzi", async () => {
    const user = userEvent.setup();
    serve({
      statements: {
        unmatched: [
          debit(1, {
            reason: "Kwota nie zgadza się z żadną fakturą.",
            hints: [
              {
                entry_id: 9,
                invoice_number: "FV/9/11/2026",
                seller_name: "Firma Testowa sp. z o.o.",
                gross_amount: "250.00",
                currency: "PLN",
              },
              { entry_id: 10, invoice_number: null, seller_name: null, gross_amount: null, currency: "PLN" },
            ],
          }),
          debit(2, { counterparty_name: null, title: "" }),
        ],
        recent: [],
      },
    });
    let calls = 0;
    onPost(`${PAY}/records/1/assign`, () => {
      calls += 1;
      if (calls === 1) return { data: {} };
      throw apiError("Faktura już zapłacona.");
    });
    renderTab();
    expect(
      await screen.findByText("Firma Testowa sp. z o.o. · Zapłata za FV/9/11/2026"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("21.11.2026").length).toBeGreaterThan(0);
    expect(screen.getAllByText("250,00 zł").length).toBeGreaterThan(0);
    expect(screen.getByText("Kwota nie zgadza się z żadną fakturą.")).toBeInTheDocument();
    const fallback = screen.getByRole("button", { name: /Przypisz: #10/ });
    expect(fallback).toHaveTextContent("Przypisz: #10 · · —");
    await user.click(
      screen.getByRole("button", {
        name: /^Przypisz: FV\/9\/11\/2026 · Firma Testowa sp\. z o\.o\. · 250,00\szł$/,
      }),
    );
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(`${PAY}/records/1/assign`, { entry_id: 9 }),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith("Zapłata przypisana.", "success"),
    );
    await user.click(fallback);
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Faktura już zapłacona."),
        "error",
      ),
    );
  });

  it("pominięcie operacji wymaga powodu; anulowane okno nic nie wysyła; błąd toastem", async () => {
    const user = userEvent.setup();
    serve({ statements: { unmatched: [debit(1)], recent: [] } });
    mocks.askReason
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce("przelew spoza faktur")
      .mockResolvedValueOnce("przelew spoza faktur");
    let calls = 0;
    onPost(`${PAY}/records/1/ignore`, () => {
      calls += 1;
      if (calls === 1) return { data: {} };
      throw apiError("Operacja już pominięta.");
    });
    renderTab();
    const skip = await screen.findByRole("button", { name: "Pomiń" });
    await user.click(skip);
    expect(mocks.askReason).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Pominąć operację z wyciągu?",
        field: expect.objectContaining({ minLength: 3, maxLength: 500 }),
      }),
    );
    expect(calls).toBe(0);
    await user.click(skip);
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(`${PAY}/records/1/ignore`, {
        reason: "przelew spoza faktur",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Pomiń" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Operacja już pominięta."),
        "error",
      ),
    );
  });

  it("podgląd jako inna osoba: bez wgrywania i pomijania, podpowiedzi wyłączone", async () => {
    serve({
      statements: {
        unmatched: [
          debit(1, {
            hints: [
              {
                entry_id: 9,
                invoice_number: "FV/9/11/2026",
                seller_name: "Firma Testowa sp. z o.o.",
                gross_amount: "250.00",
                currency: "PLN",
              },
            ],
          }),
        ],
        recent: [],
      },
    });
    renderTab(false);
    expect(await screen.findByRole("button", { name: /Przypisz: FV\/9/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Pomiń" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Wyciąg MT940 albo CAMT.053")).not.toBeInTheDocument();
  });
});
