"use client";

/**
 * Zapas „Jak u klienta” w edytorze CV: prawdziwy plik DOCX z BIEŻĄCEJ treści edytora,
 * narysowany tą samą drogą co podgląd CV firmowego w panelu osoby
 * (`StageCvPreview`). Kartka edytora odwzorowuje układ szablonu, ale to ten
 * plik dostaje klient.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { alignB2bLetterheadPreview } from "@/lib/cv-docx-preview";
import { observeDocxFit } from "@/lib/docx-fit";
import { renderDocxSafely } from "@/lib/docx-preview-safe";

export interface CvEditorWordPreviewProps {
  /** Plik Word z bieżącej treści; wołany przy otwarciu podglądu i po „Ponów”. */
  load: () => Promise<Blob>;
  /**
   * Co pokazać pod komunikatem, gdy pliku nie da się pokazać (np. 409 bez
   * zgody RODO, 403 przy prawie tylko do odczytu) — zwykle treść CV w układzie
   * kartki edytora, żeby podgląd nigdy nie był pusty.
   */
  fallback?: ReactNode;
}

export function CvEditorWordPreview({ load, fallback }: CvEditorWordPreviewProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    (async () => {
      try {
        const blob = await load();
        const host = hostRef.current;
        if (cancelled || !host) return;
        host.innerHTML = "";
        await renderDocxSafely(blob, host, {
          className: "docx",
          inWrapper: true,
          breakPages: true,
          useBase64URL: true,
        });
        if (cancelled) return;
        alignB2bLetterheadPreview(host);
        setState("ready");
      } catch (error) {
        if (cancelled) return;
        // 409 `consent_required` (brak zrzutu zgody RODO) niesie polski komunikat serwera.
        setMessage(apiErrorMessage(error, "Nie udało się przygotować podglądu Word."));
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
    // `load` powstaje przy każdym renderze okna — podgląd rysuje się raz na
    // otwarcie i po „Ponów”, nie przy każdym renderze.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  // Strona DOCX ma ~794 px (A4); w węższym polu skalujemy ją do szerokości.
  useEffect(() => {
    if (state !== "ready") return;
    const host = hostRef.current;
    if (!host) return;
    return observeDocxFit(host);
  }, [state]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {state === "loading" ? (
        <p role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> Przygotowuję plik Word…
        </p>
      ) : null}
      {state === "error" ? (
        <div className="min-h-0 flex-1 overflow-auto">
          <div className="mx-auto max-w-md space-y-3 py-6 text-center text-sm">
            <p className="text-foreground">{message}</p>
            <Button type="button" variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
              Ponów
            </Button>
          </div>
          {fallback}
        </div>
      ) : null}
      <div
        ref={hostRef}
        hidden={state !== "ready"}
        aria-label="Podgląd pliku Word"
        className="min-h-0 flex-1 overflow-auto"
      />
    </div>
  );
}
