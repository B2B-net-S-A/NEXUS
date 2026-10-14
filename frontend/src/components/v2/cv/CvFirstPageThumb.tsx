"use client";

/**
 * Miniatura pierwszej strony CV do klienta (Edytor CV 3, „Ekran 5”,
 * 14.10.2026). Karta „CV do klienta” pokazuje prawdziwą pierwszą stronę pliku,
 * który dostanie klient (PDF z pliku Word, jak w „Podglądzie”), a klik otwiera
 * okno ze wszystkimi stronami.
 *
 * Miniatura jest ozdobą: PDF pobieramy dopiero, gdy miniatura jest na ekranie
 * (zamiana na serwerze kosztuje ok. 2 s procesora), pdf.js ładujemy leniwie
 * przez `pdfjs-loader` (poza chunkiem karty), a każda awaria — 503, 409 bez
 * zgody RODO, błąd pdf.js — daje neutralną ikonę pliku, bez komunikatu.
 */

import { useEffect, useRef, useState } from "react";
import { FileText } from "lucide-react";

import { loadPdfJs } from "@/lib/pdfjs-loader";
import { cn } from "@/lib/utils";

export interface CvFirstPageThumbProps {
  /** PDF stron CV — bez intencji pobrania. */
  load: () => Promise<Blob>;
  /** Klik w miniaturę — okno ze wszystkimi stronami. */
  onOpen: () => void;
  /** Liczba stron, gdy PDF się wczytał. */
  onPages?: (count: number) => void;
  /** Nazwa przycisku dla czytnika ekranu. */
  label?: string;
  className?: string;
}

/** Szerokość miniatury w px CSS; wysokość z proporcji A4 (297 × 210 mm). */
export const CV_THUMB_WIDTH = 120;
const CV_THUMB_HEIGHT = Math.round((CV_THUMB_WIDTH * 297) / 210);

type ThumbState = "pending" | "ready" | "failed";

/** `true`, gdy element pierwszy raz trafi na ekran (bez obserwatora — od razu). */
function useSeenOnce(ref: React.RefObject<HTMLElement | null>): boolean {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        setSeen(true);
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return seen;
}

export function CvFirstPageThumb({
  load,
  onOpen,
  onPages,
  label = "Otwórz strony CV",
  className,
}: CvFirstPageThumbProps) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<ThumbState>("pending");
  const seen = useSeenOnce(buttonRef);
  // Najnowsze funkcje z propsów bez ponownego rysowania przy każdym renderze.
  const callbacksRef = useRef({ load, onPages });
  callbacksRef.current = { load, onPages };

  useEffect(() => {
    if (!seen) return;
    let cancelled = false;
    let documentTask: { destroy: () => Promise<void> } | null = null;
    let renderTask: { cancel: () => void } | null = null;

    (async () => {
      // Najpierw plik: bez PDF-u (409, 503) nie ma po co ładować pdf.js.
      const blob = await callbacksRef.current.load();
      if (cancelled) return;
      const { lib } = await loadPdfJs();
      if (cancelled) return;
      const data = new Uint8Array(await blob.arrayBuffer());
      if (cancelled) return;
      const task = lib.getDocument({ data });
      documentTask = task;
      const pdf = await task.promise;
      if (cancelled) return;
      callbacksRef.current.onPages?.(pdf.numPages);
      const page = await pdf.getPage(1);
      const canvas = canvasRef.current;
      if (cancelled || !canvas) return;
      // Ostro na ekranach o gęstości 2× — płótno w pikselach urządzenia.
      const pixelRatio = window.devicePixelRatio || 1;
      const scale = (CV_THUMB_WIDTH * pixelRatio) / page.getViewport({ scale: 1 }).width;
      const viewport = page.getViewport({ scale });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      const job = page.render({ canvas, viewport, annotationMode: lib.AnnotationMode.DISABLE });
      renderTask = job;
      await job.promise;
      if (!cancelled) setState("ready");
    })().catch(() => {
      if (!cancelled) setState("failed");
    });

    return () => {
      cancelled = true;
      renderTask?.cancel();
      void documentTask?.destroy();
    };
  }, [seen]);

  return (
    <button
      ref={buttonRef}
      type="button"
      aria-label={label}
      title={label}
      onClick={onOpen}
      data-testid="cv-first-page-thumb"
      data-state={state}
      style={{ width: CV_THUMB_WIDTH, height: CV_THUMB_HEIGHT }}
      className={cn(
        "relative block shrink-0 overflow-hidden rounded-sm border border-border bg-card shadow-sm transition-shadow",
        "hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      {/* Płótno stoi od początku — pdf.js rysuje do istniejącego elementu. */}
      <canvas
        ref={canvasRef}
        aria-hidden
        className={cn("block h-full w-full object-contain", state !== "ready" && "invisible")}
      />
      {state === "pending" ? (
        <span aria-hidden className="absolute inset-0 animate-pulse bg-muted/60" />
      ) : null}
      {state === "failed" ? (
        <span
          aria-hidden
          data-testid="cv-first-page-placeholder"
          className="absolute inset-0 flex items-center justify-center bg-muted/40 text-muted-foreground"
        >
          <FileText className="h-8 w-8" />
        </span>
      ) : null}
    </button>
  );
}
