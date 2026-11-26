"use client";

/**
 * Lista wymagań przejścia na kolejną kolumnę Tablicy — JEDNA dla okna
 * „Przesuń dalej” (`MoveNextDialog`) i ramki „Następny etap” w doku osoby
 * (`PipelineCandidateDock`). Reguły liczy serwer
 * (`GET /api/pipeline/move-requirements`); tu tylko render i przycisk, który
 * usuwa brak. Co przycisk robi, decyduje wołający (`onAction`) — okno i dok
 * mają inne okna pod ręką, ale ten sam wiersz.
 */

import { AlertTriangle, Check, Clock, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  isBlockingGap,
  isDealBreakerWarning,
  isPreContractWarning,
  type MoveRequirementAction,
  type MoveRequirementItem,
} from "@/lib/api/moveRequirements";
import { cn } from "@/lib/utils";

export function RequirementStatusIcon({ status }: { status: MoveRequirementItem["status"] }) {
  if (status === "ok") {
    return <Check className="h-4 w-4 shrink-0 text-success" aria-label="Spełnione" />;
  }
  if (status === "waiting") {
    return <Clock className="h-4 w-4 shrink-0 text-warning" aria-label="W toku" />;
  }
  return <X className="h-4 w-4 shrink-0 text-destructive" aria-label="Brakuje" />;
}

/** Stawkę kandydata / do klienta i tak zapyta okno ruchu — bez osobnego przycisku. */
export function isAskedDuringMove(item: MoveRequirementItem, askedDuringMove: boolean): boolean {
  return (
    item.status === "missing" &&
    askedDuringMove &&
    (item.action?.kind === "set_candidate_rate" || item.action?.kind === "set_client_rate")
  );
}

export interface ActionBusy {
  label: string;
  note?: string;
}

export interface MoveRequirementListProps {
  items: readonly MoveRequirementItem[];
  /** `primary.kind === "move"` — okno stawki otworzy się przy samym ruchu. */
  askedDuringMove: boolean;
  readOnly?: boolean;
  /**
   * Akcja przy braku. `canAct` pozwala schować przycisk, którego wołający
   * nie umie obsłużyć (np. dok bez warsztatu CV) — lepiej brak przycisku niż
   * przycisk, który nic nie robi.
   */
  onAction: (action: MoveRequirementAction, item: MoveRequirementItem) => void;
  canAct?: (action: MoveRequirementAction) => boolean;
  /**
   * Akcja w toku (np. wypełnianie formularza klienta, do minuty): przycisk
   * z kręciołkiem i `label`, a `note` zamiast opisu braku.
   */
  actionBusy?: (action: MoveRequirementAction, item: MoveRequirementItem) => ActionBusy | null;
  compact?: boolean;
  className?: string;
}

export function MoveRequirementList({
  items,
  askedDuringMove,
  readOnly = false,
  onAction,
  canAct = () => true,
  actionBusy,
  compact = false,
  className,
}: MoveRequirementListProps) {
  return (
    <ul
      aria-label="Wymagania przejścia"
      className={cn("divide-y divide-border rounded-md border border-border", className)}
    >
      {items.map((req) => {
        const action = req.action?.kind ? req.action : null;
        const blocking = isBlockingGap(req, askedDuringMove);
        const askedLater = isAskedDuringMove(req, askedDuringMove);
        const showAction = action && req.status !== "ok" && !readOnly && !askedLater && canAct(action);
        // „Odpada, gdy…” nie blokuje ruchu, ale nie jest zwykłym przypomnieniem:
        // odpowiedź kandydata wyklucza go z tej rekrutacji.
        const warning = isDealBreakerWarning(req) || isPreContractWarning(req);
        const busy = showAction && actionBusy ? actionBusy(action, req) : null;
        const detail = busy?.note ?? req.detail;
        return (
          <li
            // Klucz z kolumną: ten sam brak bywa w dwóch kolumnach drogi
            // (`client_form` w „QC CV” i „CV wysłane”, 26.11.2026).
            key={`${req.column ?? ""}:${req.key}`}
            data-requirement={req.key}
            data-status={req.status}
            data-tone={warning ? "warning" : undefined}
            className={cn(
              "flex items-start gap-2",
              compact ? "px-2.5 py-1.5 text-xs" : "px-3 py-2 text-sm",
              warning && "bg-warning-muted",
            )}
          >
            {warning ? (
              <AlertTriangle
                className="h-4 w-4 shrink-0 text-warning-muted-foreground"
                aria-label="Ostrzeżenie"
              />
            ) : (
              <RequirementStatusIcon status={req.status} />
            )}
            <div className="min-w-0 flex-1">
              <p
                className={cn(
                  "font-medium",
                  warning
                    ? "text-warning-muted-foreground"
                    : blocking
                      ? "text-foreground"
                      : "text-foreground/90",
                )}
              >
                {req.label}
                {!req.blocking && req.status !== "ok" && (
                  <span
                    className={cn(
                      "ml-1 text-xs font-normal",
                      warning ? "text-warning-muted-foreground" : "text-muted-foreground",
                    )}
                  >
                    (nie blokuje)
                  </span>
                )}
              </p>
              {detail && (
                <p className={cn("text-xs", warning ? "text-warning-muted-foreground" : "text-muted-foreground")}>
                  {detail}
                </p>
              )}
              {askedLater && (
                <p className="text-xs text-muted-foreground">Zapytamy o nią przy przesunięciu.</p>
              )}
            </div>
            {showAction && (
              <Button
                size="sm"
                variant="outline"
                className="shrink-0"
                loading={busy != null}
                disabled={busy != null}
                onClick={() => onAction(action, req)}
              >
                {busy?.label ?? action.label ?? "Uzupełnij"}
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
