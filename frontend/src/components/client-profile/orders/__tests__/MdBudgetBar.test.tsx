import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MdBudgetBar } from "../MdBudgetBar";

describe("MdBudgetBar", () => {
  it("pokazuje pełną liczbę z ułamkiem i jednostkę", () => {
    render(<MdBudgetBar remaining={39.17} total={96.95} />);
    expect(screen.getByRole("progressbar").nextElementSibling).toHaveTextContent("39,17 / 96,95 MD");
  });

  // Zamówienie 86_2026 przy 1280 × 720: pasek 96 px + „39,17 / 96,95 MD” (119 px)
  // nie mieściły się w 184 px komórki i tekst wchodził pod przycisk „Zużycie”.
  // jsdom nie liczy układu, więc pilnujemy kontraktu: ustępuje pasek, nie liczby.
  it("w ciasnej komórce ustępuje pasek, a liczba bez miejsca schodzi pod spód", () => {
    render(<MdBudgetBar remaining={39.17} total={96.95} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveClass("basis-10", "grow", "max-w-24");
    expect(bar).not.toHaveClass("shrink-0", "w-24");
    expect(bar.nextElementSibling).toHaveClass("shrink-0");
    expect(bar.parentElement).toHaveClass("flex-wrap");
  });

  it("przekroczony budżet zostaje widoczny jako liczba ujemna", () => {
    render(<MdBudgetBar remaining={-2.5} total={96.95} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "0");
    expect(bar.nextElementSibling).toHaveTextContent("-2,5 / 96,95 MD");
  });
});
