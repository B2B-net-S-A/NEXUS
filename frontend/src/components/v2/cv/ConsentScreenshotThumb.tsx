"use client";

/**
 * Miniatura zrzutu zgody RODO przy uwadze QC `consent_matches` (27.10.2026).
 *
 * Delivery Lead przyjmuje zrzut, którego AI nie potwierdziło („To nieprawda”),
 * albo odsyła CV — do tej pory musiał w tym celu pobrać całe CV. Klik
 * powiększa obraz w oknie. Awaria pobrania to komunikat w miejscu miniatury,
 * nie pusty kwadrat: brak obrazu nie może wyglądać jak „zrzutu nie ma”.
 */

import { useEffect, useState } from "react";
import { ImageOff, Loader2 } from "lucide-react";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useQcConsentScreenshot } from "@/lib/api/cvQc";

/** Adres obrazu z pobranego pliku; zwalniany przy zmianie i odmontowaniu. */
function useObjectUrl(blob: Blob | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

export function ConsentScreenshotThumb({ stageId }: { stageId: number }) {
  const [open, setOpen] = useState(false);
  const query = useQcConsentScreenshot(stageId);
  const url = useObjectUrl(query.data);

  if (query.isError) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <ImageOff className="size-3.5" aria-hidden />
        Nie udało się wczytać zrzutu — pobierz CV, żeby go obejrzeć.
      </span>
    );
  }
  if (!url) {
    return (
      <span className="inline-flex h-16 w-24 items-center justify-center rounded-md border border-border bg-muted/40">
        <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Wczytywanie zrzutu zgody" />
      </span>
    );
  }
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Pokaż zrzut zgody"
        className="group relative h-16 w-24 shrink-0 overflow-hidden rounded-md border border-border bg-card hover:border-primary focus-visible:outline-2 focus-visible:outline-primary"
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- obraz z bloba, bez optymalizacji Next */}
        <img src={url} alt="" className="size-full object-cover object-top" />
        <span className="absolute inset-x-0 bottom-0 bg-card/90 px-1 py-0.5 text-[10px] font-medium text-foreground group-hover:text-primary">
          Pokaż zrzut
        </span>
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="xl" className="gap-0 p-0">
          <DialogHeader className="border-b border-border px-5 py-3">
            <DialogTitle>Zrzut zgody RODO</DialogTitle>
            <DialogDescription>Ten obraz stoi pod CV wysyłanym do klienta.</DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-auto bg-muted/40 p-4">
            {/* eslint-disable-next-line @next/next/no-img-element -- obraz z bloba, bez optymalizacji Next */}
            <img src={url} alt="Zrzut zgody RODO kandydata" className="mx-auto h-auto max-w-full" />
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
