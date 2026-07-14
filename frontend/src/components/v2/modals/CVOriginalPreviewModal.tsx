"use client";

/**
 * CVOriginalPreviewModal — pokazuje snapshot oryginalnego CV per rekrutacja.
 *
 * PR2 — Faza 5. PDF renderujemy inline w <iframe>; DOCX/legacy nie ma natywnego
 * viewera, więc pokazujemy tylko przycisk „Pobierz".
 *
 * Auth: endpoint pobrania jest chroniony Bearer JWT (localStorage, NIE cookie),
 * więc surowy URL w `<iframe src>` / `<a href>` 401-uje ("Not authenticated").
 * Pobieramy bajty uwierzytelnionym fetch-em i podajemy same-origin blob URL —
 * patrz `lib/authenticated-files`.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileText, AlertCircle, Loader2 } from "lucide-react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import {
  downloadAuthenticatedFile,
  fetchAuthenticatedObjectUrl,
} from "@/lib/authenticated-files";
import { candidateStageCvApi, type CVOriginalSnapshot } from "@/lib/api";

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

  const { data, isLoading, error } = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", stageId],
    queryFn: () => candidateStageCvApi.original.get(stageId).then((r) => r.data),
    enabled: open,
  });

  const hasSnapshot = Boolean(data?.has_snapshot);
  const filename = data?.original_cv_filename ?? null;
  const isPdfFile = isPdf(filename);
  const showInlinePdf = hasSnapshot && isPdfFile;
  const downloadPath = `/api/candidates/stages/${stageId}/cv/original/download`;

  const [downloading, setDownloading] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState(false);

  // Inline PDF: pobierz bajty z autoryzacją → same-origin blob URL dla <iframe>.
  // Surowy URL backendu w iframe nie wysyła nagłówka Authorization → 401.
  useEffect(() => {
    if (!open || !showInlinePdf) {
      setPdfUrl(null);
      setPdfError(false);
      return;
    }
    let cancelled = false;
    let createdUrl: string | null = null;
    setPdfUrl(null);
    setPdfError(false);

    (async () => {
      try {
        const url = await fetchAuthenticatedObjectUrl(
          downloadPath,
          "application/pdf",
        );
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        createdUrl = url;
        setPdfUrl(url);
      } catch {
        if (!cancelled) setPdfError(true);
      }
    })();

    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
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
      <DialogContent size="2xl" className="p-0 max-h-[92vh] flex flex-col">
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
          ) : error ? (
            <div className="p-10 text-center">
              <AlertCircle className="h-8 w-8 text-amber-500 mx-auto mb-3" />
              <div className="text-sm text-muted-foreground">
                Nie udało się wczytać CV.
              </div>
            </div>
          ) : !hasSnapshot ? (
            <div className="p-10 text-center">
              <FileText className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
              <div className="text-sm text-muted-foreground">
                Kandydat nie miał CV w momencie zgłoszenia do tej rekrutacji.
              </div>
            </div>
          ) : showInlinePdf ? (
            pdfError ? (
              <div className="p-10 text-center">
                <AlertCircle className="h-8 w-8 text-amber-500 mx-auto mb-3" />
                <div className="text-sm text-muted-foreground">
                  Nie udało się wyświetlić podglądu CV.
                </div>
              </div>
            ) : pdfUrl ? (
              <iframe
                title="CV oryginalne"
                src={pdfUrl}
                className="w-full h-[75vh] border-0"
              />
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
