import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  toast: vi.fn(),
  askConfirm: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: mocks.put, patch: vi.fn(), delete: mocks.del },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.askConfirm, confirmDialog: null }),
}));

import { TemplateDialog } from "../TemplateDialog";
import type { InvoiceTemplate } from "@/lib/api/issued-invoices";

const SETTINGS = {
  settings: { default_vat: "8" },
  vat_rates: [
    { code: "23", label: "23%" },
    { code: "8", label: "8%" },
    { code: "np", label: "np." },
  ],
};

function template(overrides: Partial<InvoiceTemplate> = {}): InvoiceTemplate {
  return {
    id: 5,
    kind: "benefit",
    kind_label: "refaktura benefitu",
    benefit: "medical",
    benefit_label: "opieka medyczna",
    name: "Pakiet medyczny — Firma Testowa",
    active: true,
    client_id: 7,
    buyer: { name: "Firma Testowa sp. z o.o.", number: "0000000000", address_l1: "ul. Przykładowa 1", address_l2: "00-001 Warszawa", country: "PL" },
    currency: "PLN",
    series_code: "PL",
    lines: [{ name: "Opieka medyczna {okres}", quantity: "3", unit: "os.", unit_price: "150.00", vat_rate: "np" } as InvoiceTemplate["lines"][number]],
    net: "450.00",
    payment_days: 0,
    notes: null,
    valid_from: "2026-01-01",
    valid_to: null,
    source: "manual",
    source_ref: null,
    in_month: true,
    ...overrides,
  } as InvoiceTemplate;
}

function renderDialog(tpl: InvoiceTemplate | null, onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["issued-invoices", "settings", null], SETTINGS);
  render(
    <QueryClientProvider client={client}>
      <TemplateDialog template={tpl} defaultKind="service" onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
  mocks.get.mockResolvedValue({ data: SETTINGS });
});

describe("TemplateDialog — nowy szablon", () => {
  it("wysyła usługę z pustymi polami jako null i liczbowym terminem płatności", async () => {
    mocks.post.mockResolvedValue({ data: template() });
    const user = userEvent.setup();
    const onClose = renderDialog(null);
    expect(await screen.findByText("Nowy szablon faktury")).toBeInTheDocument();
    expect(screen.queryByLabelText("Benefit")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usuń" })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Nazwa szablonu"), "Najem biura");
    await user.type(screen.getByLabelText("Nazwa"), "Firma Testowa sp. z o.o.");
    await user.selectOptions(screen.getByLabelText("Waluta"), "EUR");
    await user.type(screen.getByLabelText("Pozycja 1: nazwa"), "Najem {{okres}");
    await user.type(screen.getByLabelText("Pozycja 1: cena netto"), "1200,50");
    await user.type(screen.getByLabelText("Termin płatności (dni)"), "a1b4x5678");
    expect(screen.getByLabelText("Termin płatności (dni)")).toHaveValue("145");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    const [url, body] = mocks.post.mock.calls[0];
    expect(url).toBe("/api/finance/issued-invoices/templates");
    expect(body).toEqual({
      kind: "service",
      benefit: null,
      name: "Najem biura",
      buyer: { name: "Firma Testowa sp. z o.o.", number: "", address_l1: "", address_l2: "", country: "PL" },
      currency: "EUR",
      lines: [{ name: "Najem {okres}", quantity: "1", unit: "usł.", unit_price: "1200,50", vat_rate: expect.any(String) }],
      valid_from: null,
      valid_to: null,
      payment_days: 145,
      active: true,
      notes: null,
    });
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Dodano szablon", "success"));
    expect(onClose).toHaveBeenCalled();
  });

  it("nowa pozycja bierze domyślną stawkę VAT z ustawień; ostatniej pozycji nie da się usunąć", async () => {
    const user = userEvent.setup();
    renderDialog(null);
    await screen.findByText("Nowy szablon faktury");
    expect(screen.getByRole("button", { name: "Usuń pozycję 1" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Dodaj pozycję" }));
    expect(screen.getByLabelText("Pozycja 2: stawka VAT")).toHaveValue("8");
    expect(screen.getByLabelText("Pozycja 2: ilość")).toHaveValue("1");
    expect(screen.getByLabelText("Pozycja 2: jednostka")).toHaveValue("usł.");
    await user.type(screen.getByLabelText("Pozycja 2: nazwa"), "Druga");
    await user.click(screen.getByRole("button", { name: "Usuń pozycję 1" }));
    expect(screen.getByLabelText("Pozycja 1: nazwa")).toHaveValue("Druga");
    expect(screen.queryByLabelText("Pozycja 2: nazwa")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Usuń pozycję 1" })).toBeDisabled();
  });

  it("refaktura benefitu wysyła rodzaj benefitu; pusty termin to null (z ustawień)", async () => {
    mocks.post.mockResolvedValue({ data: template() });
    const user = userEvent.setup();
    renderDialog(null);
    await screen.findByText("Nowy szablon faktury");
    await user.selectOptions(screen.getByLabelText("Rodzaj"), "benefit");
    expect(screen.getByLabelText("Benefit")).toHaveValue("sport");
    await user.selectOptions(screen.getByLabelText("Benefit"), "other");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ kind: "benefit", benefit: "other", payment_days: null });
  });

  it("odmowa serwera zostaje w oknie, okno się nie zamyka", async () => {
    mocks.post.mockRejectedValue({ isAxiosError: true, response: { status: 422, data: { detail: "Pozycja 1: cena musi być większa od zera." } } });
    const user = userEvent.setup();
    const onClose = renderDialog(null);
    await screen.findByText("Nowy szablon faktury");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Pozycja 1: cena musi być większa od zera.");
    expect(onClose).not.toHaveBeenCalled();
    expect(mocks.toast).not.toHaveBeenCalled();
  });

  it.todo(
    "pierwsza pozycja nowego szablonu bierze domyślną stawkę VAT z ustawień także wtedy, gdy ustawienia doszły po otwarciu okna — dziś TemplateDialog.tsx:65 liczy `blankLine(defaultVat)` raz, przy „23” zanim przyjdzie `default_vat`",
  );
});

describe("TemplateDialog — istniejący szablon", () => {
  it("wypełnia pola z szablonu, w tym termin 0 dni, i zapisuje PUT-em z wyłączeniem", async () => {
    mocks.put.mockResolvedValue({ data: template() });
    const user = userEvent.setup();
    renderDialog(template());
    expect(await screen.findByText("Szablon faktury")).toBeInTheDocument();
    expect(screen.getByLabelText("Benefit")).toHaveValue("medical");
    expect(screen.getByLabelText("Termin płatności (dni)")).toHaveValue("0");
    expect(screen.getByLabelText("Pozycja 1: cena netto")).toHaveValue("150.00");
    expect(screen.getByLabelText("Pozycja 1: stawka VAT")).toHaveValue("np");
    await user.click(screen.getByRole("checkbox", { name: "Szablon aktywny" }));
    await user.type(screen.getByLabelText("Obowiązuje do"), "2026-12-31");
    await user.type(screen.getByLabelText("Uwagi na fakturze"), "Mechanizm podzielonej płatności");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    const [url, body] = mocks.put.mock.calls[0];
    expect(url).toBe("/api/finance/issued-invoices/templates/5");
    expect(body).toMatchObject({
      kind: "benefit",
      benefit: "medical",
      payment_days: 0,
      active: false,
      valid_from: "2026-01-01",
      valid_to: "2026-12-31",
      notes: "Mechanizm podzielonej płatności",
    });
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Zapisano szablon", "success"));
  });

  it("usunięcie pyta przez useConfirmV2; odmowa nic nie kasuje", async () => {
    mocks.askConfirm.mockResolvedValue(false);
    const user = userEvent.setup();
    const onClose = renderDialog(template());
    await user.click(await screen.findByRole("button", { name: "Usuń" }));
    expect(mocks.askConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Usunąć szablon?", confirmLabel: "Usuń szablon", variant: "destructive" }),
    );
    expect(mocks.del).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("potwierdzone usunięcie kasuje szablon; błąd zostaje w oknie", async () => {
    mocks.askConfirm.mockResolvedValue(true);
    mocks.del
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { detail: "Szablon ma szkic w tym miesiącu." } } })
      .mockResolvedValueOnce({ data: { result: "deleted" } });
    const user = userEvent.setup();
    const onClose = renderDialog(template());
    await user.click(await screen.findByRole("button", { name: "Usuń" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Szablon ma szkic w tym miesiącu.");
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Usuń" }));
    await waitFor(() => expect(mocks.del).toHaveBeenLastCalledWith("/api/finance/issued-invoices/templates/5"));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Usunięto szablon", "success"));
    expect(onClose).toHaveBeenCalled();
  });

  it("szablon bez pozycji dostaje jedną pustą pozycję", async () => {
    renderDialog(template({ lines: [], payment_days: null }));
    await screen.findByText("Szablon faktury");
    expect(screen.getByLabelText("Pozycja 1: nazwa")).toHaveValue("");
    expect(screen.getByLabelText("Termin płatności (dni)")).toHaveValue("");
  });
});
