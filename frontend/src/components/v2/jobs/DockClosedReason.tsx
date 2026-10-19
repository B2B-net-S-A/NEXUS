import { Ban, LogOut } from "lucide-react";
import { closedReason, type ClosedReasonSource } from "@/lib/closed-reason";
import { cn, formatDate } from "@/lib/utils";

/**
 * Ramka „Odrzucony: powód” na górze panelu osoby (19.10.2026, wariant A).
 * Ten sam wzór co „Powód odrzucenia” w profilu → Rekrutacje, żeby rekruter
 * rozpoznał go od razu; widoczna też w widoku „Rozwiń”. Dla osób w toku
 * nic nie rysuje.
 */
export function DockClosedReason({ item }: { item: ClosedReasonSource }) {
  const closed = closedReason(item);
  if (!closed) return null;
  const Icon = closed.kind === "withdrawn" ? LogOut : Ban;
  const meta = [closed.by, closed.at ? formatDate(closed.at) : null].filter(Boolean).join(" · ");
  return (
    <div
      role="note"
      aria-label={closed.kind === "rejected" ? "Powód odrzucenia" : "Powód rezygnacji"}
      data-testid="dock-closed-reason"
      data-tone={closed.tone}
      className={cn(
        "space-y-1.5 rounded-lg border px-3 py-2 text-xs",
        closed.tone === "danger"
          ? "border-destructive/30 bg-destructive/10 text-destructive"
          : "border-border bg-muted/40 text-foreground",
      )}
    >
      <div className="flex items-start gap-1.5">
        <Icon className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="min-w-0">
          <span className="font-semibold">{closed.verb}:</span> {closed.reasonText}
        </span>
      </div>
      {closed.comment ? (
        <p className="whitespace-pre-wrap break-words rounded-md bg-background px-2 py-1.5 text-foreground">
          {closed.comment}
        </p>
      ) : null}
      {meta ? <p className="text-[11px] text-muted-foreground">{meta}</p> : null}
    </div>
  );
}
