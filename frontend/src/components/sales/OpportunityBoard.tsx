"use client";

import { DragDropContext, Draggable, Droppable, type DropResult } from "@hello-pangea/dnd";
import { useRouter } from "next/navigation";
import { useLayoutEffect, useRef, useState } from "react";

import { KanbanBoard, KanbanCard } from "@/components/ds/Kanban";
import { StatusDot } from "@/components/ds/StatusDot";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { Badge } from "@/components/ui/badge";
import type { Opportunity, Pipeline, Stage } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { formatDealAmount, formatDealNumber } from "./format";
import { amountLabel, canDragOpportunity, lastContactLabel, shortCompany, stepLabel, stepTone } from "./step";
import { useBoardMove } from "./useBoardMove";

function amountHint(item: Opportunity): string | undefined {
  const closing = item.expected_close_date
    ? `Planowane zamknięcie ${formatIsoDatePl(item.expected_close_date)}`
    : null;
  const split =
    item.mrr_value && item.one_off_value
      ? `${formatDealNumber(item.mrr_value)} zł miesięcznie + ${formatDealNumber(item.one_off_value)} zł jednorazowo`
      : null;
  return [split, closing].filter(Boolean).join(" · ") || undefined;
}

interface OpportunityTileProps {
  item: Opportunity;
  index: number;
  canEdit: boolean;
  showOwner: boolean;
}

function OpportunityTile({ item, index, canEdit, showOwner }: OpportunityTileProps) {
  const router = useRouter();
  const company = shortCompany(item.company.name);
  const open = item.status === "open";
  const tone = stepTone(item);
  return (
    <Draggable draggableId={String(item.id)} index={index} isDragDisabled={!canDragOpportunity(item, canEdit)}>
      {(provided, snapshot) => (
        <KanbanCard
          ref={provided.innerRef}
          {...provided.draggableProps}
          {...provided.dragHandleProps}
          onClick={() => router.push(`/sales/opportunities/${item.id}`)}
          aria-label={`${company} · ${item.title}`}
          className={cn("mb-1 p-2", snapshot.isDragging && "border-primary/60 shadow-lg")}
        >
          <TruncatedText title={item.company.name} className="max-w-none font-medium leading-5 text-foreground">
            {company}
          </TruncatedText>
          <TruncatedText className="max-w-none text-xs leading-4 text-muted-foreground">
            {item.title.replace(/\s+/g, " ")}
          </TruncatedText>
          <div className="mt-1 flex items-center justify-between gap-x-2 text-xs leading-4">
            <span className="min-w-0 truncate tabular-nums text-foreground" title={amountHint(item)}>
              {amountLabel(item)}
            </span>
            {open && (
              <StatusDot tone={tone} className="shrink-0" title="Następny krok">
                {tone === "danger" ? <span className="text-destructive">brak kroku</span> : stepLabel(item)}
              </StatusDot>
            )}
          </div>
          <p className="truncate text-xs leading-4 text-muted-foreground">
            {open ? (
              <span title="Ostatni kontakt" className={cn(item.waiting_for_reply && "font-semibold text-foreground")}>
                {lastContactLabel(item.last_contact)}
              </span>
            ) : item.status === "lost" ? (
              item.lost_reason
            ) : null}
            {showOwner && item.owner ? `${open || item.lost_reason ? " · " : ""}${item.owner.name}` : ""}
          </p>
        </KanbanCard>
      )}
    </Draggable>
  );
}

function sumOf(items: readonly Opportunity[]): number {
  return items.reduce((sum, item) => sum + Number(item.value ?? 0), 0);
}

interface OpportunityBoardProps {
  pipeline: Pipeline;
  stages: readonly Stage[];
  items: readonly Opportunity[];
  canEdit: boolean;
  showOwner: boolean;
  refetch: () => Promise<unknown>;
}

const BOARD_BOTTOM_GAP_PX = 24;
const BOARD_MIN_HEIGHT_PX = 320;

/** Kolumny kończą się na dole ekranu, ile by nie zajmowało to, co nad tablicą. */
function useFitToViewport(dependency: unknown) {
  const ref = useRef<HTMLDivElement>(null);
  const [maxHeight, setMaxHeight] = useState<number>();
  useLayoutEffect(() => {
    const measure = () => {
      const top = ref.current?.getBoundingClientRect().top ?? 0;
      setMaxHeight(Math.max(BOARD_MIN_HEIGHT_PX, window.innerHeight - top - BOARD_BOTTOM_GAP_PX));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [dependency]);
  return { ref, maxHeight };
}

/** Tablica z przeciąganiem między etapami bez wyniku; wygraną i przegraną zamyka karta. */
export function OpportunityBoard({ pipeline, stages, items, canEdit, showOwner, refetch }: OpportunityBoardProps) {
  const { stageOf, moveToStage } = useBoardMove({ stages: pipeline.stages, refetch });
  const { ref, maxHeight } = useFitToViewport(items.length);

  const onDragEnd = ({ draggableId, destination }: DropResult) => {
    if (!destination) return;
    const item = items.find((candidate) => String(candidate.id) === draggableId);
    const target = stages.find((stage) => String(stage.id) === destination.droppableId);
    if (!item || !target || target.outcome !== "open") return;
    void moveToStage(item, target);
  };

  return (
    <DragDropContext onDragEnd={onDragEnd}>
      <KanbanBoard ref={ref} aria-label="Tablica szans" className="gap-3 pb-0">
        {stages.map((stage) => {
          const column = items.filter((item) => stageOf(item) === stage.id);
          return (
            <section
              key={stage.id}
              aria-label={stage.name}
              style={{ maxHeight }}
              className="flex min-w-[232px] flex-1 basis-0 flex-col rounded-lg border border-border bg-muted/40"
            >
              <div className="px-3 pb-1 pt-1.5">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="truncate text-sm font-medium text-foreground">{stage.name}</h3>
                  <Badge variant="soft" size="sm" className="tabular-nums">
                    {column.length}
                  </Badge>
                </div>
                <p className="text-xs leading-4 tabular-nums text-muted-foreground">{formatDealAmount(sumOf(column))}</p>
              </div>
              <Droppable droppableId={String(stage.id)} isDropDisabled={stage.outcome !== "open" || !canEdit}>
                {(provided, snapshot) => (
                  <div
                    ref={provided.innerRef}
                    {...provided.droppableProps}
                    className={cn("min-h-16 flex-1 overflow-y-auto px-2", snapshot.isDraggingOver && "bg-primary/5")}
                  >
                    {column.map((item, index) => (
                      <OpportunityTile key={item.id} item={item} index={index} canEdit={canEdit} showOwner={showOwner} />
                    ))}
                    {provided.placeholder}
                  </div>
                )}
              </Droppable>
            </section>
          );
        })}
      </KanbanBoard>
    </DragDropContext>
  );
}
