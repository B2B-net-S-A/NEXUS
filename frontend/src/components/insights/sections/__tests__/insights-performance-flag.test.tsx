/**
 * Plakietki ostrzeżeń przy osobie — trzy reguły, których złamanie jest
 * defektem, a nie kwestią gustu:
 *
 * 1. **Awaria odczytu ostrzeżeń nie może renderować się jako ich brak.**
 *    Wiersze tabeli bez plakietek czytają się jako zdanie „nikt nie ma
 *    ostrzeżeń”, którego nikt nie wypowiedział — a 403 i 500 znaczą coś
 *    zupełnie innego niż zero.
 * 2. **Zero ostrzeżeń u czynnego pracownika to WYNIK, nie pusty stan.**
 *    Żadnej kreski, żadnego pudełka „brak danych”.
 * 3. **„Były pracownik” stoi OBOK ostrzeżeń, nie zamiast nich** — i pokazuje
 *    się także wtedy, gdy osoba nie ma żadnej plakietki.
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  InsightsPerformanceFlags,
  PerformanceFlagsLoadNotice,
} from "@/components/insights/sections/InsightsPerformanceFlag";
import type { PerformanceFlag } from "@/lib/insights-flags-api";

function flag(overrides: Partial<PerformanceFlag> = {}): PerformanceFlag {
  return {
    id: 1,
    user_id: 7,
    flag_type: "weak_results",
    label: "Słabe wyniki",
    description: "Bardzo słabe wyniki, wymagana nagła poprawa",
    severity: "critical",
    note: "Skonsultuj się z managerem. Za mała ilość weryfikacji.",
    is_active: true,
    created_at: "2026-08-12T09:00:00+02:00",
    created_by_id: 1,
    created_by_name: "Admin System",
    cleared_at: null,
    cleared_by_id: null,
    cleared_by_name: null,
    ...overrides,
  };
}

describe("InsightsPerformanceFlags", () => {
  it("renderuje etykietę, stały opis i komentarz autora", () => {
    render(<InsightsPerformanceFlags flags={[flag()]} />);

    expect(screen.getByText("Słabe wyniki")).toBeInTheDocument();
    expect(
      screen.getByText("Bardzo słabe wyniki, wymagana nagła poprawa"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Skonsultuj się z managerem. Za mała ilość weryfikacji.",
      ),
    ).toBeInTheDocument();
  });

  it("pokazuje obie plakietki naraz, a wspólny komentarz tylko raz", () => {
    // DynaReporter: Zuzanna Gruszczyńska ma „Słabe wyniki” I „Procedury”,
    // a pod nimi JEDNO zdanie. Powtórzone brzmi jak dwa różne zarzuty.
    render(
      <InsightsPerformanceFlags
        flags={[
          flag({ id: 1, note: "Za mała ilość weryfikacji." }),
          flag({
            id: 2,
            flag_type: "procedures",
            label: "Procedury",
            description:
              "Niestosowanie się do procedur, wymagane przypomnienie procedur",
            severity: "warning",
            note: "Za mała ilość weryfikacji.",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Słabe wyniki")).toBeInTheDocument();
    expect(screen.getByText("Procedury")).toBeInTheDocument();
    expect(screen.getAllByText("Za mała ilość weryfikacji.")).toHaveLength(1);
  });

  it("niesie podpis autora w `title` — anonimowej oceny nie renderujemy", () => {
    const { container } = render(<InsightsPerformanceFlags flags={[flag()]} />);
    const titled = container.querySelector("[title]");
    expect(titled?.getAttribute("title")).toContain("Admin System");
  });

  it("brak ostrzeżeń u czynnej osoby renderuje NIC (to wynik, nie pustka)", () => {
    const { container } = render(<InsightsPerformanceFlags flags={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("chip „były pracownik” pokazuje się także bez ostrzeżeń", () => {
    render(<InsightsPerformanceFlags flags={[]} isFormerEmployee />);
    expect(screen.getByText("były pracownik")).toBeInTheDocument();
  });

  it("chip stoi OBOK ostrzeżenia, nie zamiast niego", () => {
    render(<InsightsPerformanceFlags flags={[flag()]} isFormerEmployee />);
    expect(screen.getByText("były pracownik")).toBeInTheDocument();
    expect(screen.getByText("Słabe wyniki")).toBeInTheDocument();
  });

  it("nieznane `severity` nadal renderuje plakietkę", () => {
    render(
      <InsightsPerformanceFlags
        flags={[
          flag({
            // Backend dorzucił typ, front jeszcze o nim nie wie. Plakietka,
            // która znika przez nierozpoznany kolor, gubi całą treść oceny.
            severity: "spoznienia" as never,
            label: "Spóźnienia",
            description: "Powtarzające się spóźnienia",
          }),
        ]}
      />,
    );
    expect(screen.getByText("Spóźnienia")).toBeInTheDocument();
    expect(screen.getByText("Powtarzające się spóźnienia")).toBeInTheDocument();
  });
});

describe("PerformanceFlagsLoadNotice", () => {
  it("403 mówi o uprawnieniach, a NIE o braku ostrzeżeń", () => {
    render(
      <PerformanceFlagsLoadNotice
        isPending={false}
        isSuccess={false}
        isError
        error={{ response: { status: 403 } }}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("nie ma dostępu");
    expect(screen.getByRole("status").textContent).toContain("NIE jest pusta");
  });

  it("500 proponuje ponowienie i nie twierdzi, że ostrzeżeń nie ma", () => {
    const onRetry = vi.fn();
    render(
      <PerformanceFlagsLoadNotice
        isPending={false}
        isSuccess={false}
        isError
        error={{ response: { status: 500 } }}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("Mogą istnieć");
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("błąd sieci (bez statusu) mówi o połączeniu", () => {
    render(
      <PerformanceFlagsLoadNotice
        isPending={false}
        isSuccess={false}
        isError
        error={new Error("Network Error")}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain(
      "połączyć z serwerem",
    );
  });

  it("przerwa między ponowieniami to NADAL ładowanie, nie cisza", () => {
    // `isPending=false`, `isError=false`, `isSuccess=false` — react-query
    // między próbami. Bez gałęzi `isSuccess` ten stan udawałby sukces.
    render(
      <PerformanceFlagsLoadNotice
        isPending={false}
        isSuccess={false}
        isError={false}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain(
      "Wczytuję ostrzeżenia",
    );
  });

  it("sukces nie renderuje niczego", () => {
    const { container } = render(
      <PerformanceFlagsLoadNotice
        isPending={false}
        isSuccess
        isError={false}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
