"use client";

/**
 * CVOriginalPreviewModal — pokazuje snapshot oryginalnego CV per rekrutacja.
 *
 * PR2 — Faza 5. PDF renderujemy inline przez pdf.js z lupą „Szukaj w CV”
 * (`SearchablePdfPreview`, 09.2026 — wcześniej `<iframe>`, w którym Ctrl+F
 * przeszukiwał stronę pod oknem); DOCX/legacy nie ma podglądu, więc
 * pokazujemy tylko przycisk „Pobierz".
 *
 * Auth: endpoint pobrania jest chroniony Bearer JWT (localStorage, NIE cookie),
 * więc surowy URL w `<iframe src>` / `<a href>` 401-uje ("Not authenticated").
 * Pobieramy bajty uwierzytelnionym fetch-em i podajemy same-origin blob URL —
 * patrz `lib/authenticated-files`.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Download, FileText, AlertCircle, Loader2 } from "lucide-react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import {
  downloadAuthenticatedFile,
  fetchAuthenticatedBlob,
} from "@/lib/authenticated-files";
import { keepDialogOpenOnDocumentSearchEscape } from "@/components/v2/files/DocumentSearchBar";
import { SearchablePdfPreview } from "@/components/v2/files/SearchablePdfPreview";
import { candidateStageCvApi, type CVOriginalSnapshot } from "@/lib/api";
import { resolveViewState } from "@/lib/view-state";

/**
 * Trzy różne powody pustego okna, trzy różne zdania (audyt B19). Do 09.2026
 * każdy błąd zapytania czytał się jako „Nie udało się wczytać CV" — także 403
 * (rekrutacja spoza zespołu) i 404 etapu bez wiersza snapshotu, więc rekruter
 * nie wiedział, czy prosić o dostęp, czy sięgnąć po aktualne CV na profilu.
 */
const LOAD_ERROR_COPY: Record<"forbidden" | "not_found" | "error", string> = {
  forbidden:
    "Nie masz dostępu do tej rekrutacji — snapshot CV widzi tylko jej zespół.",
  not_found: "Ten etap rekrutacji nie istnieje albo został usunięty.",
  error: "Nie udało się wczytać CV. Spróbuj ponownie.",
};

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stageId: number;
  jobTitle?: string;
  candidateName: string;
}

function isPdf(filename: string | null | undefined): boolean {
  return Boolean(filename && filename.toLowerCase().endsWith(".pdf"));
}

export function CVOriginalPreviewModal({
  open,
  onOpenChange,
  stageId,
  jobTitle,
  candidateName,
}: Props) {
  const { showError } = useToast();

  const { data, isLoading, error, refetch } = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", stageId],
    queryFn: () => candidateStageCvApi.original.get(stageId).then((r) => r.data),
    enabled: open,
  });
  const loadState = resolveViewState({ isLoading, error });
  const loadFailed =
    loadState === "forbidden" ||
    loadState === "not_found" ||
    loadState === "error";

  const hasSnapshot = Boolean(data?.has_snapshot);
  const filename = data?.original_cv_filename ?? null;
  const isPdfFile = isPdf(filename);
  const showInlinePdf = hasSnapshot && isPdfFile;
  const downloadPath = `/api/candidates/stages/${stageId}/cv/original/download`;

  const [downloading, setDownloading] = useState(false);
  const [pdfBlob, setPdfBlob] = useState<Blob | null>(null);
  const [pdfError, setPdfError] = useState(false);

  // Inline PDF: pobierz bajty z autoryzacją (surowy URL backendu nie wysyła
  // nagłówka Authorization → 401) i oddaj je pdf.js.
  useEffect(() => {
    if (!open || !showInlinePdf) {
      setPdfBlob(null);
      setPdfError(false);
      return;
    }
    let cancelled = false;
    setPdfBlob(null);
    setPdfError(false);

    (async () => {
      try {
        const blob = await fetchAuthenticatedBlob(downloadPath);
        if (!cancelled) setPdfBlob(blob);
      } catch {
        if (!cancelled) setPdfError(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, showInlinePdf, downloadPath]);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await downloadAuthenticatedFile(
        downloadPath,
        filename ?? `cv_stage_${stageId}.pdf`,
      );
    } catch {
      showError("Nie udało się pobrać CV.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="2xl"
        className="p-0 max-h-[92vh] flex flex-col"
        onEscapeKeyDown={keepDialogOpenOnDocumentSearchEscape}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              CV oryginalne (snapshot z momentu zgłoszenia)
            </div>
            <div className="text-sm font-medium text-foreground truncate">
              {candidateName}
              {jobTitle ? (
                <span className="text-muted-foreground font-normal">
                  {" "}
                  — {jobTitle}
                </span>
              ) : null}
            </div>
          </div>
          {hasSnapshot ? (
            <Button
              size="sm"
              variant="outline"
              onClick={handleDownload}
              disabled={downloading}
            >
              {downloading ? (
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5 mr-1.5" />
              )}
              Pobierz
            </Button>
          ) : null}
        </div>

        <div className="flex-1 overflow-auto bg-background">
          {isLoading ? (
            <div className="p-10 text-center text-sm text-muted-foreground">
              Ładowanie…
            </div>
          ) : loadFailed ? (
            <div className="p-10 text-center" role="alert">
              <AlertCircle className="h-8 w-8 text-warning mx-auto mb-3" />
              <div className="text-sm text-muted-foreground">
                {LOAD_ERROR_COPY[loadState]}
              </div>
              {loadState === "error" ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-3"
                  onClick={() => void refetch()}
                >
                  Ponów
                </Button>
              ) : null}
            </div>
          ) : !hasSnapshot ? (
            <div className="p-10 text-center">
              <FileText className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
              <div className="text-sm text-muted-foreground">
                Brak snapshotu CV z momentu zgłoszenia do tej rekrutacji.
              </div>
              {/* Aktualne CV to INNY dokument niż snapshot — nie udajemy, że
                  je tu pokazujemy; przejście jest jawne i prowadzi na profil. */}
              {data?.candidate_id ? (
                <Link
                  href={`/candidates/${data.candidate_id}`}
                  className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
                >
                  Otwórz aktualne CV na profilu kandydata →
                </Link>
              ) : null}
            </div>
          ) : showInlinePdf ? (
            pdfError ? (
              <div className="p-10 text-center">
                <AlertCircle className="h-8 w-8 text-amber-500 mx-auto mb-3" />
                <div className="text-sm text-muted-foreground">
                  Nie udało się wyświetlić podglądu CV.
                </div>
              </div>
            ) : pdfBlob ? (
              <div
                className="relative h-[75vh] w-full"
                aria-label="CV oryginalne"
                role="document"
              >
                <SearchablePdfPreview
                  file={pdfBlob}
                  onError={() => setPdfError(true)}
                  findShortcutScope="dialog"
                />
              </div>
            ) : (
              <div className="p-10 text-center text-sm text-muted-foreground">
                Ładowanie podglądu…
              </div>
            )
          ) : (
            <div className="p-10 text-center">
              <FileText className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
              <div className="text-sm text-muted-foreground mb-3">
                Plik {filename ?? "CV"} nie ma wbudowanego podglądu.
              </div>
              <Button onClick={handleDownload} disabled={downloading}>
                {downloading ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Download className="h-4 w-4 mr-2" />
                )}
                Pobierz
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
