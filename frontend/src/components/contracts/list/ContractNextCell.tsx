"use client";
// Komórki wiersza listy kontraktów (przebudowa 20.11.2026, wariant A):
// „Co dalej” słowami i drobny druk typu/statusu, gdy to nie „B2B”/„Aktywny”.
import type { ReactNode } from "react";
import type { NextStep, NextTone } from "@/lib/contract-list-next";
import { CALM_EMPTY } from "@/lib/calm-table";
import { contractStatusLabel, contractStatusVariant, type StatusVariant } from "@/lib/status-labels";
import { cn } from "@/lib/utils";

const NEXT_DOT: Record<NextTone, string> = {
  danger: "bg-destructive",
  warning: "bg-warning",
  info: "bg-info",
  muted: "bg-muted-foreground/40",
};

/**
 * Pierwsza sprawa w pierwszej linii z kropką, reszta drobnym drukiem pod
 * spodem. Pełne zdania są w podpowiedzi — kolumna ma przy 1280 px ok. 300 px.
 */
export function ContractNextCell({ steps, children }: { steps: NextStep[]; children?: ReactNode }) {
  if (steps.length === 0) {
    return children ? <div className="flex flex-wrap items-center gap-1.5">{children}</div> : <span className={cn("text-[12px]", CALM_EMPTY)}>—</span>;
  }
  const [first, ...rest] = steps;
  const subline = [first.detail, ...rest.map((step) => step.text)].filter(Boolean).join(" · ");
  const title = [first.text, first.hint ?? first.detail, ...rest.map((step) => step.text)].filter(Boolean).join("\n");
  return (
    <div className="flex min-w-0 items-center gap-2" data-testid="contract-next-steps">
      <div className="min-w-0 flex-1" title={title}>
        <p
          className={cn(
            "flex min-w-0 items-center gap-1.5 text-[12px] font-medium leading-4",
            first.tone === "muted" ? "text-muted-foreground" : "text-foreground",
          )}
        >
          <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", NEXT_DOT[first.tone])} />
          <span className="truncate">{first.text}</span>
        </p>
        {subline ? <p className="truncate pl-3 text-[11px] leading-4 text-muted-foreground">{subline}</p> : null}
      </div>
      {children}
    </div>
  );
}

const TYPE_SHORT: Record<string, string> = {
  uop: "UoP",
  uzlecenie: "Zlecenie",
};

const STATUS_DOT: Record<StatusVariant, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  soft: "bg-info",
  neutral: "bg-muted-foreground/50",
};

/**
 * Typ i status drobnym drukiem — tylko gdy to nie „B2B” i „Aktywny” (prawie
 * każdy wiersz), więc kolumny „Typ” i „Status” zniknęły bez utraty informacji.
 */
export function rowNoteParts(status: string | null | undefined, contractType: string | null | undefined) {
  return {
    type: contractType && contractType !== "b2b" ? (TYPE_SHORT[contractType] ?? contractType.toUpperCase()) : null,
    status: status && status !== "active" ? status : null,
  };
}

export function ContractRowNote({
  status,
  contractType,
  statusLabel,
  className,
}: {
  status: string | null | undefined;
  contractType: string | null | undefined;
  /** Etykieta z mapy statusów listy (`CONTRACT_STATUS_BADGE`); domyślnie słownik wspólny. */
  statusLabel?: string;
  className?: string;
}) {
  const parts = rowNoteParts(status, contractType);
  if (!parts.type && !parts.status) return null;
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5 text-[11px] leading-4", className)} data-testid="contract-row-note">
      {parts.status ? (
        <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap font-medium text-foreground">
          <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", STATUS_DOT[contractStatusVariant(parts.status)])} />
          {statusLabel ?? contractStatusLabel(parts.status)}
        </span>
      ) : null}
      {parts.type ? <span className="font-medium uppercase tracking-[0.03em] text-muted-foreground">{parts.type}</span> : null}
    </span>
  );
}
