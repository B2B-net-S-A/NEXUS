"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { SearchablePdfPreview } from "@/components/v2/files/SearchablePdfPreview";

/** Źródło bajtów podglądu — w aplikacji endpoint z `preview=true` (nie liczy
 *  się jako pobranie), w harnessie plik statyczny. */
export type OrderPdfLoader = (ref: {
  kind: string;
  id: number;
}) => Promise<Blob>;

/**
 * Podgląd PDF-u zamówienia (pdf.js z wyszukiwaniem, jak podgląd CV).
 * Wypełnia rodzica — rodzic musi mieć wysokość.
 */
export function OrderPdfViewer({
  file,
  loadPdf,
}: {
  file: { kind: string; id: number };
  loadPdf: OrderPdfLoader;
}) {
  const [blob, setBlob] = useState<Blob | null>(null);
  const [failed, setFailed] = useState(false);
  const key = `${file.kind}:${file.id}`;

  useEffect(() => {
    let cancelled = false;
    setBlob(null);
    setFailed(false);
    loadPdf(file)
      .then((loaded) => {
        if (!cancelled) setBlob(loaded);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
    // `file` jest obiektem z danych — zmienia się tożsamość przy każdym
    // odświeżeniu listy; plik identyfikuje klucz.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, loadPdf]);

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border border-border bg-muted/40">
      {failed ? (
        <p className="flex h-full items-center justify-center p-4 text-center text-sm text-muted-foreground">
          Nie udało się wczytać podglądu PDF. Spróbuj pobrać plik.
        </p>
      ) : blob ? (
        <SearchablePdfPreview
          file={blob}
          placeholder="Szukaj w zamówieniu"
          onError={() => setFailed(true)}
        />
      ) : (
        <p className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Wczytywanie podglądu…
        </p>
      )}
    </div>
  );
}
