/**
 * Leniwe ładowanie pdf.js (biblioteka + komponenty przeglądarki).
 *
 * Do 09.2026 PDF-y szły do natywnej przeglądarki Chrome w `<iframe>`, do której
 * wnętrza kod strony nie ma dostępu — Ctrl+F przeszukiwał wtedy stronę POD
 * oknem podglądu, a nie CV. pdf.js renderuje stronę + warstwę tekstu w naszym
 * DOM-ie, więc wyszukiwanie i podświetlanie trafień są w naszych rękach.
 *
 * Trzy rzeczy są tu load-bearing:
 * - `pdf_viewer.mjs` czyta `globalThis.pdfjsLib` PRZY EWALUACJI modułu, więc
 *   biblioteka musi być podpięta pod `globalThis` zanim zaimportujemy viewer.
 * - Worker powstaje RAZ i jest współdzielony (`workerPort`): `new Worker(new
 *   URL(…), {type:"module"})` to wzorzec, który webpack rozpoznaje i bundluje
 *   jako osobny chunk (ten sam co w `pdfjs-dist/webpack.mjs`).
 * - Wszystko jest ładowane dopiero przy otwarciu PDF-a — ~1 MB, którego żaden
 *   inny ekran nie potrzebuje.
 */

type PdfJsLib = typeof import("pdfjs-dist");
type PdfJsViewer = typeof import("pdfjs-dist/web/pdf_viewer.mjs");

export interface PdfJsModules {
  lib: PdfJsLib;
  viewer: PdfJsViewer;
}

let modulesPromise: Promise<PdfJsModules> | null = null;

export function loadPdfJs(): Promise<PdfJsModules> {
  if (!modulesPromise) {
    modulesPromise = (async () => {
      const lib = await import("pdfjs-dist");
      if (!lib.GlobalWorkerOptions.workerPort) {
        lib.GlobalWorkerOptions.workerPort = new Worker(
          new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url),
          { type: "module" },
        );
      }
      (globalThis as unknown as { pdfjsLib: PdfJsLib }).pdfjsLib = lib;
      const viewer = await import("pdfjs-dist/web/pdf_viewer.mjs");
      return { lib, viewer };
    })().catch((error: unknown) => {
      // Nieudany import (np. zerwane łącze przy pobieraniu chunka) nie może
      // zablokować kolejnych prób do przeładowania strony.
      modulesPromise = null;
      throw error;
    });
  }
  return modulesPromise;
}
