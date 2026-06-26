import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ClientRateModal } from "../ClientRateModal";

function renderModal(overrides: { onConfirm?: ReturnType<typeof vi.fn>; onSkip?: ReturnType<typeof vi.fn> } = {}) {
  const onConfirm = overrides.onConfirm ?? vi.fn();
  const onSkip = overrides.onSkip ?? vi.fn();
  render(
    <ClientRateModal
      open
      onOpenChange={vi.fn()}
      candidateName="Szymon Eliasz"
      onConfirm={onConfirm}
      onSkip={onSkip}
    />,
  );
  return { onConfirm, onSkip };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ClientRateModal", () => {
  it("pokazuje nazwę kandydata i prośbę o stawkę do klienta", () => {
    renderModal();
    expect(screen.getByText("Szymon Eliasz")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /CV Wysłane/i }),
    ).toBeInTheDocument();
  });

  it("blokuje „Przesuń i zapisz” dopóki stawka nie jest dodatnią liczbą", () => {
    renderModal();
    const confirm = screen.getByRole("button", { name: "Przesuń i zapisz" });
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("np. 25000"), {
      target: { value: "0" },
    });
    expect(confirm).toBeDisabled();
  });

  it("przekazuje stawkę z domyślną jednostką monthly i walutą PLN", () => {
    const { onConfirm } = renderModal();
    fireEvent.change(screen.getByPlaceholderText("np. 25000"), {
      target: { value: "25000.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Przesuń i zapisz" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith({
      rate: 25000.5,
      unit: "monthly",
      currency: "PLN",
    });
  });

  it("„Przesuń bez stawki” wywołuje onSkip bez onConfirm", () => {
    const { onConfirm, onSkip } = renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Przesuń bez stawki" }));

    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
