"use client";

/**
 * Harness lupy „Szukaj w CV” w podglądzie dokumentu (09.2026).
 *
 * Renderuje PRAWDZIWE `FilePreviewModal` i `FilePreviewContent` z plikami
 * statycznymi z `public/preview/cv-search/` (dane fikcyjne) — bez API, więc
 * strona jest w `PUBLIC_PATHS` middleware'u. Trzy przypadki, które muszą
 * zachowywać się różnie: PDF z tekstem (podświetlenia + licznik), skan (pasek
 * mówi „brak tekstu”) i DOCX (to samo wyszukiwanie po HTML-u).
 */

import { useState } from "react";

import {
  type CandidateDocument,
  FilePreviewContent,
  FilePreviewModal,
} from "@/components/v2/files/FilePreviewModal";

const FILES: Record<number, string> = {
  1: "/preview/cv-search/cv-tekst.pdf",
  2: "/preview/cv-search/cv-skan.pdf",
  3: "/preview/cv-search/cv.docx",
};

function doc(
  id: number,
  filename: string,
  contentType: string,
  isPrimary = false,
): CandidateDocument {
  return {
    id,
    filename,
    content_type: contentType,
    size_bytes: null,
    document_kind: "cv",
    is_primary: isPrimary,
    uploaded_at: `2026-09-0${id}T08:00:00Z`,
    external_source: null,
    created_at: `2026-09-0${id}T08:00:00Z`,
  };
}

const DOCUMENTS: CandidateDocument[] = [
  doc(1, "Anna Przykładowa — CV.pdf", "application/pdf", true),
  doc(2, "Anna Przykładowa — skan.pdf", "application/pdf"),
  doc(
    3,
    "Anna Przykładowa — CV.docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ),
];

async function loadStaticBlob(
  _candidateId: number,
  docId: number,
): Promise<Blob> {
  const response = await fetch(FILES[docId]);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.blob();
}

export default function CvSearchPreviewPage() {
  const [openId, setOpenId] = useState<number | null>(null);

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-foreground">
            Szukaj w CV — harness
          </h1>
          <p className="text-sm text-muted-foreground">
            Ctrl+F w otwartym podglądzie przeszukuje dokument, nie stronę.
          </p>
        </div>
        <div className="flex gap-2">
          {DOCUMENTS.map((document) => (
            <button
              key={document.id}
              type="button"
              onClick={() => setOpenId(document.id)}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-sm hover:bg-accent"
            >
              Otwórz: {document.filename.split("— ")[1]}
            </button>
          ))}
        </div>
      </header>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-foreground">
          Podgląd osadzony w stronie (profil kandydata)
        </h2>
        <div className="h-[70dvh] overflow-hidden rounded-lg border border-border">
          <FilePreviewContent
            doc={DOCUMENTS[0]}
            candidateId={0}
            onDownload={() => undefined}
            loadDocumentBlob={loadStaticBlob}
            hidePdfSidebar
            className="h-full"
          />
        </div>
      </section>

      <FilePreviewModal
        documents={DOCUMENTS}
        initialDocumentId={openId}
        candidateId={0}
        onClose={() => setOpenId(null)}
        onDownload={() => undefined}
        loadDocumentBlob={loadStaticBlob}
      />
    </main>
  );
}
