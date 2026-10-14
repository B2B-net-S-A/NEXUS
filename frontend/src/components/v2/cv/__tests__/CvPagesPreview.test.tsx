/**
 * „Jak u klienta” (Edytor CV 3, J2, 14.10.2026): strony PDF z pliku Word,
 * a gdy PDF nie powstanie albo pdf.js go nie narysuje — plik Word jak dotąd.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ pdfFile: null as Blob | null }));

// pdf.js i docx-preview nie działają w jsdom — każdy ma własny test.
vi.mock("@/components/v2/files/SearchablePdfPreview", () => ({
  SearchablePdfPreview: (props: { file: Blob; onError?: () => void }) => {
    mocks.pdfFile = props.file;
    return (
      <button type="button" data-testid="pdf-pages" onClick={() => props.onError?.()}>
        strony
      </button>
    );
  },
}));
vi.mock("@/components/v2/cv-editor/CvEditorWordPreview", () => ({
  CvEditorWordPreview: (props: { load: () => Promise<Blob>; fallback?: ReactNode }) => (
    <div data-testid="word-preview">{props.fallback}</div>
  ),
}));

import { CvPagesPreview } from "../CvPagesPreview";

describe("CvPagesPreview", () => {
  it("rysuje strony PDF i nie pobiera pliku Word", async () => {
    const pages = new Blob(["%PDF"], { type: "application/pdf" });
    const loadDocx = vi.fn();
    render(<CvPagesPreview loadPdf={() => Promise.resolve(pages)} loadDocx={loadDocx} />);

    expect(screen.getByRole("status")).toHaveTextContent("Przygotowuję strony CV…");
    expect(await screen.findByTestId("pdf-pages")).toBeInTheDocument();
    expect(mocks.pdfFile).toBe(pages);
    expect(screen.getByTestId("cv-pages-preview")).toBeInTheDocument();
    expect(screen.queryByTestId("word-preview")).not.toBeInTheDocument();
    expect(loadDocx).not.toHaveBeenCalled();
  });

  it("bez PDF (503, brak zgody, brak prawa) pokazuje plik Word z zapasem", async () => {
    render(
      <CvPagesPreview
        loadPdf={() => Promise.reject(new Error("503"))}
        loadDocx={vi.fn()}
        fallback={<p>treść z edytora</p>}
      />,
    );

    const word = await screen.findByTestId("word-preview");
    expect(word).toHaveTextContent("treść z edytora");
    expect(screen.queryByTestId("pdf-pages")).not.toBeInTheDocument();
  });

  it("PDF, którego pdf.js nie narysuje, oddaje miejsce plikowi Word", async () => {
    render(<CvPagesPreview loadPdf={() => Promise.resolve(new Blob(["zły"]))} loadDocx={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("pdf-pages"));
    expect(await screen.findByTestId("word-preview")).toBeInTheDocument();
  });
});
