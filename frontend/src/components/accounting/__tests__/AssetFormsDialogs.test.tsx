import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: vi.fn(),
    patch: (...a: unknown[]) => patch(...a),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));

let accounting: { config: { today: string }; period: { year: number; month: number } };
vi.mock("@/components/accounting/AccountingShell", () => ({
  useAccounting: () => accounting,
}));

import { AssetFormModal, ImportModal, OperationModal } from "@/components/accounting/AssetForms";
import type { AssetCard, AssetImportResult } from "@/lib/api/accounting-assets";

const CARD: AssetCard = {
  id: 1,
  inventory_number: "ST/2026/001",
  name: "Stacje robocze (3 szt.)",
  kind: "fixed",
  kind_label: "Środek trwały",
  kst: "491",
  accepted_on: "2026-07-14",
  initial_value: 3_690_000,
  asset_account: "010",
  depreciation_account: "070",
  mpk: "OG",
  mpk_label: "Koszty ogólne",
  balance_method: "linear",
  balance_rate: "30",
  tax_method: "linear",
  tax_rate: "30",
  coefficient: "2.0",
  method_labels: { linear: "liniowa", degressive: "degresywna", one_off: "jednorazowa", none: "bez amortyzacji" },
  status: "in_use",
  status_label: "w użyciu",
  disposed_on: null,
  note: "Pokój 2",
  opening: null,
  equipment: { id: 9, inventory_number: "IT-009", serial_number: "SN-1", model: "Laptop Testowy 14", category: "laptop", status: "in_use" },
  position: { month: "2026-10", value: 3_690_000, accumulated: 276_750, net: 3_413_250, amount: 92_250, monthly: 92_250, plan_end: "2029-11", tax_plan_end: "2029-11" },
  balance_plan: [],
  tax_plan: [],
  operations: [
    {
      id: 11,
      op_type: "OT",
      label: "Przyjęcie (OT)",
      number: "OT 1/2026",
      op_date: "2026-07-14",
      amount: 3_690_000,
      mpk_from: null,
      mpk_to: null,
      counter_account: "080",
      posted: true,
      cost_entry: null,
      note: "",
      document: { id: 70, number: "OT 1/2026", status: "approved", journal_no: 1 },
      can_delete: false,
    },
  ],
  locked: "amortyzacja 08.2026, zapis nr 3",
  can_manage: true,
  can_delete: false,
};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

function field(dialog: HTMLElement, label: string | RegExp) {
  const text = within(dialog).getByText(label, { selector: "label" });
  return text.querySelector("input, select") as HTMLInputElement | HTMLSelectElement;
}

const REFUSAL = (detail: string) => ({ isAxiosError: true, response: { status: 422, data: { detail } } });

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  showToast.mockReset();
  accounting = { config: { today: "2026-10-20" }, period: { year: 2026, month: 10 } };
});

describe("Przyjęcie środka (OT) — walidacja", () => {
  it("pusty formularz nie idzie do API i wypisuje wszystkie braki", async () => {
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    for (const problem of [
      "Podaj nazwę środka.",
      "Podaj symbol KŚT (np. 491).",
      "Podaj wartość początkową większą od zera.",
      "Plan bilansowy: podaj stawkę.",
      "Plan podatkowy: podaj stawkę.",
    ]) {
      expect(within(dialog).getByText(problem)).toBeInTheDocument();
    }
    expect(post).not.toHaveBeenCalled();
  });

  it("wartość zero albo ujemna i stawka ponad 100% są odrzucane", async () => {
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    await user.type(field(dialog, "Nazwa"), "Serwer");
    await user.type(field(dialog, "KŚT (2016)"), "491");
    await user.type(field(dialog, "Wartość początkowa, zł"), "0,00");
    await user.type(field(dialog, "Stawka bilansowa, %"), "120");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    expect(within(dialog).getByText("Podaj wartość początkową większą od zera.")).toBeInTheDocument();
    expect(within(dialog).getByText("Stawka bilansowa: od 0 do 100%.")).toBeInTheDocument();
    await user.clear(field(dialog, "Wartość początkowa, zł"));
    await user.type(field(dialog, "Wartość początkowa, zł"), "-100");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    expect(within(dialog).getByText("Podaj wartość początkową większą od zera.")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("WNiP: bez KŚT, konta 020/071 i bez metody degresywnej podatkowo", async () => {
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(field(dialog, /^Podatkowo — metoda/), "degressive");
    expect(field(dialog, /^Współczynnik degresywnej/)).toBeEnabled();
    await user.selectOptions(field(dialog, /^Rodzaj/), "intangible");
    expect(field(dialog, "KŚT — nie dotyczy WNiP")).toBeDisabled();
    expect(field(dialog, "Konto środka")).toHaveValue("020");
    expect(field(dialog, "Konto umorzenia")).toHaveValue("071");
    const tax = field(dialog, /^Podatkowo — metoda/) as HTMLSelectElement;
    // Zmiana rodzaju przestawia degresywną na liniową i usuwa ją z listy.
    expect(tax).toHaveValue("linear");
    expect([...tax.options].map((o) => o.value)).not.toContain("degressive");
    expect(field(dialog, /^Współczynnik degresywnej/)).toBeDisabled();
  });

  it("współczynnik degresywnej spoza 1,0–2,0 blokuje zapis", async () => {
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(field(dialog, /^Bilansowo — metoda/), "degressive");
    await user.clear(field(dialog, /^Współczynnik degresywnej/));
    await user.type(field(dialog, /^Współczynnik degresywnej/), "2,5");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    expect(within(dialog).getByText("Współczynnik degresywnej: od 1,0 do 2,0.")).toBeInTheDocument();
  });
});

describe("Przyjęcie środka (OT) — zapis", () => {
  it("stan z Symfonii: umorzenie musi być kwotą; poprawny stan idzie bez OT w księdze", async () => {
    post.mockResolvedValue({ data: { id: 5, inventory_number: "ST/2025/007" } });
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={onClose} onSaved={onSaved} />);
    const dialog = await screen.findByRole("dialog");
    await user.type(field(dialog, "Nazwa"), "Serwer plików");
    await user.type(field(dialog, "KŚT (2016)"), "491");
    await user.type(field(dialog, "Wartość początkowa, zł"), "24 600,00");
    await user.type(field(dialog, "Stawka bilansowa, %"), "30");
    await user.selectOptions(field(dialog, /^Bilansowo — metoda/), "degressive");
    await user.click(within(dialog).getByRole("checkbox", { name: /Środek przyjęty wcześniej/ }));
    expect(within(dialog).queryByText("Konto przeciwstawne")).not.toBeInTheDocument();
    await user.clear(field(dialog, "Umorzenie bilansowe, zł"));
    await user.type(field(dialog, "Umorzenie bilansowe, zł"), "dużo");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    expect(within(dialog).getByText("Stan z Symfonii: umorzenie jako kwota (np. 1234,56).")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();

    await user.clear(field(dialog, "Umorzenie bilansowe, zł"));
    await user.type(field(dialog, "Umorzenie bilansowe, zł"), "1 230,50");
    await user.type(field(dialog, "Bilansowe na początek roku"), "0");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/api/accounting/assets");
    expect(body).toMatchObject({
      initial_value: "24600.00",
      balance_method: "degressive",
      coefficient: "2.00",
      opening: { month: "2026-10-01", balance: "1230.50", tax: null, balance_year: "0.00", tax_year: null },
    });
    expect(body).not.toHaveProperty("post_intake");
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(5));
    expect(showToast).toHaveBeenCalledWith("Przyjęto ST/2025/007.");
    expect(onClose).toHaveBeenCalled();
  });

  it("faktura z kolejki kosztów podpowiada wartość netto, datę i uwagi; bez OT konto przeciwstawne jest null", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === "/api/accounting/assets/options/cost-entries")
        return {
          data: {
            items: [
              { id: 31, invoice_number: "FV 7/10/2026", seller_name: "Firma Testowa sp. z o.o.", issue_date: "2026-09-30", currency: "PLN", net_amount: 1_234_567 },
            ],
          },
        };
      throw new Error(`nieoczekiwane ${url}`);
    });
    post.mockResolvedValue({ data: { id: 6, inventory_number: "ST/2026/006" } });
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    await user.click(field(dialog, "Z faktury z kolejki kosztów (opcjonalnie)"));
    await user.click(await within(dialog).findByRole("button", { name: /FV 7\/10\/2026/ }));
    expect(within(dialog).getByText(/Faktura FV 7\/10\/2026 · Firma Testowa sp\. z o\.o\. · netto 12 345,67 PLN/)).toBeInTheDocument();
    expect(field(dialog, "Wartość początkowa, zł")).toHaveValue("12345,67");
    expect(field(dialog, "Data przyjęcia")).toHaveValue("2026-09-30");
    expect(field(dialog, "Uwagi")).toHaveValue("Faktura FV 7/10/2026 — Firma Testowa sp. z o.o.");
    await user.type(field(dialog, "Nazwa"), "Serwer");
    await user.type(field(dialog, "KŚT (2016)"), "491");
    await user.type(field(dialog, "Stawka bilansowa, %"), "30");
    await user.click(within(dialog).getByRole("checkbox", { name: "OT w księdze" }));
    expect(field(dialog, "Konto przeciwstawne")).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toMatchObject({
      initial_value: "12345.67",
      accepted_on: "2026-09-30",
      post_intake: false,
      counter_account: null,
      cost_entry_id: 31,
      opening: null,
    });
  });

  it("faktura w walucie nie wpisuje wartości PLN; pusta lista i awaria mówią różne rzeczy", async () => {
    let fail = false;
    get.mockImplementation(async (url: string, opts: { params: { q: string } }) => {
      if (fail) throw new Error("500");
      if (url === "/api/accounting/assets/options/cost-entries" && opts.params.q === "")
        return { data: { items: [{ id: 32, invoice_number: null, seller_name: null, issue_date: null, currency: "EUR", net_amount: 50_000 }] } };
      return { data: { items: [] } };
    });
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    const search = field(dialog, "Z faktury z kolejki kosztów (opcjonalnie)");
    await user.click(search);
    await user.click(await within(dialog).findByRole("button", { name: /#32/ }));
    expect(field(dialog, "Wartość początkowa, zł")).toHaveValue("");
    expect(field(dialog, "Data przyjęcia")).toHaveValue("2026-10-20");
    expect(within(dialog).getByText(/Faktura 32 · — · netto 500,00 EUR/)).toBeInTheDocument();
    await user.click(within(dialog).getAllByRole("button", { name: "Odłącz" })[0]);
    const again = field(dialog, "Z faktury z kolejki kosztów (opcjonalnie)");
    await user.click(again);
    await user.type(again, "nic");
    expect(await within(dialog).findByText("Nie ma takiej faktury w kolejce kosztów.")).toBeInTheDocument();
    fail = true;
    await user.type(again, "x");
    expect(await within(dialog).findByText("Nie udało się wczytać faktur.")).toBeInTheDocument();
    expect(within(dialog).queryByText("Nie ma takiej faktury w kolejce kosztów.")).not.toBeInTheDocument();
    await user.click(within(dialog).getAllByRole("button", { name: "Zamknij listę" })[0]);
    expect(within(dialog).queryByText("Nie udało się wczytać faktur.")).not.toBeInTheDocument();
  });

  it("pozycja „Sprzętu” podpowiada nazwę i idzie jako equipment_item_id", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === "/api/accounting/assets/options/equipment")
        return { data: { items: [{ id: 9, inventory_number: "IT-009", serial_number: "SN-1", model: "Laptop Testowy 14", category: "laptop", status: "in_use" }] } };
      return { data: { items: [] } };
    });
    post.mockResolvedValue({ data: { id: 7, inventory_number: "ST/2026/007" } });
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    await user.click(field(dialog, "Pozycja „Sprzętu” (gdy dotyczy)"));
    await user.click(await within(dialog).findByRole("button", { name: /Laptop Testowy 14/ }));
    expect(within(dialog).getByText("Laptop Testowy 14 · nr IT-009 · SN SN-1")).toBeInTheDocument();
    expect(field(dialog, "Nazwa")).toHaveValue("Laptop Testowy 14");
    await user.type(field(dialog, "KŚT (2016)"), "491");
    await user.type(field(dialog, "Wartość początkowa, zł"), "5000");
    await user.type(field(dialog, "Stawka bilansowa, %"), "30");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toMatchObject({ equipment_item_id: 9, name: "Laptop Testowy 14", initial_value: "5000.00" });
  });

  it("awaria listy „Sprzętu” to komunikat błędu, nie „nie ma pozycji”", async () => {
    get.mockRejectedValue(new Error("500"));
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    await user.click(field(dialog, "Pozycja „Sprzętu” (gdy dotyczy)"));
    expect(await within(dialog).findByText("Nie udało się wczytać „Sprzętu”.")).toBeInTheDocument();
    expect(within(dialog).queryByText("Nie ma takiej pozycji bez karty środka.")).not.toBeInTheDocument();
  });

  it("odmowa serwera pokazuje powód i nie zamyka okna", async () => {
    post.mockRejectedValue(REFUSAL("Numer ST/2026/001 jest już zajęty."));
    const onClose = vi.fn();
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={null} intakeAccount="080" onClose={onClose} />);
    const dialog = await screen.findByRole("dialog");
    await user.type(field(dialog, "Nazwa"), "Serwer");
    await user.type(field(dialog, "KŚT (2016)"), "491");
    await user.type(field(dialog, "Wartość początkowa, zł"), "100");
    await user.type(field(dialog, "Stawka bilansowa, %"), "30");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Numer ST/2026/001 jest już zajęty.", "error"));
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("Karta środka z zatwierdzonym zapisem", () => {
  it("pokazuje dane z karty i zapisuje tylko opis PATCH-em", async () => {
    patch.mockResolvedValue({ data: { id: 1, inventory_number: "ST/2026/001" } });
    const onClose = vi.fn();
    const user = userEvent.setup();
    wrap(<AssetFormModal open editing={CARD} intakeAccount="080" onClose={onClose} />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Karta środka ST/2026/001")).toBeInTheDocument();
    expect(within(dialog).getByText(/zmienisz tylko opis/)).toBeInTheDocument();
    expect(field(dialog, "Wartość początkowa, zł")).toHaveValue("36900,00");
    expect(field(dialog, "Wartość początkowa, zł")).toBeDisabled();
    expect(field(dialog, /^Rodzaj/)).toBeDisabled();
    expect(field(dialog, "MPK")).toBeDisabled();
    expect(field(dialog, /^Współczynnik degresywnej/)).toHaveValue("2,0");
    expect(within(dialog).queryByRole("checkbox", { name: /Środek przyjęty wcześniej/ })).not.toBeInTheDocument();
    expect(within(dialog).getByText("Laptop Testowy 14 · nr IT-009 · SN SN-1")).toBeInTheDocument();
    await user.clear(field(dialog, "Uwagi"));
    await user.type(field(dialog, "Uwagi"), "Pokój 3");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz kartę" }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch).toHaveBeenCalledWith("/api/accounting/assets/1", {
      name: "Stacje robocze (3 szt.)",
      kst: "491",
      inventory_number: "ST/2026/001",
      note: "Pokój 3",
      equipment_item_id: 9,
    });
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano ST/2026/001."));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("Dokumenty środka (UL, MT, LT, SP)", () => {
  it("ulepszenie: ujemna wartość odmówiona, poprawna idzie z kwotą i pustym kontem jako null", async () => {
    post.mockResolvedValue({ data: { id: 40, number: "UL 1/2026" } });
    const onClose = vi.fn();
    const user = userEvent.setup();
    wrap(<OperationModal asset={CARD} type="UL" onClose={onClose} />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Ulepszenie — zwiększenie wartości · ST/2026/001")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    expect(within(dialog).getByText("Podaj wartość ulepszenia większą od zera.")).toBeInTheDocument();
    await user.type(field(dialog, "Wartość ulepszenia, zł"), "-1500");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    expect(post).not.toHaveBeenCalled();
    await user.clear(field(dialog, "Wartość ulepszenia, zł"));
    await user.type(field(dialog, "Wartość ulepszenia, zł"), "1 500,5");
    await user.type(field(dialog, "Uwagi"), "  Dysk  ");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/accounting/assets/1/operations", {
      op_type: "UL",
      op_date: "2026-10-20",
      amount: "1500.50",
      mpk_to: null,
      counter_account: null,
      note: "Dysk",
    });
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano UL 1/2026."));
    expect(onClose).toHaveBeenCalled();
  });

  it("zmiana MPK: zła wartość odmówiona, małe litery zamieniane na wielkie, bez obecnego MPK na liście", async () => {
    post.mockResolvedValue({ data: { id: 41, number: "MT 1/2026" } });
    const user = userEvent.setup();
    wrap(<OperationModal asset={CARD} type="MT" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    const input = field(dialog, "Nowe MPK (teraz Koszty ogólne)");
    const options = [...document.querySelectorAll("#asset-mpk-move option")].map((o) => o.getAttribute("value"));
    expect(options).toEqual(["FO", "BO"]);
    await user.type(input, "X1");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    expect(within(dialog).getByText("Nowe MPK: OG, FO, BO albo K<id klienta>.")).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, " k12 ");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toMatchObject({ op_type: "MT", mpk_to: "K12", amount: null, counter_account: null });
  });

  it("sprzedaż: cena pusta wolno, zero odmówione; likwidacja ma pole „Powód likwidacji”", async () => {
    post.mockResolvedValue({ data: { id: 42, number: "SP 1/2026" } });
    const user = userEvent.setup();
    const { unmount } = wrap(<OperationModal asset={CARD} type="SP" onClose={vi.fn()} />);
    let dialog = await screen.findByRole("dialog");
    await user.type(field(dialog, "Cena sprzedaży netto, zł (informacyjnie)"), "0");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    expect(within(dialog).getByText("Cena sprzedaży: kwota większa od zera.")).toBeInTheDocument();
    await user.clear(field(dialog, "Cena sprzedaży netto, zł (informacyjnie)"));
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toMatchObject({ op_type: "SP", amount: null });
    unmount();

    post.mockReset();
    post.mockRejectedValue(REFUSAL("Środek jest już zlikwidowany."));
    wrap(<OperationModal asset={CARD} type="LT" onClose={vi.fn()} />);
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByText(/zł/, { selector: "label" })).not.toBeInTheDocument();
    await user.type(field(dialog, "Powód likwidacji"), "Zniszczony");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Środek jest już zlikwidowany.", "error"));
    expect(post.mock.calls[0][1]).toMatchObject({ op_type: "LT", amount: null, note: "Zniszczony" });
  });

  it("bez daty dokumentu nie ma zapisu", async () => {
    const user = userEvent.setup();
    wrap(<OperationModal asset={CARD} type="LT" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    await user.clear(field(dialog, "Data dokumentu"));
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dokument" }));
    expect(within(dialog).getByText("Podaj datę dokumentu.")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });
});

function importResult(overrides: Partial<AssetImportResult> = {}): AssetImportResult {
  return {
    month: "2025-12",
    saved: false,
    created: 0,
    rows: 3,
    valid: 2,
    skipped_disposed: 1,
    columns: {},
    preview: [
      { line: 2, inventory_number: null, name: "Drukarka", kind: "fixed", kst: "491", accepted_on: "2024-05-02", initial_value: 450_000, balance: 0, tax: null, balance_method: "linear", balance_rate: "30.00", mpk: "OG" },
    ],
    errors: [],
    errors_total: 0,
    missing_accounts: [],
    totals: { initial: 450_000, balance: -1_050, tax: 0 },
    ...overrides,
  };
}

describe("Import ewidencji z Symfonii", () => {
  it("w styczniu stan domyślnie na koniec grudnia poprzedniego roku; błędy blokują zapis", async () => {
    accounting = { config: { today: "2026-01-15" }, period: { year: 2026, month: 1 } };
    post
      .mockResolvedValueOnce({
        data: importResult({
          errors: [{ line: 4, problems: ["Brak daty przyjęcia.", "Wartość nie jest kwotą."] }],
          errors_total: 1,
          missing_accounts: ["011", "071-2"],
        }),
      })
      .mockResolvedValueOnce({ data: importResult() })
      .mockResolvedValueOnce({ data: importResult({ saved: true, created: 2 }) });
    const onClose = vi.fn();
    const user = userEvent.setup();
    wrap(<ImportModal open onClose={onClose} />);
    const dialog = await screen.findByRole("dialog");
    expect(field(dialog, "Stan na koniec miesiąca")).toHaveValue("2025-12");
    expect(within(dialog).getByRole("button", { name: "Podgląd" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Zapisz" })).toBeDisabled();
    const file = field(dialog, "Plik z Symfonii") as HTMLInputElement;
    await user.upload(file, new File(["a;b"], "ewidencja.csv", { type: "text/csv" }));
    await user.click(within(dialog).getByRole("button", { name: "Podgląd" }));
    expect(await within(dialog).findByText("Wiersz 4: Brak daty przyjęcia. Wartość nie jest kwotą.")).toBeInTheDocument();
    expect(within(dialog).getByText("Kont nie ma w planie kont: 011, 071-2.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Zapisz 2 środków" })).toBeDisabled();
    expect(post.mock.calls[0][2]).toMatchObject({ params: { year: 2025, month: 12, save: false } });

    await user.click(within(dialog).getByRole("button", { name: "Podgląd" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Zapisz 2 środków" })).toBeEnabled());
    expect(within(dialog).getByText(/pominięte zbyte: 1 · wartość 4 500,00 zł · umorzenie −10,50 zł/)).toBeInTheDocument();
    expect(within(dialog).getByText("nowy numer · Drukarka")).toBeInTheDocument();
    expect(within(dialog).getByText("02.05.2024")).toBeInTheDocument();
    expect(within(dialog).getByText("liniowa 30%")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Zapisz 2 środków" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano 2 środków ze stanem na koniec 12.2025."));
    expect(post.mock.calls[2][2]).toMatchObject({ params: { year: 2025, month: 12, save: true } });
    expect(onClose).toHaveBeenCalled();
  });

  it("plik bez poprawnych środków nie pozwala zapisać, a błąd pliku idzie komunikatem", async () => {
    post
      .mockRejectedValueOnce(REFUSAL("Plik nie ma kolumny „Nazwa”."))
      .mockResolvedValueOnce({ data: importResult({ valid: 0, preview: [] }) });
    const user = userEvent.setup();
    wrap(<ImportModal open onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    expect(field(dialog, "Stan na koniec miesiąca")).toHaveValue("2026-09");
    await user.upload(field(dialog, "Plik z Symfonii") as HTMLInputElement, new File(["x"], "e.xlsx"));
    await user.click(within(dialog).getByRole("button", { name: "Podgląd" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Plik nie ma kolumny „Nazwa”.", "error"));
    await user.click(within(dialog).getByRole("button", { name: "Podgląd" }));
    expect(await within(dialog).findByRole("button", { name: "Zapisz 0 środków" })).toBeDisabled();
  });
});
