/**
 * Okno „Podgląd” CV (Edytor CV 3): Esc w „Szukaj w CV” czyści zapytanie,
 * a nie zamyka okna — tak jak w podglądzie oryginału i w edytorze.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Strony PDF mają własny test; tu tylko pole wyszukiwania z paska stron.
vi.mock("@/components/v2/cv/CvPagesPreview", () => ({
  CvPagesPreview: () => (
    <div data-document-search="">
      <input aria-label="Szukaj w CV" defaultValue="Java" />
    </div>
  ),
}));

import { CvFilePreviewDialog } from "../CvFilePreviewDialog";

function renderDialog(onOpenChange = vi.fn()) {
  render(
    <CvFilePreviewDialog
      open
      onOpenChange={onOpenChange}
      title="CV do klienta — Anna Przykładowa"
      loadPdf={vi.fn()}
      load={vi.fn()}
    />,
  );
  return onOpenChange;
}

describe("CvFilePreviewDialog", () => {
  it("Esc w polu „Szukaj w CV” z zapytaniem nie zamyka okna", () => {
    const onOpenChange = renderDialog();
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Szukaj w CV" }), { key: "Escape" });
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("Esc poza wyszukiwaniem zamyka okno", () => {
    const onOpenChange = renderDialog();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
