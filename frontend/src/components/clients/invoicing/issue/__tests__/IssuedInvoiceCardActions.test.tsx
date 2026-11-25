import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  toast: vi.fn(),
  push: vi.fn(),
  askConfirm: vi.fn(),
  download: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: mocks.put, patch: vi.fn(), delete: mocks.del },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.askConfirm, confirmDialog: null }),
}));
vi.mock("@/lib/api/issued-invoices", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/issued-invoices")>()),
  downloadIssuedFile: mocks.download,
}));
vi.mock("../CollectiveCorrectionBox", () => ({
  CollectiveCorrectionBox: () => <div data-testid="collective-box" />,
}));

import { IssuedInvoiceCardView } from "../IssuedInvoiceCardView";
import type { IssuedInvoiceCard } from "@/lib/api/issued-invoices";

const CARD = {
  id: 5,
  status: "draft",
  status_label: "Szkic",
  invoice_type: "VAT",
  type_label: "Faktura",
  series_code: "PL",
  invoice_number: null,
  client_id: 7,
  client_name: "Klient Testowy S.A.",
  template_id: null,
  buyer: { name: "Klient Testowy S.A.", number: "0000000000", address_l1: "ul. Przykładowa 5", address_l2: "", country: "PL" },
  buyer_kind: "nip",
  order_group_id: null,
  order_id: null,
  client_order_number: "ZAM/2026/118",
  period: "październik 2026",
  currency: "PLN",
  issue_date: "2026-11-02",
  sale_date: "2026-10-31",
  period_from: "2026-10-01",
  period_to: "2026-10-31",
  due_date: "2026-12-02",
  net: "1000.00",
  vat: "230.00",
  gross: "1230.00",
  ksef_number: null,
  ksef_status_text: null,
  sent_at: null,
  accepted_at: null,
  payment: { status: "none", paid: null },
  lines: [
    { name: "Usługi IT — październik 2026", consultant: null, quantity: "10", unit: "MD", unit_price: "100", vat_rate: "23", net: "1000.00", order_id: null },
  ],
  lines_before: [],
  warnings: [],
  checks: [],
  order_numbers: ["ZAM/2026/118"],
  requirements: [],
  mail: null,
  buyer_options: [],
  rates: [{ code: "23", label: "23%", net: "1000.00", vat: "230.00" }],
  fx: null,
  notes: null,
  correction_reason: null,
  corrects: null,
  collective: null,
  ksef_status_code: null,
  ksef_environment: null,
  has_upo: false,
  has_xml: false,
  sales_invoice_id: null,
  problems: [],
  editable: true,
  can_send: true,
  can_check: false,
  can_correct: false,
  history: [],
  rebate: null,
} as unknown as IssuedInvoiceCard;

function card(overrides: Record<string, unknown> = {}): IssuedInvoiceCard {
  return { ...CARD, ...overrides } as IssuedInvoiceCard;
}

function route(data: IssuedInvoiceCard | Error, ksefReason: string | null = null) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url === "/api/finance/issued-invoices/5") {
      if (data instanceof Error) throw data;
      return { data };
    }
    if (url === "/api/finance/issued-invoices/settings")
      return {
        data: {
          vat_rates: [
            { code: "23", label: "23%" },
            { code: "zw", label: "zw." },
          ],
          ksef: { mode: "test", mode_label: "", enabled: !ksefReason, disabled_reason: ksefReason },
        },
      };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

// Kwoty z formatMoney mają twardą spację przed walutą.
const norm = (text: string | null) => (text ?? "").replace(/\s/g, " ");
const amountOf = (region: HTMLElement, label: string) => norm(within(region).getByText(label).nextElementSibling!.textContent);

const refusal = (detail: string, status = 409) => ({ isAxiosError: true, response: { status, data: { detail } } });

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
});

describe("Karta faktury — wczytanie i kwoty", () => {
  it("awaria karty to błąd z ponowieniem, nie pusta karta", async () => {
    route(new Error("500"));
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByRole("button", { name: "Wyślij do KSeF" })).not.toBeInTheDocument();
  });

  it("stawka bez VAT nie dokleja „+ 0,00”, brutto w walucie, a EUR bez kursu NBP ostrzega", async () => {
    route(
      card({
        currency: "EUR",
        rates: [
          { code: "23", label: "23%", net: "1000.00", vat: "230.00" },
          { code: "zw", label: "zw.", net: "500.00", vat: "0.00" },
        ],
        gross: "1730.00",
      }),
    );
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const amounts = await screen.findByRole("region", { name: "Kwoty" });
    expect(amountOf(amounts, "23%")).toBe("1000,00 EUR + 230,00 EUR");
    expect(amountOf(amounts, "zw.")).toBe("500,00 EUR");
    expect(amountOf(amounts, "Brutto")).toBe("1730,00 EUR");
    expect(within(amounts).getByText("Brak kursu NBP z dnia przed datą dostawy.")).toBeInTheDocument();
  });

  it("kurs NBP pokazuje dzień i miesiąc; KSeF z numerem i środowiskiem testowym", async () => {
    route(
      card({
        currency: "EUR",
        fx: { date: "2026-10-30", rate: "4.2512" },
        status: "accepted",
        status_label: "Przyjęta w KSeF",
        invoice_number: "12/11/2026",
        ksef_number: "0000000000-20261102-ABCDEF-01",
        ksef_environment: "test",
        editable: false,
        can_send: false,
      }),
    );
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    expect(await screen.findByText("Kurs NBP EUR z 30.10: 4.2512 zł")).toBeInTheDocument();
    const ksef = screen.getByRole("region", { name: "KSeF" });
    expect(ksef).toHaveTextContent("0000000000-20261102-ABCDEF-01");
    expect(ksef).toHaveTextContent("środowisko testowe MF");
    expect(screen.getByRole("heading", { name: "Faktura 12/11/2026" })).toBeInTheDocument();
    // Przyjęta faktura: bez edycji, wysyłki i usuwania.
    expect(screen.queryByRole("button", { name: "Wyślij do KSeF" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz szkic" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Nazwa pozycji 1")).toBeDisabled();
  });

  it("problemy przed wysyłką są listą, a pozycja liczy netto z rabatem", async () => {
    route(card({ can_send: false, problems: ["Brak NIP nabywcy.", "Pozycja 1 bez stawki VAT."] }));
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const before = await screen.findByRole("region", { name: "Przed wysyłką" });
    expect(within(before).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Brak NIP nabywcy.",
      "Pozycja 1 bez stawki VAT.",
    ]);
    expect(screen.getByRole("button", { name: "Wyślij do KSeF" })).toBeDisabled();
    await user.type(screen.getByLabelText("Rabat % — pozycja 1"), "10");
    const line = screen.getByLabelText("Nazwa pozycji 1").closest("li")!;
    expect(norm(line.textContent)).toContain("900,00");
  });
});

describe("Karta faktury — szkic", () => {
  it("„Odrzuć zmiany” przywraca dane z karty i zdejmuje blokadę wysyłki", async () => {
    route(card());
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const name = await screen.findByLabelText("Nazwa nabywcy");
    await user.type(name, " zmiana");
    const send = screen.getByRole("button", { name: "Wyślij do KSeF" });
    expect(send).toBeDisabled();
    expect(send).toHaveAttribute("title", "Najpierw zapisz zmiany.");
    await user.click(screen.getByRole("button", { name: "Odrzuć zmiany" }));
    expect(name).toHaveValue("Klient Testowy S.A.");
    expect(send).toBeEnabled();
    expect(screen.getByRole("button", { name: "Zapisz szkic" })).toBeDisabled();
  });

  it("nowa pozycja dziedziczy stawkę VAT pierwszej; kraj nabywcy wielkimi literami; puste daty jako null", async () => {
    route(card());
    mocks.put.mockResolvedValue({ data: card() });
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Pozycja" }));
    expect(screen.getByLabelText("Stawka VAT — pozycja 2")).toHaveValue("23");
    await user.type(screen.getByLabelText("Nazwa pozycji 2"), "Licencja");
    await user.type(screen.getByLabelText("Cena netto — pozycja 2"), "1 234,5");
    await user.clear(screen.getByLabelText("Kraj nabywcy"));
    await user.type(screen.getByLabelText("Kraj nabywcy"), "de");
    await user.clear(screen.getByLabelText("Termin płatności"));
    await user.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    const [url, patch] = mocks.put.mock.calls[0];
    expect(url).toBe("/api/finance/issued-invoices/5");
    expect(patch.buyer.country).toBe("DE");
    expect(patch.due_date).toBeNull();
    expect(patch.currency).toBe("PLN");
    expect(patch.lines[1]).toMatchObject({ name: "Licencja", quantity: "1", unit: "usł.", unit_price: "1234.5", vat_rate: "23", discount_pct: null });
    expect(patch).not.toHaveProperty("correction_reason");
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Zapisano szkic", "success"));
  });

  it("usunięcie pozycji i odmowa zapisu — komunikat z API", async () => {
    route(card());
    mocks.put.mockRejectedValue(refusal("Faktura musi mieć co najmniej jedną pozycję.", 422));
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Usuń pozycję 1" }));
    expect(screen.queryByLabelText("Nazwa pozycji 1")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith("Faktura musi mieć co najmniej jedną pozycję.", "error"),
    );
    expect(mocks.put.mock.calls[0][1].lines).toEqual([]);
  });

  it("kilka zamówień na pozycjach: pole numeru zamówienia zablokowane z listą numerów", async () => {
    route(card({ order_numbers: ["ZAM/1", "ZAM/2"] }));
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const field = await screen.findByLabelText("Numery zamówień klienta (z pozycji)");
    expect(field).toBeDisabled();
    expect(field).toHaveValue("ZAM/1, ZAM/2");
  });

  it("zaliczka ma „Otrzymanie zaliczki” zamiast okresu i nie ma serii", async () => {
    route(card({ invoice_type: "ZAL", type_label: "Faktura zaliczkowa" }));
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    expect(await screen.findByLabelText("Otrzymanie zaliczki")).toHaveValue("2026-10-31");
    expect(screen.queryByLabelText("Okres od")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Seria")).not.toBeInTheDocument();
  });
});

describe("Karta faktury — korekta (KOR)", () => {
  const KOR = {
    invoice_type: "KOR",
    type_label: "Korekta",
    series_code: "KOR",
    corrects: { id: 4, invoice_number: "7/10/2026" },
    lines_before: [{ name: "Usługi IT", consultant: null, quantity: "10", unit: "MD", unit_price: "100", vat_rate: "23", net: "1000.00", order_id: null }],
    rates: [{ code: "23", label: "23%", net: "-100.00", vat: "-23.00" }],
    gross: "-123.00",
    correction_reason: "Błędna ilość",
  };

  it("pokazuje stan przed korektą, ujemną różnicę i blokuje walutę", async () => {
    route(card(KOR));
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    expect(await screen.findByText(/korekta faktury 7\/10\/2026/)).toBeInTheDocument();
    expect(screen.getByText("Stan przed korektą")).toBeInTheDocument();
    expect(norm(screen.getByText(/10 × 100 =/).textContent)).toContain("1000,00 zł");
    expect(screen.getByText("Stan po korekcie")).toBeInTheDocument();
    const amounts = screen.getByRole("region", { name: "Kwoty" });
    expect(within(amounts).getByText("Kwoty (różnica)")).toBeInTheDocument();
    expect(amountOf(amounts, "Brutto")).toBe("-123,00 zł");
    expect(screen.getByLabelText("Waluta")).toBeDisabled();
    expect(screen.queryByLabelText("Seria")).not.toBeInTheDocument();
  });

  it("zapis korekty wysyła przyczynę, bez waluty i serii", async () => {
    route(card(KOR));
    mocks.put.mockResolvedValue({ data: card(KOR) });
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const reason = await screen.findByLabelText("Przyczyna korekty");
    await user.clear(reason);
    await user.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    const patch = mocks.put.mock.calls[0][1];
    expect(patch.correction_reason).toBeNull();
    expect(patch).not.toHaveProperty("currency");
    expect(patch).not.toHaveProperty("series_code");
  });
});

describe("Karta faktury — wysyłka, status, pliki", () => {
  it("ponowna wysyłka z numerem ostrzega o tym samym numerze; odrzucenie idzie jako błąd z opisem KSeF", async () => {
    route(card({ invoice_number: "12/11/2026", status: "rejected", status_label: "Odrzucona" }));
    mocks.askConfirm.mockResolvedValue(true);
    mocks.post.mockResolvedValue({ data: card({ status: "rejected", status_label: "Odrzucona", ksef_status_text: "Błędny NIP nabywcy" }) });
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Wyślij do KSeF" }));
    expect(mocks.askConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ description: expect.stringContaining("Faktura 12/11/2026 idzie do KSeF ponownie, z tym samym numerem") }),
    );
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/finance/issued-invoices/5/send"));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Odrzucona — Błędny NIP nabywcy", "error"));
  });

  it("odmowa potwierdzenia nie wysyła; błąd wysyłki idzie komunikatem", async () => {
    route(card());
    mocks.askConfirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    mocks.post.mockRejectedValue(refusal("KSeF nie odpowiada.", 502));
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Wyślij do KSeF" }));
    await waitFor(() => expect(mocks.askConfirm).toHaveBeenCalledTimes(1));
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Wyślij do KSeF" }));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("KSeF nie odpowiada.", "error"));
  });

  it("„Sprawdź status” woła check; błąd idzie komunikatem", async () => {
    route(card({ status: "sent", status_label: "Wysłana", can_check: true, editable: false, can_send: false }));
    mocks.post.mockRejectedValue(refusal("Sesja KSeF wygasła."));
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Sprawdź status" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/finance/issued-invoices/5/check"));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Sesja KSeF wygasła.", "error"));
  });

  it("pliki dostają nazwę z numerem bez ukośników; szkic bez numeru — „szkic-<id>”", async () => {
    route(card({ invoice_number: "12/11/2026", has_upo: true, has_xml: true }));
    mocks.download.mockResolvedValueOnce(undefined).mockResolvedValueOnce(undefined).mockRejectedValueOnce(refusal("Plik XML nie istnieje.", 404));
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "PDF" }));
    expect(mocks.download).toHaveBeenCalledWith("/api/finance/issued-invoices/5/pdf", "faktura-12-11-2026.pdf");
    await user.click(screen.getByRole("button", { name: "UPO" }));
    expect(mocks.download).toHaveBeenCalledWith("/api/finance/issued-invoices/5/upo", "upo-12-11-2026.xml");
    await user.click(screen.getByRole("button", { name: "XML" }));
    expect(mocks.download).toHaveBeenCalledWith("/api/finance/issued-invoices/5/xml", "fa3-12-11-2026.xml");
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Plik XML nie istnieje.", "error"));
  });

  it("szkic bez numeru pobiera PDF jako „faktura-szkic-5.pdf”, bez UPO i XML", async () => {
    route(card());
    mocks.download.mockResolvedValue(undefined);
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "PDF" }));
    expect(mocks.download).toHaveBeenCalledWith("/api/finance/issued-invoices/5/pdf", "faktura-szkic-5.pdf");
    expect(screen.queryByRole("button", { name: "UPO" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "XML" })).not.toBeInTheDocument();
  });

  it("„Zapisz jako szablon” tylko dla faktury VAT spoza zamówień i szablonów", async () => {
    route(card());
    mocks.post.mockResolvedValueOnce({ data: {} }).mockRejectedValueOnce(refusal("Szablon już istnieje."));
    const user = userEvent.setup();
    const { unmount } = wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Zapisz jako szablon" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/finance/issued-invoices/5/template"));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Zapisano szablon — znajdziesz go w „Szablony”", "success"));
    await user.click(screen.getByRole("button", { name: "Zapisz jako szablon" }));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Szablon już istnieje.", "error"));
    unmount();

    route(card({ order_group_id: 118 }));
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await screen.findByRole("button", { name: "PDF" });
    expect(screen.queryByRole("button", { name: "Zapisz jako szablon" })).not.toBeInTheDocument();
  });
});

describe("Karta faktury — usuwanie i korekta", () => {
  it("szkic bez numeru: „Usuń szkic” po potwierdzeniu wraca do listy faktur", async () => {
    route(card());
    mocks.askConfirm.mockResolvedValue(true);
    mocks.del.mockResolvedValue({ data: { result: "deleted" } });
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Usuń szkic" }));
    expect(mocks.askConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Usunąć szkic?", confirmLabel: "Usuń szkic", variant: "destructive" }),
    );
    await waitFor(() => expect(mocks.del).toHaveBeenCalledWith("/api/finance/issued-invoices/5"));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Usunięto", "success"));
    expect(mocks.push).toHaveBeenCalledWith("/finance?view=sales-invoices");
  });

  it("faktura z numerem: „Wycofaj” zostawia ślad numeru i nie wychodzi z karty", async () => {
    route(card({ invoice_number: "12/11/2026", status: "failed", status_label: "Błąd wysyłki" }));
    mocks.askConfirm.mockResolvedValue(true);
    mocks.del.mockResolvedValue({ data: { result: "cancelled" } });
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Wycofaj" }));
    expect(mocks.askConfirm).toHaveBeenCalledWith(expect.objectContaining({ title: "Wycofać fakturę?", confirmLabel: "Wycofaj fakturę" }));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Wycofano — numer zostaje jako ślad", "success"));
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("odmowa potwierdzenia usunięcia nic nie kasuje; błąd usunięcia idzie komunikatem", async () => {
    route(card());
    mocks.askConfirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    mocks.del.mockRejectedValue(refusal("Szkic jest w wysyłce seryjnej."));
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Usuń szkic" }));
    await waitFor(() => expect(mocks.askConfirm).toHaveBeenCalledTimes(1));
    expect(mocks.del).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Usuń szkic" }));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Szkic jest w wysyłce seryjnej.", "error"));
  });

  it("korekta wymaga przyczyny z co najmniej 3 znaków i przenosi do szkicu korekty", async () => {
    route(card({ invoice_number: "12/11/2026", status: "accepted", status_label: "Przyjęta", editable: false, can_send: false, can_correct: true }));
    mocks.post.mockResolvedValue({ data: card({ id: 9 }) });
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Wystaw korektę" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Korekta faktury 12/11/2026")).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Przyczyna korekty"), " ab ");
    await user.click(within(dialog).getByRole("button", { name: "Utwórz szkic korekty" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Podaj przyczynę korekty (co najmniej 3 znaki).");
    expect(mocks.post).not.toHaveBeenCalled();
    await user.type(within(dialog).getByLabelText("Przyczyna korekty"), "c");
    await user.click(within(dialog).getByRole("button", { name: "Utwórz szkic korekty" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/issued-invoices/5/correction", { reason: "ab c" }),
    );
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/finance/faktury/9"));
    expect(mocks.toast).toHaveBeenCalledWith("Utworzono szkic korekty", "success");
  });

  it("odmowa utworzenia korekty zostaje w oknie", async () => {
    route(card({ invoice_number: "12/11/2026", status: "accepted", editable: false, can_send: false, can_correct: true }));
    mocks.post.mockRejectedValue(refusal("Faktura ma już szkic korekty."));
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Wystaw korektę" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Przyczyna korekty"), "Rabat roczny");
    await user.click(within(dialog).getByRole("button", { name: "Utwórz szkic korekty" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Faktura ma już szkic korekty.");
    expect(mocks.push).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Karta faktury — nabywca", () => {
  it("nabywca z listy klienta zapisuje kod; adres doręczenia jest widoczny", async () => {
    route(
      card({
        buyer: { ...CARD.buyer, code: "A", delivery_l1: "ul. Doręczeń 2", delivery_l2: "00-002 Warszawa", delivery_country: "PL" },
        buyer_options: [
          { code: "A", name: "Klient Testowy S.A.", number: "0000000000" },
          { code: "B", name: "Oddział Testowy", number: null },
        ],
      }),
    );
    mocks.put.mockResolvedValueOnce({ data: card() }).mockRejectedValueOnce(refusal("Nabywca B nie ma NIP."));
    const user = userEvent.setup();
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    expect(await screen.findByText("Adres doręczenia: ul. Doręczeń 2, 00-002 Warszawa, PL")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Nabywca z listy klienta"), "B");
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/api/finance/issued-invoices/5", { buyer_code: "B" }));
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Nabywca zapisany dla kontraktów tej faktury", "success"));
  });

  it("korekta zbiorcza rabatu pokazuje liczbę faktur w nagłówku", async () => {
    route(card({ collective: { invoice_count: 4 } }));
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    expect(await screen.findByText(/korekta zbiorcza rabatu: 4 faktur/)).toBeInTheDocument();
    expect(screen.getByTestId("collective-box")).toBeInTheDocument();
  });
});
