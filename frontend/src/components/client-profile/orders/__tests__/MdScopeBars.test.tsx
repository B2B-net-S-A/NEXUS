import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MdScopeBars } from "@/components/client-profile/orders/MdScopeBars";
import type { OrderLineRead } from "@/lib/api/orderGroups";

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 10,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Anna Przykładowa",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-01-01",
    end_date: null,
    rate_cost: null,
    rate_revenue: null,
    input_value: 190,
    input_mode: "md",
    md_total: 190,
    md_remaining: 36,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_used: 154,
    md_optional_total: 170,
    md_base_used: 154,
    md_optional_used: 0,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    ...overrides,
  };
}

describe("MdScopeBars — podstawa + opcja (CeZ)", () => {
  it("dwa paski ZUŻYCIA i suma z procentem — wypełnienie to wykorzystane MD", () => {
    render(<MdScopeBars line={line()} />);

    const base = screen.getByRole("progressbar", { name: /Podstawa/ });
    // 154 / 190 = 81% — pasek rośnie razem ze zużyciem, nie opada z resztą.
    expect(base).toHaveAttribute("aria-valuenow", "81");
    expect(base.closest("div")?.parentElement).toHaveTextContent(/154 \/ 190 MD 81%/);

    const optional = screen.getByRole("progressbar", { name: /Opcja/ });
    expect(optional).toHaveAttribute("aria-valuenow", "0");
    expect(optional.closest("div")?.parentElement).toHaveTextContent(/0 \/ 170 MD 0%/);

    // 154 / (190 + 170) = 43%
    expect(screen.getByText(/Wykorzystano łącznie/)).toHaveTextContent(/154 \/ 360 MD 43%/);
  });

  it("umowa bez opcji: kursywa zamiast pustego paska „0 / 0”", () => {
    render(
      <MdScopeBars
        line={line({ md_optional_total: null, md_optional_used: null, md_used: 50, md_base_used: 50 })}
      />,
    );
    expect(screen.getByText("brak opcji w umowie")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar", { name: /Opcja/ })).toBeNull();
    // Suma liczy samą podstawę.
    expect(screen.getByText(/Wykorzystano łącznie/)).toHaveTextContent(/50 \/ 190 MD 26%/);
  });

  it("przekroczenie zakresu zmienia kolor na ostrzegawczy, a liczby nie są ścinane", () => {
    render(
      <MdScopeBars
        line={line({ md_total: 100, md_used: 112, md_base_used: 100, md_optional_total: 10, md_optional_used: 12 })}
      />,
    );
    const optional = screen.getByRole("progressbar", { name: /Opcja/ });
    expect(optional.firstElementChild).toHaveClass("bg-destructive");
    // 12 / 10 = 120% — tekst mówi prawdę, tylko szerokość paska jest ścięta.
    expect(optional.closest("div")?.parentElement).toHaveTextContent(/12 \/ 10 MD 120%/);
    expect(screen.getByText(/Wykorzystano łącznie/)).toHaveTextContent(/112 \/ 110 MD 102%/);
    expect(screen.getByText(/Wykorzystano łącznie/)).toHaveClass("text-destructive");
  });

  it("bez serwerowego podziału dzieli md_used po tej samej regule co backend", () => {
    // Wiersz sprzed rozszerzenia kontraktu: samo `md_used`, opcja z umowy.
    render(
      <MdScopeBars
        line={line({ md_used: 200, md_base_used: null, md_optional_used: null, md_optional_total: 50 })}
      />,
    );
    expect(screen.getByRole("progressbar", { name: /Podstawa/ }).closest("div")?.parentElement)
      .toHaveTextContent(/190 \/ 190 MD 100%/);
    expect(screen.getByRole("progressbar", { name: /Opcja/ }).closest("div")?.parentElement)
      .toHaveTextContent(/10 \/ 50 MD 20%/);
  });
});
