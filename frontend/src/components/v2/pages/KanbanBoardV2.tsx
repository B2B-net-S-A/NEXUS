"use client";

import * as React from"react";
import { memo, useCallback, useEffect, useRef, useState } from"react";
import { useQueryClient } from"@tanstack/react-query";
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
 Trash2,
 UserX,
 XCircle,
} from"lucide-react";
import api, {
 candidatesApi,
 pipelineApi,
 pipelineTemplatesApi,
 type RateUnit,
} from"@/lib/api";
import { candidatePipelinesQueryKey } from"@/components/CandidatePipelinesWidget";
import { getUserRoles, useAuthStore } from"@/store/auth";
import { VerifiedRateModal } from"@/components/v2/modals/VerifiedRateModal";
import { ClientRateModal } from"@/components/v2/modals/ClientRateModal";
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
import { cn, formatDate } from"@/lib/utils";
import { encodeJobBackRef } from"@/lib/url-filters";
import { celebrate } from "@/lib/celebrate";
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
import { terminalOf } from"@/lib/kanban-terminal";
import { assignErrorMessage } from "@/lib/assign-error";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import type { CandidateContactSummary } from "@/lib/candidate-contact";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";

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
 // Kto przypisał kandydata do tej rekrutacji (rekruter z najwcześniejszego
 // etapu pary kandydat/oferta) i kiedy — pokazywane w tooltipie karty.
 added_to_job_by_name?: string | null;
 added_to_job_at?: string | null;
 // Pending verification (migracja 0056)
 verification_status?:"active" |"pending" |"rejected";
 expected_rate_value?: string | number | null;
 expected_rate_unit?: RateUnit | null;
 expected_rate_currency?: string | null;
 budget_max_at_move?: number | null;
 // Hiring manager tej oferty odrzucił już tego kandydata po rozmowie na innej
 // rekrutacji. Manager jest domyślny (to manager tej oferty), więc chip nie
 // niesie nazwiska — kto/kiedy/dlaczego siedzi w tooltipie.
 hm_veto?: {
  hiring_manager_contact_id: number;
  hiring_manager_name?: string | null;
  source_job_id: number;
  source_job_title?: string | null;
  rejected_at: string;
  rejection_reason_name: string;
  rejection_note?: string | null;
 } | null;
 contact_case?: CandidateContactSummary | null;
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
 /** KTÓRY terminal, nie tylko „czy terminal".
  *
  *  Kolumna bez mapowania na legacy enum raportuje `stage: "new"`, więc
  *  rozpoznawanie terminala po `stage` gubiło WŁASNE etapy terminalne:
  *  „odrzucony" nie otwierał modala powodu (backend odbijał 422), a
  *  „zatrudniony" pomijał potwierdzenie mimo skutków ubocznych. */
 terminal_type?: "hired" | "rejected" | "withdrawn" | null;
}

interface KanbanBoardV2Props {
 columns: KanbanColumn[];
 jobId: number;
 // AI match scores (0-100) keyed by candidate_id → score ring on each card.
 // Kept as a candidate-keyed map (not embedded in items) so it survives the
 // optimistic-move / "verified" item rebuilds below.
 scoreMap?: Map<number, number>;
 // True while the scores query is first resolving → cards show a placeholder
 // ring instead of nothing (cold pipelines don't look broken).
 scoresLoading?: boolean;
 // Stan zwinięcia nagłówka oferty (parent steruje). Sam w sobie nie zmienia
 // wysokości — służy jako trigger re-pomiaru: gdy nagłówek się zwija/rozwija,
 // board przesuwa się w pionie i kolumny muszą przeliczyć wysokość, żeby
 // wypełnić zwolnioną przestrzeń (inaczej zostaje dziura na dole).
 headerCollapsed?: boolean;
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

// Screening Championa odpalamy przy weryfikacji kandydata (stage „verified" —
// patrz submitVerifiedMove), NIE przy „cv_sent". Te etapy zewnętrzne zostają
// jako dodatkowe punkty re-screeningu przed kontaktem z klientem.
const EXTERNAL_STAGES_FOR_SCREENING = new Set(["client_interview","acceptance","negotiation","onboarding",
]);

const colId = (col: KanbanColumn) =>
 col.stage_def_id ? `def:${col.stage_def_id}` : `stage:${col.stage}`;

const columnLabel = (col: KanbanColumn) => col.name ?? col.stage;

// ── Stage summary strip ──────────────────────────────────────────────
// Przy długich pipeline'ach (10+ etapów) liczników w nagłówkach kolumn nie
// widać bez poziomego scrollowania. Ten pasek pokazuje WSZYSTKIE etapy
// z licznikami w jednym zawijanym wierszu nad boardem; klik w pigułkę
// przewija board do danej kolumny.

const StageSummaryStrip = memo(function StageSummaryStrip({
 cols,
 onJump,
}: {
 cols: KanbanColumn[];
 onJump: (id: string) => void;
}) {
 const total = cols.reduce(
 (sum, c) => sum + (c.category === "terminal" ? 0 : c.count),
 0
 );
 return (
 <div className="flex flex-wrap items-center gap-1.5" role="navigation" aria-label="Podsumowanie etapów">
 <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 text-primary border border-primary/20 px-2.5 py-1 text-xs font-semibold">
 W procesie: <span className="tabular-nums">{total}</span>
 </span>
 {cols.map((col) => (
 <button
 key={colId(col)}
 type="button"
 onClick={() => onJump(colId(col))}
 title={`Przewiń do kolumny „${columnLabel(col)}”`}
 className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
 col.count > 0
 ?"border-border bg-card text-foreground hover:border-primary/40 hover:bg-primary/5" :"border-border/60 bg-transparent text-muted-foreground/60 hover:text-muted-foreground hover:bg-card/60"
 )}
 >
 {col.category && (
 <span
 className={cn("h-1.5 w-1.5 rounded-full shrink-0 ring-1 ring-border",
 CATEGORY_COLOR[col.category]
 )}
 aria-hidden
 />
 )}
 <span className="truncate max-w-[160px]">{columnLabel(col)}</span>
 <span
 className={cn("font-semibold tabular-nums",
 col.count > 0 &&"text-primary"
 )}
 >
 {col.count}
 </span>
 </button>
 ))}
 </div>
 );
});

// ── AI match score ring ──────────────────────────────────────────────
// Circular badge mirroring the hybrid AI match score (0-100): colored arc +
// number. Tiers use FIXED hues (not --primary) so the traffic-light reading
// stays stable across the user-selectable theme palettes / kids mode.

function scoreRingColor(score: number): string {
 if (score >= 75) return "text-emerald-500";
 if (score >= 50) return "text-sky-500";
 if (score >= 25) return "text-amber-500";
 return "text-rose-400";
}

// `score == null` → loading placeholder (muted, pulsing, no number); shown
// while the scores query is still resolving so cold pipelines don't look broken.
const ScoreRing = memo(function ScoreRing({
 score,
 density,
}: {
 score: number | null;
 density: "cozy" |"compact";
}) {
 const compact = density === "compact";
 const size = compact ? 28 : 40;
 const stroke = compact ? 3 : 3.5;
 const r = (size - stroke) / 2;
 const circ = 2 * Math.PI * r;

 if (score == null) {
 return (
 <div
 className={cn("relative shrink-0 self-center animate-pulse",
 compact ?"h-7 w-7" :"h-10 w-10"
 )}
 aria-label="Obliczanie dopasowania AI…"
 >
 <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full">
 <circle
 cx={size / 2}
 cy={size / 2}
 r={r}
 fill="none"
 strokeWidth={stroke}
 className="stroke-current text-muted-foreground/20"
 />
 </svg>
 </div>
 );
 }

 const pct = Math.max(0, Math.min(100, Math.round(score)));
 const dash = (pct / 100) * circ;
 const color = scoreRingColor(pct);
 return (
 <Tooltip>
 <TooltipTrigger asChild>
 <div
 className={cn("relative shrink-0 self-center", compact ?"h-7 w-7" :"h-10 w-10")}
 aria-label={`Dopasowanie AI: ${pct} na 100`}
 >
 <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full -rotate-90">
 <circle
 cx={size / 2}
 cy={size / 2}
 r={r}
 fill="none"
 strokeWidth={stroke}
 className="stroke-current text-muted-foreground/20"
 />
 <circle
 cx={size / 2}
 cy={size / 2}
 r={r}
 fill="none"
 strokeWidth={stroke}
 strokeLinecap="round"
 strokeDasharray={`${dash} ${circ - dash}`}
 className={cn("stroke-current transition-all", color)}
 />
 </svg>
 <span
 className={cn("absolute inset-0 flex items-center justify-center font-bold",
 compact ?"text-[10px]" :"text-xs",
 color
 )}
 >
 {pct}
 </span>
 </div>
 </TooltipTrigger>
 <TooltipContent side="top">Dopasowanie AI: {pct}/100</TooltipContent>
 </Tooltip>
 );
});

// ── Card ─────────────────────────────────────────────────────────────

interface CardProps {
 item: KanbanItem;
 jobId: number;
 selected: boolean;
 onToggleSelect: (id: number) => void;
 onOpenScreening: (stageId: number, name: string) => void;
 density: "cozy" |"compact";
 canScreen: boolean;
 isApprover: boolean;
 matchScore?: number;
 scoresLoading?: boolean;
 onAcceptVerification?: (item: KanbanItem) => void;
 onRejectVerification?: (item: KanbanItem) => void;
 onRemoveFromRecruitment: (item: KanbanItem) => void;
 contactFeatureEnabled: boolean;
}

const CandidateKanbanCard = memo(function CandidateKanbanCard({
 item,
 jobId,
 selected,
 onToggleSelect,
 onOpenScreening,
 density,
 canScreen,
 isApprover,
 matchScore,
 scoresLoading,
 onAcceptVerification,
 onRejectVerification,
 onRemoveFromRecruitment,
 contactFeatureEnabled,
}: CardProps) {
 const isPending = item.verification_status === "pending";
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

 // Kto przypisał kandydata do tej rekrutacji (+ kiedy) — tooltip na hover karty.
 const addedAttribution = item.added_to_job_by_name
 ? `Dodany do rekrutacji przez: ${item.added_to_job_by_name}${
 item.added_to_job_at ? ` · ${formatDate(item.added_to_job_at)}` :""
 }`
 : item.added_to_job_at
 ? `Dodany do rekrutacji: ${formatDate(item.added_to_job_at)}`
 : undefined;

 return (
 <div
 className={cn("group relative rounded-lg bg-card border border-border transition-all","hover:shadow-xs hover:border-primary/40",
 selected &&"ring-2 ring-primary border-primary",
 density === "compact" ?"p-2" :"p-5",
 isPending &&"opacity-70 grayscale-40 border-amber-300 bg-amber-50/40",
 // Świadomie bez grayscale/opacity — to sygnatura „pending" i czytałaby
 // się jako „nieaktywny". Ten kandydat jest aktywny, tylko nie dla tego
 // managera.
 item.hm_veto && !isPending &&"border-destructive/50"
 )}
 title={
 isPending
 ? `Oczekuje akceptacji weryfikacji — rate ${item.expected_rate_value} > budżet ${item.budget_max_at_move ??"?"}`
 : addedAttribution
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
 href={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
 className="block"
 onClick={(e) => e.stopPropagation()}
 >
 <div className={cn("flex items-start gap-2", density === "compact" ?"pl-5" :"pl-5")}>
 <div
 className={cn("rounded-full bg-primary text-white font-semibold flex items-center justify-center shrink-0",
 density === "compact" ?"h-6 w-6 text-[10px]" :"h-12 w-12 text-lg"
 )}
 >
 {initials}
 </div>
 <div className="min-w-0 flex-1">
 <div
 className={cn("font-medium text-foreground truncate",
 density === "compact" ?"text-sm" :"text-2xl"
 )}
 >
 {fullName}
 </div>
 {contactFeatureEnabled ? (
 <ContactStatusBadge
 contactCase={item.contact_case}
 className="mt-1"
 />
 ) : null}
 <div
 className={cn("flex items-center gap-1.5 mt-0.5 text-muted-foreground",
 density === "compact" ?"text-xs" :"text-base"
 )}
 >
 {item.rating != null && item.rating > 0 && (
 <span className="inline-flex items-center gap-0.5">
 <Star className={cn("fill-amber-500 text-amber-500", density === "compact" ?"h-3 w-3" :"h-4 w-4")} />
 {item.rating.toFixed(1)}
 </span>
 )}
 {daysBadge && (
 <span
 className={cn("inline-flex items-center gap-0.5",
 daysBadge === "danger"
 ?"text-primary"
 : daysBadge === "warning"
 ?"text-amber-600"
 :""
 )}
 >
 <Clock className={density === "compact" ?"h-3 w-3" :"h-4 w-4"} />
 {item.days_in_stage}d
 </span>
 )}
 {item.hm_veto && (
 <span
 className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-destructive/10 text-destructive"
 title={[
 `${item.hm_veto.hiring_manager_name ?? "Hiring manager tej rekrutacji"} odrzucił(a) tego kandydata po rozmowie ${formatDate(item.hm_veto.rejected_at)}`,
 `Powód: ${item.hm_veto.rejection_reason_name}`,
 item.hm_veto.source_job_title
 ? `Rekrutacja: ${item.hm_veto.source_job_title}`
 : null,
 "Nie proponuj go temu managerowi ponownie.",
 ]
 .filter(Boolean)
 .join("\n")}
 >
 <UserX className={density === "compact" ?"h-3 w-3" :"h-3.5 w-3.5"} />
 Weto HM
 </span>
 )}
 </div>
 </div>
 {!isPending && (matchScore != null || scoresLoading) && (
 <ScoreRing score={matchScore ?? null} density={density} />
 )}
 </div>
 </Link>

 {/* Usuń z rekrutacji — akcja korekcyjna („dodano nie tego kandydata").
 Hover-revealed, żeby nie zaśmiecać karty; przesunięta niżej na kartach
 „pending", gdzie prawy górny róg zajmuje badge weryfikacji. */}
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onRemoveFromRecruitment(item);
 }}
 className={cn("absolute right-1 z-10 inline-flex items-center justify-center rounded-md bg-card/80 text-muted-foreground opacity-0 transition-opacity","hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-hidden",
 density === "compact" ?"h-5 w-5" :"h-6 w-6",
 isPending ?"top-7" :"top-1"
 )}
 title="Usuń kandydata z tej rekrutacji"
 aria-label={`Usuń ${fullName} z rekrutacji`}
 >
 <Trash2 className={density === "compact" ?"h-3 w-3" :"h-3.5 w-3.5"} />
 </button>

 {canScreen && !isPending && (
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
 {isPending && isApprover && (
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
 jobId: number;
 selectedIds: Set<number>;
 onToggleSelect: (id: number) => void;
 onOpenScreening: (stageId: number, name: string) => void;
 density: "cozy" |"compact";
 isApprover: boolean;
 scoreMap?: Map<number, number>;
 scoresLoading?: boolean;
 onAcceptVerification: (item: KanbanItem) => void;
 onRejectVerification: (item: KanbanItem) => void;
 onRemoveFromRecruitment: (item: KanbanItem) => void;
 contactFeatureEnabled: boolean;
}

const KanbanColumnV2 = memo(function KanbanColumnV2({
 col,
 jobId,
 selectedIds,
 onToggleSelect,
 onOpenScreening,
 density,
 isApprover,
 scoreMap,
 scoresLoading,
 onAcceptVerification,
 onRejectVerification,
 onRemoveFromRecruitment,
 contactFeatureEnabled,
}: ColProps) {
 const dropId = colId(col);
 return (
 <div
 data-colid={dropId}
 className={cn("flex flex-col shrink-0 rounded-lg bg-background/60 border border-border",
 density === "compact" ?"w-60" :"w-96"
 )}
 >
 <div className={cn("sticky top-0 z-10 rounded-t-lg bg-background/95 backdrop-blur-xs border-b border-border flex items-center gap-2", density === "compact" ?"px-3 py-2" :"px-4 py-3")}>
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
 <span className={cn("text-foreground flex-1 truncate", density === "compact" ?"text-sm font-medium" :"text-xl font-semibold")}>
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
 className={cn(
 // Kolumna wypełnia wysokość boardu (flex-1), a sam board (przodek) jest
 // JEDYNYM scroll-kontenerem (oba kierunki). Dzięki temu @hello-pangea/dnd
 // śledzi scroll boardu i trafienia dropa zgadzają się z kursorem nawet po
 // auto-scrollu. Brak własnego overflow-y kolumny = brak zagnieżdżonego
 // scroll-kontenera (biblioteka go nie wspiera → wcześniej kursor mapował
 // się na złą kolumnę po poziomym auto-scrollu).
 "flex-1 p-2 space-y-2 rounded-b-v2-m transition-colors",
 snapshot.isDraggingOver &&"bg-primary/10"
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
 dragSnapshot.isDragging &&"relative z-20 shadow-md rotate-1 opacity-90"
 )}
 >
 <CandidateKanbanCard
 item={item}
 jobId={jobId}
 selected={selectedIds.has(item.id)}
 onToggleSelect={onToggleSelect}
 onOpenScreening={onOpenScreening}
 density={density}
 canScreen={EXTERNAL_STAGES_FOR_SCREENING.has(item.stage)}
 isApprover={isApprover}
 matchScore={scoreMap?.get(item.candidate_id)}
 scoresLoading={scoresLoading}
 onAcceptVerification={onAcceptVerification}
 onRejectVerification={onRejectVerification}
 onRemoveFromRecruitment={onRemoveFromRecruitment}
 contactFeatureEnabled={contactFeatureEnabled}
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

// Dół boardu: pb-4 kontenera (16px) + dolny padding <main> (24px). Tyle zostawiamy
// pod kolumnami, żeby strona nie scrollowała się w pionie pod pipeline.
const BOARD_BOTTOM_GAP = 40;
// Podłoga wysokości kolumny na małych ekranach (min-height wygrywa z height).
const MIN_COLUMN_HEIGHT = 280;

export function KanbanBoardV2({ columns, jobId, scoreMap, scoresLoading, headerCollapsed }: KanbanBoardV2Props) {
 const density = useUiStore((s) => s.density);
 const setDensity = useUiStore((s) => s.setDensity);
 const queryClient = useQueryClient();
 const contactFeature = useCandidateContactFeature();
 const { showActionToast, showSuccess, showError } = useToast();
 // M4 PR-03: pełny zbiór ról (primary + secondary), nie tylko primary —
 // hybrydowy TAC+DL ma widzieć akcje approvera (parity z backendem #782).
 const authUser = useAuthStore((s) => s.user);
 const isApprover = getUserRoles(authUser).some((r) => APPROVER_ROLES.has(r));
 const [cols, setCols] = useState(columns);
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
 // M4 PR-03 (audyt P1.6): potwierdzenie przed hired — ruch tworzy draft
 // kontraktu + zamówienia, nie powinien być skutkiem samego puszczenia myszy.
 const [hiredConfirm, setHiredConfirm] = useState<{
 item: KanbanItem;
 destCol: KanbanColumn;
 srcColId: string;
 } | null>(null);
 const [jobBudgetMax, setJobBudgetMax] = useState<number | null>(null);

 // --- Wysokość kolumn liczona dynamicznie od realnej pozycji boardu ---------
 // Problem: stary `h-[calc(100vh-350px)]` miał na sztywno offset 350px = wysokość
 // rozwiniętego nagłówka. Po zwinięciu nagłówka treść nad boardem maleje, ale
 // offset zostaje 350 → board się nie rozciąga i na dole robi się dziura.
 // Fix: mierzymy `getBoundingClientRect().top` boardu i wypełniamy resztę
 // viewportu. Adaptuje się do KAŻDEGO stanu nagłówka (zwinięty/rozwinięty,
 // z opisem/bez, zawijające się przyciski) — bez magicznych liczb.
 const boardRef = useRef<HTMLDivElement>(null);
 const [columnHeight, setColumnHeight] = useState<number | undefined>(undefined);
 const measureColumnHeight = useCallback(() => {
 const el = boardRef.current;
 if (!el || typeof window === "undefined") return;
 const top = el.getBoundingClientRect().top;
 const next = Math.max(
 MIN_COLUMN_HEIGHT,
 Math.round(window.innerHeight - top - BOARD_BOTTOM_GAP)
 );
 setColumnHeight((prev) => (prev === next ? prev : next));
 }, []);
 // Listenery (resize) ustawiamy raz; ResizeObserver na <html> łapie zmiany
 // viewportu (np. pasek narzędzi mobile). CSS calc-fallback trzyma sensowną
 // wysokość do pierwszego pomiaru, więc useEffect (po paint) wystarcza i nie
 // generuje ostrzeżenia SSR.
 useEffect(() => {
 measureColumnHeight();
 window.addEventListener("resize", measureColumnHeight);
 const ro =
 typeof ResizeObserver !== "undefined"
 ? new ResizeObserver(() => measureColumnHeight())
 : null;
 ro?.observe(document.documentElement);
 return () => {
 window.removeEventListener("resize", measureColumnHeight);
 ro?.disconnect();
 };
 }, [measureColumnHeight]);
 // Re-pomiar gdy cokolwiek nad/wewnątrz boardu może przesunąć jego pozycję:
 // zwinięcie nagłówka (prop), zmiana gęstości, status-baru lub liczby kolumn.
 useEffect(() => {
 measureColumnHeight();
 }, [measureColumnHeight, headerCollapsed, density, statusMessage, cols.length]);

 // Terminal-move modal — pojedynczy drag LUB bulk (wspólny powód odrzucenia
 // dla wszystkich zaznaczonych kandydatów).
 const [pendingRejection, setPendingRejection] = useState<{
 entries: { item: KanbanItem; srcColId: string }[];
 destCol: KanbanColumn;
 terminalType: "rejected" |"withdrawn";
 } | null>(null);
 // Pending verification flow (migracja 0056)
 const [verifiedRatePrompt, setVerifiedRatePrompt] = useState<{
 item: KanbanItem;
 destCol: KanbanColumn;
 srcColId: string;
 } | null>(null);
 // Bulk → "Zweryfikowany": stawka jest per kandydat, więc kolejka modali
 // (jeden po drugim) zamiast jednego wspólnego formularza.
 const [verifiedQueue, setVerifiedQueue] = useState<
 { item: KanbanItem; srcColId: string }[]
 >([]);
 const [verifiedBulkTotal, setVerifiedBulkTotal] = useState(0);
 // „CV Wysłane" → zapytaj o stawkę do klienta (sell rate). Analogiczne do
 // verified, ale stawka jest opcjonalna i zapisywana osobnym PATCH-em po ruchu
 // (kolumny client_rate_* na najnowszym CandidateStage). Bulk = kolejka modali.
 const [clientRatePrompt, setClientRatePrompt] = useState<{
 item: KanbanItem;
 destCol: KanbanColumn;
 srcColId: string;
 } | null>(null);
 const [clientRateQueue, setClientRateQueue] = useState<
 { item: KanbanItem; srcColId: string }[]
 >([]);
 const [clientRateBulkTotal, setClientRateBulkTotal] = useState(0);
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
 // „Usuń z rekrutacji" — korekta (dodano nie tego kandydata / nie na tę
 // ofertę). Modal potwierdzenia trzyma board, karta tylko sygnalizuje intencję.
 const [pendingRemoval, setPendingRemoval] = useState<KanbanItem | null>(null);
 const [removeBusy, setRemoveBusy] = useState(false);

 useEffect(() => setCols(columns), [columns]);

 useEffect(() => {
 (async () => {
 const mapReasons = (rrs: any[]) =>
 rrs.map((r: any) => ({
 id: r.id,
 label: r.name,
 applies_to: [r.category as"rejected" |"withdrawn"],
 }));
 try {
 const jobRes = await api.get(`/api/jobs/${jobId}`);
 const sMax = jobRes.data?.salary_max;
 setJobBudgetMax(typeof sMax === "number" ? sMax : null);
 const tid = jobRes.data?.pipeline_template_id;

 let reasons: {
 id: string;
 label: string;
 applies_to: ("rejected" |"withdrawn")[];
 }[] = [];
 if (tid) {
 const detail = await pipelineTemplatesApi.get(tid);
 reasons = mapReasons(detail.data.rejection_reasons ?? []);
 const withScorecard = new Set<number>();
 for (const s of detail.data.stages ?? []) {
 const sch = (s as any).scorecard_schema;
 if (sch && Array.isArray(sch.questions) && sch.questions.length > 0) {
 withScorecard.add((s as any).id);
 }
 }
 setStagesWithScorecard(withScorecard);
 }

 // Legacy joby (np. import z Traffit) nie mają pipeline_template_id, więc
 // ich szablon nie dostarcza powodów odrzucenia. Bez fallbacku dialog
 // "Odrzuć kandydata" miałby pustą listę powodów, a przycisk "Potwierdź"
 // byłby trwale zablokowany. Dociągamy powody z szablonu domyślnego, aby
 // zachować kontrolowany słownik (raporty lejka) zamiast wolnego tekstu.
 if (reasons.length === 0) {
 try {
 const templates = await pipelineTemplatesApi.list();
 const def = templates.data.find((t) => t.is_default);
 if (def) {
 const defDetail = await pipelineTemplatesApi.get(def.id);
 reasons = mapReasons(defDetail.data.rejection_reasons ?? []);
 }
 } catch (e) {
 console.error("Default rejection-reasons fallback failed", e);
 }
 }
 setRejectionReasons(reasons);
 } catch (e) {
 console.error("Pipeline template load failed", e);
 }
 })();
 }, [jobId]);

 const filtered = cols;

 // Klik w pigułkę paska podsumowania → poziomy scroll boardu do kolumny.
 // block:"nearest" nie rusza pionowego scrolla strony.
 const scrollToColumn = useCallback((id: string) => {
 const el = boardRef.current?.querySelector<HTMLElement>(
 `[data-colid="${CSS.escape(id)}"]`
 );
 el?.scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" });
 }, []);

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

 // M4 PR-03: po błędzie ruchu NIE zostawiamy karty w niepotwierdzonej
 // kolumnie — dociągamy prawdę z serwera (a nie lokalny snapshot, bo 409
 // oznacza, że stan pary i tak się zmienił pod nami).
 const refreshBoardAfterMove = useCallback(async () => {
 try {
 const fresh = await pipelineApi.kanban(jobId);
 if (Array.isArray(fresh.data?.columns)) {
 setCols(fresh.data.columns as KanbanColumn[]);
 }
 } catch (e) {
 console.error("Kanban refresh failed", e);
 }
 }, [jobId]);

 const sendMove = useCallback(
 async (
 item: KanbanItem,
 dst: KanbanColumn,
 reason?: {
 id: string;
 notes: string;
 sendRejectionEmail?: boolean | null;
 candidateOfferResponse?:"pending" |"accepted" |"declined" | null;
 // Wolny tekst powodu — tylko gdy szablon nie miał zdefiniowanych powodów.
 freeReason?: string;
 },
 opts?: { silent?: boolean }
 ): Promise<boolean> => {
 try {
 const response = await api.post<{
 id?: number;
 verification_status?:"active" |"pending" |"rejected";
 scheduled_rejection_email_id?: number | null;
 }>("/api/pipeline/move", {
 candidate_id: item.candidate_id,
 job_id: jobId,
 stage: dst.stage,
 stage_def_id: dst.stage_def_id ?? undefined,
 rejection_reason_id: reason?.id || undefined,
 rejection_reason: reason?.freeReason || undefined,
 notes: reason?.notes,
 send_rejection_email: reason?.sendRejectionEmail ?? undefined,
 candidate_offer_response:
 reason?.candidateOfferResponse ?? undefined,
 });

 // M4 PR-03 (audyt P1.3): backend tworzy NOWY CandidateStage — karta w
 // cache dostaje jego id + status z serwera. Bez tego kolejne akcje
 // (screening, scorecard, accept/reject) celowały w historyczny rekord.
 const newStageId = response?.data?.id;
 const serverVerifStatus = response?.data?.verification_status;
 if (typeof newStageId === "number" && newStageId !== item.id) {
 setCols((prev) =>
 prev.map((c) => {
 if (colId(c) !== colId(dst)) return c;
 return {
 ...c,
 items: c.items.map((i) =>
 i.id === item.id
 ? {
 ...i,
 id: newStageId,
 verification_status:
 serverVerifStatus ?? i.verification_status,
 }
 : i
 ),
 };
 })
 );
 }
 const currentStageId =
 typeof newStageId === "number" ? newStageId : item.id;

 // Kids mode: confetti + mascot pop on a win. No-op outside game mode.
 if (dst.stage === "hired") {
 celebrate({ variant: "hired", message: "Zatrudniony! 🎉" });
 } else if (reason?.candidateOfferResponse === "accepted") {
 celebrate({ variant: "offer", message: "Oferta przyjęta! 💖" });
 }

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

 // Prompt screening if moved to external-visible stage — na NOWYM id
 // (M4 PR-03: screening zapisywał się na historycznym rekordzie).
 if (EXTERNAL_STAGES_FOR_SCREENING.has(dst.stage)) {
 setScreeningPrompt({
 stageId: currentStageId,
 candidateName: `${item.name ??""} ${item.lastname ??""}`.trim() ||"Kandydat",
 });
 }
 // Prompt scorecard if stage has one — również na nowym id.
 if (dst.stage_def_id && stagesWithScorecard.has(dst.stage_def_id)) {
 setScorecardPrompt({
 candidateStageId: currentStageId,
 stageId: currentStageId,
 stageDefId: dst.stage_def_id,
 stageName: dst.name ?? dst.stage,
 });
 }
 return true;
 } catch (e) {
 console.error("Move failed", e);
 if (!opts?.silent) {
 // Wspólny parser zachowuje dotychczasowe szczegóły błędu i dodatkowo
 // rozpoznaje strukturalny PRIORITY_WORK_LOCKED.
 showError(assignErrorMessage(e));
 // M4 PR-03 (audyt P1.4): rollback optimistic — plansza wraca do
 // prawdy serwera zamiast kłamać kolumną, której DB nie potwierdziła.
 await refreshBoardAfterMove();
 }
 return false;
 }
 },
 [
 jobId,
 stagesWithScorecard,
 refreshBoardAfterMove,
 showActionToast,
 showSuccess,
 showError,
 ]
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
 if (dst.stage === "verified") {
 setVerifiedQueue([]);
 setVerifiedBulkTotal(1);
 setVerifiedRatePrompt({
 item,
 destCol: dst,
 srcColId: colId(src),
 });
 return;
 }

 // „CV Wysłane" — zapytaj o stawkę do klienta przed ruchem (recruiter może
 // pominąć lub anulować w modalu, dlatego NIE applyOptimistic tutaj).
 if (dst.stage === "cv_sent") {
 setClientRateQueue([]);
 setClientRateBulkTotal(1);
 setClientRatePrompt({ item, destCol: dst, srcColId: colId(src) });
 return;
 }

 // M4 PR-03 (audyt P1.6): hired = artefakty (draft kontraktu i zamówienia)
 // — wymaga jawnego potwierdzenia zamiast samego drop-u.
 if (terminalOf(dst) === "hired") {
 setHiredConfirm({ item, destCol: dst, srcColId: colId(src) });
 return;
 }

 // Terminal — najpierw modal powodu; optimistic dopiero po potwierdzeniu,
 // żeby anulowanie nie zostawiało karty w złej kolumnie.
 const dropTerminal = terminalOf(dst);
 if (dropTerminal === "rejected" || dropTerminal === "withdrawn") {
 setPendingRejection({
 entries: [{ item, srcColId: colId(src) }],
 destCol: dst,
 terminalType: dropTerminal,
 });
 return;
 }

 applyOptimistic(item, colId(src), dst);
 sendMove(item, dst);
 },
 [cols, applyOptimistic, sendMove]
 );

 // Submit z modala"Zweryfikowany — podaj rate"
 const submitVerifiedMove = useCallback(
 async (payload: { rate: number; unit: RateUnit; currency: string }) => {
 if (!verifiedRatePrompt) return;
 const { item, destCol, srcColId } = verifiedRatePrompt;
 // Pojedynczy ruch (drag/drop) vs bulk — screening Championa otwieramy
 // tylko dla pojedynczego, żeby nie nakładać go na modal stawki kolejnego
 // kandydata z kolejki bulk.
 const isSingleMove = verifiedBulkTotal <= 1;
 let newStageId: number | null = null;
 const movedName =
 `${item.name ??""} ${item.lastname ??""}`.trim() ||"Kandydat";
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
 // Backend tworzy NOWY CandidateStage — bierzemy jego id (nie stare
 // item.id), żeby screening zapisał się na świeżym etapie „verified".
 newStageId = (res?.data as { id?: number } | undefined)?.id ?? null;
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
 // M4 PR-03 (audyt P1.3): karta niesie id NOWEGO CandidateStage —
 // późniejsze accept/reject-verification przestaje celować w stary rekord.
 id: newStageId ?? item.id,
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
 if (verifStatus === "pending") {
 showSuccess("Wysłano do akceptacji delivery_lead. Karta będzie aktywna po zatwierdzeniu."
 );
 }
 } catch (e) {
 console.error("Move to verified failed", e);
 showError("Nie udało się przesunąć kandydata.");
 } finally {
 // Bulk: pokaż modal stawki dla kolejnego kandydata z kolejki.
 const [next, ...rest] = verifiedQueue;
 setVerifiedQueue(rest);
 setVerifiedRatePrompt(
 next ? { item: next.item, destCol, srcColId: next.srcColId } : null
 );
 // Po udanym pojedynczym ruchu na „Zweryfikowany" otwórz screening
 // Championa dla nowo utworzonego stage'u (skip przy bulk — nie nakładamy
 // na modal stawki kolejnego kandydata).
 if (!next && isSingleMove && newStageId != null) {
 setScreeningPrompt({ stageId: newStageId, candidateName: movedName });
 }
 }
 },
 [
 verifiedRatePrompt,
 verifiedQueue,
 verifiedBulkTotal,
 jobId,
 jobBudgetMax,
 showSuccess,
 showError,
 ]
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

 // Potwierdzone usunięcie kandydata z tej rekrutacji. Optymistycznie zdejmuje
 // kartę z kolumny, kasuje go z zaznaczenia bulk i odświeża powiązane widoki
 // (zakładka „Rekrutacje" + widget pipeline'ów na profilu kandydata).
 const confirmRemoveFromRecruitment = useCallback(async () => {
 if (!pendingRemoval) return;
 const item = pendingRemoval;
 const removedName =
 `${item.name ??""} ${item.lastname ??""}`.trim() ||"Kandydat";
 setRemoveBusy(true);
 try {
 await candidatesApi.removeFromRecruitment(item.candidate_id, jobId);
 setCols((prev) =>
 prev.map((c) => {
 if (!c.items.some((i) => i.id === item.id)) return c;
 const items = c.items.filter((i) => i.id !== item.id);
 return { ...c, items, count: items.length };
 })
 );
 setSelected((prev) => {
 if (!prev.has(item.id)) return prev;
 const n = new Set(prev);
 n.delete(item.id);
 return n;
 });
 queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
 queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
 queryClient.invalidateQueries({ queryKey: ["candidate-history"] });
 queryClient.invalidateQueries({
 queryKey: candidatePipelinesQueryKey(item.candidate_id),
 });
 showSuccess(`${removedName} — usunięty z rekrutacji.`);
 setPendingRemoval(null);
 } catch (e) {
 console.error("Remove from recruitment failed", e);
 const detail = (e as { response?: { data?: { detail?: unknown } } })
 ?.response?.data?.detail;
 showError(
 typeof detail === "string"
 ? detail :"Nie udało się usunąć kandydata z rekrutacji."
 );
 } finally {
 setRemoveBusy(false);
 }
 }, [pendingRemoval, jobId, queryClient, showSuccess, showError]);

 const toggleSelect = (id: number) => {
 setSelected((p) => {
 const n = new Set(p);
 if (n.has(id)) n.delete(id);
 else n.add(id);
 return n;
 });
 };

 // Submit z modala „CV Wysłane — stawka do klienta". `payload === null` =
 // recruiter pominął stawkę (ruch i tak następuje). Najpierw ruch (tworzy
 // nowy CandidateStage), potem PATCH stawki na ten najnowszy etap. Obsługuje
 // też kolejkę bulk (jeden modal na kandydata).
 const submitClientRateMove = useCallback(
 async (
 payload: { rate: number; unit: RateUnit; currency: string } | null
 ) => {
 if (!clientRatePrompt) return;
 const { item, destCol, srcColId } = clientRatePrompt;
 const isBulk = clientRateBulkTotal > 1;

 applyOptimistic(item, srcColId, destCol);
 const ok = await sendMove(item, destCol, undefined, { silent: isBulk });
 if (ok && payload) {
 try {
 await candidatesApi.setRecruitmentClientRate(item.candidate_id, jobId, {
 rate_value: payload.rate,
 rate_unit: payload.unit,
 rate_currency: payload.currency,
 });
 if (!isBulk) {
 showSuccess("Przeniesiono na „CV Wysłane” i zapisano stawkę do klienta.");
 }
 } catch (e) {
 console.error("Set client rate failed", e);
 showError("Przeniesiono, ale nie udało się zapisać stawki do klienta — uzupełnij ją z profilu kandydata."
 );
 }
 } else if (!ok && isBulk) {
 await refreshBoardAfterMove();
 }

 // Bulk: pokaż modal stawki dla kolejnego kandydata z kolejki (lub zamknij).
 const [next, ...rest] = clientRateQueue;
 setClientRateQueue(rest);
 setClientRatePrompt(
 next ? { item: next.item, destCol, srcColId: next.srcColId } : null
 );
 },
 [
 clientRatePrompt,
 clientRateQueue,
 clientRateBulkTotal,
 jobId,
 applyOptimistic,
 sendMove,
 refreshBoardAfterMove,
 showSuccess,
 showError,
 ]
 );

 const bulkMove = async (destColId: string) => {
 const dst = cols.find((c) => colId(c) === destColId);
 if (!dst || selected.size === 0) return;
 // Zaznaczone karty wraz z kolumną źródłową; karty już w celu pomijamy.
 const entries: { item: KanbanItem; srcColId: string }[] = [];
 for (const sid of Array.from(selected)) {
 const src = cols.find((c) => c.items.some((i) => i.id === sid));
 if (!src || colId(src) === colId(dst)) continue;
 entries.push({
 item: src.items.find((i) => i.id === sid)!,
 srcColId: colId(src),
 });
 }
 if (entries.length === 0) {
 setSelected(new Set());
 return;
 }

 // "Zweryfikowany" wymaga stawki per kandydat (backend: 422 bez stawki) —
 // zamiast bezpośrednich POST-ów otwórz modal stawki dla każdego po kolei.
 if (dst.stage === "verified") {
 setVerifiedBulkTotal(entries.length);
 setVerifiedQueue(entries.slice(1));
 setVerifiedRatePrompt({
 item: entries[0].item,
 destCol: dst,
 srcColId: entries[0].srcColId,
 });
 setSelected(new Set());
 return;
 }

 // „CV Wysłane" — stawka do klienta per kandydat → kolejka modali (analogicznie
 // do verified). Pominięcie/anulowanie obsłużone w submitClientRateMove.
 if (dst.stage === "cv_sent") {
 setClientRateBulkTotal(entries.length);
 setClientRateQueue(entries.slice(1));
 setClientRatePrompt({
 item: entries[0].item,
 destCol: dst,
 srcColId: entries[0].srcColId,
 });
 setSelected(new Set());
 return;
 }

 // M4 PR-03 (audyt P1.6): zbiorcze zatrudnianie bez wizardu = N draftów
 // kontraktów jednym kliknięciem — wykonuj pojedynczo (drag z potwierdzeniem).
 if (terminalOf(dst) === "hired") {
 showError("Zatrudnienie oznaczaj pojedynczo — przeciągnij kartę kandydata.");
 return;
 }

 // Etapy terminalne wymagają powodu — jeden modal, wspólny powód dla
 // całego zaznaczenia.
 const bulkTerminal = terminalOf(dst);
 if (bulkTerminal === "rejected" || bulkTerminal === "withdrawn") {
 setPendingRejection({
 entries,
 destCol: dst,
 terminalType: bulkTerminal,
 });
 setSelected(new Set());
 return;
 }

 setBulkBusy(true);
 try {
 let failures = 0;
 for (const { item, srcColId } of entries) {
 applyOptimistic(item, srcColId, dst);
 const ok = await sendMove(item, dst, undefined, { silent: true });
 if (!ok) failures += 1;
 }
 if (failures > 0) {
 showError(
 `Nie udało się przenieść ${failures} z ${entries.length} kandydatów.`
 );
 await refreshBoardAfterMove();
 } else if (entries.length > 1) {
 showSuccess(`Przeniesiono ${entries.length} kandydatów.`);
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
 ? e.message : "Pobieranie nie powiodło się."
 );
 } finally {
 setBulkDownloadBusy(false);
 }
 };

 return (
 <div className="relative space-y-3">
 {/* Density toggle floated into the header gap (top-right, beside the
 tabs) so the board sits flush under the tabs instead of leaving an
 empty toolbar band above it. */}
 <div className="absolute -top-9 right-0 z-10 flex items-center gap-2">
 <Tooltip>
 <TooltipTrigger asChild>
 <button
 onClick={() => setDensity(density === "cozy" ?"compact" :"cozy")}
 className="h-8 w-8 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-primary/10 hover:text-foreground"
 >
 {density === "compact" ? (
 <LayoutGrid className="h-4 w-4" />
 ) : (
 <Rows3 className="h-4 w-4" />
 )}
 </button>
 </TooltipTrigger>
 <TooltipContent>
 Gęstość: {density === "compact" ?"kompaktowa" :"cozy"}
 </TooltipContent>
 </Tooltip>
 </div>

 {/* Podsumowanie etapów — wszystkie liczniki widoczne bez scrollowania */}
 {cols.length > 0 && <StageSummaryStrip cols={cols} onJump={scrollToColumn} />}

 {/* Bulk action bar */}
 {selected.size > 0 && (
 <Card className="p-3! flex items-center gap-3 flex-wrap bg-card text-foreground border-white/10">
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
 <div
 ref={boardRef}
 className={cn(
 // Board = JEDYNY scroll-kontener (oba kierunki). Po usunięciu overflow-y
 // z kolumn to on jest „closestScrollable" każdej kolumny → @hello-pangea/dnd
 // śledzi jego scroll i auto-scrolluje go natywnie (drop trafia pod kursor,
 // skrajne kolumny osiągalne — bez ręcznego rAF). Definite height wypełnia
 // viewport; calc fallback działa do pierwszego pomiaru (SSR/pierwszy render).
 "flex gap-3 overflow-auto pb-4 min-h-[280px]",
 columnHeight == null && "h-[calc(100vh-350px)]"
 )}
 style={columnHeight != null ? { height: columnHeight } : undefined}
 >
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
 jobId={jobId}
 selectedIds={selected}
 onToggleSelect={toggleSelect}
 onOpenScreening={(stageId, name) =>
 setScreeningPrompt({ stageId, candidateName: name })
 }
 density={density}
 isApprover={isApprover}
 scoreMap={scoreMap}
 scoresLoading={scoresLoading}
 onAcceptVerification={handleAcceptVerification}
 onRejectVerification={(item) =>
 setPendingRejectVerification({ item, note: "" })
 }
 onRemoveFromRecruitment={(item) => setPendingRemoval(item)}
 contactFeatureEnabled={contactFeature.enabled}
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
 const firstSrc = pendingRejection?.entries[0]?.srcColId;
 if (!firstSrc) return null;
 const cat = cols.find((c) => colId(c) === firstSrc)?.category;
 return cat === "external" ?"external" : cat === "internal" ?"internal" : null;
 })()}
 previousStage={
 pendingRejection
 ? cols.find(
 (c) => colId(c) === pendingRejection.entries[0]?.srcColId
 )?.stage ?? null
 : null
 }
 onConfirm={(
 reasonId,
 notes,
 sendRejectionEmail,
 candidateOfferResponse,
 freeReason
 ) => {
 if (!pendingRejection) return;
 const { entries, destCol } = pendingRejection;
 setPendingRejection(null);
 void (async () => {
 let failures = 0;
 for (const { item, srcColId } of entries) {
 applyOptimistic(item, srcColId, destCol);
 const ok = await sendMove(
 item,
 destCol,
 {
 id: reasonId,
 notes,
 sendRejectionEmail,
 candidateOfferResponse: candidateOfferResponse ?? null,
 freeReason,
 },
 { silent: entries.length > 1 }
 );
 if (!ok) failures += 1;
 }
 if (failures > 0) {
 if (entries.length > 1) {
 showError(
 `Nie udało się przenieść ${failures} z ${entries.length} kandydatów.`
 );
 }
 await refreshBoardAfterMove();
 } else if (entries.length > 1) {
 showSuccess(`Przeniesiono ${entries.length} kandydatów.`);
 }
 })();
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
 key={verifiedRatePrompt.item.id}
 open={true}
 onOpenChange={(v) => {
 if (!v) {
 // Anulowanie przerywa też resztę bulk-kolejki.
 setVerifiedRatePrompt(null);
 setVerifiedQueue([]);
 setVerifiedBulkTotal(0);
 }
 }}
 candidateName={
 (`${verifiedRatePrompt.item.name ??""} ${verifiedRatePrompt.item.lastname ??""}`.trim() ||"Kandydat") +
 (verifiedBulkTotal > 1
 ? ` (${verifiedBulkTotal - verifiedQueue.length}/${verifiedBulkTotal})`
 : "")
 }
 jobBudgetMax={jobBudgetMax}
 onConfirm={submitVerifiedMove}
 />
 )}

 {/* „CV Wysłane" — recruiter podaje stawkę do klienta (lub pomija) */}
 {clientRatePrompt && (
 <ClientRateModal
 key={clientRatePrompt.item.id}
 open={true}
 onOpenChange={(v) => {
 if (!v) {
 // Anulowanie (X/Escape) przerywa też resztę bulk-kolejki.
 setClientRatePrompt(null);
 setClientRateQueue([]);
 setClientRateBulkTotal(0);
 }
 }}
 candidateName={
 (`${clientRatePrompt.item.name ??""} ${clientRatePrompt.item.lastname ??""}`.trim() ||"Kandydat") +
 (clientRateBulkTotal > 1
 ? ` (${clientRateBulkTotal - clientRateQueue.length}/${clientRateBulkTotal})`
 : "")
 }
 onConfirm={(payload) => submitClientRateMove(payload)}
 onSkip={() => submitClientRateMove(null)}
 />
 )}

 {/* M4 PR-03 (audyt P1.6): potwierdzenie przed hired — powstają artefakty */}
 {hiredConfirm && (
 <Dialog open onOpenChange={(o) => !o && setHiredConfirm(null)}>
 <DialogContent>
 <DialogHeader>
 <DialogTitle>Potwierdź zatrudnienie</DialogTitle>
 <DialogDescription>
 {`${hiredConfirm.item.name ??""} ${hiredConfirm.item.lastname ??""}`.trim() ||"Kandydat"}{" "}
 trafi na etap „Zatrudniony”. System utworzy szkic kontraktu i
 zamówienia dla tej rekrutacji.
 </DialogDescription>
 </DialogHeader>
 <DialogFooter>
 <Button variant="outline" onClick={() => setHiredConfirm(null)}>
 Anuluj
 </Button>
 <Button
 onClick={() => {
 const { item, destCol, srcColId } = hiredConfirm;
 setHiredConfirm(null);
 applyOptimistic(item, srcColId, destCol);
 void sendMove(item, destCol);
 }}
 >
 Potwierdź zatrudnienie
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
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
 className="w-full px-3 py-2 rounded-md border border-border bg-card focus:outline-hidden focus:ring-2 focus:ring-primary"
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

 {/* Usuń z rekrutacji — potwierdzenie (operacja nieodwracalna) */}
 {pendingRemoval && (
 <Dialog
 open={true}
 onOpenChange={(v: boolean) => {
 if (!v && !removeBusy) setPendingRemoval(null);
 }}
 >
 <DialogContent>
 <DialogHeader>
 <DialogTitle>Usunąć kandydata z tej rekrutacji?</DialogTitle>
 <DialogDescription>
 <span className="font-medium text-foreground">
 {`${pendingRemoval.name ??""} ${pendingRemoval.lastname ??""}`.trim() ||"Kandydat"}
 </span>{" "}
 zostanie zdjęty z pipeline'u tej rekrutacji. Usunięta zostanie cała
 historia jego etapów wraz z powiązanymi snapshotami CV
 (oryginalne/brandowane) i linkami do udostępnień. Tej operacji nie
 można cofnąć — kandydata można jednak dodać do rekrutacji ponownie.
 Sam profil kandydata oraz jego umowy pozostają bez zmian.
 </DialogDescription>
 </DialogHeader>
 <DialogBody>
 <p className="text-xs text-muted-foreground">
 To nie to samo co odrzucenie — jeśli kandydat brał udział w procesie,
 użyj „Odrzuć", by zachować historię.
 </p>
 </DialogBody>
 <DialogFooter>
 <Button
 variant="ghost"
 onClick={() => setPendingRemoval(null)}
 disabled={removeBusy}
 >
 Anuluj
 </Button>
 <Button
 variant="destructive"
 onClick={confirmRemoveFromRecruitment}
 disabled={removeBusy}
 loading={removeBusy}
 >
 Usuń z rekrutacji
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 )}
 </div>
 );
}
