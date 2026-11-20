import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

const download = vi.fn();
vi.mock("@/lib/authenticated-files", () => ({
  fetchAuthenticatedDownload: (...a: unknown[]) => download(...a),
  downloadBlob: vi.fn(),
}));

import { ClientInvoicingTab } from "@/components/clients/invoicing/ClientInvoicingTab";

import { CLIENT_MONTH, DELIVERY_MONTH } from "@/app/preview/client-invoicing/fixtures";
import type { ClientInvoicing } from "@/lib/api/client-invoicing";

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientInvoicingTab clientId={7} initialPeriod="2026-10" />
    </QueryClientProvider>,
  );
}

const nbsp = (text: string | null) => (text ?? "").replace(/[\u00a0\u202f]/g, " ");

/** Faktury miesiąca pod `/invoicing`, RCP z rozliczeń pod `/my-clients/7/settlements`. */
function answer(month: ClientInvoicing, rcp: unknown = { data: DELIVERY_MONTH }) {
  get.mockImplementation((url: string) => {
    if (url === "/api/my-clients/7/settlements") {
      return (rcp as { response?: unknown }).response ? Promise.reject(rcp) : Promise.resolve(rcp);
    }
    return Promise.resolve({ data: month });
  });
}

function stepsList() {
  return screen.findByRole("list", { name: "Kroki rozliczenia miesiąca" });
}

describe("ClientInvoicingTab", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    download.mockReset();
    showToast.mockReset();
  });

  it("shows what to invoice next to the KSeF invoice and payment", async () => {
    answer(CLIENT_MONTH);
    renderTab();
    const first = await screen.findByTestId("billing-row-g11");
    expect(get).toHaveBeenCalledWith("/api/clients/7/invoicing", { params: { year: 2026, month: 10 } });
    expect(nbsp(first.textContent)).toContain("21 MD × 1200,00 zł");
    expect(within(first).getByText("FS 10/118/2026")).toBeInTheDocument();
    expect(within(first).getByText("zgodna")).toBeInTheDocument();

    const hourly = screen.getByTestId("billing-row-o21");
    expect(nbsp(hourly.textContent)).toContain("po terminie 10 dni");

    const difference = screen.getByTestId("billing-row-g13");
    expect(nbsp(difference.textContent)).toContain("różnica do sprawdzenia · +75,00 zł");

    // Kosztowe: bez kwoty „do faktury”, z budżetem i porównaniem faktury z resztą.
    const cost = screen.getByTestId("billing-row-g15");
    expect(within(cost).getByText("zamówienie kosztowe — kwotę faktury ustalają Finanse")).toBeInTheDocument();
    expect(nbsp(cost.textContent)).toContain("budżet 500 000,00 zł · zostało 380 000,00 zł");
    expect(within(cost).getByText("mieści się w budżecie")).toBeInTheDocument();
    expect(within(cost).getByTitle("Kwotę faktury ustalają Finanse")).toHaveTextContent("—");

    const waiting = screen.getByTestId("billing-row-g14");
    expect(within(waiting).getByText("jeszcze nie wystawiona")).toBeInTheDocument();
    expect(within(waiting).getByText("czeka na zużycie MD za miesiąc")).toBeInTheDocument();

    // Faktura bez zamówienia czeka na Finanse; DL nie ma tu decyzji.
    const loose = screen.getByRole("region", { name: "Faktury z KSeF do sprawdzenia przez Finanse" });
    expect(within(loose).getByText("FS 10/9/2026")).toBeInTheDocument();
    expect(screen.queryByText("Rozstrzygnij w Finansach")).not.toBeInTheDocument();
  });

  it("shows the month as four steps: RCP → do faktury → KSeF → zapłata", async () => {
    answer(CLIENT_MONTH);
    renderTab();
    const steps = await stepsList();
    await waitFor(() => expect(within(steps).getByText("2 z 4 przyjętych")).toBeInTheDocument());
    expect(get).toHaveBeenCalledWith("/api/my-clients/7/settlements", { params: { month: "2026-10" } });
    const items = within(steps).getAllByRole("listitem");
    expect(items.map((item) => item.firstChild?.textContent)).toEqual([
      "1 · RCP",
      "2 · Do faktury",
      "3 · W KSeF",
      "4 · Zapłata",
    ]);
    expect(nbsp(items[1].textContent)).toContain("79 545,00 zł");
    expect(nbsp(items[1].textContent)).toContain("5 zamówień · 1 kosztowe bez kwoty");
    expect(items[2]).toHaveTextContent("4 z 5 zamówień");
    expect(items[2]).toHaveTextContent("1 różnica do sprawdzenia · 1 faktura do przypisania");
    // Dwie zaległości z dowodem z wyciągów (fikcja harnessu) — „po terminie” tylko z dowodem.
    expect(items[3]).toHaveTextContent("1 z 5 zapłacone");
    expect(items[3]).toHaveTextContent("2 po terminie · 2 przed terminem");
    // Pięć liczb nad tabelą zastąpił pasek kroków.
    expect(document.querySelector("#client-invoicing-stats")).toBeNull();
  });

  it("shows no data about payments instead of an overdue count without statements", async () => {
    // 19.11.2026: „62 po terminie” u jednego klienta to faktury bez wyciągów, nie zaległości.
    const invoices = CLIENT_MONTH.invoices.map((item) =>
      item.overdue_days > 0 ? { ...item, overdue_days: 0, payment_unknown: true } : item,
    );
    answer({
      ...CLIENT_MONTH,
      invoices,
      overdue: [],
      summary: {
        ...CLIENT_MONTH.summary,
        overdue: 0,
        payment_unknown: 2,
      },
    });
    renderTab();
    const unpaid = await screen.findByTestId("billing-row-g13");
    expect(nbsp(unpaid.textContent)).toContain("brak danych o zapłacie");
    expect(nbsp(unpaid.textContent)).not.toContain("po terminie");
    // Część wpłaty jest z wyciągu (fakt), o reszcie NEXUS nie wie.
    const hourly = screen.getByTestId("billing-row-o21");
    expect(nbsp(hourly.textContent)).toContain("zapłacono część");
    expect(nbsp(hourly.textContent)).not.toContain("po terminie");

    const payment = within(await stepsList()).getAllByRole("listitem")[3];
    expect(payment).toHaveTextContent("1 z 5 zapłacone");
    expect(payment).toHaveTextContent("1 zapłacone w części · 1 bez danych o zapłacie · 2 przed terminem");
    expect(payment).not.toHaveTextContent(/po terminie|niezapłac/);
    expect(screen.queryByText("Po terminie z wcześniejszych miesięcy")).not.toBeInTheDocument();
  });

  it("keeps the steps when the settlements module is closed for the account", async () => {
    answer(CLIENT_MONTH, { response: { status: 404, data: { detail: "Moduł wyłączony" } } });
    renderTab();
    const steps = await stepsList();
    await waitFor(() => expect(within(steps).getByText("bez dostępu")).toBeInTheDocument());
    expect(within(steps).getByText("rozliczenia RCP są poza Twoim dostępem")).toBeInTheDocument();
    expect(within(steps).getByText("4 z 5 zamówień")).toBeInTheDocument();
  });

  it("does not render an empty month when the request fails", async () => {
    get.mockRejectedValue({ response: { status: 500, data: { detail: "Błąd" } } });
    renderTab();
    await waitFor(() => expect(screen.queryByText(/Wczytywanie/)).not.toBeInTheDocument());
    expect(screen.queryByText(/nie ma zamówień do zafakturowania/)).not.toBeInTheDocument();
  });

  it("names the portfolio boundary on 403", async () => {
    get.mockRejectedValue({
      response: { status: 403, data: { detail: "Ten klient jest poza Twoim portfelem." } },
    });
    renderTab();
    await waitFor(() => expect(screen.queryByText(/Wczytywanie/)).not.toBeInTheDocument());
    expect(screen.queryByTestId("billing-row-g11")).not.toBeInTheDocument();
  });

  it("switches month and downloads the export for issuing", async () => {
    answer(CLIENT_MONTH);
    download.mockResolvedValue({ blob: new Blob(["x"]), filename: "do-faktury.xlsx" });
    renderTab();
    await screen.findByTestId("billing-row-g11");
    await userEvent.click(screen.getByRole("button", { name: "Eksport do wystawienia" }));
    expect(download).toHaveBeenCalledWith(
      "/api/clients/7/invoicing/export?year=2026&month=10&format=xlsx",
    );
    await userEvent.click(screen.getByRole("button", { name: "Poprzedni miesiąc" }));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/clients/7/invoicing", {
        params: { year: 2026, month: 9 },
      }),
    );
    // Krok RCP idzie za miesiącem wybranym strzałką.
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/my-clients/7/settlements", { params: { month: "2026-09" } }),
    );
  });
});
