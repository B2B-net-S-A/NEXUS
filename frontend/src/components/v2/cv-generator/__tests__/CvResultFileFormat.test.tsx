import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { GeneratedCvItem } from "@/lib/api";
import type { CvFileFormat } from "@/lib/cv-file-format";

import { CvResultView, newLayoutStageId } from "../CvResult";

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
  const buttons = screen.getAllByRole("button", { name: /^Pobierz (DOCX|PDF|Word)$/ }).map((b) => b.textContent);
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

// 26.11.2026 (Artur: „wybieram nowy szablon, a generuje mi się stary”): wynik
// generatora przy „Nowym CV” pokazywał i dawał klasyczny plik generacji. Gdy CV
// trafiło do etapu w Nowym CV, podgląd i pliki biorą CV z karty etapu.
describe("CvResultView — Nowe CV z karty etapu", () => {
  const stageNew = { cv_layout: "new" as const, stage_cv_stage_id: 77, stage_cv_layout: "new" as const };

  it("bez wymagań klienta: PDF Nowego CV i Word nowego wyglądu", () => {
    const { buttons, onDownloadPdf } = view(null, stageNew);
    expect(buttons).toEqual(["Pobierz PDF", "Pobierz Word"]);
    fireEvent.click(screen.getByTestId("cv-result-download-pdf"));
    expect(onDownloadPdf).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/plik DOCX stąd jest klasyczny/)).toBeNull();
  });

  it("klient chce Worda: Word pierwszy", () => {
    expect(view("docx", stageNew).buttons).toEqual(["Pobierz Word", "Pobierz PDF"]);
  });

  it("CV etapu przełączone na Klasyczne: zwykły plik generacji", () => {
    expect(view(null, { ...stageNew, stage_cv_layout: "classic" }).buttons).toEqual(["Pobierz DOCX"]);
  });
});

describe("newLayoutStageId", () => {
  it("etap tylko przy CV etapu w Nowym CV", () => {
    const base = { id: 1, language: "pl", filename: "x", status: "ready" } as const;
    expect(newLayoutStageId({ ...base, stage_cv_stage_id: 77, stage_cv_layout: "new" } as GeneratedCvItem)).toBe(77);
    expect(newLayoutStageId({ ...base, stage_cv_stage_id: 77, stage_cv_layout: "classic" } as GeneratedCvItem)).toBeNull();
    expect(newLayoutStageId({ ...base, cv_layout: "new" } as GeneratedCvItem)).toBeNull();
  });
});

// 26.11.2026 (Artur, wariant „Użyj w rekrutacji”): etap miał już szkic, więc
// generacja nie trafiła do rekrutacji — ekran mówi to wprost i daje wybór.
describe("CvResultView — etap ma już inne CV", () => {
  function conflictView(busy = false) {
    const onUse = vi.fn();
    const onKeep = vi.fn();
    render(
      <CvResultView
        mainId={1} documents={[item({ id: 1, cv_layout: "new" })]} canWrite onPreview={() => undefined}
        onEdit={() => undefined} onDownload={() => undefined} attachedStage="verified"
        stageConflict={{ since: "2026-11-13T16:11:35Z", busy, onUse, onKeep }}
      />,
    );
    return { onUse, onKeep };
  }

  it("mówi, że wersja nie trafiła do rekrutacji, i nie twierdzi, że podpięto", () => {
    conflictView();
    expect(screen.getByTestId("cv-result-stage-conflict")).toHaveTextContent("Etap ma już CV do klienta z 13.11");
    expect(screen.getByTestId("cv-result-stage-conflict")).toHaveTextContent("Ta wersja nie trafiła do rekrutacji");
    expect(screen.queryByText(/Podpięte do procesu/)).toBeNull();
  });

  it("„Użyj tej wersji w rekrutacji” i „Zostaw stare” wołają swoje akcje", () => {
    const { onUse, onKeep } = conflictView();
    fireEvent.click(screen.getByRole("button", { name: "Użyj tej wersji w rekrutacji" }));
    fireEvent.click(screen.getByRole("button", { name: "Zostaw stare" }));
    expect(onUse).toHaveBeenCalledTimes(1);
    expect(onKeep).toHaveBeenCalledTimes(1);
  });

  it("w trakcie podmiany przycisk jest zablokowany", () => {
    conflictView(true);
    expect(screen.getByRole("button", { name: "Używam…" })).toBeDisabled();
  });
});
