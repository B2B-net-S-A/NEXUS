"use client";

/**
 * PdfDocumentViewer — PDF renderowany przez pdf.js w naszym DOM-ie.
 *
 * Zastępuje `<iframe>` z natywną przeglądarką PDF Chrome (09.2026). Tamtej nie
 * da się przeszukać z kodu strony, więc Ctrl+F w podglądzie CV szukał po
 * stronie POD oknem. Tu warstwa tekstu jest nasza, a wyszukiwanie robi
 * `PDFFindController` z pdf.js (ten sam, którego używa Firefox): podświetla
 * wszystkie trafienia, przewija do bieżącego i liczy „3 z 12”, bez wielkości
 * liter i bez polskich znaków.
 *
 * Komponent nie ma własnego paska — stan (strona, powiększenie, wynik
 * wyszukiwania, obecność tekstu) oddaje callbackami, a sterowanie wystawia
 * przez `handleRef`. Pasek składa `SearchablePdfPreview`.
 */

import {
  useEffect,
  useImperativeHandle,
  useRef,
  type Ref,
} from "react";

import { loadPdfJs } from "@/lib/pdfjs-loader";
import { isSearchableQuery } from "@/lib/document-text-search";
import type {
  DocumentFindResult,
  DocumentTextAvailability,
} from "./DocumentSearchBar";
import "./pdf-viewer.css";

export interface PdfViewState {
  page: number;
  pages: number;
  scalePercent: number;
}

export interface PdfViewerHandle {
  /** Nowe zapytanie (puste / za krótkie = zdjęcie podświetleń). */
  search(query: string): void;
  /** Następne / poprzednie trafienie bieżącego zapytania. */
  step(previous: boolean): void;
  zoomIn(): void;
  zoomOut(): void;
  fitWidth(): void;
}

// pdf.js domyślnie ściąga pliki tłumaczeń etykiet ARIA stron z sieci. Nasze
// etykiety nie są nigdzie pokazywane, a zbędne żądanie do nieistniejącej
// ścieżki kończyłoby się 404 w konsoli — podstawiamy pusty słownik.
const SILENT_L10N = {
  getLanguage: () => "pl",
  getDirection: () => "ltr",
  get: async (_ids: unknown, _args?: unknown, fallback?: string) =>
    fallback ?? "",
  translate: async () => undefined,
  translateOnce: async () => undefined,
  destroy: async () => undefined,
  pause: () => undefined,
  resume: () => undefined,
};

type ViewerInternals = {
  eventBus: InstanceType<
    Awaited<ReturnType<typeof loadPdfJs>>["viewer"]["EventBus"]
  >;
  pdfViewer: InstanceType<
    Awaited<ReturnType<typeof loadPdfJs>>["viewer"]["PDFViewer"]
  >;
  pendingState: number;
};

export function PdfDocumentViewer({
  file,
  handleRef,
  onLoaded,
  onError,
  onTextAvailability,
  onFindResult,
  onViewState,
}: {
  file: Blob;
  handleRef?: Ref<PdfViewerHandle>;
  onLoaded?: () => void;
  onError?: () => void;
  onTextAvailability?: (availability: DocumentTextAvailability) => void;
  onFindResult?: (result: DocumentFindResult) => void;
  onViewState?: (state: PdfViewState) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<HTMLDivElement | null>(null);
  const internalsRef = useRef<ViewerInternals | null>(null);
  const queryRef = useRef("");
  // „Dopasuj do szerokości” obowiązuje, dopóki użytkownik sam nie zmieni
  // powiększenia — wtedy zmiana rozmiaru okna nie może mu go nadpisać.
  const fitWidthRef = useRef(true);
  // Najnowsze callbacki bez odtwarzania całej przeglądarki przy każdym renderze.
  const callbacksRef = useRef({
    onLoaded,
    onError,
    onTextAvailability,
    onFindResult,
    onViewState,
  });
  callbacksRef.current = {
    onLoaded,
    onError,
    onTextAvailability,
    onFindResult,
    onViewState,
  };

  useImperativeHandle(
    handleRef,
    () => ({
      search(query: string) {
        queryRef.current = query;
        const internals = internalsRef.current;
        if (!internals) return;
        if (!isSearchableQuery(query)) {
          internals.eventBus.dispatch("findbarclose", { source: null });
          callbacksRef.current.onFindResult?.({
            current: 0,
            total: 0,
            pending: false,
          });
          return;
        }
        dispatchFind(internals, query, { again: false, previous: false });
      },
      step(previous: boolean) {
        const internals = internalsRef.current;
        if (!internals || !isSearchableQuery(queryRef.current)) return;
        dispatchFind(internals, queryRef.current, { again: true, previous });
      },
      zoomIn() {
        fitWidthRef.current = false;
        internalsRef.current?.pdfViewer.increaseScale();
      },
      zoomOut() {
        fitWidthRef.current = false;
        internalsRef.current?.pdfViewer.decreaseScale();
      },
      fitWidth() {
        fitWidthRef.current = true;
        const internals = internalsRef.current;
        if (internals) internals.pdfViewer.currentScaleValue = "page-width";
      },
    }),
    [],
  );

  useEffect(() => {
    const container = containerRef.current;
    const viewerElement = viewerRef.current;
    if (!container || !viewerElement) return;

    let cancelled = false;
    const abort = new AbortController();
    let loadingTask: { destroy: () => Promise<void> } | null = null;
    let pdfViewer: ViewerInternals["pdfViewer"] | null = null;
    let pagesReady = false;
    fitWidthRef.current = true;
    callbacksRef.current.onTextAvailability?.("pending");

    // Szerokość liczona w chwili `pagesinit` bywa zerowa, gdy okno jeszcze się
    // układa (animacja otwarcia dialogu, doczytany CSS) — wtedy pdf.js dawał
    // ujemną skalę i niewidoczne strony. Dopasowujemy ponownie przy każdej
    // realnej zmianie szerokości kontenera.
    let lastWidth = -1;
    const applyFitWidth = () => {
      if (!pdfViewer || !pagesReady || !fitWidthRef.current) return;
      if (container.clientWidth < 80) return;
      pdfViewer.currentScaleValue = "page-width";
    };
    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            if (container.clientWidth === lastWidth) return;
            lastWidth = container.clientWidth;
            applyFitWidth();
          });
    resizeObserver?.observe(container);

    (async () => {
      const { lib, viewer } = await loadPdfJs();
      if (cancelled) return;

      const eventBus = new viewer.EventBus();
      const linkService = new viewer.PDFLinkService({ eventBus });
      const findController = new viewer.PDFFindController({
        eventBus,
        linkService,
      });
      const viewerOptions = {
        container,
        viewer: viewerElement,
        eventBus,
        linkService,
        findController,
        textLayerMode: 1,
        annotationMode: lib.AnnotationMode.DISABLE,
        // Kontrakt typów wymaga pełnej klasy L10n; pdf.js woła wyłącznie
        // metody zdefiniowane w SILENT_L10N.
        l10n: SILENT_L10N as never,
        // Jest w kodzie `PDFViewer` (odpina ResizeObserver i nasłuch
        // przewijania), ale nie w jego typach.
        abortSignal: abort.signal,
      };
      pdfViewer = new viewer.PDFViewer(
        viewerOptions as ConstructorParameters<typeof viewer.PDFViewer>[0],
      );
      linkService.setViewer(pdfViewer);
      const internals: ViewerInternals = {
        eventBus,
        pdfViewer,
        pendingState: viewer.FindState.PENDING,
      };

      const reportView = () => {
        if (!pdfViewer) return;
        callbacksRef.current.onViewState?.({
          page: pdfViewer.currentPageNumber,
          pages: pdfViewer.pagesCount,
          scalePercent: Math.round(pdfViewer.currentScale * 100),
        });
      };
      eventBus.on("pagesinit", () => {
        pagesReady = true;
        applyFitWidth();
        requestAnimationFrame(applyFitWidth);
        reportView();
      });
      eventBus.on("pagechanging", reportView);
      eventBus.on("scalechanging", reportView);
      eventBus.on(
        "updatefindmatchescount",
        ({ matchesCount }: { matchesCount: { current: number; total: number } }) => {
          callbacksRef.current.onFindResult?.({
            current: matchesCount.current,
            total: matchesCount.total,
            pending: false,
          });
        },
      );
      eventBus.on(
        "updatefindcontrolstate",
        ({
          state,
          matchesCount,
        }: {
          state: number;
          matchesCount: { current: number; total: number };
        }) => {
          callbacksRef.current.onFindResult?.({
            current: matchesCount.current,
            total: matchesCount.total,
            pending: state === internals.pendingState,
          });
        },
      );

      const data = new Uint8Array(await file.arrayBuffer());
      if (cancelled) return;
      const task = lib.getDocument({ data });
      loadingTask = task;
      const pdfDocument = await task.promise;
      if (cancelled) return;

      pdfViewer.setDocument(pdfDocument);
      linkService.setDocument(pdfDocument);
      internalsRef.current = internals;
      callbacksRef.current.onLoaded?.();

      // Zapytanie wpisane, zanim dokument się wczytał (np. przełączenie CV
      // strzałką przy aktywnym wyszukiwaniu) — ponawiamy je na nowym pliku.
      if (isSearchableQuery(queryRef.current)) {
        dispatchFind(internals, queryRef.current, {
          again: false,
          previous: false,
        });
      }

      // Skan = strony bez ani jednego znaku w warstwie tekstu. Kończymy na
      // pierwszej stronie z tekstem, żeby nie czytać całego długiego pliku.
      let hasText = false;
      for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber++) {
        const page = await pdfDocument.getPage(pageNumber);
        const content = await page.getTextContent();
        if (cancelled) return;
        if (
          content.items.some(
            (item) => "str" in item && item.str.trim().length > 0,
          )
        ) {
          hasText = true;
          break;
        }
      }
      if (!cancelled) {
        callbacksRef.current.onTextAvailability?.(hasText ? "has_text" : "no_text");
      }
    })().catch(() => {
      if (!cancelled) callbacksRef.current.onError?.();
    });

    return () => {
      cancelled = true;
      internalsRef.current = null;
      resizeObserver?.disconnect();
      abort.abort();
      pdfViewer?.setDocument(null as never);
      void loadingTask?.destroy();
    };
  }, [file]);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 overflow-auto"
      data-testid="pdf-document-viewer"
    >
      <div ref={viewerRef} className="pdfViewer" />
    </div>
  );
}

function dispatchFind(
  internals: ViewerInternals,
  query: string,
  { again, previous }: { again: boolean; previous: boolean },
): void {
  internals.eventBus.dispatch("find", {
    source: null,
    type: again ? "again" : "",
    query: query.trim(),
    caseSensitive: false,
    entireWord: false,
    highlightAll: true,
    findPrevious: previous,
    matchDiacritics: false,
  });
}
