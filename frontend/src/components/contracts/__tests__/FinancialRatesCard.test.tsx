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

  it("używa osobnych walut i oblicza mieszaną marżę EUR/PLN w PLN", () => {
    render(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          rate_client_currency: "EUR",
          rate_candidate_currency: "PLN",
          rate_candidate: 120,
          margin: null,
          framework_rate: 130,
        }}
      />,
    );

    expect(screen.getByText("Klient").parentElement).toHaveTextContent("38,75 €/h");
    expect(screen.getByText("Kandydat").parentElement).toHaveTextContent("120,00 zł/h");
    expect(screen.getByTestId("rate-client-pln")).toHaveTextContent("≈ 166,68 zł/h");
    expect(screen.queryByTestId("rate-candidate-pln")).not.toBeInTheDocument();
    expect(screen.getByText("Marża").parentElement).toHaveTextContent(
      "46,679 zł/h(28.0%)",
    );
    expect(screen.queryByTestId("margin-pln")).not.toBeInTheDocument();
    expect(screen.getByText("Z umowy ramowej").parentElement).toHaveTextContent(
      "130,00 zł/h",
    );
    expect(screen.queryByTestId("framework-rate-pln")).not.toBeInTheDocument();
  });

  it("przelicza koszt i stawkę ramową, gdy tylko ich walutą jest EUR", () => {
    render(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          rate_client_currency: "PLN",
          rate_candidate_currency: "EUR",
          rate_client: 200,
          rate_candidate: 28,
          framework_rate: 30,
          margin: null,
        }}
      />,
    );

    expect(screen.queryByTestId("rate-client-pln")).not.toBeInTheDocument();
    expect(screen.getByTestId("rate-candidate-pln")).toHaveTextContent(
      "≈ 120,44 zł/h",
    );
    expect(screen.getByTestId("framework-rate-pln")).toHaveTextContent(
      "≈ 129,04 zł/h",
    );
    expect(screen.getByText("Marża").parentElement).toHaveTextContent(
      "79,561 zł/h(39.8%)",
    );
  });

  it("nie pokazuje fałszywej marży dla walut bez dostępnej konwersji", () => {
    render(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          rate_client_currency: "USD",
          rate_candidate_currency: "PLN",
          rate_client: 100,
          rate_candidate: 80,
          margin: null,
        }}
      />,
    );

    expect(screen.getByText("Marża").parentElement).toHaveTextContent("—");
    expect(screen.queryByText(/20[,.]00/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("eur-pln-rate-note")).not.toBeInTheDocument();
  });
});
