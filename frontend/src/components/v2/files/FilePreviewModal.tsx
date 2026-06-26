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

import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Download, FileText, Loader2, X } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface CandidateDocument {
  id: number;
  filename: string;
  content_type: string | null;
  size_bytes: number | null;
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
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const url = `${apiBase}/api/candidates/${candidateId}/documents/${docId}/content?disposition=${disposition}`;
  const res = await fetch(url, {
    method: "GET",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
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
export function FilePreviewContent({
  doc,
  candidateId,
  onDownload,
  className,
}: {
  doc: CandidateDocument | null;
  candidateId: number;
  onDownload: (doc: CandidateDocument) => void;
  className?: string;
}) {
  const docxHostRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [docxBlob, setDocxBlob] = useState<Blob | null>(null);

  const kind = doc ? previewKind(doc) : "unsupported";

  // Pobranie contentu po zmianie doc.id.
  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    let createdUrl: string | null = null;
    setStatus("loading");
    setBlobUrl(null);
    setDocxBlob(null);

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
          raw = await fetchDocumentBlob(candidateId, doc.id, "inline");
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
      } else {
        // PDF / obraz — wymuszamy poprawny MIME (Blob default octet-stream
        // wymusiłby download zamiast inline renderu).
        const typed = doc.content_type
          ? new Blob([raw], { type: doc.content_type })
          : raw;
        createdUrl = URL.createObjectURL(typed);
        setBlobUrl(createdUrl);
        setStatus("ready");
      }
    })();

    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [doc, candidateId, kind]);

  // DOCX render — gdy blob gotowy i host w DOM. docx-preview lazy import,
  // żeby nie obciążać głównego bundla (ładowany tylko przy podglądzie DOCX).
  useEffect(() => {
    if (kind !== "docx" || !docxBlob) return;
    if (!docxHostRef.current) return;
    let cancelled = false;

    (async () => {
      try {
        const { renderAsync } = await import("docx-preview");
        const host = docxHostRef.current;
        if (cancelled || !host) return;
        host.innerHTML = "";
        await renderAsync(docxBlob, host, undefined, {
          className: "docx",
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          breakPages: true,
          useBase64URL: true,
        });
        if (!cancelled) setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [kind, docxBlob]);

  if (!doc) return null;

  return (
    <div className={cn("relative overflow-auto bg-muted/40", className)}>
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

      {kind === "pdf" && blobUrl && (
        <iframe
          src={blobUrl}
          title={doc.filename ?? "PDF"}
          className="h-full w-full border-0"
        />
      )}

      {kind === "image" && blobUrl && (
        <div className="flex h-full w-full items-center justify-center p-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={blobUrl}
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
            {doc.content_type ? ` (${doc.content_type})` : ""}. Pobierz plik, aby
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
  );
}

// Podgląd pliku in-app (modal). PDF → natywny viewer w <iframe>; DOCX →
// `docx-preview` (lazy import); obraz → <img>; reszta → fallback z pobraniem.
// Body wydzielone do `FilePreviewContent`, by ten sam podgląd działał inline.
export function FilePreviewModal({
  doc,
  candidateId,
  onClose,
  onDownload,
}: {
  doc: CandidateDocument | null;
  candidateId: number;
  onClose: () => void;
  onDownload: (doc: CandidateDocument) => void;
}) {
  return (
    <Dialog open={!!doc} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="full" className="h-[92vh] p-0 gap-0" hideClose>
        <DialogHeader className="flex-row items-center justify-between gap-3 py-3 pr-3">
          <DialogTitle className="min-w-0 truncate text-base font-semibold">
            {doc?.filename ?? "Podgląd pliku"}
          </DialogTitle>
          <div className="flex shrink-0 items-center gap-2">
            {doc && (
              <button
                type="button"
                onClick={() => onDownload(doc)}
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
              aria-label="Zamknij"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </DialogHeader>

        <FilePreviewContent
          doc={doc}
          candidateId={candidateId}
          onDownload={onDownload}
          className="flex-1 min-h-0"
        />
      </DialogContent>
    </Dialog>
  );
}
