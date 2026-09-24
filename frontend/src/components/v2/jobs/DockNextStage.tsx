"use client";

/**
 * Ramka „Następny etap” w doku osoby na Tablicy.
 *
 * Mówi to samo co okno „Przesuń dalej” (`MoveNextDialog`) — z tej samej
 * odpowiedzi serwera (`GET /api/pipeline/move-requirements`) i tą samą listą
 * (`MoveRequirementList`) — ale od razu po otwarciu karty, zanim ktoś kliknie
 * ruch. Główny przycisk słucha `primary.kind` z odpowiedzi serwera tą samą
 * regułą co okno (`planPrimaryStep`): „move” = ruch na następną kolumnę
 * (`onMove` → `requestMove` tablicy — okna stawki, ostrzeżenia i bramki
 * serwera bez zmian), „hand_to_dl”/„hand_to_cpro” = przekazanie jak w oknie,
 * „blocked” = przycisk wyłączony z powodem. Do 24.09.2026 ramka ignorowała
 * `primary` i obiecywała ruch, którego serwer albo tablica odmawiały.
 *
 * Awaria wymagań nie blokuje przycisku ruchu.
 */

import { useEffect, useMemo, useRef } from "react";
import { AlertCircle, ArrowRight, Loader2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { MoveRequirementList } from "@/components/v2/recruitment/MoveRequirementList";
import { apiErrorMessage } from "@/lib/api-error";
import {
  isBlockingGap,
  summarizeRequirements,
  useMoveRequirements,
  type MoveRequirementAction,
  type MoveRequirementsResponse,
} from "@/lib/api/moveRequirements";
import { boardColumnLabel, boardColumnStep, type BoardColumnKey } from "@/lib/board-stages";
import { planPrimaryStep } from "@/lib/move-primary";
import { countPl } from "@/lib/plural-pl";

/**
 * Nazwa i numer kolumny docelowej. Serwer zna kolumnę (`to_column`); przed
 * odpowiedzią — i gdy etap nie ma definicji — zostaje nazwa etapu z karty.
 * „Wysłane do Cpro” rozpoznajemy po wierszu kolejki Cpro w wymaganiach (ten
 * sam fakt, z którego serwer go dokłada).
 */
export function nextStageHeading(
  data: Pick<MoveRequirementsResponse, "to_column" | "items"> | null | undefined,
  fallbackName: string,
): { step: number | null; label: string } {
  const key = (data?.to_column ?? null) as BoardColumnKey | null;
  const step = boardColumnStep(key);
  if (!key || step == null) return { step: null, label: fallbackName };
  const cproEnabled = (data?.items ?? []).some((i) => i.key === "cpro_upload");
  return { step, label: boardColumnLabel(key, { cproEnabled }) };
}

export interface DockNextStageProps {
  candidateId: number;
  jobId: number;
  target: KanbanColumn;
  readOnly: boolean;
  onMove: (target: KanbanColumn) => void;
  /**
   * Ruch na wskazany etap szablonu (`primary.target_stage_def_id`): „QC CV”
   * przy przekazaniu Delivery Leadowi, „Wysłać do Cpro” u Nordei. Bez niego
   * przekazanie jest nieaktywne (nie zgadujemy etapu).
   */
  onMoveToStageDef?: (stageDefId: number) => void;
  onAction: (action: MoveRequirementAction) => void;
  canAct: (action: MoveRequirementAction) => boolean;
  /**
   * Zmienia się, gdy tablica przyniesie nowy stan karty (np. po zapisie
   * arkusza screeningu) — wtedy wymagania liczymy od nowa.
   */
  refreshToken?: unknown;
}

export function DockNextStage({
  candidateId,
  jobId,
  target,
  readOnly,
  onMove,
  onMoveToStageDef,
  onAction,
  canAct,
  refreshToken,
}: DockNextStageProps) {
  const { showSuccess, showError } = useToast();
  const toStageDefId = target.stage_def_id ?? null;
  const params = useMemo(
    () => ({ candidateId, jobId, toStageDefId }),
    [candidateId, jobId, toStageDefId],
  );
  const query = useMoveRequirements(params, toStageDefId != null);
  const { refetch } = query;
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    if (toStageDefId != null) void refetch();
  }, [refreshToken, refetch, toStageDefId]);

  const data = query.data ?? null;
  const heading = nextStageHeading(data, target.name ?? target.stage);
  const askedDuringMove = data?.primary?.kind === "move";
  const summary = data ? summarizeRequirements(data.items ?? []) : null;
  const gaps = (data?.items ?? []).filter((i) => isBlockingGap(i, askedDuringMove)).length;
  // Bez odpowiedzi serwera (ładowanie, awaria) przycisk robi zwykły ruch —
  // serwer i tak sprawdzi swoje bramki.
  const step = data?.primary ? planPrimaryStep(data, gaps) : ({ type: "move" } as const);
  const primaryKind = data?.primary?.kind ?? "move";
  const handsOver = primaryKind === "hand_to_dl" || primaryKind === "hand_to_cpro";
  const buttonDisabled =
    step.type === "disabled" || (step.type === "stage" && onMoveToStageDef == null);
  const buttonLabel = handsOver && data?.primary ? data.primary.label : `Przenieś na etap: ${heading.label}`;
  const blockedHint =
    primaryKind === "blocked" && data?.primary ? data.primary.label : null;
  const runPrimary = () => {
    switch (step.type) {
      case "move":
        onMove(target);
        return;
      case "stage":
        if (!onMoveToStageDef) return;
        onMoveToStageDef(step.stageDefId);
        if (step.notice) showSuccess(step.notice);
        return;
      case "notice":
        showSuccess(step.message);
        return;
      case "error":
        showError(step.message);
        return;
      default:
        return;
    }
  };

  return (
    <section
      aria-label="Następny etap"
      data-testid="dock-next-stage"
      className="space-y-2 rounded-lg border border-primary/30 bg-primary/5 p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-primary">
          Następny etap: {heading.step != null ? `${heading.step} · ` : ""}
          {heading.label}
        </h3>
        {summary && summary.total > 0 && (
          <span
            className="shrink-0 text-[11px] tabular-nums text-muted-foreground"
            data-testid="dock-next-stage-counter"
          >
            {summary.missing > 0 ? `brakuje ${summary.missing} z ${summary.total}` : `gotowe ${summary.total} z ${summary.total}`}
          </span>
        )}
      </div>

      {toStageDefId == null ? null : query.isPending ? (
        <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          Sprawdzamy, czego brakuje…
        </p>
      ) : query.isError ? (
        <div role="alert" className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            Nie udało się sprawdzić wymagań ({apiErrorMessage(query.error, "brak odpowiedzi serwera")}).
            Możesz przenieść osobę mimo to — serwer sprawdzi swoje bramki.{" "}
            <button type="button" className="font-medium text-primary hover:underline" onClick={() => void refetch()}>
              Ponów
            </button>
          </span>
        </div>
      ) : data && summary ? (
        <>
          {(data.items ?? []).length === 0 ? (
            <p className="text-xs text-muted-foreground">Ten krok nie ma wymagań.</p>
          ) : (
            <MoveRequirementList
              items={data.items ?? []}
              askedDuringMove={askedDuringMove}
              readOnly={readOnly}
              onAction={onAction}
              canAct={canAct}
              compact
              className="bg-card"
            />
          )}
          {summary.enforced.length > 0 ? (
            <p className="text-[11px] leading-snug text-destructive" data-testid="dock-next-stage-enforced">
              Bez: {summary.enforced.map((i) => i.label).join(", ")} system nie przepuści ruchu.
              {summary.reminders.length > 0 ? " Pozostałe braki to przypomnienie." : ""}
            </p>
          ) : summary.reminders.length > 0 && askedDuringMove ? (
            <p className="text-[11px] leading-snug text-muted-foreground" data-testid="dock-next-stage-reminder">
              {summary.reminders.length === 1 ? "Ten brak to przypomnienie" : `${countPl(summary.reminders.length, "brak", "braki", "braków")} to przypomnienie`}, nie blokada —
              możesz przenieść osobę już teraz.
            </p>
          ) : null}
          {data.owner_note && (
            <p className="rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground">{data.owner_note}</p>
          )}
        </>
      ) : null}

      {!readOnly && (
        <>
          <Button
            size="sm"
            onClick={runPrimary}
            disabled={buttonDisabled}
            aria-describedby={blockedHint ? "dock-next-stage-blocked" : undefined}
            className="w-full justify-center"
          >
            {buttonLabel}
            {primaryKind !== "hand_to_dl" && <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />}
          </Button>
          {blockedHint && (
            <p id="dock-next-stage-blocked" className="text-[11px] leading-snug text-muted-foreground">
              {blockedHint}.
            </p>
          )}
        </>
      )}
    </section>
  );
}
