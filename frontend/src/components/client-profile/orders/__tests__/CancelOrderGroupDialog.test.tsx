import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { CancelOrderGroupDialog, cancelRefusalMessage } from "../CancelOrderGroupDialog";
import { orderGroupMatchesPill } from "@/lib/client-order-list";
import type { OrderGroupRead } from "@/lib/api/orderGroups";

const group = {
  id: 7,
  order_number: "445/2026",
  status: "active",
  status_label: "Aktywne",
} as unknown as OrderGroupRead;

describe("CancelOrderGroupDialog", () => {
  it("sends the trimmed reason, or null when empty", () => {
    const onConfirm = vi.fn();
    const { rerender } = render(
      <CancelOrderGroupDialog group={group} pending={false} error={null} onConfirm={onConfirm} onClose={vi.fn()} />,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  pomyłka  " } });
    fireEvent.click(screen.getByRole("button", { name: "Anuluj zamówienie" }));
    expect(onConfirm).toHaveBeenLastCalledWith("pomyłka");

    rerender(
      <CancelOrderGroupDialog key="fresh" group={group} pending={false} error={null} onConfirm={onConfirm} onClose={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Anuluj zamówienie" }));
    expect(onConfirm).toHaveBeenLastCalledWith(null);
  });

  it("shows the server refusal inside the dialog", () => {
    render(
      <CancelOrderGroupDialog
        group={group}
        pending={false}
        error="Zamówienia 445/2026 nie można anulować — ma rozliczenia: rozliczone MD konsultantów (2)."
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("rozliczone MD konsultantów (2)");
  });

  it("renders nothing without a target", () => {
    const { container } = render(
      <CancelOrderGroupDialog group={null} pending={false} error={null} onConfirm={vi.fn()} onClose={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("cancelRefusalMessage", () => {
  it("reads message from a 409 object detail and ignores other errors", () => {
    expect(
      cancelRefusalMessage({ response: { status: 409, data: { detail: { message: "ma rozliczenia" } } } }),
    ).toBe("ma rozliczenia");
    expect(cancelRefusalMessage({ response: { status: 409, data: { detail: "już anulowane" } } })).toBe(
      "już anulowane",
    );
    expect(cancelRefusalMessage({ response: { status: 403, data: { detail: "x" } } })).toBeNull();
  });
});

describe("orderGroupMatchesPill — cancelled", () => {
  it("cancelled groups live under their own pill, not active/completed", () => {
    const cancelled = { ...group, status: "cancelled" } as OrderGroupRead;
    expect(orderGroupMatchesPill(cancelled, "cancelled")).toBe(true);
    expect(orderGroupMatchesPill(cancelled, "active")).toBe(false);
    expect(orderGroupMatchesPill(cancelled, "completed")).toBe(false);
    expect(orderGroupMatchesPill(group, "cancelled")).toBe(false);
  });
});
