"use client";

/**
 * SearchablePdfPreview — PDF z paskiem „Szukaj w CV” i sterowaniem stroną /
 * powiększeniem. Jeden komponent dla wszystkich podglądów PDF-a w aplikacji
 * (`FilePreviewContent` dla dokumentów kandydata, `CVOriginalPreviewModal` dla
 * snapshotu CV w rekrutacji), żeby lupa wszędzie działała tak samo.
 *
 * Wypełnia rodzica (`absolute inset-0`) — rodzic musi mieć `position: relative`
 * i wysokość.
 */

import { useEffect, useRef, useState, type RefObject } from "react";
import { MoveHorizontal, ZoomIn, ZoomOut } from "lucide-react";

import { cn } from "@/lib/utils";
import { useDocumentFindShortcut } from "@/lib/use-document-find-shortcut";
import {
  DocumentSearchBar,
  EMPTY_FIND_RESULT,
  type DocumentFindResult,
  type DocumentTextAvailability,
} from "./DocumentSearchBar";
import {
  PdfDocumentViewer,
  type PdfViewState,
  type PdfViewerHandle,
} from "./PdfDocumentViewer";

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export function SearchablePdfPreview({
  file,
  onLoaded,
  onError,
  findShortcutScope = "container",
  placeholder = "Szukaj w CV",
  className,
  query: controlledQuery,
  onQueryChange,
}: {
  file: Blob;
  onLoaded?: () => void;
  onError?: () => void;
  findShortcutScope?: "dialog" | "container";
  placeholder?: string;
  className?: string;
  // Opcjonalnie kontrolowane z zewnątrz — galeria CV trzyma zapytanie przy
  // przejściu PDF → DOCX, gdzie ten komponent się odmontowuje.
  query?: string;
  onQueryChange?: (query: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const handleRef = useRef<PdfViewerHandle | null>(null);
  const [ownQuery, setOwnQuery] = useState("");
  const query = controlledQuery ?? ownQuery;
  const setQuery = onQueryChange ?? setOwnQuery;
  const debouncedQuery = useDebouncedValue(query, 200);
  const [availability, setAvailability] =
    useState<DocumentTextAvailability>("pending");
  const [result, setResult] = useState<DocumentFindResult>(EMPTY_FIND_RESULT);
  const [view, setView] = useState<PdfViewState | null>(null);

  useDocumentFindShortcut({
    enabled: true,
    scope: findShortcutScope,
    containerRef: rootRef,
    inputRef,
  });

  // Nowy plik (np. strzałka „następne CV”) — licznik i strona od zera;
  // wpisane zapytanie zostaje i viewer ponawia je po wczytaniu pliku.
  useEffect(() => {
    setResult(EMPTY_FIND_RESULT);
    setView(null);
  }, [file]);

  useEffect(() => {
    handleRef.current?.search(debouncedQuery);
  }, [debouncedQuery, file]);

  return (
    <div
      ref={rootRef}
      className={cn("absolute inset-0 flex flex-col", className)}
    >
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-card px-3 py-1.5">
        <DocumentSearchBar
          query={query}
          onQueryChange={setQuery}
          availability={availability}
          result={query === debouncedQuery ? result : { ...result, pending: true }}
          onNext={() => handleRef.current?.step(false)}
          onPrevious={() => handleRef.current?.step(true)}
          inputRef={inputRef}
          placeholder={placeholder}
          className="min-w-0 flex-1"
        />
        {view ? <PdfViewControls view={view} handleRef={handleRef} /> : null}
      </div>
      <div className="relative min-h-0 flex-1">
        <PdfDocumentViewer
          file={file}
          handleRef={handleRef}
          onLoaded={onLoaded}
          onError={onError}
          onTextAvailability={setAvailability}
          onFindResult={setResult}
          onViewState={setView}
        />
      </div>
    </div>
  );
}

// Strona i powiększenie — zastępują pasek natywnej przeglądarki PDF Chrome.
export function PdfViewControls({
  view,
  handleRef,
}: {
  view: PdfViewState;
  handleRef: RefObject<PdfViewerHandle | null>;
}) {
  const buttonClass =
    "rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground";
  return (
    <div className="flex shrink-0 items-center gap-2 text-xs tabular-nums text-muted-foreground">
      <span>
        Strona {view.page} / {view.pages}
      </span>
      <div className="inline-flex items-center gap-0.5 rounded-md border border-border px-0.5">
        <button
          type="button"
          onClick={() => handleRef.current?.zoomOut()}
          className={buttonClass}
          aria-label="Pomniejsz"
        >
          <ZoomOut className="h-3.5 w-3.5" />
        </button>
        <span className="min-w-[4ch] text-center">{view.scalePercent}%</span>
        <button
          type="button"
          onClick={() => handleRef.current?.zoomIn()}
          className={buttonClass}
          aria-label="Powiększ"
        >
          <ZoomIn className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => handleRef.current?.fitWidth()}
          className={cn(buttonClass, "border-l border-border")}
          aria-label="Dopasuj do szerokości"
          title="Dopasuj do szerokości"
        >
          <MoveHorizontal className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
