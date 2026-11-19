import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));

import { OrderCostCorrections, partsText } from "@/components/finance/OrderCostCorrections";
import type { OrderCostCorrection } from "@/lib/api/order-cost-corrections";

// Dane fikcyjne.
const ROW: OrderCostCorrection = {
  order_id: 77,
  client_id: 5,
  client_name: "Fundusz Testowy",
  contract_id: 9,
  person: "Ola Kosztowa",
  order_number: "Zlecenie nr 3",
  start_date: "2026-10-01",
  end_date: "2026-10-31",
  unit: "hourly",
  currency: "PLN",
  in_order: [{ from: "2026-10-01", to: "2026-10-31", rate: "150.000" }],
  in_contract: [{ from: "2026-10-01", to: "2026-10-31", rate: "120.000" }],
  months: [{ month: "2026-10", in_order: "150.000", in_contract: "120.000", diff: "-30.000" }],
  estimate: "-5040.000",
};

function renderList(canWrite = true) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queries}>
      <OrderCostCorrections canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("partsText", () => {
  it("closes each part the day before the next one", () => {
    expect(
      partsText(
        [
          { from: "2026-07-01", to: "2026-08-31", rate: "120" },
          { from: "2026-09-01", to: "2026-12-15", rate: "130" },
        ],
        "hourly",
        "PLN",
      ),
    ).toMatch(/^120,00\s?zł\/h do 31\.08\.2026 · 130,00\s?zł\/h od 01\.09\.2026$/);
  });
});

describe("OrderCostCorrections", () => {
  it("shows the order, both costs and the monthly difference", async () => {
    get.mockResolvedValue({ data: { rows: [ROW] } });
    renderList();
    expect(await screen.findByText("Ola Kosztowa")).toBeInTheDocument();
    expect(screen.getByText(/W zamówieniu: 150,00 zł\/h/)).toBeInTheDocument();
    expect(screen.getByText(/Z kontraktu: 120,00 zł\/h/)).toBeInTheDocument();
    expect(screen.getByText(/-30,00 zł\/h/)).toBeInTheDocument();
  });

  it("dismiss posts the decision without a dialog", async () => {
    get.mockResolvedValue({ data: { rows: [ROW] } });
    post.mockResolvedValue({ data: {} });
    renderList();
    fireEvent.click(await screen.findByRole("button", { name: "Zostaw" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/order-cost-corrections/77/dismiss"),
    );
  });

  it("apply asks first and then posts", async () => {
    get.mockResolvedValue({ data: { rows: [ROW] } });
    post.mockResolvedValue({ data: {} });
    renderList();
    fireEvent.click(await screen.findByRole("button", { name: "Ustaw koszt z kontraktu" }));
    expect(post).not.toHaveBeenCalled();
    const buttons = await screen.findAllByRole("button", { name: "Ustaw koszt z kontraktu" });
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/order-cost-corrections/77/apply"),
    );
  });

  it("without amounts edit there are no buttons", async () => {
    get.mockResolvedValue({ data: { rows: [ROW] } });
    renderList(false);
    expect(await screen.findByText("Ola Kosztowa")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zostaw" })).not.toBeInTheDocument();
  });

  it("failure is not an empty list", async () => {
    get.mockImplementation(() => Promise.reject({ response: { status: 500 } }));
    renderList();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/i })).toBeInTheDocument();
    expect(screen.queryByText(/zgadza się ze stawkami/)).not.toBeInTheDocument();
  });

  it("empty list says the costs match", async () => {
    get.mockResolvedValue({ data: { rows: [] } });
    renderList();
    expect(await screen.findByText(/zgadza się ze stawkami w kontraktach/)).toBeInTheDocument();
  });
});
