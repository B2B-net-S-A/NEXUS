"use client";

/**
 * FilePreviewModal — wspólny podgląd pliku kandydata (in-app, bez pobierania).
 *
 * Wydzielone z `CandidateDetailV2` żeby ten sam, sprawdzony podgląd działał też
 * na liście kandydatów (przycisk „CV"). Browser NIE renderuje DOCX inline —
 * `window.open` na blobie DOCX wymusza download (to był zgłoszony bug: przycisk
 * CV pobierał plik zamiast go otwierać). Modal: PDF → natywny viewer w
 * `<iframe>`; DOCX → `docx-preview` (lazy import); obraz → `<img>`; reszta →
 * fallback z przyciskiem pobierania. Wszystko same-origin (blob z proxy-streamu
 * backendu), więc bez problemów CORS z bucketem Hetzner Object Storage.
 */

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Loader2,
  X,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { getAuthenticatedRequestHeaders } from "@/lib/session";
import {
  activateDocumentMatch,
  hasSearchableText,
  highlightDocumentMatches,
} from "@/lib/document-text-search";
import { useDocumentFindShortcut } from "@/lib/use-document-find-shortcut";
import { renderDocxSafely } from "@/lib/docx-preview-safe";
import {
  DocumentSearchBar,
  EMPTY_FIND_RESULT,
  keepDialogOpenOnDocumentSearchEscape,
  type DocumentFindResult,
  type DocumentTextAvailability,
} from "./DocumentSearchBar";
import { SearchablePdfPreview, useDebouncedValue } from "./SearchablePdfPreview";

export interface CandidateDocument {
  id: number;
  filename: string;
  content_type: string | null;
  size_bytes: number | null;
  document_kind: "cv" | "cover_letter" | "certificate" | "other";
  is_primary: boolean;
  uploaded_at: string | null;
  external_source: string | null;
  created_at: string;
}

export function formatFileSize(bytes: number | null): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function fileIcon(_contentType: string | null): ReactNode {
  // Visual hint by mime type.
  return <FileText className="h-4 w-4 text-muted-foreground" />;
}

export type PreviewKind = "pdf" | "docx" | "image" | "unsupported";

// Czy plik da się wyświetlić inline w przeglądarce. PDF/obraz mają natywny
// renderer; DOCX renderujemy przez `docx-preview`. Reszta (legacy .doc binarny,
// xlsx, odt, pages…) — brak inline podglądu → oferujemy pobranie.
export function previewKind(doc: CandidateDocument): PreviewKind {
  const ct = (doc.content_type || "").toLowerCase();
  const name = (doc.filename || "").toLowerCase();
  if (ct === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (
    ct ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    name.endsWith(".docx")
  ) {
    return "docx";
  }
  if (ct.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg|bmp)$/.test(name)) {
    return "image";
  }
  return "unsupported";
}

// Czytelna nazwa formatu zamiast surowego typu MIME („application/pdf”).
// Nieznany format wraca jako rozszerzenie pliku albo `null` — nigdy jako MIME.
export function fileTypeLabel(
  contentType: string | null,
  filename: string | null,
): string | null {
  const ct = (contentType || "").toLowerCase().split(";")[0].trim();
  const name = (filename || "").toLowerCase();
  const ext = name.includes(".") ? name.split(".").pop() || "" : "";
  if (ct === "application/pdf" || ext === "pdf") return "PDF";
  if (
    ct === "application/msword" ||
    ct ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    ext === "doc" ||
    ext === "docx"
  ) {
    return "Dokument Word";
  }
  if (ct === "application/rtf" || ct === "text/rtf" || ext === "rtf") {
    return "Dokument RTF";
  }
  if (ct === "application/vnd.oasis.opendocument.text" || ext === "odt") {
    return "Dokument ODT";
  }
  if (ct.startsWith("image/")) return "Obraz";
  if (ct === "text/plain" || ext === "txt") return "Plik tekstowy";
  if (/^[a-z0-9]{1,5}$/.test(ext)) return `Plik ${ext.toUpperCase()}`;
  return null;
}

// Pobranie bytes dokumentu przez proxy-stream backendu (`/content`). Natywny
// `fetch` (nie axios — axios `responseType: blob` cross-origin zwracał status 0,
// testowane na prod 25.05.2026), Bearer JWT dołączany ręcznie. Same-origin nie
// istnieje (Next.js nie ma rewrite /api/*), więc apiBase = NEXT_PUBLIC_API_URL.
export async function fetchDocumentBlob(
  candidateId: number,
  docId: number,
  disposition: "attachment" | "inline",
): Promise<Blob> {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
  const url = `${apiBase}/api/candidates/${candidateId}/documents/${docId}/content?disposition=${disposition}`;
  const res = await fetch(url, {
    method: "GET",
    headers: getAuthenticatedRequestHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.blob();
}

// Pobranie pliku na dysk (programmatic <a download>). Same-origin blob = działa.
export async function downloadDocumentBlob(
  candidateId: number,
  doc: { id: number; filename?: string | null },
): Promise<void> {
  const blob = await fetchDocumentBlob(candidateId, doc.id, "attachment");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = doc.filename ?? `document-${doc.id}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Body podglądu (bez chromu dialogu): pobiera i renderuje PDF/DOCX/obraz z
// fallbackami loading/error/unsupported. Współdzielone przez `FilePreviewModal`
// (w dialogu) i podglądy inline (np. widok CV w pipelinie). Wypełnia rodzica —
// osadź w kontenerze z wysokością (flex-child z min-h-0 albo box o stałej h).
//
// Nad dokumentem stoi pasek „Szukaj w CV” (09.2026): PDF przeszukuje pdf.js
// (`SearchablePdfPreview`, pasek ma własny), DOCX — `highlightDocumentMatches`
// po wyrenderowanym HTML-u. Ctrl+F trafia w to pole zamiast w wyszukiwarkę przeglądarki
// (`findShortcutScope`: w oknie zawsze, osadzony w stronie — gdy kursor albo
// fokus jest w podglądzie).
export function FilePreviewContent({
  doc,
  candidateId,
  onDownload,
  className,
  hidePdfSidebar: _hidePdfSidebar = false,
  findShortcutScope = "container",
  loadDocumentBlob = fetchDocumentBlob,
}: {
  doc: CandidateDocument | null;
  candidateId: number;
  onDownload: (doc: CandidateDocument) => void;
  className?: string;
  // Historycznie chowało natywny rail miniatur Chrome (`#navpanes=0`). pdf.js
  // nie ma railu i zawsze startuje od „dopasuj do szerokości”, więc flaga nie
  // zmienia już wyglądu — zostaje w API, żeby nie ruszać wywołań.
  hidePdfSidebar?: boolean;
  findShortcutScope?: "dialog" | "container";
  // Źródło bajtów — domyślnie proxy backendu. Harness `/preview/cv-search`
  // podaje pliki statyczne, bo nie może wołać API.
  loadDocumentBlob?: typeof fetchDocumentBlob;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const docxHostRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [pdfBlob, setPdfBlob] = useState<Blob | null>(null);
  const [docxBlob, setDocxBlob] = useState<Blob | null>(null);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 200);
  const [availability, setAvailability] =
    useState<DocumentTextAvailability>("pending");
  const [findResult, setFindResult] =
    useState<DocumentFindResult>(EMPTY_FIND_RESULT);
  const [docxActiveIndex, setDocxActiveIndex] = useState(0);

  const kind = doc ? previewKind(doc) : "unsupported";
  // PDF ma własny pasek w `SearchablePdfPreview`; tu pasek dla DOCX i obrazu
  // (obraz = brak tekstu, pasek mówi to wprost zamiast milczeć na Ctrl+F).
  const hasDomSearchBar = kind === "docx" || kind === "image";
  const searchPlaceholder =
    doc?.document_kind === "cv" ? "Szukaj w CV" : "Szukaj w dokumencie";

  useDocumentFindShortcut({
    enabled: hasDomSearchBar && doc != null,
    scope: findShortcutScope,
    containerRef: rootRef,
    inputRef: searchInputRef,
  });

  // Pobranie contentu po zmianie doc.id.
  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    let createdUrl: string | null = null;
    setStatus("loading");
    setImageUrl(null);
    setPdfBlob(null);
    setDocxBlob(null);
    setFindResult(EMPTY_FIND_RESULT);
    // Obraz nie ma warstwy tekstu z definicji.
    setAvailability(kind === "image" ? "no_text" : "pending");

    if (kind === "unsupported") {
      setStatus("ready");
      return;
    }

    (async () => {
      // Stream contentu z proxy backendu (→ Hetzner Object Storage) bywa
      // przejściowo zawodny (np. 500/reset przy szybkim remountcie podczas
      // przełączania zakładek). Ponawiamy do 3× z krótkim backoffem zanim
      // pokażemy błąd — inline podgląd CV jest centralnym elementem widoku.
      let raw: Blob | null = null;
      for (let attempt = 0; attempt < 3 && !cancelled; attempt++) {
        try {
          raw = await loadDocumentBlob(candidateId, doc.id, "inline");
          break;
        } catch {
          raw = null;
          if (attempt < 2) {
            await new Promise((r) => setTimeout(r, 400 * (attempt + 1)));
          }
        }
      }
      if (cancelled) return;
      if (!raw) {
        setStatus("error");
        return;
      }

      if (kind === "docx") {
        // Render w osobnym efekcie — potrzebuje kontenera DOM.
        setDocxBlob(raw);
      } else if (kind === "pdf") {
        // Render i `status: ready` po stronie `SearchablePdfPreview`.
        setPdfBlob(raw);
      } else {
        // Obraz — wymuszamy poprawny MIME (Blob default octet-stream
        // wymusiłby download zamiast inline renderu).
        const typed = doc.content_type
          ? new Blob([raw], { type: doc.content_type })
          : raw;
        createdUrl = URL.createObjectURL(typed);
        setImageUrl(createdUrl);
        setStatus("ready");
      }
    })();

    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [doc, candidateId, kind, loadDocumentBlob]);

  // DOCX render — gdy blob gotowy i host w DOM. docx-preview lazy import,
  // żeby nie obciążać głównego bundla (ładowany tylko przy podglądzie DOCX).
  useEffect(() => {
    if (kind !== "docx" || !docxBlob) return;
    if (!docxHostRef.current) return;
    let cancelled = false;

    (async () => {
      try {
        const host = docxHostRef.current;
        if (cancelled || !host) return;
        host.innerHTML = "";
        await renderDocxSafely(docxBlob, host, {
          className: "docx",
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          breakPages: true,
          useBase64URL: true,
        });
        if (cancelled) return;
        setAvailability(hasSearchableText(host) ? "has_text" : "no_text");
        setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [kind, docxBlob]);

  // DOCX: podświetlenie po wyrenderowaniu i przy każdej zmianie zapytania.
  useEffect(() => {
    if (kind !== "docx" || status !== "ready") return;
    const host = docxHostRef.current;
    if (!host) return;
    const total = highlightDocumentMatches(host, debouncedQuery);
    setDocxActiveIndex(0);
    if (total > 0) activateDocumentMatch(host, 0);
    setFindResult({ current: total > 0 ? 1 : 0, total, pending: false });
  }, [kind, status, debouncedQuery, docxBlob]);

  const stepMatch = (previous: boolean) => {
    const host = docxHostRef.current;
    if (kind !== "docx" || !host || findResult.total === 0) return;
    const total = findResult.total;
    const next = (docxActiveIndex + (previous ? total - 1 : 1)) % total;
    setDocxActiveIndex(next);
    activateDocumentMatch(host, next);
    setFindResult({ current: next + 1, total, pending: false });
  };

  if (!doc) return null;

  return (
    <div
      ref={rootRef}
      className={cn("relative flex flex-col overflow-hidden bg-muted/40", className)}
    >
      {hasDomSearchBar && status !== "error" ? (
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-card px-3 py-1.5">
          <DocumentSearchBar
            query={query}
            onQueryChange={setQuery}
            availability={availability}
            result={
              query === debouncedQuery
                ? findResult
                : { ...findResult, pending: true }
            }
            onNext={() => stepMatch(false)}
            onPrevious={() => stepMatch(true)}
            inputRef={searchInputRef}
            placeholder={searchPlaceholder}
            className="min-w-0 flex-1"
          />
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1 overflow-auto">
        {status === "loading" && (
          <div className="absolute inset-0 z-10 flex items-center justify-center">
            <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Ładowanie podglądu…
            </span>
          </div>
        )}

        {status === "error" && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 p-6 text-center">
            <AlertTriangle className="h-8 w-8 text-[hsl(var(--accent-error))]" />
            <p className="text-sm text-muted-foreground">
              Nie udało się wyświetlić podglądu tego pliku.
            </p>
            <button
              type="button"
              onClick={() => onDownload(doc)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm hover:bg-background/60"
            >
              <Download className="h-4 w-4" />
              Pobierz plik
            </button>
          </div>
        )}

        {kind === "pdf" && pdfBlob && status !== "error" && (
          <SearchablePdfPreview
            file={pdfBlob}
            onLoaded={() => setStatus("ready")}
            onError={() => setStatus("error")}
            findShortcutScope={findShortcutScope}
            placeholder={searchPlaceholder}
            query={query}
            onQueryChange={setQuery}
          />
        )}

        {kind === "image" && imageUrl && (
          <div className="flex h-full w-full items-center justify-center p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={imageUrl}
              alt={doc.filename ?? "Podgląd"}
              className="max-h-full max-w-full object-contain"
            />
          </div>
        )}

        {kind === "docx" && (
          <div ref={docxHostRef} className="docx-preview-host w-full" />
        )}

        {kind === "unsupported" && status !== "loading" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            <FileText className="h-8 w-8 text-muted-foreground" />
            <p className="max-w-sm text-sm text-muted-foreground">
              Podgląd nie jest dostępny dla tego formatu
              {fileTypeLabel(doc.content_type, doc.filename)
                ? ` (${fileTypeLabel(doc.content_type, doc.filename)})`
                : ""}. Pobierz plik, aby
              go otworzyć.
            </p>
            <button
              type="button"
              onClick={() => onDownload(doc)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm hover:bg-background/60"
            >
              <Download className="h-4 w-4" />
              Pobierz plik
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// Podgląd pliku in-app (modal). PDF → pdf.js (z wyszukiwaniem); DOCX →
// `docx-preview` (lazy import); obraz → <img>; reszta → fallback z pobraniem.
// Body wydzielone do `FilePreviewContent`, by ten sam podgląd działał inline.
export function FilePreviewModal({
  doc,
  documents,
  initialDocumentId,
  candidateId,
  onClose,
  onDownload,
  loadDocumentBlob,
}: {
  doc?: CandidateDocument | null;
  documents?: CandidateDocument[];
  initialDocumentId?: number | null;
  candidateId: number;
  onClose: () => void;
  onDownload: (doc: CandidateDocument) => void;
  loadDocumentBlob?: typeof fetchDocumentBlob;
}) {
  const gallery = useMemo(() => {
    if (documents?.length) {
      return [...documents].sort((left, right) => {
        if (left.is_primary !== right.is_primary) return left.is_primary ? -1 : 1;
        const leftDate = left.uploaded_at ?? left.created_at;
        const rightDate = right.uploaded_at ?? right.created_at;
        return rightDate.localeCompare(leftDate);
      });
    }
    return doc ? [doc] : [];
  }, [doc, documents]);
  const [activeIndex, setActiveIndex] = useState(0);
  const galleryLabel = gallery.every(
    (candidateDocument) => candidateDocument.document_kind === "cv",
  )
    ? "CV"
    : "Dokument";
  const open =
    gallery.length > 0 &&
    (documents ? initialDocumentId != null : doc != null);

  useEffect(() => {
    if (!open) {
      setActiveIndex(0);
      return;
    }
    const requestedId = initialDocumentId ?? doc?.id;
    const requestedIndex = requestedId
      ? gallery.findIndex((candidateDoc) => candidateDoc.id === requestedId)
      : -1;
    setActiveIndex(requestedIndex >= 0 ? requestedIndex : 0);
  }, [doc?.id, gallery, initialDocumentId, open]);

  useEffect(() => {
    if (!open || gallery.length <= 1) return;
    const onKeyDown = (event: KeyboardEvent) => {
      // Strzałki w polu „Szukaj w CV” przesuwają kursor w tekście.
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA")
      ) {
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setActiveIndex((index) => Math.max(0, index - 1));
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        setActiveIndex((index) => Math.min(gallery.length - 1, index + 1));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [gallery.length, open]);

  const activeDocument = gallery[activeIndex] ?? null;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent
        size="full"
        className="h-[92vh] p-0 gap-0"
        hideClose
        onEscapeKeyDown={keepDialogOpenOnDocumentSearchEscape}
      >
        <DialogHeader className="flex-row items-center justify-between gap-3 py-3 pr-3">
          <div className="min-w-0">
            <DialogTitle className="truncate text-base font-semibold">
              {activeDocument?.filename ?? "Podgląd CV"}
            </DialogTitle>
            <p
              className="mt-0.5 text-xs tabular-nums text-muted-foreground"
              aria-live="polite"
            >
              {galleryLabel} {activeIndex + 1} z {gallery.length}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <div
              className="inline-flex items-center rounded-md border border-border"
              aria-label="Nawigacja między dokumentami CV"
            >
              <button
                type="button"
                onClick={() => setActiveIndex((index) => Math.max(0, index - 1))}
                disabled={activeIndex === 0}
                className="rounded-l-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Poprzednie CV"
                aria-keyshortcuts="ArrowLeft"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() =>
                  setActiveIndex((index) =>
                    Math.min(gallery.length - 1, index + 1),
                  )
                }
                disabled={activeIndex >= gallery.length - 1}
                className="rounded-r-md border-l border-border p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Następne CV"
                aria-keyshortcuts="ArrowRight"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            {activeDocument && (
              <button
                type="button"
                onClick={() => onDownload(activeDocument)}
                className="inline-flex items-center gap-1 text-sm text-[hsl(var(--accent-primary))] hover:underline"
                title="Pobierz plik na dysk"
              >
                <Download className="h-3.5 w-3.5" />
                Pobierz
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-foreground"
              aria-label="Zamknij podgląd dokumentu"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </DialogHeader>

        <FilePreviewContent
          doc={activeDocument}
          candidateId={candidateId}
          onDownload={onDownload}
          className="flex-1 min-h-0"
          findShortcutScope="dialog"
          loadDocumentBlob={loadDocumentBlob}
        />
      </DialogContent>
    </Dialog>
  );
}
