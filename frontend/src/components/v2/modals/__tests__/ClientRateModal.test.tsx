import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Mock } from "vitest";
import type { ComponentProps } from "react";
import { render, screen, fireEvent } from "@testing-library/react";

import { ClientRateModal } from "../ClientRateModal";

type ModalProps = ComponentProps<typeof ClientRateModal>;

function renderModal(
  overrides: {
    onConfirm?: Mock<ModalProps["onConfirm"]>;
    onSkip?: Mock<ModalProps["onSkip"]>;
  } = {},
) {
  const onConfirm = overrides.onConfirm ?? vi.fn<ModalProps["onConfirm"]>();
  const onSkip = overrides.onSkip ?? vi.fn<ModalProps["onSkip"]>();
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

  it("po zamówieniu nie przyjmuje nowej stawki i odsyła do zamówienia", () => {
    const onConfirm = vi.fn<ModalProps["onConfirm"]>();
    const onSkip = vi.fn<ModalProps["onSkip"]>();
    render(
      <ClientRateModal
        open
        onOpenChange={vi.fn()}
        candidateName="Szymon Eliasz"
        onConfirm={onConfirm}
        onSkip={onSkip}
        required
        initialRate={{ value: 190, unit: "hourly" }}
        orderLock={{ order_id: 7, contract_id: 3, title: "Zamówienie Crc" }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Ta osoba ma już zamówienie „Zamówienie Crc”. Stawkę do klienta zmień w zamówieniu",
    );
    expect(screen.queryByRole("button", { name: "Przesuń i zapisz" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Przesuń bez zmiany stawki" }),
    );
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
