"use client";

/**
 * CVOriginalPreviewModal — pokazuje snapshot oryginalnego CV per rekrutacja.
 *
 * PR2 — Faza 5. PDF render w iframe (z download URL kontrolowanym przez auth
 * cookie). Dla DOCX brak natywnego viewera, więc pokazujemy tylko link
 * "Pobierz".
 */

import { useQuery } from "@tanstack/react-query";
import { Download, FileText, AlertCircle } from "lucide-react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  candidateStageCvApi,
  type CVOriginalSnapshot,
} from "@/lib/api";

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
  const { data, isLoading, error } = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", stageId],
    queryFn: () => candidateStageCvApi.original.get(stageId).then((r) => r.data),
    enabled: open,
  });

  const downloadUrl = data?.has_snapshot
    ? candidateStageCvApi.original.downloadUrl(stageId)
    : null;
  const filename = data?.original_cv_filename ?? null;
  const showInlinePdf = isPdf(filename) && downloadUrl;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" className="p-0 max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-[hsl(var(--border-subtle))]">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wider text-[hsl(var(--text-muted))]">
              CV oryginalne (snapshot z momentu zgłoszenia)
            </div>
            <div className="text-sm font-medium text-[hsl(var(--text-title))] truncate">
              {candidateName}
              {jobTitle ? (
                <span className="text-[hsl(var(--text-muted))] font-normal">
                  {" "}
                  — {jobTitle}
                </span>
              ) : null}
            </div>
          </div>
          {downloadUrl ? (
            <Button asChild size="sm" variant="outline">
              <a href={downloadUrl} target="_blank" rel="noopener noreferrer">
                <Download className="h-3.5 w-3.5 mr-1.5" />
                Pobierz
              </a>
            </Button>
          ) : null}
        </div>

        <div className="flex-1 overflow-auto bg-[hsl(var(--bg-canvas))]">
          {isLoading ? (
            <div className="p-10 text-center text-sm text-[hsl(var(--text-muted))]">
              Ładowanie…
            </div>
          ) : error ? (
            <div className="p-10 text-center">
              <AlertCircle className="h-8 w-8 text-amber-500 mx-auto mb-3" />
              <div className="text-sm text-[hsl(var(--text-muted))]">
                Nie udało się wczytać CV.
              </div>
            </div>
          ) : !data?.has_snapshot ? (
            <div className="p-10 text-center">
              <FileText className="h-8 w-8 text-[hsl(var(--text-muted))] mx-auto mb-3" />
              <div className="text-sm text-[hsl(var(--text-muted))]">
                Kandydat nie miał CV w momencie zgłoszenia do tej rekrutacji.
              </div>
            </div>
          ) : showInlinePdf ? (
            <iframe
              title="CV oryginalne"
              src={downloadUrl}
              className="w-full h-[75vh] border-0"
            />
          ) : (
            <div className="p-10 text-center">
              <FileText className="h-8 w-8 text-[hsl(var(--text-muted))] mx-auto mb-3" />
              <div className="text-sm text-[hsl(var(--text-muted))] mb-3">
                Plik {filename ?? "CV"} nie ma wbudowanego podglądu.
              </div>
              {downloadUrl ? (
                <Button asChild>
                  <a
                    href={downloadUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <Download className="h-4 w-4 mr-2" />
                    Pobierz
                  </a>
                </Button>
              ) : null}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
