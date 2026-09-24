"use client";

import { useEffect, useRef, useState } from "react";
import { Download, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import api, { cvGeneratedEditorApi, type GeneratedCvItem } from "@/lib/api";
import { alignB2bLetterheadPreview } from "@/lib/cv-docx-preview";
import { renderDocxSafely } from "@/lib/docx-preview-safe";

export interface GeneratedCvPreviewModalProps {
  item: GeneratedCvItem | null;
  onClose: () => void;
  onDownload: (item: GeneratedCvItem) => void;
}

/**
 * Podgląd wygenerowanego CV w aplikacji. Zwykle renderuje DOCX (docx-preview,
 * leniwie). Gdy brakuje wymaganej zgody RODO, DOCX się nie pobierze (409) —
 * wtedy pokazujemy treść z edytora, w piaskownicy iframe, bez skryptów.
 */
export function GeneratedCvPreviewModal({ item, onClose, onDownload }: GeneratedCvPreviewModalProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [html, setHtml] = useState<string | null>(null);
  const viaEditor = !!item?.consent_missing;

  useEffect(() => {
    if (!item) return;
    let cancelled = false;
    setStatus("loading");
    setHtml(null);
    (async () => {
      try {
        if (viaEditor) {
          const { data } = await cvGeneratedEditorApi.get(item.id);
          if (cancelled) return;
          setHtml(data.content_html ?? "");
          setStatus("ready");
          return;
        }
        const res = await api.get(`/api/cv-generator/generated/${item.id}/docx`, { responseType: "blob" });
        const host = hostRef.current;
        if (cancelled || !host) return;
        host.innerHTML = "";
        await renderDocxSafely(res.data as Blob, host, {
          className: "docx",
          inWrapper: true,
          breakPages: true,
          useBase64URL: true,
        });
        if (!cancelled) {
          alignB2bLetterheadPreview(host);
          setStatus("ready");
        }
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item, viaEditor]);

  return (
    <Dialog open={!!item} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="full" className="h-[92dvh] gap-0 p-0">
        <DialogHeader className="flex-row items-center justify-between gap-3 border-b border-border px-4 py-3 pr-16">
          <DialogTitle className="min-w-0 truncate text-base font-semibold">
            {item?.candidate_name}
            {item?.position ? ` — ${item.position}` : ""}
            {item ? ` · ${item.language.toUpperCase()}` : ""}
          </DialogTitle>
          {item && !item.consent_missing ? (
            <Button size="sm" variant="outline" onClick={() => onDownload(item)}>
              <Download aria-hidden className="mr-2 h-4 w-4" />
              Pobierz
            </Button>
          ) : null}
        </DialogHeader>
        {viaEditor ? (
          <p className="border-b border-border bg-warning-muted px-4 py-2 text-xs text-warning-muted-foreground">
            Podgląd bez zrzutu zgody RODO. Pobranie odblokuje się po dołączeniu zrzutu.
          </p>
        ) : null}
        <div className="relative flex-1 overflow-auto bg-muted/30 p-4">
          {status !== "ready" ? (
            <div className="absolute inset-0 flex items-center justify-center text-sm">
              {status === "loading" ? (
                <span className="flex items-center text-muted-foreground">
                  <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" />
                  Renderowanie podglądu…
                </span>
              ) : (
                <span className="text-destructive">
                  {viaEditor
                    ? "Nie udało się wyświetlić podglądu CV."
                    : "Nie udało się wyświetlić podglądu — pobierz plik DOCX."}
                </span>
              )}
            </div>
          ) : null}
          {viaEditor ? (
            html != null ? (
              <iframe
                title="Podgląd CV"
                sandbox=""
                srcDoc={html}
                className="mx-auto h-full min-h-[70dvh] w-full max-w-4xl rounded-lg border border-border bg-card"
              />
            ) : null
          ) : (
            <div ref={hostRef} className="docx-preview-host mx-auto" />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
