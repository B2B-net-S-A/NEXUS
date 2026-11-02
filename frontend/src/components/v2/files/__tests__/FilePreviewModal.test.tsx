import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type CandidateDocument,
  FilePreviewModal,
} from "@/components/v2/files/FilePreviewModal";
import { useAuthStore } from "@/store/auth";

function document(
  id: number,
  filename: string,
  options: Partial<CandidateDocument> = {},
): CandidateDocument {
  return {
    id,
    filename,
    content_type: "text/plain",
    size_bytes: 100,
    document_kind: "cv",
    is_primary: false,
    uploaded_at: `2026-07-${10 + id}T08:00:00Z`,
    external_source: null,
    created_at: `2026-07-${10 + id}T08:00:00Z`,
    ...options,
  };
}

describe("FilePreviewModal CV gallery", () => {
  it("orders primary first and supports buttons plus arrow keys", () => {
    const documents = [
      document(1, "CV-old.txt"),
      document(2, "CV-primary.txt", { is_primary: true }),
      document(3, "CV-new.txt"),
    ];

    render(
      <FilePreviewModal
        documents={documents}
        initialDocumentId={2}
        candidateId={7}
        onClose={vi.fn()}
        onDownload={vi.fn()}
      />,
    );

    expect(screen.getByText("CV-primary.txt")).toBeInTheDocument();
    expect(screen.getByText("CV 1 z 3")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Poprzednie CV" }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Następne CV" }));
    expect(screen.getByText("CV-new.txt")).toBeInTheDocument();
    expect(screen.getByText("CV 2 z 3")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText("CV-old.txt")).toBeInTheDocument();
    expect(screen.getByText("CV 3 z 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Następne CV" })).toBeDisabled();

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByText("CV-new.txt")).toBeInTheDocument();
  });

  it("shows CV 1 of 1 with both controls disabled", () => {
    render(
      <FilePreviewModal
        documents={[document(1, "only-cv.txt", { is_primary: true })]}
        initialDocumentId={1}
        candidateId={7}
        onClose={vi.fn()}
        onDownload={vi.fn()}
      />,
    );

    expect(screen.getByText("CV 1 z 1")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Poprzednie CV" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Następne CV" })).toBeDisabled();
  });
});

describe("FilePreviewModal — lupa „Szukaj w CV”", () => {
  it("arrow keys typed in the search box move the caret, not the CV", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => new Blob(["x"], { type: "image/png" }),
    } as Response);
    const createUrl = vi.fn(() => "blob:cv");
    Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: vi.fn() });
    const onClose = vi.fn();

    render(
      <FilePreviewModal
        documents={[
          document(1, "CV-scan.png", {
            is_primary: true,
            content_type: "image/png",
          }),
          document(2, "CV-other.png", { content_type: "image/png" }),
        ]}
        initialDocumentId={1}
        candidateId={7}
        onClose={onClose}
        onDownload={vi.fn()}
      />,
    );

    const input = await screen.findByRole("searchbox", { name: "Szukaj w CV" });
    // Obraz nie ma warstwy tekstu — pasek mówi to wprost.
    expect(
      screen.getByText("Ten plik to skan — nie ma w nim tekstu do przeszukania"),
    ).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(screen.getByText("CV 1 z 2")).toBeInTheDocument();

    // Esc z wpisanym zapytaniem czyści pole i nie zamyka okna.
    fireEvent.change(input, { target: { value: "java" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect((input as HTMLInputElement).value).toBe("");
    expect(onClose).not.toHaveBeenCalled();

    fetchMock.mockRestore();
  });
});

describe("FilePreviewModal — sama rola rekrutera (02.11.2026)", () => {
  afterEach(() => {
    useAuthStore.setState({ user: null });
  });

  const header = (doc: CandidateDocument) =>
    render(
      <FilePreviewModal
        documents={[doc]}
        initialDocumentId={doc.id}
        candidateId={7}
        onClose={vi.fn()}
        onDownload={vi.fn()}
        loadDocumentBlob={() => new Promise(() => {})}
      />,
    );

  it("nie ma „Pobierz” przy pliku z podglądem", () => {
    useAuthStore.setState({ user: { id: 1, role: "recruiter", roles: ["recruiter"] } as never });
    header(document(1, "cv.pdf", { content_type: "application/pdf" }));
    expect(screen.queryByTitle("Pobierz plik na dysk")).toBeNull();
  });

  it("zostawia pobranie przy pliku bez podglądu", () => {
    useAuthStore.setState({ user: { id: 1, role: "recruiter", roles: ["recruiter"] } as never });
    header(document(1, "cv.doc", { content_type: "application/msword" }));
    expect(screen.getByTitle("Pobierz plik na dysk")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz plik$/ })).toBeInTheDocument();
  });

  it("rola dodatkowa zdejmuje ograniczenie", () => {
    useAuthStore.setState({
      user: { id: 1, role: "delivery_lead", roles: ["delivery_lead", "recruiter"] } as never,
    });
    header(document(1, "cv.pdf", { content_type: "application/pdf" }));
    expect(screen.getByTitle("Pobierz plik na dysk")).toBeInTheDocument();
  });
});
