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

const sourcesMounted = vi.fn();
vi.mock("@/components/v2/cv-editor/CvEditorSources", async () => {
  const { useEffect } = await import("react");
  return {
    CvEditorSources: ({ stageId, cvOnly }: { stageId?: number; cvOnly?: boolean }) => {
      useEffect(() => {
        sourcesMounted();
      }, []);
      return <div data-testid="original">{`etap ${stageId} ${cvOnly ? "sam plik" : "zakładki"}`}</div>;
    },
  };
});

import { CvFilePreviewDialog } from "../CvFilePreviewDialog";

function renderDialog(onOpenChange = vi.fn(), originalStageId?: number) {
  render(
    <CvFilePreviewDialog
      open
      onOpenChange={onOpenChange}
      title="CV do klienta — Anna Przykładowa"
      loadPdf={vi.fn()}
      load={vi.fn()}
      originalStageId={originalStageId}
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

  it("bez etapu z oryginałem nie ma przycisku", () => {
    renderDialog();
    expect(screen.queryByRole("button", { name: /oryginał/, hidden: true })).toBeNull();
  });

  it("oryginał jest na przycisk: domyślnie niezamontowany, potem po lewej, schowany nie montuje się drugi raz", () => {
    sourcesMounted.mockClear();
    renderDialog(vi.fn(), 123);
    expect(screen.queryByTestId("original")).toBeNull();
    expect(sourcesMounted).not.toHaveBeenCalled();
    // Przycisk ma `hidden min-[1180px]:inline-flex`, a jsdom nie liczy szerokości.
    const button = () => screen.getByRole("button", { name: /(Pokaż|Schowaj) oryginał/, hidden: true });
    expect(button()).toHaveTextContent("Pokaż oryginał");

    fireEvent.click(button());
    const original = screen.getByTestId("original");
    expect(original).toHaveTextContent("etap 123 sam plik");
    const aside = original.closest("aside") as HTMLElement;
    expect(aside.hidden).toBe(false);
    expect(aside).toHaveClass("min-[1180px]:block");
    const pages = screen.getByRole("textbox", { name: "Szukaj w CV", hidden: true });
    expect(aside.compareDocumentPosition(pages) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(button()).toHaveTextContent("Schowaj oryginał");

    fireEvent.click(button());
    expect(aside.hidden).toBe(true);
    // Ten sam wariant szerokości co przycisk nie może przebić schowania.
    expect(aside).not.toHaveClass("min-[1180px]:block");
    fireEvent.click(button());
    expect(aside.hidden).toBe(false);
    expect(sourcesMounted).toHaveBeenCalledTimes(1);
  });
});
