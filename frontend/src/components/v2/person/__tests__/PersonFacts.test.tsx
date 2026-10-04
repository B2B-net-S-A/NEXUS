/**
 * Fakty o osobie — jeden wygląd i jedne teksty w panelu osoby i w przeglądzie
 * Delivery Leada (jeden panel osoby, 04.10.2026).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PersonFacts, RateWithBudget } from "@/components/v2/person/PersonFacts";
import { availabilityText, budgetCheck, onsiteText, rateText } from "@/lib/person-facts";

describe("teksty faktów", () => {
  it("stawka: złotówki z jednostką, obca waluta z kodem, nieczytelna = brak", () => {
    expect(rateText(140, "hourly", "PLN")).toBe("140 zł/h");
    expect(rateText("900", "daily", null)).toBe("900 zł/MD");
    expect(rateText(40, "hourly", "eur")).toBe("40 EUR/h");
    expect(rateText("abc", "hourly", "PLN")).toBeNull();
    expect(rateText(null, "hourly", "PLN")).toBeNull();
  });

  it("dostępność: data wygrywa, potem status z okresem wypowiedzenia", () => {
    expect(availabilityText({ date: "2026-11-01", status: "open_to_offers" })).toMatch(/^od /);
    expect(
      availabilityText({ status: "open_to_offers", noticePeriod: 1, noticeUnit: "months" }),
    ).toBe("Otwarty na oferty · wypowiedzenie 1 mies.");
    expect(availabilityText({ noticePeriod: 2, noticeUnit: "weeks" })).toBe("wypowiedzenie 2 tyg.");
    expect(availabilityText({ status: "unknown_status" })).toBeNull();
    expect(availabilityText(null)).toBeNull();
  });

  it("tryb: 0 dni = zdalnie", () => {
    expect(onsiteText(0)).toBe("Zdalnie");
    expect(onsiteText(2)).toBe("Do 2 dni w biurze");
    expect(onsiteText(null)).toBeNull();
  });

  it("budżet: porównanie po przeliczeniu na miesiąc, obca waluta nie do porównania", () => {
    // 150 zł/h × 168 h = 25 200 zł/mc > 20 000 zł/mc.
    expect(budgetCheck(150, "hourly", "PLN", 20_000).verdict).toBe("over");
    expect(budgetCheck("100", "hourly", "PLN", 20_000).verdict).toBe("within");
    expect(budgetCheck(40, "hourly", "EUR", 20_000).verdict).toBe("incomparable");
    expect(budgetCheck(150, "hourly", "PLN", null).verdict).toBe("none");
  });
});

describe("PersonFacts", () => {
  it("brak danych to „—”, a dopisek źródła stoi przy swoim fakcie", () => {
    render(
      <PersonFacts
        testId="facts"
        rows={[
          { label: "Tryb", value: null },
          { label: "Dostępność", value: "od zaraz", hint: "z karty" },
        ]}
      />,
    );
    expect(screen.getByTestId("facts")).toHaveTextContent("Warunki wobec rekrutacji");
    expect(screen.getByText("—")).toBeTruthy();
    const hint = screen.getByText("z karty");
    expect(hint.parentElement).toHaveTextContent("Dostępność");
    expect(hint.parentElement).toHaveTextContent("od zaraz");
  });

  it("stawka z budżetem: przekroczenie nazwane wprost, bez stawki — „brak stawki”", () => {
    const { rerender } = render(
      <RateWithBudget value={150} unit="hourly" currency="PLN" budgetMonthly={20_000} />,
    );
    expect(screen.getByText("150 zł/h")).toBeTruthy();
    expect(screen.getByText("ponad budżet")).toBeTruthy();
    rerender(<RateWithBudget value={40} unit="hourly" currency="EUR" budgetMonthly={20_000} />);
    expect(screen.getByText(/nie do porównania z budżetem/)).toBeTruthy();
    rerender(<RateWithBudget value={null} unit={null} currency={null} budgetMonthly={20_000} />);
    expect(screen.getByText("brak stawki")).toBeTruthy();
  });
});

describe("PersonFacts — układ po dwa (panel 380 px, 04.10.2026)", () => {
  it("krótkie fakty po dwa w wierszu, długi na całą szerokość, brak = „—”", () => {
    render(
      <PersonFacts
        testId="facts"
        pairs
        rows={[
          { label: "W tej rekrutacji", value: "150 zł/h w budżecie", wide: true },
          { label: "Stawka od", value: "140 zł/h" },
          { label: "Dostępność", value: null },
          { label: "Tryb", value: "hybryda" },
        ]}
      />,
    );
    const grid = screen.getByTestId("facts").querySelector('[data-layout="pairs"]') as HTMLElement;
    expect(grid.className).toMatch(/grid-cols-2/);
    expect(screen.getByText("W tej rekrutacji").parentElement?.className).toMatch(/col-span-2/);
    expect(screen.getByText("Stawka od").parentElement?.className).not.toMatch(/col-span-2/);
    expect(screen.getByText("Dostępność").parentElement).toHaveTextContent("—");
  });
});
