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

import { CLIENT_MONTH } from "@/app/preview/client-invoicing/fixtures";

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientInvoicingTab clientId={7} initialPeriod="2026-10" />
    </QueryClientProvider>,
  );
}

const nbsp = (text: string | null) => (text ?? "").replace(/ /g, " ");

describe("ClientInvoicingTab", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    download.mockReset();
    showToast.mockReset();
  });

  it("shows what to invoice next to the KSeF invoice and payment", async () => {
    get.mockResolvedValue({ data: CLIENT_MONTH });
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
    get.mockResolvedValue({ data: CLIENT_MONTH });
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
  });
});
