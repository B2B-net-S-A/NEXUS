import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OrderTypeSwitch } from "@/components/orders/OrderTypeSwitch";

describe("OrderTypeSwitch", () => {
  it("renders only order types enabled for the client", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <OrderTypeSwitch
        value="cost"
        allowedTypes={["cost", "md"]}
        onChange={onChange}
      />,
    );

    expect(screen.queryByRole("radio", { name: "Okresowe" })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Kosztowe" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(screen.getByRole("radio", { name: "MD" }));
    expect(onChange).toHaveBeenCalledWith("md");
  });

  it("podpowiada typ najczęstszy u klienta i ostrzega przy innym wyborze", () => {
    const { rerender } = render(
      <OrderTypeSwitch value="periodic" usualType="md" onChange={vi.fn()} />,
    );

    // Nazwa radia zostaje bez dopisku — inne testy i czytniki szukają „MD".
    expect(screen.getByRole("radio", { name: "MD" })).toBeInTheDocument();
    expect(screen.getByText("zwykle u klienta")).toBeInTheDocument();
    expect(
      screen.getByText(/U tego klienta zamówienia są zwykle typu\s+MD\./),
    ).toBeInTheDocument();

    rerender(<OrderTypeSwitch value="md" usualType="md" onChange={vi.fn()} />);
    expect(screen.queryByText(/U tego klienta zamówienia są zwykle/)).not.toBeInTheDocument();
  });

  it("bez podpowiedzi klienta nie pokazuje dopisku ani ostrzeżenia", () => {
    render(<OrderTypeSwitch value="periodic" onChange={vi.fn()} />);
    expect(screen.queryByText("zwykle u klienta")).not.toBeInTheDocument();
    expect(screen.queryByText(/U tego klienta/)).not.toBeInTheDocument();
  });

  it("zablokowany przełącznik nie ostrzega o typie klienta", () => {
    render(
      <OrderTypeSwitch value="periodic" usualType="md" disabled onChange={vi.fn()} />,
    );
    expect(screen.queryByText(/U tego klienta/)).not.toBeInTheDocument();
  });
});
