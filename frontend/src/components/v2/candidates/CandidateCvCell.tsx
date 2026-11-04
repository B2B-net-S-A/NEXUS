"use client";

import { useState, type MouseEvent } from "react";
import { Check, FileText, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";
import {
  FilePreviewModal,
  downloadDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";

/**
 * „Pobierz dokumenty CV → otwórz podgląd głównego” jako hook: kolumna listy
 * i karta osoby w „Podobnych rekrutacjach” otwierają to samo okno.
 * `modal` trzeba wyrenderować raz, obok przycisku.
 */
export function useCandidateCvPreview(candidateId: number) {
  const [loading, setLoading] = useState(false);
  const [previewDocumentId, setPreviewDocumentId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<CandidateDocument[]>([]);
  const { showError } = useToast();

  const open = async () => {
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

  const modal = (
    <FilePreviewModal
      documents={documents}
      initialDocumentId={previewDocumentId}
      candidateId={candidateId}
      onClose={() => setPreviewDocumentId(null)}
      onDownload={(doc) => downloadDocumentBlob(candidateId, doc).catch(() => {})}
    />
  );

  return { open, loading, modal };
}

/**
 * Kolumna „CV” na liście kandydatów: klik otwiera podgląd CV w oknie
 * (PDF przez pdf.js z wyszukiwaniem, DOCX renderowany), bez pobierania pliku.
 * Okno żyje na poziomie listy (`CandidateCvBrowser`), bo przechodzi między
 * osobami z listy; komórka tylko je otwiera. Klik NIE otwiera podglądu
 * kandydata (stopPropagation). Obejrzane w tej karcie CV ma ✓, godzina
 * w dymku — rekruter po zamknięciu okna wie, kogo już przeglądał.
 */
export function CandidateCvCell({
  candidateName,
  hasCv,
  loading = false,
  seenAt = null,
  onOpen,
}: {
  candidateName: string;
  hasCv: boolean;
  loading?: boolean;
  /** Kiedy ta osoba oglądała to CV w tej karcie (ms). */
  seenAt?: number | null;
  onOpen: () => void;
}) {
  if (!hasCv) {
    return <span className="text-xs text-muted-foreground">brak</span>;
  }

  const seenLabel = seenAt
    ? new Date(seenAt).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })
    : null;

  const openCv = (event: MouseEvent) => {
    event.stopPropagation();
    onOpen();
  };

  return (
    <div onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        onClick={openCv}
        disabled={loading}
        aria-label={`Podgląd CV: ${candidateName}${seenLabel ? ` (oglądane o ${seenLabel})` : ""}`}
        title={seenLabel ? `Oglądałeś to CV dziś o ${seenLabel}` : undefined}
        className={cn(
          "hit-area inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-md border px-2 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-50",
          seenLabel
            ? "border-info/40 bg-info-muted text-info-muted-foreground"
            : "border-border bg-card text-foreground",
        )}
      >
        {loading ? (
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
        ) : seenLabel ? (
          <Check className="h-3 w-3" aria-hidden />
        ) : (
          <FileText className="h-3 w-3" aria-hidden />
        )}
        CV
      </button>
    </div>
  );
}
