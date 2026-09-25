import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ConsumptionButton,
  shortMonthPl,
} from "@/components/client-profile/orders/ConsumptionButton";
import type { OrderLineRead } from "@/lib/api/orderGroups";

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 146,
    group_id: 51,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Konrad Teper",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-05-01",
    end_date: null,
    rate_cost: 560,
    rate_revenue: 1000,
    input_value: 9.66,
    input_mode: "md",
    md_total: 9.66,
    md_remaining: 5.963,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    consumption_recent: [
      { period_month: "2026-06", md: 12 },
      { period_month: "2026-07", md: 21.75 },
      { period_month: "2026-08", md: 3.7 },
    ],
    consumption_flags: [],
    ...overrides,
  };
}

describe("ConsumptionButton — „Zużycie MD” zamiast kalendarza", () => {
  it("mini-wykres i ostatnia wartość: „Zużycie · sie 3,7”", async () => {
    const onClick = vi.fn();
    render(<ConsumptionButton line={line()} onClick={onClick} />);
    const button = screen.getByRole("button", { name: "Zużycie MD — Konrad Teper" });
    expect(button).toHaveTextContent("Zużycie · sie 3,7");
    expect(button).toHaveAttribute(
      "title",
      "Zużycie miesięczne – podgląd i edycja",
    );
    expect(screen.getByTestId("consumption-sparkline").querySelectorAll("rect")).toHaveLength(3);
    expect(screen.queryByTestId("consumption-warning-dot")).toBeNull();
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["negative_balance", "saldo osoby jest ujemne"],
    ["missing_previous_month", "brakuje zejścia za poprzedni miesiąc"],
    ["import_to_verify", "wiersz importu tej osoby czeka na weryfikację"],
  ] as const)("ostrzeżenie %s: pomarańczowy przycisk z kropką i powodem", (flag, reason) => {
    render(<ConsumptionButton line={line({ consumption_flags: [flag] })} onClick={() => {}} />);
    const button = screen.getByRole("button", { name: new RegExp(`uwaga: ${reason}`) });
    expect(button).toHaveClass("bg-warning-muted");
    expect(button.getAttribute("title")).toContain(`Uwaga: ${reason}`);
    expect(screen.getByTestId("consumption-warning-dot")).toBeInTheDocument();
  });

  it("bez zejść — sam napis „Zużycie”, bez wykresu", () => {
    render(<ConsumptionButton line={line({ consumption_recent: [] })} onClick={() => {}} />);
    expect(screen.getByRole("button", { name: "Zużycie MD — Konrad Teper" })).toHaveTextContent(
      /^Zużycie$/,
    );
    expect(screen.queryByTestId("consumption-sparkline")).toBeNull();
  });

  it("skrót miesiąca po polsku", () => {
    expect(shortMonthPl("2026-08")).toBe("sie");
    expect(shortMonthPl("2026-01")).toBe("sty");
  });
});
