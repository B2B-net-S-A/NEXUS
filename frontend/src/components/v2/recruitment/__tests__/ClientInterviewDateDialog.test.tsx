/**
 * „Kiedy rozmowa u klienta?” przy przesunięciu karty (20.10.2026): termin albo
 * jawne „Nie znam jeszcze terminu”, nigdy cichy ruch bez decyzji.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ClientInterviewDateDialog } from "@/components/v2/recruitment/ClientInterviewDateDialog";

function renderDialog() {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ClientInterviewDateDialog
      open
      candidateName="Anna Nowak"
      onCancel={onCancel}
      onConfirm={onConfirm}
    />,
  );
  const dialog = screen.getByRole("dialog", { name: "Kiedy rozmowa u klienta?" });
  return { dialog, onConfirm, onCancel };
}

describe("ClientInterviewDateDialog", () => {
  it("bez godziny prosi o termin albo „Nie znam jeszcze terminu”", () => {
    const { dialog, onConfirm } = renderDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Przesuń" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Nie znam jeszcze terminu");
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("termin i długość idą do ruchu", () => {
    const { dialog, onConfirm } = renderDialog();
    fireEvent.change(within(dialog).getByLabelText("Dzień"), { target: { value: "2026-10-22" } });
    fireEvent.change(within(dialog).getByLabelText("Godzina"), { target: { value: "14:00" } });
    fireEvent.change(within(dialog).getByLabelText("Długość"), { target: { value: "90" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Przesuń" }));
    expect(onConfirm).toHaveBeenCalledWith({
      start: new Date("2026-10-22T14:00").toISOString(),
      durationMinutes: 90,
    });
  });

  it("„Nie znam jeszcze terminu” przesuwa bez terminu", () => {
    const { dialog, onConfirm } = renderDialog();
    fireEvent.click(within(dialog).getByLabelText("Nie znam jeszcze terminu"));
    expect(within(dialog).getByLabelText("Godzina")).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Przesuń" }));
    expect(onConfirm).toHaveBeenCalledWith(null);
  });

  it("„Anuluj” nie przesuwa", () => {
    const { dialog, onConfirm, onCancel } = renderDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
