"use client";

/**
 * Numer u klienta przy nazwie rekrutacji (prośba DL Nordei, 15.10.2026).
 *
 * Tytuły dla rekrutera są uogólnione („IT Analyst”), więc numer zapytania
 * klienta stoi przed nazwą — na liście `/jobs`, w nagłówku rekrutacji i na
 * szynie „Otwarte karty” — tak, jak klient zna swoje zapytanie. Klik kopiuje
 * cały numer. Kilka numerów (jedna rekrutacja na kilka zapytań) = pierwszy
 * i „+N”, wszystkie w dymku. Kopiowanie robi wołający (`onCopy`): nagłówek
 * bywa montowany bez `ToastProvider`.
 */
import { copyTextToClipboard } from "@/lib/clipboard";
import { clientReferenceParts } from "@/lib/job-names";
import { cn } from "@/lib/utils";

interface CopyNotify {
  showSuccess: (message: string) => void;
  showError: (message: string) => void;
}

export async function copyClientReference(
  reference: string,
  notify: CopyNotify,
): Promise<void> {
  if (await copyTextToClipboard(reference)) {
    notify.showSuccess("Skopiowano numer u klienta");
  } else {
    notify.showError("Nie udało się skopiować numeru — zaznacz go i skopiuj ręcznie.");
  }
}

export function clientReferenceTooltip(
  reference: string,
  clientTitle?: string | null,
): string {
  return [
    `Numer u klienta: ${reference}`,
    clientTitle ? `Nazwa u klienta: ${clientTitle}` : null,
    "Kliknij, aby skopiować",
  ]
    .filter(Boolean)
    .join("\n");
}

export interface ClientReferenceChipProps {
  reference: string | null | undefined;
  /** Nazwa od klienta do dymku — tylko gdy różni się od widocznego tytułu. */
  clientTitle?: string | null;
  size?: "row" | "header";
  onCopy: (reference: string) => void;
  className?: string;
  testId?: string;
}

export function ClientReferenceChip({
  reference,
  clientTitle,
  size = "row",
  onCopy,
  className,
  testId = "client-reference-chip",
}: ClientReferenceChipProps) {
  const parts = clientReferenceParts(reference);
  if (parts.length === 0) return null;
  const full = parts.join(", ");
  const extra = parts.length - 1;
  return (
    <button
      type="button"
      // Wiersz listy otwiera rekrutację kliknięciem — numer tylko kopiuje.
      onClick={(e) => {
        e.stopPropagation();
        onCopy(full);
      }}
      title={clientReferenceTooltip(full, clientTitle)}
      aria-label={`Numer u klienta ${full} — kopiuj`}
      data-testid={testId}
      className={cn(
        "inline-flex max-w-[11rem] shrink-0 cursor-copy items-center gap-1 rounded-md border border-border bg-muted font-semibold tabular-nums text-foreground transition-colors hover:border-primary/40 hover:text-primary focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        size === "header" ? "h-7 px-2 text-sm" : "h-5 px-1.5 text-xs",
        className,
      )}
    >
      <span className="min-w-0 truncate">{parts[0]}</span>
      {extra > 0 ? (
        <span className="shrink-0 font-medium text-muted-foreground">+{extra}</span>
      ) : null}
    </button>
  );
}
