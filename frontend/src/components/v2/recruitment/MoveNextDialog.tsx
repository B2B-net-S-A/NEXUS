"use client";

/**
 * Okno „Przesuń dalej" (Rekrutacja v5, makiety
 * https://claude.ai/artifact/CG4mBk9xcHZAn3y9jcmMeW, zakładka 2).
 *
 * Otwiera je strzałka „→" na karcie Tablicy, a także upuszczenie karty dalej
 * niż na sąsiednią kolumnę albo przy znanych brakach. Okno mówi trzy rzeczy:
 * skąd dokąd idzie osoba (pasek 8 kroków), czego brakuje (lista z serwera,
 * `GET /api/pipeline/move-requirements`) i co zrobi główny przycisk
 * (`primary.kind`). Brak nie jest ślepą uliczką — przy każdym jest przycisk
 * do istniejącego okna (arkusz screeningu, generator CV, QC CV, debrief…).
 *
 * Sam ruch NIE mieszka tutaj: główny przycisk woła `onMove`, a tablica
 * przepuszcza go przez `usePipelineMove` (okna stawek, ostrzeżenia,
 * konflikt wersji, zatrudnienie — wszystko jak przy przeciągnięciu).
 */

import { useMemo } from "react";
import { AlertCircle, ArrowRight, Check, Clock, Loader2, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { apiErrorMessage } from "@/lib/api-error";
import {
  isBlockingGap,
  useMoveRequirements,
  type MoveRequirementAction,
  type MoveRequirementItem,
} from "@/lib/api/moveRequirements";
import {
  BOARD_COLUMN_ORDER,
  boardColumnLabel,
  type BoardColumnKey,
} from "@/lib/board-stages";
import { itemFullName } from "@/lib/pipeline-flow";
import { cn } from "@/lib/utils";

export const HAND_TO_DL_MESSAGE =
  "Osoba czeka na Delivery Leada w jego kolejce »Czeka na Ciebie«";

export interface MoveNextDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  item: KanbanItem | null;
  /** Gospodarz kolumny docelowej (tam trafia ruch). */
  target: KanbanColumn | null;
  /** Nazwa kolumny docelowej na Tablicy („QC CV"). */
  targetLabel?: string | null;
  /** Kolumna Tablicy, na której osoba stoi dziś — zanim serwer odpowie. */
  fromKey?: BoardColumnKey | null;
  targetKey?: BoardColumnKey | null;
  cproEnabled?: boolean;
  readOnly?: boolean;
  /** Ruch na kolumnę docelową — przez `usePipelineMove`. */
  onMove: (target: KanbanColumn) => void;
  /** Nordea: ruch na etap „Wysłać do Cpro" (`primary.target_stage_def_id`). */
  onHandToCpro: (stageDefId: number) => void;
  /** Akcja przy braku (arkusz, CV, QC, debrief, terminy). */
  onAction: (action: MoveRequirementAction, item: KanbanItem) => void;
}

type StepState = "done" | "current" | "skipped" | "target" | "ahead";

function stepState(
  key: BoardColumnKey,
  from: BoardColumnKey | null,
  to: BoardColumnKey | null,
  skipped: readonly BoardColumnKey[],
): StepState {
  if (key === from) return "current";
  if (key === to) return "target";
  if (skipped.includes(key)) return "skipped";
  const at = BOARD_COLUMN_ORDER.indexOf(key);
  const fromAt = from ? BOARD_COLUMN_ORDER.indexOf(from) : -1;
  return fromAt >= 0 && at < fromAt ? "done" : "ahead";
}

const STEP_CLASS: Record<StepState, string> = {
  done: "border-primary/30 bg-primary/10 text-primary",
  current: "border-primary bg-card text-foreground ring-2 ring-primary/40",
  skipped: "border-dashed border-warning bg-warning/10 text-warning",
  target: "border-primary bg-primary text-primary-foreground",
  ahead: "border-border bg-muted text-muted-foreground",
};

const STEP_SUFFIX: Record<StepState, string> = {
  done: "za nami",
  current: "teraz",
  skipped: "pomijany",
  target: "cel",
  ahead: "dalej",
};

function StepBar({
  from,
  to,
  skipped,
  cproEnabled,
}: {
  from: BoardColumnKey | null;
  to: BoardColumnKey | null;
  skipped: readonly BoardColumnKey[];
  cproEnabled: boolean;
}) {
  return (
    <ol aria-label="Kroki procesu" data-testid="move-next-steps" className="grid grid-cols-4 gap-1 sm:grid-cols-8">
      {BOARD_COLUMN_ORDER.map((key, index) => {
        const state = stepState(key, from, to, skipped);
        const label = boardColumnLabel(key, { cproEnabled });
        return (
          <li
            key={key}
            data-step={key}
            data-state={state}
            aria-current={state === "current" ? "step" : undefined}
            aria-label={`${index + 1}. ${label} — ${STEP_SUFFIX[state]}`}
            className={cn(
              "flex min-w-0 flex-col items-center gap-0.5 rounded-md border px-1 py-1 text-center text-[10px] leading-tight",
              STEP_CLASS[state],
            )}
          >
            <span className="font-semibold tabular-nums" aria-hidden="true">
              {index + 1}
            </span>
            <span className="line-clamp-2 [overflow-wrap:anywhere]" aria-hidden="true">
              {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function StatusIcon({ status }: { status: MoveRequirementItem["status"] }) {
  if (status === "ok") {
    return <Check className="h-4 w-4 shrink-0 text-success" aria-label="Spełnione" />;
  }
  if (status === "waiting") {
    return <Clock className="h-4 w-4 shrink-0 text-warning" aria-label="W toku" />;
  }
  return <X className="h-4 w-4 shrink-0 text-destructive" aria-label="Brakuje" />;
}

export function MoveNextDialog({
  open,
  onOpenChange,
  jobId,
  item,
  target,
  targetLabel,
  fromKey = null,
  targetKey = null,
  cproEnabled = false,
  readOnly = false,
  onMove,
  onHandToCpro,
  onAction,
}: MoveNextDialogProps) {
  const { showSuccess } = useToast();
  const params = useMemo(
    () =>
      item && target
        ? {
            candidateId: item.candidate_id,
            jobId,
            toStageDefId: target.stage_def_id ?? null,
          }
        : null,
    [item, target, jobId],
  );
  const query = useMoveRequirements(params, open);
  const data = query.data;
  const primary = data?.primary ?? null;
  const askedDuringMove = primary?.kind === "move";
  const gaps = useMemo(
    () => (data?.items ?? []).filter((i) => isBlockingGap(i, askedDuringMove)),
    [data, askedDuringMove],
  );
  const fullName = item ? itemFullName(item) : "";
  const shownTargetLabel =
    targetLabel ?? (targetKey ? boardColumnLabel(targetKey, { cproEnabled }) : null) ?? target?.name ?? "";

  const close = () => onOpenChange(false);

  const runPrimary = () => {
    if (!item || !target || !primary || readOnly) return;
    if (primary.kind === "hand_to_dl") {
      showSuccess(HAND_TO_DL_MESSAGE);
      close();
      return;
    }
    if (primary.kind === "hand_to_cpro") {
      if (primary.target_stage_def_id == null) return;
      close();
      onHandToCpro(primary.target_stage_def_id);
      return;
    }
    if (primary.kind !== "move" || gaps.length > 0) return;
    close();
    onMove(target);
  };

  const primaryDisabled =
    readOnly ||
    !primary ||
    primary.kind === "blocked" ||
    (primary.kind === "move" && gaps.length > 0) ||
    (primary.kind === "hand_to_cpro" && primary.target_stage_def_id == null);
  const primaryHint = readOnly
    ? "Tylko odczyt."
    : primary?.kind === "blocked" || (primary?.kind === "move" && gaps.length > 0)
      ? `Najpierw uzupełnij: ${gaps.map((g) => g.label).join(", ") || "braki z listy"}.`
      : null;

  return (
    <Dialog open={open && item != null && target != null} onOpenChange={onOpenChange}>
      <DialogContent size="lg" data-testid="move-next-dialog" aria-describedby="move-next-description">
        <DialogHeader>
          <DialogTitle>Przesuń dalej: {fullName}</DialogTitle>
          <DialogDescription id="move-next-description">
            Na „{shownTargetLabel}” — sprawdź, czego brakuje, zanim osoba pójdzie dalej.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <StepBar
            from={data?.from_column ?? fromKey}
            to={data?.to_column ?? targetKey}
            skipped={data?.skipped_columns ?? []}
            cproEnabled={cproEnabled}
          />
          {data && data.skipped_columns.length > 0 && (
            <p className="text-xs text-warning">
              Pomijasz:{" "}
              {data.skipped_columns.map((k) => boardColumnLabel(k, { cproEnabled })).join(", ")}.
              Wymagania tych kroków też obowiązują.
            </p>
          )}

          {query.isPending && params?.toStageDefId != null ? (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Sprawdzamy, czego brakuje…
            </p>
          ) : query.isError || params?.toStageDefId == null ? (
            <div role="alert" className="space-y-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
              <p className="flex items-center gap-2 font-medium text-warning">
                <AlertCircle className="h-4 w-4" aria-hidden="true" />
                Nie udało się sprawdzić wymagań.
              </p>
              <p className="text-muted-foreground">
                {query.isError
                  ? apiErrorMessage(query.error, "Serwer nie odpowiedział.")
                  : "Ten etap nie ma definicji w szablonie."}{" "}
                Możesz przesunąć osobę mimo to — serwer i tak sprawdzi swoje bramki.
              </p>
              <div className="flex gap-2">
                {query.isError && (
                  <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
                    Ponów
                  </Button>
                )}
                {!readOnly && target && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      close();
                      onMove(target);
                    }}
                  >
                    Przesuń mimo to
                  </Button>
                )}
              </div>
            </div>
          ) : data ? (
            <>
              {data.items.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Ten krok nie ma wymagań — możesz przesuwać.
                </p>
              ) : (
                <ul aria-label="Wymagania przejścia" className="divide-y divide-border rounded-md border border-border">
                  {data.items.map((req) => {
                    const action = req.action?.kind ? req.action : null;
                    const blocking = isBlockingGap(req, askedDuringMove);
                    const askedLater =
                      req.status === "missing" &&
                      askedDuringMove &&
                      (req.action?.kind === "set_candidate_rate" || req.action?.kind === "set_client_rate");
                    return (
                      <li
                        key={req.key}
                        data-requirement={req.key}
                        data-status={req.status}
                        className="flex items-start gap-2 px-3 py-2 text-sm"
                      >
                        <StatusIcon status={req.status} />
                        <div className="min-w-0 flex-1">
                          <p className={cn("font-medium", blocking ? "text-foreground" : "text-foreground/90")}>
                            {req.label}
                            {!req.blocking && req.status !== "ok" && (
                              <span className="ml-1 text-xs font-normal text-muted-foreground">
                                (nie blokuje)
                              </span>
                            )}
                          </p>
                          {req.detail && <p className="text-xs text-muted-foreground">{req.detail}</p>}
                          {askedLater && (
                            <p className="text-xs text-muted-foreground">Zapytamy o nią przy przesunięciu.</p>
                          )}
                        </div>
                        {action && req.status !== "ok" && !readOnly && item && !askedLater && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="shrink-0"
                            onClick={() => onAction(action, item)}
                          >
                            {action.label ?? "Uzupełnij"}
                          </Button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
              {data.owner_note && (
                <p data-testid="move-next-owner-note" className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                  {data.owner_note}
                </p>
              )}
            </>
          ) : null}
        </DialogBody>
        <DialogFooter>
          {primaryHint && (
            <p id="move-next-primary-hint" className="mr-auto self-center text-xs text-muted-foreground">
              {primaryHint}
            </p>
          )}
          <Button variant="ghost" onClick={close}>
            Anuluj
          </Button>
          {primary && (
            <Button
              data-testid="move-next-primary"
              onClick={runPrimary}
              disabled={primaryDisabled}
              aria-describedby={primaryHint ? "move-next-primary-hint" : undefined}
            >
              {primary.label}
              {primary.kind !== "hand_to_dl" && <ArrowRight className="h-4 w-4" aria-hidden="true" />}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
