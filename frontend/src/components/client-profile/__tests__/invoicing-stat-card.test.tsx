/**
 * Karta „Rozliczenie” w Przeglądzie klienta (wariant A, decyzja Artura
 * z 20.11.2026): poprzedni miesiąc jako cztery kroki RCP → do faktury → KSeF →
 * zapłata. Krok mówi tylko to, co potwierdzają dane NEXUSA.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a) },
}));

import { InvoicingStatCard } from "@/components/client-profile/ClientOverviewCards";
import type { ClientInvoicing } from "@/lib/api/client-invoicing";

import { CLIENT_MONTH, DELIVERY_MONTH } from "@/app/preview/client-invoicing/fixtures";

const nbsp = (text: string | null) => (text ?? "").replace(/[  ]/g, " ");

function answer(month: ClientInvoicing | Error, rcp: unknown = DELIVERY_MONTH) {
  get.mockImplementation((url: string) => {
    if (url === "/api/my-clients/7/settlements") {
      return rcp instanceof Error ? Promise.reject(rcp) : Promise.resolve({ data: rcp });
    }
    if (url === "/api/clients/7/invoicing") {
      return month instanceof Error ? Promise.reject(month) : Promise.resolve({ data: month });
    }
    return Promise.reject(new Error(`nieoczekiwane zapytanie ${url}`));
  });
}

function failure(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail: "Błąd" } } });
}

function renderCard() {
  const onOpen = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InvoicingStatCard clientId={7} onOpen={onOpen} />
    </QueryClientProvider>,
  );
  return onOpen;
}

function stepItems() {
  return screen.findByRole("list", { name: "Kroki rozliczenia miesiąca" }).then((list) => within(list).getAllByRole("listitem"));
}

describe("InvoicingStatCard — rozliczenie miesiąca krokami", () => {
  beforeEach(() => {
    get.mockReset();
    // „Dziś” to 20.11.2026 w Warszawie, więc karta pokazuje październik.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-20T10:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("pokazuje cztery kroki poprzedniego miesiąca z tych samych zapytań co zakładka", async () => {
    answer(CLIENT_MONTH);
    const onOpen = renderCard();

    const items = await stepItems();
    await waitFor(() => expect(items[0]).toHaveTextContent("2 z 4 przyjętych"));
    expect(screen.getByText("Październik 2026")).toBeInTheDocument();
    expect(items.map((item) => item.firstChild?.textContent)).toEqual(["RCP", "Do faktury", "W KSeF", "Zapłata"]);
    expect(nbsp(items[1].textContent)).toContain("79 545,00 zł");
    expect(items[2]).toHaveTextContent("4 z 5");
    // Szczegół kroku w dymku — w karcie zostaje jedna linia na krok.
    expect(items[2]).toHaveAttribute("title", expect.stringContaining("1 różnica do sprawdzenia"));
    expect(items[3]).toHaveTextContent("1 z 5 zapłacone");

    expect(get).toHaveBeenCalledWith("/api/clients/7/invoicing", { params: { year: 2026, month: 10 } });
    expect(get).toHaveBeenCalledWith("/api/my-clients/7/settlements", { params: { month: "2026-10" } });
    expect(document.querySelector('[data-tour="client.overview.settlement"]')).not.toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Rozliczenie: otwórz „Faktury”" }));
    expect(onOpen).toHaveBeenCalledWith("faktury");
  });

  it("bez RCP i bez faktur mówi „brak w NEXUSIE” i „nie ma faktur”, bez zgadywania", async () => {
    answer(
      {
        ...CLIENT_MONTH,
        rows: CLIENT_MONTH.rows.map((row) => ({ ...row, status: "not_invoiced", invoice_ids: [] })),
        invoices: [],
        summary: { ...CLIENT_MONTH.summary, invoiced: 0, not_invoiced: 5, differences: 0, unmatched_invoices: 0 },
      },
      { ...DELIVERY_MONTH, rows: DELIVERY_MONTH.rows.map((row) => ({ ...row, kind: null, state: "waiting" })) },
    );
    renderCard();

    const items = await stepItems();
    await waitFor(() => expect(items[0]).toHaveTextContent("brak w NEXUSIE"));
    expect(items[2]).toHaveTextContent("0 z 5");
    expect(items[3]).toHaveTextContent("nie ma faktur");
    const card = items[0].closest("section");
    expect(card).not.toHaveTextContent(/niezapłac|czeka na RCP|po terminie/);
  });

  it("miesiąc bez zamówień i faktur mówi to wprost, bez kroków", async () => {
    answer({ ...CLIENT_MONTH, rows: [], invoices: [], summary: { ...CLIENT_MONTH.summary, rows: 0, invoiced: 0 } });
    renderCard();
    expect(await screen.findByText("październik 2026: nie ma zamówień do zafakturowania.")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Kroki rozliczenia miesiąca" })).toBeNull();
  });

  it("awaria rozliczenia nie udaje pustego miesiąca", async () => {
    answer(failure(500));
    renderCard();
    expect(await screen.findByText("Nie udało się wczytać rozliczenia.")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma zamówień do zafakturowania/)).toBeNull();
  });

  it("awaria rozliczeń RCP widać w karcie i zostawia pozostałe kroki", async () => {
    answer(CLIENT_MONTH, failure(500));
    renderCard();
    // Widoczny tekst, nie tylko dymek: na dotyk i w czytniku dymku nie ma.
    expect(await screen.findByText("nie udało się wczytać")).toBeVisible();
    const items = await stepItems();
    expect(items[2]).toHaveTextContent("4 z 5");
  });

  it("brak dostępu do rozliczeń RCP wygląda inaczej niż awaria", async () => {
    answer(CLIENT_MONTH, failure(403));
    renderCard();
    expect(await screen.findByText("bez dostępu")).toBeVisible();
    expect(screen.queryByText("nie udało się wczytać")).toBeNull();
  });

  it("drobny druk kroku dociera do czytnika ekranu, nie tylko do dymku", async () => {
    answer(CLIENT_MONTH);
    renderCard();
    const items = await stepItems();
    await waitFor(() => expect(items[0]).toHaveTextContent("2 z 4 przyjętych"));
    expect(items[2]).toHaveTextContent("1 różnica do sprawdzenia · 1 faktura do przypisania");
  });
});
