"use client";

/**
 * „Jak u klienta”: prawdziwe strony CV (Edytor CV 3, decyzja J2 Artura,
 * 14.10.2026). Serwer zamienia TEN SAM plik Word, który pobiera „Pobierz Word”,
 * na PDF (LibreOffice z czcionką Montserrat), a tu rysuje go pdf.js — strony
 * A4, numer strony, powiększenie i „Szukaj w CV”, tak samo na każdym
 * komputerze. Gdy PDF nie powstanie (503, brak zgody RODO, brak prawa do
 * szkicu), zostaje dotychczasowy podgląd pliku Word (`CvEditorWordPreview`,
 * z zapasem w układzie kartki).
 */

import { useEffect, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

import { SearchablePdfPreview } from "@/components/v2/files/SearchablePdfPreview";
import { preloadPdfJs } from "@/lib/pdfjs-loader";
import { CvEditorWordPreview } from "@/components/v2/cv-editor/CvEditorWordPreview";

export interface CvPagesPreviewProps {
  /** PDF stron — bez intencji pobrania. */
  loadPdf: () => Promise<Blob>;
  /** Plik Word — zapas, gdy PDF nie powstanie. */
  loadDocx: () => Promise<Blob>;
  /** Zapas zapasu: treść, gdy nie da się pokazać nawet pliku Word. */
  fallback?: ReactNode;
  /**
   * Pudełko stron. Przeglądarka PDF leży w nim absolutnie, więc pudełko musi
   * mieć wysokość: w kolumnie flex wystarcza `flex-1` (domyślnie), w bloku
   * z przewijaniem (kartka edytora) — `absolute inset-0`.
   */
  className?: string;
}

type State = { kind: "loading" } | { kind: "pdf"; blob: Blob } | { kind: "docx" };

export function CvPagesPreview({
  loadPdf,
  loadDocx,
  fallback,
  className = "relative min-h-0 flex-1",
}: CvPagesPreviewProps) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    preloadPdfJs();
    loadPdf().then(
      (blob) => {
        if (!cancelled) setState({ kind: "pdf", blob });
      },
      () => {
        if (!cancelled) setState({ kind: "docx" });
      },
    );
    return () => {
      cancelled = true;
    };
    // Strony rysują się raz na otwarcie; `loadPdf` powstaje przy każdym renderze.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (state.kind === "loading") {
    return (
      <p role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
        <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> Przygotowuję strony CV…
      </p>
    );
  }
  if (state.kind === "docx") {
    return <CvEditorWordPreview load={loadDocx} fallback={fallback} />;
  }
  return (
    <div className={className} data-testid="cv-pages-preview">
      <SearchablePdfPreview
        file={state.blob}
        fit="auto"
        findShortcutScope="dialog"
        onError={() => setState({ kind: "docx" })}
      />
    </div>
  );
}
