import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  FinancialRatesCard,
  type FinancialRatesContract,
} from "@/components/contracts/FinancialRatesCard";
import type { RecruitmentRate } from "@/lib/api/recruitmentRates";

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

/**
 * Karta czyta aneksy kontraktu (źródło kroku „aneks”) przez React Query —
 * `seed` wkłada odpowiedź do pamięci, więc testy nie wysyłają zapytań.
 */
function renderCard(ui: ReactElement, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  seed?.(client);
  const wrap = (node: ReactElement) => <QueryClientProvider client={client}>{node}</QueryClientProvider>;
  const utils = render(wrap(ui));
  return { ...utils, rerender: (next: ReactElement) => utils.rerender(wrap(next)) };
}

describe("FinancialRatesCard", () => {
  it("pokazuje przeliczenia stawek EUR na PLN i rzeczywistą datę kursu NBP", () => {
    renderCard(<FinancialRatesCard contract={BASE_CONTRACT} />);

    expect(screen.getByTestId("rate-client-pln")).toHaveTextContent("≈ 166,68 zł/h");
    expect(screen.getByTestId("rate-candidate-pln")).toHaveTextContent("≈ 120,44 zł/h");
    expect(screen.getByTestId("margin-pln")).toHaveTextContent("≈ 46,24 zł/h");
    // Marża miesięczna (10,75 € × 160 h) i jej przeliczenie — w pełnych kwotach.
    expect(screen.getByTestId("figure-margin")).toHaveTextContent("1 720 EUR / mies.");
    expect(screen.getByTestId("monthly-margin-pln")).toHaveTextContent("≈ 7 398 zł");
    const note = screen.getByTestId("eur-pln-rate-note");
    expect(note).toHaveTextContent("Kurs EUR/PLN");
    expect(note).toHaveTextContent("1 € = 4,3014 zł (tabela A NBP z 25.08.2026)");
  });

  it("pozostawia kontrakt PLN bez dodatkowych przeliczeń i informacji o kursie", () => {
    renderCard(
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

    expect(screen.getByText("Klient płaci").parentElement).toHaveTextContent("250,00 zł/h");
    expect(screen.getByText("Konsultant dostaje").parentElement).toHaveTextContent("200,00 zł/h");
    expect(screen.getByText("Marża").parentElement).toHaveTextContent("50,00 zł/h · 20,0 %");
    expect(screen.queryByTestId("rate-client-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("rate-candidate-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("margin-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("monthly-margin-pln")).not.toBeInTheDocument();
    expect(screen.queryByTestId("eur-pln-rate-note")).not.toBeInTheDocument();
  });

  it("nie pokazuje przeliczenia EUR bez kursu ani dla kursu niepoprawnego", () => {
    const { rerender } = renderCard(<FinancialRatesCard contract={{ ...BASE_CONTRACT, eur_pln_rate: null }} />);

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

  // Wariant A (19.11.2026): marży między różnymi walutami nie liczymy (Bosch:
  // klient w EUR, konsultant w PLN) — kreska i zdanie; różnica po kursie NBP
  // zostaje tylko orientacyjnie, w zdaniu.
  it("przy różnych walutach marża to kreska ze zdaniem, a różnica po kursie NBP tylko orientacyjnie", () => {
    renderCard(
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

    expect(screen.getByTestId("figure-client")).toHaveTextContent("38,75 EUR/h");
    expect(screen.getByTestId("figure-candidate")).toHaveTextContent("120,00 zł/h");
    expect(screen.getByTestId("rate-client-pln")).toHaveTextContent("≈ 166,68 zł/h");
    expect(screen.queryByTestId("rate-candidate-pln")).not.toBeInTheDocument();
    expect(screen.getByTestId("figure-margin")).toHaveTextContent("— różne waluty");
    expect(screen.queryByTestId("margin-pln")).not.toBeInTheDocument();
    const sentence = screen.getByTestId("margin-mixed-currency");
    expect(sentence).toHaveTextContent(
      "Klient płaci w EUR, konsultant dostaje w zł — marży w jednej walucie nie liczymy.",
    );
    expect(screen.getByTestId("margin-approx-pln")).toHaveTextContent("≈ 46,68 zł/h (28,0 %)");
    expect(sentence).toHaveTextContent("czyli ≈ 7 469 zł miesięcznie.");
    expect(sentence).not.toHaveTextContent("..");
    expect(screen.getByText("Z umowy ramowej").parentElement).toHaveTextContent("130,00 zł/h");
    expect(screen.queryByTestId("framework-rate-pln")).not.toBeInTheDocument();
  });

  it("przelicza koszt i stawkę ramową, gdy tylko ich walutą jest EUR", () => {
    renderCard(
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
    expect(screen.getByTestId("rate-candidate-pln")).toHaveTextContent("≈ 120,44 zł/h");
    expect(screen.getByTestId("framework-rate-pln")).toHaveTextContent("≈ 129,04 zł/h");
    expect(screen.getByTestId("figure-margin")).toHaveTextContent("—");
    expect(screen.getByTestId("margin-approx-pln")).toHaveTextContent("≈ 79,56 zł/h (39,8 %)");
  });

  it("nie pokazuje fałszywej marży dla walut bez dostępnej konwersji", () => {
    renderCard(
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
    expect(screen.queryByTestId("margin-approx-pln")).not.toBeInTheDocument();
    expect(screen.getByTestId("margin-mixed-currency")).toHaveTextContent("Klient płaci w USD");
    expect(screen.queryByTestId("eur-pln-rate-note")).not.toBeInTheDocument();
  });

  it("odróżnia krok z zamówienia od ręcznego, a wpis zastąpiony tą samą datą pomija (UAT M08-B03)", () => {
    renderCard(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          currency: "PLN",
          rate_client: 130,
          client_rate_schedule: [
            { id: 1, rate: 120, effective_from: "2026-01-01", source_order_id: null },
            { id: 2, rate: 130, effective_from: "2026-07-01", source_order_id: null },
            { id: 3, rate: 130, effective_from: "2026-07-01", source_order_id: 77 },
          ],
        }}
      />,
    );

    // Bez odczytu aneksów krok bez zamówienia zostaje „ręcznie / aneks”.
    expect(screen.getByTestId("client-rate-schedule-1-source")).toHaveTextContent("ręcznie / aneks");
    expect(screen.getByTestId("client-rate-schedule-3-source")).toHaveTextContent("zamówienie");
    // Wpis zastąpiony nie ma wiersza — zostaje jedna linia.
    expect(screen.queryByTestId("client-rate-schedule-2-source")).not.toBeInTheDocument();
    expect(screen.queryByText(/nieobowiązująca/)).not.toBeInTheDocument();
    expect(screen.getByTestId("rate-steps-superseded")).toHaveTextContent(
      "Pominięto 1 wpis zastąpiony tego samego dnia (klient).",
    );
    expect(screen.getByTestId("rate-step-2026-07-01")).toHaveTextContent("obowiązuje");
    expect(screen.getByTestId("rate-step-2026-01-01")).not.toHaveTextContent("obowiązuje");
  });

  it("krok z datą aneksu stawki ma źródło „aneks”, a pozostałe ręczne — „ręcznie”", () => {
    renderCard(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          id: 42,
          currency: "PLN",
          rate_client: 170,
          rate_candidate: 130,
          margin: 40,
          client_rate_schedule: [
            { id: 7, rate: 180, effective_from: "2026-04-01", note: "Stawka początkowa" },
            { id: 8, rate: 170, effective_from: "2026-07-01", note: null },
          ],
          candidate_rate_schedule: [
            { id: 4, rate: 140, effective_from: "2026-04-01", note: "Stawka początkowa" },
            { id: 5, rate: 130, effective_from: "2026-07-01", note: "Zmiana stawki od lipca" },
            { id: 6, rate: 130, effective_from: "2026-07-01", note: null },
          ],
        }}
      />,
      (client) =>
        client.setQueryData(
          ["contract-amendments", 42],
          [{ id: 1, amendment_type: "rate_change", effective_date: "2026-07-01", withdrawn: false }],
        ),
    );

    expect(screen.getByTestId("client-rate-schedule-7-source")).toHaveTextContent("ręcznie");
    expect(screen.getByTestId("client-rate-schedule-8-source")).toHaveTextContent("aneks");
    // Notatka kroku drobnym drukiem — także z wpisu zastąpionego.
    expect(screen.getByTestId("rate-step-2026-07-01")).toHaveTextContent("Zmiana stawki od lipca");
    expect(screen.getByTestId("rate-step-2026-07-01")).toHaveTextContent("23,5 %");
  });

  it("nie oznacza przyszłego kroku jako aktualnego, gdy żaden jeszcze nie obowiązuje (retest B53)", () => {
    renderCard(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          currency: "PLN",
          rate_client: 150,
          client_rate_schedule: [{ id: 1, rate: 150, effective_from: "2099-01-01", source_order_id: 77 }],
        }}
      />,
    );

    const step = screen.getByTestId("rate-single-step");
    expect(step).not.toHaveTextContent("bez zmian");
    expect(step).toHaveTextContent("Od 01.01.2099 (zaplanowana)");
    expect(screen.getByTestId("rates-footnote")).not.toHaveTextContent("obowiązują od");
  });
});

// UAT B53: „Historia stawek" odsyła do kroków harmonogramu w tej karcie, a karta
// renderowała harmonogram dopiero od DWÓCH kroków — przy jednym kroku
// z zamówienia wskazówka prowadziła do pustego miejsca.
describe("FinancialRatesCard — harmonogram z jednym krokiem (UAT B53)", () => {
  it("pokazuje datę i pochodzenie już przy jednym kroku stawki klienta — jednym zdaniem, bez wykresu", () => {
    renderCard(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          currency: "PLN",
          rate_client: 130,
          client_rate_schedule: [{ id: 11, rate: 130, effective_from: "2026-07-01", source_order_id: 77 }],
        }}
      />,
    );

    expect(screen.getByTestId("client-rate-schedule-11-source")).toHaveTextContent("zamówienie");
    expect(screen.getByText(/Od 01\.07\.2026/)).toBeInTheDocument();
    expect(screen.getByTestId("rate-single-step")).toHaveTextContent(
      "Od 01.07.2026 bez zmian: klient płaci 130,00 zł/h, kandydat dostaje 28,00 zł/h (źródło: zamówienie).",
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByTestId("rate-steps-table")).not.toBeInTheDocument();
  });

  it("pokazuje jeden krok stawki kandydata, a bez kroków nic nie dorysowuje", () => {
    const { rerender } = renderCard(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          currency: "PLN",
          rate_candidate: 100,
          candidate_rate_schedule: [{ id: 5, rate: 100, effective_from: "2026-03-01" }],
        }}
      />,
    );
    expect(screen.getByText(/Od 01\.03\.2026/)).toBeInTheDocument();
    expect(screen.getByTestId("candidate-rate-schedule-5-source")).toHaveTextContent("ręcznie / aneks");

    rerender(<FinancialRatesCard contract={{ ...BASE_CONTRACT, currency: "PLN", rate_candidate: 100 }} />);
    expect(screen.queryByText(/^Od /)).not.toBeInTheDocument();
    expect(screen.getByTestId("rate-timeline")).toHaveTextContent(
      "Harmonogram stawek jest pusty — obowiązują stawki z kontraktu.",
    );
  });
});

describe("FinancialRatesCard — wariant A: liczby, wykres, tabela kroków", () => {
  const PLN: FinancialRatesContract = {
    ...BASE_CONTRACT,
    currency: "PLN",
    rate_client: 170,
    rate_candidate: 130,
    margin: 40,
    billing_hours_per_month: 168,
    eur_pln_rate: null,
  };

  it("pod każdą liczbą odpowiednik miesięczny przy godzinach kontraktu, jednostka w zdaniu pod spodem", () => {
    renderCard(<FinancialRatesCard contract={PLN} />);
    expect(screen.getByTestId("figure-client")).toHaveTextContent("28 560 zł / mies.");
    expect(screen.getByTestId("figure-candidate")).toHaveTextContent("21 840 zł / mies.");
    expect(screen.getByTestId("figure-margin")).toHaveTextContent("40,00 zł/h · 23,5 %");
    expect(screen.getByTestId("figure-margin")).toHaveTextContent("6 720 zł / mies.");
    expect(screen.getByTestId("rates-footnote")).toHaveTextContent("Stawki godzinowe · miesięcznie przy 168 h");
  });

  it("stawka dzienna liczy miesiąc z 21 MD, miesięczna nie ma drugiej linii", () => {
    const { rerender } = renderCard(<FinancialRatesCard contract={{ ...PLN, rate_unit: "daily" }} />);
    expect(screen.getByTestId("figure-client")).toHaveTextContent("170,00 zł/MD");
    expect(screen.getByTestId("figure-client")).toHaveTextContent("3 570 zł / mies.");
    expect(screen.getByTestId("rates-footnote")).toHaveTextContent("Stawki dzienne (MD) · miesięcznie przy 21 MD");

    rerender(<FinancialRatesCard contract={{ ...PLN, rate_unit: "monthly" }} />);
    expect(screen.getByTestId("figure-client")).toHaveTextContent("170,00 zł/mc");
    expect(screen.getByTestId("figure-client")).not.toHaveTextContent("/ mies.");
    expect(screen.getByTestId("rates-footnote")).toHaveTextContent("Stawki miesięczne");
  });

  it("ujemna marża jest czerwona, brak stawek to kreski bez kwot miesięcznych", () => {
    const { rerender } = renderCard(<FinancialRatesCard contract={{ ...PLN, margin: -5, rate_candidate: 175 }} />);
    expect(within(screen.getByTestId("figure-margin")).getByText("-5,00")).toHaveClass("text-destructive");

    rerender(
      <FinancialRatesCard contract={{ ...PLN, rate_client: null, rate_candidate: null, margin: null }} />,
    );
    expect(within(screen.getByTestId("figure-client")).getByRole("definition")).toHaveTextContent(/^—$/);
    expect(within(screen.getByTestId("figure-margin")).getByRole("definition")).toHaveTextContent(/^—$/);
    expect(screen.queryByText(/\/ mies\./)).not.toBeInTheDocument();
    expect(screen.getByTestId("rate-timeline")).toHaveTextContent(
      "Kontrakt nie ma jeszcze stawek — wejdą z zamówienia klienta albo z aneksu.",
    );
  });

  it("od dwóch kroków rysuje wykres z opisem i tabelę bez wierszy zastąpionych", () => {
    renderCard(
      <FinancialRatesCard
        contract={{
          ...PLN,
          start_date: "2025-12-01",
          client_order_end_date: "2026-12-31",
          client_rate_schedule: [
            { id: 7, rate: 180, effective_from: "2026-04-01" },
            { id: 8, rate: 170, effective_from: "2026-07-01" },
          ],
          candidate_rate_schedule: [
            { id: 4, rate: 140, effective_from: "2026-04-01" },
            { id: 5, rate: 130, effective_from: "2026-07-01" },
            { id: 6, rate: 130, effective_from: "2026-07-01" },
            { id: 17, rate: 130, effective_from: "2026-07-01" },
          ],
        }}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "Stawki od 01.04.2026: klient płaci 180,00 zł/h, od 01.07.2026 170,00 zł/h; kandydat dostaje 140,00 zł/h, od 01.07.2026 130,00 zł/h. Kwoty są też w tabeli pod wykresem.",
      }),
    ).toBeInTheDocument();
    const table = screen.getByTestId("rate-steps-table");
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Od",
      "Klientzł/h",
      "Kandydatzł/h",
      "Marżazł/h",
      "Źródło",
    ]);
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByTestId("rate-steps-superseded")).toHaveTextContent(
      "Pominięto 2 wpisy zastąpione tego samego dnia (kandydat).",
    );
    expect(screen.getByTestId("rate-timeline")).toHaveTextContent(
      "Umowa trwa od 01.12.2025, a harmonogram stawek zaczyna się 01.04.2026.",
    );
    expect(screen.getByTestId("rates-footnote")).toHaveTextContent("obowiązują od 01.07.2026");
  });

  it("przy różnych walutach zamiast wykresu zdanie, a tabela bez kolumny marży", () => {
    renderCard(
      <FinancialRatesCard
        contract={{
          ...BASE_CONTRACT,
          rate_client_currency: "EUR",
          rate_candidate_currency: "PLN",
          rate_client: 30.125,
          rate_candidate: 100,
          margin: null,
          client_rate_schedule: [
            { id: 103, rate: 30.125, effective_from: "2019-02-18", note: "Stawka sprzed synchronizacji" },
            { id: 442, rate: 30.125, effective_from: "2026-06-01", note: "Z zamówienia klienta", source_order_id: 803 },
          ],
          candidate_rate_schedule: [{ id: 167, rate: 100, effective_from: "2019-02-18" }],
        }}
      />,
    );

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByTestId("rate-timeline-mixed-currency")).toHaveTextContent(
      "Klient płaci w EUR, kandydat dostaje w zł — wykres na jednej osi byłby mylący, kroki są w tabeli.",
    );
    const table = screen.getByTestId("rate-steps-table");
    expect(within(table).queryByText("Marża")).not.toBeInTheDocument();
    expect(screen.getByTestId("client-rate-schedule-442-source")).toHaveTextContent("zamówienie");
    expect(screen.getByTestId("client-rate-schedule-442-pln")).toHaveTextContent("≈ 129,58 zł");
    expect(screen.getByTestId("rate-step-2026-06-01")).not.toHaveTextContent("Z zamówienia klienta");
  });
});

describe("FinancialRatesCard — stawka z umowy ramowej jedną linią", () => {
  const NORDEA: FinancialRatesContract = {
    ...BASE_CONTRACT,
    currency: "PLN",
    client_name: "Nordea Bank Abp",
    rate_client: 170,
    rate_candidate: 130,
    margin: 40,
    framework_rate: 170,
    eur_pln_rate: null,
    framework_rate_schedule: [{ id: 1, rate: 170, effective_from: "2026-01-01", effective_to: "2099-12-31" }],
  };

  it("u Nordei mówi, że stawka klienta jest w limicie, z datą końca stawki ramowej", () => {
    renderCard(<FinancialRatesCard contract={NORDEA} />);
    expect(screen.getByTestId("framework-rate")).toHaveTextContent(
      "Z umowy ramowej170,00 zł/h do 31.12.2099 · stawka klienta w limicie",
    );
    expect(screen.queryByTestId("framework-rate-exceeded")).not.toBeInTheDocument();
  });

  it("u Nordei ostrzega, gdy stawka klienta przekracza ramową", () => {
    renderCard(<FinancialRatesCard contract={{ ...NORDEA, rate_client: 182, margin: 52 }} />);
    const warning = screen.getByTestId("framework-rate-exceeded");
    expect(warning).toHaveTextContent("Stawka klienta wyższa o 12,00 zł/h");
    expect(warning).toHaveAttribute("title", "Stawka klienta (182,00 zł/h) przekracza stawkę z umowy ramowej");
  });

  it("u innych klientów pokazuje samą stawkę ramową, bez oceny", () => {
    renderCard(<FinancialRatesCard contract={{ ...NORDEA, client_name: "Acme", rate_client: 182 }} />);
    expect(screen.getByTestId("framework-rate")).not.toHaveTextContent("w limicie");
    expect(screen.queryByTestId("framework-rate-exceeded")).not.toBeInTheDocument();
  });
});

// Zgłoszenie Klaudii 29.10.2026 (wariant A z makiet): kontrakt bez stawki
// klienta pokazuje stawkę z rekrutacji jako podpowiedź. Nic się nie zapisuje —
// przychód nadal przychodzi z zamówienia (decyzja z 04.10.2026).
describe("FinancialRatesCard — stawka z rekrutacji przed zamówieniem", () => {
  const PLN_HOURLY: FinancialRatesContract = {
    ...BASE_CONTRACT,
    currency: "PLN",
    rate_candidate: 110,
    rate_client: null,
    margin: null,
    eur_pln_rate: null,
  };
  const RATE: RecruitmentRate = {
    candidate_id: 5,
    job_id: 7,
    job_title: "Analityk Systemowy",
    client_rate_value: "150.00",
    client_rate_unit: "hourly",
    client_rate_currency: "PLN",
    client_rate_at: "2026-10-02T09:00:00Z",
    client_rate_by_name: "Anna Nowak",
    client_rate_redacted: false,
    candidate_rate_value: "110",
    candidate_rate_unit: "hourly",
    candidate_rate_currency: "PLN",
    candidate_rate_at: null,
  };

  it("pokazuje stawkę z rekrutacji, kto i kiedy ją wpisał, oraz marżę według niej", () => {
    renderCard(<FinancialRatesCard contract={PLN_HOURLY} recruitmentRate={RATE} />);

    const hint = screen.getByTestId("client-rate-from-recruitment");
    expect(hint).toHaveTextContent("Z rekrutacji „Analityk Systemowy” (Anna Nowak, 2.10.2026)");
    expect(hint).toHaveTextContent("150,00 zł/h");
    expect(hint).toHaveTextContent("Marża wg rekrutacji");
    expect(hint).toHaveTextContent("40,00 zł/h (26,7 %)");
    expect(hint).toHaveTextContent("Stawka przychodowa wejdzie do kontraktu z zamówieniem klienta.");
    // Marża kontraktu zostaje pusta — podpowiedź niczego nie udaje.
    expect(screen.getByText("Marża").closest("div")).toHaveTextContent("—");
  });

  it("nie pokazuje podpowiedzi, gdy kontrakt ma już stawkę klienta", () => {
    renderCard(<FinancialRatesCard contract={{ ...PLN_HOURLY, rate_client: 155, margin: 45 }} recruitmentRate={RATE} />);
    expect(screen.queryByTestId("client-rate-from-recruitment")).not.toBeInTheDocument();
  });

  it("nie pokazuje podpowiedzi, gdy stawka do klienta jest ukryta albo pusta", () => {
    const { rerender } = renderCard(
      <FinancialRatesCard
        contract={PLN_HOURLY}
        recruitmentRate={{ ...RATE, client_rate_value: null, client_rate_redacted: true }}
      />,
    );
    expect(screen.queryByTestId("client-rate-from-recruitment")).not.toBeInTheDocument();
    rerender(<FinancialRatesCard contract={PLN_HOURLY} recruitmentRate={{ ...RATE, client_rate_value: null }} />);
    expect(screen.queryByTestId("client-rate-from-recruitment")).not.toBeInTheDocument();
  });

  it("bez marży, gdy jednostka albo waluta rekrutacji jest inna niż kontraktu", () => {
    const { rerender } = renderCard(
      <FinancialRatesCard
        contract={PLN_HOURLY}
        recruitmentRate={{ ...RATE, client_rate_value: "1200", client_rate_unit: "daily" }}
      />,
    );
    let hint = screen.getByTestId("client-rate-from-recruitment");
    expect(hint).toHaveTextContent("1200,00 zł/MD");
    expect(hint).not.toHaveTextContent("Marża wg rekrutacji");

    rerender(
      <FinancialRatesCard
        contract={PLN_HOURLY}
        recruitmentRate={{ ...RATE, client_rate_value: "40", client_rate_currency: "EUR" }}
      />,
    );
    hint = screen.getByTestId("client-rate-from-recruitment");
    expect(hint).toHaveTextContent("40,00 EUR/h");
    expect(hint).not.toHaveTextContent("Marża wg rekrutacji");
  });
});
