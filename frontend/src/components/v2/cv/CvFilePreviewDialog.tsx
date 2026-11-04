"use client";

/**
 * Podgląd CV do klienta = ten sam plik, który pobiera „Pobierz” (decyzja
 * Artura z 14.10.2026, „Edytor CV 3”). Do tej pory „Podgląd” w karcie i w
 * „Użyj innego CV” pokazywał surowy tekst z edytora w stylu strony aplikacji,
 * a plik Word wyglądał zupełnie inaczej. Plik rysuje `CvEditorWordPreview`
 * (docx-preview, czcionka Montserrat z `globals.css`). Gdy pliku nie da się
 * pokazać, zostaje treść w układzie kartki edytora (`CvPaperHtml`).
 *
 * „Pokaż oryginał” (03.11.2026) stawia oryginalne CV po lewej, a okno rośnie na
 * prawie cały ekran. Domyślnie schowane; raz pokazane zostaje zamontowane, żeby
 * chowanie nie pobierało pliku drugi raz.
 */

import { useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CvEditorSources, type CvEditorSourcesProps } from "@/components/v2/cv-editor/CvEditorSources";
import { CvPagesPreview } from "@/components/v2/cv/CvPagesPreview";
import { CvPaperHtml } from "@/components/v2/cv/CvPaperHtml";
import { keepDialogOpenOnDocumentSearchEscape } from "@/components/v2/files/DocumentSearchBar";
import type { CvAlign } from "@/lib/cv-editor-align";
import { cn } from "@/lib/utils";

export interface CvFilePreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Strony CV (PDF z pliku Word) — bez intencji pobrania. */
  loadPdf: () => Promise<Blob>;
  /** Plik Word CV — zapas, gdy PDF nie powstanie; bez intencji pobrania. */
  load: () => Promise<Blob>;
  /** Treść z edytora na wypadek, gdy pliku nie da się pokazać. */
  fallbackHtml?: string | null;
  language?: "pl" | "en";
  textAlign?: CvAlign;
  /** Etap z kopią oryginału. Bez niego okna nie da się rozszerzyć o oryginał. */
  originalStageId?: number;
  /** Harness: bajty oryginału bez sieci. */
  originalLoaders?: CvEditorSourcesProps["loaders"];
}

export function CvFilePreviewDialog({
  open,
  onOpenChange,
  title,
  loadPdf,
  load,
  fallbackHtml,
  language,
  textAlign,
  originalStageId,
  originalLoaders,
}: CvFilePreviewDialogProps) {
  const [originalShown, setOriginalShown] = useState(false);
  const [originalSeen, setOriginalSeen] = useState(false);
  if (originalShown && !originalSeen) setOriginalSeen(true);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="xl"
        className={cn(
          "flex h-[92dvh] flex-col gap-0 p-0",
          originalShown && "min-[1180px]:w-[96vw] min-[1180px]:max-w-[96vw]",
        )}
        // Esc w „Szukaj w CV” czyści zapytanie, nie zamyka okna.
        onEscapeKeyDown={keepDialogOpenOnDocumentSearchEscape}
      >
        <DialogHeader className="flex-row items-start justify-between gap-3 border-b border-border px-5 py-3 pr-14">
          <div className="min-w-0 space-y-1">
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>Tak zobaczy to klient: ten sam plik co „Pobierz”.</DialogDescription>
          </div>
          {originalStageId != null ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-pressed={originalShown}
              title="Oryginalne CV po lewej, obok CV firmowego"
              // Poniżej 1180 px dwie kolumny się nie mieszczą.
              className="hidden flex-none min-[1180px]:inline-flex"
              onClick={() => setOriginalShown((shown) => !shown)}
            >
              {originalShown ? (
                <PanelLeftClose aria-hidden className="mr-1.5 h-3.5 w-3.5" />
              ) : (
                <PanelLeftOpen aria-hidden className="mr-1.5 h-3.5 w-3.5" />
              )}
              {originalShown ? "Schowaj oryginał" : "Pokaż oryginał"}
            </Button>
          ) : null}
        </DialogHeader>
        <div className="flex min-h-0 flex-1">
          {originalStageId != null && originalSeen ? (
            <aside
              aria-label="Oryginalne CV"
              hidden={!originalShown}
              // Klasa, nie sam atrybut: `min-[1180px]:block` przebiłby `hidden`.
              className={cn(
                "hidden min-h-0 min-w-0 flex-1 border-r border-border bg-card",
                originalShown && "min-[1180px]:block",
              )}
            >
              <CvEditorSources stageId={originalStageId} cvOnly loaders={originalLoaders} />
            </aside>
          ) : null}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-muted/40">
          {open ? (
            <CvPagesPreview
              loadPdf={loadPdf}
              loadDocx={load}
              fallback={
                fallbackHtml ? (
                  <>
                    <p className="px-4 pb-3 text-center text-xs text-muted-foreground">
                      Poniżej treść CV w układzie kartki edytora. Plik może wyglądać nieco inaczej.
                    </p>
                    <CvPaperHtml html={fallbackHtml} language={language} textAlign={textAlign} />
                  </>
                ) : null
              }
            />
          ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
