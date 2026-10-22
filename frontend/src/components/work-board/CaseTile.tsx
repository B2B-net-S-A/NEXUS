"use client";

import type { DraggableProvided } from "@hello-pangea/dnd";
import { FileText, History, LogOut, Mail, PenLine, type LucideIcon } from "lucide-react";

import { personInitials } from "@/components/hr/people/hr-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CASE_AREA_LABELS, CASE_SOURCE_LABELS, type CaseCard } from "@/lib/api/admin-cases";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { PRIORITY_DOT, SOURCE_ICON, caseSubline, dueBadge, type DueTone } from "../admin-cases/case-format";
import { HealthDot } from "./HealthMark";
import { MoveMenu } from "./MoveMenu";
import type { WorkColumn } from "./work-board-model";

const ICONS: Record<(typeof SOURCE_ICON)[keyof typeof SOURCE_ICON], LucideIcon> = {
  mail: Mail,
  contract: FileText,
  exit: LogOut,
  manual: PenLine,
  import: History,
};

export const DUE_VARIANT: Record<DueTone, "danger" | "warning" | "neutral" | null> = {
  overdue: "danger",
  week: "warning",
  later: "neutral",
  none: null,
};

export interface TileDrag {
  provided: DraggableProvided;
  isDragging: boolean;
}

/** Wspólna oprawa karty: `li` z przeciąganiem, uchwyt na treści (li zostaje elementem listy). */
export function TileShell({
  label,
  drag,
  selected,
  className,
  children,
}: {
  label: string;
  drag?: TileDrag;
  selected?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <li
      ref={drag?.provided.innerRef}
      {...drag?.provided.draggableProps}
      aria-label={label}
      className={cn(
        "rounded-lg border border-border bg-card text-sm shadow-xs",
        drag?.isDragging && "relative z-20 rotate-1 opacity-90 shadow-md",
        selected && "ring-2 ring-primary/40",
        className,
      )}
    >
      <div
        {...drag?.provided.dragHandleProps}
        aria-label={drag ? `Przeciągnij kartę: ${label}` : undefined}
        className="flex flex-col gap-2 px-3 py-2.5 outline-hidden focus-visible:ring-2 focus-visible:ring-primary/40 rounded-lg"
      >
        {children}
      </div>
    </li>
  );
}

/**
 * Karta sprawy na tablicy (makieta 19.10.2026, bez zmian wyglądu): ikona
 * źródła, termin w kolorze, kropka priorytetu, tytuł, osoba · klient · obszar,
 * pasek listy kontrolnej, awatar albo „Weź”. Od 22.10.2026: kropka zdrowia
 * relacji przy konsultancie (krąg D11) i „Przenieś do…”.
 */
export function CaseTile({
  card,
  today,
  weekEnd,
  onOpen,
  onTake,
  taking,
  onMove,
  column,
  drag,
  selected,
}: {
  card: CaseCard;
  today?: string;
  weekEnd?: string;
  onOpen: () => void;
  onTake: (() => void) | null;
  taking: boolean;
  /** `null` — osoba bez prawa zmiany statusu (bez menu). */
  onMove: ((target: WorkColumn) => void) | null;
  column: WorkColumn | "closed";
  drag?: TileDrag;
  selected?: boolean;
}) {
  const due = dueBadge(card, today, weekEnd);
  const subline = caseSubline(card);
  const Icon = ICONS[SOURCE_ICON[card.source]];
  const progress = card.checklist_total
    ? Math.round((card.checklist_done / card.checklist_total) * 100)
    : null;
  const dueVariant = due ? DUE_VARIANT[due.tone] : null;
  const health = card.contract?.health ?? null;
  return (
    <TileShell label={card.title} drag={drag} selected={selected}>
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground">
          <Icon className="h-3.5 w-3.5" aria-hidden />
          {CASE_SOURCE_LABELS[card.source]}
        </span>
        <span className="inline-flex items-center gap-1">
          {due && dueVariant ? (
            <Badge size="sm" variant={dueVariant} className="h-auto py-0.5">
              {due.text}
            </Badge>
          ) : due ? (
            <span className="text-[11.5px] text-muted-foreground">{due.text}</span>
          ) : null}
          {onMove ? <MoveMenu title={card.title} current={column} onMove={onMove} /> : null}
        </span>
      </div>
      <div className="flex items-start gap-1.5">
        <span
          className={cn("mt-1.5 size-2 shrink-0 rounded-full", PRIORITY_DOT[card.priority])}
          title={card.priority}
        >
          <span className="sr-only">{card.priority}</span>
        </span>
        <div className="min-w-0">
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Sprawa: ${card.title}`}
            className="line-clamp-2 text-left font-semibold text-foreground hover:underline"
          >
            {card.title}
          </button>
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            {health ? <HealthDot health={health} /> : null}
            <span className="truncate">
              {[
                subline,
                card.contract ? "kontrakt w NEXUSIE" : null,
                CASE_AREA_LABELS[card.area].toLowerCase(),
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </p>
        </div>
      </div>
      {card.follow_up_on && card.status === "waiting" ? (
        <p className="rounded-md bg-muted/60 px-2 py-1 text-xs">
          odezwać się <span className="font-semibold">{formatDayMonthPl(card.follow_up_on)}</span>
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        {progress != null ? (
          <>
            <div
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-border"
              role="progressbar"
              aria-valuenow={card.checklist_done}
              aria-valuemin={0}
              aria-valuemax={card.checklist_total}
              aria-label={`Lista kontrolna: ${card.checklist_done} z ${card.checklist_total}`}
            >
              <div className="h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
            </div>
            <span className="text-[11.5px] tabular-nums text-muted-foreground">
              {card.checklist_done}/{card.checklist_total}
            </span>
          </>
        ) : (
          <span className="flex-1" />
        )}
        {card.assignee ? (
          <span
            title={card.assignee.name ?? undefined}
            className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
          >
            <span aria-hidden>{personInitials(card.assignee.name ?? "")}</span>
            <span className="sr-only">{card.assignee.name}</span>
          </span>
        ) : onTake ? (
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5"
            disabled={taking}
            onClick={onTake}
            aria-label={`Weź sprawę: ${card.title}`}
          >
            Weź
          </Button>
        ) : (
          <span className="shrink-0 text-xs text-muted-foreground">bez osoby</span>
        )}
      </div>
    </TileShell>
  );
}
