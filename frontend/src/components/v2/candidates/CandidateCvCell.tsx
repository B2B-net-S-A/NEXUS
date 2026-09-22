"use client";

import { useState, type MouseEvent } from "react";
import { FileText, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import {
  FilePreviewModal,
  downloadDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";

/**
 * Kolumna „CV” na liście kandydatów: klik otwiera podgląd CV w oknie
 * (PDF przez pdf.js z wyszukiwaniem, DOCX renderowany), bez pobierania pliku.
 * Dokumenty pobieramy dopiero przy kliknięciu — lista nie płaci za nie
 * przy każdym wierszu. Klik NIE otwiera podglądu kandydata (stopPropagation).
 */
export function CandidateCvCell({
  candidateId,
  candidateName,
  hasCv,
}: {
  candidateId: number;
  candidateName: string;
  hasCv: boolean;
}) {
  const [loading, setLoading] = useState(false);
  const [previewDocumentId, setPreviewDocumentId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<CandidateDocument[]>([]);
  const { showError } = useToast();

  if (!hasCv) {
    return <span className="text-xs text-muted-foreground">brak</span>;
  }

  const openCv = async (event: MouseEvent) => {
    event.stopPropagation();
    if (loading) return;
    setLoading(true);
    try {
      const { data: docs } = await api.get<CandidateDocument[]>(
        `/api/candidates/${candidateId}/documents?kind=cv`,
      );
      const primary = docs.find((d) => d.is_primary) ?? docs[0];
      if (!primary) {
        showError("Kandydat nie ma zapisanego pliku CV.");
        return;
      }
      setDocuments(docs);
      setPreviewDocumentId(primary.id);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się otworzyć CV kandydata."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        onClick={openCv}
        disabled={loading}
        aria-label={`Podgląd CV: ${candidateName}`}
        className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-card px-2 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-50"
      >
        {loading ? (
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
        ) : (
          <FileText className="h-3 w-3" aria-hidden />
        )}
        CV
      </button>
      <FilePreviewModal
        documents={documents}
        initialDocumentId={previewDocumentId}
        candidateId={candidateId}
        onClose={() => setPreviewDocumentId(null)}
        onDownload={(doc) => downloadDocumentBlob(candidateId, doc).catch(() => {})}
      />
    </div>
  );
}
