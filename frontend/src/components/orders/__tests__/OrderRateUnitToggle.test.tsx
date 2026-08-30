import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  OrderCurrencySelect,
  OrderRateUnitToggle,
  convertRateInput,
} from "@/components/orders/OrderRateUnitToggle";
import type { OrderRateUnit } from "@/lib/api/dlPortal";

function RateHarness() {
  const [unit, setUnit] = useState<OrderRateUnit>("hourly");
  const [cost, setCost] = useState("125");
  const [revenue, setRevenue] = useState("150");
  return (
    <>
      <OrderRateUnitToggle
        value={unit}
        rateCandidate={cost}
        rateClient={revenue}
        onValueChange={setUnit}
        onRateCandidateChange={setCost}
        onRateClientChange={setRevenue}
      />
      <output data-testid="cost">{cost}</output>
      <output data-testid="revenue">{revenue}</output>
    </>
  );
}

describe("OrderRateUnitToggle", () => {
  it("przelicza obie stawki hour ↔ MD jednym przełączeniem (1 MD = 8 h)", async () => {
    const user = userEvent.setup();
    render(<RateHarness />);

    await user.click(screen.getByRole("radio", { name: "MD" }));
    expect(screen.getByTestId("cost")).toHaveTextContent("1000");
    expect(screen.getByTestId("revenue")).toHaveTextContent("1200");

    await user.click(screen.getByRole("radio", { name: "Godzinowa" }));
    expect(screen.getByTestId("cost")).toHaveTextContent("125");
    expect(screen.getByTestId("revenue")).toHaveTextContent("150");
  });

  it("zachowuje 3 miejsca oraz billing hours przy przełączeniach miesięcznych", () => {
    expect(convertRateInput("164,375", "hourly", "daily")).toBe("1315");
    expect(convertRateInput("1315", "daily", "hourly")).toBe("164.375");
    expect(convertRateInput("16000", "monthly", "hourly", 160)).toBe("100");
    expect(convertRateInput("16000", "monthly", "hourly", 168)).toBe(
      "95.238",
    );
  });

  it("zachowuje istniejący wybór GBP obok PLN/EUR/USD", async () => {
    const user = userEvent.setup();
    function CurrencyHarness() {
      const [currency, setCurrency] = useState("GBP");
      return <OrderCurrencySelect value={currency} onChange={setCurrency} />;
    }

    render(<CurrencyHarness />);
    const select = screen.getByRole("combobox", {
      name: "Waluta zamówienia (przychodowa)",
    });
    expect(select).toHaveValue("GBP");
    expect(screen.getByRole("option", { name: "GBP" })).toBeInTheDocument();

    await user.selectOptions(select, "EUR");
    expect(select).toHaveValue("EUR");
    expect(screen.getByRole("option", { name: "GBP" })).toBeInTheDocument();
  });
});
