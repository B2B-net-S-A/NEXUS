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
 ArrowRight,
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
import {
 api,
 candidatesApi,
 pipelineApi,
} from"@/lib/api";
import { candidatePipelinesQueryKey } from"@/components/CandidatePipelinesWidget";
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
import { encodeJobBackRef } from"@/lib/url-filters";
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
import { ScorecardV2 } from"@/components/v2/modals/ScorecardV2";
import { ScreeningSheet } from"@/components/v2/modals/ScreeningSheet";
import { useToast } from"@/components/Toast";
import { BoardReviewSection } from "@/components/v2/jobs/BoardReviewSection";
import { SlotRequestDialog } from "@/components/calendar/cycle/SlotDialogs";
import { DlReviewPanel } from "@/components/v2/recruitment/DlReviewPanel";
import { CvQcDialog } from "@/components/v2/recruitment/CvQcDialog";
import { MoveNextDialog } from "@/components/v2/recruitment/MoveNextDialog";
import { dockNavigationOrder } from "@/lib/board-dock-order";
import { DebriefRequiredDialog } from "@/components/v2/recruitment/DebriefRequiredDialog";
import {
 MOVE_REQUIREMENTS_PREFIX,
 type MoveRequirementAction,
} from "@/lib/api/moveRequirements";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
import type { PairInfo } from "@/lib/interview-cycle";
import {
 SETTABLE_BADGES,
 STAGE_BADGE_LABEL,
 STAGE_BADGE_TITLE,
 boardColumnStep,
 foldBoardColumns,
 impliedBadges,
 placeStage,
 type BoardColumnKey,
 type StageBadgeKey,
} from "@/lib/board-stages";
import { boardColumnPurpose } from "@/lib/board-column-purpose";
import { hasRole, useAuthStore } from "@/store/auth";
import {
 CARD_BADGE_TONE_CLASS,
 cardBadges,
 cardNextStep,
 claimAction,
 knownForwardGap,
 qcChip,
 type CardNextStep,
 type QcChipTone,
} from "@/lib/board-card-badges";
import { apiErrorMessage } from "@/lib/api-error";
import {
 BoardWorkbenchDrawer,
 type BoardWorkbenchContext,
} from "@/components/v2/recruitment/BoardWorkbenchDrawer";
import type { KanbanQueryState } from "@/components/v2/recruitment/PersonPanel";
import { buildProcessRows } from "@/components/v2/recruitment/person-rows";
import type { PersonPanelSection } from "@/components/v2/recruitment/types";
import { useBulkCvHandoff } from "@/components/v2/recruitment/useBulkCvHandoff";
import { terminalOf } from"@/lib/kanban-terminal";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import {
 usePipelineMove,
 type PipelineMoveConfirmedPatch,
} from "@/hooks/usePipelineMove";
import { PipelineFilterBar } from "@/components/v2/jobs/PipelineFiltersRail";
import {
 PipelineCandidateDock,
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
 CV_SENT_STAGE,
 findStageColumn,
 formatExpectedRate,
 groupKanbanColumns,
 moveBlockedReason,
 itemFullName,
 primaryForwardMove,
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
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { useJobPipelineTemplate } from "@/hooks/useJobPipelineTemplate";
import {
 kanbanViewToggleVisible,
 resolveKanbanViewMode,
 useKanbanViewPreference,
 type KanbanViewMode,
} from "@/lib/kanban-view-preferences";

// Re-eksport — `KanbanColumn`/`KanbanItem`/`colId`/`columnLabel`/`ScoreRing`
// mieszkają teraz w `kanban-shared.tsx` (dok i lewy rail importują je STAMTĄD,
// nie stąd, żeby uniknąć cyklu: KanbanBoardV2 → dok/rail → KanbanBoardV2).
// Re-eksport zostaje dla wstecznej zgodności — `KanbanColumn` było publicznym
// eksportem tego modułu przed PR3 programu „flow w języku C2".
export type { KanbanColumn, KanbanItem };
export { colId, columnLabel, ScoreRing };

// ── Types ─────────────────────────────────────────────────────────────

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
 /** Deep link `?candidate=<id>` (powiadomienia, „Wróć do rekrutacji"): po
  *  załadowaniu tablicy otwiera dok tej osoby i przewija do jej karty. */
 initialDockCandidateId?: number | null;
 /** Woła się raz po obsłużeniu `initialDockCandidateId` — niezależnie od tego,
  *  czy karta była na tablicy — żeby strona zdjęła parametr z adresu. */
 onInitialDockHandled?: () => void;
 /** Kto jest teraz w doku — strona trzyma go w adresie (`?candidate=`). */
 onDockCandidateChange?: (candidateId: number | null) => void;
 /**
 * Kontekst warsztatów osoby (dawna „Tabela": CV do klienta, rozmowy, umowa).
 * Bez niego dok nie pokazuje przycisków warsztatu, a pasek zaznaczenia —
 * zbiorczej wysyłki CV.
 */
 workbenchContext?: BoardWorkbenchContext;
 kanbanQueryState?: KanbanQueryState;
 /** Deep link `?candidate=&panel=` — otwiera warsztat tej osoby. */
 initialWorkbench?: { candidateId: number; section: PersonPanelSection } | null;
 onInitialWorkbenchHandled?: () => void;
 /** Nordea (`job.cpro_enabled`): „CV wysłane" = „Wysłane do Cpro", znacznik
  *  „W kolejce Cpro" w kolumnie „QC CV". */
 cproEnabled?: boolean;
 /** Panel „Dodaj kandydatów" (Rekrutacja v5) — otwiera go strona; bez tej
  *  funkcji kolumna „Nowi" pokazuje dawne karty propozycji. */
 onOpenAddCandidates?: (tab: "search" | "proposals") => void;
 /** „Ścieżka rekrutacji" w nagłówku: przewiń do kolumny Tablicy i podświetl
  *  ją na chwilę. `seq` rozróżnia kolejne kliknięcia tej samej kolumny. */
 focusColumnRequest?: { column: BoardColumnKey; seq: number } | null;
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
 fullPipelineDesktop,
}: {
 cols: KanbanColumn[];
 focusedId: string | null;
 onFocus: (id: string) => void;
 fullPipelineDesktop: boolean;
}) {
 const focusedIndex = Math.max(
 0,
 cols.findIndex((col) => colId(col) === focusedId)
 );
 const focused = cols[focusedIndex];

 if (!focused) return null;

 return (
 <div
 className={cn(
 "flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-2 py-1.5",
 // Na desktopie wszystkie kolumny są widoczne — wiersz niósłby tylko
 // przełączniki, które siedzą teraz w pasku filtrów (makieta 2).
 fullPipelineDesktop && "xl:pointer-fine:hidden"
 )}
 role="navigation"
 aria-label="Nawigacja etapów pipeline"
 >

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

 {/* Przełącznik widoku. Renderowany TYLKO gdy jest co przełączać
 (`kanbanViewToggleVisible`): poniżej progu kolumny i tak mieszczą się bez
 przewijania, więc „widok przeglądowy" dałby wyłącznie mniejsze karty. */}
 </div>
 );
});

/** Przełączniki widoku (kafelki/kolumny) i gęstości — w pasku filtrów Tablicy. */
function BoardViewControls({
 viewMode,
 onSetViewMode,
 density,
 onToggleDensity,
}: {
 viewMode: KanbanViewMode | null;
 onSetViewMode: (next: KanbanViewMode) => void;
 density: "cozy" | "compact";
 onToggleDensity: () => void;
}) {
 return (
 <>
 {viewMode !== null && (
 <div
 role="group"
 aria-label="Widok tablicy"
 className="inline-flex items-center gap-0.5 rounded-md border border-border p-0.5"
 >
 <Button
 type="button"
 size="sm"
 variant={viewMode === "tiles" ? "primary" : "ghost"}
 aria-pressed={viewMode === "tiles"}
 onClick={() => onSetViewMode("tiles")}
 className="h-6 px-2 text-[11px]"
 >
 Widok przeglądowy
 </Button>
 <Button
 type="button"
 size="sm"
 variant={viewMode === "columns" ? "primary" : "ghost"}
 aria-pressed={viewMode === "columns"}
 onClick={() => onSetViewMode("columns")}
 className="h-6 px-2 text-[11px]"
 >
 Widok kolumnowy
 </Button>
 </div>
 )}

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
 </>
 );
}

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
 "inline-flex h-5 min-w-5 items-center justify-center rounded-full border px-1 text-[10px] font-bold leading-none",
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
 step,
 hidden,
 advance,
}: {
 action: NextAction;
 /** „Kto ma ruch" + co zrobić (Rekrutacja v5) — `null` = sama etykieta akcji. */
 step?: CardNextStep | null;
 hidden?: boolean;
 /** Strzałka „→" na końcu wiersza. */
 advance?: React.ReactNode;
}) {
 if (action.kind === "none" && !step && !advance) return null;
 const Icon = action.tone === "normal" ? NEXT_ACTION_ICON[action.kind] : AlertTriangle;
 const label = step?.label ?? action.label;
 return (
 <div
 data-next-action={action.tone}
 className={cn(
 "mt-1.5 flex items-center gap-1.5 border-t border-dashed border-border pt-1 text-[10.5px] leading-tight",
 action.tone === "normal" ? "text-foreground/80" : "text-warning font-medium",
 hidden && "xl:pointer-fine:hidden"
 )}
 >
 {step ? (
  <span
   data-testid="card-next-who"
   className={cn(
    "shrink-0 rounded px-1 text-[9.5px] font-semibold",
    step.mine ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
   )}
  >
   {step.who}
  </span>
 ) : label ? (
  <Icon className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
 ) : null}
 {/* Dwie linie zamiast ucinania: „Twój ruch" / imię zabiera miejsce,
 a „Przygotuj C…" nie mówi, co zrobić. */}
 <span className="min-w-0 flex-1 line-clamp-2" title={label}>{label}</span>
 {advance}
 </div>
 );
}

/** Zwykły klik lewym przyciskiem — bez modyfikatorów „otwórz w nowej karcie". */
export function isPlainLeftClick(e: {
 button: number;
 metaKey: boolean;
 ctrlKey: boolean;
 shiftKey: boolean;
 altKey: boolean;
}): boolean {
 return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

/** Ton chipu QC — tokeny, jak odznaki karty. */
const QC_CHIP_TONE: Record<QcChipTone, string> = {
 ok: "bg-success/15 text-success",
 urgent: "bg-destructive/10 text-destructive",
 wait: "bg-warning/15 text-warning",
 neutral: "bg-muted text-muted-foreground",
};

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
 /** Tryb przeglądowy: karta degraduje się do kafelka (patrz
  *  `lib/kanban-view-preferences.ts`). */
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
 /** Odznaka z etapu szablonu złożonego w tę kolumnę (DZ, Cpro, prep, umowa…). */
 stageBadge?: StageBadgeKey | null;
}

const STAGE_BADGE_TONE: Record<StageBadgeKey, string> = {
 posting: "bg-muted text-muted-foreground",
 acceptance: "bg-info/15 text-info",
 cpro: "bg-info/15 text-info",
 prep: "bg-info/15 text-info",
 after_interview: "bg-muted text-muted-foreground",
 contract_sent: "bg-warning/15 text-warning",
 contract_signed: "bg-success/15 text-success",
 onboarding: "bg-info/15 text-info",
};

// ── Pasek zamkniętych (Pipeline v4) ─────────────────────────────────────────
// Odrzuceni dzielą się na trzy grupy po `ended_by`; wiersz bez tej informacji
// (sprzed 0352, import) liczy się jako „przez nas", jak w statystykach.
const CLOSED_BY_SEP = "::";
type ClosedRejectBy = "recruiter" | "delivery_lead" | "client";
// `short` stoi na chipie po „Zamknięci:" w pasku filtrów (24.09.2026),
// `label` — w nazwie dostępnej i dymku.
const CLOSED_REJECT_GROUPS: { by: ClosedRejectBy; label: string; short: string }[] = [
 { by: "recruiter", label: "Odrzucony przez nas", short: "przez nas" },
 { by: "delivery_lead", label: "Odrzucony przez DL", short: "przez DL" },
 { by: "client", label: "Odrzucony przez klienta", short: "przez klienta" },
];

function closedChips(closed: KanbanColumn[]) {
 return closed.flatMap((c) => {
 const terminal = terminalOf(c);
 if (terminal === "withdrawn") {
 return [{ col: c, droppableId: colId(c), label: "Zrezygnował", short: "zrezygnował", count: c.count }];
 }
 if (terminal === "rejected") {
 return CLOSED_REJECT_GROUPS.map(({ by, label, short }) => ({
 col: c,
 droppableId: `${colId(c)}${CLOSED_BY_SEP}${by}`,
 label,
 short,
 count: c.items.filter((i) => (i.ended_by ?? "recruiter") === by).length,
 }));
 }
 return [{ col: c, droppableId: colId(c), label: columnLabel(c), short: columnLabel(c), count: c.count }];
 });
}

/**
 * Pipeline v4 (23.09.2026): to, czego karta nie wie sama — w której kolumnie
 * Tablicy stoi, kto na nią patrzy, czy to Nordea — i akcja „Biorę/Przejmij".
 * Kontekst zamiast propów, bo `memo` karty i kolumny ma zostać tanie.
 */
interface BoardV4Ctx {
 columnByItemId: Map<number, BoardColumnKey | null>;
 cproEnabled: boolean;
 viewerId: number | null;
 readOnly: boolean;
 takingIds: ReadonlySet<number>;
 onTake: (item: KanbanItem) => void;
 /** Rekrutacja v5: następna kolumna Tablicy karty (`null` = brak strzałki). */
 nextColumnLabel: (item: KanbanItem) => string | null;
 /** Strzałka „→" — okno „Przesuń dalej". */
 onAdvance: (item: KanbanItem) => void;
 /** Chip QC — okno QC CV. */
 onOpenQc: (item: KanbanItem) => void;
}
const BoardV4Context = React.createContext<BoardV4Ctx | null>(null);

function CardV4Badges({
 item,
 fullName,
 stageBadge,
}: {
 item: KanbanItem;
 fullName: string;
 stageBadge: StageBadgeKey | null;
}) {
 const v4 = React.useContext(BoardV4Context);
 if (!v4) return null;
 const ctx = {
  column: v4.columnByItemId.get(item.id) ?? null,
  cproEnabled: v4.cproEnabled,
  viewerId: v4.viewerId,
  now: new Date(),
  stageBadge,
 };
 const badges = cardBadges(item, ctx);
 const action = v4.readOnly ? null : claimAction(item, ctx);
 if (badges.length === 0 && !action) return null;
 return (
  <>
   {badges.map((b) => (
    <span
     key={b.key}
     data-testid={`card-badge-${b.key}`}
     className={cn(
      "inline-flex max-w-full items-center truncate rounded px-1 text-[10px] font-semibold",
      CARD_BADGE_TONE_CLASS[b.tone]
     )}
     title={b.title}
    >
     {b.label}
    </span>
   ))}
   {action && (
    <button
     type="button"
     onClick={(e) => {
      e.stopPropagation();
      e.preventDefault();
      v4.onTake(item);
     }}
     disabled={v4.takingIds.has(item.id)}
     className="inline-flex items-center rounded border border-primary/40 px-1.5 text-[10px] font-semibold text-primary hover:bg-primary/10 disabled:opacity-50"
     aria-label={`${action === "takeover" ? "Przejmij" : "Biorę"} ${fullName} — na 12 h`}
    >
     {action === "takeover" ? "Przejmij" : "Biorę"}
    </button>
   )}
  </>
 );
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
 stageBadge = null,
}: CardProps) {
 const fullName = `${item.name ??""} ${item.lastname ??""}`.trim() ||"Kandydat";
 // Rekrutacja v5: kolumna Tablicy karty, „kto ma ruch", strzałka „→" i chip QC.
 const v5 = React.useContext(BoardV4Context);
 const boardKey = v5?.columnByItemId.get(item.id) ?? null;
 const nextStep = v5
 ? cardNextStep(nextAction, item, { column: boardKey, cproEnabled: v5.cproEnabled, stageBadge, viewerId: v5.viewerId })
 : null;
 const nextColumnLabel = v5 && !readOnly ? v5.nextColumnLabel(item) : null;
 const forwardGap = nextColumnLabel ? knownForwardGap(item, boardKey) : null;
 const qc = boardKey === "cv_qc" ? qcChip(item) : null;
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
 data-candidate-id={item.candidate_id}
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
 "relative h-6 w-6 border-0 bg-transparent pointer-coarse:after:absolute pointer-coarse:after:-inset-2 before:absolute before:inset-1 before:rounded-md before:border before:border-border before:bg-card before:transition-colors hover:border-transparent hover:before:border-primary",
 "data-[state=checked]:border-transparent data-[state=checked]:bg-transparent data-[state=checked]:before:border-primary data-[state=checked]:before:bg-primary",
 "data-[state=indeterminate]:border-transparent data-[state=indeterminate]:bg-transparent data-[state=indeterminate]:before:border-primary data-[state=indeterminate]:before:bg-primary"
 )}
 />
 </div>

 {/* Kropka ostrzeżenia — sygnał hm_veto widoczny także bez czytania
 tekstowego badge'a „Weto HM" niżej na karcie (patrz `dołóż flagę
 bramki jako kropkę` w brief programu C2, 04 Pipeline). */}
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
 w procesie" (`handleCardClick` na kontenerze). Od 24.09.2026 także
 zwykły klik w nazwisko otwiera dok (wcześniej wyrzucał na profil,
 czyli z rekrutacji); profil w nowej karcie daje Ctrl/⌘-klik na
 nazwisku i „Pełny profil" w doku. */}
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
 // Zwykły klik w nazwisko otwiera dok osoby — jak klik w kartę — i NIE
 // wyrzuca z rekrutacji (24.09.2026). Ctrl/⌘/Shift/środkowy przycisk
 // zostawiamy przeglądarce: profil w nowej karcie, prawdziwy `href` dla
 // czytników ekranu i „Kopiuj adres linku".
 onClick={(e) => {
 e.stopPropagation();
 if (isPlainLeftClick(e)) {
 e.preventDefault();
 onOpenDock(item);
 }
 }}
 // `break-words`, NIE `overflow-wrap:anywhere` — to drugie łamie nazwisko
 // w środku wyrazu przy ~176 px kolumny („Wojcie/ch Wyleżoł"), czyli robi
 // dokładnie to, czego ta karta miała się pozbyć.
 className={cn("block font-semibold text-foreground hover:underline break-words line-clamp-2",
 density === "compact" ?"text-[11px] leading-tight" :"text-[13px] leading-snug",
 desktopOverview &&"xl:pointer-fine:whitespace-normal xl:pointer-fine:break-words xl:pointer-fine:text-[10px] xl:pointer-fine:font-semibold xl:pointer-fine:leading-3",
 // W kafelku nazwisko zajmuje CAŁĄ kartę (39x87 px), więc link do profilu
 // przechwytywał każde kliknięcie i dok był nieosiągalny. `pointer-events-none`
 // przepuszcza klik do karty (dok), a link zostaje w drzewie dostępności
 // i pod Tabem — profil jest też w doku („Pełny profil").
 desktopOverview &&"xl:pointer-fine:pointer-events-none"
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
 desktopOverview && "xl:pointer-fine:justify-center xl:pointer-fine:gap-0 xl:pointer-fine:text-[10px] xl:pointer-fine:leading-none"
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
 "inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-semibold uppercase tracking-wide bg-destructive/10 text-destructive",
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
 "inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-semibold uppercase tracking-wide bg-warning/15 text-warning",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={`Stawka ${formatExpectedRate(item) ?? ""} przekracza budżet godzinowy rekrutacji. Ruch nie jest blokowany.`}
 >
 <AlertTriangle className="h-2.5 w-2.5" />
 ponad budżet
 </span>
 )}
 {impliedBadges(stageBadge).map((badge) => (
 <span
 key={badge}
 className={cn(
 "inline-flex items-center rounded px-1 text-[10px] font-semibold",
 STAGE_BADGE_TONE[badge],
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={STAGE_BADGE_TITLE[badge]}
 >
 {STAGE_BADGE_LABEL[badge]}
 </span>
 ))}
 {qc && v5 && (
 <button
 type="button"
 data-testid="card-qc-chip"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 v5.onOpenQc(item);
 }}
 className={cn(
 "inline-flex items-center rounded px-1 text-[9px] font-semibold hover:ring-1 hover:ring-current focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
 QC_CHIP_TONE[qc.tone],
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={qc.title}
 aria-label={`${qc.label} — otwórz QC CV dla ${fullName}`}
 >
 {qc.label}
 </button>
 )}
 <CardV4Badges item={item} fullName={fullName} stageBadge={stageBadge} />
 {/* `=== true`: odznaka obiecuje gotowy dokument (dawna odznaka
 kolumny „Następny krok" w Tabeli). */}
 {item.auto_cv_ready === true && (
 <span
 className={cn(
 "inline-flex items-center rounded px-1 text-[10px] font-semibold bg-info/15 text-info",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title="CV wygenerowane automatycznie po weryfikacji czeka w warsztacie CV — sprawdź je przed wysyłką."
 >
 CV gotowe w tle
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
 "inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-semibold bg-warning/15 text-warning hover:bg-warning hover:text-white transition-colors",
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

 {/* Wiersz 3 makiety: kto ma ruch, co zrobić i strzałka „→" (v5). */}
 <NextActionRow
 action={nextAction}
 step={nextStep}
 hidden={desktopOverview}
 advance={
 nextColumnLabel && v5 ? (
 <button
 type="button"
 data-testid="card-advance"
 data-gap={forwardGap ? "true" : "false"}
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 v5.onAdvance(item);
 }}
 aria-label={`Przesuń ${fullName} na następny etap`}
 title={
 forwardGap
 ? `${forwardGap} — kliknij, żeby zobaczyć, czego brakuje do „${nextColumnLabel}”`
 : `Dalej: ${nextColumnLabel}`
 }
 className={cn(
 "ml-auto inline-flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
 forwardGap
 ? "border-border bg-muted text-muted-foreground hover:text-foreground"
 : "border-primary/40 text-primary hover:bg-primary hover:text-primary-foreground"
 )}
 >
 <ArrowRight className="h-3 w-3" aria-hidden="true" />
 </button>
 ) : null
 }
 />

 {/* Usuń z rekrutacji — akcja korekcyjna („dodano nie tego kandydata").
 Hover-revealed, żeby nie zaśmiecać karty. */}
 {!readOnly && <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onRemoveFromRecruitment(item);
 }}
 className={cn("absolute right-1 z-10 inline-flex items-center justify-center rounded-md bg-card/80 text-muted-foreground transition-opacity pointer-fine:opacity-0","hover:bg-destructive/10 hover:text-destructive pointer-fine:group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-hidden",
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
 przykrywała „Wyślij CV do klienta" (#1604). */}
 {!readOnly && canScreen && (
 <div className={cn("mt-1 flex justify-end", desktopOverview &&"xl:pointer-fine:mt-0")}>
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 onOpenScreening(item.id, fullName);
 }}
 className={cn("inline-flex max-w-full items-center gap-1 text-[10px] px-1.5 py-0.5 pointer-coarse:min-h-8 pointer-coarse:px-2.5 rounded-full font-semibold hover:bg-primary hover:text-white transition-colors",
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
 fullPipelineDesktop: boolean;
 desktopOverview: boolean;
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
 /** Nagłówek kolumny zamiast nazwy etapu (kolumna „Do przejrzenia"). */
 titleOverride?: string;
 /** Treść nad kartami etapu — propozycje i przepięcia w „Do przejrzenia". */
 prepend?: React.ReactNode;
 /** Odznaki kart z etapów złożonych w tę kolumnę (klucz: id karty). */
 badgeByItemId?: ReadonlyMap<number, StageBadgeKey>;
 /** Dolicz do licznika w nagłówku (propozycje w „Do przejrzenia"). */
 extraCount?: number;
 /** Numer kroku procesu (1–8) w nagłówku kolumny Tablicy; `null` = bez numeru. */
 step?: number | null;
 /** „Co tu robisz" pod nazwą kolumny (`lib/board-column-purpose.ts`);
  *  `null` = własny etap szablonu — zostaje dawna linia SLA. */
 purpose?: string | null;
 /** Krótkie podświetlenie po skoku ze „Ścieżki rekrutacji". */
 highlighted?: boolean;
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
 desktopOverview,
 onRemoveFromRecruitment,
 contactFeatureEnabled,
 fullPipelineDesktop,
 readOnly,
 dropDisabled,
 onOpenDock,
 isDimmed,
 group,
 slaDays,
 titleOverride,
 prepend,
 badgeByItemId,
 extraCount = 0,
 step = null,
 purpose = null,
 highlighted = false,
}: ColProps) {
 const headerCount = col.count + extraCount;
 // Pusta kolumna jest WĄSKA (24.09.2026): przy 1440 px osiem kolumn mieści się
 // bez przewijania, gdy połowa jest pusta. Tylko na desktopie z myszą i poza
 // trybem kafelków (tam kolumny i tak dzielą szerokość); `droppableId`
 // i indeksy kart się nie zmieniają, więc upuszczanie działa jak dotąd.
 const narrow = headerCount === 0 && prepend == null;
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
 aria-label={`${titleOverride ?? columnLabel(col)}, liczba kandydatów: ${headerCount}`}
 className={cn(
 "flex w-[calc((100%-1.5rem)/3)] min-w-[17rem] shrink-0 snap-start flex-col rounded-lg border border-border bg-background/60 sm:min-w-[19rem]",
 prepend != null && "border-dashed border-primary/40",
 // NIE ściskamy kolumn do zera. Podłoga 12,5 rem (200 px) mieści pełną
 // kartę (nazwisko do dwóch linii, właściciel, wiek, następna akcja)
 // niezależnie od liczby kolumn. Board ma `overflow-auto`, więc nadmiar
 // kolumn przewija się w poziomie.
 // Kafelek: kolumny dzielą się dostępną szerokością i mieszczą się bez
 // przewijania. Kolumny: podłoga 12,5 rem (200 px), nadmiar przewija się
 // w poziomie — patrz `lib/kanban-view-preferences.ts`.
 fullPipelineDesktop && desktopOverview &&"xl:pointer-fine:w-0 xl:pointer-fine:min-w-0 xl:pointer-fine:basis-0 xl:pointer-fine:grow xl:pointer-fine:shrink",
 // Podłoga 11,5 rem (184 px) — przy 12,5 rem cztery kolumny z kartami
 // i cztery wąskie puste nie mieściły się w 1440 px z przypiętym paskiem.
 fullPipelineDesktop && !desktopOverview && !narrow &&"xl:pointer-fine:w-auto xl:pointer-fine:min-w-[11.5rem] xl:pointer-fine:basis-[11.5rem] xl:pointer-fine:grow",
 !desktopOverview && narrow &&"xl:pointer-fine:w-24 xl:pointer-fine:min-w-24 xl:pointer-fine:basis-24 xl:pointer-fine:grow-0",
 highlighted &&"ring-2 ring-primary"
 )}
 data-narrow={narrow && !desktopOverview ? "true" : undefined}
 >
 <div className={cn("sticky top-0 z-10 rounded-t-lg bg-background/95 backdrop-blur-xs border-b border-border flex items-center gap-2", density === "compact" ?"px-3 py-2" :"px-4 py-3", desktopOverview &&"xl:pointer-fine:min-h-14 xl:pointer-fine:flex-col xl:pointer-fine:items-stretch xl:pointer-fine:gap-1 xl:pointer-fine:px-1 xl:pointer-fine:py-1.5", !desktopOverview && narrow &&"xl:pointer-fine:flex-wrap xl:pointer-fine:gap-1 xl:pointer-fine:px-2")}>
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
 {step != null && (
 <span
 data-testid="column-step"
 className={cn(
 "inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 px-1 text-[10px] font-semibold tabular-nums text-primary",
 desktopOverview && "xl:pointer-fine:h-4 xl:pointer-fine:min-w-4 xl:pointer-fine:self-center xl:pointer-fine:text-[9px]"
 )}
 aria-label={`Krok ${step}`}
 >
 {step}
 </span>
 )}
 {/* Nazwa etapu zawija się na spacjach, a słowo dłuższe niż kolumna —
 w środku (dzielenie po polsku, `lang="pl"`). „Zweryfikowany" ucinało się
 do „Zweryfikowan" w wąskiej pustej kolumnie (96 px) i w pełnej przy 1440 px
 (audyt 24.09.2026). Pełna nazwa zostaje w `title`. */}
 <h3 className={cn("text-foreground flex-1 min-w-0 line-clamp-2 leading-tight hyphens-auto [overflow-wrap:break-word]", density === "compact" ?"text-sm font-medium" :"text-base font-semibold", desktopOverview &&"xl:pointer-fine:line-clamp-2 xl:pointer-fine:whitespace-normal xl:pointer-fine:text-center xl:pointer-fine:text-[10px] xl:pointer-fine:leading-tight xl:pointer-fine:[overflow-wrap:anywhere]", !desktopOverview && narrow &&"xl:pointer-fine:order-last xl:pointer-fine:basis-full xl:pointer-fine:text-xs xl:pointer-fine:font-medium xl:pointer-fine:line-clamp-3 xl:pointer-fine:hyphens-auto xl:pointer-fine:[overflow-wrap:anywhere]")} title={titleOverride ?? columnLabel(col)} lang="pl">
 {titleOverride ?? columnLabel(col)}
 </h3>
 <Badge size="sm" variant={headerCount > 0 ?"soft" :"outline"} className={cn(desktopOverview &&"xl:pointer-fine:h-4 xl:pointer-fine:min-w-4 xl:pointer-fine:self-center xl:pointer-fine:px-1 xl:pointer-fine:text-[10px]")}>
 {headerCount}
 </Badge>
 </div>

 {/* Druga linia nagłówka (24.09.2026): „co tu robisz" po lewej, SLA
 klienta / najstarsza karta po prawej. Własny etap szablonu (bez znanego
 znaczenia) zostaje przy dawnym „SLA: —" — cisza czytałaby się jak
 „zdążamy". Pełna informacja o SLA siedzi w `title`. */}
 <div
 data-column-sla={dropId}
 title={[slaHint.left, slaHint.right].filter(Boolean).join(" · ")}
 className={cn(
 "flex items-start justify-between gap-2 border-b border-border px-3 pb-1.5 pt-1 text-[10px] text-muted-foreground",
 !desktopOverview && narrow && "xl:pointer-fine:flex-wrap xl:pointer-fine:gap-0.5 xl:pointer-fine:px-2",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 >
 <span
 data-column-purpose={purpose ? "true" : undefined}
 className={cn(
 "min-w-0",
 // Wąska pusta kolumna (96 px) potrzebuje trzech linii na „Prep → rozmowa → telefon”.
 purpose ? cn(narrow ? "line-clamp-3" : "line-clamp-2", "font-medium leading-snug text-foreground/80") : "truncate",
 )}
 title={purpose ?? undefined}
 >
 {purpose ?? slaHint.left}
 </span>
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

 {prepend}
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
 stageBadge={badgeByItemId?.get(item.id) ?? null}
 />
 </div>
 )}
 </Draggable>
 ))}
 {headerCount === 0 && !snapshot.isDraggingOver && !readOnly && !noDrop && (
 <div
 aria-hidden="true"
 data-testid="column-drop-hint"
 className={cn(
 "rounded-md border border-dashed border-border px-1 py-6 text-center text-[10px] text-muted-foreground",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 >
 upuść tutaj
 </div>
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
// `p-4` obszaru treści powłoki (góra + dół) — patrz pomiar planszy na telefonie.
const MOBILE_MAIN_PADDING_Y = 32;

export function KanbanBoardV2({ columns, jobId, jobTitle, scoreMap, scoresLoading, headerCollapsed, offTemplate, readOnly = false, clientId = null, initialDockCandidateId = null, onInitialDockHandled, onDockCandidateChange, workbenchContext, kanbanQueryState, initialWorkbench = null, onInitialWorkbenchHandled, cproEnabled = false, onOpenAddCandidates, focusColumnRequest = null }: KanbanBoardV2Props) {
 const density = useUiStore((s) => s.density);
 const setDensity = useUiStore((s) => s.setDensity);
 // Krok 04 Pipeline (flow C2, PR 3/7): globalny przełącznik, jak `density` —
 // świadomie nie per-job.
 const hideEmptyColumns = useUiStore((s) => s.hideEmptyKanbanColumns);
 const setHideEmptyColumns = useUiStore((s) => s.setHideEmptyKanbanColumns);
 // Widok tablicy: kafelki ↔ kolumny. Reguła automatyczna (szeroki szablon
 // otwiera się kafelkowo) jest WARTOŚCIĄ DOMYŚLNĄ, wybór użytkownika ją
 // nadpisuje i jest pamiętany — patrz `lib/kanban-view-preferences.ts`.
 const [viewPreference, setViewPreference] = useKanbanViewPreference();
 const queryClient = useQueryClient();
 const contactFeature = useCandidateContactFeature();
 const { showSuccess, showError } = useToast();
 const [cols, setCols] = useState(() => composeColumns(columns, offTemplate));
 // Kolumny SZABLONU — wszystko, co wybiera cel ruchu albo mierzy pipeline,
 // musi iść po tej liście, nie po `cols` (w `cols` siedzi też kubełek).
 const stageCols = useMemo(() => cols.filter((c) => !isOffTemplate(c)), [cols]);
 // 8 kolumn Tablicy (Rekrutacja v5, `lib/board-stages.ts`): etapy szablonu
 // złożone w kolumny, to, co nie jest krokiem procesu, jako odznaka na karcie.
 // `cols`/`stageCols` zostają PRAWDZIWYMI etapami — z nich liczy się ruch,
 // liczniki i dok; złożenie dotyczy wyłącznie renderu i celów upuszczenia.
 const boardFold = useMemo(
 () => foldBoardColumns(stageCols, { cproEnabled }),
 [stageCols, cproEnabled]
 );
 const displayCols = useMemo(
 () =>
 boardFold.columns.map((f) => ({ ...f.host, items: f.items, count: f.count })),
 [boardFold]
 );
 const boardKeyByColId = useMemo(() => {
 const m = new Map<string, BoardColumnKey>();
 for (const f of boardFold.columns) if (f.key) m.set(colId(f.host), f.key);
 return m;
 }, [boardFold]);
 const boardLabelByColId = useMemo(() => {
 const m = new Map<string, string>();
 for (const f of boardFold.columns) m.set(colId(f.host), f.label);
 return m;
 }, [boardFold]);
 // Prawdziwy etap → gospodarz jego kolumny Tablicy (tam trafia ruch).
 const hostByColId = useMemo(() => {
 const m = new Map<string, KanbanColumn>();
 for (const f of boardFold.columns) for (const c of f.members) m.set(colId(c), f.host);
 for (const c of boardFold.closed) m.set(colId(c), c);
 return m;
 }, [boardFold]);
 // Cele ruchu z doku i paska zbiorczego: 8 gospodarzy + zamknięci.
 // Gospodarz niesie nazwę KOLUMNY Tablicy („Umowa", nie „Umowa wysłana").
 const moveTargetCols = useMemo(
 () => [
 ...boardFold.columns.map((f) => ({ ...f.host, name: f.label })),
 ...boardFold.closed,
 ],
 [boardFold]
 );
 // Odrzuceni / wycofani / rezerwa — pasek pod tablicą, rozwijany na kolumny.
 const [showClosed, setShowClosed] = useState(false);
 // Propozycje z bazy i przepięcia w „Do przejrzenia" — licznik kolumny liczy
 // je razem z kartami etapu „Ogłoszenia" (do 23.09 nagłówek mówił „0" nad
 // czternastoma propozycjami).
 const [reviewTotal, setReviewTotal] = useState<number | null>(null);
 const authUser = useAuthStore((st) => st.user);
 const isDlOrHor =
 hasRole(authUser, "admin") ||
 hasRole(authUser, "delivery_lead") ||
 hasRole(authUser, "head_of_recruitment");
 // Poza Nordeą CV do klienta wysyła DL albo admin (lustro
 // `pipeline_move_rules.CLIENT_SEND_ROLES`).
 const canReviewAsDl = hasRole(authUser, "admin") || hasRole(authUser, "delivery_lead");
 // Terminy od klienta dodaje DL (lustro bramki `interview_slots`: admin, HoR,
 // DL, TAC z członkostwem — serwer i tak sprawdza członkostwo).
 const canAddClientSlots =
 !readOnly &&
 (isDlOrHor || hasRole(authUser, "tac"));
 const [slotPair, setSlotPair] = useState<PairInfo | null>(null);
 // Pipeline v4: kolumna Tablicy każdej karty (odznaki) i „Biorę/Przejmij".
 const columnByItemId = useMemo(() => {
 const m = new Map<number, BoardColumnKey | null>();
 for (const f of boardFold.columns) for (const it of f.items) m.set(it.id, f.key);
 for (const c of boardFold.closed) for (const it of c.items) m.set(it.id, "closed");
 return m;
 }, [boardFold]);
 // Rekrutacja v5: następna kolumna Tablicy karty — cel strzałki „→".
 // Zatrudnieni, zamknięci i kubełek „Poza szablonem" strzałki nie mają.
 const nextFoldByItemId = useMemo(() => {
 const m = new Map<number, (typeof boardFold.columns)[number]>();
 boardFold.columns.forEach((f, index) => {
 const next = boardFold.columns[index + 1];
 if (!next || f.key === "hired") return;
 for (const it of f.items) m.set(it.id, next);
 });
 return m;
 }, [boardFold]);
 const foldIndexByColId = useMemo(() => {
 const m = new Map<string, number>();
 boardFold.columns.forEach((f, index) => {
 for (const c of f.members) m.set(colId(c), index);
 });
 return m;
 }, [boardFold]);
 const nextColumnLabel = useCallback(
 (item: KanbanItem) => nextFoldByItemId.get(item.id)?.label ?? null,
 [nextFoldByItemId]
 );
 // Okno „Przesuń dalej" i okno QC CV (F2: `CvQcDialog`).
 const [moveNext, setMoveNext] = useState<{
 item: KanbanItem;
 srcColId: string;
 target: KanbanColumn;
 targetLabel: string;
 targetKey: BoardColumnKey | null;
 fromKey: BoardColumnKey | null;
 } | null>(null);
 // Okno „Przesuń dalej" chowa się na czas akcji z listy braków (arkusz,
 // QC, warsztat) i wraca po jej zamknięciu ze świeżymi wymaganiami.
 const [moveNextOpen, setMoveNextOpen] = useState(false);
 const moveNextSuspended = useRef(false);
 const [qcStageId, setQcStageId] = useState<number | null>(null);
 const [debriefFor, setDebriefFor] = useState<{ eventId: number; name: string } | null>(null);
 const openMoveNext = useCallback(
 (item: KanbanItem, srcColId: string, target: KanbanColumn) => {
 const fold = boardFold.columns.find((f) => f.host === target || f.members.includes(target));
 const host = fold?.host ?? target;
 setMoveNext({
 item,
 srcColId,
 target: host,
 targetLabel: fold?.label ?? columnLabel(host),
 targetKey: fold?.key ?? null,
 fromKey: columnByItemId.get(item.id) ?? null,
 });
 moveNextSuspended.current = false;
 setMoveNextOpen(true);
 },
 [boardFold, columnByItemId]
 );
 const onAdvance = useCallback(
 (item: KanbanItem) => {
 const next = nextFoldByItemId.get(item.id);
 const src = cols.find((c) => c.items.some((i) => i.id === item.id));
 if (!next || !src) return;
 openMoveNext(item, colId(src), next.host);
 },
 [nextFoldByItemId, cols, openMoveNext]
 );
 const onOpenQc = useCallback((item: KanbanItem) => setQcStageId(item.id), []);
 const [takingIds, setTakingIds] = useState<ReadonlySet<number>>(() => new Set());
 const takeCandidate = useCallback(
 async (item: KanbanItem) => {
 setTakingIds((prev) => new Set(prev).add(item.id));
 try {
 await api.post("/api/pipeline/claim", {
 candidate_id: item.candidate_id,
 job_id: jobId,
 });
 showSuccess(
 `${`${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat"} — Twój na 12 h.`
 );
 queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
 queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
 } catch (e) {
 showError(apiErrorMessage(e, "Nie udało się wziąć tej osoby."));
 } finally {
 setTakingIds((prev) => {
 const n = new Set(prev);
 n.delete(item.id);
 return n;
 });
 }
 },
 [jobId, queryClient, showSuccess, showError]
 );
 const boardV4 = useMemo<BoardV4Ctx>(
 () => ({
 columnByItemId,
 cproEnabled,
 viewerId: authUser?.id ?? null,
 readOnly,
 takingIds,
 onTake: takeCandidate,
 nextColumnLabel,
 onAdvance,
 onOpenQc,
 }),
 [columnByItemId, cproEnabled, authUser?.id, readOnly, takingIds, takeCandidate, nextColumnLabel, onAdvance, onOpenQc]
 );
 // Osoby już na tablicy — „Do przejrzenia" nie proponuje ich drugi raz.
 const boardCandidateIds = useMemo(
 () => cols.flatMap((c) => c.items.map((i) => i.candidate_id)),
 [cols]
 );
 const [focusedColId, setFocusedColId] = useState<string | null>(() =>
 defaultFocusColumnId(columns)
 );
 // Zaznaczenie po `candidate_id`, nie po id etapu: każdy ruch tworzy NOWY
 // `CandidateStage`, więc id etapu zaznaczonej karty po ruchu przestawało
 // istnieć, a „Zaznaczono N" liczyło martwe wpisy.
 const [selected, setSelected] = useState<Set<number>>(new Set());
 const [bulkDownloadBusy, setBulkDownloadBusy] = useState(false);
 const [statusMessage, setStatusMessage] = useState<string | null>(null);
 const showStatus = useCallback((msg: string) => {
 setStatusMessage(msg);
 setTimeout(() => setStatusMessage(null), 4000);
 }, []);
 // Powody odrzucenia, etapy ze scorecardem, nazwa szablonu, budżet PLN/h
 // (ta sama liczba co nagłówek i wyszukiwanie) oraz prawo zapisu stawki do
 // klienta (`GET /api/jobs/{id}` liczy je tą samą funkcją co
 // `PATCH …/client-rate`) — wspólny hook z widokiem tabeli rekrutacji.
 const {
 rejectionReasons,
 stagesWithScorecard,
 budgetHourly: jobBudgetHourlyValue,
 canWriteClientRate,
 } = useJobPipelineTemplate(jobId);

 // Krok 04 Pipeline (flow C2, PR 3/7): dok „Karta w procesie" — trzymany po
 // `candidate_id` (STABILNY), nie po id CandidateStage (`item.id` zmienia się
 // przy KAŻDYM ruchu — `usePipelineMove` podmienia je przez `confirmMoved` na nowy
 // wiersz). Po candidate_id dok „podąża" za kandydatem przez ruchy bez żadnej
 // dodatkowej synchronizacji.
 const [dockCandidateId, setDockCandidateId] = useState<number | null>(null);
 const openDock = useCallback((item: KanbanItem) => {
 setDockCandidateId(item.candidate_id);
 }, []);
 const closeDock = useCallback(() => setDockCandidateId(null), []);
 // Warsztat osoby (szeroki panel z dawnej „Tabeli") — nad Tablicą.
 const [workbench, setWorkbench] = useState<{
 candidateId: number;
 section: PersonPanelSection;
 } | null>(null);
 useEffect(() => {
 onDockCandidateChange?.(dockCandidateId);
 }, [dockCandidateId, onDockCandidateChange]);

 // Lewa kolumna: filtry NIE usuwają kart z `cols` (zepsułoby to indeksy
 // `@hello-pangea/dnd`, na których stoi `onDragEnd` — patrz `PipelineFiltersRail`).
 // Przyciemniają niepasujące karty; `isDimmed` musi mieć stabilną referencję
 // (memo na `KanbanColumnV2`/`CandidateKanbanCard` — patrz komentarz niżej przy
 // `toggleSelect`), stąd `useCallback` z zależnościami tylko od samych filtrów.
 const [stuckFilter, setStuckFilter] = useState(false);
 const [blockedFilter, setBlockedFilter] = useState(false);
 const [noActionFilter, setNoActionFilter] = useState(false);
 const [recruiterFilter, setRecruiterFilter] = useState<string | null>(null);
 // Pasek filtrów (22.09.2026): „Mój ruch" i szukanie po nazwisku.
 const [myMoveFilter, setMyMoveFilter] = useState(false);
 const [nameQuery, setNameQuery] = useState("");

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


 // --- Wysokość kolumn liczona dynamicznie od realnej pozycji boardu ---------
 // Problem: stary `h-[calc(100dvh-350px)]` miał na sztywno offset 350px = wysokość
 // rozwiniętego nagłówka. Po zwinięciu nagłówka treść nad boardem maleje, ale
 // offset zostaje 350 → board się nie rozciąga i na dole robi się dziura.
 // Fix: mierzymy `getBoundingClientRect().top` boardu i wypełniamy resztę
 // viewportu. Adaptuje się do KAŻDEGO stanu nagłówka (zwinięty/rozwinięty,
 // z opisem/bez, zawijające się przyciski) — bez magicznych liczb.
 const boardRef = useRef<HTMLDivElement>(null);
 const [columnHeight, setColumnHeight] = useState<number | undefined>(undefined);
 // Górna krawędź obszaru treści (pod topbarem i ewentualnym paskiem „podglądaj
 // jako"). Dok karty kandydata startuje od niej — stałe `top-12` zakładało,
 // że topbar jest pierwszy, więc przy pasku podglądu dok zachodził na topbar.
 const [chromeTop, setChromeTop] = useState<number | null>(null);
 const measureColumnHeight = useCallback(() => {
 const el = boardRef.current;
 if (!el || typeof window === "undefined") return;
 const main = el.closest("main");
 const mainTop = main ? Math.round(main.getBoundingClientRect().top) : null;
 setChromeTop((prev) => (prev === mainTop ? prev : mainTop));
 // Telefon: nad planszą stoi nagłówek, filtry i nawigator etapów, więc
 // „reszta okna pod planszą" to często podłoga 280 px (≈2 karty). Tam plansza
 // dostaje wysokość całego obszaru treści: nagłówek przewija się raz, potem
 // plansza wypełnia ekran.
 const narrow =
 typeof window.matchMedia === "function" &&
 !window.matchMedia("(min-width: 768px)").matches;
 const next = Math.max(
 MIN_COLUMN_HEIGHT,
 narrow && main
 ? Math.round(main.clientHeight - MOBILE_MAIN_PADDING_Y)
 : Math.round(window.innerHeight - el.getBoundingClientRect().top - BOARD_BOTTOM_GAP)
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

 // Skok ze „Ścieżki rekrutacji" (nagłówek strony): przewiń i podświetl.
 const [highlightColId, setHighlightColId] = useState<string | null>(null);
 const handledFocusSeq = useRef<number | null>(null);
 useEffect(() => {
 if (!focusColumnRequest || handledFocusSeq.current === focusColumnRequest.seq) return;
 const fold = boardFold.columns.find((f) => f.key === focusColumnRequest.column);
 if (!fold) return;
 handledFocusSeq.current = focusColumnRequest.seq;
 const id = colId(fold.host);
 focusColumn(id);
 setHighlightColId(id);
 }, [focusColumnRequest, boardFold, focusColumn]);
 useEffect(() => {
 if (!highlightColId) return;
 const timer = window.setTimeout(() => setHighlightColId(null), 1600);
 return () => window.clearTimeout(timer);
 }, [highlightColId]);

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

 // M4 PR-03: po błędzie ruchu NIE zostawiamy karty w niepotwierdzonej
 // kolumnie — dociągamy prawdę z serwera (a nie lokalny snapshot, bo 409
 // oznacza, że stan pary i tak się zmienił pod nami). Zapytanie strony
 // (`["kanban", …]`, oba klucze) unieważnia po tym sam `usePipelineMove`.
 const refreshBoardFromServer = useCallback(async () => {
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
 }, [jobId]);

 // Serwer potwierdził ruch. `fromColId === null` = karta stoi już w kolumnie
 // docelowej (ruch optymistyczny) i dostaje pola nowego `CandidateStage`;
 // inaczej („Zweryfikowany" — bez ruchu optymistycznego, bo okno stawki można
 // anulować) zdejmujemy ją ze źródła i dokładamy do celu.
 const confirmMoved = useCallback(
 ({
 item,
 fromColId,
 toColumn,
 patch,
 }: {
 item: KanbanItem;
 fromColId: string | null;
 toColumn: KanbanColumn;
 patch: PipelineMoveConfirmedPatch;
 }) => {
 setCols((prev) =>
 prev.map((c) => {
 if (fromColId !== null && colId(c) === fromColId) {
 const items = c.items.filter((i) => i.id !== item.id);
 return { ...c, items, count: items.length };
 }
 if (colId(c) !== colId(toColumn)) return c;
 if (fromColId === null) {
 return {
 ...c,
 items: c.items.map((i) => (i.id === item.id ? { ...i, ...patch } : i)),
 };
 }
 const items = [...c.items, { ...item, ...patch }];
 return { ...c, items, count: items.length };
 })
 );
 },
 []
 );

 // Krok 04 Pipeline: cała orkiestracja ruchu (bramka `moveBlockedReason`,
 // okna stawek, potwierdzenie zatrudnienia, powód odrzucenia, ostrzeżenie
 // dopuszczalności, konflikt wersji, unieważnienie zapytań) mieszka w
 // `usePipelineMove` — dok, przeciąganie i akcje zbiorcze wołają TĘ SAMĄ
 // decyzję. Tablica dokłada wyłącznie swój stan optymistyczny `cols`.
 const move = usePipelineMove({
 jobId,
 job: { budgetHourly: jobBudgetHourlyValue, rejectionReasons },
 columns: cols,
 readOnly,
 canWriteClientRate,
 cproEnabled,
 optimistic: {
 apply: applyOptimistic,
 confirm: confirmMoved,
 sync: refreshBoardFromServer,
 },
 // 409 CV_QC_FAILED (także z przeciągnięcia) → okno QC CV tej pary.
 onCvQcFailed: (failure, item) => setQcStageId(failure.stageId ?? item.id),
 });
 const { requestMove, requestReject } = move;

 // Rekrutacja v5: ruch NAPRZÓD przez Tablicę. Na sąsiednią kolumnę bez
 // znanych braków — od razu (`usePipelineMove`, jak dotąd). Dalej niż
 // o jedną kolumnę, przy znanym braku albo na „CV wysłane" (bramka QC,
 // wysyłka przez DL / kolejka Cpro) — najpierw okno „Przesuń dalej".
 // Ruchy wstecz i na etapy-znaczniki w tej samej kolumnie idą od razu.
 const routeMove = useCallback(
 (item: KanbanItem, srcColId: string, dst: KanbanColumn) => {
 const fromIndex = foldIndexByColId.get(srcColId);
 const toIndex = foldIndexByColId.get(colId(dst));
 if (fromIndex == null || toIndex == null || toIndex <= fromIndex) {
 requestMove(item, srcColId, dst);
 return;
 }
 const fromKey = boardFold.columns[fromIndex]?.key ?? null;
 const toKey = boardFold.columns[toIndex]?.key ?? null;
 const stageBadge = boardFold.badgeByItemId.get(item.id) ?? null;
 const directToClient =
 toKey === "cv_sent" &&
 !(cproEnabled ? stageBadge === "cpro" : canReviewAsDl && item.qc?.status !== "failed");
 if (toIndex - fromIndex > 1 || knownForwardGap(item, fromKey) || directToClient) {
 openMoveNext(item, srcColId, dst);
 return;
 }
 requestMove(item, srcColId, dst);
 },
 [foldIndexByColId, boardFold, cproEnabled, canReviewAsDl, openMoveNext, requestMove]
 );

 const onDragEnd = useCallback(
 (res: DropResult) => {
 if (readOnly) return;
 if (!res.destination) return;
 // Kolumna Tablicy składa kilka etapów — indeks karty liczy się po
 // ZŁOŻONEJ liście, a ruch po prawdziwym etapie, na którym karta stoi.
 const srcDisplay =
 displayCols.find((c) => colId(c) === res.source.droppableId) ??
 cols.find((c) => colId(c) === res.source.droppableId);
 // Pasek zamkniętych (Pipeline v4): „<kolumna>::<kto>" = odrzucenie
 // z wybranym „kto kończy" (my / DL / klient).
 const [dstId, closedBy] = res.destination.droppableId.split(CLOSED_BY_SEP);
 // `stageCols`, nie `cols` — kubełek nie jest celem ruchu.
 const dst = stageCols.find((c) => colId(c) === dstId);
 if (!srcDisplay || !dst || colId(srcDisplay) === colId(dst)) return;
 const item = srcDisplay.items[res.source.index];
 if (!item) return;
 const realSrc = cols.find((c) => c.items.some((i) => i.id === item.id));
 if (!realSrc || hostByColId.get(colId(realSrc)) === dst) return;
 if (closedBy && terminalOf(dst) === "rejected") {
 requestReject(item, dst, { endedBy: closedBy as ClosedRejectBy });
 return;
 }
 routeMove(item, colId(realSrc), dst);
 },
 [cols, displayCols, stageCols, hostByColId, routeMove, requestReject, readOnly]
 );

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
 const host = hostByColId.get(colId(c));
 return {
 dockItem: found,
 dockItemColId: colId(c),
 dockItemColLabel:
 (host ? boardLabelByColId.get(colId(host)) : undefined) ?? columnLabel(c),
 };
 }
 }
 }
 return { dockItem: null, dockItemColId: null, dockItemColLabel: null };
 }, [cols, dockCandidateId, hostByColId, boardLabelByColId]);

 // Dok jest nakładką z prawej — Escape go zamyka, chyba że otwarty jest
 // dialog (modal powodu odrzucenia, stawki itp.): wtedy Escape należy do niego.
 useEffect(() => {
 if (!dockItem) return;
 const onKey = (e: KeyboardEvent) => {
 if (e.key !== "Escape" || e.defaultPrevented) return;
 if (document.querySelector('[role="dialog"],[role="alertdialog"]')) return;
 closeDock();
 };
 window.addEventListener("keydown", onKey);
 return () => window.removeEventListener("keydown", onKey);
 }, [dockItem, closeDock]);

 // Deep link `?candidate=&panel=` (dawne linki do sekcji panelu „Tabeli" —
 // m.in. zapisane w powiadomieniach): otwiera warsztat osoby, gdy jest na
 // tablicy. Jednorazowo na każdą nową wartość, jak dok.
 const handledWorkbenchRef = useRef<string | null>(null);
 useEffect(() => {
 if (!initialWorkbench || !workbenchContext) return;
 const key = `${initialWorkbench.candidateId}:${initialWorkbench.section}`;
 if (handledWorkbenchRef.current === key) return;
 const onBoard = cols.some((c) =>
 c.items.some((i) => i.candidate_id === initialWorkbench.candidateId)
 );
 if (!onBoard && cols.length === 0) return;
 handledWorkbenchRef.current = key;
 if (onBoard) setWorkbench(initialWorkbench);
 onInitialWorkbenchHandled?.();
 }, [initialWorkbench, workbenchContext, cols, onInitialWorkbenchHandled]);

 // Zbiorcza wysyłka CV (dawny pasek zbiorczy „Tabeli"): per osoba ruch na
 // „CV Wysłane" → link dla klienta → stawka, na końcu jedno okno z linkami.
 const bulkCv = useBulkCvHandoff({
 jobId,
 jobTitle: jobTitle ?? null,
 columns: stageCols,
 canWriteClientRate,
 });
 const cvSentColumn = useMemo(() => findStageColumn(stageCols, CV_SENT_STAGE), [stageCols]);
 const startBulkCv = () => {
 const rows = buildProcessRows(stageCols, { budgetHourly: jobBudgetHourlyValue ?? null }).filter(
 (r) => selected.has(r.candidateId)
 );
 if (rows.length === 0) return;
 bulkCv.start(rows, { onHandled: () => setSelected(new Set()) });
 };

 // Deep link `?candidate=<id>`: jednorazowo na każdą NOWĄ wartość parametru.
 // Ref trzyma obsłużone id, żeby przebudowa `cols` (ruch, odświeżenie) nie
 // otwierała doku ponownie po tym, jak użytkownik go zamknął.
 const handledInitialDockRef = useRef<number | null>(null);
 useEffect(() => {
 if (initialDockCandidateId == null) {
 handledInitialDockRef.current = null;
 return;
 }
 if (handledInitialDockRef.current === initialDockCandidateId) return;
 handledInitialDockRef.current = initialDockCandidateId;
 const onBoard = cols.some((c) =>
 c.items.some((i) => i.candidate_id === initialDockCandidateId)
 );
 if (onBoard) {
 setDockCandidateId(initialDockCandidateId);
 const card = document.querySelector<HTMLElement>(
 `[data-candidate-id="${initialDockCandidateId}"]`
 );
 card?.scrollIntoView?.({ block: "center", inline: "center" });
 }
 onInitialDockHandled?.();
 }, [initialDockCandidateId, cols, onInitialDockHandled]);

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
 const dockHost = dockItemColId ? (hostByColId.get(dockItemColId) ?? null) : null;
 const dockHostKey = dockItem ? (columnByItemId.get(dockItem.id) ?? null) : null;
 const dockMoveTargets = useMemo<PipelineMoveTarget[]>(() => {
 if (!dockItem || !dockItemColId) return [];
 // Cele: 8 kolumn Tablicy (ich gospodarze) + zamknięci — bez etapów-odznak,
 // te ustawia się przełącznikiem odznaki.
 return moveTargetCols
 .filter((c) => !dockHost || colId(c) !== colId(dockHost))
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
 }, [dockItem, dockItemColId, moveTargetCols, dockHost, readOnly]);
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
 // Po kolumnach Tablicy, nie po etapach szablonu: z „QC CV" główna akcja
 // prowadzi do „CV wysłane", nie do etapu-znacznika „Wysłać do Cpro".
 return primaryForwardMove({
 item: dockItem,
 columns: moveTargetCols,
 currentColId: dockHost ? colId(dockHost) : dockItemColId,
 readOnly,
 });
 }, [dockItem, dockItemColId, moveTargetCols, dockHost, readOnly]);

 // Przełączniki odznak w doku: etap-odznaka z kolumny tej osoby. Włączenie =
 // ruch na etap-odznakę, wyłączenie = powrót na gospodarza kolumny.
 const dockBadgeToggles = useMemo(() => {
 if (!dockItem || !dockItemColId || !dockHost) return [];
 const fold = boardFold.columns.find((f) => f.host === dockHost);
 if (!fold) return [];
 const toggles: Array<{
 key: StageBadgeKey;
 label: string;
 active: boolean;
 disabledReason: string | null;
 onToggle: () => void;
 }> = [];
 // Rekrutacja v5: DZ stał się kolumną „QC CV", a Cpro ustawia strzałka
 // („Przesuń dalej" → „Przekaż do Cpro") — zostaje „Umowa podpisana".
 for (const member of fold.members) {
 const badge = placeStage(member).badge;
 if (!badge || !SETTABLE_BADGES.includes(badge)) continue;
 const currentBadge = placeStage(
 fold.members.find((m) => colId(m) === dockItemColId) ?? dockHost
 ).badge;
 const active = impliedBadges(currentBadge).includes(badge);
 toggles.push({
 key: badge,
 label: STAGE_BADGE_LABEL[badge],
 active,
 disabledReason: readOnly ? "Tylko odczyt." : null,
 onToggle: () => requestMove(dockItem, dockItemColId, active ? dockHost : member),
 });
 }
 return toggles;
 }, [dockItem, dockItemColId, dockHost, boardFold, readOnly, requestMove]);

 // Wiersz „następna akcja" doku — TA SAMA funkcja, którą renderuje karta na
 // tablicy; osobna kopia rozjechałaby się przy pierwszej zmianie progu.
 const dockNextAction = useMemo<NextAction | null>(() => {
 if (!dockItem || !dockItemColumn) return null;
 return nextActionFor(dockItem, dockItemColumn, {
 slaDays,
 group: dockItemColId ? groupByColId.get(dockItemColId) : undefined,
 });
 }, [dockItem, dockItemColumn, dockItemColId, groupByColId, slaDays]);

 // Pipeline v4 (decyzja 23.09.2026): DL wysyłający osobę ze „Zweryfikowanego"
 // do klienta dostaje ten sam pełny przegląd co na pulpicie (stawka kandydata,
 // CV, screening, stawka do klienta — bez marży), a nie samo okno stawki.
 const [dlReviewTask, setDlReviewTask] = useState<BoardTaskRow | null>(null);
 const handleDockMove = useCallback(
 (dst: KanbanColumn) => {
 if (!dockItem || !dockItemColId) return;
 if (
 dst.stage === "cv_sent" &&
 !cproEnabled &&
 canReviewAsDl &&
 dockHostKey === "cv_qc" &&
 dockItem.qc?.status !== "failed"
 ) {
 setDlReviewTask({
 kind: "dl_review",
 stage_id: dockItem.id,
 candidate_id: dockItem.candidate_id,
 candidate_name: itemFullName(dockItem),
 job_id: jobId,
 job_title: jobTitle ?? "",
 client_id: clientId ?? null,
 client_name: null,
 since: dockItem.moved_at ?? new Date().toISOString(),
 process_state_version: dockItem.process_state_version ?? 0,
 target_stage_def_id: dst.stage_def_id ?? null,
 rejected_stage_def_id: rejectedTemplateCol?.stage_def_id ?? null,
 assignee_id: null,
 assignee_name: null,
 verified_at: dockItem.moved_at ?? null,
 expected_rate_value:
 dockItem.expected_rate_value != null ? Number(dockItem.expected_rate_value) : null,
 expected_rate_unit: dockItem.expected_rate_unit ?? null,
 expected_rate_currency: dockItem.expected_rate_currency ?? null,
 // Serwer czyta arkusz pary (także z „Nowych"), gdy etap nie ma własnego.
 screening_stage_id: dockItem.id,
 });
 return;
 }
 // Wybór etapu z doku jest jawny — ruch od razu (serwer i tak pilnuje
 // bramki QC; 409 CV_QC_FAILED otwiera okno QC CV).
 requestMove(dockItem, dockItemColId, dst);
 },
 [dockItem, dockItemColId, requestMove, cproEnabled, canReviewAsDl, dockHostKey, jobId, jobTitle, clientId, rejectedTemplateCol]
 );
 // Ramka „Następny etap": przekazanie na etap wskazany przez serwer
 // (`primary.target_stage_def_id` — „QC CV" dla DL, „Wysłać do Cpro").
 // Ta sama droga co w oknie „Przesuń dalej" (`handleHandToCpro`).
 const handleDockMoveToStageDef = useCallback(
 (stageDefId: number) => {
 if (!dockItem || !dockItemColId) return;
 const dst = stageCols.find((c) => c.stage_def_id === stageDefId);
 if (!dst) {
 showError("Nie znaleziono tego etapu w szablonie tej rekrutacji.");
 return;
 }
 requestMove(dockItem, dockItemColId, dst);
 },
 [dockItem, dockItemColId, stageCols, requestMove, showError]
 );

 const handleDockReject = useCallback(() => {
 if (!dockItem || !dockItemColId || !rejectedTemplateCol) return;
 requestReject(dockItem, rejectedTemplateCol);
 }, [dockItem, dockItemColId, rejectedTemplateCol, requestReject]);
 const handleDockWithdraw = useCallback(() => {
 if (!dockItem) return;
 move.requestWithdraw(dockItem);
 }, [dockItem, move]);

 // ── Okno „Przesuń dalej" (Rekrutacja v5) ────────────────────────────────
 const refreshMoveRequirements = useCallback(() => {
 void queryClient.invalidateQueries({ queryKey: MOVE_REQUIREMENTS_PREFIX });
 }, [queryClient]);
 // Okno akcji (arkusz, QC, warsztat, terminy, debrief) się zamknęło — wróć
 // do „Przesuń dalej" z przeliczonymi wymaganiami.
 const resumeMoveNext = useCallback(() => {
 refreshMoveRequirements();
 if (!moveNextSuspended.current) return;
 moveNextSuspended.current = false;
 setMoveNextOpen(true);
 }, [refreshMoveRequirements]);
 const suspendMoveNext = useCallback(() => {
 moveNextSuspended.current = true;
 setMoveNextOpen(false);
 }, []);
 const handleMoveNextAction = useCallback(
 (action: MoveRequirementAction, item: KanbanItem) => {
 const name = itemFullName(item);
 const stageId = action.stage_id ?? item.id;
 switch (action.kind) {
 case "open_screening":
 suspendMoveNext();
 setScreeningPrompt({ stageId, candidateName: name });
 return;
 case "open_qc":
 suspendMoveNext();
 setQcStageId(stageId);
 return;
 case "set_candidate_rate": {
 // Stawkę kandydata zapisuje ruch na „Zweryfikowany" (okno stawki
 // `usePipelineMove`) — osoba stoi dalej przed tą kolumną.
 const verified = boardFold.columns.find((f) => f.key === "verified")?.host;
 const src = cols.find((c) => c.items.some((i) => i.id === item.id));
 setMoveNextOpen(false);
 if (verified && src) requestMove(item, colId(src), verified);
 return;
 }
 case "generate_cv":
 case "set_client_rate":
 if (workbenchContext) {
 suspendMoveNext();
 setWorkbench({ candidateId: item.candidate_id, section: "cv" });
 } else {
 window.open(
 `/cv-generator?candidate_id=${item.candidate_id}&job_id=${jobId}`,
 "_blank",
 "noopener"
 );
 }
 return;
 case "open_debrief":
 suspendMoveNext();
 if (action.event_id != null) {
 setDebriefFor({ eventId: action.event_id, name });
 } else if (workbenchContext) {
 setWorkbench({ candidateId: item.candidate_id, section: "interviews" });
 } else {
 moveNextSuspended.current = false;
 window.open(`/calendar?view=agenda`, "_blank", "noopener");
 }
 return;
 case "request_slots":
 if (canAddClientSlots) {
 suspendMoveNext();
 setSlotPair({
 candidate_id: item.candidate_id,
 candidate_name: name,
 candidate_email: null,
 job_id: jobId,
 job_title: jobTitle ?? null,
 client_id: clientId ?? null,
 client_name: null,
 });
 } else {
 window.open(`/calendar?view=agenda`, "_blank", "noopener");
 }
 return;
 default:
 return;
 }
 },
 [suspendMoveNext, boardFold, cols, requestMove, workbenchContext, jobId, jobTitle, clientId, canAddClientSlots]
 );
 const handleMoveNextMove = useCallback(
 (target: KanbanColumn) => {
 if (!moveNext) return;
 requestMove(moveNext.item, moveNext.srcColId, target);
 },
 [moveNext, requestMove]
 );
 const handleHandToCpro = useCallback(
 (stageDefId: number) => {
 if (!moveNext) return;
 const cpro = stageCols.find((c) => c.stage_def_id === stageDefId);
 if (!cpro) {
 showError("Nie znaleziono tego etapu w szablonie tej rekrutacji.");
 return;
 }
 requestMove(moveNext.item, moveNext.srcColId, cpro);
 },
 [moveNext, stageCols, requestMove, showError]
 );

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
 // „Mój ruch" — karty, na których plakietka mówi „Twój ruch" (`cardNextStep`
 // — ta sama funkcja i te same kolumny Tablicy co karta). Do 24.09.2026 filtr
 // liczył każdą kartę z ruchem po stronie rekrutera, także tę z imieniem innego
 // rekrutera albo z „DL" w QC CV. Karty w „Nowi" też się liczą — ich
 // plakietka mówi „Twój ruch" (albo imię osoby, która wzięła je na 12 h).
 const myMoveIds = useMemo(() => {
 const ids = new Set<number>();
 for (const col of [...displayCols, ...cols.filter((c) => isOffTemplate(c))]) {
 if (col.category === "terminal") continue;
 const group = groupByColId.get(colId(col));
 const column = boardKeyByColId.get(colId(col)) ?? null;
 for (const item of col.items) {
 const action = nextActionFor(item, col, { slaDays, group });
 const step = cardNextStep(action, item, {
 column,
 cproEnabled,
 stageBadge: boardFold.badgeByItemId.get(item.id) ?? null,
 viewerId: authUser?.id ?? null,
 });
 if (step?.mine) ids.add(item.id);
 }
 }
 return ids;
 }, [displayCols, cols, groupByColId, boardKeyByColId, boardFold, slaDays, cproEnabled, authUser?.id]);
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
 if (myMoveFilter && !myMoveIds.has(item.id)) return true;
 const q = nameQuery.trim().toLocaleLowerCase("pl");
 if (q && !`${item.name ?? ""} ${item.lastname ?? ""}`.toLocaleLowerCase("pl").includes(q)) {
 return true;
 }
 return false;
 },
 [stuckFilter, stuckIds, blockedFilter, noActionFilter, noActionIds, recruiterFilter, myMoveFilter, myMoveIds, nameQuery]
 );

 // Kolumny do renderu: 8 kolumn Tablicy (+ rozwinięci zamknięci + kubełek
 // „Poza szablonem"). „Ukryj puste kolumny" usuwa CAŁE kolumny bez kart —
 // bezpieczne dla `@hello-pangea/dnd` (pusta kolumna nie ma indeksów).
 // „Do przejrzenia" nie znika nigdy: niesie propozycje spoza kanbana.
 const offTemplateCols = useMemo(() => cols.filter((c) => isOffTemplate(c)), [cols]);
 const visibleCols = useMemo(() => {
 const base = [
 ...displayCols,
 ...(showClosed ? boardFold.closed : []),
 ...offTemplateCols,
 ];
 return hideEmptyColumns
 ? base.filter((c) => c.count > 0 || boardKeyByColId.get(colId(c)) === "new")
 : base;
 }, [displayCols, boardFold, showClosed, offTemplateCols, hideEmptyColumns, boardKeyByColId]);

 // Nawigator doku „‹ N z M ›" — kolejność WIDOCZNEJ Tablicy: kolumny od
 // lewej (także rozwinięci zamknięci i „Poza szablonem"), karty od góry,
 // bez kart przygaszonych filtrem (`dockNavigationOrder`). Klucz to
 // `candidate_id` (stabilny przez ruchy), dokładnie jak `dockCandidateId`.
 const dockOrder = useMemo(
 () => dockNavigationOrder(visibleCols, isDimmed, dockCandidateId),
 [visibleCols, isDimmed, dockCandidateId]
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

 const boardEntries = useMemo(
 () => visibleCols.map((col) => ({ kind: "column" as const, key: colId(col), col })),
 [visibleCols]
 );

 const bulkMove = (destColId: string) => {
 const dst = stageCols.find((c) => colId(c) === destColId);
 if (!dst || selected.size === 0) return;
 const allCards = cols.flatMap((c) => c.items);
 const items: KanbanItem[] = [];
 for (const cid of Array.from(selected)) {
 const found = allCards.find((i) => i.candidate_id === cid);
 if (found) items.push(found);
 }
 void move.requestBulkMove(items, dst, {
 onHandled: () => setSelected(new Set()),
 });
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
 // Tryb widoku: `auto` rozstrzyga próg kolumn, jawny wybór użytkownika
 // wygrywa. Poniżej progu przełącznika nie ma, więc wynik jest zawsze
 // „kolumny" — kafelki na wąskim szablonie byłyby stanem bez wyjścia.
 const viewToggleVisible = kanbanViewToggleVisible({
 renderedColumns: boardEntries.length,
 fullPipelineDesktop,
 });
 const viewMode = resolveKanbanViewMode(viewPreference, {
 renderedColumns: boardEntries.length,
 fullPipelineDesktop,
 });
 const desktopOverview = viewMode === "tiles";

 // Zamknięci w JEDNEJ linii z filtrami (24.09.2026): „Zamknięci:" + chipy.
 // Każdy chip jest celem upuszczenia (odrzucenie z powodem jak dotąd), klik
 // rozwija ich pełne kolumny na końcu tablicy.
 const closedBar =
 boardFold.closed.length > 0 ? (
 <span
 data-testid="board-closed-bar"
 data-help="jobs.board.closed"
 className="inline-flex flex-wrap items-center gap-1 text-[11px]"
 >
 <span className="text-muted-foreground">Zamknięci:</span>
 {showClosed ? (
 <button
 type="button"
 onClick={() => setShowClosed(false)}
 className="rounded-full border border-border px-2 py-0.5 text-muted-foreground hover:bg-accent pointer-coarse:min-h-9"
 >
 Zwiń zamkniętych
 </button>
 ) : (
 closedChips(boardFold.closed).map(({ droppableId, label, short, count }) => (
 <Droppable key={droppableId} droppableId={droppableId} isDropDisabled={readOnly}>
 {(provided, snapshot) => (
 <span
 ref={provided.innerRef}
 {...provided.droppableProps}
 className={cn(
 "inline-flex rounded-full border border-dashed border-border transition-colors",
 snapshot.isDraggingOver && "border-destructive bg-destructive/10"
 )}
 >
 <button
 type="button"
 onClick={() => setShowClosed(true)}
 aria-label={`${label}: ${count} — pokaż kolumny zamkniętych`}
 title={`${label} — upuść tu kartę albo kliknij, żeby zobaczyć osoby`}
 className="px-2 py-0.5 text-muted-foreground hover:text-foreground pointer-coarse:min-h-9"
 >
 {short}{" "}
 <span className="font-semibold tabular-nums text-foreground">{count}</span>
 </button>
 <span className="hidden">{provided.placeholder}</span>
 </span>
 )}
 </Droppable>
 ))
 )}
 </span>
 ) : null;

 return (
 <BoardV4Context.Provider value={boardV4}>
 <div className="relative space-y-3">
 {/* DragDropContext obejmuje też pasek filtrów: chipy zamkniętych stoją
 w nim (jedna linia, 24.09.2026) i są celami upuszczenia. */}
 <DragDropContext onDragEnd={onDragEnd}>
 {/* Krok 04 Pipeline: lewa kolumna filtrów i tablica. Dok „Karta
 kandydata" NIE zajmuje kolumny siatki — wysuwa się z prawej dopiero po
 kliknięciu karty (przegląd UX 17.09.2026: stała trzecia kolumna zjadała
 tablicy 360 px nawet wtedy, gdy nic nie było wybrane). */}
 <div className="space-y-3">
 <PipelineFilterBar
 nameQuery={nameQuery}
 onNameQueryChange={setNameQuery}
 myMoveFilter={myMoveFilter}
 onToggleMyMoveFilter={() => setMyMoveFilter((v) => !v)}
 myMoveCount={myMoveIds.size}
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
 trailing={
 <BoardViewControls
 viewMode={viewToggleVisible ? viewMode : null}
 onSetViewMode={setViewPreference}
 density={density}
 onToggleDensity={() => setDensity(density === "cozy" ? "compact" : "cozy")}
 />
 }
 inProcessCount={stageCols.reduce(
 (sum, c) => sum + (c.category === "terminal" ? 0 : c.count),
 0
 )}
 closed={closedBar}
 />

 <div className={cn("min-w-0 space-y-3", dockItem && dockItemColLabel !== null &&"lg:pr-[380px]")}>
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
 cols={displayCols}
 focusedId={focusedColId}
 onFocus={focusColumn}
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
 {/* „Zatrudniony" nie jest celem ruchu zbiorczego — hired zakłada
 szkic kontraktu i zamówienia per osoba (guard w `bulkMove`
 odrzuca go i tak; tu nie kusimy opcją, która zawsze odmówi). */}
 {moveTargetCols
 .filter((c) => terminalOf(c) !== "hired")
 .map((c) => (
 <SelectItem key={colId(c)} value={colId(c)}>
 {columnLabel(c)}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 </div>}
 {!readOnly && workbenchContext && cvSentColumn && (
 <Button
 size="sm"
 variant="secondary"
 onClick={startBulkCv}
 disabled={bulkCv.busy || move.isMoving || bulkDownloadBusy}
 >
 <Send className="h-3.5 w-3.5" />
 Wyślij CV do klienta
 </Button>
 )}
 <Button
 size="sm"
 variant="secondary"
 onClick={bulkDownloadCvs}
 disabled={bulkDownloadBusy || move.isMoving}
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
 disabled={move.isMoving || bulkDownloadBusy}
 className="text-destructive hover:bg-destructive/10 hover:text-destructive"
 >
 <XCircle className="h-3.5 w-3.5" />
 Odrzuć
 </Button>
 )}
 <button
 onClick={() => setSelected(new Set())}
 disabled={move.isMoving || bulkDownloadBusy}
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
 <div
 ref={boardRef}
 data-testid="pipeline-board"
 data-help="jobs.board.columns"
 data-desktop-layout={fullPipelineDesktop ?"full-pipeline" :"scroll"}
 className={cn(
 // Board = JEDYNY scroll-kontener (oba kierunki). Po usunięciu overflow-y
 // z kolumn to on jest „closestScrollable" każdej kolumny → @hello-pangea/dnd
 // śledzi jego scroll i auto-scrolluje go natywnie (drop trafia pod kursor,
 // skrajne kolumny osiągalne — bez ręcznego rAF). Definite height wypełnia
 // viewport; calc fallback działa do pierwszego pomiaru (SSR/pierwszy render).
 "flex gap-3 overflow-auto pb-4 min-h-[280px]",
 // Na dotyku kolumna dociąga do krawędzi (17 rem przy 343 px ekranu =
 // jedna kolumna + skrawek). `proximity`, nie `mandatory`: mandatory
 // walczy z auto-scrollem @hello-pangea/dnd przy przeciąganiu karty.
 "pointer-coarse:snap-x pointer-coarse:snap-proximity",
 fullPipelineDesktop &&"xl:pointer-fine:gap-1",
 columnHeight == null && "h-[calc(100dvh-4rem)] md:h-[calc(100dvh-240px)]"
 )}
 style={columnHeight != null ? { height: columnHeight } : undefined}
 >
 {/* „Nowi" (z propozycjami na górze) zawsze stoi pierwsza — także gdy
 szablon nie ma etapu „Nowi" albo jego pusta kolumna jest ukryta. */}
 {!boardEntries.some((e) => boardKeyByColId.get(e.key) === "new") && (
 <div className="flex w-[calc((100%-1.5rem)/3)] min-w-[17rem] shrink-0 snap-start flex-col rounded-lg border border-dashed border-primary/40 bg-background/60 sm:min-w-[19rem] xl:pointer-fine:min-w-[12.5rem]">
 <div className="flex items-center gap-2 border-b border-border px-3 py-2">
 <h3 className="flex-1 truncate text-sm font-medium text-foreground">Nowi</h3>
 {reviewTotal != null && (
 <Badge size="sm" variant={reviewTotal > 0 ? "soft" : "outline"}>
 {reviewTotal}
 </Badge>
 )}
 </div>
 <BoardReviewSection
 jobId={jobId}
 readOnly={readOnly}
 showPostingHeading={false}
 onTotalChange={setReviewTotal}
 pipelineCandidateIds={boardCandidateIds}
 budgetHourly={jobBudgetHourlyValue ?? null}
 compact={Boolean(onOpenAddCandidates)}
 onOpenPanel={onOpenAddCandidates}
 />
 </div>
 )}
 {boardEntries.length === 0 ? (
 <div className="flex-1 py-12 text-center text-sm text-muted-foreground">
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
 <>
 {boardEntries.map((entry) => (
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
 fullPipelineDesktop={fullPipelineDesktop}
 desktopOverview={desktopOverview}
 readOnly={readOnly}
 dropDisabled={isOffTemplate(entry.col)}
 onOpenDock={openDock}
 isDimmed={isDimmed}
 group={groupByColId.get(entry.key)}
 slaDays={slaDays}
 badgeByItemId={boardFold.badgeByItemId}
 step={boardColumnStep(boardKeyByColId.get(entry.key))}
 purpose={boardColumnPurpose(boardKeyByColId.get(entry.key), {
 cproEnabled,
 hired: entry.col.count,
 headcount: workbenchContext?.headcount ?? null,
 })}
 highlighted={highlightColId === entry.key}
 {...(boardLabelByColId.has(entry.key)
 ? { titleOverride: boardLabelByColId.get(entry.key) }
 : {})}
 {...(boardKeyByColId.get(entry.key) === "new"
 ? {
 // v5: propozycje mają własne pole nad kartami — nagłówek liczy ludzi w kolumnie.
 extraCount: onOpenAddCandidates ? 0 : (reviewTotal ?? 0),
 prepend: (
 <BoardReviewSection
 jobId={jobId}
 readOnly={readOnly}
 showPostingHeading={false}
 onTotalChange={setReviewTotal}
 pipelineCandidateIds={boardCandidateIds}
 budgetHourly={jobBudgetHourlyValue ?? null}
 compact={Boolean(onOpenAddCandidates)}
 onOpenPanel={onOpenAddCandidates}
 />
 ),
 }
 : {})}
 />
 ))}
 </>
 )}
 </div>
 </div>

 </div>
 </DragDropContext>

 {dockItem && dockItemColLabel !== null && (
 // Tablet (768–1023): dok nakrywa prawe kolumny planszy, a plansza nie ma
 // rezerwy miejsca (ta jest od `lg`), więc dok jest nakładką z tłem —
 // klik w tło zamyka kartę. Na telefonie dok ma pełną szerokość.
 <div
 aria-hidden="true"
 data-testid="pipeline-dock-backdrop"
 className="fixed inset-x-0 bottom-0 top-12 z-20 hidden bg-card/50 backdrop-blur-[2px] md:block lg:hidden"
 style={chromeTop != null ? { top: chromeTop } : undefined}
 onClick={closeDock}
 />
 )}
 {dockItem && dockItemColLabel !== null && (
 <aside
 aria-label="Karta kandydata"
 data-help="jobs.person.dock"
 className="fixed right-0 top-12 bottom-0 z-30 flex w-full max-w-[380px] flex-col border-l border-border bg-background shadow-xl"
 style={chromeTop != null ? { top: chromeTop } : undefined}
 >
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
 onMoveToStageDef={handleDockMoveToStageDef}
 onOpenScreening={handleOpenScreening}
 onReject={handleDockReject}
 onWithdraw={handleDockWithdraw}
 onAddClientSlots={
 canAddClientSlots &&
 (dockHostKey === "cv_sent" || dockHostKey === "client_interview")
 ? () =>
 setSlotPair({
 candidate_id: dockItem.candidate_id,
 candidate_name: itemFullName(dockItem),
 candidate_email: null,
 job_id: jobId,
 job_title: jobTitle ?? null,
 client_id: clientId ?? null,
 client_name: null,
 })
 : undefined
 }
 badgeToggles={dockBadgeToggles}
 onOpenWorkbench={
 workbenchContext
 ? (section) =>
 setWorkbench({ candidateId: dockItem.candidate_id, section })
 : undefined
 }
 />
 </aside>
 )}

 <DlReviewPanel
 task={dlReviewTask}
 open={dlReviewTask !== null}
 onOpenChange={(open) => {
 if (!open) setDlReviewTask(null);
 }}
 />
 <SlotRequestDialog
 open={slotPair !== null}
 pair={slotPair}
 onOpenChange={(open) => {
 if (open) return;
 setSlotPair(null);
 // Terminy od klienta same przesuwają kartę na „Rozmowę u klienta".
 queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
 queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
 resumeMoveNext();
 }}
 />
 <MoveNextDialog
 open={moveNextOpen && moveNext !== null}
 onOpenChange={(open) => {
 setMoveNextOpen(open);
 if (!open && !moveNextSuspended.current) setMoveNext(null);
 }}
 jobId={jobId}
 item={moveNext?.item ?? null}
 target={moveNext?.target ?? null}
 targetLabel={moveNext?.targetLabel ?? null}
 targetKey={moveNext?.targetKey ?? null}
 fromKey={moveNext?.fromKey ?? null}
 cproEnabled={cproEnabled}
 readOnly={readOnly}
 onMove={handleMoveNextMove}
 onHandToCpro={handleHandToCpro}
 onAction={handleMoveNextAction}
 />
 <CvQcDialog
 stageId={qcStageId}
 open={qcStageId !== null}
 onClose={() => {
 setQcStageId(null);
 resumeMoveNext();
 }}
 onChanged={() => {
 queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
 queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
 refreshMoveRequirements();
 }}
 />
 {debriefFor && (
 <DebriefRequiredDialog
 open={true}
 onOpenChange={(open) => {
 if (open) return;
 setDebriefFor(null);
 resumeMoveNext();
 }}
 eventId={debriefFor.eventId}
 candidateName={debriefFor.name}
 jobId={jobId}
 onSaved={() => {
 setDebriefFor(null);
 resumeMoveNext();
 }}
 />
 )}
 {workbench && workbenchContext && kanbanQueryState && (
 <BoardWorkbenchDrawer
 jobId={jobId}
 jobTitle={jobTitle ?? null}
 columns={stageCols}
 candidateId={workbench.candidateId}
 section={workbench.section}
 onSectionChange={(section) =>
 setWorkbench((prev) => (prev ? { ...prev, section } : prev))
 }
 onClose={() => {
 setWorkbench(null);
 resumeMoveNext();
 }}
 readOnly={readOnly}
 canWriteClientRate={canWriteClientRate}
 budgetHourly={jobBudgetHourlyValue ?? null}
 rejectionReasons={rejectionReasons}
 workbenchContext={workbenchContext}
 kanbanQueryState={kanbanQueryState}
 cproEnabled={cproEnabled}
 />
 )}
 {bulkCv.dialogs}

 {/* Modals */}
 {/* Okna ruchu (powód odrzucenia, stawki, zatrudnienie, ostrzeżenie) —
  `usePipelineMove`, wspólne z przyszłym widokiem tabeli i panelem osoby. */}
 {move.dialogs}

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
 onOpenChange={(v) => {
 if (v) return;
 setScreeningPrompt(null);
 resumeMoveNext();
 }}
 stageId={screeningPrompt.stageId}
 candidateName={screeningPrompt.candidateName}
 onSubmitted={() => {
 setScreeningPrompt(null);
 resumeMoveNext();
 }}
 />
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
 </BoardV4Context.Provider>
 );
}
