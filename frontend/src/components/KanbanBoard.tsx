"use client";

import { useState, useCallback, memo, useMemo } from "react";
import { DragDropContext, Droppable, Draggable, DropResult } from "@hello-pangea/dnd";
import { CandidateCard } from "./CandidateCard";
import api from "@/lib/api";

const STAGE_LABELS: Record<string, string> = {
  new: "Nowi / Analiza CV",
  prep_call: "Preparation Call",
  screening: "Screening",
  interview: "Interview Wewnętrzny",
  cv_sent: "CV Wysłane",
  client_interview: "Interview Klient",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  hired: "Zatrudniony",
  rejected: "Odrzucony",
  withdrawn: "Wycofany",
};

const STAGE_COLORS: Record<string, string> = {
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

const STAGE_ICONS: Record<string, string> = {
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

const STAGE_CATEGORIES: Record<string, "internal" | "external" | "terminal"> = {
  new: "internal",
  prep_call: "internal",
  screening: "internal",
  interview: "internal",
  cv_sent: "internal",
  client_interview: "external",
  acceptance: "external",
  negotiation: "external",
  onboarding: "external",
  hired: "terminal",
  rejected: "terminal",
  withdrawn: "terminal",
};

interface KanbanItem {
  id: number;
  candidate_id: number;
  stage: string;
  rating?: number;
  days_in_stage?: number;
}

interface KanbanColumn {
  stage: string;
  category?: string;
  count: number;
  items: KanbanItem[];
}

interface KanbanBoardProps {
  columns: KanbanColumn[];
  jobId: number;
}

type TabFilter = "all" | "internal" | "external" | "terminal";

// Memoized column to prevent re-renders of unchanged columns during drag
const KanbanColumnView = memo(function KanbanColumnView({
  col,
  movingId,
}: {
  col: KanbanColumn;
  movingId: number | null;
}) {
  return (
    <div
      className={`flex-shrink-0 w-56 bg-gray-50 dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 border-t-4 ${STAGE_COLORS[col.stage] || ""}`}
    >
      <div className="px-3 py-2.5 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <span className="font-medium text-xs text-gray-700 dark:text-gray-200 flex items-center gap-1">
            <span>{STAGE_ICONS[col.stage] || "📌"}</span>
            {STAGE_LABELS[col.stage] || col.stage}
          </span>
          <span className={`text-xs font-bold px-1.5 py-0.5 rounded-full ${
            col.count > 0 ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300" : "text-gray-400"
          }`}>
            {col.count}
          </span>
        </div>
      </div>

      <Droppable droppableId={col.stage}>
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
                {(provided, snapshot) => (
                  <div
                    ref={provided.innerRef}
                    {...provided.draggableProps}
                    {...provided.dragHandleProps}
                    className={`transition-shadow ${
                      snapshot.isDragging
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

export function KanbanBoard({ columns, jobId }: KanbanBoardProps) {
  const [cols, setCols] = useState(columns);
  const [movingId, setMovingId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<TabFilter>("all");

  // Filter columns by category tab
  const filteredCols = useMemo(() => {
    if (activeTab === "all") return cols;
    return cols.filter(c => {
      const cat = STAGE_CATEGORIES[c.stage] || c.category;
      return cat === activeTab;
    });
  }, [cols, activeTab]);

  const handleDragEnd = useCallback(
    async (result: DropResult) => {
      setMovingId(null);
      if (!result.destination) return;

      const { source, destination, draggableId } = result;
      if (source.droppableId === destination.droppableId && source.index === destination.index) return;

      const entryId = parseInt(draggableId);
      const srcCol = cols.find((c) => c.stage === source.droppableId);
      const dstCol = cols.find((c) => c.stage === destination.droppableId);
      if (!srcCol || !dstCol) return;

      // Optimistic update
      const item = srcCol.items.find((i) => i.id === entryId);
      if (!item) return;

      setCols((prev) =>
        prev.map((c) => {
          if (c.stage === source.droppableId) {
            const items = c.items.filter((i) => i.id !== entryId);
            return { ...c, items, count: items.length };
          }
          if (c.stage === destination.droppableId) {
            const items = [...c.items];
            items.splice(destination.index, 0, { ...item, stage: c.stage, days_in_stage: 0 });
            return { ...c, items, count: items.length };
          }
          return c;
        })
      );

      // Server call
      try {
        await api.post("/api/pipeline/move", {
          candidate_id: item.candidate_id,
          job_id: jobId,
          stage: destination.droppableId,
        });
      } catch (err) {
        console.error("Pipeline move failed:", err);
        setCols(columns); // Revert
      }
    },
    [cols, columns, jobId]
  );

  const tabs: { key: TabFilter; label: string; color: string }[] = [
    { key: "all", label: "Wszystkie", color: "bg-gray-100 text-gray-700" },
    { key: "internal", label: "🏠 Etapy wewnętrzne", color: "bg-blue-100 text-blue-700" },
    { key: "external", label: "🏢 Etapy zewnętrzne", color: "bg-amber-100 text-amber-700" },
    { key: "terminal", label: "🏁 Zakończone", color: "bg-green-100 text-green-700" },
  ];

  return (
    <div>
      {/* Tab bar */}
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

      {/* Kanban columns */}
      <DragDropContext onDragStart={(start) => setMovingId(parseInt(start.draggableId))} onDragEnd={handleDragEnd}>
        <div className="flex gap-3 overflow-x-auto pb-4" style={{ minHeight: 300 }}>
          {filteredCols.map((col) => (
            <KanbanColumnView key={col.stage} col={col} movingId={movingId} />
          ))}
        </div>
      </DragDropContext>
    </div>
  );
}
