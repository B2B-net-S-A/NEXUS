import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a) },
}));

import { RateDivergencesTab } from "@/components/finance/RateDivergencesTab";
import type { RateDivergence, RateDivergenceReport } from "@/lib/api/rate-divergences";

const ROW: RateDivergence = {
  person: "Maria Rozjazdowa",
  client_name: "Bank Testowy",
  order_number: "ZAM/445",
  leg: "revenue",
  leg_label: "przychód",
  month: "2026-10",
  currency: "PLN",
  contract_rate: "800.00",
  order_rate: "750.00",
  difference: "-50.00",
  md: "20.00",
  effect: "-1000.00",
  rounding: false,
  link: "/clients/12?tab=zamowienia",
};

const REPORT: RateDivergenceReport = {
  generated_at: "2026-11-08T00:30:00+00:00",
  month: "2026-10",
  checked_lines: 40,
  skipped: { no_contract_rate: 2, other_currency: 0 },
  rows: [ROW, { ...ROW, person: "Ela Zaokrąglona", rounding: true }],
};

function renderTab() {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queries}>
      <RateDivergencesTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
});

describe("RateDivergencesTab", () => {
  it("lists person, client, amounts and marks rounding", async () => {
    get.mockResolvedValue({ data: REPORT });
    renderTab();
    expect(await screen.findByText("Maria Rozjazdowa")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Bank Testowy" })[0]).toHaveAttribute(
      "href",
      "/clients/12?tab=zamowienia",
    );
    expect(screen.getByText(/1 rozjazd/)).toHaveTextContent("1 zaokrąglenie");
    expect(screen.getByText(/bez stawki w kontrakcie: 2/)).toBeInTheDocument();
    expect(screen.getByText("zaokrąglenie stawki godzinowej")).toBeInTheDocument();
  });

  it("says when the report has not run yet", async () => {
    get.mockResolvedValue({
      data: { generated_at: null, month: null, checked_lines: 0, skipped: { no_contract_rate: 0, other_currency: 0 }, rows: [] },
    });
    renderTab();
    expect(await screen.findByText(/Raport jeszcze nie powstał/)).toBeInTheDocument();
  });

  it("failure is not an empty list", async () => {
    get.mockImplementation(() => Promise.reject({ response: { status: 500 } }));
    renderTab();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/i })).toBeInTheDocument();
    expect(screen.queryByText(/stawki kontraktów i zamówień są zgodne/)).not.toBeInTheDocument();
  });
});
