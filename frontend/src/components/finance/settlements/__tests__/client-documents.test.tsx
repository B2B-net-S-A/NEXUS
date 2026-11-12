import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientDocumentsMonth } from "@/lib/api/client-settlements";

import { ClientDocumentsPanel } from "../ClientDocumentsPanel";
import { money } from "../format";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  download: vi.fn(),
  copy: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn(), put: vi.fn() } }));
vi.mock("@/lib/authenticated-files", () => ({ downloadBlob: mocks.download }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copy }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }) }));

const BLOCK = [
  "[ESP-MANAGER-START]",
  "Stage: ACTUAL",
  "Project: ALFA",
  "PO: ZAM-TEST",
  "Month: 2026-11",
  "Vendor: Dostawca",
  "MD: 17",
  "Cost net EUR: 4250",
  "Comment:",
  "[ESP-MANAGER-END]",
].join("\n");

const base: ClientDocumentsMonth = {
  client_id: 7,
  month: "2026-11",
  enabled: true,
  kind: "Service Delivery Confirmation",
  stage: "ACTUAL",
  can_see_amounts: true,
  projects: [
    {
      project: "ALFA",
      people: 2,
      accepted: 1,
      hours: "136.00",
      md: "17.000",
      order_numbers: ["ZAM-TEST"],
      tasks: 4,
      esp: null,
    },
  ],
  skipped: [{ person: "Jan Testowy", reason: "Brak Time Sheet w Excelu z godzinami" }],
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
    mocks.copy.mockReset();
    mocks.success.mockReset();
    mocks.error.mockReset();
  });

  function withBlock(esp: ClientDocumentsMonth["projects"][number]["esp"], canSee = true): ClientDocumentsMonth {
    return { ...base, can_see_amounts: canSee, projects: [{ ...base.projects[0], esp }] };
  }

  it("kwota w walucie klienta, zł bez zmian", () => {
    expect(money("1234.50", "EUR")).toMatch(/^1\s234,50 EUR$/);
    expect(money("1100", "PLN")).toMatch(/^1\s100,00\szł$/);
    expect(money(null, "EUR")).toBe("–");
  });

  it("pokazuje projekt z godzinami i MD bez kwot, osoby poza dokumentem i pobiera PDF", async () => {
    renderPanel(base);
    expect(await screen.findByText("ALFA")).toBeInTheDocument();
    expect(screen.getByText("136 h · 17 MD")).toBeInTheDocument();
    expect(screen.getByText("2 osoby, przyjęte 1 z 2")).toBeInTheDocument();
    expect(screen.getByText(/Poza dokumentem: Jan Testowy \(brak time sheet/)).toBeInTheDocument();

    mocks.get.mockResolvedValueOnce({ data: new Blob(["%PDF"]) });
    fireEvent.click(screen.getByRole("button", { name: "Pobierz PDF: ALFA" }));
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

  it("„Kopiuj blok ESP” kopiuje tekst bloku i pokazuje kwotę do faktury", async () => {
    mocks.copy.mockResolvedValue(true);
    renderPanel(withBlock({ ready: true, md: "17.000", currency: "EUR", cost: "4250.00", text: BLOCK }));
    const button = await screen.findByRole("button", { name: "Kopiuj blok ESP: ALFA" });
    expect(screen.getByText(/17 MD · 4\s250,00 EUR/)).toBeInTheDocument();
    fireEvent.click(button);
    await waitFor(() => expect(mocks.copy).toHaveBeenCalledWith(BLOCK));
    expect(mocks.success).toHaveBeenCalledWith("Skopiowano blok ESP: ALFA.");
  });

  it("nieudane kopiowanie mówi o tym, zamiast udawać sukces", async () => {
    mocks.copy.mockResolvedValue(false);
    renderPanel(withBlock({ ready: true, md: "17.000", currency: "EUR", cost: "4250.00", text: BLOCK }));
    fireEvent.click(await screen.findByRole("button", { name: "Kopiuj blok ESP: ALFA" }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalled());
    expect(mocks.success).not.toHaveBeenCalled();
  });

  it("blok przed przyjęciem wszystkich osób jest nieaktywny", async () => {
    renderPanel(withBlock({ ready: false, md: "8.000", currency: "EUR", cost: null, text: null }));
    expect(await screen.findByRole("button", { name: "Kopiuj blok ESP: ALFA" })).toBeDisabled();
  });

  it("bez dostępu do kwot albo bez reguły nie ma przycisku bloku", async () => {
    const { unmount } = renderPanel(
      withBlock({ ready: true, md: "17.000", currency: "EUR", cost: null, text: null }, false),
    );
    expect(await screen.findByText("ALFA")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Kopiuj blok ESP/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/EUR/)).not.toBeInTheDocument();
    unmount();

    renderPanel(base);
    expect(await screen.findByText("ALFA")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Kopiuj blok ESP/ })).not.toBeInTheDocument();
  });

  it("klient bez reguły dokumentu nie widzi sekcji", async () => {
    const { container } = renderPanel({ ...base, enabled: false, projects: [] });
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
