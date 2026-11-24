import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  showToast: vi.fn(),
  askConfirm: vi.fn(),
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
  useConfirmV2: () => ({ askConfirm: mocks.askConfirm, askReason: vi.fn(), confirmDialog: null }),
}));

import {
  ContractorBlocks,
  GarnishmentDialog,
  HoldDialog,
} from "@/components/finance/ledger/ContractorBlocks";
import type { Garnishment, PaymentHold, PlanItem } from "@/lib/api/finance-payments";

const PAY = "/api/finance/payments";

function garnishment(patch: Partial<Garnishment> = {}): Garnishment {
  return {
    id: 5,
    contract_id: 42,
    contractor_name: "Jan Testowy",
    client_name: "Firma Testowa sp. z o.o.",
    authority_kind: "bailiff",
    authority_label: "Komornik",
    authority_name: "Komornik Przykładowy",
    case_number: "KM 12/26",
    served_on: "2026-10-05",
    principal_amount: "1500.00",
    costs_amount: "120.00",
    interest_mode: "none",
    interest_label: "Bez odsetek",
    interest_amount: null,
    interest_rate: null,
    interest_from: null,
    authority_account: "11111111111111111111111111",
    note: null,
    lifted_on: null,
    lifted_note: null,
    lifted_by_name: null,
    active: true,
    transferred: "300.00",
    due_today: "1320.00",
    problem: null,
    created_by_name: null,
    created_at: null,
    updated_by_name: null,
    updated_at: null,
    ...patch,
  };
}

function hold(patch: Partial<PaymentHold> = {}): PaymentHold {
  return {
    id: 3,
    settlement_id: 9,
    reason: "Praca bez zamówienia klienta",
    created_by_name: "Anna Przykładowa",
    created_at: "2026-11-10T08:15:00+00:00",
    released_by_name: null,
    released_at: null,
    release_note: null,
    contract_id: 42,
    contractor_name: "Jan Testowy",
    client_name: null,
    period_month: "2026-10",
    ...patch,
  };
}

function planItem(patch: Partial<PlanItem> = {}): PlanItem {
  return {
    entry_id: 77,
    invoice_number: "FV/77/10/2026",
    ksef_number: null,
    seller_name: "Jan Testowy",
    seller_nip: null,
    category: "contractor",
    due_date: "2026-11-12",
    currency: "PLN",
    gross_amount: "1230.00",
    vat_amount: "230.00",
    to_pay: "1230.00",
    amount_note: null,
    account_note: null,
    mode: "standard",
    mode_label: "Zwykły",
    mode_suggested: false,
    account: null,
    account_source: null,
    account_source_label: null,
    title: "FV/77/10/2026",
    white_list: { state: "off", label: "Nie sprawdzono" },
    selectable: true,
    block: null,
    block_label: null,
    acks: [],
    hints: [],
    batch_id: null,
    preselect: false,
    contract_id: 42,
    period_month: "2026-10",
    settlement_id: 9,
    hold: null,
    contractor_amount: null,
    garnishments: [],
    ...patch,
  } as PlanItem;
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function serveLists(garnishments: Garnishment[] | Error, holds: PaymentHold[] | Error) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url === `${PAY}/garnishments`) {
      if (garnishments instanceof Error) throw garnishments;
      return { data: { items: garnishments } };
    }
    if (url === `${PAY}/holds`) {
      if (holds instanceof Error) throw holds;
      return { data: { items: holds } };
    }
    // Odświeżenia po mutacji (plan, paczki) nie są przedmiotem tych testów.
    return { data: { items: [] } };
  });
}

const apiError = (detail: string) => ({ response: { status: 400, data: { detail } } });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  // 23:30 UTC 24.11 to już 25.11 w Warszawie — „dziś” liczy kalendarz firmy.
  vi.setSystemTime(new Date("2026-11-24T23:30:00Z"));
  for (const fn of Object.values(mocks)) fn.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ContractorBlocks — lista zajęć i sporów", () => {
  it("awaria zapytania o zajęcia pokazuje błąd, nie pusty stan", async () => {
    serveLists(new Error("500"), []);
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByText("Brak aktywnych zajęć wierzytelności.")).not.toBeInTheDocument();
  });

  it("pusty stan tylko po udanym zapytaniu", async () => {
    serveLists([], []);
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    expect(await screen.findByText("Brak aktywnych zajęć wierzytelności.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pokaż uchylone/ })).not.toBeInTheDocument();
  });

  it("wiersz zajęcia: kontraktor z klientem, rachunek organu, należność na dziś i przekazane", async () => {
    serveLists([garnishment()], []);
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    expect(
      await screen.findByText("Jan Testowy · Firma Testowa sp. z o.o."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Komornik · Komornik Przykładowy/)).toHaveTextContent(
      "doręczone 05.10.2026",
    );
    expect(screen.getByText("PL11 1111 1111 1111 1111 1111 1111")).toBeInTheDocument();
    expect(screen.getByText("1320,00 zł")).toBeInTheDocument();
    expect(screen.getByText(/przekazano 300,00 zł/)).toBeInTheDocument();
  });

  it("kwoty nie da się policzyć: „—” zamiast 0 zł, powód i brak rachunku organu", async () => {
    serveLists(
      [
        garnishment({
          contractor_name: null,
          client_name: null,
          due_today: null,
          transferred: "0",
          problem: "brak stopy odsetek",
          authority_account: null,
        }),
      ],
      [],
    );
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    expect(await screen.findByText("Kontrakt #42")).toBeInTheDocument();
    // Dwa „—”: należność na dziś i brak rachunku organu.
    expect(screen.getAllByText("—")).toHaveLength(2);
    // Zero przekazane to „0,00 zł” — kwota znana, nie brak danych.
    expect(screen.getByText(/przekazano\s+0,00 zł/)).toBeInTheDocument();
    expect(screen.getByText("Kwoty nie da się policzyć: brak stopy odsetek")).toBeInTheDocument();
    // `formatAccount(null)` daje „—”, więc zapas „bez rachunku organu” się nie pokazuje.
    expect(screen.queryByText("bez rachunku organu")).not.toBeInTheDocument();
  });

  it("uchylone zajęcia są schowane i pokazują się przełącznikiem z licznikiem", async () => {
    const user = userEvent.setup();
    serveLists(
      [
        garnishment(),
        garnishment({
          id: 6,
          case_number: "KM 99/25",
          active: false,
          lifted_on: "2026-11-02",
          lifted_by_name: "Anna Przykładowa",
          lifted_note: "postanowienie 7/26",
        }),
      ],
      [],
    );
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    const toggle = await screen.findByRole("button", { name: "Pokaż uchylone (1)" });
    expect(screen.queryByText("KM 99/25")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByText("KM 99/25")).toBeInTheDocument();
    expect(
      screen.getByText("Uchylone 02.11.2026 · Anna Przykładowa · postanowienie 7/26"),
    ).toBeInTheDocument();
    // Uchylonego zajęcia nie da się już zmienić ani uchylić drugi raz.
    expect(screen.getAllByRole("button", { name: "Zmień" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Ukryj uchylone" }));
    expect(screen.queryByText("KM 99/25")).not.toBeInTheDocument();
  });

  it("uchylone bez daty i autora: sam napis „Uchylone”", async () => {
    const user = userEvent.setup();
    serveLists([garnishment({ active: false, lifted_on: null })], []);
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Pokaż uchylone (1)" }));
    expect(screen.getByText(/^Uchylone\s*$/)).toBeInTheDocument();
  });

  it("bez prawa zapisu nie ma przycisków Zmień, Uchyl ani Zwolnij", async () => {
    serveLists([garnishment()], [hold()]);
    wrap(<ContractorBlocks canWrite={false} onEdit={vi.fn()} />);
    expect(await screen.findByText("Praca bez zamówienia klienta")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Uchyl" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zwolnij" })).not.toBeInTheDocument();
  });

  it("„Zmień” oddaje zajęcie z etykietą kontraktu do okna edycji", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    const row = garnishment();
    serveLists([row], []);
    wrap(<ContractorBlocks canWrite onEdit={onEdit} />);
    await user.click(await screen.findByRole("button", { name: "Zmień" }));
    expect(onEdit).toHaveBeenCalledWith({
      kind: "garnishment",
      contractId: 42,
      label: "Jan Testowy · Firma Testowa sp. z o.o.",
      garnishment: row,
    });
  });
});

describe("ContractorBlocks — uchylenie zajęcia", () => {
  it("uchyla z dzisiejszą datą Warszawy, bez uwagi wysyła null", async () => {
    const user = userEvent.setup();
    serveLists([garnishment()], []);
    mocks.post.mockResolvedValue({ data: { ...garnishment(), released_from_batches: [] } });
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Uchyl" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Uchylenie zajęcia KM 12/26")).toBeInTheDocument();
    const day = within(dialog).getByLabelText("Data uchylenia");
    expect(day).toHaveValue("2026-11-25");
    expect(day).toHaveAttribute("min", "2026-10-05");
    expect(day).toHaveAttribute("max", "2026-11-25");
    await user.type(within(dialog).getByLabelText("Uwaga do uchylenia"), "   ");
    await user.click(within(dialog).getByRole("button", { name: "Uchyl zajęcie" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(`${PAY}/garnishments/5/lift`, {
        lifted_on: "2026-11-25",
        note: null,
      }),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        "Zajęcie uchylone — od tego dnia płacimy kontraktorowi.",
        "success",
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("uchylenie zdejmujące fakturę z paczki mówi, z której paczki", async () => {
    const user = userEvent.setup();
    serveLists([garnishment()], []);
    mocks.post.mockResolvedValue({
      data: {
        ...garnishment(),
        released_from_batches: [
          { batch_id: 8, entry_id: 77, file_stale: true, released: true, reason: null },
        ],
      },
    });
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Uchyl" }));
    await user.type(screen.getByLabelText("Uwaga do uchylenia"), " postanowienie 7/26 ");
    await user.click(screen.getByRole("button", { name: "Uchyl zajęcie" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(`${PAY}/garnishments/5/lift`, {
        lifted_on: "2026-11-25",
        note: "postanowienie 7/26",
      }),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Zdjęto z paczki #8 (1)"),
        "success",
      ),
    );
  });

  it("błąd uchylenia zostaje w oknie jako komunikat", async () => {
    const user = userEvent.setup();
    serveLists([garnishment()], []);
    mocks.post.mockRejectedValue(apiError("Data uchylenia przed doręczeniem."));
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Uchyl" }));
    await user.click(screen.getByRole("button", { name: "Uchyl zajęcie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Data uchylenia przed doręczeniem.",
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(mocks.showToast).not.toHaveBeenCalled();
  });

  it("„Anuluj” zamyka okno bez zapytania", async () => {
    const user = userEvent.setup();
    serveLists([garnishment()], []);
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Uchyl" }));
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocks.post).not.toHaveBeenCalled();
  });
});

describe("ContractorBlocks — spory (wstrzymane płatności)", () => {
  it("awaria zapytania o spory pokazuje błąd", async () => {
    serveLists([], new Error("500"));
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    expect(await screen.findByText("Brak aktywnych zajęć wierzytelności.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
  });

  it("wiersz sporu: miesiąc, powód, autor i dzień; bez autora „Finanse”", async () => {
    serveLists(
      [],
      [hold(), hold({ id: 4, created_by_name: null, created_at: null, period_month: undefined, contractor_name: null, contract_id: 50 })],
    );
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    expect(await screen.findByText("Jan Testowy · 2026-10")).toBeInTheDocument();
    expect(screen.getByText("Anna Przykładowa · 10.11.2026")).toBeInTheDocument();
    expect(screen.getByText("Kontrakt #50")).toBeInTheDocument();
    expect(screen.getByText("Finanse")).toBeInTheDocument();
    expect(screen.getAllByText("Spór / wstrzymane")).toHaveLength(2);
  });

  it("„Zwolnij” bez potwierdzenia nic nie wysyła", async () => {
    const user = userEvent.setup();
    serveLists([], [hold()]);
    mocks.askConfirm.mockResolvedValue(false);
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Zwolnij" }));
    expect(mocks.askConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Zwolnić wstrzymaną płatność?", confirmLabel: "Zwolnij" }),
    );
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("potwierdzone „Zwolnij” wysyła zwolnienie sporu z note: null", async () => {
    const user = userEvent.setup();
    serveLists([], [hold()]);
    mocks.askConfirm.mockResolvedValue(true);
    mocks.post.mockResolvedValue({ data: hold({ released_at: "2026-11-25T08:00:00Z" }) });
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Zwolnij" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(`${PAY}/holds/3/release`, { note: null }),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith("Płatność zwolniona.", "success"),
    );
  });

  it("błąd zwolnienia idzie toastem z treścią serwera", async () => {
    const user = userEvent.setup();
    serveLists([], [hold()]);
    mocks.askConfirm.mockResolvedValue(true);
    mocks.post.mockRejectedValue(apiError("Spór już zwolniony."));
    wrap(<ContractorBlocks canWrite onEdit={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Zwolnij" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Spór już zwolniony."),
        "error",
      ),
    );
  });
});

describe("GarnishmentDialog — formularz zajęcia", () => {
  const target = (g: Garnishment | null = null) => ({
    kind: "garnishment" as const,
    contractId: 42,
    label: "Jan Testowy · Firma Testowa sp. z o.o.",
    garnishment: g,
  });

  it("nowe zajęcie: dzisiejsza data doręczenia i koszty 0, kwota z przecinkiem i spacją idzie jako 1234.50", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mocks.post.mockResolvedValue({ data: { ...garnishment(), released_from_batches: [] } });
    wrap(<GarnishmentDialog target={target()} onClose={onClose} />);
    expect(screen.getByText(/Zajęcie wierzytelności —/)).toHaveTextContent(
      "Jan Testowy · Firma Testowa sp. z o.o.",
    );
    const served = screen.getByLabelText("Data doręczenia");
    expect(served).toHaveValue("2026-11-25");
    expect(served).toHaveAttribute("max", "2026-11-25");
    expect(screen.getByLabelText("Koszty")).toHaveValue("0");

    await user.selectOptions(screen.getByLabelText("Rodzaj organu"), "tax_office");
    await user.type(screen.getByLabelText("Nazwa organu"), " Urząd Skarbowy Testowo ");
    await user.type(screen.getByLabelText("Sygnatura sprawy"), "US-7/26");
    await user.type(screen.getByLabelText("Należność główna"), "1 234,50");
    await user.type(screen.getByLabelText("Rachunek organu"), "22 2222 2222 2222 2222 2222 2222");
    await user.click(screen.getByRole("button", { name: "Zapisz zajęcie" }));

    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(`${PAY}/garnishments`, {
        authority_kind: "tax_office",
        authority_name: "Urząd Skarbowy Testowo",
        case_number: "US-7/26",
        served_on: "2026-11-25",
        principal_amount: "1234.50",
        costs_amount: "0.00",
        interest_mode: "unknown",
        interest_amount: null,
        interest_rate: null,
        interest_from: null,
        authority_account: "22222222222222222222222222",
        note: null,
        contract_id: 42,
      }),
    );
    expect(mocks.put).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        "Zajęcie zapisane — paczka podzieli płatność.",
        "success",
      ),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("należność 0 zł nie przechodzi walidacji i nic nie idzie do serwera", async () => {
    const user = userEvent.setup();
    wrap(<GarnishmentDialog target={target()} onClose={vi.fn()} />);
    await user.type(screen.getByLabelText("Nazwa organu"), "Komornik Przykładowy");
    await user.type(screen.getByLabelText("Sygnatura sprawy"), "KM 1/26");
    await user.type(screen.getByLabelText("Należność główna"), "0,00");
    await user.click(screen.getByRole("button", { name: "Zapisz zajęcie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Kwota należności musi być większa od zera.",
    );
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("odsetki z pisma: pole kwoty pojawia się i jego wartość idzie w żądaniu", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: { ...garnishment(), released_from_batches: [] } });
    wrap(<GarnishmentDialog target={target()} onClose={vi.fn()} />);
    expect(screen.queryByLabelText("Kwota odsetek")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Odsetki"), "fixed");
    await user.type(screen.getByLabelText("Nazwa organu"), "Komornik Przykładowy");
    await user.type(screen.getByLabelText("Sygnatura sprawy"), "KM 1/26");
    await user.type(screen.getByLabelText("Należność główna"), "500");
    await user.click(screen.getByRole("button", { name: "Zapisz zajęcie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Wpisz kwotę odsetek z pisma organu.",
    );
    await user.type(screen.getByLabelText("Kwota odsetek"), "12,5");
    await user.click(screen.getByRole("button", { name: "Zapisz zajęcie" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        `${PAY}/garnishments`,
        expect.objectContaining({
          principal_amount: "500.00",
          interest_mode: "fixed",
          interest_amount: "12.50",
          interest_rate: null,
        }),
      ),
    );
    // Po udanym zapisie poprzedni komunikat walidacji znika.
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("odsetki stopą: stopa i dzień początkowy w żądaniu", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: { ...garnishment(), released_from_batches: [] } });
    wrap(<GarnishmentDialog target={target()} onClose={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Odsetki"), "rate");
    await user.type(screen.getByLabelText("Nazwa organu"), "Komornik Przykładowy");
    await user.type(screen.getByLabelText("Sygnatura sprawy"), "KM 1/26");
    await user.type(screen.getByLabelText("Należność główna"), "500");
    await user.type(screen.getByLabelText("Stopa odsetek"), "11,25");
    await user.click(screen.getByRole("button", { name: "Zapisz zajęcie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Podaj dzień, od którego liczyć odsetki.",
    );
    await user.type(screen.getByLabelText("Odsetki od dnia"), "2026-10-05");
    await user.click(screen.getByRole("button", { name: "Zapisz zajęcie" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        `${PAY}/garnishments`,
        expect.objectContaining({
          interest_mode: "rate",
          interest_rate: "11.25",
          interest_from: "2026-10-05",
          interest_amount: null,
        }),
      ),
    );
  });

  it("zmiana istniejącego zajęcia: pola wypełnione, zapis przez PUT bez contract_id", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mocks.put.mockResolvedValue({
      data: {
        ...garnishment(),
        released_from_batches: [
          { batch_id: 4, entry_id: 77, file_stale: false, released: false, reason: "downloaded" },
        ],
      },
    });
    wrap(<GarnishmentDialog target={target(garnishment({ note: "pismo z 05.10" }))} onClose={onClose} />);
    expect(screen.getByText(/Zmień zajęcie —/)).toBeInTheDocument();
    expect(screen.getByLabelText("Sygnatura sprawy")).toHaveValue("KM 12/26");
    expect(screen.getByLabelText("Należność główna")).toHaveValue("1500.00");
    expect(screen.getByLabelText("Uwaga")).toHaveValue("pismo z 05.10");
    const costs = screen.getByLabelText("Koszty");
    await user.clear(costs);
    await user.click(screen.getByRole("button", { name: "Zapisz zajęcie" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(`${PAY}/garnishments/5`, {
        authority_kind: "bailiff",
        authority_name: "Komornik Przykładowy",
        case_number: "KM 12/26",
        served_on: "2026-10-05",
        principal_amount: "1500.00",
        // Puste koszty to zero, nie błąd.
        costs_amount: "0.00",
        interest_mode: "none",
        interest_amount: null,
        interest_rate: null,
        interest_from: null,
        authority_account: "11111111111111111111111111",
        note: "pismo z 05.10",
      }),
    );
    expect(mocks.post).not.toHaveBeenCalled();
    // Plik paczki już pobrany: komunikat informacyjny, nie „sukces”.
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("Paczka #4 ma pobrany plik"),
        "info",
      ),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("błąd serwera przy zapisie zostaje w oknie", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mocks.put.mockRejectedValue(apiError("Sygnatura już zapisana na tym kontrakcie."));
    wrap(<GarnishmentDialog target={target(garnishment())} onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Zapisz zajęcie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sygnatura już zapisana na tym kontrakcie.",
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it("„Anuluj” wywołuje onClose", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    wrap(<GarnishmentDialog target={target()} onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("HoldDialog — wstrzymanie płatności", () => {
  it("bez powodu (same spacje) nie wysyła i prosi o powód", async () => {
    const user = userEvent.setup();
    wrap(<HoldDialog item={planItem()} onClose={vi.fn()} />);
    expect(screen.getByText("Spór / wstrzymane — Jan Testowy · 2026-10")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Powód wstrzymania"), "   ");
    await user.click(screen.getByRole("button", { name: "Wstrzymaj płatność" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Podaj powód wstrzymania.");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("bez nazwy sprzedawcy i miesiąca tytuł mówi „kontraktor”", () => {
    wrap(<HoldDialog item={planItem({ seller_name: null, period_month: null })} onClose={vi.fn()} />);
    expect(screen.getByText("Spór / wstrzymane — kontraktor")).toBeInTheDocument();
  });

  it("wstrzymanie zdejmujące z paczki: przycięty powód i toast informacyjny", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mocks.post.mockResolvedValue({
      data: {
        ...hold(),
        released_from_batches: [
          { batch_id: 2, entry_id: 77, file_stale: false, released: false, reason: "executed" },
        ],
      },
    });
    wrap(<HoldDialog item={planItem()} onClose={onClose} />);
    await user.type(screen.getByLabelText("Powód wstrzymania"), "  Spór o godziny  ");
    await user.click(screen.getByRole("button", { name: "Wstrzymaj płatność" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(`${PAY}/holds`, {
        entry_id: 77,
        reason: "Spór o godziny",
      }),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        expect.stringContaining("W paczce #2 bank wykonał już część przelewów"),
        "info",
      ),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("wstrzymanie bez wpływu na paczki: toast sukcesu", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: { ...hold(), released_from_batches: [] } });
    wrap(<HoldDialog item={planItem()} onClose={vi.fn()} />);
    await user.type(screen.getByLabelText("Powód wstrzymania"), "Spór o godziny");
    await user.click(screen.getByRole("button", { name: "Wstrzymaj płatność" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith("Płatność wstrzymana do zwolnienia.", "success"),
    );
  });

  it("błąd wstrzymania zostaje w oknie", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mocks.post.mockRejectedValue(apiError("Rozliczenie już opłacone."));
    wrap(<HoldDialog item={planItem()} onClose={onClose} />);
    await user.type(screen.getByLabelText("Powód wstrzymania"), "Spór o godziny");
    await user.click(screen.getByRole("button", { name: "Wstrzymaj płatność" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Rozliczenie już opłacone.");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("„Anuluj” wywołuje onClose", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    wrap(<HoldDialog item={planItem()} onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(onClose).toHaveBeenCalled();
  });
});
