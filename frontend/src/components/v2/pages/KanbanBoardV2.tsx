"use client";

import * as React from"react";
import { memo, useCallback, useEffect, useMemo, useState } from"react";
import Link from"next/link";
import {
 DragDropContext,
 Draggable,
 Droppable,
 type DropResult,
} from"@hello-pangea/dnd";
import {
 AlertCircle,
 CheckCircle2,
 Clock,
 FileArchive,
 Flag,
 HelpCircle,
 LayoutGrid,
 Loader2,
 MoveRight,
 Rows3,
 Sparkles,
 Star,
 XCircle,
} from"lucide-react";
import api, { pipelineApi, pipelineTemplatesApi, type RateUnit } from"@/lib/api";
import { useAuthStore } from"@/store/auth";
import { VerifiedRateModal } from"@/components/v2/modals/VerifiedRateModal";
import {
 Dialog,
 DialogBody,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { FormField } from"@/components/ui/form-field";
import {
 BulkCvDownloadError,
 downloadBulkCvs,
} from"@/lib/bulk-cv-download";
import { cn } from"@/lib/utils";
import { useUiStore } from"@/store/ui";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Card } from"@/components/ui/card";
import { Checkbox } from"@/components/ui/checkbox";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from"@/components/ui/tooltip";
import { RejectionV2 } from"@/components/v2/modals/RejectionV2";
import { ScorecardV2 } from"@/components/v2/modals/ScorecardV2";
import { ScreeningSheet } from"@/components/v2/modals/ScreeningSheet";
import { useToast } from"@/components/Toast";

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
 // Pending verification (migracja 0056)
 verification_status?:"active" |"pending" |"rejected";
 expected_rate_value?: string | number | null;
 expected_rate_unit?: RateUnit | null;
 expected_rate_currency?: string | null;
 budget_max_at_move?: number | null;
}

const APPROVER_ROLES = new Set(["admin","delivery_lead","head_of_recruitment"]);

export interface KanbanColumn {
 stage: string;
 category?:"internal" |"external" |"terminal";
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
 internal: "bg-primary",
 external: "bg-card",
 terminal: "bg-[hsl(var(--muted-foreground))]",
};

const CATEGORY_LABEL: Record<string, string> = {
 internal: "Wewnętrzny",
 external: "Zewnętrzny",
 terminal: "Terminalny",
};

const EXTERNAL_STAGES_FOR_SCREENING = new Set(["cv_sent","client_interview","acceptance","negotiation","onboarding",
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
 density: "cozy" |"compact";
 canScreen: boolean;
 isApprover: boolean;
 onAcceptVerification?: (item: KanbanItem) => void;
 onRejectVerification?: (item: KanbanItem) => void;
}

const CandidateKanbanCard = memo(function CandidateKanbanCard({
 item,
 selected,
 onToggleSelect,
 onOpenScreening,
 density,
 canScreen,
 isApprover,
 onAcceptVerification,
 onRejectVerification,
}: CardProps) {
 const isPending = item.verification_status ==="pending";
 const fullName = `${item.name ??""} ${item.lastname ??""}`.trim() ||"Kandydat";
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
 ?"danger"
 : item.days_in_stage >= 3
 ?"warning"
 :"neutral";

 return (
 <div
 className={cn("group relative rounded-lg bg-card border border-border transition-all","hover:shadow-sm hover:border-primary/40",
 selected &&"ring-2 ring-primary border-primary",
 density ==="compact" ?"p-2" :"p-3",
 isPending &&"opacity-70 grayscale-[40%] border-amber-300 bg-amber-50/40"
 )}
 title={
 isPending
 ? `Oczekuje akceptacji weryfikacji — rate ${item.expected_rate_value} > budżet ${item.budget_max_at_move ??"?"}`
 : undefined
 }
 >
 {isPending && (
 <div className="absolute top-1 right-1 inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300 font-semibold">
 <HelpCircle className="h-2.5 w-2.5" />
 Pending
 </div>
 )}
 <div className="absolute top-1 left-1">
 <Checkbox
 checked={selected}
 onCheckedChange={() => onToggleSelect(item.id)}
 aria-label={`Zaznacz ${fullName}`}
 className="bg-card"
 />
 </div>

 <Link
 href={`/candidates/${item.candidate_id}`}
 className="block"
 onClick={(e) => e.stopPropagation()}
 >
 <div className={cn("flex items-start gap-2", density ==="compact" ?"pl-5" :"pl-5")}>
 <div
 className={cn("rounded-full bg-primary text-white font-semibold flex items-center justify-center shrink-0",
 density ==="compact" ?"h-6 w-6 text-[10px]" :"h-8 w-8 text-xs"
 )}
 >
 {initials}
 </div>
 <div className="min-w-0 flex-1">
 <div
 className={cn("font-medium text-foreground truncate",
 density ==="compact" ?"text-xs" :"text-sm"
 )}
 >
 {fullName}
 </div>
 <div
 className={cn("flex items-center gap-1.5 mt-0.5 text-[10px] text-muted-foreground"
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
 className={cn("inline-flex items-center gap-0.5",
 daysBadge ==="danger"
 ?"text-primary"
 : daysBadge ==="warning"
 ?"text-amber-600"
 :""
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

 {canScreen && density !=="compact" && !isPending && (
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onOpenScreening(item.id, fullName);
 }}
 className="absolute bottom-1 right-1 inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-semibold hover:bg-primary hover:text-white transition-colors"
 title="Screening Championa"
 >
 <Sparkles className="h-2.5 w-2.5" />
 Screening
 </button>
 )}
 {isPending && isApprover && density !=="compact" && (
 <div className="mt-2 pt-2 border-t border-amber-200 flex items-center gap-1.5">
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onAcceptVerification?.(item);
 }}
 className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-md bg-emerald-600 text-white font-semibold hover:bg-emerald-700 transition-colors"
 title="Akceptuj weryfikację"
 >
 <CheckCircle2 className="h-3 w-3" />
 Akceptuj
 </button>
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onRejectVerification?.(item);
 }}
 className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-md bg-card text-rose-700 border border-rose-300 font-semibold hover:bg-rose-50 transition-colors"
 title="Odrzuć weryfikację"
 >
 <XCircle className="h-3 w-3" />
 Odrzuć
 </button>
 </div>
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
 density: "cozy" |"compact";
 isApprover: boolean;
 onAcceptVerification: (item: KanbanItem) => void;
 onRejectVerification: (item: KanbanItem) => void;
}

const KanbanColumnV2 = memo(function KanbanColumnV2({
 col,
 selectedIds,
 onToggleSelect,
 onOpenScreening,
 density,
 isApprover,
 onAcceptVerification,
 onRejectVerification,
}: ColProps) {
 const dropId = colId(col);
 return (
 <div
 className={cn("flex-shrink-0 rounded-lg bg-background/60 border border-border",
 density ==="compact" ?"w-52" :"w-60"
 )}
 >
 <div className="px-3 py-2 border-b border-border flex items-center gap-2">
 {col.category && (
 <Tooltip>
 <TooltipTrigger asChild>
 <span
 className={cn("h-2 w-2 rounded-full shrink-0",
 CATEGORY_COLOR[col.category]
 )}
 aria-label={CATEGORY_LABEL[col.category]}
 />
 </TooltipTrigger>
 <TooltipContent side="top">{CATEGORY_LABEL[col.category]}</TooltipContent>
 </Tooltip>
 )}
 <span className="text-xs font-medium text-foreground flex-1 truncate">
 {columnLabel(col)}
 </span>
 <Badge size="sm" variant={col.count > 0 ?"soft" :"outline"}>
 {col.count}
 </Badge>
 </div>

 <Droppable droppableId={dropId}>
 {(provided, snapshot) => (
 <div
 ref={provided.innerRef}
 {...provided.droppableProps}
 className={cn("p-2 space-y-2 min-h-[180px] max-h-[540px] overflow-y-auto rounded-b-v2-m transition-colors",
 snapshot.isDraggingOver &&"bg-primary/10/60"
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
 className={cn("transition-shadow",
 dragSnapshot.isDragging &&"shadow-md rotate-1 opacity-90"
 )}
 >
 <CandidateKanbanCard
 item={item}
 selected={selectedIds.has(item.id)}
 onToggleSelect={onToggleSelect}
 onOpenScreening={onOpenScreening}
 density={density}
 canScreen={EXTERNAL_STAGES_FOR_SCREENING.has(item.stage)}
 isApprover={isApprover}
 onAcceptVerification={onAcceptVerification}
 onRejectVerification={onRejectVerification}
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
 const { showActionToast, showSuccess, showError } = useToast();
 const userRole = useAuthStore((s) => s.user?.role);
 const isApprover = !!userRole && APPROVER_ROLES.has(userRole);
 const [cols, setCols] = useState(columns);
 const [activeTab, setActiveTab] = useState<"all" |"internal" |"external" |"terminal">("all");
 const [selected, setSelected] = useState<Set<number>>(new Set());
 const [bulkBusy, setBulkBusy] = useState(false);
 const [bulkDownloadBusy, setBulkDownloadBusy] = useState(false);
 const [statusMessage, setStatusMessage] = useState<string | null>(null);
 const showStatus = useCallback((msg: string) => {
 setStatusMessage(msg);
 setTimeout(() => setStatusMessage(null), 4000);
 }, []);
 const [rejectionReasons, setRejectionReasons] = useState<
 { id: string; label: string; applies_to: ("rejected" |"withdrawn")[] }[]
 >([]);
 const [stagesWithScorecard, setStagesWithScorecard] = useState<Set<number>>(new Set());
 const [jobBudgetMax, setJobBudgetMax] = useState<number | null>(null);

 const [pendingRejection, setPendingRejection] = useState<{
 item: KanbanItem;
 destCol: KanbanColumn;
 srcColId: string;
 terminalType: "rejected" |"withdrawn";
 } | null>(null);
 // Pending verification flow (migracja 0056)
 const [verifiedRatePrompt, setVerifiedRatePrompt] = useState<{
 item: KanbanItem;
 destCol: KanbanColumn;
 srcColId: string;
 } | null>(null);
 const [pendingRejectVerification, setPendingRejectVerification] = useState<{
 item: KanbanItem;
 note: string;
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
 const sMax = jobRes.data?.salary_max;
 setJobBudgetMax(typeof sMax ==="number" ? sMax : null);
 const tid = jobRes.data?.pipeline_template_id;
 if (!tid) return;
 const detail = await pipelineTemplatesApi.get(tid);
 setRejectionReasons(
 detail.data.rejection_reasons.map((r: any) => ({
 id: r.id,
 label: r.name,
 applies_to: [r.category as"rejected" |"withdrawn"],
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
 activeTab ==="all"
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
 async (
 item: KanbanItem,
 dst: KanbanColumn,
 reason?: {
 id: string;
 notes: string;
 sendRejectionEmail?: boolean | null;
 candidateOfferResponse?:"pending" |"accepted" |"declined" | null;
 }
 ) => {
 try {
 const response = await api.post<{
 scheduled_rejection_email_id?: number | null;
 }>("/api/pipeline/move", {
 candidate_stage_id: item.id,
 to_stage: dst.stage,
 to_stage_def_id: dst.stage_def_id ?? undefined,
 rejection_reason_id: reason?.id,
 notes: reason?.notes,
 send_rejection_email: reason?.sendRejectionEmail ?? undefined,
 candidate_offer_response:
 reason?.candidateOfferResponse ?? undefined,
 });

 // 0045_rejection_emails — if the backend scheduled an auto-email,
 // offer a 10-second"Cofnij wysyłkę" toast so the recruiter can
 // abort before the 15-minute countdown elapses.
 const scheduledId = response?.data?.scheduled_rejection_email_id;
 if (scheduledId) {
 showActionToast("Email odrzucenia zostanie wysłany za 15 minut.",
 {
 actionLabel: "Cofnij wysyłkę",
 onAction: async () => {
 try {
 await api.post(`/api/rejection-emails/${scheduledId}/cancel`);
 showSuccess("Anulowano wysyłkę emaila.");
 } catch (err) {
 console.error("rejection email cancel failed", err);
 showError("Nie udało się anulować wysyłki.");
 }
 },
 durationMs: 10_000,
 }
 );
 }

 // Prompt screening if moved to external-visible stage
 if (EXTERNAL_STAGES_FOR_SCREENING.has(dst.stage)) {
 setScreeningPrompt({
 stageId: item.id,
 candidateName: `${item.name ??""} ${item.lastname ??""}`.trim() ||"Kandydat",
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
 showError("Nie udało się zmienić etapu.");
 // TODO: revert optimistic on error
 }
 },
 [stagesWithScorecard, showActionToast, showSuccess, showError]
 );

 const onDragEnd = useCallback(
 (res: DropResult) => {
 if (!res.destination) return;
 const src = cols.find((c) => colId(c) === res.source.droppableId);
 const dst = cols.find((c) => colId(c) === res.destination!.droppableId);
 if (!src || !dst || colId(src) === colId(dst)) return;
 const item = src.items[res.source.index];
 if (!item) return;

 // Pending verification (migracja 0056) — najpierw zapytaj o rate,
 // dopiero potem optimistic + sendMove. NIE applyOptimistic tu, bo
 // recruiter może anulować w modalu.
 if (dst.stage ==="verified") {
 setVerifiedRatePrompt({
 item,
 destCol: dst,
 srcColId: colId(src),
 });
 return;
 }

 applyOptimistic(item, colId(src), dst);

 if (dst.category ==="terminal" && (dst.stage ==="rejected" || dst.stage ==="withdrawn")) {
 setPendingRejection({
 item,
 destCol: dst,
 srcColId: colId(src),
 terminalType: dst.stage as"rejected" |"withdrawn",
 });
 } else {
 sendMove(item, dst);
 }
 },
 [cols, applyOptimistic, sendMove]
 );

 // Submit z modala"Zweryfikowany — podaj rate"
 const submitVerifiedMove = useCallback(
 async (payload: { rate: number; unit: RateUnit; currency: string }) => {
 if (!verifiedRatePrompt) return;
 const { item, destCol, srcColId } = verifiedRatePrompt;
 try {
 const res = await pipelineApi.move({
 candidate_id: item.candidate_id,
 job_id: jobId,
 stage: "verified",
 stage_def_id: destCol.stage_def_id ?? undefined,
 expected_rate_value: payload.rate,
 expected_rate_unit: payload.unit,
 expected_rate_currency: payload.currency,
 });
 const verifStatus = res?.data?.verification_status as
 |"active"
 |"pending"
 | undefined;
 // Zaktualizuj kolumnę z faktycznym statusem (nie zgaduj — backend wie).
 setCols((prev) =>
 prev.map((c) => {
 if (colId(c) === srcColId) {
 const items = c.items.filter((i) => i.id !== item.id);
 return { ...c, items, count: items.length };
 }
 if (colId(c) === colId(destCol)) {
 const enriched: KanbanItem = {
 ...item,
 stage: destCol.stage,
 days_in_stage: 0,
 verification_status: verifStatus ??"active",
 expected_rate_value: payload.rate,
 expected_rate_unit: payload.unit,
 expected_rate_currency: payload.currency,
 budget_max_at_move: jobBudgetMax,
 };
 const items = [...c.items, enriched];
 return { ...c, items, count: items.length };
 }
 return c;
 })
 );
 if (verifStatus ==="pending") {
 showSuccess("Wysłano do akceptacji delivery_lead. Karta będzie aktywna po zatwierdzeniu."
 );
 }
 } catch (e) {
 console.error("Move to verified failed", e);
 showError("Nie udało się przesunąć kandydata.");
 } finally {
 setVerifiedRatePrompt(null);
 }
 },
 [verifiedRatePrompt, jobId, jobBudgetMax, showSuccess, showError]
 );

 const handleAcceptVerification = useCallback(
 async (item: KanbanItem) => {
 try {
 await pipelineApi.acceptVerification(item.id);
 setCols((prev) =>
 prev.map((c) => ({
 ...c,
 items: c.items.map((i) =>
 i.id === item.id ? { ...i, verification_status: "active" } : i
 ),
 }))
 );
 showSuccess("Weryfikacja zaakceptowana.");
 } catch (e) {
 console.error("Accept verification failed", e);
 showError("Nie udało się zaakceptować weryfikacji.");
 }
 },
 [showSuccess, showError]
 );

 const submitRejectVerification = useCallback(async () => {
 if (!pendingRejectVerification) return;
 const { item, note } = pendingRejectVerification;
 if (!note.trim()) return;
 try {
 await pipelineApi.rejectVerification(item.id, note.trim());
 // Odśwież widok — backend tworzy nowy CandidateStage z poprzednim
 // stage'em, więc najprościej ponownie pobrać kanban dla joba.
 const fresh = await pipelineApi.kanban(jobId);
 if (Array.isArray(fresh.data?.columns)) {
 setCols(fresh.data.columns as KanbanColumn[]);
 }
 showSuccess("Weryfikacja odrzucona — kandydat wrócił na poprzedni stage.");
 } catch (e) {
 console.error("Reject verification failed", e);
 showError("Nie udało się odrzucić weryfikacji.");
 } finally {
 setPendingRejectVerification(null);
 }
 }, [pendingRejectVerification, jobId, showSuccess, showError]);

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

 const bulkDownloadCvs = async () => {
 if (selected.size === 0 || bulkDownloadBusy) return;
 const candidateIds = Array.from(
 new Set(
 cols
 .flatMap((c) => c.items)
 .filter((i) => selected.has(i.id))
 .map((i) => i.candidate_id)
 )
 );
 if (candidateIds.length === 0) return;
 setBulkDownloadBusy(true);
 showStatus("Przygotowywanie ZIP…");
 try {
 const { includedCount, skippedCount } = await downloadBulkCvs(candidateIds);
 showStatus(
 skippedCount > 0
 ? `Pobrano ${includedCount} CV. Pominięto: ${skippedCount} (brak CV).`
 : `Pobrano ${includedCount} CV.`
 );
 } catch (e) {
 showStatus(
 e instanceof BulkCvDownloadError
 ? e.message
 :"Pobieranie nie powiodło się."
 );
 } finally {
 setBulkDownloadBusy(false);
 }
 };

 return (
 <div className="space-y-3">
 {/* Toolbar */}
 <div className="flex items-center gap-2 flex-wrap">
 {/* Swimlane / category tabs */}
 <div className="inline-flex gap-1 bg-card rounded-lg p-1 border border-border">
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
 className={cn("px-3 py-1.5 text-xs rounded-md font-medium transition-colors",
 activeTab === t.v
 ?"bg-primary text-white"
 :"text-muted-foreground hover:text-foreground"
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
 onClick={() => setDensity(density ==="cozy" ?"compact" :"cozy")}
 className="h-8 w-8 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-primary/10 hover:text-foreground"
 >
 {density ==="compact" ? (
 <LayoutGrid className="h-4 w-4" />
 ) : (
 <Rows3 className="h-4 w-4" />
 )}
 </button>
 </TooltipTrigger>
 <TooltipContent>
 Gęstość: {density ==="compact" ?"kompaktowa" :"cozy"}
 </TooltipContent>
 </Tooltip>
 </div>
 </div>

 {/* Bulk action bar */}
 {selected.size > 0 && (
 <Card className="!p-3 flex items-center gap-3 flex-wrap bg-card text-foreground border-white/10">
 <Flag className="h-4 w-4" />
 <span className="text-sm font-medium">
 Wybrano: <strong>{selected.size}</strong>
 </span>
 <div className="inline-flex items-center gap-2 text-xs ml-2">
 <MoveRight className="h-3.5 w-3.5" />
 <span>Przenieś do:</span>
 <Select onValueChange={bulkMove}>
 <SelectTrigger className="h-8 w-[220px] bg-card/10 text-foreground border-white/20">
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
 <Button
 size="sm"
 variant="secondary"
 onClick={bulkDownloadCvs}
 disabled={bulkDownloadBusy || bulkBusy}
 >
 {bulkDownloadBusy ? (
 <Loader2 className="h-3.5 w-3.5 animate-spin" />
 ) : (
 <FileArchive className="h-3.5 w-3.5" />
 )}{""}
 Pobierz CV (ZIP)
 </Button>
 <button
 onClick={() => setSelected(new Set())}
 disabled={bulkBusy || bulkDownloadBusy}
 className="ml-auto text-xs text-foreground/70 hover:text-foreground"
 >
 Wyczyść
 </button>
 </Card>
 )}

 {statusMessage && (
 <div
 role="status"
 className="text-xs rounded-md px-3 py-2 bg-primary/10 text-primary border border-primary/20"
 >
 {statusMessage}
 </div>
 )}

 {/* Board */}
 <DragDropContext onDragEnd={onDragEnd}>
 <div className="flex gap-3 overflow-x-auto pb-4" style={{ minHeight: 300 }}>
 {filtered.length === 0 ? (
 <div className="w-full py-12 text-center text-sm text-muted-foreground">
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
 isApprover={isApprover}
 onAcceptVerification={handleAcceptVerification}
 onRejectVerification={(item) =>
 setPendingRejectVerification({ item, note: "" })
 }
 />
 ))
 )}
 </div>
 </DragDropContext>

 {/* Modals */}
 <RejectionV2
 open={pendingRejection !== null}
 onOpenChange={(v) => !v && setPendingRejection(null)}
 terminalType={pendingRejection?.terminalType ??"rejected"}
 reasons={rejectionReasons}
 previousStageCategory={(() => {
 if (!pendingRejection) return null;
 const cat = cols.find((c) => colId(c) === pendingRejection.srcColId)
 ?.category;
 return cat ==="external" ?"external" : cat ==="internal" ?"internal" : null;
 })()}
 previousStage={
 pendingRejection
 ? cols.find((c) => colId(c) === pendingRejection.srcColId)?.stage ??
 null
 : null
 }
 onConfirm={(
 reasonId,
 notes,
 sendRejectionEmail,
 candidateOfferResponse
 ) => {
 if (!pendingRejection) return;
 sendMove(pendingRejection.item, pendingRejection.destCol, {
 id: reasonId,
 notes,
 sendRejectionEmail,
 candidateOfferResponse: candidateOfferResponse ?? null,
 });
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

 {/* Pending verification modal — recruiter wpisuje rate */}
 {verifiedRatePrompt && (
 <VerifiedRateModal
 open={true}
 onOpenChange={(v) => !v && setVerifiedRatePrompt(null)}
 candidateName={
 `${verifiedRatePrompt.item.name ??""} ${verifiedRatePrompt.item.lastname ??""}`.trim() ||"Kandydat"
 }
 jobBudgetMax={jobBudgetMax}
 onConfirm={submitVerifiedMove}
 />
 )}

 {/* Reject verification modal — approver wpisuje notatkę */}
 {pendingRejectVerification && (
 <Dialog
 open={true}
 onOpenChange={(v: boolean) => !v && setPendingRejectVerification(null)}
 >
 <DialogContent>
 <DialogHeader>
 <DialogTitle>Odrzuć weryfikację</DialogTitle>
 <DialogDescription>
 Kandydat wróci na poprzedni stage z notatką. Ta akcja jest
 widoczna w historii pipeline'a.
 </DialogDescription>
 </DialogHeader>
 <DialogBody>
 <FormField label="Powód odrzucenia">
 <textarea
 value={pendingRejectVerification.note}
 onChange={(e) =>
 setPendingRejectVerification((p) =>
 p ? { ...p, note: e.target.value } : null
 )
 }
 placeholder="np. Stawka za wysoka, max 22000 PLN"
 rows={4}
 className="w-full px-3 py-2 rounded-md border border-border bg-card focus:outline-none focus:ring-2 focus:ring-primary"
 autoFocus
 />
 </FormField>
 </DialogBody>
 <DialogFooter>
 <Button
 variant="ghost"
 onClick={() => setPendingRejectVerification(null)}
 >
 Anuluj
 </Button>
 <Button
 onClick={submitRejectVerification}
 disabled={!pendingRejectVerification.note.trim()}
 >
 Odrzuć i wróć
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 )}
 </div>
 );
}
