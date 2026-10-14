"use client";

/**
 * Podgląd CV do klienta = ten sam plik, który pobiera „Pobierz” (decyzja
 * Artura z 14.10.2026, „Edytor CV 3”). Do tej pory „Podgląd” w karcie i w
 * „Użyj innego CV” pokazywał surowy tekst z edytora w stylu strony aplikacji,
 * a plik Word wyglądał zupełnie inaczej. Plik rysuje `CvEditorWordPreview`
 * (docx-preview, czcionka Montserrat z `globals.css`). Gdy pliku nie da się
 * pokazać, zostaje treść w układzie kartki edytora (`CvPaperHtml`).
 */

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CvPaperHtml } from "@/components/v2/cv/CvPaperHtml";
import { CvEditorWordPreview } from "@/components/v2/cv-editor/CvEditorWordPreview";
import type { CvAlign } from "@/lib/cv-editor-align";

export interface CvFilePreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Plik Word CV — bez intencji pobrania (podgląd nie jest pobraniem). */
  load: () => Promise<Blob>;
  /** Treść z edytora na wypadek, gdy pliku nie da się pokazać. */
  fallbackHtml?: string | null;
  language?: "pl" | "en";
  textAlign?: CvAlign;
}

export function CvFilePreviewDialog({
  open,
  onOpenChange,
  title,
  load,
  fallbackHtml,
  language,
  textAlign,
}: CvFilePreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl" className="flex h-[92dvh] flex-col gap-0 p-0">
        <DialogHeader className="border-b border-border px-5 py-3">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>Tak zobaczy to klient: ten sam plik co „Pobierz”.</DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col bg-muted/40">
          {open ? (
            <CvEditorWordPreview
              load={load}
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
      </DialogContent>
    </Dialog>
  );
}
