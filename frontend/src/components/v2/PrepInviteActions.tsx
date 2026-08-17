"use client";

import { useState } from "react";
import {
  AlertCircle,
  CalendarPlus,
  Check,
  Copy,
  ExternalLink,
} from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  InviteDraft,
  PREP_INVITE_CV_REMINDER,
  buildInviteIcs,
  buildOutlookComposeUrl,
  downloadIcsFile,
  icsFileName,
} from "@/lib/help-invite";

/**
 * Akcje na gotowym zaproszeniu prep — wspólne dla zakładki Pomoc i profilu
 * kandydata, żeby oba miejsca dawały dokładnie tę samą treść.
 *
 * Kolejność przycisków odzwierciedla to, jak zespół pracuje: `.ics` jest
 * WYRÓŻNIONY, bo rekruterzy siedzą w desktopowym Outlooku, a tylko tam da się
 * dołączyć plik CV do zaproszenia. Pop-out webowy jest opcją, nie równorzędną
 * alternatywą — dlatego `variant="outline"`, nie `default`.
 */
export interface PrepInviteActionsProps {
  draft: InviteDraft;
  /** Odróżnia opisy dostępności, gdy na ekranie jest wiele zaproszeń. */
  label?: string;
  /**
   * Kanał komunikatów. Drugi argument rozróżnia sukces od porażki, żeby
   * powierzchnia z rozdzielonymi toastami (`showSuccess`/`showError`) nie
   * musiała zgadywać z treści. Handler jednoargumentowy pasuje tu bez zmian.
   */
  onToast?: (message: string, type?: "success" | "error") => void;
  className?: string;
}

type CopyState = "idle" | "copied" | "failed";

export function PrepInviteActions({
  draft,
  label,
  onToast,
  className,
}: PrepInviteActionsProps) {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const suffix = label ? `: ${label}` : "";

  const handleDownload = () => {
    downloadIcsFile(icsFileName(draft.subject), buildInviteIcs(draft));
    onToast?.("Pobrano zaproszenie — otwórz plik, aby dołączyć CV w Outlooku");
  };

  const handleCopy = async () => {
    // Fallback zamiast wyjątku: `navigator.clipboard` nie istnieje w kontekście
    // nie-HTTPS, a rekruter zobaczyłby tylko martwy przycisk.
    const text = `${draft.subject}\n\n${draft.body}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("copied");
      setTimeout(() => setCopyState("idle"), 2000);
      onToast?.("Skopiowano treść zaproszenia");
    } catch {
      // Porażka MUSI być widoczna na samym przycisku, nie tylko w toaście:
      // gdy powierzchnia nie podepnie `onToast`, cisza po kliknięciu wygląda
      // jak udane kopiowanie i rekruter wkleja do Outlooka poprzedni schowek.
      setCopyState("failed");
      setTimeout(() => setCopyState("idle"), 4000);
      onToast?.(
        "Nie udało się skopiować — zaznacz treść i skopiuj ręcznie",
        "error",
      );
    }
  };

  const copyLabel =
    copyState === "copied"
      ? "Skopiowano"
      : copyState === "failed"
        ? "Nie udało się skopiować"
        : "Kopiuj treść";

  return (
    <div className={cn("flex items-center gap-1.5 flex-wrap", className)}>
      <Button
        size="sm"
        onClick={handleDownload}
        aria-label={`Pobierz zaproszenie (.ics)${suffix}`}
      >
        <CalendarPlus className="h-4 w-4" aria-hidden="true" /> Pobierz
        zaproszenie (.ics)
      </Button>

      {/* Goły <a> ze stylami `buttonVariants`, nie `<Button asChild>`: Button
          dokłada slot na spinner, więc Radix Slot dostaje dwoje dzieci. */}
      <a
        href={buildOutlookComposeUrl(draft)}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Otwórz w Outlook Web${suffix}`}
        className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
      >
        <ExternalLink className="h-4 w-4" aria-hidden="true" /> Outlook Web
      </a>

      <Button
        size="sm"
        variant="ghost"
        onClick={handleCopy}
        aria-label={`Kopiuj treść zaproszenia${suffix}`}
      >
        {copyState === "copied" ? (
          <Check className="h-4 w-4" aria-hidden="true" />
        ) : copyState === "failed" ? (
          <AlertCircle className="h-4 w-4 text-primary" aria-hidden="true" />
        ) : (
          <Copy className="h-4 w-4" aria-hidden="true" />
        )}
        {copyLabel}
      </Button>
    </div>
  );
}

/**
 * Podpowiedź operacyjna dla rekrutera.
 *
 * To zdanie CELOWO nie jest częścią treści zaproszenia — w `body` byłoby
 * wewnętrzną notatką wysłaną kandydatowi. Renderujemy je obok przycisków
 * i nigdzie indziej.
 */
export function PrepInviteCvReminder({ className }: { className?: string }) {
  return (
    <p className={cn("text-xs text-muted-foreground", className)}>
      {PREP_INVITE_CV_REMINDER}
    </p>
  );
}
