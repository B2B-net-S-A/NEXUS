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
import { ScorecardModal } from "./ScorecardModal";
import { ScreeningModal } from "./ScreeningModal";
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
  name?: string;
  lastname?: string;
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

const EXTERNAL_STAGES_FOR_SCREENING = new Set([
  "cv_sent",
  "client_interview",
  "acceptance",
  "negotiation",
  "onboarding",
]);

const KanbanColumnView = memo(function KanbanColumnView({
  col,
  selectedIds,
  onToggleSelect,
  onOpenScreening,
}: {
  col: KanbanColumn;
  selectedIds: Set<number>;
  onToggleSelect: (id: number) => void;
  onOpenScreening: (stageId: number, candidateName: string) => void;
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
                    className={`relative transition-shadow ${
                      dragSnapshot.isDragging
                        ? "shadow-lg rotate-1 opacity-90"
                        : "shadow-none"
                    } ${
                      selectedIds.has(item.id)
                        ? "ring-2 ring-blue-500 rounded-lg"
                        : ""
                    }`}
                  >
                    <label
                      className="absolute top-1 left-1 z-10 flex items-center bg-white/80 dark:bg-gray-900/80 rounded p-0.5 cursor-pointer"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        className="w-3 h-3"
                        checked={selectedIds.has(item.id)}
                        onChange={() => onToggleSelect(item.id)}
                      />
                    </label>
                    <CandidateCard
                      candidateId={item.candidate_id}
                      stage={item.stage}
                      rating={item.rating}
                      daysInStage={item.days_in_stage}
                    />
                    {EXTERNAL_STAGES_FOR_SCREENING.has(item.stage) && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          e.preventDefault();
                          onOpenScreening(
                            item.id,
                            `${item.name ?? ""} ${item.lastname ?? ""}`.trim() ||
                              "Kandydat"
                          );
                        }}
                        className="absolute bottom-1 right-1 text-[9px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 hover:bg-purple-200 font-semibold"
                        title="Screening Championa"
                        data-testid={`open-screening-${item.id}`}
                      >
                        ★ Screening
                      </button>
                    )}
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
  // Stage def ids that have a non-empty scorecard_schema.questions[]
  const [stagesWithScorecard, setStagesWithScorecard] = useState<Set<number>>(new Set());
  // Scorecard prompt after a successful move
  // Phase 10: screening prompt when moving to cv_sent or later.
  const [screeningPrompt, setScreeningPrompt] = useState<{
    stageId: number;
    candidateName: string;
  } | null>(null);

  const [scorecardPrompt, setScorecardPrompt] = useState<{
    candidateStageId: number;
    stageId: number;
    stageDefId: number;
    stageName: string;
  } | null>(null);
  // Phase 4: multi-select + bulk move
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

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
          const withScorecard = new Set<number>();
          for (const s of detail.data.stages ?? []) {
            const schema = (s as { scorecard_schema?: { questions?: unknown[] } }).scorecard_schema;
            if (schema && Array.isArray(schema.questions) && schema.questions.length > 0) {
              withScorecard.add(s.id);
            }
          }
          setStagesWithScorecard(withScorecard);
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
        const res = await api.post("/api/pipeline/move", {
          candidate_id: item.candidate_id,
          job_id: jobId,
          // Send BOTH — server accepts either
          stage: dstCol.stage,
          stage_def_id: dstCol.stage_def_id ?? undefined,
          rejection_reason_id: rejectionReasonId,
        });
        // Prompt for scorecard if target stage has a schema (non-terminal only)
        const newStageId = res.data?.id as number | undefined;
        const newStageDefId = res.data?.stage_def_id as number | null | undefined;
        if (
          newStageId &&
          newStageDefId &&
          stagesWithScorecard.has(newStageDefId) &&
          dstCol.category !== "terminal"
        ) {
          setScorecardPrompt({
            candidateStageId: newStageId,
            stageId: newStageId,
            stageDefId: newStageDefId,
            stageName: dstCol.name ?? dstCol.stage,
          });
        }

        // Phase 10: Champion screening prompt when moving to cv_sent or any
        // external stage — recruiter must capture answers before the client
        // reviews the CV.
        const EXTERNAL_STAGES = new Set([
          "cv_sent",
          "client_interview",
          "acceptance",
          "negotiation",
          "onboarding",
        ]);
        if (newStageId && EXTERNAL_STAGES.has(dstCol.stage)) {
          setScreeningPrompt({
            stageId: newStageId,
            candidateName: `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat",
          });
        }
      } catch (err) {
        console.error("Pipeline move failed:", err);
        setCols(columns); // revert to server truth
      }
    },
    [jobId, columns, stagesWithScorecard]
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

  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clearSelection = () => setSelected(new Set());

  const bulkMoveTo = async (targetCol: KanbanColumn) => {
    if (selected.size === 0) return;
    const idsArr = Array.from(selected);
    const rowsById = new Map<number, KanbanItem>();
    cols.forEach((c) => c.items.forEach((i) => rowsById.set(i.id, i)));

    setBulkBusy(true);
    try {
      // Use the existing /api/pipeline/bulk-move endpoint for atomic server move
      const candidateIds = idsArr
        .map((id) => rowsById.get(id)?.candidate_id)
        .filter((x): x is number => typeof x === "number");
      await api.post("/api/pipeline/bulk-move", {
        candidate_ids: candidateIds,
        job_id: jobId,
        stage: targetCol.stage,
      });
      // Refetch by reverting to server state — parent holds the source of truth
      setCols(columns);
      clearSelection();
    } catch (err) {
      console.error("bulk-move failed:", err);
      alert("Nie udało się wykonać bulk move.");
    } finally {
      setBulkBusy(false);
    }
  };

  return (
    <div>
      {/* Phase 4: bulk action bar */}
      {selected.size > 0 && (
        <div className="mb-3 flex items-center gap-3 rounded-lg bg-blue-600 text-white px-3 py-2 shadow">
          <span className="text-sm font-medium">
            {selected.size} zaznaczonych
          </span>
          <span className="text-xs opacity-80">Przenieś do:</span>
          <select
            onChange={(e) => {
              const cid = e.target.value;
              const target = cols.find((c) => colId(c) === cid);
              if (target) bulkMoveTo(target);
              e.currentTarget.selectedIndex = 0;
            }}
            disabled={bulkBusy}
            className="text-xs rounded bg-white/20 border border-white/30 text-white px-2 py-1 focus:bg-white/30"
            data-testid="bulk-move-select"
          >
            <option value="">-- wybierz etap --</option>
            {cols
              .filter((c) => c.category !== "terminal")
              .map((c) => (
                <option
                  key={colId(c)}
                  value={colId(c)}
                  className="text-gray-900"
                >
                  {c.name ?? c.stage}
                </option>
              ))}
          </select>
          <button
            onClick={clearSelection}
            className="ml-auto text-xs hover:underline"
          >
            Wyczyść zaznaczenie
          </button>
        </div>
      )}

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
            <KanbanColumnView
              key={colId(col)}
              col={col}
              selectedIds={selected}
              onToggleSelect={toggleSelect}
              onOpenScreening={(stageId, candidateName) =>
                setScreeningPrompt({ stageId, candidateName })
              }
            />
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

      {scorecardPrompt && (
        <ScorecardModal
          candidateStageId={scorecardPrompt.candidateStageId}
          stageId={scorecardPrompt.stageId}
          stageDefId={scorecardPrompt.stageDefId}
          stageName={scorecardPrompt.stageName}
          onClose={() => setScorecardPrompt(null)}
          onSaved={() => setScorecardPrompt(null)}
        />
      )}

      {screeningPrompt && (
        <ScreeningModal
          stageId={screeningPrompt.stageId}
          candidateName={screeningPrompt.candidateName}
          onClose={() => setScreeningPrompt(null)}
          onSubmitted={() => setScreeningPrompt(null)}
        />
      )}

      {templateId === null && (
        <p className="text-xs text-gray-400 mt-2">
          Ten projekt nie ma przypisanego procesu — używany jest domyślny.
        </p>
      )}
    </div>
  );
}
