"use client";

import { Copy } from "lucide-react";
import { copyTextToClipboard } from "@/lib/clipboard";
import { useToast } from "@/components/Toast";

/** `tel:` bez spacji i myślników — „+48 601 204 118" → „+48601204118". */
export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}

/**
 * Kolumna „Telefon”: numer jest linkiem `tel:` (dzwoni z telefonu albo
 * softphone'u), ikona obok kopiuje go do schowka. Oba kliknięcia NIE
 * otwierają podglądu kandydata. Brak numeru = wyszarzone „brak”.
 */
export function CandidatePhoneCell({
  phone,
  candidateName,
}: {
  phone: string | null | undefined;
  candidateName: string;
}) {
  const { showSuccess, showError } = useToast();
  const value = phone?.trim();
  if (!value) return <span className="text-xs text-muted-foreground">brak</span>;

  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1">
      <a
        href={telHref(value)}
        onClick={(e) => e.stopPropagation()}
        className="truncate font-mono text-xs tabular-nums text-foreground hover:text-primary hover:underline"
        title={`Zadzwoń: ${value}`}
      >
        {value}
      </a>
      <button
        type="button"
        onClick={async (e) => {
          e.stopPropagation();
          const ok = await copyTextToClipboard(value);
          if (ok) showSuccess("Skopiowano numer telefonu");
          else showError("Nie udało się skopiować numeru — zaznacz go ręcznie.");
        }}
        aria-label={`Kopiuj numer: ${candidateName}`}
        title="Kopiuj numer"
        className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-primary/10 hover:text-primary focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Copy className="h-3.5 w-3.5" aria-hidden />
      </button>
    </span>
  );
}
