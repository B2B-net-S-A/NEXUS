"use client";

import * as React from "react";
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  DragDropContext,
  Draggable,
  Droppable,
  type DropResult,
} from "@hello-pangea/dnd";
import {
  AlertCircle,
  Clock,
  Flag,
  LayoutGrid,
  MoveRight,
  Rows3,
  Sparkles,
  Star,
} from "lucide-react";
import api, { pipelineTemplatesApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/store/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { RejectionV2 } from "@/components/v2/modals/RejectionV2";
import { ScorecardV2 } from "@/components/v2/modals/ScorecardV2";
import { ScreeningSheet } from "@/components/v2/modals/ScreeningSheet";

// ── Types ─────────────────────────────────────────────────────────────

interface KanbanItem {
  id: number;
  candidate_id: number;
  stage: string;
  stage_def_id?: number | null;
  rating?: number;
  days_in_stage?: number;
  name?: string;
  lastname?: string;
}

export interface KanbanColumn {
  stage: string;
  category?: "internal" | "external" | "terminal";
  count: number;
  items: KanbanItem[];
  stage_def_id?: number | null;
  name?: string | null;
  order?: number | null;
}

interface KanbanBoardV2Props {
  columns: KanbanColumn[];
  jobId: number;
}

const CATEGORY_COLOR: Record<string, string> = {
  internal: "bg-[hsl(var(--accent))]",
  external: "bg-[hsl(var(--bg-chrome))]",
  terminal: "bg-[hsl(var(--text-muted))]",
};

const CATEGORY_LABEL: Record<string, string> = {
  internal: "Wewnętrzny",
  external: "Zewnętrzny",
  terminal: "Terminalny",
};

const EXTERNAL_STAGES_FOR_SCREENING = new Set([
  "cv_sent",
  "client_interview",
  "acceptance",
  "negotiation",
  "onboarding",
]);

const colId = (col: KanbanColumn) =>
  col.stage_def_id ? `def:${col.stage_def_id}` : `stage:${col.stage}`;

const columnLabel = (col: KanbanColumn) => col.name ?? col.stage;

// ── Card ─────────────────────────────────────────────────────────────

interface CardProps {
  item: KanbanItem;
  selected: boolean;
  onToggleSelect: (id: number) => void;
  onOpenScreening: (stageId: number, name: string) => void;
  density: "cozy" | "compact";
  canScreen: boolean;
}

const CandidateKanbanCard = memo(function CandidateKanbanCard({
  item,
  selected,
  onToggleSelect,
  onOpenScreening,
  density,
  canScreen,
}: CardProps) {
  const fullName = `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
  const initials = fullName
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const daysBadge =
    item.days_in_stage == null
      ? null
      : item.days_in_stage >= 7
        ? "danger"
        : item.days_in_stage >= 3
          ? "warning"
          : "neutral";

  return (
    <div
      className={cn(
        "group relative rounded-v2-m bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))] transition-all",
        "hover:shadow-v2-s hover:border-[hsl(var(--accent))]/40",
        selected && "ring-2 ring-[hsl(var(--accent))] border-[hsl(var(--accent))]",
        density === "compact" ? "p-2" : "p-3"
      )}
    >
      <div className="absolute top-1 left-1">
        <Checkbox
          checked={selected}
          onCheckedChange={() => onToggleSelect(item.id)}
          aria-label={`Zaznacz ${fullName}`}
          className="bg-[hsl(var(--bg-surface))]"
        />
      </div>

      <Link
        href={`/candidates/${item.candidate_id}`}
        className="block"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={cn("flex items-start gap-2", density === "compact" ? "pl-5" : "pl-5")}>
          <div
            className={cn(
              "rounded-full bg-[hsl(var(--accent))] text-white font-semibold flex items-center justify-center shrink-0",
              density === "compact" ? "h-6 w-6 text-[10px]" : "h-8 w-8 text-xs"
            )}
          >
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div
              className={cn(
                "font-medium text-[hsl(var(--text-title))] truncate",
                density === "compact" ? "text-xs" : "text-sm"
              )}
            >
              {fullName}
            </div>
            <div
              className={cn(
                "flex items-center gap-1.5 mt-0.5 text-[10px] text-[hsl(var(--text-muted))]"
              )}
            >
              {item.rating != null && item.rating > 0 && (
                <span className="inline-flex items-center gap-0.5">
                  <Star className="h-2.5 w-2.5 fill-amber-500 text-amber-500" />
                  {item.rating.toFixed(1)}
                </span>
              )}
              {daysBadge && (
                <span
                  className={cn(
                    "inline-flex items-center gap-0.5",
                    daysBadge === "danger"
                      ? "text-[hsl(var(--accent))]"
                      : daysBadge === "warning"
                        ? "text-amber-600"
                        : ""
                  )}
                >
                  <Clock className="h-2.5 w-2.5" />
                  {item.days_in_stage}d
                </span>
              )}
            </div>
          </div>
        </div>
      </Link>

      {canScreen && density !== "compact" && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            e.preventDefault();
            onOpenScreening(item.id, fullName);
          }}
          className="absolute bottom-1 right-1 inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))] font-semibold hover:bg-[hsl(var(--accent))] hover:text-white transition-colors"
          title="Screening Championa"
        >
          <Sparkles className="h-2.5 w-2.5" />
          Screening
        </button>
      )}
    </div>
  );
});

// ── Column ───────────────────────────────────────────────────────────

interface ColProps {
  col: KanbanColumn;
  selectedIds: Set<number>;
  onToggleSelect: (id: number) => void;
  onOpenScreening: (stageId: number, name: string) => void;
  density: "cozy" | "compact";
}

const KanbanColumnV2 = memo(function KanbanColumnV2({
  col,
  selectedIds,
  onToggleSelect,
  onOpenScreening,
  density,
}: ColProps) {
  const dropId = colId(col);
  return (
    <div
      className={cn(
        "flex-shrink-0 rounded-v2-m bg-[hsl(var(--bg-canvas))]/60 border border-[hsl(var(--border-subtle))]",
        density === "compact" ? "w-52" : "w-60"
      )}
    >
      <div className="px-3 py-2 border-b border-[hsl(var(--border-subtle))] flex items-center gap-2">
        {col.category && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                className={cn(
                  "h-2 w-2 rounded-full shrink-0",
                  CATEGORY_COLOR[col.category]
                )}
                aria-label={CATEGORY_LABEL[col.category]}
              />
            </TooltipTrigger>
            <TooltipContent side="top">{CATEGORY_LABEL[col.category]}</TooltipContent>
          </Tooltip>
        )}
        <span className="text-xs font-medium text-[hsl(var(--text-title))] flex-1 truncate">
          {columnLabel(col)}
        </span>
        <Badge size="sm" variant={col.count > 0 ? "soft" : "outline"}>
          {col.count}
        </Badge>
      </div>

      <Droppable droppableId={dropId}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            className={cn(
              "p-2 space-y-2 min-h-[180px] max-h-[540px] overflow-y-auto rounded-b-v2-m transition-colors",
              snapshot.isDraggingOver &&
                "bg-[hsl(var(--accent-soft))]/60"
            )}
          >
            {col.items.map((item, index) => (
              <Draggable
                key={String(item.id)}
                draggableId={String(item.id)}
                index={index}
              >
                {(dragProvided, dragSnapshot) => (
                  <div
                    ref={dragProvided.innerRef}
                    {...dragProvided.draggableProps}
                    {...dragProvided.dragHandleProps}
                    className={cn(
                      "transition-shadow",
                      dragSnapshot.isDragging && "shadow-v2-l rotate-1 opacity-90"
                    )}
                  >
                    <CandidateKanbanCard
                      item={item}
                      selected={selectedIds.has(item.id)}
                      onToggleSelect={onToggleSelect}
                      onOpenScreening={onOpenScreening}
                      density={density}
                      canScreen={EXTERNAL_STAGES_FOR_SCREENING.has(item.stage)}
                    />
                  </div>
                )}
              </Draggable>
            ))}
            {provided.placeholder}
          </div>
        )}
      </Droppable>
    </div>
  );
});

// ── Board ────────────────────────────────────────────────────────────

export function KanbanBoardV2({ columns, jobId }: KanbanBoardV2Props) {
  const density = useUiStore((s) => s.density);
  const setDensity = useUiStore((s) => s.setDensity);
  const [cols, setCols] = useState(columns);
  const [activeTab, setActiveTab] = useState<"all" | "internal" | "external" | "terminal">("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [rejectionReasons, setRejectionReasons] = useState<
    { id: string; label: string; applies_to: ("rejected" | "withdrawn")[] }[]
  >([]);
  const [stagesWithScorecard, setStagesWithScorecard] = useState<Set<number>>(new Set());

  const [pendingRejection, setPendingRejection] = useState<{
    item: KanbanItem;
    destCol: KanbanColumn;
    srcColId: string;
    terminalType: "rejected" | "withdrawn";
  } | null>(null);
  const [scorecardPrompt, setScorecardPrompt] = useState<{
    candidateStageId: number;
    stageId: number;
    stageDefId: number;
    stageName: string;
  } | null>(null);
  const [screeningPrompt, setScreeningPrompt] = useState<{
    stageId: number;
    candidateName: string;
  } | null>(null);

  useEffect(() => setCols(columns), [columns]);

  useEffect(() => {
    (async () => {
      try {
        const jobRes = await api.get(`/api/jobs/${jobId}`);
        const tid = jobRes.data?.pipeline_template_id;
        if (!tid) return;
        const detail = await pipelineTemplatesApi.get(tid);
        setRejectionReasons(
          detail.data.rejection_reasons.map((r: any) => ({
            id: r.id,
            label: r.name,
            applies_to: [r.category as "rejected" | "withdrawn"],
          }))
        );
        const withScorecard = new Set<number>();
        for (const s of detail.data.stages ?? []) {
          const sch = (s as any).scorecard_schema;
          if (sch && Array.isArray(sch.questions) && sch.questions.length > 0) {
            withScorecard.add((s as any).id);
          }
        }
        setStagesWithScorecard(withScorecard);
      } catch (e) {
        console.error("Pipeline template load failed", e);
      }
    })();
  }, [jobId]);

  const filtered = useMemo(
    () =>
      activeTab === "all"
        ? cols
        : cols.filter((c) => c.category === activeTab),
    [cols, activeTab]
  );

  const applyOptimistic = useCallback(
    (item: KanbanItem, srcId: string, dst: KanbanColumn) => {
      setCols((prev) =>
        prev.map((c) => {
          if (colId(c) === srcId) {
            const items = c.items.filter((i) => i.id !== item.id);
            return { ...c, items, count: items.length };
          }
          if (colId(c) === colId(dst)) {
            const items = [...c.items, { ...item, stage: c.stage, days_in_stage: 0 }];
            return { ...c, items, count: items.length };
          }
          return c;
        })
      );
    },
    []
  );

  const sendMove = useCallback(
    async (item: KanbanItem, dst: KanbanColumn, reason?: { id: string; notes: string }) => {
      try {
        await api.post("/api/pipeline/move", {
          candidate_stage_id: item.id,
          to_stage: dst.stage,
          to_stage_def_id: dst.stage_def_id ?? undefined,
          rejection_reason_id: reason?.id,
          notes: reason?.notes,
        });
        // Prompt screening if moved to external-visible stage
        if (EXTERNAL_STAGES_FOR_SCREENING.has(dst.stage)) {
          setScreeningPrompt({
            stageId: item.id,
            candidateName: `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat",
          });
        }
        // Prompt scorecard if stage has one
        if (dst.stage_def_id && stagesWithScorecard.has(dst.stage_def_id)) {
          setScorecardPrompt({
            candidateStageId: item.id,
            stageId: item.id,
            stageDefId: dst.stage_def_id,
            stageName: dst.name ?? dst.stage,
          });
        }
      } catch (e) {
        console.error("Move failed", e);
        // TODO: revert optimistic on error
      }
    },
    [stagesWithScorecard]
  );

  const onDragEnd = useCallback(
    (res: DropResult) => {
      if (!res.destination) return;
      const src = cols.find((c) => colId(c) === res.source.droppableId);
      const dst = cols.find((c) => colId(c) === res.destination!.droppableId);
      if (!src || !dst || colId(src) === colId(dst)) return;
      const item = src.items[res.source.index];
      if (!item) return;

      applyOptimistic(item, colId(src), dst);

      if (dst.category === "terminal" && (dst.stage === "rejected" || dst.stage === "withdrawn")) {
        setPendingRejection({
          item,
          destCol: dst,
          srcColId: colId(src),
          terminalType: dst.stage as "rejected" | "withdrawn",
        });
      } else {
        sendMove(item, dst);
      }
    },
    [cols, applyOptimistic, sendMove]
  );

  const toggleSelect = (id: number) => {
    setSelected((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  const bulkMove = async (destColId: string) => {
    const dst = cols.find((c) => colId(c) === destColId);
    if (!dst || selected.size === 0) return;
    setBulkBusy(true);
    try {
      for (const sid of Array.from(selected)) {
        const src = cols.find((c) => c.items.some((i) => i.id === sid));
        if (!src) continue;
        const item = src.items.find((i) => i.id === sid)!;
        applyOptimistic(item, colId(src), dst);
        await sendMove(item, dst);
      }
      setSelected(new Set());
    } finally {
      setBulkBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Swimlane / category tabs */}
        <div className="inline-flex gap-1 bg-[hsl(var(--bg-surface))] rounded-v2-m p-1 border border-[hsl(var(--border-subtle))]">
          {(
            [
              { v: "all" as const, label: "Wszystkie" },
              { v: "internal" as const, label: "Wewnętrzne" },
              { v: "external" as const, label: "Zewnętrzne" },
              { v: "terminal" as const, label: "Zakończone" },
            ]
          ).map((t) => (
            <button
              key={t.v}
              onClick={() => setActiveTab(t.v)}
              className={cn(
                "px-3 py-1.5 text-xs rounded-v2-s font-medium transition-colors",
                activeTab === t.v
                  ? "bg-[hsl(var(--accent))] text-white"
                  : "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text-title))]"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => setDensity(density === "cozy" ? "compact" : "cozy")}
                className="h-8 w-8 inline-flex items-center justify-center rounded-v2-s text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))] hover:text-[hsl(var(--text-title))]"
              >
                {density === "compact" ? (
                  <LayoutGrid className="h-4 w-4" />
                ) : (
                  <Rows3 className="h-4 w-4" />
                )}
              </button>
            </TooltipTrigger>
            <TooltipContent>
              Gęstość: {density === "compact" ? "kompaktowa" : "cozy"}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <Card className="!p-3 flex items-center gap-3 flex-wrap bg-[hsl(var(--bg-chrome))] text-[hsl(var(--text-onchrome))] border-white/10">
          <Flag className="h-4 w-4" />
          <span className="text-sm font-medium">
            Wybrano: <strong>{selected.size}</strong>
          </span>
          <div className="inline-flex items-center gap-2 text-xs ml-2">
            <MoveRight className="h-3.5 w-3.5" />
            <span>Przenieś do:</span>
            <Select onValueChange={bulkMove}>
              <SelectTrigger className="h-8 w-[220px] bg-white/10 text-[hsl(var(--text-onchrome))] border-white/20">
                <SelectValue placeholder="Wybierz etap…" />
              </SelectTrigger>
              <SelectContent>
                {cols.map((c) => (
                  <SelectItem key={colId(c)} value={colId(c)}>
                    {columnLabel(c)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <button
            onClick={() => setSelected(new Set())}
            disabled={bulkBusy}
            className="ml-auto text-xs text-[hsl(var(--text-onchrome))]/70 hover:text-[hsl(var(--text-onchrome))]"
          >
            Wyczyść
          </button>
        </Card>
      )}

      {/* Board */}
      <DragDropContext onDragEnd={onDragEnd}>
        <div className="flex gap-3 overflow-x-auto pb-4" style={{ minHeight: 300 }}>
          {filtered.length === 0 ? (
            <div className="w-full py-12 text-center text-sm text-[hsl(var(--text-muted))]">
              <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-40" />
              Brak kolumn w tej kategorii.
            </div>
          ) : (
            filtered.map((col) => (
              <KanbanColumnV2
                key={colId(col)}
                col={col}
                selectedIds={selected}
                onToggleSelect={toggleSelect}
                onOpenScreening={(stageId, name) =>
                  setScreeningPrompt({ stageId, candidateName: name })
                }
                density={density}
              />
            ))
          )}
        </div>
      </DragDropContext>

      {/* Modals */}
      <RejectionV2
        open={pendingRejection !== null}
        onOpenChange={(v) => !v && setPendingRejection(null)}
        terminalType={pendingRejection?.terminalType ?? "rejected"}
        reasons={rejectionReasons}
        onConfirm={(reasonId, notes) => {
          if (!pendingRejection) return;
          sendMove(pendingRejection.item, pendingRejection.destCol, { id: reasonId, notes });
          setPendingRejection(null);
        }}
      />

      {scorecardPrompt && (
        <ScorecardV2
          open={true}
          onOpenChange={(v) => !v && setScorecardPrompt(null)}
          candidateStageId={scorecardPrompt.candidateStageId}
          stageId={scorecardPrompt.stageId}
          stageDefId={scorecardPrompt.stageDefId}
          stageName={scorecardPrompt.stageName}
          onSaved={() => setScorecardPrompt(null)}
        />
      )}

      {screeningPrompt && (
        <ScreeningSheet
          open={true}
          onOpenChange={(v) => !v && setScreeningPrompt(null)}
          stageId={screeningPrompt.stageId}
          candidateName={screeningPrompt.candidateName}
          onSubmitted={() => setScreeningPrompt(null)}
        />
      )}
    </div>
  );
}
