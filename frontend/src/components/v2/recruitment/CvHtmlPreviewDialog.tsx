"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Podgląd treści CV etapu. Treść pochodzi z edytora (HTML), więc przed
 * wstawieniem przechodzi przez DOMPurify — ładowany dopiero przy otwarciu.
 * Działa także bez zgody RODO: blokada dotyczy pobrania pliku, nie czytania.
 *
 * Wspólny dla karty „CV do klienta” i okna „Użyj innego CV” (podgląd CV
 * z innej rekrutacji przed wyborem). `html === undefined` = treść się wczytuje.
 */
export function CvHtmlPreviewDialog({
  open,
  onOpenChange,
  html,
  title,
  failed = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  html: string | null | undefined;
  title: string;
  /** Nie udało się wczytać treści — to nie to samo co „CV bez treści”. */
  failed?: boolean;
}) {
  const [safe, setSafe] = useState<string | null>(null);
  useEffect(() => {
    if (!open || !html) return;
    let cancelled = false;
    void import("dompurify").then(({ default: DOMPurify }) => {
      if (cancelled) return;
      setSafe(DOMPurify.sanitize(html, { FORBID_TAGS: ["style", "script"] }));
    });
    return () => {
      cancelled = true;
    };
  }, [open, html]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" className="flex max-h-[92dvh] flex-col p-0">
        <DialogHeader className="border-b border-border px-5 py-3">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>Podgląd treści CV do klienta.</DialogDescription>
        </DialogHeader>
        <div className="flex-1 overflow-auto bg-background p-5">
          {failed ? (
            <p role="alert" className="text-sm text-destructive-muted-foreground">
              Nie udało się wczytać treści tego CV.
            </p>
          ) : html === null || html === "" ? (
            <p className="text-sm text-muted-foreground">To CV nie ma jeszcze treści.</p>
          ) : html === undefined || safe == null ? (
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Wczytywanie podglądu…
            </p>
          ) : (
            <div
              data-testid="cv-to-client-preview"
              className="prose prose-sm max-w-none rounded-lg border border-border bg-card p-4"
              // Treść po DOMPurify (bez skryptów i stylów).
              dangerouslySetInnerHTML={{ __html: safe }}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
