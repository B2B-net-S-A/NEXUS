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
});
