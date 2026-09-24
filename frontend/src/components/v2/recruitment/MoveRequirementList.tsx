"use client";

/**
 * Lista wymagań przejścia na kolejną kolumnę Tablicy — JEDNA dla okna
 * „Przesuń dalej” (`MoveNextDialog`) i ramki „Następny etap” w doku osoby
 * (`PipelineCandidateDock`). Reguły liczy serwer
 * (`GET /api/pipeline/move-requirements`); tu tylko render i przycisk, który
 * usuwa brak. Co przycisk robi, decyduje wołający (`onAction`) — okno i dok
 * mają inne okna pod ręką, ale ten sam wiersz.
 */

import { Check, Clock, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  isBlockingGap,
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
  onAction: (action: MoveRequirementAction) => void;
  canAct?: (action: MoveRequirementAction) => boolean;
  compact?: boolean;
  className?: string;
}

export function MoveRequirementList({
  items,
  askedDuringMove,
  readOnly = false,
  onAction,
  canAct = () => true,
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
        return (
          <li
            key={req.key}
            data-requirement={req.key}
            data-status={req.status}
            className={cn("flex items-start gap-2", compact ? "px-2.5 py-1.5 text-xs" : "px-3 py-2 text-sm")}
          >
            <RequirementStatusIcon status={req.status} />
            <div className="min-w-0 flex-1">
              <p className={cn("font-medium", blocking ? "text-foreground" : "text-foreground/90")}>
                {req.label}
                {!req.blocking && req.status !== "ok" && (
                  <span className="ml-1 text-xs font-normal text-muted-foreground">(nie blokuje)</span>
                )}
              </p>
              {req.detail && <p className="text-xs text-muted-foreground">{req.detail}</p>}
              {askedLater && (
                <p className="text-xs text-muted-foreground">Zapytamy o nią przy przesunięciu.</p>
              )}
            </div>
            {showAction && (
              <Button
                size="sm"
                variant="outline"
                className="shrink-0"
                onClick={() => onAction(action)}
              >
                {action.label ?? "Uzupełnij"}
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
