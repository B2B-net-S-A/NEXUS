/**
 * Mail odrzucenia jest OPT-IN od 17.09.2026: checkbox domyślnie odznaczony,
 * a okno zawsze wysyła jawny boolean — serwer planuje wysyłkę wyłącznie
 * przy `true`.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RejectionV2 } from "@/components/v2/modals/RejectionV2";

const reasons = [
  { id: "7", label: "Za wysoka stawka", applies_to: ["rejected" as const] },
];

function renderRejection(onConfirm = vi.fn()) {
  render(
    <RejectionV2
      open
      onOpenChange={() => {}}
      terminalType="rejected"
      reasons={reasons}
      previousStageCategory="external"
      previousStage="cv_sent"
      onConfirm={onConfirm}
    />,
  );
  return onConfirm;
}

describe("RejectionV2 — mail odrzucenia opt-in", () => {
  it("checkbox maila jest domyślnie odznaczony i wysyłamy jawne false", () => {
    const onConfirm = renderRejection();
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();

    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][2]).toBe(false);
  });

  it("zaznaczony checkbox wysyła true", () => {
    const onConfirm = renderRejection();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));

    expect(onConfirm.mock.calls[0][2]).toBe(true);
  });
});
