"use client";

/**
 * Jedna strona PDF nowego CV obok formularza (22.11.2026): pdf.js rysuje ją
 * na całą wysokość kolumny, a ramka pokazuje edytowany blok — punkty
 * „Dlaczego nasz kandydat” na stronie 1 albo wybrane stanowisko na stronie,
 * na której stoi (szukane po tekście warstwy PDF, `lib/cv-new-preview.ts`).
 *
 * Nowy PDF rysuje się poza ekranem i dopiero gotowy zastępuje stary obraz,
 * więc odświeżenie podglądu nie miga pustą stroną.
 */

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { loadPdfJs } from "@/lib/pdfjs-loader";
import { bestPage, textLines, type PdfBox, type PdfLine, type PdfTextItem } from "@/lib/cv-new-preview";
import { cn } from "@/lib/utils";

type PdfTask = ReturnType<Awaited<ReturnType<typeof loadPdfJs>>["lib"]["getDocument"]>;
type PdfDocument = Awaited<PdfTask["promise"]>;

// Zadanie wczytania per dokument: w pdf.js 6 niszczy się zadanie, nie dokument.
const TASKS = new WeakMap<object, PdfTask>();

function destroyPdf(document: PdfDocument): void {
  void TASKS.get(document)?.destroy();
}

export interface CvPdfPlacement {
  page: number;
  pages: number;
  /** Czy ramka edytowanego bloku stoi na stronie. */
  outlined: boolean;
}

export interface CvPdfPageViewProps {
  blob: Blob;
  /** Strona do pokazania; bez niej — strona z największą liczbą trafień `needles`. */
  page?: number;
  /** Teksty edytowanego bloku (początki punktów, firma, stanowisko). */
  needles: readonly string[];
  onPlaced?: (placement: CvPdfPlacement) => void;
  className?: string;
}

interface Drawn {
  width: number;
  height: number;
  box: { left: number; top: number; width: number; height: number } | null;
}

// Linie tekstu stron per dokument: odświeżony PDF ma własną pamięć.
const LINES = new WeakMap<object, Map<number, PdfLine[]>>();

async function pageLines(pdf: PdfDocument, number: number): Promise<PdfLine[]> {
  let cache = LINES.get(pdf);
  if (!cache) {
    cache = new Map();
    LINES.set(pdf, cache);
  }
  const cached = cache.get(number);
  if (cached) return cached;
  const page = await pdf.getPage(number);
  const content = await page.getTextContent();
  const items: PdfTextItem[] = [];
  for (const item of content.items) {
    if (!("str" in item)) continue;
    items.push({ str: item.str, x: item.transform[4], y: item.transform[5], width: item.width, height: item.height });
  }
  const lines = textLines(items);
  cache.set(number, lines);
  return lines;
}

export function CvPdfPageView({ blob, page, needles, onPlaced, className }: CvPdfPageViewProps) {
  const wrapper = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [pdf, setPdf] = useState<PdfDocument | null>(null);
  const [failed, setFailed] = useState(false);
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  const placedRef = useRef(onPlaced);
  placedRef.current = onPlaced;
  const needleKey = needles.join("\u0000");

  useEffect(() => {
    const node = wrapper.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((current) =>
        current && Math.abs(current.width - width) < 2 && Math.abs(current.height - height) < 2
          ? current
          : { width, height },
      );
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const { lib } = await loadPdfJs();
      const data = new Uint8Array(await blob.arrayBuffer());
      const task = lib.getDocument({ data });
      const document = await task.promise;
      TASKS.set(document, task);
      if (cancelled) {
        destroyPdf(document);
        return;
      }
      setFailed(false);
      setPdf(document);
    })().catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, [blob]);

  // Stary dokument znika dopiero, gdy nowy już stoi (rysowanie starego jest wtedy przerwane).
  useEffect(
    () => () => {
      if (pdf) destroyPdf(pdf);
    },
    [pdf],
  );

  useEffect(() => {
    if (!pdf || !size || size.width < 40 || size.height < 40) return;
    let cancelled = false;
    void (async () => {
      let number = page ?? 1;
      let box: PdfBox | null = null;
      if (page === undefined) {
        const all: PdfLine[][] = [];
        for (let i = 1; i <= pdf.numPages; i += 1) all.push(await pageLines(pdf, i));
        const found = bestPage(all, needles);
        if (found) ({ page: number, box } = found);
      } else if (needles.length) {
        const found = bestPage([await pageLines(pdf, number)], needles);
        box = found?.box ?? null;
      }
      number = Math.min(Math.max(number, 1), pdf.numPages);
      const pdfPage = await pdf.getPage(number);
      const base = pdfPage.getViewport({ scale: 1 });
      const scale = Math.min(size.width / base.width, size.height / base.height);
      const viewport = pdfPage.getViewport({ scale });
      const ratio = typeof window === "undefined" ? 1 : Math.min(window.devicePixelRatio || 1, 2);
      const offscreen = document.createElement("canvas");
      offscreen.width = Math.floor(viewport.width * ratio);
      offscreen.height = Math.floor(viewport.height * ratio);
      await pdfPage.render({ canvas: offscreen, viewport: pdfPage.getViewport({ scale: scale * ratio }) }).promise;
      if (cancelled || !canvas.current) return;
      const target = canvas.current;
      target.width = offscreen.width;
      target.height = offscreen.height;
      target.getContext("2d")?.drawImage(offscreen, 0, 0);
      let rect: Drawn["box"] = null;
      if (box) {
        // Odstęp od tekstu ponad 2 px obramowania; dół linii PDF to linia bazowa,
        // więc pod spodem jest jeszcze miejsce na ogonki liter (g, p, y).
        const pad = 6;
        const descent = 3;
        const [x0, y0] = viewport.convertToViewportPoint(box.x0, box.y0) as [number, number];
        const [x1, y1] = viewport.convertToViewportPoint(box.x1, box.y1) as [number, number];
        const left = Math.max(0, Math.min(x0, x1) - pad);
        const top = Math.max(0, Math.min(y0, y1) - pad);
        const right = Math.min(viewport.width, Math.max(x0, x1) + pad);
        const bottom = Math.min(viewport.height, Math.max(y0, y1) + pad + descent);
        rect = { left, top, width: right - left, height: bottom - top };
      }
      setDrawn({ width: viewport.width, height: viewport.height, box: rect });
      placedRef.current?.({ page: number, pages: pdf.numPages, outlined: rect !== null });
    })().catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => {
      cancelled = true;
    };
    // `needles` porównujemy po treści (`needleKey`), nie po tożsamości tablicy.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdf, size, page, needleKey]);

  return (
    <div ref={wrapper} className={cn("relative flex min-h-0 min-w-0 items-start justify-center", className)}>
      {failed ? (
        <p role="alert" className="p-4 text-sm text-destructive">
          Nie udało się narysować strony PDF.
        </p>
      ) : null}
      {!drawn && !failed ? (
        <p role="status" className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> Rysuję stronę…
        </p>
      ) : null}
      <div
        className="relative bg-card shadow-sm ring-1 ring-border"
        style={drawn ? { width: drawn.width, height: drawn.height } : { width: 0, height: 0 }}
        hidden={!drawn}
      >
        <canvas
          ref={canvas}
          data-testid="cv-new-preview-page"
          className="block h-full w-full"
          aria-label="Podgląd strony CV"
        />
        {drawn?.box ? (
          <div
            aria-hidden
            data-testid="cv-new-preview-outline"
            className="pointer-events-none absolute rounded-md border-2 border-primary"
            style={drawn.box}
          />
        ) : null}
      </div>
    </div>
  );
}
