/**
 * Karta „Pieniądze” w Przeglądzie kontraktu: marża stoi w walucie kontraktu
 * (zgłoszenie z 22.11.2026 — kontrakt w EUR pokazywał „10,75 zł/h” i „1 806 zł”),
 * a przy EUR obok jest równowartość w złotych po kursie NBP z tabeli A.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ contractsApi: { benchmark: vi.fn() } }));

import { ContractOverviewMoney, type ContractOverviewMoneyProps } from "../ContractOverviewMoney";

function renderCard(overrides: Partial<ContractOverviewMoneyProps> = {}) {
  const props: ContractOverviewMoneyProps = {
    contractId: 1,
    rateClient: 38.75,
    rateCandidate: 28,
    margin: 10.75,
    monthlyMargin: 1806,
    hoursPerMonth: 168,
    clientCurrency: "EUR",
    candidateCurrency: "EUR",
    frameworkRate: null,
    clientSchedule: [],
    candidateSchedule: [],
    showBenchmark: false,
    eurPlnRate: { rate: 4.25, effective_date: "2026-11-20", source: "NBP", table: "A" },
    onOpenMoney: () => {},
    ...overrides,
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ContractOverviewMoney {...props} />
    </QueryClientProvider>,
  );
}

describe("ContractOverviewMoney", () => {
  it("marża kontraktu w EUR stoi w EUR, nie w złotych", () => {
    renderCard();
    expect(screen.getByText(/^EUR\/h · /)).toBeInTheDocument();
    expect(screen.queryByText(/zł\/h/)).not.toBeInTheDocument();
    expect(screen.getByText("≈ 1 806 EUR")).toBeInTheDocument();
  });

  it("przy EUR pokazuje równowartość w złotych po kursie NBP z datą tabeli", () => {
    renderCard();
    // 1 806 × 4,25 = 7 675,50 → pełne złote
    expect(screen.getByText(/≈ 7 676 zł po kursie NBP 4,2500 zł z 20\.11\.2026/)).toBeInTheDocument();
  });

  it("bez kursu NBP nie zgaduje złotych", () => {
    renderCard({ eurPlnRate: null });
    expect(screen.getByText("≈ 1 806 EUR")).toBeInTheDocument();
    expect(screen.queryByText(/po kursie NBP/)).not.toBeInTheDocument();
  });

  it("kontrakt w złotych bez zmian: zł/h i kwota w zł, bez przeliczenia", () => {
    renderCard({
      clientCurrency: "PLN",
      candidateCurrency: "PLN",
      rateClient: 160,
      rateCandidate: 130,
      margin: 30,
      monthlyMargin: 5040,
      eurPlnRate: null,
    });
    expect(screen.getByText(/^zł\/h · /)).toBeInTheDocument();
    expect(screen.getByText("≈ 5 040 zł")).toBeInTheDocument();
    expect(screen.queryByText(/po kursie NBP/)).not.toBeInTheDocument();
  });

  it("różne waluty: marży nie liczy", () => {
    renderCard({ clientCurrency: "EUR", candidateCurrency: "PLN" });
    expect(screen.getByText(/Marży nie liczymy/)).toBeInTheDocument();
  });
});
