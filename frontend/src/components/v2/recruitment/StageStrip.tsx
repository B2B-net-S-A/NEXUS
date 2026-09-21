"use client";

/**
 * Pasek etapów rekrutacji — jednocześnie lejek i filtr tabeli osób.
 *
 * Dwanaście zakładek rekrutacji odpowiadało na pytanie „gdzie jest ekran do
 * tego etapu". Pasek odpowiada na „ile osób jest na tym etapie" i jednym
 * kliknięciem zawęża tabelę — ten sam gest, niezależnie od etapu.
 *
 * Komponent jest KONTROLOWANY (`segment` / `onSegmentChange`): segment żyje
 * w adresie strony, więc link z powiadomienia otwiera od razu właściwy filtr.
 */

import { useMemo } from "react";
import { ChevronDown } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { columnLabel, type KanbanColumn } from "@/components/v2/pages/kanban-shared";
import {
  PIPELINE_GROUP_LABEL,
  PIPELINE_GROUP_SHORT_LABEL,
  groupKanbanColumns,
  type PipelineColumnGroup,
} from "@/lib/pipeline-flow";
import { cn } from "@/lib/utils";

import { segmentCounts, type OffTemplateBucket } from "./person-rows";
import type { RecruitmentSegment } from "./types";

export interface StageStripProps {
  columns: KanbanColumn[];
  offTemplate?: OffTemplateBucket | null;
  /** `null` = jeszcze nie wiadomo (trwa pobieranie) → „—", nigdy zero. */
  openProposalsCount: number | null;
  shortlistCount: number | null;
  segment: RecruitmentSegment;
  onSegmentChange: (segment: RecruitmentSegment) => void;
  className?: string;
}

function formatCount(value: number | null | undefined): string {
  return value == null ? "—" : String(value);
}

interface SegmentButtonProps {
  label: string;
  count: string;
  pressed: boolean;
  onClick: () => void;
  variant?: "default" | "dashed" | "muted";
  wide?: boolean;
  title?: string;
  /** Druga linia pod etykietą — nazwa zawężonego etapu. */
  detail?: string | null;
  /** Doklejone po prawej (menu zawężenia do jednego etapu). */
  trailing?: React.ReactNode;
}

function SegmentButton({
  label,
  count,
  pressed,
  onClick,
  variant = "default",
  wide = false,
  title,
  detail,
  trailing,
}: SegmentButtonProps) {
  return (
    <div
      className={cn(
        "flex h-[52px] min-w-[104px] shrink-0 items-stretch rounded-lg border transition-colors",
        wide ? "flex-[1.4]" : "flex-1",
        pressed
          ? "border-primary bg-primary/10 text-primary ring-1 ring-primary"
          : variant === "dashed"
            ? "border-dashed border-muted-foreground/50 bg-card text-foreground hover:bg-muted"
            : variant === "muted"
              ? "border-border bg-card text-muted-foreground hover:bg-muted"
              : "border-border bg-card text-foreground hover:bg-muted",
      )}
    >
      <button
        type="button"
        aria-pressed={pressed}
        title={title}
        onClick={onClick}
        className="flex min-w-0 flex-1 flex-col justify-center gap-px rounded-lg px-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="text-[17px] font-semibold leading-tight tabular-nums">{count}</span>
        <span className="truncate whitespace-nowrap text-[11px] font-medium">
          {label}
          {detail ? <span className="font-normal"> · {detail}</span> : null}
        </span>
      </button>
      {trailing}
    </div>
  );
}

export function StageStrip({
  columns,
  offTemplate,
  openProposalsCount,
  shortlistCount,
  segment,
  onSegmentChange,
  className,
}: StageStripProps) {
  const groups = useMemo(() => groupKanbanColumns(columns), [columns]);
  const counts = useMemo(() => segmentCounts(columns, offTemplate), [columns, offTemplate]);

  // Zawężenie `stage:<id>` podświetla segment swojej GRUPY — inaczej po
  // wyborze etapu z menu żaden segment nie byłby wciśnięty.
  const narrowed = useMemo(() => {
    if (!segment.startsWith("stage:")) return null;
    const id = Number(segment.slice("stage:".length));
    for (const group of groups) {
      const col = group.columns.find((c) => c.stage_def_id === id);
      if (col) return { groupKey: group.key, column: col };
    }
    return null;
  }, [segment, groups]);

  const renderGroup = (group: PipelineColumnGroup) => {
    const groupSegment: RecruitmentSegment = `group:${group.key}`;
    const isNarrowed = narrowed?.groupKey === group.key;
    const pressed = segment === groupSegment || isNarrowed;
    const stageColumns = group.columns.filter((c) => c.stage_def_id != null);
    const count = isNarrowed
      ? (counts.stages[narrowed.column.stage_def_id as number] ?? 0)
      : (counts.groups[group.key] ?? 0);
    return (
      <SegmentButton
        key={group.key}
        label={PIPELINE_GROUP_SHORT_LABEL[group.key]}
        title={PIPELINE_GROUP_LABEL[group.key]}
        detail={isNarrowed ? columnLabel(narrowed.column) : null}
        count={String(count)}
        pressed={pressed}
        onClick={() => onSegmentChange(groupSegment)}
        trailing={
          // Menu ma sens dopiero przy >1 etapie: przy jednym „zawężenie"
          // pokazywałoby dokładnie to samo co grupa.
          stageColumns.length > 1 ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={`Zawęź „${PIPELINE_GROUP_SHORT_LABEL[group.key]}” do jednego etapu`}
                  className="flex w-7 shrink-0 items-center justify-center rounded-r-lg border-l border-border/60 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <ChevronDown className="size-3.5" aria-hidden />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => onSegmentChange(groupSegment)}>
                  <span className="flex-1">Wszystkie etapy grupy</span>
                  <span className="tabular-nums text-muted-foreground">
                    {counts.groups[group.key] ?? 0}
                  </span>
                </DropdownMenuItem>
                {stageColumns.map((col) => (
                  <DropdownMenuItem
                    key={col.stage_def_id}
                    onSelect={() =>
                      onSegmentChange(`stage:${col.stage_def_id as number}`)
                    }
                  >
                    <span className="flex-1">{columnLabel(col)}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {counts.stages[col.stage_def_id as number] ?? 0}
                    </span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null
        }
      />
    );
  };

  return (
    <nav
      aria-label="Etapy rekrutacji"
      className={cn("flex items-stretch gap-1.5 overflow-x-auto pb-1", className)}
    >
      <SegmentButton
        label="Propozycje z bazy"
        count={formatCount(openProposalsCount)}
        pressed={segment === "proposals"}
        onClick={() => onSegmentChange("proposals")}
        variant="dashed"
        wide
        title="Osoby spoza tej rekrutacji, które do niej pasują"
      />
      <SegmentButton
        label="Shortlista"
        count={formatCount(shortlistCount)}
        pressed={segment === "shortlist"}
        onClick={() => onSegmentChange("shortlist")}
      />
      {/* Odstęp oddziela „skąd biorę ludzi" od „co się z nimi dzieje". */}
      <span className="w-1 shrink-0" aria-hidden />
      <SegmentButton
        label="W procesie"
        count={String(counts.inProcess)}
        pressed={segment === "in-process"}
        onClick={() => onSegmentChange("in-process")}
        wide
      />
      {groups.filter((group) => group.key !== "closed").map(renderGroup)}
      {counts.offTemplate > 0 ? (
        <SegmentButton
          label="Poza szablonem"
          count={String(counts.offTemplate)}
          pressed={segment === "off-template"}
          onClick={() => onSegmentChange("off-template")}
          title="Osoby na etapie, którego nie ma w szablonie tej rekrutacji"
        />
      ) : null}
      {groups.some((group) => group.key === "closed") ? (
        <SegmentButton
          label="Odrzuceni"
          count={String(counts.closed)}
          pressed={segment === "closed"}
          onClick={() => onSegmentChange("closed")}
          variant="muted"
          title="Odrzuceni i wycofani"
        />
      ) : null}
    </nav>
  );
}
