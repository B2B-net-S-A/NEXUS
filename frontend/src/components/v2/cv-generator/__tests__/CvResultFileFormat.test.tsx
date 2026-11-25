import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { GeneratedCvItem } from "@/lib/api";
import type { CvFileFormat } from "@/lib/cv-file-format";

import { CvResultView } from "../CvResult";

vi.mock("@/components/v2/modals/CVBrandedEditModal", () => ({ CVBrandedEditModal: () => null }));

function item(partial: Partial<GeneratedCvItem> & Pick<GeneratedCvItem, "id">): GeneratedCvItem {
  return {
    candidate_name: "Jan Kowalski", candidate_id: 1, job_id: 5, client_name: "Bank Przykładowy", position: "Java Developer",
    language: "pl", blind: false, mode: "new", content_mode: "tailored", filename: `CV_${partial.id}.docx`,
    status: "ready", warnings: [], can_download: true, can_delete: true, created_at: new Date().toISOString(),
    ...partial,
  };
}

function view(fileFormat: CvFileFormat | null, partial: Partial<GeneratedCvItem> = {}) {
  const onDownload = vi.fn();
  const onDownloadPdf = vi.fn();
  render(
    <CvResultView
      mainId={1} documents={[item({ id: 1, ...partial })]} canWrite onPreview={() => undefined} onEdit={() => undefined}
      onDownload={onDownload} onDownloadPdf={onDownloadPdf} fileFormat={fileFormat}
    />,
  );
  const buttons = screen.getAllByRole("button", { name: /^Pobierz (DOCX|PDF)$/ }).map((b) => b.textContent);
  return { onDownload, onDownloadPdf, buttons };
}

// Format pliku z reguły klienta (25.11.2026): wynik generatora stawia go na wierzchu.
describe("CvResultView — format pliku klienta", () => {
  it("bez wymagań zostaje sam „Pobierz DOCX”", () => {
    expect(view(null).buttons).toEqual(["Pobierz DOCX"]);
  });

  it("klient chce Worda: sam „Pobierz DOCX”", () => {
    expect(view("docx").buttons).toEqual(["Pobierz DOCX"]);
  });

  it("klient chce PDF: „Pobierz PDF” pierwszy, pobiera PDF", () => {
    const { buttons, onDownloadPdf, onDownload } = view("pdf");
    expect(buttons).toEqual(["Pobierz PDF", "Pobierz DOCX"]);
    expect(screen.getByTestId("cv-result-client-format")).toHaveTextContent("Klient chce: PDF");
    fireEvent.click(screen.getByTestId("cv-result-download-pdf"));
    expect(onDownloadPdf).toHaveBeenCalledTimes(1);
    expect(onDownload).not.toHaveBeenCalled();
  });

  it("generacja w Nowym CV: bez PDF z pliku Word, wskazanie karty", () => {
    expect(view("pdf", { cv_layout: "new" }).buttons).toEqual(["Pobierz DOCX"]);
    expect(screen.getByTestId("cv-result-client-format")).toHaveTextContent("z karty „CV do klienta”");
  });

  it("klient chce obu: DOCX i PDF", () => {
    expect(view("both").buttons).toEqual(["Pobierz DOCX", "Pobierz PDF"]);
  });
});
