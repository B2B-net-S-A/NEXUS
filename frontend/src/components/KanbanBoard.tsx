"use client";

import { useState, useCallback, memo, useMemo, useEffect } from "react";
import {
  DragDropContext,
  Droppable,
  Draggable,
  DropResult,
} from "@hello-pangea/dnd";
import { CandidateCard } from "./CandidateCard";
import {
  RejectionReasonModal,
  RejectionReasonOption,
} from "./RejectionReasonModal";
import api, { pipelineTemplatesApi } from "@/lib/api";

// ── Fallback styling for well-known legacy stages ────────────────────────────

const LEGACY_COLORS: Record<string, string> = {
  new: "border-t-gray-400",
  prep_call: "border-t-sky-400",
  screening: "border-t-blue-400",
  interview: "border-t-purple-400",
  cv_sent: "border-t-indigo-400",
  client_interview: "border-t-amber-400",
  acceptance: "border-t-orange-400",
  negotiation: "border-t-yellow-400",
  onboarding: "border-t-lime-400",
  hired: "border-t-green-500",
  rejected: "border-t-red-400",
  withdrawn: "border-t-slate-400",
};

const LEGACY_ICONS: Record<string, string> = {
  new: "📋",
  prep_call: "📞",
  screening: "🔍",
  interview: "🎤",
  cv_sent: "📤",
  client_interview: "🏢",
  acceptance: "✅",
  negotiation: "🤝",
  onboarding: "🚀",
  hired: "🎉",
  rejected: "❌",
  withdrawn: "🚪",
};

const CATEGORY_COLORS: Record<string, string> = {
  internal: "border-t-blue-400",
  external: "border-t-amber-400",
  terminal: "border-t-slate-400",
};

const CATEGORY_ICONS: Record<string, string> = {
  internal: "🏠",
  external: "🏢",
  terminal: "🏁",
};

interface KanbanItem {
  id: number;
  candidate_id: number;
  stage: string;
  stage_def_id?: number | null;
  rating?: number;
  days_in_stage?: number;
}

interface KanbanColumn {
  stage: string;
  category?: "internal" | "external" | "terminal";
  count: number;
  items: KanbanItem[];
  // Phase 1 additions (server may include these):
  stage_def_id?: number | null;
  name?: string | null;
  order?: number | null;
}

interface KanbanBoardProps {
  columns: KanbanColumn[];
  jobId: number;
}

type TabFilter = "all" | "internal" | "external" | "terminal";

// ── Helpers ──────────────────────────────────────────────────────────────────

const colId = (col: KanbanColumn) =>
  col.stage_def_id ? `def:${col.stage_def_id}` : `stage:${col.stage}`;

const columnLabel = (col: KanbanColumn) =>
  col.name ?? (col.stage && LEGACY_COLORS[col.stage] ? col.stage : col.stage);

const columnBorderColor = (col: KanbanColumn): string => {
  if (col.stage && LEGACY_COLORS[col.stage]) return LEGACY_COLORS[col.stage];
  if (col.category) return CATEGORY_COLORS[col.category];
  return "border-t-gray-300";
};

const columnIcon = (col: KanbanColumn): string => {
  if (col.stage && LEGACY_ICONS[col.stage]) return LEGACY_ICONS[col.stage];
  if (col.category) return CATEGORY_ICONS[col.category];
  return "📌";
};

// ── Memoized column ──────────────────────────────────────────────────────────

const KanbanColumnView = memo(function KanbanColumnView({
  col,
}: {
  col: KanbanColumn;
}) {
  const dropId = colId(col);
  return (
    <div
      className={`flex-shrink-0 w-56 bg-gray-50 dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 border-t-4 ${columnBorderColor(col)}`}
    >
      <div className="px-3 py-2.5 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <span className="font-medium text-xs text-gray-700 dark:text-gray-200 flex items-center gap-1">
            <span>{columnIcon(col)}</span>
            {columnLabel(col)}
          </span>
          <span
            className={`text-xs font-bold px-1.5 py-0.5 rounded-full ${
              col.count > 0
                ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                : "text-gray-400"
            }`}
          >
            {col.count}
          </span>
        </div>
      </div>

      <Droppable droppableId={dropId}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            className={`p-2 space-y-2 min-h-[180px] max-h-[500px] overflow-y-auto transition-colors rounded-b-xl ${
              snapshot.isDraggingOver ? "bg-blue-50/60 dark:bg-blue-900/20" : ""
            }`}
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
                    className={`transition-shadow ${
                      dragSnapshot.isDragging
                        ? "shadow-lg rotate-1 opacity-90"
                        : "shadow-none"
                    }`}
                  >
                    <CandidateCard
                      candidateId={item.candidate_id}
                      stage={item.stage}
                      rating={item.rating}
                      daysInStage={item.days_in_stage}
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

// ── KanbanBoard ──────────────────────────────────────────────────────────────

export function KanbanBoard({ columns, jobId }: KanbanBoardProps) {
  const [cols, setCols] = useState(columns);
  const [activeTab, setActiveTab] = useState<TabFilter>("all");
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [rejectionReasons, setRejectionReasons] = useState<RejectionReasonOption[]>([]);

  // Pending rejection (drop awaiting reason selection)
  const [pendingRejection, setPendingRejection] = useState<{
    item: KanbanItem;
    destCol: KanbanColumn;
    srcColId: string;
    terminalType: "rejected" | "withdrawn";
  } | null>(null);

  // Sync with incoming prop changes
  useEffect(() => {
    setCols(columns);
  }, [columns]);

  // Fetch template + rejection reasons (for terminal drops)
  useEffect(() => {
    (async () => {
      try {
        const jobRes = await api.get(`/api/jobs/${jobId}`);
        const tid = jobRes.data?.pipeline_template_id ?? null;
        setTemplateId(tid);
        if (tid) {
          const detail = await pipelineTemplatesApi.get(tid);
          setRejectionReasons(
            detail.data.rejection_reasons.map((r) => ({
              id: r.id,
              name: r.name,
              category: r.category as "rejected" | "withdrawn",
            }))
          );
        }
      } catch (err) {
        console.error("Failed to load pipeline template for kanban:", err);
      }
    })();
  }, [jobId]);

  const filteredCols = useMemo(() => {
    if (activeTab === "all") return cols;
    return cols.filter((c) => c.category === activeTab);
  }, [cols, activeTab]);

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
    async (
      item: KanbanItem,
      dstCol: KanbanColumn,
      rejectionReasonId?: number
    ) => {
      try {
        await api.post("/api/pipeline/move", {
          candidate_id: item.candidate_id,
          job_id: jobId,
          // Send BOTH — server accepts either
          stage: dstCol.stage,
          stage_def_id: dstCol.stage_def_id ?? undefined,
          rejection_reason_id: rejectionReasonId,
        });
      } catch (err) {
        console.error("Pipeline move failed:", err);
        setCols(columns); // revert to server truth
      }
    },
    [jobId, columns]
  );

  const handleDragEnd = useCallback(
    async (result: DropResult) => {
      if (!result.destination) return;
      const { source, destination, draggableId } = result;
      if (
        source.droppableId === destination.droppableId &&
        source.index === destination.index
      )
        return;

      const entryId = parseInt(draggableId);
      const srcCol = cols.find((c) => colId(c) === source.droppableId);
      const dstCol = cols.find((c) => colId(c) === destination.droppableId);
      if (!srcCol || !dstCol) return;

      const item = srcCol.items.find((i) => i.id === entryId);
      if (!item) return;

      // Terminal drop → ask for reason
      const legacyTerminal =
        dstCol.stage === "rejected" || dstCol.stage === "withdrawn";
      const serverTerminal = dstCol.category === "terminal" && legacyTerminal;

      if (serverTerminal) {
        setPendingRejection({
          item,
          destCol: dstCol,
          srcColId: source.droppableId,
          terminalType: dstCol.stage as "rejected" | "withdrawn",
        });
        return;
      }

      applyOptimistic(item, source.droppableId, dstCol);
      await sendMove(item, dstCol);
    },
    [cols, applyOptimistic, sendMove]
  );

  const handleConfirmRejection = async (reasonId: number) => {
    if (!pendingRejection) return;
    const { item, destCol, srcColId } = pendingRejection;
    applyOptimistic(item, srcColId, destCol);
    setPendingRejection(null);
    await sendMove(item, destCol, reasonId);
  };

  const tabs: { key: TabFilter; label: string; color: string }[] = [
    { key: "all", label: "Wszystkie", color: "bg-gray-100 text-gray-700" },
    { key: "internal", label: "🏠 Etapy wewnętrzne", color: "bg-blue-100 text-blue-700" },
    { key: "external", label: "🏢 Etapy zewnętrzne", color: "bg-amber-100 text-amber-700" },
    { key: "terminal", label: "🏁 Zakończone", color: "bg-green-100 text-green-700" },
  ];

  return (
    <div>
      <div className="flex gap-2 mb-4 flex-wrap">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
              activeTab === tab.key
                ? `${tab.color} ring-2 ring-offset-1 ring-blue-400`
                : "bg-gray-50 text-gray-500 hover:bg-gray-100 dark:bg-gray-800 dark:text-gray-400"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <DragDropContext onDragEnd={handleDragEnd}>
        <div className="flex gap-3 overflow-x-auto pb-4" style={{ minHeight: 300 }}>
          {filteredCols.map((col) => (
            <KanbanColumnView key={colId(col)} col={col} />
          ))}
        </div>
      </DragDropContext>

      <RejectionReasonModal
        open={!!pendingRejection}
        terminalType={pendingRejection?.terminalType ?? "rejected"}
        reasons={rejectionReasons}
        onClose={() => setPendingRejection(null)}
        onConfirm={handleConfirmRejection}
      />

      {templateId === null && (
        <p className="text-xs text-gray-400 mt-2">
          Ten projekt nie ma przypisanego procesu — używany jest domyślny.
        </p>
      )}
    </div>
  );
}
