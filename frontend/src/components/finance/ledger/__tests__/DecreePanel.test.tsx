import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const put = vi.fn();
const get = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
    patch: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { DecreePanel } from "@/components/finance/ledger/DecreePanel";
import type { DecreeSection } from "@/lib/api/finance-posting";

const SECTION: DecreeSection = {
  computed: true,
  manual: false,
  computed_at: "2026-11-13T10:00:00+00:00",
  register: "purchase",
  register_label: "Zakup",
  doc_type: "FVZ",
  description: "Usługi IT 10/2026",
  currency: "PLN",
  rule: { id: 1, label: "Kontraktorzy" },
  positions: [
    {
      kind: "cost",
      kind_label: "Koszt",
      account: "402-203",
      account_name: "Usługi obce — kontraktorzy",
      side: "debit",
      side_label: "Wn",
      amount: "100.00",
      vat_rate: "23",
      deduction: "full",
      deduction_label: "100%",
    },
    {
      kind: "vat",
      kind_label: "VAT",
      account: "221",
      account_name: "VAT naliczony",
      side: "debit",
      side_label: "Wn",
      amount: "23.00",
      vat_rate: "23",
      deduction: "full",
      deduction_label: "100%",
    },
    {
      kind: "counterparty",
      kind_label: "Rozrachunek z kontrahentem",
      account: null,
      account_name: null,
      side: "credit",
      side_label: "Ma",
      amount: "123.00",
      vat_rate: null,
      deduction: null,
      deduction_label: null,
    },
  ],
  debit_total: "123.00",
  credit_total: "123.00",
  balanced: true,
  issues: ["Kontrahent „Dostawca Testowy” nie ma konta rozrachunkowego w kartotece — uzupełnij je w „Kontrahenci”."],
  editable: true,
  batch: null,
  fx_rate: null,
  fx_date: null,
};

const LISTS = {
  doc_types: [
    { value: "FVZ", label: "Faktura VAT zakup" },
    { value: "IU", label: "Import usług" },
  ],
  registers: [{ value: "Zakup", label: "Zakup" }],
  output_registers: [{ value: "Import usług VAT należny", label: "Import usług VAT należny" }],
  vat_accounts: [{ value: "221", label: "VAT naliczony", in_plan: true }],
  output_vat_accounts: [{ value: "226", label: "VAT należny import usług", in_plan: false }],
  jpk_procedures: [{ value: "MK", label: "Metoda kasowa" }],
  import_rates: [23, 8, 5],
  net_accounts: [{ value: "402-215", label: "402-215 Usługi obce" }],
  allocation_accounts: [{ value: "510-5", label: "510-5 Koszty" }],
  offbalance_accounts: [{ value: "902", label: "902 Pozabilansowe" }],
  allocation_offset: "490",
  offbalance_debit: "999",
};

const EFFECTIVE = {
  description: "Usługi IT 10/2026",
  doc_type: "FVZ",
  register: "Zakup",
  net_account: "402-203",
  vat_account: "221",
  output_register: null,
  output_vat_account: null,
  eu: false,
  service: false,
  import_rate: null,
  allocation_account: null,
  car: false,
  offbalance_account: null,
  jpk_procedure: null,
  fx_date: null,
  fx_rate: null,
  fx_table: null,
  service_date: "2026-10-31",
};

function renderPanel(section: DecreeSection = SECTION, readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DecreePanel entryId={42} section={section} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe("DecreePanel", () => {
  beforeEach(() => {
    post.mockReset();
    put.mockReset();
    get.mockReset();
    get.mockResolvedValue({ data: LISTS });
    showToast.mockReset();
  });

  it("pokazuje pozycje, sumy i to, co blokuje księgowanie", () => {
    renderPanel();
    expect(screen.getByText("402-203")).toBeInTheDocument();
    // Pozycja Ma i dwie sumy „Razem”.
    expect(screen.getAllByText("123,00")).toHaveLength(3);
    expect(screen.getByRole("list", { name: "Co blokuje księgowanie" })).toHaveTextContent(
      "nie ma konta rozrachunkowego",
    );
    expect(screen.getByText("Kontraktorzy")).toBeInTheDocument();
  });

  it("waluta obca: kurs NBP i jego dzień na karcie", () => {
    renderPanel({ ...SECTION, currency: "EUR", fx_rate: "4.2512", fx_date: "2026-11-03" });
    expect(screen.getByText("Kurs NBP EUR 4,2512 z 03.11.2026")).toBeInTheDocument();
  });

  it("po „Gotowa” i w podglądzie nie ma przycisków zmiany", () => {
    const { unmount } = renderPanel({ ...SECTION, editable: false });
    expect(screen.queryByRole("button", { name: "Przelicz" })).not.toBeInTheDocument();
    unmount();
    renderPanel(SECTION, true);
    expect(screen.queryByRole("button", { name: "Popraw ręcznie" })).not.toBeInTheDocument();
  });

  it("korekta: zapis dopiero przy koncie i bilansie Wn = Ma", async () => {
    put.mockResolvedValue({ data: { id: 42, decree: SECTION } });
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole("button", { name: "Popraw ręcznie" }));
    const save = screen.getByRole("button", { name: "Zapisz dekret" });
    expect(save).toBeDisabled();
    expect(screen.getByText("Pozycja 3: wpisz numer konta.")).toBeInTheDocument();

    const third = screen.getByRole("group", { name: "Pozycja 3" });
    const account = third.querySelector('input[aria-label="Konto"]') as HTMLInputElement;
    await user.type(account, "201-2-905");
    const amount = third.querySelector('input[aria-label="Kwota"]') as HTMLInputElement;
    await user.clear(amount);
    await user.type(amount, "122,99");
    expect(save).toBeDisabled();
    expect(screen.getByText("Suma Wn (123,00) różni się od sumy Ma (122,99).")).toBeInTheDocument();

    await user.clear(amount);
    await user.type(amount, "123");
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const [url, body] = put.mock.calls[0];
    expect(url).toBe("/api/finance/posting/entries/42/decree");
    expect(body.positions[2]).toEqual({
      kind: "counterparty",
      account: "201-2-905",
      side: "credit",
      amount: "123.00",
      vat_rate: null,
      deduction: null,
    });
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Dekret zapisany.", "success"));
  });

  it("„Przelicz” woła serwer, błąd idzie do komunikatu", async () => {
    post.mockRejectedValue({ response: { status: 409, data: { detail: "Zaksięgowanej faktury tu nie zmieniasz." } } });
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole("button", { name: "Przelicz" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/finance/posting/entries/42/recalculate"));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
  });

  it("opis: rejestry, procedura JPK i data usługi na karcie", () => {
    renderPanel({
      ...SECTION,
      jpk_procedure: "MK",
      service_date: "2026-10-31",
      car: true,
      registers: [
        { name: "Zakup", rate: "23", net: "50.00", vat: "11.50", gross: "61.50", net_cur: null,
          vat_cur: null, gross_cur: null, output: false, eu: false, service: false },
        { name: "Rejestr NP VAT", rate: "23", net: "50.00", vat: "11.50", gross: "61.50",
          net_cur: null, vat_cur: null, gross_cur: null, output: false, eu: false, service: false },
      ],
    });
    expect(screen.getByText(/Rejestr NP VAT · 23% · netto 50,00/)).toBeInTheDocument();
    expect(screen.getByText("MK")).toBeInTheDocument();
    expect(screen.getByText("31.10.2026")).toBeInTheDocument();
    expect(screen.getByText(/½ VAT do odliczenia/)).toBeInTheDocument();
  });

  it("„Opisz do księgowania”: import usług odsłania rejestr należny, zapis woła serwer", async () => {
    put.mockResolvedValue({ data: { id: 42, decree: SECTION } });
    const user = userEvent.setup();
    renderPanel({ ...SECTION, effective: EFFECTIVE, choices: {} });
    await user.click(screen.getByRole("button", { name: "Opisz do księgowania" }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/api/finance/posting/choice-lists"));
    expect(screen.queryByRole("combobox", { name: "Rejestr VAT należnego" })).not.toBeInTheDocument();
    await screen.findByRole("option", { name: "Import usług" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Typ dokumentu" }), "IU");
    expect(screen.getByRole("combobox", { name: "Rejestr VAT należnego" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "VAT należny import usług (brak w planie)" })).toBeInTheDocument();
    await user.type(screen.getByRole("combobox", { name: /Konto „5”/ }), "510-5");
    await user.click(screen.getByRole("button", { name: "Zapisz opis" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const [url, body] = put.mock.calls[0];
    expect(url).toBe("/api/finance/posting/entries/42/description");
    expect(body).toMatchObject({
      doc_type: "IU",
      allocation_account: "510-5",
      net_account: null,
      car: false,
      eu: null,
      service: null,
    });
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Opis zapisany, dekret przeliczony.", "success"),
    );
  });

  it("waluta: pola kursu i tabeli; zła tabela blokuje zapis", async () => {
    const user = userEvent.setup();
    renderPanel({ ...SECTION, currency: "EUR", effective: EFFECTIVE, choices: {} });
    await user.click(screen.getByRole("button", { name: "Opisz do księgowania" }));
    await user.type(screen.getByRole("textbox", { name: "Tabela NBP" }), "kwiecień");
    expect(screen.getByText("Tabela NBP: numer jak 211/A/NBP/2026.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz opis" })).toBeDisabled();
  });
});
