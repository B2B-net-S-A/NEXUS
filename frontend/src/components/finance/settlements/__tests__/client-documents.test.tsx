import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientDocumentsMonth } from "@/lib/api/client-settlements";

import { ClientDocumentsPanel } from "../ClientDocumentsPanel";
import { money } from "../format";

const mocks = vi.hoisted(() => ({ get: vi.fn(), download: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn(), put: vi.fn() } }));
vi.mock("@/lib/authenticated-files", () => ({ downloadBlob: mocks.download }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));

const base: ClientDocumentsMonth = {
  client_id: 7,
  month: "2026-11",
  enabled: true,
  kind: "Service Delivery Confirmation",
  stage: "ACTUAL",
  projects: [
    {
      project: "ALFA",
      people: 2,
      accepted: 1,
      hours: "136.00",
      md: "17.000",
      order_numbers: ["ZAM-TEST"],
      tasks: 4,
      net: [{ currency: "EUR", amount: "4250.00" }],
    },
  ],
  skipped: [{ person: "Jan Testowy", reason: "Brak Time Sheet w Excelu z godzinami" }],
  can_see_amounts: true,
};

function renderPanel(data: ClientDocumentsMonth) {
  mocks.get.mockResolvedValue({ data });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientDocumentsPanel clientId={7} month="2026-11" />
    </QueryClientProvider>,
  );
}

describe("Potwierdzenie usług per projekt (E6.2)", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.download.mockReset();
  });

  it("kwota w walucie klienta, zł bez zmian", () => {
    expect(money("1234.50", "EUR")).toMatch(/^1\s234,50 EUR$/);
    expect(money("1100", "PLN")).toMatch(/^1\s100,00\szł$/);
    expect(money(null, "EUR")).toBe("–");
  });

  it("pokazuje projekt z godzinami, MD i kwotą w euro, osoby poza dokumentem i pobiera PDF", async () => {
    renderPanel(base);
    expect(await screen.findByText("ALFA")).toBeInTheDocument();
    expect(screen.getByText("136 h · 17 MD")).toBeInTheDocument();
    expect(screen.getByText(/^4\s250,00 EUR$/)).toBeInTheDocument();
    expect(screen.getByText("2 osoby, przyjęte 1 z 2")).toBeInTheDocument();
    expect(screen.getByText(/Poza dokumentem: Jan Testowy \(brak time sheet/)).toBeInTheDocument();

    mocks.get.mockResolvedValueOnce({ data: new Blob(["%PDF"]) });
    fireEvent.click(screen.getByRole("button", { name: /Pobierz PDF/ }));
    await waitFor(() => expect(mocks.download).toHaveBeenCalledWith(expect.any(Blob), "SDC_ALFA_2026-11.pdf"));
    expect(mocks.get).toHaveBeenLastCalledWith("/api/finance/settlements/client-documents/file", {
      params: { client_id: 7, month: "2026-11", project: "ALFA" },
      responseType: "blob",
    });
  });

  it("plan miesiąca oznacza dokument jako estymację", async () => {
    renderPanel({ ...base, stage: "FORECAST", skipped: [] });
    expect(await screen.findByText("z planu (estymacja)")).toBeInTheDocument();
  });

  it("klient bez reguły dokumentu nie widzi sekcji", async () => {
    const { container } = renderPanel({ ...base, enabled: false, projects: [] });
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
