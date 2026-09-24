import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmTwoStepButton } from "@/components/orders/ConfirmTwoStepButton";

// N8 (audyt 24.09.2026): potwierdzenie w oknie zamiast `window.confirm`,
// który zamraża automatyzację przeglądarki.
describe("ConfirmTwoStepButton", () => {
  afterEach(() => vi.useRealTimers());

  it("pierwszy klik pyta, drugi wykonuje — bez window.confirm", () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    const onConfirm = vi.fn();
    render(
      <ConfirmTwoStepButton
        ariaLabel="Usuń plik"
        confirmAriaLabel="Potwierdź usunięcie"
        confirmLabel="Usunąć?"
        onConfirm={onConfirm}
      >
        Usuń
      </ConfirmTwoStepButton>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Usuń plik" }));
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź usunięcie" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("wraca do stanu wyjściowego po czasie bez drugiego kliknięcia", () => {
    vi.useFakeTimers();
    const onConfirm = vi.fn();
    render(
      <ConfirmTwoStepButton confirmLabel="Usunąć?" onConfirm={onConfirm} timeoutMs={1000}>
        Usuń
      </ConfirmTwoStepButton>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toHaveTextContent("Usunąć?");
    act(() => {
      vi.advanceTimersByTime(1001);
    });
    expect(screen.getByRole("button")).toHaveTextContent("Usuń");
    fireEvent.click(screen.getByRole("button"));
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
