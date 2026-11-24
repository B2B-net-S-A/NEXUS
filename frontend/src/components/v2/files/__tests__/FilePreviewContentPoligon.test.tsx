import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type CandidateDocument, FilePreviewContent } from "@/components/v2/files/FilePreviewModal";

// Zgłoszenie z 24.11.2026: na Poligonie „CV oryginalne” osoby ćwiczebnej
// pisało „Podgląd nie jest dostępny dla tego formatu. Pobierz plik…”, a „CV
// firmowe” — że to Poligon. Poligon nie renderuje plików (zestaw ma sam opis
// pliku, bez nazwy), a bajty szłyby do API z identyfikatorem 990000+.

const POLIGON_TEXT = "Na poligonie podgląd tego pliku nie działa. W prawdziwej rekrutacji zobaczysz tu plik.";

function doc(options: Partial<CandidateDocument> = {}): CandidateDocument {
  return {
    id: 990305,
    // Kopia CV ze zgłoszenia z zestawu: nazwa pliku wycięta, typ nieznany.
    filename: "CV",
    content_type: null,
    size_bytes: null,
    document_kind: "cv",
    is_primary: false,
    uploaded_at: null,
    external_source: null,
    created_at: "",
    ...options,
  };
}

afterEach(() => {
  window.sessionStorage.clear();
});

describe("FilePreviewContent na Poligonie", () => {
  it.each([
    ["kopia CV bez nazwy pliku", doc()],
    ["PDF z profilu", doc({ id: 991420, filename: "CV.pdf", content_type: "application/pdf" })],
  ])("%s: komunikat Poligonu, bez pobierania", async (_, file) => {
    window.sessionStorage.setItem("nexus.poligon", "1");
    const load = vi.fn(async () => new Blob(["x"]));
    render(<FilePreviewContent doc={file} candidateId={990105} onDownload={vi.fn()} loadDocumentBlob={load} />);
    expect(await screen.findByText(POLIGON_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(/Podgląd nie jest dostępny/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Pobierz plik/ })).toBeNull();
    expect(load).not.toHaveBeenCalled();
  });

  it("poranna porcja nowości (tryb ćwiczebny „novelty”) też mówi, że to Poligon", async () => {
    window.sessionStorage.setItem("nexus.poligon", "novelty");
    render(<FilePreviewContent doc={doc()} candidateId={990105} onDownload={vi.fn()} />);
    expect(await screen.findByText(POLIGON_TEXT)).toBeInTheDocument();
  });

  it("poza Poligonem plik bez podglądu dalej proponuje pobranie", async () => {
    render(<FilePreviewContent doc={doc()} candidateId={7} onDownload={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/Podgląd nie jest dostępny dla tego formatu/)).toBeInTheDocument());
    expect(screen.queryByText(POLIGON_TEXT)).toBeNull();
  });
});
