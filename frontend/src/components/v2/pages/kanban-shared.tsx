"use client";

/**
 * Typy i drobne helpery pipeline'u kanbanowego, wydzielone z
 * `KanbanBoardV2.tsx` (krok 04 Pipeline, program „flow w języku C2", PR 3/7).
 *
 * Powód wydzielenia: `KanbanBoardV2` renderuje `PipelineCandidateDock` i
 * `PipelineFiltersRail`, a oba potrzebują tych samych typów/identyfikatorów
 * kolumn (`KanbanItem`, `KanbanColumn`, `colId`, `columnLabel`) i tego samego
 * pierścienia wyniku (`ScoreRing`, żeby dok pokazywał TEN SAM wizualny
 * element co karta — „ten sam `pipelineScores`"). Import tego z samego
 * `KanbanBoardV2.tsx` zamknąłby cykl (KanbanBoardV2 → dok/rail →
 * KanbanBoardV2); ten moduł nie importuje niczego z żadnego z nich, więc
 * cyklu nie ma.
 */

import { memo } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { RateUnit } from "@/lib/api";
import type { CandidateContactSummary } from "@/lib/candidate-contact";

// ── Types ─────────────────────────────────────────────────────────────

export interface KanbanItem {
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

export const colId = (col: KanbanColumn) =>
 col.stage_def_id ? `def:${col.stage_def_id}` : `stage:${col.stage}`;

export const columnLabel = (col: KanbanColumn) => col.name ?? col.stage;

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
export const ScoreRing = memo(function ScoreRing({
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
