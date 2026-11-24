import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { CostPaymentPanel } from "@/components/finance/ledger/CostPaymentPanel";
import type { EntryPayment } from "@/lib/api/finance-payments";

/** Intl dla pl-PL grupuje twardą spacją — porównujemy tekst po jej zamianie. */
function text(el: Element | null): string {
  return (el?.textContent ?? "").replace(/[  ]/g, " ");
}

const BASE: EntryPayment = {
  entry_id: 7,
  path: "costs",
  state: "unpaid",
  state_label: "Nieopłacona",
  due_date: "2026-11-30",
  currency: "PLN",
  gross_amount: "1230.00",
  to_pay: "1230.00",
  amount_note: null,
  payable_problem: null,
  paid_on: null,
  paid_source: null,
  paid_source_label: null,
  mode: "standard",
  mode_label: "Zwykły przelew",
  mode_suggested: false,
  account: "11222233334444555566667777",
  account_source: "ksef",
  account_source_label: "z KSeF",
  account_note: null,
  accounts: { manual: null, ksef: [], factor: [], counterparty: null },
  can_remember: true,
  batch: null,
  records: [],
} as EntryPayment;

function renderPanel(data: Partial<EntryPayment> | Error, readOnly = false) {
  if (data instanceof Error) get.mockRejectedValue(data);
  else get.mockResolvedValue({ data: { ...BASE, ...data } });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CostPaymentPanel entryId={7} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-24T10:00:00+01:00"));
  get.mockReset();
  post.mockReset();
  put.mockReset();
  showToast.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CostPaymentPanel — odczyt", () => {
  it("pokazuje kwoty z walutą (pl-PL nie grupuje czterech cyfr), termin i rachunek w grupach po 4 z prefiksem PL", async () => {
    renderPanel({});
    await screen.findByText("Nieopłacona");
    expect(get).toHaveBeenCalledWith("/api/finance/payments/entries/7");
    const body = text(document.body);
    expect(body).toContain("1230,00 zł");
    expect(body).toContain("30.11.2026");
    expect(body).toContain("PL11 2222 3333 4444 5555 6666 7777");
    expect(body).toContain("· z KSeF");
    expect(body).toContain("Zwykły przelew");
  });

  it("waluta obca idzie kodem ISO, nie „zł”", async () => {
    renderPanel({ currency: "EUR", gross_amount: "250", to_pay: "250" });
    await screen.findByText("Nieopłacona");
    expect(text(document.body)).toContain("250,00 EUR");
    expect(text(document.body)).not.toContain("zł");
  });

  it("brak kwoty z API to „—”, nigdy „0 zł”", async () => {
    renderPanel({ gross_amount: null, to_pay: null, due_date: null });
    await screen.findByText("Nieopłacona");
    expect(text(document.body)).not.toMatch(/0,00 zł/);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("problem z kwotą zastępuje „Do zapłaty” i chowa przycisk „Opłacono…”", async () => {
    renderPanel({ payable_problem: "Korekta przewyższa fakturę — sprawdź ręcznie." });
    await screen.findByText("Korekta przewyższa fakturę — sprawdź ręcznie.");
    expect(screen.queryByRole("button", { name: "Opłacono…" })).not.toBeInTheDocument();
  });

  it("notatka do kwoty i tryb z podpowiedzi „do potwierdzenia”", async () => {
    renderPanel({ amount_note: "Pomniejszone o kaucję", mode_suggested: true, mode_label: "Split payment" });
    await screen.findByText("Pomniejszone o kaucję");
    expect(screen.getByText("Split payment (z kwoty — do potwierdzenia przy paczce)")).toBeInTheDocument();
  });

  it("brak trybu pokazuje problem trybu", async () => {
    renderPanel({ mode_label: null, mode_problem: "Brak NIP-u — nie wiadomo, czy split" });
    await screen.findByText("Brak NIP-u — nie wiadomo, czy split");
  });

  it("brak rachunku prosi o wpisanie, a notatka rachunku jest ostrzeżeniem", async () => {
    renderPanel({ account: null });
    await screen.findByText("brak — wpisz poniżej");
  });

  it("notatka rachunku obok rachunku", async () => {
    renderPanel({ account: "PL61109010140000071219812874", account_note: "Inny niż na fakturze" });
    await screen.findByText("Inny niż na fakturze");
  });

  it("ścieżka płacowa: bez „Do zapłaty”, rachunku i formularzy", async () => {
    renderPanel({ path: "payroll", path_label: "Płatne przez listę płac" });
    await screen.findByText("Płatne przez listę płac");
    expect(screen.queryByText("Rachunek")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Opłacono…" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Rachunek odbiorcy")).not.toBeInTheDocument();
  });

  it("tylko odczyt: bez formularza rachunku i zapłaty", async () => {
    renderPanel({}, true);
    await screen.findByText("Nieopłacona");
    expect(screen.queryByLabelText("Rachunek odbiorcy")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Opłacono…" })).not.toBeInTheDocument();
  });

  it("w paczce: numer paczki z kwotą, bez zmiany rachunku i „Opłacono”", async () => {
    renderPanel({
      state: "in_batch",
      state_label: "W paczce",
      batch: { id: 31, execution_date: "2026-11-25", mode: "standard", amount: "1230.00" },
    });
    await screen.findByText("W paczce");
    expect(text(document.body)).toContain("#31 · 25.11.2026 · 1230,00 zł");
    expect(screen.queryByLabelText("Rachunek odbiorcy")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Opłacono…" })).not.toBeInTheDocument();
    expect(screen.getByText(/Faktura jest w paczce czekającej na bank/)).toBeInTheDocument();
  });

  it("opłacona: data i źródło zapłaty, lista zapłat, bez „Opłacono…”", async () => {
    renderPanel({
      state: "paid",
      state_label: "Opłacona",
      paid_on: "2026-11-20",
      paid_source_label: "wyciąg",
      records: [
        {
          id: 1,
          kind: "statement_line",
          match_status: "matched",
          amount: "1000.00",
          currency: "PLN",
          booked_on: "2026-11-19",
          title: null,
          reason: null,
        },
        {
          id: 2,
          kind: "manual",
          match_status: "matched",
          amount: "230.00",
          currency: "PLN",
          booked_on: "2026-11-20",
          title: null,
          reason: "karta firmowa",
        },
      ],
    } as Partial<EntryPayment>);
    await screen.findByText("Opłacona");
    const body = text(document.body);
    expect(body).toContain("20.11.2026 · wyciąg");
    expect(body).toContain("1000,00 zł · wyciąg");
    expect(body).toContain("230,00 zł · ręcznie · karta firmowa");
    expect(screen.queryByRole("button", { name: "Opłacono…" })).not.toBeInTheDocument();
  });

  it("awaria odczytu to komunikat błędu z ponowieniem, nie pusty panel", async () => {
    renderPanel(new Error("503"));
    expect(await screen.findByRole("button", { name: /spróbuj ponownie/i })).toBeInTheDocument();
    expect(screen.queryByText("Płatność")).not.toBeInTheDocument();
  });
});

describe("CostPaymentPanel — zapis", () => {
  it("rachunek: wysyła przycięty numer i domyślnie nie zapamiętuje w kartotece", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({ data: { ...BASE, account: "PL61109010140000071219812874" } });
    renderPanel({ account: null });
    const input = await screen.findByLabelText("Rachunek odbiorcy");
    await user.type(input, "  PL61109010140000071219812874  ");
    await user.click(screen.getByRole("button", { name: "Zapisz rachunek" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/finance/payments/entries/7", {
        account: "PL61109010140000071219812874",
        remember: false,
      }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Rachunek zapisany.", "success"));
  });

  it("rachunek: pusty wpis czyści ręczny rachunek (null), „zapamiętaj” jedzie jako true", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({ data: BASE });
    renderPanel({ accounts: { manual: "PL00", ksef: [], factor: [], counterparty: null } });
    const input = await screen.findByLabelText("Rachunek odbiorcy");
    await user.clear(input);
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Zapisz rachunek" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/finance/payments/entries/7", { account: null, remember: true }),
    );
  });

  it("rachunek: bez prawa do kartoteki nie ma pola „zapamiętaj”", async () => {
    renderPanel({ can_remember: false });
    await screen.findByLabelText("Rachunek odbiorcy");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("rachunek: błąd zapisu idzie toastem", async () => {
    const user = userEvent.setup();
    put.mockRejectedValue(new Error("boom"));
    renderPanel({});
    await user.click(await screen.findByRole("button", { name: "Zapisz rachunek" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
  });

  it("opłacono: data domyślnie dziś (Warszawa), kwota z przecinkiem zamieniona na kropkę", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ data: { ...BASE, state: "paid", state_label: "Opłacona" } });
    renderPanel({});
    await user.click(await screen.findByRole("button", { name: "Opłacono…" }));
    expect(screen.getByLabelText("Data zapłaty")).toHaveValue("2026-11-24");
    expect(screen.getByLabelText("Data zapłaty")).toHaveAttribute("max", "2026-11-24");
    expect(screen.getByLabelText("Kwota zapłaty")).toHaveAttribute("placeholder", "1230.00 (całość)");
    await user.type(screen.getByLabelText("Kwota zapłaty"), "100,50");
    const save = screen.getByRole("button", { name: "Zapisz" });
    await user.type(screen.getByLabelText("Powód"), "ka");
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Powód"), "rta");
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/payments/entries/7/paid", {
        amount: "100.50",
        paid_on: "2026-11-24",
        reason: "karta",
      }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapłata zapisana.", "success"));
  });

  it("opłacono: pusta kwota = całość (bez pola amount)", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ data: BASE });
    renderPanel({ to_pay: null });
    await user.click(await screen.findByRole("button", { name: "Opłacono…" }));
    expect(screen.getByLabelText("Kwota zapłaty")).toHaveAttribute("placeholder", "kwota");
    await user.type(screen.getByLabelText("Powód"), "gotówka");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/payments/entries/7/paid", {
        amount: undefined,
        paid_on: "2026-11-24",
        reason: "gotówka",
      }),
    );
  });

  it("opłacono: błąd zapisu idzie toastem, a „Anuluj” zamyka formularz", async () => {
    const user = userEvent.setup();
    post.mockRejectedValue(new Error("boom"));
    renderPanel({});
    await user.click(await screen.findByRole("button", { name: "Opłacono…" }));
    await user.type(screen.getByLabelText("Powód"), "przelew");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(screen.getByRole("button", { name: "Opłacono…" })).toBeInTheDocument();
  });
});
