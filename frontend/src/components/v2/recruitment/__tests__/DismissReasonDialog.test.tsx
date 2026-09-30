import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DismissReasonDialog, dismissDialogTitle } from "@/components/v2/recruitment/DismissReasonDialog";
import {
  DISMISS_REASONS,
  dismissFeedbackError,
  dismissRequestBody,
} from "@/lib/proposal-dismiss";

describe("powód „Pomiń”", () => {
  it("walidacja: powód wymagany, przy „Inne” także opis", () => {
    expect(dismissFeedbackError(null, "")).toBe("Wybierz powód pominięcia.");
    expect(dismissFeedbackError("other", "   ")).toMatch(/Inne/);
    expect(dismissFeedbackError("other", "Klient nie chce B2B")).toBeNull();
    expect(dismissFeedbackError("too_expensive", "")).toBeNull();
    expect(dismissFeedbackError("too_junior", "x".repeat(501))).toMatch(/500/);
  });

  it("ciało żądania: źródło + powód, pusty opis nie jedzie", () => {
    expect(dismissRequestBody("new_cv", { reason: "outdated_cv", note: "  " })).toEqual({
      source: "new_cv",
      reason: "outdated_cv",
    });
    expect(dismissRequestBody("full_base", { reason: "other", note: " Za daleko " })).toEqual({
      source: "full_base",
      reason: "other",
      note: "Za daleko",
    });
  });

  it("tytuł odmienia liczbę osób", () => {
    expect(dismissDialogTitle(1)).toBe("Dlaczego pomijasz tę osobę?");
    expect(dismissDialogTitle(3)).toBe("Pomiń 3 osoby — dlaczego?");
    expect(dismissDialogTitle(5)).toBe("Pomiń 5 osób — dlaczego?");
    expect(dismissDialogTitle(12)).toBe("Pomiń 12 osób — dlaczego?");
  });

  it("okno pokazuje sześć powodów i nie wysyła bez wyboru", () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(<DismissReasonDialog open count={1} onOpenChange={onOpenChange} onConfirm={onConfirm} />);
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getAllByRole("radio")).toHaveLength(DISMISS_REASONS.length);
    fireEvent.click(dialog.getByRole("button", { name: "Pomiń" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(dialog.getByRole("alert")).toHaveTextContent("Wybierz powód pominięcia.");
  });

  it("„Inne” wymaga opisu, a po jego wpisaniu wysyła powód z opisem", () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(<DismissReasonDialog open count={1} onOpenChange={onOpenChange} onConfirm={onConfirm} />);
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.click(dialog.getByRole("radio", { name: "Inne" }));
    fireEvent.click(dialog.getByRole("button", { name: "Pomiń" }));
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.change(dialog.getByLabelText("Opis (wymagany)"), { target: { value: "  Klient zna go z innej firmy " } });
    fireEvent.click(dialog.getByRole("button", { name: "Pomiń" }));
    expect(onConfirm).toHaveBeenCalledWith({ reason: "other", note: "Klient zna go z innej firmy" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
