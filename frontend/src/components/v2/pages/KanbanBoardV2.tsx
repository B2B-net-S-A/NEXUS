"use client";

import * as React from"react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from"react";
import { useQueryClient } from"@tanstack/react-query";
import Link from"next/link";
import { Alert } from"@/components/ui/alert";
import {
 DragDropContext,
 Draggable,
 Droppable,
 type DropResult,
} from"@hello-pangea/dnd";
import {
 AlertCircle,
 AlertTriangle,
 ChevronLeft,
 ChevronRight,
 Clock,
 FileArchive,
 FileSignature,
 FileText,
 Flag,
 HelpCircle,
 LayoutGrid,
 Loader2,
 Mail,
 MoveRight,
 Phone,
 Rows3,
 Send,
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
import {
 BulkCvDownloadError,
 downloadBulkCvs,
} from"@/lib/bulk-cv-download";
import { cn, formatDate } from"@/lib/utils";
import { countPl } from"@/lib/plural-pl";
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
import { moveDialogFor } from "@/lib/pipeline-move-dialog";
import { assignErrorMessage } from "@/lib/assign-error";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { PipelineFiltersRail } from "@/components/v2/jobs/PipelineFiltersRail";
import {
 PipelineCandidateDock,
 PipelineCandidateDockEmpty,
 type PipelineMoveTarget,
} from "@/components/v2/jobs/PipelineCandidateDock";
import {
 colId,
 columnLabel,
 ScoreRing,
 type KanbanColumn,
 type KanbanItem,
} from "@/components/v2/pages/kanban-shared";
import {
 PIPELINE_GROUP_SHORT_LABEL,
 bulkMoveSkipReason,
 formatExpectedRate,
 groupKanbanColumns,
 itemFullName,
 moveBlockedReason,
 primaryForwardMove,
 type PipelineColumnGroup,
 type PipelineGroupKey,
 type PrimaryForwardMove,
} from "@/lib/pipeline-flow";
import {
 columnSlaHint,
 hasNoNextAction,
 nextActionFor,
 oldestDaysInColumn,
 type NextAction,
 type NextActionKind,
} from "@/lib/pipeline-next-action";
import { useClientPlaybook } from "@/lib/client-playbooks";
import {
  PIPELINE_VERSION_CONFLICT_MESSAGE,
  expectedStateVersionOf,
  invalidateAfterPipelineVersionConflict,
  isPipelineVersionConflict,
} from "@/lib/pipeline-version-conflict";
import {
  eligibilityWarningReason,
  isEligibilityWarning,
} from "@/lib/pipeline-eligibility-warning";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { jobBudgetHourly as resolveJobBudgetHourly } from "@/lib/job-budget";

// Re-eksport — `KanbanColumn`/`KanbanItem`/`colId`/`columnLabel`/`ScoreRing`
// mieszkają teraz w `kanban-shared.tsx` (dok i lewy rail importują je STAMTĄD,
// nie stąd, żeby uniknąć cyklu: KanbanBoardV2 → dok/rail → KanbanBoardV2).
// Re-eksport zostaje dla wstecznej zgodności — `KanbanColumn` było publicznym
// eksportem tego modułu przed PR3 programu „flow w języku C2".
export type { KanbanColumn, KanbanItem };
export { colId, columnLabel, ScoreRing };

// ── Types ─────────────────────────────────────────────────────────────

// Lustro `RECRUITMENT_RATE_EDIT_ROLES` (backend/app/api/recruitment_access.py):
// ruch na „Zweryfikowany" może zapisać stawkę kandydata i poza tymi rolami
// serwer odpowiada 403. Okno stawki dla innej roli kończyłoby się odmową PO
// wpisaniu kwoty, więc tablica mówi o tym przed. (Head of Recruitment ma
// parytet z rekruterem od 17.09.2026.)
const RATE_EDIT_ROLES = new Set(["admin","head_of_recruitment","delivery_lead","tac","recruiter","finance"]);
const RATE_EDIT_DENIED_MESSAGE =
 "Ruch na „Zweryfikowany” może zapisać stawkę kandydata — mogą go wykonać: rekruter, TAC, Delivery Lead, Head of Recruitment, Finanse lub administrator.";

interface KanbanBoardV2Props {
 columns: KanbanColumn[];
 jobId: number;
 /** Tytuł rekrutacji — nagłówki modali CV i zakładka „Dopasowanie" w doku
  *  „Karta w procesie" (krok 04). Nie mylić z nazwą etapu. */
 jobTitle?: string;
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
 /** Read-only policy keeps the pipeline visible but removes every mutation. */
 readOnly?: boolean;
 /** Karty poza szablonem — `null` na zdrowej tablicy. */
 offTemplate?: OffTemplateColumn | null;
 /** Klient tej rekrutacji — SLA w dniach roboczych z jego karty
  *  (`client_playbooks`) zasila lewą kolumnę i licznik na kolumnie
  *  „Screening". Bez niego tablica działa jak dotąd i mówi wprost, że SLA
  *  nie jest ustawione — nigdy go nie zgaduje. */
 clientId?: number | null;
 /** `?candidate=<id>` z adresu rekrutacji (np. wzmianka w notatce) — otwiera
  *  dok tego kandydata raz, gdy jego karta pojawi się na tablicy. */
 focusCandidateId?: number | null;}

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

// Etapy zewnętrzne z punktem re-screeningu Championa przed kontaktem z klientem.
// Od 17.09.2026 arkusz NIE otwiera się sam po ruchu — karta na tych etapach
// i na „Zweryfikowany" pokazuje pigułkę „Uzupełnij screening", dopóki
// arkusz nie jest zapisany (`screening_done`).
const EXTERNAL_STAGES_FOR_SCREENING = new Set(["client_interview","acceptance","negotiation","onboarding",
]);
const SCREENING_BADGE_STAGES = new Set([...EXTERNAL_STAGES_FOR_SCREENING, "verified"]);

/** Karty, których etap nie ma kolumny w szablonie tej rekrutacji.
 *
 *  Backend zwraca je OSOBNO od `columns` (`KanbanView.off_template`), właśnie
 *  po to, żeby kubełek nie miał tożsamości celu ruchu. */
export interface OffTemplateColumn {
 name: string;
 count: number;
 items: KanbanItem[];
 missing_stage_labels: string[];
}

/** Sentinel kolumny „poza szablonem" — CELOWO nie jest wartością `PipelineStage`.
 *
 *  Gdyby kubełek udawał `"new"`, przeciek przez `isDropDisabled` i filtr celów
 *  skończyłby się cichym HTTP 200 na złym etapie (backend rozwiązuje etap po
 *  `legacy_enum_value`). Z tym sentinelem ta sama pomyłka daje 422 i board
 *  odświeża prawdę z serwera — awaria jest widoczna, nie cicha. */
const OFF_TEMPLATE_STAGE = "__off_template__";

const isOffTemplate = (col: KanbanColumn) => col.stage === OFF_TEMPLATE_STAGE;

/** Doklej kubełek na koniec listy kolumn (albo zwróć kolumny bez zmian).
 *
 *  Musi być użyty w KAŻDYM punkcie synchronizacji stanu — inaczej kubełek
 *  znika po pierwszym odświeżeniu i karty znowu są niewidoczne. */
export const composeColumns = (
 columns: KanbanColumn[],
 offTemplate?: OffTemplateColumn | null
): KanbanColumn[] => {
 if (!offTemplate || offTemplate.count === 0) return columns;
 return [
 ...columns,
 {
 stage: OFF_TEMPLATE_STAGE,
 count: offTemplate.count,
 items: offTemplate.items,
 stage_def_id: null,
 name: offTemplate.name,
 },
 ];
};

const defaultFocusColumnId = (cols: KanbanColumn[]) => {
 const preferred = cols.find(
 (col) => col.count > 0 && col.category !== "terminal"
 );
 const col = preferred ?? cols[0];
 return col ? colId(col) : null;
};

// ── Stage focus navigator ───────────────────────────────────────────
// Wszystkie kolumny pozostają zamontowane dla DnD. Navigator zmienia wyłącznie
// poziomy viewport planszy: wybór etapu centruje go pomiędzy sąsiadami.

const StageFocusNavigator = memo(function StageFocusNavigator({
 cols,
 focusedId,
 onFocus,
 density,
 onToggleDensity,
 fullPipelineDesktop,
}: {
 cols: KanbanColumn[];
 focusedId: string | null;
 onFocus: (id: string) => void;
 density: "cozy" | "compact";
 onToggleDensity: () => void;
 fullPipelineDesktop: boolean;
}) {
 const total = cols.reduce(
 (sum, c) => sum + (c.category === "terminal" ? 0 : c.count),
 0
 );
 const focusedIndex = Math.max(
 0,
 cols.findIndex((col) => colId(col) === focusedId)
 );
 const focused = cols[focusedIndex];

 if (!focused) return null;

 return (
 <div
 className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-2 py-1.5"
 role="navigation"
 aria-label="Nawigacja etapów pipeline"
 >
 <Badge variant="soft" className="tabular-nums">
 W procesie: {total}
 </Badge>

 <div
 data-mobile-stage-navigation
 className={cn(
 "order-3 flex w-full min-w-0 items-center justify-center gap-1 sm:order-none sm:w-auto",
 fullPipelineDesktop &&"xl:pointer-fine:hidden"
 )}
 >
 <Button
 type="button"
 size="icon-sm"
 variant="ghost"
 onClick={() => onFocus(colId(cols[focusedIndex - 1]))}
 disabled={focusedIndex === 0}
 aria-label="Poprzedni etap"
 >
 <ChevronLeft className="h-4 w-4" />
 </Button>
 <Select value={colId(focused)} onValueChange={onFocus}>
 <SelectTrigger
 className="h-8 min-w-0 flex-1 sm:w-[300px] sm:flex-none"
 aria-label={`${columnLabel(focused)}, etap ${focusedIndex + 1} z ${cols.length}`}
 >
 <SelectValue>
 <span className="truncate">
 {columnLabel(focused)} · etap {focusedIndex + 1} z {cols.length}
 </span>
 </SelectValue>
 </SelectTrigger>
 <SelectContent>
 {cols.map((col, index) => (
 <SelectItem
 key={colId(col)}
 value={colId(col)}
 textValue={columnLabel(col)}
 >
 <span className="flex w-full items-center justify-between gap-3">
 <span className="truncate">
 {index + 1}. {columnLabel(col)}
 </span>
 <span className="tabular-nums text-muted-foreground" aria-hidden="true">
 {col.count}
 </span>
 <span className="sr-only">, liczba kandydatów: {col.count}</span>
 </span>
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 <Button
 type="button"
 size="icon-sm"
 variant="ghost"
 onClick={() => onFocus(colId(cols[focusedIndex + 1]))}
 disabled={focusedIndex === cols.length - 1}
 aria-label="Następny etap"
 >
 <ChevronRight className="h-4 w-4" />
 </Button>
 </div>

 <Tooltip>
 <TooltipTrigger asChild>
 <Button
 type="button"
 size="icon-sm"
 variant="ghost"
 onClick={onToggleDensity}
 aria-label={`Gęstość: ${density === "compact" ? "kompaktowa" : "cozy"}`}
 >
 {density === "compact" ? (
 <LayoutGrid className="h-4 w-4" />
 ) : (
 <Rows3 className="h-4 w-4" />
 )}
 </Button>
 </TooltipTrigger>
 <TooltipContent>
 Gęstość: {density === "compact" ? "kompaktowa" : "cozy"}
 </TooltipContent>
 </Tooltip>
 </div>
 );
});

const OverviewScoreBadge = memo(function OverviewScoreBadge({
 normalizedScore,
 loading,
 candidateId,
}: {
 normalizedScore?: number;
 loading?: boolean;
 candidateId: number;
}) {
 const pct = normalizedScore ?? null;
 const label = loading
 ? "Obliczanie dopasowania AI…"
 : pct == null
 ? "Brak wyliczonego dopasowania AI"
 : `Dopasowanie AI: ${pct} na 100`;
 const tone =
 pct == null
 ? "border-border bg-muted text-muted-foreground"
 : pct >= 75
 ? "border-emerald-200 bg-emerald-50 text-emerald-700"
 : pct >= 50
 ? "border-sky-200 bg-sky-50 text-sky-700"
 : pct >= 25
 ? "border-amber-200 bg-amber-50 text-amber-700"
 : "border-rose-200 bg-rose-50 text-rose-700";

 return (
 <Tooltip>
 <TooltipTrigger asChild>
 <span
 data-testid={`overview-match-score-${candidateId}`}
 className={cn(
 "inline-flex h-5 min-w-5 items-center justify-center rounded-full border px-1 text-[9px] font-bold leading-none",
 loading && "animate-pulse",
 tone
 )}
 aria-hidden="true"
 >
 {loading ? "…" : pct ?? "—"}
 </span>
 </TooltipTrigger>
 <TooltipContent side="top">{label}</TooltipContent>
 </Tooltip>
 );
});

// ── Card ─────────────────────────────────────────────────────────────

/** Ikona wiersza „następna akcja". Ton (`due`/`gate`) wygrywa z rodzajem —
 *  zaległość i bramka mają mówić o sobie, nie o etapie. */
const NEXT_ACTION_ICON: Record<NextActionKind, typeof Phone> = {
 analysis: FileText,
 screening: Phone,
 verification: HelpCircle,
 cv: Send,
 client: Mail,
 offer: Clock,
 contract: FileSignature,
 none: FileText,
};

function NextActionRow({
 action,
 hidden,
}: {
 action: NextAction;
 hidden?: boolean;
}) {
 if (action.kind === "none") return null;
 const Icon = action.tone === "normal" ? NEXT_ACTION_ICON[action.kind] : AlertTriangle;
 return (
 <div
 data-next-action={action.tone}
 className={cn(
 "mt-1.5 flex items-center gap-1.5 border-t border-dashed border-border pt-1 text-[10.5px] leading-tight",
 action.tone === "normal" ? "text-foreground/80" : "text-warning font-medium",
 hidden && "xl:pointer-fine:hidden"
 )}
 >
 <Icon className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
 <span className="min-w-0 truncate">{action.label}</span>
 </div>
 );
}

interface CardProps {
 item: KanbanItem;
 jobId: number;
 selected: boolean;
 onToggleSelect: (id: number) => void;
 onOpenScreening: (stageId: number, name: string) => void;
 density: "cozy" |"compact";
 canScreen: boolean;
 /** Arkusz screeningu na tym etapie jeszcze niezapisany (17.09.2026). */
 screeningDue: boolean;
 /** Scorecard tego etapu jeszcze niezapisany (17.09.2026). */
 scorecardDue: boolean;
 onOpenScorecard: (item: KanbanItem) => void;
 /** Stawka z karty ponad budżet PLN/h rekrutacji — odznaka, nie blokada. */
 overBudget: boolean;
 matchScore?: number;
 scoresLoading?: boolean;
 onRemoveFromRecruitment: (item: KanbanItem) => void;
 contactFeatureEnabled: boolean;
 desktopOverview: boolean;
 readOnly: boolean;
 /** Krok 04 Pipeline (flow C2, PR 3/7): klik na kartę otwiera dok „Karta w
  *  procesie" obok tablicy — wszędzie poza checkboxem i linkiem do profilu. */
 onOpenDock: (item: KanbanItem) => void;
 /** Karta nie pasuje aktywnym filtrom lewej kolumny — przyciemniona, ale
  *  NADAL w DOM-ie i przeciągalna: usunięcie jej z listy zepsułoby indeksy
  *  `@hello-pangea/dnd`, na których stoi `onDragEnd`. Ukrywanie liczników w
  *  rail'u (nie tutaj) jest tym, co czyni przyciemnienie „nie cichym". */
 dimmed?: boolean;
 /** Wiersz „co dalej" — liczony z etapu i wieku karty, patrz
  *  `lib/pipeline-next-action.ts`. Przekazywany gotowy (a nie liczony tutaj),
  *  bo tylko kolumna zna grupę etapu policzoną nad CAŁĄ tablicą. */
 nextAction: NextAction;
}

const CandidateKanbanCard = memo(function CandidateKanbanCard({
 item,
 jobId,
 selected,
 onToggleSelect,
 onOpenScreening,
 density,
 canScreen,
 screeningDue,
 scorecardDue,
 onOpenScorecard,
 overBudget,
 matchScore,
 scoresLoading,
 onRemoveFromRecruitment,
 contactFeatureEnabled,
 desktopOverview,
 readOnly,
 onOpenDock,
 dimmed,
 nextAction,
}: CardProps) {
 const fullName = `${item.name ??""} ${item.lastname ??""}`.trim() ||"Kandydat";
 const normalizedMatchScore =
 typeof matchScore === "number" && Number.isFinite(matchScore)
 ? Math.max(0, Math.min(100, Math.round(matchScore)))
 : null;
 const daysBadge =
 item.days_in_stage == null
 ? null
 : item.days_in_stage >= 7
 ?"danger"
 : item.days_in_stage >= 3
 ?"warning"
 :"neutral";
 const detailsId = `kanban-candidate-details-${item.id}`;
 const hasAddedByName = Boolean(item.added_to_job_by_name?.trim());
 const addedByDisplayName = item.added_to_job_by_name?.trim() || "brak danych";
 const addedByShortName = item.added_to_job_by_name?.trim()
 ? item.added_to_job_by_name.trim().split(/\s+/)[0]
 : "Brak danych";
 // Awatar WŁAŚCICIELA karty, nie kandydata — makieta kroku 04 pyta „czyja to
 // karta", a nazwisko kandydata i tak stoi wiersz wyżej.
 const ownerInitials = item.added_to_job_by_name?.trim()
 ? item.added_to_job_by_name
 .trim()
 .split(/\s+/)
 .map((w) => w[0])
 .slice(0, 2)
 .join("")
 .toUpperCase()
 : "?";
 const addedAttribution = hasAddedByName
 ? `Dodano do rekrutacji przez: ${addedByDisplayName}${
 item.added_to_job_at ? ` · ${formatDate(item.added_to_job_at)}` : ""
 }`
 : `Brak danych o osobie dodającej${
 item.added_to_job_at ? ` · dodano ${formatDate(item.added_to_job_at)}` : ""
 }`;
 const accessibleDetails = [
 overBudget ? "Stawka ponad budżet rekrutacji." : null,
 screeningDue ? "Screening do uzupełnienia." : null,
 scorecardDue ? "Scorecard do uzupełnienia." : null,
 normalizedMatchScore != null
 ? `Dopasowanie AI: ${normalizedMatchScore} na 100.`
 : scoresLoading
 ? "Trwa obliczanie dopasowania AI."
 : desktopOverview
 ? "Brak wyliczonego dopasowania AI."
 : null,
 item.rating != null && item.rating > 0
 ? `Ocena: ${item.rating.toFixed(1)}.`
 : null,
 item.days_in_stage != null
 ? `W etapie od ${item.days_in_stage} dni.`
 : null,
 `${addedAttribution}.`,
 item.hm_veto ? "Ostrzeżenie: weto hiring managera." : null,
 // Na końcu, nie w środku — „następny krok" jest podsumowaniem karty, a nie
 // kolejnym faktem o kandydacie.
 nextAction.kind !== "none" ? `Następny krok: ${nextAction.label}.` : null,
 ]
 .filter(Boolean)
 .join(" ");
 // Krok 04 Pipeline: otwórz dok na klik gdziekolwiek na karcie POZA
 // checkboxem, linkiem do profilu i przyciskami akcji hover — te już
 // robią coś swojego (zaznaczenie / nawigacja / mutacja) i mają własny
 // `stopPropagation()`. `.closest()` jest odporne na to, że link do
 // profilu owija dziś większość treści karty (avatar, nazwisko, badge'e).
 const handleCardClick = (e: React.MouseEvent<HTMLDivElement>) => {
 if ((e.target as HTMLElement).closest('a, button, [role="checkbox"], input')) {
 return;
 }
 onOpenDock(item);
 };
 const gateFlagReason = item.hm_veto
 ? [
 `${item.hm_veto.hiring_manager_name ?? "Hiring manager tej rekrutacji"} odrzucił(a) tego kandydata po rozmowie ${formatDate(item.hm_veto.rejected_at)}`,
 `Powód: ${item.hm_veto.rejection_reason_name}`,
 ]
 .filter(Boolean)
 .join(" — ")
 : null;

 return (
 <div
 data-kanban-card=""
 onClick={handleCardClick}
 className={cn("group relative rounded-lg bg-card border border-border transition-all","hover:shadow-xs hover:border-primary/40",
 selected &&"ring-2 ring-primary border-primary",
 // Makieta kroku 04 daje karcie ~9 px oddechu; stare `p-5` (20 px) zjadało
 // przy 176 px kolumny ćwierć jej szerokości na sam padding.
 density === "compact" ?"p-2" :"p-3",
 desktopOverview &&"xl:pointer-fine:min-h-[68px] xl:pointer-fine:rounded-md xl:pointer-fine:p-1 xl:pointer-fine:pb-6 xl:pointer-fine:pt-6",
 // Świadomie bez grayscale/opacity — czytałoby się jako „nieaktywny". Ten
 // kandydat jest aktywny; weto to ostrzeżenie (17.09.2026), nie blokada.
 item.hm_veto &&"border-destructive/50",
 // Filtr lewej kolumny nie pasuje — przyciemnij, ale zostaw w DOM-ie
 // (patrz komentarz `dimmed` w `CardProps`).
 dimmed &&"opacity-35"
 )}
 title={
 [
 fullName,
 normalizedMatchScore != null
 ? `Dopasowanie AI: ${normalizedMatchScore}/100`
 : null,
 item.rating != null && item.rating > 0
 ? `Ocena: ${item.rating.toFixed(1)}`
 : null,
 item.days_in_stage != null
 ? `W etapie: ${item.days_in_stage} dni`
 : null,
 addedAttribution,
 ]
 .filter(Boolean)
 .join("\n")
 }
 >
 {accessibleDetails && (
 <span id={detailsId} className="sr-only">
 {accessibleDetails}
 </span>
 )}
 <div className="absolute left-0 top-0 flex h-6 w-6 items-center justify-center">
 <Checkbox
 checked={selected}
 onCheckedChange={() => onToggleSelect(item.candidate_id)}
 aria-label={`Zaznacz ${fullName}`}
 className={cn(
 "relative h-6 w-6 border-0 bg-transparent before:absolute before:inset-1 before:rounded-md before:border before:border-border before:bg-card before:transition-colors hover:border-transparent hover:before:border-primary",
 "data-[state=checked]:border-transparent data-[state=checked]:bg-transparent data-[state=checked]:before:border-primary data-[state=checked]:before:bg-primary",
 "data-[state=indeterminate]:border-transparent data-[state=indeterminate]:bg-transparent data-[state=indeterminate]:before:border-primary data-[state=indeterminate]:before:bg-primary"
 )}
 />
 </div>

 {/* Kropka ostrzeżenia — jedyny sygnał hm_veto, który przeżywa gęsty
 widok pełnego pipeline'u (`desktopOverview`): tekstowy badge niżej na
 karcie (Weto HM) jest tam schowany (`xl:pointer-fine:hidden`),
 bo w tym trybie karta jest kilkunastopikselowym kafelkiem. Ta kropka
 NIE jest owinięta tym warunkiem — patrz `dołóż flagę bramki jako
 kropkę` w brief programu C2 (04 Pipeline). */}
 {gateFlagReason && (
 <span
 className="absolute left-4 top-0 z-10 h-2 w-2 rounded-full ring-2 ring-card bg-destructive"
 title={gateFlagReason}
 aria-hidden="true"
 />
 )}

 {desktopOverview && (
 <div className="absolute right-0 top-0 hidden h-6 min-w-6 items-center justify-center xl:pointer-fine:flex">
 <OverviewScoreBadge
 normalizedScore={normalizedMatchScore ?? undefined}
 loading={scoresLoading && normalizedMatchScore == null}
 candidateId={item.candidate_id}
 />
 </div>
 )}

 {/* Krok 04 Pipeline (flow C2): klik w TREŚĆ karty otwiera dok „Karta
 w procesie" (`handleCardClick` na kontenerze). Do profilu prowadzi
 wyłącznie nazwisko (link niżej) oraz „Pełny profil" w doku. Wcześniej
 link owijał całą treść, więc dok dało się otworzyć tylko z paddingu. */}
 {/* Wiersz 1 makiety: nazwisko (do dwóch linii, bez ucinania w połowie)
 + pierścień wyniku po prawej. Wielki awatar kandydata odpadł razem
 z jednolinijkowym nazwiskiem — przy ~176 px szerokości kolumny to on
 zabierał miejsce, przez które nazwisko trzeba było uciąć. */}
 {/* Wcięcie DOKŁADNIE pod checkbox: jego pole wizualne (`before:inset-1`)
 kończy się 20 px od lewej krawędzi karty, a padding karty to 12 px
 (cozy) / 8 px (compact). Stare `pl-5` zostawiało nazwisku 64 z 158 px
 karty — stąd „Wojcie/ch" łamane w środku wyrazu. */}
 <div className={cn("flex items-start gap-2", density === "compact" ? "pl-3" : "pl-2", desktopOverview &&"xl:pointer-fine:items-center xl:pointer-fine:gap-1 xl:pointer-fine:pl-0")}>
 <div className="min-w-0 flex-1">
 <Link
 href={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
 aria-label={fullName}
 aria-describedby={accessibleDetails ? detailsId : undefined}
 onClick={(e) => e.stopPropagation()}
 // `break-words`, NIE `overflow-wrap:anywhere` — to drugie łamie nazwisko
 // w środku wyrazu przy ~176 px kolumny („Wojcie/ch Wyleżoł"), czyli robi
 // dokładnie to, czego ta karta miała się pozbyć.
 className={cn("block font-semibold text-foreground hover:underline break-words line-clamp-2",
 density === "compact" ?"text-[11px] leading-tight" :"text-[13px] leading-snug",
 desktopOverview &&"xl:pointer-fine:whitespace-normal xl:pointer-fine:break-words xl:pointer-fine:text-[10px] xl:pointer-fine:font-semibold xl:pointer-fine:leading-3"
 )}
 >
 {fullName}
 </Link>
 </div>
 {(normalizedMatchScore != null || scoresLoading) && (
 <div className={cn(desktopOverview &&"xl:pointer-fine:hidden")}>
 {/* Zawsze `compact`: kolumna kanbana ma ~176 px, a pierścień „cozy"
 (40 px) zabierał ćwierć tej szerokości nazwisku obok. Gęstość
 steruje tu paddingiem i krojem, nie rozmiarem pierścienia. */}
 <ScoreRing score={normalizedMatchScore} density="compact" />
 </div>
 )}
 </div>

 {/* Wiersz 2 makiety: właściciel karty po lewej, wiek na etapie po prawej. */}
 <div
 className={cn(
 // Bez `pl-5`: checkbox jest absolutny i zajmuje tylko górne 24 px, więc
 // wcięcie w dolnych wierszach kradłoby 20 px z i tak wąskiej kolumny.
 "mt-1 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[10.5px] text-muted-foreground",
 desktopOverview && "xl:pointer-fine:justify-center xl:pointer-fine:gap-0 xl:pointer-fine:text-[9px] xl:pointer-fine:leading-none"
 )}
 title={addedAttribution}
 >
 <span
 className={cn(
 "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[7px] font-semibold",
 hasAddedByName
 ? "bg-primary/10 text-primary"
 : "bg-warning/15 text-warning",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 aria-hidden="true"
 >
 {ownerInitials}
 </span>
 <span
 className={cn(
 "min-w-0 truncate",
 !hasAddedByName && "text-warning",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 aria-hidden="true"
 >
 {addedByShortName}
 </span>
 {desktopOverview && (
 <span className="hidden truncate xl:pointer-fine:inline" aria-hidden="true">
 R: {addedByShortName}
 </span>
 )}
 {item.rating != null && item.rating > 0 && (
 <span
 className={cn(
 "inline-flex items-center gap-0.5",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 aria-hidden="true"
 >
 <Star className="h-2.5 w-2.5 fill-amber-500 text-amber-500" />
 {item.rating.toFixed(1)}
 </span>
 )}
 {item.hm_veto && (
 <span
 className={cn(
 "inline-flex items-center gap-0.5 rounded px-1 text-[9px] font-semibold uppercase tracking-wide bg-destructive/10 text-destructive",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={[
 `${item.hm_veto.hiring_manager_name ?? "Hiring manager tej rekrutacji"} odrzucił(a) tego kandydata po rozmowie ${formatDate(item.hm_veto.rejected_at)}`,
 `Powód: ${item.hm_veto.rejection_reason_name}`,
 item.hm_veto.source_job_title
 ? `Rekrutacja: ${item.hm_veto.source_job_title}`
 : null,
 "Ostrzeżenie — ruch jest możliwy po potwierdzeniu.",
 ]
 .filter(Boolean)
 .join("\n")}
 >
 <UserX className="h-2.5 w-2.5" />
 Weto HM
 </span>
 )}
 {overBudget && (
 <span
 className={cn(
 "inline-flex items-center gap-0.5 rounded px-1 text-[9px] font-semibold uppercase tracking-wide bg-warning/15 text-warning",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={`Stawka ${formatExpectedRate(item) ?? ""} przekracza budżet godzinowy rekrutacji. Ruch nie jest blokowany.`}
 >
 <AlertTriangle className="h-2.5 w-2.5" />
 ponad budżet
 </span>
 )}
 {!readOnly && scorecardDue && (
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onOpenScorecard(item);
 }}
 className={cn(
 "inline-flex items-center gap-0.5 rounded px-1 text-[9px] font-semibold bg-warning/15 text-warning hover:bg-warning hover:text-white transition-colors",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title="Scorecard tego etapu — do uzupełnienia"
 aria-label={`Uzupełnij scorecard dla ${fullName}`}
 >
 <Flag className="h-2.5 w-2.5" />
 Scorecard
 </button>
 )}
 {daysBadge && (
 <span
 className={cn(
 "ml-auto shrink-0 tabular-nums",
 daysBadge === "danger"
 ? "font-semibold text-destructive"
 : daysBadge === "warning"
 ? "font-semibold text-warning"
 : "",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 aria-hidden="true"
 >
 {item.days_in_stage} d
 </span>
 )}
 </div>

 {contactFeatureEnabled ? (
 <div className={cn(desktopOverview &&"xl:pointer-fine:sr-only")}>
 <ContactStatusBadge contactCase={item.contact_case} className="mt-1" />
 </div>
 ) : null}

 {/* Wiersz 3 makiety: co dalej z tą kartą. */}
 <NextActionRow action={nextAction} hidden={desktopOverview} />

 {/* Usuń z rekrutacji — akcja korekcyjna („dodano nie tego kandydata").
 Hover-revealed, żeby nie zaśmiecać karty. */}
 {!readOnly && <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onRemoveFromRecruitment(item);
 }}
 className={cn("absolute right-1 z-10 inline-flex items-center justify-center rounded-md bg-card/80 text-muted-foreground opacity-0 transition-opacity","hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-hidden",
 density === "compact" ?"h-5 w-5" :"h-6 w-6",
 desktopOverview &&"xl:pointer-fine:h-6 xl:pointer-fine:w-6",
 "top-1",
 desktopOverview &&"xl:pointer-fine:bottom-0 xl:pointer-fine:left-0 xl:pointer-fine:right-auto xl:pointer-fine:top-auto"
 )}
 title="Usuń kandydata z tej rekrutacji"
 aria-label={`Usuń ${fullName} z rekrutacji`}
 >
 <Trash2 className={density === "compact" ?"h-3 w-3" :"h-3.5 w-3.5"} />
 </button>}

 {/* Screening jest WIERSZEM karty, nie elementem na `absolute bottom-1
 right-1`: tamta pozycja to dokładnie wiersz „co dalej z tą kartą"
 (`NextActionRow`), więc na „Zweryfikowany" pigułka „Uzupełnij screening"
 przykrywała „Wyślij CV do klienta". Przy kartach 25 px (tryb kafelkowy)
 nie było tego widać — odsłoniły to karty 200 px. */}
 {!readOnly && canScreen && (
 <div className={cn("mt-1 flex justify-end", desktopOverview &&"xl:pointer-fine:mt-0")}>
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onOpenScreening(item.id, fullName);
 }}
 className={cn("inline-flex max-w-full items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full font-semibold hover:bg-primary hover:text-white transition-colors",
 screeningDue
 ? "bg-warning/15 text-warning ring-1 ring-warning/40"
 : "bg-primary/10 text-primary",
 desktopOverview &&"xl:pointer-fine:h-6 xl:pointer-fine:w-6 xl:pointer-fine:justify-center xl:pointer-fine:gap-0 xl:pointer-fine:p-0")}
 title={screeningDue ? "Screening Championa — do uzupełnienia" : "Screening Championa"}
 aria-label={`${screeningDue ? "Uzupełnij screening" : "Screening Championa"} dla ${fullName}`}
 >
 <Sparkles className="h-2.5 w-2.5 shrink-0" />
 <span className={cn("truncate", desktopOverview &&"xl:pointer-fine:sr-only")}>
 {screeningDue ? "Uzupełnij screening" : "Screening"}
 </span>
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
 scoreMap?: Map<number, number>;
 scoresLoading?: boolean;
 /** Definicje etapów ze scorecardem — odznaka „Scorecard" (17.09.2026). */
 stagesWithScorecard: Set<number>;
 onOpenScorecard: (item: KanbanItem, col: KanbanColumn) => void;
 /** Budżet PLN/h rekrutacji — odznaka „ponad budżet". */
 jobBudgetHourly: number | null;
 onRemoveFromRecruitment: (item: KanbanItem) => void;
 contactFeatureEnabled: boolean;
 desktopOverview: boolean;
 fullPipelineDesktop: boolean;
 readOnly: boolean;
 /** Kolumna „poza szablonem" jest wyłącznie ŹRÓDŁEM: kartę można z niej
  *  wyciągnąć, ale nie da się jej tam upuścić (upuszczenie znaczyłoby ruch
  *  na przypadkowy etap). */
 dropDisabled?: boolean;
 onOpenDock: (item: KanbanItem) => void;
 /** `true` = karta nie pasuje aktywnym filtrom lewej kolumny (przyciemnij). */
 isDimmed: (item: KanbanItem) => boolean;
 /** Grupa etapu policzona nad CAŁĄ tablicą — bez niej własny etap wewnętrzny
  *  po screeningu byłby nie do odróżnienia od etapu wejściowego. */
 group?: PipelineGroupKey;
 /** SLA klienta w dniach roboczych (karta klienta) — `null` = nie ustawiono. */
 slaDays: number | null;
}

const KanbanColumnV2 = memo(function KanbanColumnV2({
 col,
 jobId,
 selectedIds,
 onToggleSelect,
 onOpenScreening,
 density,
 scoreMap,
 scoresLoading,
 stagesWithScorecard,
 onOpenScorecard,
 jobBudgetHourly,
 onRemoveFromRecruitment,
 contactFeatureEnabled,
 desktopOverview,
 fullPipelineDesktop,
 readOnly,
 dropDisabled,
 onOpenDock,
 isDimmed,
 group,
 slaDays,
}: ColProps) {
 const dropId = colId(col);
 // `Boolean(...)` obowiązkowo — @hello-pangea/dnd ma twardy invariant
 // („isDropDisabled must be a boolean"), a `undefined` wywala całą tablicę.
 const noDrop = Boolean(dropDisabled);
 // Jedna tablica akcji na kolumnę, memoizowana razem z nią — gdyby liczyć je
 // w JSX-ie, każda karta dostawałaby nowy obiekt przy KAŻDYM renderze kolumny
 // (np. po zaznaczeniu sąsiada) i `memo` na `CandidateKanbanCard` przestałoby
 // cokolwiek dawać na tablicy z 26+ kartami.
 const nextActions = useMemo(
 () => col.items.map((it) => nextActionFor(it, col, { slaDays, group })),
 [col, slaDays, group]
 );
 const slaHint = useMemo(
 () => columnSlaHint(col, { slaDays, group, oldestDays: oldestDaysInColumn(col) }),
 [col, slaDays, group]
 );
 return (
 <div
 data-colid={dropId}
 data-drop-disabled={noDrop}
 role="group"
 aria-label={`${columnLabel(col)}, liczba kandydatów: ${col.count}`}
 className={cn(
 "flex w-[calc((100%-1.5rem)/3)] min-w-[17rem] shrink-0 flex-col rounded-lg border border-border bg-background/60 sm:min-w-[19rem]",
 fullPipelineDesktop && desktopOverview &&"xl:pointer-fine:w-0 xl:pointer-fine:min-w-0 xl:pointer-fine:basis-0 xl:pointer-fine:grow xl:pointer-fine:shrink",
 // Mało kolumn: NIE ściskamy ich do zera. Podłoga 11 rem to szerokość,
 // przy której makieta mieści pełną kartę (nazwisko do dwóch linii,
 // właściciel, wiek, następna akcja); poniżej karta znów byłaby kafelkiem,
 // tylko bez uczciwego trybu przeglądowego. Board ma `overflow-auto`, więc
 // nadmiar kolumn scrolluje się w poziomie — tak jak w makiecie.
 fullPipelineDesktop && !desktopOverview &&"xl:pointer-fine:w-auto xl:pointer-fine:min-w-[11rem] xl:pointer-fine:basis-[11rem] xl:pointer-fine:grow"
 )}
 >
 <div className={cn("sticky top-0 z-10 rounded-t-lg bg-background/95 backdrop-blur-xs border-b border-border flex items-center gap-2", density === "compact" ?"px-3 py-2" :"px-4 py-3", desktopOverview &&"xl:pointer-fine:min-h-14 xl:pointer-fine:flex-col xl:pointer-fine:items-stretch xl:pointer-fine:gap-1 xl:pointer-fine:px-1 xl:pointer-fine:py-1.5")}>
 {col.category && (
 <Tooltip>
 <TooltipTrigger asChild>
 <span
 className={cn("h-2 w-2 rounded-full shrink-0",
 desktopOverview &&"xl:pointer-fine:h-1.5 xl:pointer-fine:w-1.5 xl:pointer-fine:self-center",
 CATEGORY_COLOR[col.category]
 )}
 aria-label={CATEGORY_LABEL[col.category]}
 />
 </TooltipTrigger>
 <TooltipContent side="top">{CATEGORY_LABEL[col.category]}</TooltipContent>
 </Tooltip>
 )}
 <h3 className={cn("text-foreground flex-1 truncate", density === "compact" ?"text-sm font-medium" :"text-xl font-semibold", desktopOverview &&"xl:pointer-fine:line-clamp-2 xl:pointer-fine:whitespace-normal xl:pointer-fine:text-center xl:pointer-fine:text-[10px] xl:pointer-fine:leading-tight xl:pointer-fine:[overflow-wrap:anywhere]")} title={columnLabel(col)}>
 {columnLabel(col)}
 </h3>
 <Badge size="sm" variant={col.count > 0 ?"soft" :"outline"} className={cn(desktopOverview &&"xl:pointer-fine:h-4 xl:pointer-fine:min-w-4 xl:pointer-fine:self-center xl:pointer-fine:px-1 xl:pointer-fine:text-[9px]")}>
 {col.count}
 </Badge>
 </div>

 {/* Druga linia nagłówka: SLA klienta po lewej, najstarsza karta po prawej.
 „SLA: —" zamiast pustki — cisza czytałaby się jak „zdążamy", a prawda
 jest taka, że na tej kolumnie nikt nic nie mierzy. */}
 <div
 data-column-sla={dropId}
 className={cn(
 "flex items-center justify-between gap-2 border-b border-border px-3 pb-1.5 pt-1 text-[9.5px] text-muted-foreground",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 >
 <span className="min-w-0 truncate">{slaHint.left}</span>
 {slaHint.right && (
 <span
 className={cn(
 "shrink-0 tabular-nums",
 slaHint.rightTone === "bad"
 ? "font-semibold text-destructive"
 : slaHint.rightTone === "warn"
 ? "font-semibold text-warning"
 : ""
 )}
 >
 {slaHint.right}
 </span>
 )}
 </div>

 <Droppable droppableId={dropId} isDropDisabled={noDrop}>
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
 desktopOverview &&"xl:pointer-fine:space-y-1 xl:pointer-fine:p-1",
 snapshot.isDraggingOver &&"bg-primary/10"
 )}
 >
 {col.items.map((item, index) => (
 <Draggable
 key={String(item.id)}
 draggableId={String(item.id)}
 index={index}
 isDragDisabled={readOnly}
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
 selected={selectedIds.has(item.candidate_id)}
 onToggleSelect={onToggleSelect}
 onOpenScreening={onOpenScreening}
 density={density}
 canScreen={SCREENING_BADGE_STAGES.has(item.stage)}
 // `=== false`, nie `!`: odpowiedź bez pola (starszy serwer) nie
 // pokazuje odznaki, której nie umie uzasadnić.
 screeningDue={
 SCREENING_BADGE_STAGES.has(item.stage) && item.screening_done === false
 }
 scorecardDue={
 Boolean(col.stage_def_id && stagesWithScorecard.has(col.stage_def_id)) &&
 item.scorecard_done === false
 }
 onOpenScorecard={(it) => onOpenScorecard(it, col)}
 overBudget={isOverHourlyBudget(item, jobBudgetHourly)}
 matchScore={scoreMap?.get(item.candidate_id)}
 scoresLoading={scoresLoading}
 onRemoveFromRecruitment={onRemoveFromRecruitment}
 contactFeatureEnabled={contactFeatureEnabled}
 desktopOverview={desktopOverview}
 readOnly={readOnly}
 onOpenDock={onOpenDock}
 dimmed={isDimmed(item)}
 nextAction={nextActions[index]}
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

/**
 * Zwinięta grupa pustych etapów — JEDNA kolumna-zastępnik zamiast trzech
 * pustych („Default B2B" ma trzynaście pustych kolumn z piętnastu).
 *
 * Zastępnik JEST celem upuszczenia — pod `droppableId` PIERWSZEJ kolumny swojej
 * grupy („CV Wysłane" dla etapów u klienta, „Umowa wysłana" dla umowy). Bez
 * tego zwijanie zabierałoby najczęstszy ruch w produkcie: pierwsze CV do
 * klienta przeciągane ze Screeningu na pusty jeszcze etap „CV Wysłane"
 * wymagałoby wcześniejszego kliknięcia „Rozwiń etapy", czyli regresu
 * domyślnego zachowania w zamian za porządek na ekranie.
 *
 * Dwie rzeczy, na których to stoi:
 *  1. `onDragEnd` rozwiązuje cel po `droppableId` (`stageCols.find(c => colId(c)
 *     === res.destination.droppableId)`), NIE po indeksie — więc upuszczenie tu
 *     wpada w tę samą ścieżkę `requestMove` co każdy inny drop, z całą bramką
 *     i modalami (stawka do klienta, weto HM, powód odrzucenia). Zero nowej
 *     logiki ruchu.
 *  2. Kolumna, której id pożyczamy, jest zwinięta, więc NIE jest renderowana —
 *     `droppableId` nie dubluje się (biblioteka tego wymaga). Gdy grupa się
 *     rozwija, zastępnik znika razem z tym id.
 *
 * Karta trafia zawsze na PIERWSZY etap grupy, nie na „przypadkowy" — to jest
 * ten etap, na który i tak prowadzi kolejność szablonu.
 */
const CollapsedGroupColumn = memo(function CollapsedGroupColumn({
 group,
 fullPipelineDesktop,
 desktopOverview,
 readOnly,
 onExpand,
}: {
 group: PipelineColumnGroup;
 fullPipelineDesktop: boolean;
 desktopOverview: boolean;
 readOnly: boolean;
 onExpand: () => void;
}) {
 const label = PIPELINE_GROUP_SHORT_LABEL[group.key];
 // Grupa zwija się dopiero od dwóch kolumn, więc pierwsza zawsze istnieje.
 const dropTarget = group.columns[0];
 // `Boolean(...)` obowiązkowo — @hello-pangea/dnd ma twardy invariant na
 // `isDropDisabled`. Ta sama wartość ląduje w atrybucie niżej, żeby test
 // wiązał się z NIĄ, a nie z własną kopią flagi (DnD nie odpala się w jsdom).
 const noDrop = Boolean(readOnly);
 return (
 <div
 data-collapsed-group={group.key}
 data-drop-disabled={noDrop}
 role="group"
 aria-label={`${label}, grupa pustych etapów: ${group.columns
 .map((c) => columnLabel(c))
 .join(", ")}. Upuszczenie karty przenosi ją na etap ${columnLabel(dropTarget)}.`}
 className={cn(
 "flex w-[calc((100%-1.5rem)/3)] min-w-[17rem] shrink-0 flex-col rounded-lg border border-dashed border-border bg-background/40 sm:min-w-[19rem]",
 fullPipelineDesktop && desktopOverview && "xl:pointer-fine:w-0 xl:pointer-fine:min-w-0 xl:pointer-fine:basis-0 xl:pointer-fine:grow xl:pointer-fine:shrink",
 fullPipelineDesktop && !desktopOverview && "xl:pointer-fine:w-auto xl:pointer-fine:min-w-[11rem] xl:pointer-fine:basis-[11rem] xl:pointer-fine:grow"
 )}
 >
 <div className="flex items-center gap-2 border-b border-border px-3 py-2">
 <span className="h-2 w-2 shrink-0 rounded-full bg-muted-foreground/40" aria-hidden="true" />
 <h3 className="min-w-0 flex-1 truncate text-sm font-medium text-muted-foreground" title={label}>
 {label}
 </h3>
 <Badge size="sm" variant="outline">
 {group.count}
 </Badge>
 </div>
 <div className="border-b border-border px-3 pb-1.5 pt-1 text-[9.5px] text-muted-foreground">
 <span className="line-clamp-2">
 {group.columns.map((c) => columnLabel(c)).join(" · ")}
 </span>
 </div>
 <Droppable droppableId={colId(dropTarget)} isDropDisabled={noDrop}>
 {(provided, snapshot) => (
 <div
 ref={provided.innerRef}
 {...provided.droppableProps}
 className={cn(
 "flex flex-1 flex-col gap-2 p-2.5 text-[10.5px] leading-snug text-muted-foreground transition-colors",
 snapshot.isDraggingOver && "bg-primary/10"
 )}
 >
 {snapshot.isDraggingOver ? (
 // Ghost z makiety (linia 1110): w trakcie przeciągania zastępnik
 // mówi WPROST, na który etap trafi karta — inaczej upuszczenie na
 // kolumnę podpisaną nazwą grupy byłoby zgadywanką.
 <div className="grid place-items-center rounded-lg border-[1.5px] border-dashed border-primary/45 bg-primary/5 px-2 py-3 text-center font-medium text-primary">
 upuść tutaj → {columnLabel(dropTarget)}
 </div>
 ) : (
 <>
 <p>
 {countPl(group.columns.length, "etap", "etapy", "etapów")} zwinięte,
 dopóki są puste. Upuszczenie karty tutaj przenosi ją na etap
 „{columnLabel(dropTarget)}".
 </p>
 <button
 type="button"
 onClick={onExpand}
 className="self-start rounded-md border border-border px-2 py-1 text-[10.5px] text-foreground transition-colors hover:bg-accent"
 >
 Rozwiń etapy
 </button>
 </>
 )}
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

export function KanbanBoardV2({ columns, jobId, jobTitle, scoreMap, scoresLoading, headerCollapsed, offTemplate, readOnly = false, clientId = null, focusCandidateId = null }: KanbanBoardV2Props) {
 const density = useUiStore((s) => s.density);
 const setDensity = useUiStore((s) => s.setDensity);
 // Krok 04 Pipeline (flow C2, PR 3/7): globalny przełącznik, jak `density` —
 // świadomie nie per-job.
 const hideEmptyColumns = useUiStore((s) => s.hideEmptyKanbanColumns);
 const setHideEmptyColumns = useUiStore((s) => s.setHideEmptyKanbanColumns);
 const queryClient = useQueryClient();
 const contactFeature = useCandidateContactFeature();
 const { showActionToast, showSuccess, showError } = useToast();
 // Pełny zbiór ról (primary + secondary), nie tylko primary — hybryda ról
 // widzi to, na co pozwala jej którakolwiek z nich (parity z backendem).
 const authUser = useAuthStore((s) => s.user);
 const canEditRates = getUserRoles(authUser).some((r) => RATE_EDIT_ROLES.has(r));
 const [cols, setCols] = useState(() => composeColumns(columns, offTemplate));
 // Kolumny SZABLONU — wszystko, co wybiera cel ruchu albo mierzy pipeline,
 // musi iść po tej liście, nie po `cols` (w `cols` siedzi też kubełek).
 const stageCols = useMemo(() => cols.filter((c) => !isOffTemplate(c)), [cols]);
 const [focusedColId, setFocusedColId] = useState<string | null>(() =>
 defaultFocusColumnId(columns)
 );
 // Zaznaczenie po `candidate_id`, nie po id etapu: każdy ruch tworzy NOWY
 // `CandidateStage`, więc id etapu zaznaczonej karty po ruchu przestawało
 // istnieć, a „Zaznaczono N" liczyło martwe wpisy.
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
 // Nazwa szablonu do nagłówka lewej kolumny — z odpowiedzi, którą board i tak
 // już pobiera przy rejection-reasons. Żadnego dodatkowego zapytania.
 const [templateName, setTemplateName] = useState<string | null>(null);
 // M4 PR-03 (audyt P1.6): potwierdzenie przed hired — ruch tworzy draft
 // kontraktu + zamówienia, nie powinien być skutkiem samego puszczenia myszy.
 const [hiredConfirm, setHiredConfirm] = useState<{
 item: KanbanItem;
 destCol: KanbanColumn;
 srcColId: string;
 } | null>(null);
 // Budżet GODZINOWY rekrutacji — ta sama liczba co nagłówek i wyszukiwanie;
 // odznaka „ponad budżet" i okno „Zweryfikowany" porównują się z nim.
 const [jobBudgetHourlyValue, setJobBudgetHourlyValue] = useState<number | null>(null);
 // `GET /api/jobs/{id}` liczy to tą samą funkcją co `PATCH …/client-rate`
 // (admin, DL, TAC, TCM, HoR, Finanse albo właściciel/twórca rekrutacji).
 // Reszta przenosi kartę na „CV Wysłane" bez pytania o stawkę — okno
 // kończyłoby się 403 po wpisaniu kwoty.
 const [canWriteClientRate, setCanWriteClientRate] = useState(false);

 // Krok 04 Pipeline (flow C2, PR 3/7): dok „Karta w procesie" — trzymany po
 // `candidate_id` (STABILNY), nie po id CandidateStage (`item.id` zmienia się
 // przy KAŻDYM ruchu — `sendMove`/`submitVerifiedMove` podmieniają je na nowy
 // wiersz). Po candidate_id dok „podąża" za kandydatem przez ruchy bez żadnej
 // dodatkowej synchronizacji.
 const [dockCandidateId, setDockCandidateId] = useState<number | null>(null);
 const openDock = useCallback((item: KanbanItem) => {
 setDockCandidateId(item.candidate_id);
 }, []);
 const closeDock = useCallback(() => setDockCandidateId(null), []);
 // Deep link `?candidate=` otwiera dok RAZ na wartość parametru — zamknięcie
 // doku przez użytkownika nie może go ponownie otworzyć przy odświeżeniu kart.
 const focusHandledRef = useRef<number | null>(null);
 useEffect(() => {
 if (focusCandidateId == null || focusHandledRef.current === focusCandidateId) return;
 if (!cols.some((c) => c.items.some((i) => i.candidate_id === focusCandidateId))) return;
 focusHandledRef.current = focusCandidateId;
 setDockCandidateId(focusCandidateId);
 }, [focusCandidateId, cols]);

 // Lewa kolumna: filtry NIE usuwają kart z `cols` (zepsułoby to indeksy
 // `@hello-pangea/dnd`, na których stoi `onDragEnd` — patrz `PipelineFiltersRail`).
 // Przyciemniają niepasujące karty; `isDimmed` musi mieć stabilną referencję
 // (memo na `KanbanColumnV2`/`CandidateKanbanCard` — patrz komentarz niżej przy
 // `toggleSelect`), stąd `useCallback` z zależnościami tylko od samych filtrów.
 const [stuckFilter, setStuckFilter] = useState(false);
 const [blockedFilter, setBlockedFilter] = useState(false);
 const [noActionFilter, setNoActionFilter] = useState(false);
 const [recruiterFilter, setRecruiterFilter] = useState<string | null>(null);

 // Grupy etapów — jedno źródło dla lewej kolumny, zwijania pustych grup na
 // tablicy i „następnej akcji" na karcie (bez grupy własny etap wewnętrzny po
 // screeningu byłby nie do odróżnienia od etapu wejściowego).
 const stageGroups = useMemo(() => groupKanbanColumns(stageCols), [stageCols]);
 const groupByColId = useMemo(() => {
 const map = new Map<string, PipelineGroupKey>();
 for (const group of stageGroups) {
 for (const col of group.columns) map.set(colId(col), group.key);
 }
 return map;
 }, [stageGroups]);

 // SLA klienta z jego karty (`client_playbooks`) — TA SAMA ścieżka i ten sam
 // klucz zapytania, co krok 06 „CV do klienta". Bez `clientId` hook nie strzela
 // w ogóle, a rail mówi wprost, że SLA nie jest ustawione.
 const playbookQuery = useClientPlaybook(clientId);
 const slaDays = playbookQuery.data?.sla_business_days ?? null;

 // Grupy pustych etapów rozwinięte ręcznie („Rozwiń etapy" na zastępniku).
 const [expandedGroups, setExpandedGroups] = useState<Set<PipelineGroupKey>>(
 () => new Set()
 );
 const expandGroup = useCallback((key: PipelineGroupKey) => {
 setExpandedGroups((prev) => {
 if (prev.has(key)) return prev;
 const next = new Set(prev);
 next.add(key);
 return next;
 });
 }, []);

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
 }, [
 measureColumnHeight,
 headerCollapsed,
 density,
 statusMessage,
 cols.length,
 selected.size,
 ]);

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
 // 409 ELIGIBILITY_WARNING (17.09.2026) — jedno okno na tablicę. `retry`
 // powtarza ruch, który je wywołał, z `acknowledge_eligibility: true`;
 // `onDismiss` pozwala kolejce zbiorczej pójść dalej po „Anuluj".
 const [eligibilityWarning, setEligibilityWarning] = useState<{
 reason: string;
 retry: () => Promise<void>;
 onDismiss?: () => void;
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

 useEffect(() => {
 setCols(composeColumns(columns, offTemplate));
 setFocusedColId((current) =>
 current && columns.some((col) => colId(col) === current)
 ? current
 : defaultFocusColumnId(columns)
 );
 }, [columns, offTemplate]);

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
 setJobBudgetHourlyValue(resolveJobBudgetHourly(jobRes.data));
 setCanWriteClientRate(jobRes.data?.can_write_client_rate === true);
 const tid = jobRes.data?.pipeline_template_id;

 let reasons: {
 id: string;
 label: string;
 applies_to: ("rejected" |"withdrawn")[];
 }[] = [];
 if (tid) {
 const detail = await pipelineTemplatesApi.get(tid);
 reasons = mapReasons(detail.data.rejection_reasons ?? []);
 // Nazwa szablonu do nagłówka lewej kolumny — z odpowiedzi, która i tak
 // tu leci po rejection-reasons.
 const tname = (detail.data as { name?: string | null }).name;
 setTemplateName(typeof tname === "string" && tname.trim() ? tname : null);
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

 // Navigator zmienia tylko poziomy viewport. Szukamy po dataset zamiast
 // składać selektor CSS, żeby custom stage IDs pozostały bezpieczne.
 const scrollToColumn = useCallback((
 id: string,
 behavior: ScrollBehavior = "smooth"
 ) => {
 const el = Array.from(
 boardRef.current?.querySelectorAll<HTMLElement>("[data-colid]") ?? []
 ).find((column) => column.dataset.colid === id);
 el?.scrollIntoView?.({
 behavior,
 inline: "center",
 block: "nearest",
 });
 }, []);

 const focusColumn = useCallback(
 (id: string) => {
 setFocusedColId(id);
 scrollToColumn(id);
 },
 [scrollToColumn]
 );

 const initialFocusApplied = useRef(false);
 useEffect(() => {
 if (!focusedColId) return;
 const behavior = initialFocusApplied.current ? "smooth" : "auto";
 initialFocusApplied.current = true;
 const frame = window.requestAnimationFrame(() =>
 scrollToColumn(focusedColId, behavior)
 );
 return () => window.cancelAnimationFrame(frame);
 }, [focusedColId, cols.length, scrollToColumn]);

 // Po zmianie breakpointu/obrocie ekranu aktywny etap ma nadal zostać w
 // centrum nowego viewportu, a nie utknąć w pozycji policzonej dla desktopu.
 useEffect(() => {
 if (!focusedColId) return;
 const refocusAfterResize = () => {
 window.requestAnimationFrame(() => scrollToColumn(focusedColId, "auto"));
 };
 window.addEventListener("resize", refocusAfterResize);
 return () => window.removeEventListener("resize", refocusAfterResize);
 }, [focusedColId, scrollToColumn]);

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

 // Strona trzyma pipeline pod `["kanban", id]` (`id` to string z `useParams`)
 // i karmi nim listwę kroków, klaster KPI w jobbarze oraz kolejki kroków
 // 05–08. Tablica ma WŁASNY stan `cols` (ruch optymistyczny), więc bez
 // unieważnienia tamtego zapytania po ruchu KPI i kolejki pokazywały stan
 // sprzed ruchu aż do przeładowania strony. Oba klucze — jak w
 // `confirmRemoveFromRecruitment` (część konsumentów trzyma liczbę).
 const syncKanbanCache = useCallback(() => {
 void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
 void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
 }, [queryClient, jobId]);

 // M4 PR-03: po błędzie ruchu NIE zostawiamy karty w niepotwierdzonej
 // kolumnie — dociągamy prawdę z serwera (a nie lokalny snapshot, bo 409
 // oznacza, że stan pary i tak się zmienił pod nami).
 const refreshBoardAfterMove = useCallback(async () => {
 try {
 const fresh = await pipelineApi.kanban(jobId);
 if (Array.isArray(fresh.data?.columns)) {
 setCols(
 composeColumns(
 fresh.data.columns as KanbanColumn[],
 fresh.data.off_template as OffTemplateColumn | null
 )
 );
 }
 } catch (e) {
 console.error("Kanban refresh failed", e);
 }
 // Częściowy sukces (bulk) i 409 „stan zmienił się pod nami" dotyczą też
 // reszty strony — ta sama prawda ma trafić do KPI i kolejek kroków.
 syncKanbanCache();
 }, [jobId, syncKanbanCache]);

 // „Anuluj" w oknie ostrzeżenia: optymistyczna karta wraca na miejsce
 // (prawda serwera), a kolejka zbiorcza — jeśli to ona pytała — idzie dalej.
 const dismissEligibilityWarning = useCallback(async () => {
 const onDismiss = eligibilityWarning?.onDismiss;
 setEligibilityWarning(null);
 onDismiss?.();
 await refreshBoardAfterMove();
 }, [eligibilityWarning, refreshBoardAfterMove]);

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
 opts?: {
 silent?: boolean;
 // Pętle zbiorcze (i ruch + PATCH stawki) unieważniają zapytanie strony
 // RAZ, po całej operacji — odświeżenie w środku pętli nadpisywało
 // optymistyczne ruchy kolejnych kart stanem sprzed nich.
 deferCacheSync?: boolean;
 // F05: pojedynczy ruch z karty odsyła wersję procesu
 // (`expected_state_version`). Ruchy zbiorcze przekazują `false` — bez
 // sprawdzenia, jak dotąd.
 checkVersion?: boolean;
 // 17.09.2026: powtórka po 409 ELIGIBILITY_WARNING („Przenieś mimo to").
 acknowledgeEligibility?: boolean;
 }
 ): Promise<boolean> => {
 try {
 const response = await api.post<{
 id?: number;
 verification_status?:"active" |"pending" |"rejected";
 scheduled_rejection_email_id?: number | null;
 process_state_version?: number | null;
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
 expected_state_version:
 opts?.checkVersion === false ? undefined : expectedStateVersionOf(item),
 acknowledge_eligibility: opts?.acknowledgeEligibility ? true : undefined,
 });

 // M4 PR-03 (audyt P1.3): backend tworzy NOWY CandidateStage — karta w
 // cache dostaje jego id + status z serwera. Bez tego kolejne akcje
 // (screening, scorecard, accept/reject) celowały w historyczny rekord.
 const newStageId = response?.data?.id;
 const serverVerifStatus = response?.data?.verification_status;
 // F05: nowa wersja procesu — kolejny ruch z tej karty przed odświeżeniem
 // tablicy nie może wysłać wersji sprzed własnego ruchu.
 const serverVersion = response?.data?.process_state_version;
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
 process_state_version:
 typeof serverVersion === "number"
 ? serverVersion
 : i.process_state_version,
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

 // Od 17.09.2026 po ruchu NIE otwieramy arkuszy screeningu ani scorecardu —
 // nowy wiersz etapu ma je puste, więc karta pokazuje odznaki
 // „do uzupełnienia" (screening_done/scorecard_done), a arkusz otwiera się
 // z karty albo doku, kiedy rekruter ma na to czas.
 if (currentStageId !== item.id) {
 setCols((prev) =>
 prev.map((c) =>
 colId(c) !== colId(dst)
 ? c
 : {
 ...c,
 items: c.items.map((i) =>
 i.id === currentStageId
 ? { ...i, screening_done: false, scorecard_done: false }
 : i
 ),
 }
 )
 );
 }
 if (!opts?.deferCacheSync) syncKanbanCache();
 return true;
 } catch (e) {
 console.error("Move failed", e);
 if (
 !opts?.silent &&
 !opts?.acknowledgeEligibility &&
 isEligibilityWarning(e)
 ) {
 // Czarna lista / NDA / konkurent / weto HM: jedno pytanie, potem TEN
 // SAM ruch z potwierdzeniem. Optymistyczna karta czeka na decyzję;
 // „Anuluj" cofa ją prawdą serwera.
 setEligibilityWarning({
 reason: eligibilityWarningReason(e) ?? "Serwer ostrzega przed tym ruchem.",
 retry: async () => {
 setEligibilityWarning(null);
 await sendMoveRef.current?.(item, dst, reason, {
 ...opts,
 acknowledgeEligibility: true,
 });
 },
 });
 return false;
 }
 if (!opts?.silent && isPipelineVersionConflict(e)) {
 // Ktoś przesunął tę parę po odczycie tablicy: bez ponowienia —
 // pokazujemy prawdę serwera i dajemy zdecydować jeszcze raz.
 showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
 invalidateAfterPipelineVersionConflict(
 queryClient,
 jobId,
 item.candidate_id
 );
 await refreshBoardAfterMove();
 return false;
 }
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
 queryClient,
 refreshBoardAfterMove,
 syncKanbanCache,
 showActionToast,
 showSuccess,
 showError,
 ]
 );
 // Ref, nie zależność: `retry` w oknie ostrzeżenia woła NAJNOWSZĄ wersję
 // `sendMove`, a sam `sendMove` nie może zależeć od siebie.
 const sendMoveRef = useRef<typeof sendMove | null>(null);
 sendMoveRef.current = sendMove;

 // Krok 04 Pipeline (flow C2, PR 3/7): wyodrębnione z `onDragEnd`, żeby dok
 // „Karta w procesie" mogło wołać DOKŁADNIE tę samą decyzję co przeciągnięcie
 // karty — bez kopiowania gałęzi „Zweryfikowany"/„CV Wysłane"/„Zatrudniony"/
 // terminal. Zachowanie drag&drop jest bit w bit takie samo jak przed tym
 // refaktorem (czysta ekstrakcja, zero zmiany logiki).
 const requestMove = useCallback(
 (item: KanbanItem, srcColId: string, dst: KanbanColumn) => {
 if (readOnly) return;
 if (srcColId === colId(dst)) return;

 // Ta sama bramka co pigułki doku i warsztaty 05–07. Bez niej przeciągnięcie
 // karty „Pending" (albo z wetem na „CV Wysłane") otwierało modal stawki,
 // a dopiero po jego wypełnieniu serwer odpowiadał 409.
 const dstTerminal = terminalOf(dst);
 const blocked = moveBlockedReason({
 item,
 readOnly,
 terminal: dstTerminal === "rejected" || dstTerminal === "withdrawn",
 targetStage: dst.stage,
 });
 if (blocked) {
 showError(blocked);
 return;
 }

 // Która gałąź — decyduje `lib/pipeline-move-dialog`, wspólne z dokiem
 // „Decyzja" kroku 07. Zachowanie bit w bit takie samo jak przed
 // wyniesieniem warunków (czysta ekstrakcja, zero zmiany logiki).
 const dialog = moveDialogFor(dst);

 // Pending verification (migracja 0056) — najpierw zapytaj o rate,
 // dopiero potem optimistic + sendMove. NIE applyOptimistic tu, bo
 // recruiter może anulować w modalu.
 if (dialog === "verified_rate") {
 if (!canEditRates) {
 showError(RATE_EDIT_DENIED_MESSAGE);
 return;
 }
 setVerifiedQueue([]);
 setVerifiedBulkTotal(1);
 setVerifiedRatePrompt({
 item,
 destCol: dst,
 srcColId,
 });
 return;
 }

 // „CV Wysłane" — zapytaj o stawkę do klienta przed ruchem (recruiter może
 // pominąć lub anulować w modalu, dlatego NIE applyOptimistic tutaj).
 if (dialog === "client_rate" && canWriteClientRate) {
 setClientRateQueue([]);
 setClientRateBulkTotal(1);
 setClientRatePrompt({ item, destCol: dst, srcColId });
 return;
 }

 // M4 PR-03 (audyt P1.6): hired = artefakty (draft kontraktu i zamówienia)
 // — wymaga jawnego potwierdzenia zamiast samego drop-u.
 if (dialog === "hired_confirm") {
 setHiredConfirm({ item, destCol: dst, srcColId });
 return;
 }

 // Terminal — najpierw modal powodu; optimistic dopiero po potwierdzeniu,
 // żeby anulowanie nie zostawiało karty w złej kolumnie.
 if (dialog === "rejection") {
 const dropTerminal = terminalOf(dst);
 setPendingRejection({
 entries: [{ item, srcColId }],
 destCol: dst,
 terminalType: dropTerminal === "withdrawn" ? "withdrawn" : "rejected",
 });
 return;
 }

 applyOptimistic(item, srcColId, dst);
 sendMove(item, dst);
 },
 [readOnly, applyOptimistic, sendMove, showError, canEditRates, canWriteClientRate]
 );

 const onDragEnd = useCallback(
 (res: DropResult) => {
 if (readOnly) return;
 if (!res.destination) return;
 const src = cols.find((c) => colId(c) === res.source.droppableId);
 // `stageCols`, nie `cols` — kubełek nie jest celem ruchu. Istniejący
 // guard `if (!src || !dst) return;` domyka sprawę, gdyby drop przeszedł.
 const dst = stageCols.find((c) => colId(c) === res.destination!.droppableId);
 if (!src || !dst || colId(src) === colId(dst)) return;
 const item = src.items[res.source.index];
 if (!item) return;
 requestMove(item, colId(src), dst);
 },
 [cols, stageCols, requestMove, readOnly]
 );

 // Submit z okna „Zweryfikowany". `payload === null` = „Pomiń stawkę" (stawka
 // opcjonalna od 17.09.2026). `acknowledge` = powtórka po 409
 // ELIGIBILITY_WARNING; kolejka zbiorcza przesuwa się DOPIERO po decyzji.
 const submitVerifiedMove = useCallback(
 async (
 payload: { rate: number; unit: RateUnit; currency: string } | null,
 acknowledge = false
 ) => {
 if (!verifiedRatePrompt) return;
 const { item, destCol, srcColId } = verifiedRatePrompt;
 const isSingleMove = verifiedBulkTotal <= 1;
 const advanceQueue = () => {
 const [next, ...rest] = verifiedQueue;
 setVerifiedQueue(rest);
 setVerifiedRatePrompt(
 next ? { item: next.item, destCol, srcColId: next.srcColId } : null
 );
 };
 try {
 const res = await pipelineApi.move({
 candidate_id: item.candidate_id,
 job_id: jobId,
 stage: "verified",
 stage_def_id: destCol.stage_def_id ?? undefined,
 ...(payload
 ? {
 expected_rate_value: payload.rate,
 expected_rate_unit: payload.unit,
 expected_rate_currency: payload.currency,
 }
 : {}),
 // F05: tylko ruch pojedynczy — kolejka zbiorcza bez sprawdzenia.
 expected_state_version: isSingleMove
 ? expectedStateVersionOf(item)
 : undefined,
 acknowledge_eligibility: acknowledge ? true : undefined,
 });
 // Backend tworzy NOWY CandidateStage — bierzemy jego id (nie stare
 // item.id), żeby screening zapisał się na świeżym etapie „verified".
 const newStageId = (res?.data as { id?: number } | undefined)?.id ?? null;
 setCols((prev) =>
 prev.map((c) => {
 if (colId(c) === srcColId) {
 const items = c.items.filter((i) => i.id !== item.id);
 return { ...c, items, count: items.length };
 }
 if (colId(c) === colId(destCol)) {
 const enriched: KanbanItem = {
 ...item,
 id: newStageId ?? item.id,
 stage: destCol.stage,
 days_in_stage: 0,
 verification_status: "active",
 expected_rate_value: payload?.rate ?? item.expected_rate_value ?? null,
 expected_rate_unit: payload?.unit ?? item.expected_rate_unit ?? null,
 expected_rate_currency:
 payload?.currency ?? item.expected_rate_currency ?? null,
 // Nowy wiersz etapu — arkusze trzeba uzupełnić od nowa (odznaki).
 screening_done: false,
 scorecard_done: false,
 process_state_version:
 typeof res?.data?.process_state_version === "number"
 ? res.data.process_state_version
 : item.process_state_version,
 };
 const items = [...c.items, enriched];
 return { ...c, items, count: items.length };
 }
 return c;
 })
 );
 syncKanbanCache();
 advanceQueue();
 } catch (e) {
 console.error("Move to verified failed", e);
 if (!acknowledge && isEligibilityWarning(e)) {
 setEligibilityWarning({
 reason: eligibilityWarningReason(e) ?? "Serwer ostrzega przed tym ruchem.",
 retry: async () => {
 setEligibilityWarning(null);
 await submitVerifiedMoveRef.current?.(payload, true);
 },
 onDismiss: advanceQueue,
 });
 return;
 }
 if (isPipelineVersionConflict(e)) {
 showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
 invalidateAfterPipelineVersionConflict(
 queryClient,
 jobId,
 item.candidate_id
 );
 await refreshBoardAfterMove();
 } else {
 showError(assignErrorMessage(e));
 }
 advanceQueue();
 }
 },
 [
 verifiedRatePrompt,
 verifiedQueue,
 verifiedBulkTotal,
 jobId,
 queryClient,
 refreshBoardAfterMove,
 syncKanbanCache,
 showError,
 ]
 );
 const submitVerifiedMoveRef = useRef<typeof submitVerifiedMove | null>(null);
 submitVerifiedMoveRef.current = submitVerifiedMove;

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
 if (!prev.has(item.candidate_id)) return prev;
 const n = new Set(prev);
 n.delete(item.candidate_id);
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

 // Cztery handlery poniżej MUSZĄ mieć stabilne referencje. `KanbanColumnV2`
 // (:582) i `CandidateKanbanCard` (:343) są opakowane w `memo()` z domyślnym
 // płytkim porównaniem propsów — świeżo alokowana strzałka przy każdym
 // renderze tablicy przebija obie granice, więc tiknięcie jednego checkboxa
 // re-renderowało wszystkie karty (z ich SVG-owymi ScoreRingami) w każdej
 // kolumnie. Setterzy `useState` są stabilni, stąd puste tablice zależności.
 const toggleSelect = useCallback((id: number) => {
 setSelected((p) => {
 const n = new Set(p);
 if (n.has(id)) n.delete(id);
 else n.add(id);
 return n;
 });
 }, []);

 const handleOpenScreening = useCallback((stageId: number, name: string) => {
 setScreeningPrompt({ stageId, candidateName: name });
 }, []);

 const handleOpenScorecard = useCallback(
 (item: KanbanItem, col: KanbanColumn) => {
 if (!col.stage_def_id) return;
 setScorecardPrompt({
 candidateStageId: item.id,
 stageId: item.id,
 stageDefId: col.stage_def_id,
 stageName: col.name ?? col.stage,
 });
 },
 []
 );

 const handleRemoveFromRecruitment = useCallback((item: KanbanItem) => {
 setPendingRemoval(item);
 }, []);

 // ── Krok 04 Pipeline (flow C2, PR 3/7): dok „Karta w procesie" ─────────
 //
 // `dockItem` szuka po `candidate_id`, nie po `id` (patrz komentarz przy
 // `dockCandidateId`). Jedno przejście po `cols` starcza na trójkę: samą
 // kartę, id kolumny w której dziś stoi (do wykluczenia z pigułek ruchu i
 // do `requestMove`) i etykietę tej kolumny (do nagłówka „Etap ·" w doku).
 const { dockItem, dockItemColId, dockItemColLabel } = useMemo((): {
 dockItem: KanbanItem | null;
 dockItemColId: string | null;
 dockItemColLabel: string | null;
 } => {
 if (dockCandidateId != null) {
 for (const c of cols) {
 const found = c.items.find((i) => i.candidate_id === dockCandidateId);
 if (found) {
 return { dockItem: found, dockItemColId: colId(c), dockItemColLabel: columnLabel(c) };
 }
 }
 }
 return { dockItem: null, dockItemColId: null, dockItemColLabel: null };
 }, [cols, dockCandidateId]);

 // Kolumna terminala „Odrzucony" tego szablonu — potrzebna zarówno „Odrzuć
 // z powodem" w doku, jak i sprawdzeniu, czy dana karta w ogóle DA się
 // jeszcze odrzucić (kandydat już `hired`/`rejected`/`withdrawn` — nie ma
 // po co proponować ponowne odrzucenie).
 const rejectedTemplateCol = useMemo(
 () => stageCols.find((c) => terminalOf(c) === "rejected"),
 [stageCols]
 );
 const dockItemColumn = dockItemColId
 ? (cols.find((c) => colId(c) === dockItemColId) ?? null)
 : null;
 const dockItemTerminal = dockItemColumn ? terminalOf(dockItemColumn) : null;
 const canRejectDockItem = Boolean(rejectedTemplateCol) && dockItemTerminal == null;

 // Pigułki „Przenieś na etap": wszystkie kolumny szablonu poza tą, na której
 // kandydat dziś stoi. Bramka — JEDNA funkcja `moveBlockedReason`, wspólna
 // z warsztatami 05–07. Od 17.09.2026 blokuje wyłącznie brak prawa zapisu:
 // weto HM, czarna lista, NDA i konkurent są ostrzeżeniem serwera, które
 // tablica zamienia na okno „Przenieś mimo to".
 const dockMoveTargets = useMemo<PipelineMoveTarget[]>(() => {
 if (!dockItem || !dockItemColId) return [];
 return stageCols
 .filter((c) => colId(c) !== dockItemColId)
 .map((c) => {
 const terminal = terminalOf(c);
 const blockedReason = moveBlockedReason({
 item: dockItem,
 readOnly,
 terminal: terminal === "rejected" || terminal === "withdrawn",
 targetStage: c.stage,
 });
 return { col: c, blockedReason };
 });
 }, [dockItem, dockItemColId, stageCols, readOnly]);
 // „Odrzuć z powodem" w doku — ta sama bramka (tylko `readOnly`).
 const dockRejectBlockedReason = useMemo(
 () =>
 dockItem
 ? moveBlockedReason({
 item: dockItem,
 readOnly,
 terminal: true,
 targetStage: rejectedTemplateCol?.stage ?? null,
 })
 : null,
 [dockItem, readOnly, rejectedTemplateCol]
 );

 // Główna akcja doku: PIERWSZY etap nieterminalny PO bieżącym w kolejności
 // szablonu (weto HM nie zatrzymuje — serwer ostrzega przy ruchu). Reguła
 // mieszka w `primaryForwardMove`
 // (`lib/pipeline-flow.ts`), obok jedynej bramki ruchu `moveBlockedReason`.
 const dockPrimaryMove = useMemo<PrimaryForwardMove | null>(() => {
 if (!dockItem || !dockItemColId) return null;
 return primaryForwardMove({
 item: dockItem,
 columns: stageCols,
 currentColId: dockItemColId,
 readOnly,
 });
 }, [dockItem, dockItemColId, stageCols, readOnly]);

 // Wiersz „następna akcja" doku — TA SAMA funkcja, którą renderuje karta na
 // tablicy; osobna kopia rozjechałaby się przy pierwszej zmianie progu.
 const dockNextAction = useMemo<NextAction | null>(() => {
 if (!dockItem || !dockItemColumn) return null;
 return nextActionFor(dockItem, dockItemColumn, {
 slaDays,
 group: dockItemColId ? groupByColId.get(dockItemColId) : undefined,
 });
 }, [dockItem, dockItemColumn, dockItemColId, groupByColId, slaDays]);

 const handleDockMove = useCallback(
 (dst: KanbanColumn) => {
 if (!dockItem || !dockItemColId) return;
 requestMove(dockItem, dockItemColId, dst);
 },
 [dockItem, dockItemColId, requestMove]
 );

 // Nawigator doku „‹ N z M ›" — kolejność TABLICY (kolumna po kolumnie),
 // łącznie z kubełkiem „Poza szablonem": to nadal karty w procesie, a dok
 // musi umieć na nie wejść. Klucz to `candidate_id` (stabilny przez ruchy),
 // dokładnie jak `dockCandidateId`.
 const dockOrder = useMemo(
 () => cols.flatMap((c) => c.items.map((i) => i.candidate_id)),
 [cols]
 );
 const dockIndex = dockItem ? dockOrder.indexOf(dockItem.candidate_id) : -1;
 const selectAdjacentDockCard = useCallback(
 (delta: -1 | 1) => {
 if (dockOrder.length === 0) return;
 const current = dockIndex;
 if (current < 0) return;
 const next = current + delta;
 if (next < 0 || next >= dockOrder.length) return;
 setDockCandidateId(dockOrder[next]);
 },
 [dockOrder, dockIndex]
 );

 const handleDockReject = useCallback(() => {
 if (!dockItem || !dockItemColId || !rejectedTemplateCol) return;
 setPendingRejection({
 entries: [{ item: dockItem, srcColId: dockItemColId }],
 destCol: rejectedTemplateCol,
 terminalType: "rejected",
 });
 }, [dockItem, dockItemColId, rejectedTemplateCol]);

 // Filtry lewej kolumny — liczone raz nad WSZYSTKIMI kartami (łącznie z
 // kubełkiem „Poza szablonem": to nadal realni kandydaci w procesie).
 const allItems = useMemo(() => cols.flatMap((c) => c.items), [cols]);
 // „Utknęli > 7 d" BEZ kolumn terminalnych (B-B05): odrzucony czy zatrudniony
 // „stoi" na swoim etapie bezterminowo i nie jest sprawą do załatwienia.
 // Ta sama reguła co `countStalled` w KPI jobbara tuż nad tablicą — do
 // 09.2026 filtr liczył wszystkie karty i pokazywał 80 obok KPI „26" pod
 // tą samą etykietą.
 const stuckIds = useMemo(() => {
 const ids = new Set<number>();
 for (const col of cols) {
 if (col.category === "terminal") continue;
 for (const item of col.items) {
 if ((item.days_in_stage ?? 0) > 7) ids.add(item.id);
 }
 }
 return ids;
 }, [cols]);
 const stuckCount = stuckIds.size;
 // Karty bez podpowiedzi „co dalej" — liczone tą samą funkcją, którą karta
 // renderuje, więc licznik w rail'u nie może rozjechać się z tablicą.
 const noActionIds = useMemo(() => {
 const ids = new Set<number>();
 for (const col of cols) {
 const group = groupByColId.get(colId(col));
 for (const item of col.items) {
 if (hasNoNextAction(nextActionFor(item, col, { slaDays, group }))) {
 ids.add(item.id);
 }
 }
 }
 return ids;
 }, [cols, groupByColId, slaDays]);
 // „Ostrzeżenia" = weto hiring managera. Od 17.09.2026 nic nie BLOKUJE ruchu
 // (karta „Oczekuje" nie powstaje), więc filtr pokazuje karty z ostrzeżeniem.
 const blockedCount = useMemo(
 () => allItems.filter((i) => Boolean(i.hm_veto)).length,
 [allItems]
 );
 const recruiterNames = useMemo(() => {
 const names = new Set<string>();
 for (const i of allItems) {
 const n = i.added_to_job_by_name?.trim();
 if (n) names.add(n);
 }
 return Array.from(names).sort((a, b) => a.localeCompare(b, "pl"));
 }, [allItems]);

 // Stabilna referencja — patrz komentarz nad `toggleSelect` (memo na
 // kolumnach/kartach). Zmienia tożsamość WYŁĄCZNIE gdy zmieni się któryś
 // z trzech filtrów, nigdy przy niepowiązanym re-renderze (np. checkbox).
 const isDimmed = useCallback(
 (item: KanbanItem) => {
 if (stuckFilter && !stuckIds.has(item.id)) return true;
 if (blockedFilter && !item.hm_veto) return true;
 if (noActionFilter && !noActionIds.has(item.id)) return true;
 if (recruiterFilter && item.added_to_job_by_name !== recruiterFilter) {
 return true;
 }
 return false;
 },
 [stuckFilter, stuckIds, blockedFilter, noActionFilter, noActionIds, recruiterFilter]
 );

 // „Ukryj puste kolumny" usuwa CAŁE kolumny bez kandydatów z renderu — to
 // jest bezpieczne dla `@hello-pangea/dnd` (w odróżnieniu od filtrowania
 // ITEMÓW wewnątrz kolumny, patrz `isDimmed`): pusta kolumna nie ma żadnych
 // indeksów do zepsucia, a `onDragEnd`/`bulkMove`/`stageCols` i tak liczą po
 // PEŁNYM `cols`, więc ukrycie jej z widoku nie rusza celów ruchu.
 const visibleCols = useMemo(
 () => (hideEmptyColumns ? cols.filter((c) => c.count > 0) : cols),
 [cols, hideEmptyColumns]
 );

 // Grupy zwinięte w jedną kolumnę-zastępnik: WYŁĄCZNIE etapy u klienta i etapy
 // umowy, wyłącznie gdy KAŻDA kolumna grupy jest pusta i gdy jest ich więcej
 // niż jedna (zwinięcie jednej kolumny w jeden zastępnik to sama zmiana nazwy).
 // Grupa, w której ktokolwiek stoi, rozwija się z powrotem sama.
 const collapsedGroupKeys = useMemo(() => {
 const keys = new Set<PipelineGroupKey>();
 for (const group of stageGroups) {
 if (group.key !== "client" && group.key !== "contract") continue;
 if (expandedGroups.has(group.key)) continue;
 if (group.columns.length < 2) continue;
 if (group.columns.every((c) => c.count === 0)) keys.add(group.key);
 }
 return keys;
 }, [stageGroups, expandedGroups]);

 // Lista renderu tablicy: prawdziwe kolumny (jedyne cele `Droppable`) i
 // zastępniki zwiniętych grup. Zastępnik wchodzi w miejsce PIERWSZEJ kolumny
 // swojej grupy, więc kolejność etapów zostaje nienaruszona.
 const boardEntries = useMemo(() => {
 const entries: Array<
 | { kind: "column"; key: string; col: KanbanColumn }
 | { kind: "collapsed"; key: string; group: PipelineColumnGroup }
 > = [];
 const emitted = new Set<PipelineGroupKey>();
 for (const col of visibleCols) {
 const groupKey = groupByColId.get(colId(col));
 if (groupKey && collapsedGroupKeys.has(groupKey)) {
 if (emitted.has(groupKey)) continue;
 emitted.add(groupKey);
 const group = stageGroups.find((g) => g.key === groupKey);
 if (group) {
 entries.push({ kind: "collapsed", key: `group:${groupKey}`, group });
 continue;
 }
 }
 entries.push({ kind: "column", key: colId(col), col });
 }
 return entries;
 }, [visibleCols, groupByColId, collapsedGroupKeys, stageGroups]);

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
 // Zapytanie strony odświeżamy PO zapisie stawki — inaczej kolejki kroków
 // dostałyby „CV Wysłane" bez stawki, którą zaraz zapiszemy.
 const ok = await sendMove(item, destCol, undefined, {
 silent: isBulk,
 deferCacheSync: true,
 checkVersion: !isBulk,
 });
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
 // `sendMove` w trybie zbiorczym jest cichy — bez tego toastu karta
 // wracała na miejsce bez słowa wyjaśnienia.
 const failedName =
 `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
 showError(`${failedName}: nie udało się przenieść na „CV Wysłane”.`);
 await refreshBoardAfterMove();
 }
 if (ok) syncKanbanCache();

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
 syncKanbanCache,
 showSuccess,
 showError,
 ]
 );

 const bulkMove = async (destColId: string) => {
 const dst = stageCols.find((c) => colId(c) === destColId);
 if (!dst || selected.size === 0) return;
 // Zaznaczone karty wraz z kolumną źródłową; karty już w celu pomijamy.
 const entries: { item: KanbanItem; srcColId: string }[] = [];
 const skippedEntries: { name: string; reason: string }[] = [];
 const dstTerminal = terminalOf(dst);
 for (const cid of Array.from(selected)) {
 const src = cols.find((c) => c.items.some((i) => i.candidate_id === cid));
 if (!src || colId(src) === colId(dst)) continue;
 const item = src.items.find((i) => i.candidate_id === cid)!;
 // Ruch zbiorczy nie ma okna „Przenieś mimo to" (serwer odrzuca paczkę
 // z ostrzeżeniem), więc karty z ostrzeżeniem widocznym na karcie (weto HM
 // na etapie klienta) POMIJAMY z wyjaśnieniem — nie liczymy ich jako
 // nieudanych. Taką kartę przenosi się pojedynczo, z potwierdzeniem.
 const reason = bulkMoveSkipReason({
 item,
 readOnly,
 terminal: dstTerminal === "rejected" || dstTerminal === "withdrawn",
 targetStage: dst.stage,
 });
 if (reason) {
 skippedEntries.push({ name: itemFullName(item), reason });
 continue;
 }
 entries.push({ item, srcColId: colId(src) });
 }
 if (skippedEntries.length > 0) {
 showError(
 `Pominięto ${skippedEntries.length}: ` +
 skippedEntries.map((b) => `${b.name} — ${b.reason}`).join("; ")
 );
 }
 if (entries.length === 0) {
 setSelected(new Set());
 return;
 }

 // „Zweryfikowany" pyta o stawkę per kandydat (opcjonalnie — „Pomiń stawkę")
 // → kolejka okien, jedno po drugim.
 if (dst.stage === "verified") {
 if (!canEditRates) {
 showError(RATE_EDIT_DENIED_MESSAGE);
 return;
 }
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
 if (dst.stage === "cv_sent" && canWriteClientRate) {
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
 const ok = await sendMove(item, dst, undefined, {
 silent: true,
 deferCacheSync: true,
 checkVersion: false,
 });
 if (!ok) failures += 1;
 }
 if (failures > 0) {
 showError(
 `Nie udało się przenieść ${failures} z ${entries.length} kandydatów.`
 );
 // `refreshBoardAfterMove` odświeża też zapytanie strony.
 await refreshBoardAfterMove();
 } else {
 syncKanbanCache();
 if (entries.length > 1) {
 showSuccess(`Przeniesiono ${entries.length} kandydatów.`);
 }
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
 .filter((i) => selected.has(i.candidate_id))
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

 // Progi liczone z kolumn SZABLONU — kubełek nie może przestawić układu
 // desktopowego na 1 009 rekrutacjach z sierotami.
 // 16, nie 15: domyślny szablon „Default B2B" ma 15 kolumn + „Ogłoszenia"
 // (migracja 0317) — bez podniesienia progu każda rekrutacja wpadałaby w tryb
 // przewijania.
 const fullPipelineDesktop = stageCols.length > 0 && stageCols.length <= 16;
 // Próg zwężenia karty liczy się z liczby RENDEROWANYCH kolumn, nie z liczby
 // etapów szablonu: po zwinięciu pustych grup „Default B2B" pokazuje dziesięć
 // kolumn zamiast szesnastu, więc na kolumnę wypada ~140 px — tyle, ile
 // makieta przewiduje dla pełnej karty (nazwisko do dwóch linii, właściciel,
 // wiek, następna akcja). Powyżej karta znowu musi degradować się do kafelka.
 //
 // Dziesięć, nie dziewięć: to jest DOKŁADNIE tyle, ile zostaje z „Default B2B"
 // po zwinięciu grup „U klienta" i „Umowa → zatrudnieni" — osiem prawdziwych
 // kolumn (16 − 4 − 4, w tym „Ogłoszenia" z migracji 0317) plus dwa
 // zastępniki. Próg o jeden niżej zostawiałby najczęstszy szablon w produkcie
 // po gorszej stronie granicy, czyli cała ta karta nigdy nie pokazałaby się
 // nikomu (a przy wąskiej planszy kafelki o zerowej szerokości chowały karty).
 const OVERVIEW_COLUMN_THRESHOLD = 10;
 const desktopOverview =
 fullPipelineDesktop && boardEntries.length > OVERVIEW_COLUMN_THRESHOLD;

 return (
 <div className="relative space-y-3">
 {/* Krok 04 Pipeline (flow C2, PR 3/7): ten sam grid co warsztat C2
 (`AIMatchingSection`/`JobMatchDock`) — lewa kolumna filtrów, środek,
 dok. Poniżej `xl` dok spływa pod tablicę, nie obok niej. */}
 <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
 <PipelineFiltersRail
 stageCols={stageCols}
 groups={stageGroups}
 templateName={templateName}
 focusedColId={focusedColId}
 onFocusColumn={focusColumn}
 offTemplateCount={offTemplate?.count ?? 0}
 onFocusOffTemplate={() => focusColumn(`stage:${OFF_TEMPLATE_STAGE}`)}
 stuckFilter={stuckFilter}
 onToggleStuckFilter={() => setStuckFilter((v) => !v)}
 stuckCount={stuckCount}
 noActionFilter={noActionFilter}
 onToggleNoActionFilter={() => setNoActionFilter((v) => !v)}
 noActionCount={noActionIds.size}
 blockedFilter={blockedFilter}
 onToggleBlockedFilter={() => setBlockedFilter((v) => !v)}
 blockedCount={blockedCount}
 recruiters={recruiterNames}
 recruiterFilter={recruiterFilter}
 onSetRecruiterFilter={setRecruiterFilter}
 hideEmptyColumns={hideEmptyColumns}
 onToggleHideEmptyColumns={() => setHideEmptyColumns(!hideEmptyColumns)}
 slaDays={slaDays}
 slaClientName={playbookQuery.data?.client_name ?? null}
 slaLoading={playbookQuery.isLoading}
 />

 <div className="min-w-0 space-y-3">
 {offTemplate && offTemplate.count > 0 && (
 <Alert
 variant="warning"
 title={`${offTemplate.count} ${
 offTemplate.count === 1 ? "kandydat stoi" : "kandydatów stoi"
 } na etapie spoza szablonu tej rekrutacji`}
 description={
 <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
 <span>
 Etapy bez kolumny:{" "}
 <strong>{offTemplate.missing_stage_labels.join(", ")}</strong>.
 Karty są w kolumnie „{offTemplate.name}" na końcu tablicy — przenieś
 je dalej albo uzupełnij szablon.
 </span>
 <button
 type="button"
 className="underline underline-offset-2 font-medium"
 onClick={() => focusColumn(`stage:${OFF_TEMPLATE_STAGE}`)}
 >
 Pokaż
 </button>
 <Link
 href="/settings/pipeline-templates"
 className="underline underline-offset-2 font-medium"
 >
 Otwórz szablony
 </Link>
 </span>
 }
 />
 )}

 {stageCols.length > 0 && (
 <StageFocusNavigator
 cols={stageCols}
 focusedId={focusedColId}
 onFocus={focusColumn}
 density={density}
 onToggleDensity={() =>
 setDensity(density === "cozy" ? "compact" : "cozy")
 }
 fullPipelineDesktop={fullPipelineDesktop}
 />
 )}

 {/* Bulk action bar */}
 {selected.size > 0 && (
 <Card className="p-3! flex items-center gap-2 flex-wrap bg-card text-foreground border-white/10">
 <Flag className="h-4 w-4" />
 <span className="text-sm">
 Zaznaczono <strong className="font-semibold">{selected.size}</strong>
 </span>
 {!readOnly && <div className="inline-flex items-center gap-1.5 text-xs ml-1">
 <MoveRight className="h-3.5 w-3.5" />
 <Select onValueChange={bulkMove}>
 <SelectTrigger className="h-8 w-[200px] bg-card/10 text-foreground border-white/20">
 <SelectValue placeholder="Przenieś na etap…" />
 </SelectTrigger>
 <SelectContent>
 {stageCols.map((c) => (
 <SelectItem key={colId(c)} value={colId(c)}>
 {columnLabel(c)}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 </div>}
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
 CV (ZIP)
 </Button>
 {/* Skrót do tej samej ścieżki, co wybór „Odrzucony" z listy wyżej —
 `bulkMove` otwiera wspólny modal powodu (`RejectionV2`). Żadnej nowej
 mutacji: bez kolumny terminalnej „Odrzucony" w szablonie przycisku
 po prostu nie ma. */}
 {!readOnly && rejectedTemplateCol && (
 <Button
 size="sm"
 variant="ghost"
 onClick={() => bulkMove(colId(rejectedTemplateCol))}
 disabled={bulkBusy || bulkDownloadBusy}
 className="text-destructive hover:bg-destructive/10 hover:text-destructive"
 >
 <XCircle className="h-3.5 w-3.5" />
 Odrzuć
 </Button>
 )}
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
 data-testid="pipeline-board"
 data-desktop-layout={fullPipelineDesktop ?"full-pipeline" :"scroll"}
 className={cn(
 // Board = JEDYNY scroll-kontener (oba kierunki). Po usunięciu overflow-y
 // z kolumn to on jest „closestScrollable" każdej kolumny → @hello-pangea/dnd
 // śledzi jego scroll i auto-scrolluje go natywnie (drop trafia pod kursor,
 // skrajne kolumny osiągalne — bez ręcznego rAF). Definite height wypełnia
 // viewport; calc fallback działa do pierwszego pomiaru (SSR/pierwszy render).
 "flex gap-3 overflow-auto pb-4 min-h-[280px]",
 fullPipelineDesktop &&"xl:pointer-fine:gap-1",
 columnHeight == null && "h-[calc(100vh-240px)]"
 )}
 style={columnHeight != null ? { height: columnHeight } : undefined}
 >
 {boardEntries.length === 0 ? (
 <div className="w-full py-12 text-center text-sm text-muted-foreground">
 <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-40" />
 {cols.length === 0 ? (
 "Brak kolumn w tej kategorii."
 ) : (
 <>
 Wszystkie kolumny są dziś puste.{" "}
 <button
 type="button"
 className="underline underline-offset-2 font-medium"
 onClick={() => setHideEmptyColumns(false)}
 >
 Pokaż puste kolumny
 </button>
 </>
 )}
 </div>
 ) : (
 boardEntries.map((entry) =>
 entry.kind === "collapsed" ? (
 <CollapsedGroupColumn
 key={entry.key}
 group={entry.group}
 fullPipelineDesktop={fullPipelineDesktop}
 desktopOverview={desktopOverview}
 readOnly={readOnly}
 onExpand={() => expandGroup(entry.group.key)}
 />
 ) : (
 <KanbanColumnV2
 key={entry.key}
 col={entry.col}
 jobId={jobId}
 selectedIds={selected}
 onToggleSelect={toggleSelect}
 onOpenScreening={handleOpenScreening}
 density={density}
 scoreMap={scoreMap}
 scoresLoading={scoresLoading}
 stagesWithScorecard={stagesWithScorecard}
 onOpenScorecard={handleOpenScorecard}
 jobBudgetHourly={jobBudgetHourlyValue}
 onRemoveFromRecruitment={handleRemoveFromRecruitment}
 contactFeatureEnabled={contactFeature.enabled}
 desktopOverview={desktopOverview}
 fullPipelineDesktop={fullPipelineDesktop}
 readOnly={readOnly}
 dropDisabled={isOffTemplate(entry.col)}
 onOpenDock={openDock}
 isDimmed={isDimmed}
 group={groupByColId.get(entry.key)}
 slaDays={slaDays}
 />
 )
 )
 )}
 </div>
 </DragDropContext>
 </div>

 <aside className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:self-start">
 {dockItem && dockItemColLabel !== null ? (
 <PipelineCandidateDock
 key={dockItem.candidate_id}
 item={dockItem}
 jobId={jobId}
 currentStageLabel={dockItemColLabel}
 jobTitle={jobTitle}
 matchScore={scoreMap?.get(dockItem.candidate_id)}
 scoresLoading={scoresLoading}
 moveTargets={dockMoveTargets}
 readOnly={readOnly}
 contactFeatureEnabled={contactFeature.enabled}
 canReject={canRejectDockItem}
 rejectBlockedReason={dockRejectBlockedReason}
 budgetHourly={jobBudgetHourlyValue}
 position={dockIndex >= 0 ? dockIndex + 1 : null}
 total={dockOrder.length}
 onSelectPrevious={() => selectAdjacentDockCard(-1)}
 onSelectNext={() => selectAdjacentDockCard(1)}
 nextAction={dockNextAction}
 primaryTarget={dockPrimaryMove?.target ?? null}
 primaryBlocked={dockPrimaryMove?.blocked ?? null}
 onClose={closeDock}
 onMoveTo={handleDockMove}
 onOpenScreening={handleOpenScreening}
 onReject={handleDockReject}
 />
 ) : (
 <PipelineCandidateDockEmpty />
 )}
 </aside>
 </div>

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
 {
 silent: entries.length > 1,
 deferCacheSync: entries.length > 1,
 checkVersion: entries.length === 1,
 }
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
 syncKanbanCache();
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

 {/* „Zweryfikowany" — stawka opcjonalna, podpowiedź z profilu kandydata */}
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
 jobBudgetHourly={jobBudgetHourlyValue}
 initialRateHourly={verifiedRatePrompt.item.candidate_expected_rate_hourly ?? null}
 onConfirm={(payload) => void submitVerifiedMove(payload)}
 onSkip={() => void submitVerifiedMove(null)}
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
 trafi na etap „Zatrudniony”. System spróbuje założyć szkic kontraktu
 i zamówienia; jeśli się nie uda, zatrudnienie i tak zostanie zapisane,
 a Delivery dostanie powiadomienie z powodem.
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

 {/* 409 ELIGIBILITY_WARNING (17.09.2026) — jedno pytanie, potem ten sam ruch
 z potwierdzeniem. Czarna lista / NDA / konkurent / weto HM nie blokują. */}
 {eligibilityWarning && (
 <Dialog
 open={true}
 onOpenChange={(v: boolean) => {
 if (!v) void dismissEligibilityWarning();
 }}
 >
 <DialogContent>
 <DialogHeader>
 <DialogTitle>Ostrzeżenie przed przeniesieniem</DialogTitle>
 <DialogDescription>{eligibilityWarning.reason}</DialogDescription>
 </DialogHeader>
 <DialogBody>
 <p className="text-sm text-muted-foreground">
 Ruch jest możliwy — zapiszemy w historii, kto go potwierdził.
 </p>
 </DialogBody>
 <DialogFooter>
 <Button variant="ghost" onClick={() => void dismissEligibilityWarning()}>
 Anuluj
 </Button>
 <Button onClick={() => void eligibilityWarning.retry()}>
 Przenieś mimo to
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
