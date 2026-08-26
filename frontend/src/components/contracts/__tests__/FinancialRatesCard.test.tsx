import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  FinancialRatesCard,
  type FinancialRatesContract,
} from "@/components/contracts/FinancialRatesCard";

const BASE_CONTRACT: FinancialRatesContract = {
  rate_candidate: 28,
  rate_client: 38.75,
  candidate_rate_schedule: [],
  client_rate_schedule: [],
  framework_rate: null,
  currency: "EUR",
  rate_unit: "hourly",
  billing_hours_per_month: 160,
  margin: 10.75,
  client_name: "Acme",
  eur_pln_rate: {
    rate: 4.3014,
    effective_date: "2026-08-25",
    source: "NBP",
    table: "A",
    table_no: "163/A/NBP/2026",
  },
};

describe("FinancialRatesCard", () => {
  it("pokazuje przeliczenia stawek EUR na PLN i rzeczywistą datę kursu NBP", () => {
    render(<FinancialRatesCard contract={BASE_CONTRACT} />);

    expect(screen.getByTestId("rate-client-pln")).toHaveTextContent("≈ 166,68 zł/h");
    expect(screen.getByTestId("rate-candidate-pln")).toHaveTextContent(
      "≈ 120,44 zł/h",
    );
    expect(screen.getByTestId("margin-pln")).toHaveTextContent("≈ 46,24 zł/h");
    expect(screen.getByTestId("monthly-margin-pln")).toHaveTextContent(
      "≈ 7398,41 zł",
    );
    expect(screen.getByTestId("eur-pln-rate-note")).toHaveTextContent(
      "Kurs EUR/PLN z tabeli A NBP na dzień 25.08.2026: 1 € = 4,3014 zł",
    );
  });

  it("pozostawia kontrakt PLN bez dodatkowych przeliczeń i informacji o kursie", () => {
    render(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          currency: "PLN",
          rate_candidate: 200,
          rate_client: 250,
          margin: 50,
        }}
      />,
    );

    expect(screen.getByText("Klient").parentElement).toHaveTextContent("250,00 zł/h");
    expect(screen.getByText("Kandydat").parentElement).toHaveTextContent("200,00 zł/h");
    expect(screen.queryByTestId("rate-client-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("rate-candidate-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("margin-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("monthly-margin-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("eur-pln-rate-note")).not.toBeInTheDocument();
  });

  it("nie pokazuje przeliczenia EUR bez kursu ani dla kursu niepoprawnego", () => {
    const { rerender } = render(
      <FinancialRatesCard contract={{ ...BASE_CONTRACT, eur_pln_rate: null }} />,
    );

    expect(screen.queryByTestId("rate-client-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("eur-pln-rate-note")).not.toBeInTheDocument();

    rerender(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          eur_pln_rate: { ...BASE_CONTRACT.eur_pln_rate!, rate: 0 },
        }}
      />,
    );

    expect(screen.queryByTestId("rate-client-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("eur-pln-rate-note")).not.toBeInTheDocument();
  });
});
