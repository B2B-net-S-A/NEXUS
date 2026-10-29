"use client";

import * as React from"react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from"react";
import { invalidatePreContract, preContractsApi } from "@/lib/api/preContracts";
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
 Ban,
 ClipboardList,
 ChevronLeft,
 ChevronRight,
 CircleCheck,
 Clock,
 FileArchive,
 FileSignature,
 FileText,
 Flag,
 HelpCircle,
 Loader2,
 Lock,
 LogOut,
 Mail,
 MoveRight,
 Phone,
 Send,
 Sparkles,
 Star,
 Trash2,
 Unlock,
 UserPlus,
 UserX,
 XCircle,
} from"lucide-react";
import {
 api,
 candidatesApi,
 hiringManagerFeedbackApi,
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
import { EmploymentPill } from "@/components/ds/EmploymentMarker";
import { isPlainLeftClick } from "@/lib/plain-left-click";
import { markerLabel } from "@/lib/employment-marker";
import { eligibilityWarningBadges } from "@/lib/eligibility-reason-labels";
import { encodeJobBackRef } from"@/lib/url-filters";
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
import { SlotRequestDialog } from "@/components/calendar/cycle/SlotDialogs";
import { DlReviewBody } from "@/components/v2/recruitment/DlReviewPanel";
import { DlReviewQueueDialog } from "@/components/v2/recruitment/dl-review/DlReviewQueueDialog";
import { PersonPanelShell, type PersonPanelSize } from "@/components/v2/person/PersonPanelShell";
import { CvQcDialog } from "@/components/v2/recruitment/CvQcDialog";
import { MoveNextDialog } from "@/components/v2/recruitment/MoveNextDialog";
import { MinimumFieldsDialog } from "@/components/v2/recruitment/MinimumFieldsDialog";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { ClientAcceptedDialog, type ClientAcceptanceValues } from "@/components/v2/recruitment/ClientAcceptedDialog";
import {
 acceptanceLine,
 acceptanceTitle,
 acceptedToast,
 contractStepCounts,
 type ClientAcceptanceRecipient,
 type ContractStepCounts,
} from "@/lib/client-acceptance";
import {
 dockNavigationOrder,
 nextColumnWithPeople,
 queueColumnAfterOpen,
 returnToQueueTarget,
} from "@/lib/board-dock-order";
import {
 ADDED_BY_ALL,
 addedByEmptyColumnText,
 addedByOptions,
 addedByQueueSuffix,
 matchesAddedBy,
 peopleInProgress,
 type AddedByFilter,
} from "@/lib/board-added-by";
import { cardCareLabel } from "@/lib/departed-care";
import { myWaitingItems } from "@/lib/job-closed-waiting";
import { ClosedJobWaitingBanner } from "@/components/v2/jobs/ClosedJobWaitingBanner";
import { DebriefRequiredDialog } from "@/components/v2/recruitment/DebriefRequiredDialog";
import {
 MOVE_REQUIREMENTS_PREFIX,
 type MoveRequirementAction,
} from "@/lib/api/moveRequirements";
import { CPRO_REVIEW_LABEL, fetchDlReviewRow, type BoardTaskRow } from "@/lib/api/boardTasks";
import type { PairInfo } from "@/lib/interview-cycle";
import {
 SETTABLE_BADGES,
 STAGE_BADGE_LABEL,
 STAGE_BADGE_TITLE,
 boardColumnStep,
 foldBoardColumns,
 impliedBadges,
 isCproStageName,
 placeStage,
 type BoardColumnKey,
 type StageBadgeKey,
} from "@/lib/board-stages";
import { boardColumnPurpose } from "@/lib/board-column-purpose";
import { HiredColumnHelp } from "@/components/v2/jobs/HiredColumnHelp";
import { hasPermission } from "@/lib/permissions";
import { hasRole, useAuthStore } from "@/store/auth";
import {
 CARD_BADGE_TONE_CLASS,
 cardBadges,
 cardStageBadge,
 cardNextStep,
 claimAction,
 fillGapsText,
 knownForwardGap,
 minimumOnlyGap,
 requirementsSkippedBadge,
 qcChip,
 type CardNextStep,
 type QcChipTone,
 compactCardBadge,
 cardOwner,
 cardShortName,
 criticalGapBadge,
 cvStateBadge,
 dlSendQueue,
 isReadyForDlSend,
 shortStepLabel,
} from "@/lib/board-card-badges";
import { apiErrorMessage } from "@/lib/api-error";
import {
 PersonWorkbenchTabs,
 usePersonRow,
 workbenchDefaultSection,
 workbenchSectionOwnsMove,
 type BoardWorkbenchContext,
 type KanbanQueryState,
 type NextInColumn,
} from "@/components/v2/person/PersonWorkbenchTabs";
import { createNoteFillChannel } from "@/lib/note-fill-channel";
import { screeningFormQueryKey } from "@/lib/api/screeningForm";
import { buildProcessRows } from "@/components/v2/recruitment/person-rows";
import type { PersonPanelSection } from "@/components/v2/recruitment/types";
import { useBulkCvHandoff } from "@/components/v2/recruitment/useBulkCvHandoff";
import { terminalOf } from"@/lib/kanban-terminal";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import {
 usePipelineMove,
 type PipelineMoveConfirmedPatch,
 type RejectFollowUp,
} from "@/hooks/usePipelineMove";
import {
 PipelineCandidateDock,
 type PipelineMoveTarget,
} from "@/components/v2/jobs/PipelineCandidateDock";
import { PersonPanelErrorBoundary } from "@/components/v2/jobs/PersonPanelErrorBoundary";
import {
 colId,
 columnLabel,
 ScoreRing,
 type KanbanColumn,
 type KanbanItem,
} from "@/components/v2/pages/kanban-shared";
import { OtherJobsChip, showsOtherJobsChip } from "@/components/v2/pages/kanban-other-jobs-chip";
import { useJointScreeningIntent } from "@/store/joint-screening";
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
 nextActionFor,
 oldestDaysInColumn,
 type NextAction,
 type NextActionKind,
} from "@/lib/pipeline-next-action";
import { closedReason } from "@/lib/closed-reason";
import { useClientPlaybook } from "@/lib/client-playbooks";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { useJobPipelineTemplate } from "@/hooks/useJobPipelineTemplate";
import { useReviewSequence } from "@/hooks/useReviewSequence";
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
 /** Krytyczne bez śladu u osoby (`/pipeline-scores` → `exclusions`) —
  *  plakietka „brak: …” na karcie (16.10.2026). */
 criticalGapMap?: Map<number, string[]>;
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
 /** `?candidate=<id>&review=1` (dzwonek „CV do przeglądu”): poza dokiem
  *  otwiera też przegląd DL tej osoby, gdy czeka na niego w „QC CV”. */
 initialDockOpensReview?: boolean;
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
 /** Przegląd przed wysłaniem do klienta w tej rekrutacji NALEŻY do patrzącego
  *  (serwer: `viewer_owns_dl_review` — Delivery Lead rekrutacji, a bez niego
  *  portfel klienta). Nie mylić z prawem wysyłki (`recruitment_manage`), które
  *  ma admin i każdy DL: ono daje przycisk, to — „Czeka na Ciebie”. */
 viewerOwnsDlReview?: boolean;
 /**
  * Pasek nad tablicą (02.10.2026: kafle „Kandydaci do dodania”). Dostaje
  * przełącznik widoku tablicy — widoczny tylko przy bardzo szerokim szablonie.
  */
 renderAbove?: (viewControls: React.ReactNode) => React.ReactNode;
 /** Zamknięta rekrutacja (28.10.2026): pasek z osobami patrzącego od „CV wysłane”. */
 closedJob?: { closedOn: string | null; reasonLabel: string | null } | null;
 /** Filtr „Kto dodał” (14.10.2026): strona trzyma go w adresie (`?added_by=`).
  *  Chowa karty innych osób w kolumnach w toku i zawęża kolejkę panelu.
  *  Obiekt ma być stabilny między renderami (strona go memoizuje). */
 addedBy?: AddedByFilter;
 /** Zmiana filtra z Tablicy („Pokaż wszystkich” w pustej kolumnie, pasek końca
  *  kolejki) i z menu etykiety kolejki w panelu. Bez niego tych miejsc nie ma. */
 onAddedByChange?: (filter: AddedByFilter) => void;
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

/**
 * Ruchy strzałką „→” czekające na wysłanie (14.10.2026) na świeżym stanie
 * z serwera. Serwer jeszcze o nich nie wie — odświeżenie tablicy w ciągu tych
 * 10 s cofałoby kartę na stare miejsce, a potem przesuwało ją drugi raz.
 */
export const withPendingMoves = (
 cols: KanbanColumn[],
 pending: ReadonlyArray<{ candidateId: number; toColumn: KanbanColumn }>
): KanbanColumn[] => {
 let next = cols;
 for (const { candidateId, toColumn } of pending) {
 const target = colId(toColumn);
 const from = next.find((c) => c.items.some((i) => i.candidate_id === candidateId));
 if (!from || colId(from) === target || !next.some((c) => colId(c) === target)) continue;
 const moved = from.items.find((i) => i.candidate_id === candidateId) as KanbanItem;
 next = next.map((c) => {
 if (c === from) {
 const items = c.items.filter((i) => i.candidate_id !== candidateId);
 return { ...c, items, count: items.length };
 }
 if (colId(c) !== target) return c;
 // Świeże wejście na etap = góra kolumny, jak po odświeżeniu (`compareNewestFirst`).
 const entered = { ...moved, stage: c.stage, days_in_stage: 0, moved_at: new Date().toISOString() };
 const items = [entered, ...c.items];
 return { ...c, items, count: items.length };
 });
 }
 return next;
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

/** Przełącznik widoku (kafelki/kolumny) — w pasku filtrów Tablicy. */
function BoardViewControls({
 viewMode,
 onSetViewMode,
}: {
 viewMode: KanbanViewMode | null;
 onSetViewMode: (next: KanbanViewMode) => void;
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
 days,
 hideWho = false,
}: {
 action: NextAction;
 /** „Kto ma ruch" + co zrobić (Rekrutacja v5) — `null` = sama etykieta akcji. */
 step?: CardNextStep | null;
 hidden?: boolean;
 /** Strzałka „→" na końcu wiersza. */
 advance?: React.ReactNode;
 /** Dni na etapie — „piłka” mówi, od kiedy leży (PR 4, 04.10.2026). */
 days?: number | null;
 /** Imię osoby z ruchem stoi już wiersz wyżej (dodał ją ta sama osoba). */
 hideWho?: boolean;
}) {
 if (action.kind === "none" && !step && !advance && !(days != null && days >= 1)) return null;
 const daysTone = days == null ? null : days >= 7 ? "danger" : days >= 3 ? "warning" : "neutral";
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
 {step && !hideWho ? (
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
 {/* Krótka nazwa kroku (`shortStepLabel`) — pełna w `title`; dwie linie
 zostają jako zapas dla własnych etapów szablonu. */}
 <span className="min-w-0 flex-1 line-clamp-2" title={label}>{shortStepLabel(label)}</span>
 {/* „0 d” nic nie mówi — dni od pierwszego pełnego dnia na etapie. */}
 {days != null && days >= 1 && (
  <span
   data-testid="card-days"
   className={cn(
    "shrink-0 tabular-nums text-muted-foreground",
    daysTone === "danger" && "font-semibold text-destructive",
    daysTone === "warning" && "font-semibold text-warning"
   )}
   title={`Na tym etapie od ${days} dni`}
  >
   {days} d
  </span>
 )}
 {advance}
 </div>
 );
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
 canScreen: boolean;
 /** Arkusz screeningu na tym etapie jeszcze niezapisany (17.09.2026). */
 screeningDue: boolean;
 /** Scorecard tego etapu jeszcze niezapisany (17.09.2026). */
 scorecardDue: boolean;
 onOpenScorecard: (item: KanbanItem) => void;
 /** Stawka z karty ponad budżet PLN/h rekrutacji — odznaka, nie blokada. */
 overBudget: boolean;
 /** Krytyczne bez śladu w profilu, CV i notatkach — odznaka, nie blokada. */
 criticalGaps?: string[];
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
 /** Wiersz „co dalej" — liczony z etapu i wieku karty, patrz
  *  `lib/pipeline-next-action.ts`. Przekazywany gotowy (a nie liczony tutaj),
  *  bo tylko kolumna zna grupę etapu policzoną nad CAŁĄ tablicą. */
 nextAction: NextAction;
 /** Odznaka z etapu szablonu złożonego w tę kolumnę (DZ, Cpro, prep, umowa…). */
 stageBadge?: StageBadgeKey | null;
}

/** Kroki umowy w doku („+ Umowa wysłana”), gdzie skrót „wysłana” nie wystarcza. */
const SETTABLE_BADGE_TOGGLE_LABEL: Partial<Record<StageBadgeKey, string>> = {
 contract_sent: "Umowa wysłana",
 contract_signed: "Umowa podpisana",
};

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
 /** Strzałka „→": ruch od razu z „Cofnij” albo okno „Przesuń dalej" (14.10.2026). */
 onAdvance: (item: KanbanItem) => void;
 /** Chip QC — okno QC CV. */
 onOpenQc: (item: KanbanItem) => void;
 /** Patrzący MOŻE wysłać CV do klienta (`recruitment_manage`). */
 canReviewAsDl: boolean;
 /** Patrzący przesuwa bez bramek pól (`/api/auth/me` → `skips_fill_gates`). */
 skipsFillGates: boolean;
 /** Przegląd tej rekrutacji NALEŻY do patrzącego (serwer). */
 viewerOwnsDlReview: boolean;
 /** „Przejrzyj i wyślij” — przegląd przed wysłaniem do klienta. */
 onReviewSend: (item: KanbanItem) => void;
 /** Otwórz panel osoby jak klik w kartę („Screening razem” z okienka karty). */
 onOpenPerson: (item: KanbanItem) => void;
 /** D1 (16.10.2026): „Klient zaakceptował” — okno akceptacji; `null` = szablon
  *  bez etapu „Akceptacja” albo tylko odczyt (przycisku nie ma). */
 onClientAccept: ((item: KanbanItem) => void) | null;
}
const BoardV4Context = React.createContext<BoardV4Ctx | null>(null);

/** Klucz osoby w kolejce przeglądu „po kolei” (stała funkcja — zależność haka). */
const candidateIdOf = (item: KanbanItem): number => item.candidate_id;

/** PR 6 (04.10.2026): zamiast nowej karty z kalendarzem — co zrobić w panelu. */
export const SLOTS_BY_OTHERS_MESSAGE =
 "Terminy od klienta wpisuje osoba z uprawnieniem do terminów (zwykle Delivery Lead). Gdy je doda, wybierzesz termin z kandydatem w panelu osoby.";

/** Ikony skróconych plakietek karty (`compactCardBadge`). */
const COMPACT_BADGE_ICON: Record<string, typeof Lock> = {
 source: UserPlus,
 claim: Lock,
 recommendation_card: ClipboardList,
};

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
  viewerOwnsDlReview: v4.viewerOwnsDlReview,
 };
 const badges = cardBadges(item, ctx);
 const action = v4.readOnly ? null : claimAction(item, ctx);
 if (badges.length === 0 && !action) return null;
 return (
  <>
   {badges.map((b) => {
    const compact = compactCardBadge(b);
    if (compact) {
     // Źródło, blokada 12 h i karta rekomendacji: ikona + krótki dopisek,
     // pełna treść w podpowiedzi i dla czytnika ekranu (PR 4, 04.10.2026).
     const Icon =
      b.key === "claim" && b.tone === "free" ? Unlock : (COMPACT_BADGE_ICON[b.key] ?? HelpCircle);
     return (
      <span
       key={b.key}
       data-testid={`card-badge-${b.key}`}
       className={cn(
        "inline-flex max-w-full items-center gap-0.5 truncate rounded px-1 text-[10px] font-semibold",
        CARD_BADGE_TONE_CLASS[b.tone]
       )}
       title={compact.full}
      >
       <Icon className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
       {compact.short ? <span aria-hidden="true">{compact.short}</span> : null}
       <span className="sr-only">{b.label}</span>
      </span>
     );
    }
    return (
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
    );
   })}
   {action && (() => {
    // Osoba od systemu (23.10.2026): „Biorę” to decyzja „Dzwonię”.
    const takeLabel =
     action === "takeover"
      ? "Przejmij"
      : item.entry_source === "system" && !item.entry_autofill?.decided
       ? "Dzwonię"
       : "Biorę";
    return (
     <button
      type="button"
      onClick={(e) => {
       e.stopPropagation();
       e.preventDefault();
       v4.onTake(item);
      }}
      disabled={v4.takingIds.has(item.id)}
      className="inline-flex items-center rounded border border-primary/40 px-1.5 text-[10px] font-semibold text-primary hover:bg-primary/10 disabled:opacity-50"
      aria-label={`${takeLabel} ${fullName} — na 12 h`}
     >
      {takeLabel}
     </button>
    );
   })()}
  </>
 );
}

const CandidateKanbanCard = memo(function CandidateKanbanCard({
 item,
 jobId,
 selected,
 onToggleSelect,
 onOpenScreening,
 canScreen,
 screeningDue,
 scorecardDue,
 onOpenScorecard,
 overBudget,
 criticalGaps,
 matchScore,
 scoresLoading,
 onRemoveFromRecruitment,
 contactFeatureEnabled,
 desktopOverview,
 readOnly,
 onOpenDock,
 nextAction,
 stageBadge = null,
}: CardProps) {
 const fullName = `${item.name ??""} ${item.lastname ??""}`.trim() ||"Kandydat";
 // Rekrutacja v5: kolumna Tablicy karty, „kto ma ruch", strzałka „→" i chip QC.
 const v5 = React.useContext(BoardV4Context);
 const boardKey = v5?.columnByItemId.get(item.id) ?? null;
 const nextStep = v5
 ? cardNextStep(nextAction, item, { column: boardKey, cproEnabled: v5.cproEnabled, stageBadge, viewerId: v5.viewerId, viewerOwnsDlReview: v5.viewerOwnsDlReview })
 : null;
 const nextColumnLabel = v5 && !readOnly ? v5.nextColumnLabel(item) : null;
 // „Do wysłania do klienta” (13.10.2026): kto może wysłać, dostaje na gotowej
 // karcie przycisk przeglądu zamiast strzałki — strzałka otwierała okno
 // „Przesuń dalej”, a dopiero z niego przegląd.
 const reviewSend = Boolean(
 v5 && !readOnly && v5.canReviewAsDl && isReadyForDlSend(item, boardKey, stageBadge === "cpro")
 );
 const forwardGap = nextColumnLabel
 ? knownForwardGap(item, boardKey, { skipsFillGates: v5?.skipsFillGates })
 : null;
 const qc = boardKey === "cv_qc" ? qcChip(item) : null;
 const cvBadge = cvStateBadge(item, boardKey);
 // 22.10.2026: karta przeszła dalej mimo braków, bo przesunął ją DL.
 const skippedBadge = requirementsSkippedBadge(item, boardKey);
 const normalizedMatchScore =
 typeof matchScore === "number" && Number.isFinite(matchScore)
 ? Math.max(0, Math.min(100, Math.round(matchScore)))
 : null;
 const detailsId = `kanban-candidate-details-${item.id}`;
 const hasAddedByName = Boolean(item.added_to_job_by_name?.trim());
 const addedByDisplayName = item.added_to_job_by_name?.trim() || "brak danych";
 // Od „Zweryfikowanego” karta pokazuje osobę, która zweryfikowała (20.10.2026).
 const owner = cardOwner(item, boardKey);
 const hasOwnerName = owner.name != null;
 const ownerShortName = cardShortName(owner.name) ?? "Brak danych";
 // Awatar WŁAŚCICIELA karty, nie kandydata — makieta kroku 04 pyta „czyja to
 // karta", a nazwisko kandydata i tak stoi wiersz wyżej.
 const ownerInitials = owner.name
 ? owner.name
 .split(/\s+/)
 .map((w) => w[0])
 .slice(0, 2)
 .join("")
 .toUpperCase()
 : "?";
 const addedLine = item.entry_source === "system"
 ? `Dodał system („Nowi” na 20)${
 item.added_to_job_at ? ` · ${formatDate(item.added_to_job_at)}` : ""
 }`
 : hasAddedByName
 ? `Dodano do rekrutacji przez: ${addedByDisplayName}${
 item.added_to_job_at ? ` · ${formatDate(item.added_to_job_at)}` : ""
 }`
 : `Brak danych o osobie dodającej${
 item.added_to_job_at ? ` · dodano ${formatDate(item.added_to_job_at)}` : ""
 }`;
 const addedAttribution =
 owner.role === "assigned"
 ? `Prowadzi: ${owner.name}${
 item.owner_assigned_by_name ? ` · przypisał(a) ${item.owner_assigned_by_name}` : ""
 }\n${addedLine}`
 : owner.role === "taken"
 ? `Wziął(-ęła) „Biorę”: ${owner.name}\n${addedLine}`
 : owner.role === "verified"
 ? `Zweryfikował(a): ${owner.name}${
 item.verified_at ? ` · ${formatDate(item.verified_at)}` : ""
 }\n${addedLine}`
 : addedLine;
 // Konflikty z klientem i czarna lista: serwer niesie je w `warnings`,
 // a karta do 12.10.2026 rysowała tylko weto HM i „ponad budżet”.
 const warningBadges = eligibilityWarningBadges(item.warnings, item.employment_marker);
 const criticalGap = criticalGapBadge(criticalGaps);
 // Odejście z firmy (28.10.2026): para osoby z wyłączonym kontem, którą
 // domyka Delivery Lead — „Prowadzi” zostaje przy osobie, która odeszła.
 const care =
 item.care_user_id != null && item.care_departed_name
 ? cardCareLabel(item.care_departed_name, item.care_user_id, item.care_user_name, v5?.viewerId ?? null)
 : null;
 // Kolumny zamknięte (19.10.2026): powód widać bez otwierania karty, komentarz
 // i kto zamknął — w dymku i w opisie karty dla czytnika.
 const closed = closedReason(item);
 const closedSummary = closed
 ? `${closed.verb}: ${closed.reasonText}${closed.comment ? ` — ${closed.comment}` : ""}`
 : null;
 const closedTitle = closed
 ? [
 closedSummary,
 [closed.by, closed.at ? formatDate(closed.at) : null].filter(Boolean).join(" · ") || null,
 ]
 .filter(Boolean)
 .join("\n")
 : undefined;
 const accessibleDetails = [
 overBudget ? "Stawka ponad budżet rekrutacji." : null,
 criticalGap ? criticalGap.title : null,
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
 `${addedAttribution.replace("\n", ". ")}.`,
 closedSummary ? `${closedSummary}.` : null,
 item.hm_veto ? "Ostrzeżenie: weto hiring managera." : null,
 ...warningBadges.map((w) => `Ostrzeżenie: ${w.label}.`),
 care ? `${care.departed}, ${care.caretaker}.` : null,
 item.employment_marker ? `${markerLabel(item.employment_marker)}.` : null,
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
 data-champion={item.is_champion ? "true" : undefined}
 onClick={handleCardClick}
 className={cn("group relative rounded-lg bg-card border border-border transition-all","hover:shadow-xs hover:border-primary/40",
 // Champion (D3, 15.10.2026): złota obwódka; zaznaczenie i weto HM wygrywają.
 item.is_champion &&"border-medal-gold-foreground/40",
 selected &&"ring-2 ring-primary border-primary",
 // Makieta kroku 04 daje karcie ~9 px oddechu; stare `p-5` (20 px) zjadało
 // przy 176 px kolumny ćwierć jej szerokości na sam padding.
 "p-3",
 desktopOverview &&"xl:pointer-fine:min-h-[68px] xl:pointer-fine:rounded-md xl:pointer-fine:p-1 xl:pointer-fine:pb-6 xl:pointer-fine:pt-6",
 // Świadomie bez grayscale/opacity — czytałoby się jako „nieaktywny". Ten
 // kandydat jest aktywny; weto to ostrzeżenie (17.09.2026), nie blokada.
 item.hm_veto &&"border-destructive/50"
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
 kończy się 20 px od lewej krawędzi karty, a padding karty to 12 px.
 Stare `pl-5` zostawiało nazwisku 64 z 158 px
 karty — stąd „Wojcie/ch" łamane w środku wyrazu. */}
 <div className={cn("flex items-start gap-2", "pl-2", desktopOverview &&"xl:pointer-fine:items-center xl:pointer-fine:gap-1 xl:pointer-fine:pl-0")}>
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
 "text-[13px] leading-snug",
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
 (40 px) zabierał ćwierć tej szerokości nazwisku obok. */}
 <ScoreRing score={normalizedMatchScore} density="compact" />
 </div>
 )}
 </div>

 {/* D2 (16.10.2026): akceptacja klienta — kiedy i kto zaznaczył. Tylko
 w kolumnie „Akceptacja i umowa”; karta cofnięta do rozmowy jej nie ma. */}
 {boardKey === "contract" && item.client_acceptance && (
 <p
 data-testid="card-client-acceptance"
 title={acceptanceTitle(item.client_acceptance) ?? undefined}
 className={cn(
 // Dwie linie zamiast ucinania: przy 1280 px „· Olga W.” spadało za brzeg.
 "mt-1 line-clamp-2 break-words rounded px-1.5 py-0.5 text-[10.5px] font-semibold leading-snug bg-success-muted text-success-muted-foreground",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 >
 {acceptanceLine(item.client_acceptance)}
 </p>
 )}

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
 hasOwnerName
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
 !hasOwnerName && "text-warning",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 aria-hidden="true"
 >
 {ownerShortName}
 </span>
 {desktopOverview && (
 <span className="hidden truncate xl:pointer-fine:inline" aria-hidden="true">
 R: {ownerShortName}
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
 {criticalGap && (
 <span
 data-testid="card-critical-gap"
 className={cn(
 "inline-flex min-w-0 max-w-full items-center gap-0.5 rounded px-1 text-[10px] font-semibold uppercase tracking-wide bg-warning/15 text-warning",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={criticalGap.title}
 >
 <AlertTriangle className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
 <span className="truncate" aria-hidden="true">{criticalGap.label}</span>
 </span>
 )}
 {warningBadges.map((w) => (
 <span
 key={w.code}
 data-testid={`card-warning-${w.code}`}
 className={cn(
 "inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-semibold uppercase tracking-wide",
 w.tone === "danger" ? "bg-destructive/10 text-destructive" : "bg-warning/15 text-warning",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={w.title}
 >
 <AlertTriangle className="h-2.5 w-2.5" aria-hidden="true" />
 <span aria-hidden="true">{w.label}</span>
 </span>
 ))}
 {care && (
 <span
 data-testid="card-departed-care"
 className={cn(
 "inline-flex min-w-0 max-w-full items-center gap-0.5 rounded px-1 text-[10px] font-semibold bg-muted text-foreground",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={`${care.departed} (odejście z firmy) — ${care.caretaker}. „Prowadzi” bez zmian: nie liczy się do Ligi, KPI ani premii.`}
 >
 <UserX className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
 <span className="truncate" aria-hidden="true">{care.caretaker}</span>
 </span>
 )}
 {impliedBadges(cardStageBadge(item, stageBadge))
 .filter((badge) => !(badge === "acceptance" && boardKey === "contract" && item.client_acceptance))
 .map((badge) => (
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
 {showsOtherJobsChip(item, boardKey) && (
 <OtherJobsChip
 item={item}
 fullName={fullName}
 className={cn(desktopOverview && "xl:pointer-fine:hidden")}
 onScreenTogether={
 v5 && !readOnly
 ? (jobIds) => {
 useJointScreeningIntent.getState().setIntent(item.candidate_id, jobIds);
 v5.onOpenPerson(item);
 }
 : undefined
 }
 />
 )}
 <CardV4Badges item={item} fullName={fullName} stageBadge={stageBadge} />
 {/* Osobny wiersz na końcu: u kogo osoba u nas pracuje i do kiedy.
 Treść dla czytnika jest w opisie karty (`accessibleDetails`). */}
 {item.employment_marker && (
 <EmploymentPill
 marker={item.employment_marker}
 appearance="text"
 label={{ clients: "count", date: "short" }}
 aria-hidden="true"
 data-testid="card-employment"
 className={cn("basis-full text-[10.5px]", desktopOverview && "xl:pointer-fine:hidden")}
 />
 )}
 {/* Stan CV firmowego (14.10.2026, `cvStateBadge` — ta sama reguła
 co wiersz tabeli): automat pisze CV, „CV gotowe · QC: N do poprawy” /
 „bez uwag” po QC na „Zweryfikowanym”, „CV gotowe w tle” przed QC. */}
 {skippedBadge && (
 <span
 data-testid="card-requirements-skipped"
 className={cn(
 "inline-flex items-center rounded px-1 text-[10px] font-semibold",
 CARD_BADGE_TONE_CLASS[skippedBadge.tone],
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={skippedBadge.title}
 >
 {skippedBadge.label}
 </span>
 )}
 {cvBadge && (
 <span
 data-testid="card-cv-state"
 className={cn(
 "inline-flex items-center rounded px-1 text-[10px] font-semibold",
 CARD_BADGE_TONE_CLASS[cvBadge.tone],
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 title={cvBadge.title}
 >
 {cvBadge.label}
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
 </div>

 {contactFeatureEnabled ? (
 <div className={cn(desktopOverview &&"xl:pointer-fine:sr-only")}>
 <ContactStatusBadge contactCase={item.contact_case} className="mt-1" />
 </div>
 ) : null}

 {closed ? (
 <p
 data-testid="card-closed-reason"
 data-tone={closed.tone}
 title={closedTitle}
 aria-hidden="true"
 className={cn(
 "mt-1 flex min-w-0 items-center gap-1 text-[11px] leading-snug",
 closed.tone === "danger" ? "text-destructive" : "text-muted-foreground"
 )}
 >
 {closed.kind === "withdrawn" ? (
 <LogOut className="h-3 w-3 shrink-0" aria-hidden="true" />
 ) : (
 <Ban className="h-3 w-3 shrink-0" aria-hidden="true" />
 )}
 <span className="truncate">{closed.reason ?? "Powód nie zapisany"}</span>
 </p>
 ) : null}

 {/* Wiersz 3 makiety: kto ma ruch, co zrobić i strzałka „→" (v5). */}
 <NextActionRow
 action={nextAction}
 step={nextStep}
 days={item.days_in_stage ?? null}
 hidden={desktopOverview}
 // Osoba z karty (dodała albo zweryfikowała) ma ruch — jej imię stoi wiersz wyżej
 // (dawniej „Integracje:” dwa razy na jednej karcie, 04.10.2026).
 hideWho={Boolean(nextStep && !nextStep.mine && hasOwnerName && nextStep.who === ownerShortName)}
 advance={
 nextColumnLabel && v5 && !reviewSend ? (
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

 {/* D1 (16.10.2026): „Klient zaakceptował” na karcie po rozmowie u klienta —
 okno akceptacji (data, debrief, kto dostanie dzwonek), potem ruch. */}
 {boardKey === "client_interview" && v5?.onClientAccept && !readOnly && (
 <button
 type="button"
 data-testid="card-client-accept"
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 v5.onClientAccept?.(item);
 }}
 aria-label={`Klient zaakceptował: ${fullName}`}
 className={cn(
 "mt-1.5 flex h-7 w-full items-center justify-center gap-1 rounded-md border border-success/40 bg-success-muted text-[11px] font-semibold text-success-muted-foreground transition-colors hover:bg-success/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9",
 desktopOverview && "xl:pointer-fine:hidden"
 )}
 >
 <CircleCheck className="h-3.5 w-3.5" aria-hidden="true" />
 Klient zaakceptował
 </button>
 )}

 {/* „Przejrzyj i wyślij” — własny wiersz pod „kto ma ruch” (jak pigułka
 Screeningu niżej, nigdy `absolute`). Wypełniony u Delivery Leada tej
 rekrutacji, obrysowany u pozostałych z prawem wysyłki. */}
 {reviewSend && v5 && (
 <div className={cn("mt-1 flex justify-end", desktopOverview && "xl:pointer-fine:hidden")}>
 <button
 type="button"
 data-testid="card-review-send"
 data-owner={v5.viewerOwnsDlReview ? "true" : "false"}
 onClick={(e) => {
 e.stopPropagation();
 e.preventDefault();
 v5.onReviewSend(item);
 }}
 aria-label={`${v5.cproEnabled ? "Przejrzyj i zaakceptuj do Cpro" : "Przejrzyj i wyślij"}: ${fullName}`}
 className={cn(
 "inline-flex max-w-full items-center rounded border px-1.5 text-[10px] font-semibold transition-colors pointer-coarse:min-h-8 pointer-coarse:px-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
 v5.viewerOwnsDlReview
 ? "border-primary bg-primary text-primary-foreground hover:bg-primary/90"
 : "border-primary/40 text-primary hover:bg-primary/10"
 )}
 >
 {/* Nordea (14.10.2026): nic nie idzie do klienta — przegląd kończy
 akceptacja do kolejki Cpro. */}
 <span className="truncate">{v5.cproEnabled ? CPRO_REVIEW_LABEL : "Przejrzyj i wyślij"}</span>
 </button>
 </div>
 )}

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
 "h-6 w-6",
 desktopOverview &&"xl:pointer-fine:h-6 xl:pointer-fine:w-6",
 "top-1",
 desktopOverview &&"xl:pointer-fine:bottom-0 xl:pointer-fine:left-0 xl:pointer-fine:right-auto xl:pointer-fine:top-auto"
 )}
 title="Usuń kandydata z tej rekrutacji"
 aria-label={`Usuń ${fullName} z rekrutacji`}
 >
 <Trash2 className="h-3.5 w-3.5" />
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
 scoreMap?: Map<number, number>;
 criticalGapMap?: Map<number, string[]>;
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
 /** Grupa etapu policzona nad CAŁĄ tablicą — bez niej własny etap wewnętrzny
  *  po screeningu byłby nie do odróżnienia od etapu wejściowego. */
 group?: PipelineGroupKey;
 /** SLA klienta w dniach roboczych (karta klienta) — `null` = nie ustawiono. */
 slaDays: number | null;
 /** Nagłówek kolumny zamiast nazwy etapu (kolumna „Do przejrzenia"). */
 titleOverride?: string;
 /** Odznaki kart z etapów złożonych w tę kolumnę (klucz: id karty). */
 badgeByItemId?: ReadonlyMap<number, StageBadgeKey>;
 /** Numer kroku procesu (1–8) w nagłówku kolumny Tablicy; `null` = bez numeru. */
 step?: number | null;
 /** „Co tu robisz" pod nazwą kolumny (`lib/board-column-purpose.ts`);
  *  `null` = własny etap szablonu — zostaje dawna linia SLA. */
 purpose?: string | null;
 /** Akcja w nagłówku kolumny (D10: „Porównaj (N)” w „QC CV” dla DL). */
 headerAction?: React.ReactNode;
 /** Filtr „Kto dodał” (14.10.2026): liczba osób w kolumnie BEZ filtra. Gdy
  *  filtr coś schował, licznik mówi „N z M”. Bez filtra — `undefined`. */
 totalCount?: number;
 /** Filtr schował wszystkich z tej kolumny: napis i „Pokaż wszystkich (M)”. */
 filterEmpty?: { text: string; onShowAll: () => void } | null;
 /** Zamiast „co tu robisz” w drugiej linii nagłówka („Przejrzyj po kolei (N)”
  *  w „QC CV” u Delivery Leada tej rekrutacji) — ta sama linia, bez dodatkowej
  *  wysokości. */
 purposeAction?: React.ReactNode;
 /** Trzecia linia nagłówka: liczniki kroków w „Akceptacja i umowa” (D2). */
 headerExtra?: React.ReactNode;
}

/** Liczniki kroków w nagłówku kolumny „Akceptacja i umowa” (D2, 16.10.2026). */
function ContractStepChips({ counts }: { counts: ContractStepCounts }) {
 const chips: Array<{ key: string; label: string; n: number; tone: string }> = [
 { key: "accepted", label: "Zaakceptowani", n: counts.accepted, tone: "border-success/40 bg-success-muted text-success-muted-foreground" },
 { key: "sent", label: "Umowa wysłana", n: counts.sent, tone: "border-border bg-card text-muted-foreground" },
 { key: "signed", label: "Podpisana", n: counts.signed, tone: "border-border bg-card text-muted-foreground" },
 ];
 return (
 <>
 {chips.map((c) => (
 <span
 key={c.key}
 data-testid={`contract-step-${c.key}`}
 className={cn("inline-flex items-center gap-1 rounded-full border px-1.5 text-[10px] font-medium leading-4", c.tone)}
 >
 {c.label} <span className="font-semibold tabular-nums">{c.n}</span>
 </span>
 ))}
 </>
 );
}

const KanbanColumnV2 = memo(function KanbanColumnV2({
 col,
 jobId,
 selectedIds,
 onToggleSelect,
 onOpenScreening,
 scoreMap,
 criticalGapMap,
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
 group,
 slaDays,
 titleOverride,
 badgeByItemId,
 step = null,
 purpose = null,
 headerAction = null,
 purposeAction = null,
 headerExtra = null,
 totalCount,
 filterEmpty = null,
}: ColProps) {
 const headerCount = col.count;
 // Kolumna pusta przez filtr „Kto dodał” nie jest wąska — mieści napis
 // „Brak osób dodanych przez…” i „Pokaż wszystkich”.
 const peopleCount = totalCount ?? headerCount;
 const hiddenByFilter = totalCount != null && totalCount !== headerCount;
 const countText = hiddenByFilter ? `${headerCount} z ${totalCount}` : String(headerCount);
 // Pusta kolumna jest WĄSKA (24.09.2026): przy 1440 px osiem kolumn mieści się
 // bez przewijania, gdy połowa jest pusta. Tylko na desktopie z myszą i poza
 // trybem kafelków (tam kolumny i tak dzielą szerokość); `droppableId`
 // i indeksy kart się nie zmieniają, więc upuszczanie działa jak dotąd.
 const narrow = peopleCount === 0;
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
 aria-label={`${titleOverride ?? columnLabel(col)}, liczba kandydatów: ${countText}`}
 className={cn(
 "flex w-[calc((100%-1.5rem)/3)] min-w-[17rem] shrink-0 snap-start flex-col rounded-lg border border-border bg-background/60 sm:min-w-[19rem]",
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
 !desktopOverview && narrow &&"xl:pointer-fine:w-24 xl:pointer-fine:min-w-24 xl:pointer-fine:basis-24 xl:pointer-fine:grow-0"
 )}
 data-narrow={narrow && !desktopOverview ? "true" : undefined}
 >
 <div className={cn("sticky top-0 z-10 rounded-t-lg bg-background/95 backdrop-blur-xs border-b border-border flex items-center gap-2", "px-3 py-2", desktopOverview &&"xl:pointer-fine:min-h-14 xl:pointer-fine:flex-col xl:pointer-fine:items-stretch xl:pointer-fine:gap-1 xl:pointer-fine:px-1 xl:pointer-fine:py-1.5", !desktopOverview && narrow &&"xl:pointer-fine:flex-wrap xl:pointer-fine:gap-1 xl:pointer-fine:px-2")}>
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
 {/* Nazwa etapu: jeden rozmiar i jedna linia w kolumnie z kartami
 (04.10.2026 — przy 1280 px duża nazwa łamała się na „Zweryfi-kowany”
 i „CV wysłane”); pełna nazwa w `title`. Wąska pusta kolumna (96 px) dalej
 zawija nazwę, także w środku słowa (dzielenie po polsku, `lang="pl"`,
 audyt 24.09.2026). */}
 <h3 className={cn("text-foreground flex-1 min-w-0 truncate leading-tight", "text-[13px] font-semibold", desktopOverview &&"xl:pointer-fine:line-clamp-2 xl:pointer-fine:whitespace-normal xl:pointer-fine:text-center xl:pointer-fine:text-[10px] xl:pointer-fine:leading-tight xl:pointer-fine:[overflow-wrap:anywhere]", !desktopOverview && narrow &&"xl:pointer-fine:order-last xl:pointer-fine:basis-full xl:pointer-fine:whitespace-normal xl:pointer-fine:text-xs xl:pointer-fine:line-clamp-3 xl:pointer-fine:hyphens-auto xl:pointer-fine:[overflow-wrap:anywhere]")} title={titleOverride ?? columnLabel(col)} lang="pl">
 {titleOverride ?? columnLabel(col)}
 </h3>
 <Badge size="sm" variant={headerCount > 0 ?"soft" :"outline"} className={cn("tabular-nums", desktopOverview &&"xl:pointer-fine:h-4 xl:pointer-fine:min-w-4 xl:pointer-fine:self-center xl:pointer-fine:px-1 xl:pointer-fine:text-[10px]")} data-testid="column-count">
 {countText}
 </Badge>
 {headerAction}
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
 {purposeAction ?? (
 <span
 data-column-purpose={purpose ? "true" : undefined}
 className={cn(
 "min-w-0",
 // Wąska pusta kolumna (96 px) potrzebuje trzech linii na „Prep → rozmowa → telefon”;
 // w kolumnie z kartami jedna linia, pełny tekst w `title` (04.10.2026).
 purpose ? cn(narrow ? "line-clamp-3" : "truncate", "font-medium leading-snug text-foreground/80") : "truncate",
 )}
 title={purpose ?? undefined}
 >
 {purpose ?? slaHint.left}
 </span>
 )}
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
 {headerExtra && (
 <div
 data-testid="column-header-extra"
 className={cn("flex flex-wrap gap-1 border-b border-border px-3 py-1", desktopOverview && "xl:pointer-fine:hidden")}
 >
 {headerExtra}
 </div>
 )}

 <Droppable droppableId={dropId} isDropDisabled={noDrop}>
 {(provided, snapshot) => (
 <div
 ref={provided.innerRef}
 {...provided.droppableProps}
 className={cn(
 // Kolumna wypełnia wysokość pasa kolumn (flex-1) — czyli najdłuższej
 // kolumny, nie tylko okna boardu — a sam board (przodek) jest
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
 criticalGaps={criticalGapMap?.get(item.candidate_id)}
 matchScore={scoreMap?.get(item.candidate_id)}
 scoresLoading={scoresLoading}
 onRemoveFromRecruitment={onRemoveFromRecruitment}
 contactFeatureEnabled={contactFeatureEnabled}
 desktopOverview={desktopOverview}
 readOnly={readOnly}
 onOpenDock={onOpenDock}
 nextAction={nextActions[index]}
 stageBadge={badgeByItemId?.get(item.id) ?? null}
 />
 </div>
 )}
 </Draggable>
 ))}
 {/* Ramka „upuść tutaj” pojawia się dopiero w trakcie przeciągania
 karty (`data-dragging` na korzeniu tablicy) — w spoczynku pusta
 kolumna jest po prostu pusta (04.10.2026). */}
 {filterEmpty && headerCount === 0 ? (
 <div data-testid="column-filter-empty" className="space-y-1 px-1 py-3 text-xs text-muted-foreground">
 <p>{filterEmpty.text}</p>
 <button
 type="button"
 onClick={filterEmpty.onShowAll}
 className="font-semibold text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
 >
 Pokaż wszystkich ({peopleCount})
 </button>
 </div>
 ) : null}
 {peopleCount === 0 && !snapshot.isDraggingOver && !readOnly && !noDrop && (
 <div
 aria-hidden="true"
 data-testid="column-drop-hint"
 className={cn(
 "hidden rounded-md border border-dashed border-border px-1 py-6 text-center text-[10px] text-muted-foreground group-data-[dragging=true]/board:block",
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

/** Kolumna z kartami, które przechodzą filtr „Kto dodał” (14.10.2026). */
function withAddedByFilter<C extends { items: KanbanItem[]; count: number }>(
 col: C,
 filter: AddedByFilter
): C {
 if (filter.kind === "all") return col;
 const items = col.items.filter((item) => matchesAddedBy(item, filter));
 return { ...col, items, count: items.length };
}

// Dół boardu: pb-4 kontenera (16px) + dolny padding <main> (24px). Tyle zostawiamy
// pod kolumnami, żeby strona nie scrollowała się w pionie pod pipeline.
const BOARD_BOTTOM_GAP = 40;
// Podłoga wysokości kolumny na małych ekranach (min-height wygrywa z height).
const MIN_COLUMN_HEIGHT = 280;
// `p-4` obszaru treści powłoki (góra + dół) — patrz pomiar planszy na telefonie.
const MOBILE_MAIN_PADDING_Y = 32;

export function KanbanBoardV2({ columns, jobId, jobTitle, scoreMap, criticalGapMap, scoresLoading, headerCollapsed, offTemplate, readOnly = false, clientId = null, initialDockCandidateId = null, onInitialDockHandled, initialDockOpensReview = false, onDockCandidateChange, workbenchContext, kanbanQueryState, initialWorkbench = null, onInitialWorkbenchHandled, cproEnabled = false, viewerOwnsDlReview = false, renderAbove, addedBy = ADDED_BY_ALL, onAddedByChange, closedJob = null }: KanbanBoardV2Props) {
 // Widok tablicy: kafelki ↔ kolumny. Reguła automatyczna (szeroki szablon
 // otwiera się kafelkowo) jest WARTOŚCIĄ DOMYŚLNĄ, wybór użytkownika ją
 // nadpisuje i jest pamiętany — patrz `lib/kanban-view-preferences.ts`.
 const [viewPreference, setViewPreference] = useKanbanViewPreference();
 const queryClient = useQueryClient();
 const contactFeature = useCandidateContactFeature();
 const { showSuccess, showError, showInfo, showActionToast } = useToast();
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
 const allDisplayCols = useMemo(
 () =>
 boardFold.columns.map((f) => ({ ...f.host, items: f.items, count: f.count })),
 [boardFold]
 );
 // Filtr „Kto dodał” (14.10.2026) chowa karty w kolumnach w toku. Liczony
 // PRZED przeciąganiem: indeksy kart w kolumnie to indeksy widocznej listy.
 // `count` = widoczne karty, liczba bez filtra — `totalCountByColId`.
 const displayCols = useMemo(
 () => allDisplayCols.map((c) => withAddedByFilter(c, addedBy)),
 [allDisplayCols, addedBy]
 );
 const boardKeyByColId = useMemo(() => {
 const m = new Map<string, BoardColumnKey>();
 for (const f of boardFold.columns) if (f.key) m.set(colId(f.host), f.key);
 return m;
 }, [boardFold]);
 // Nordea: kolumna „Do Cpro” (kolejka osoby od Cpro) — ten sam klucz
 // `cv_qc` co „QC CV”, ale bez przeglądu DL i bez numeru kroku.
 const cproQueueColIds = useMemo(
 () => new Set(boardFold.columns.filter((f) => f.cproQueue).map((f) => colId(f.host))),
 [boardFold]
 );
 const boardLabelByColId = useMemo(() => {
 const m = new Map<string, string>();
 for (const f of boardFold.columns) m.set(colId(f.host), f.label);
 return m;
 }, [boardFold]);
 // D2 (16.10.2026): liczniki kroków w nagłówku „Akceptacja i umowa” — ile
 // osób po akceptacji, z wysłaną i z podpisaną umową (bez filtra „Kto dodał”).
 const contractCountsByColId = useMemo(() => {
 const m = new Map<string, ContractStepCounts>();
 for (const f of boardFold.columns) {
 if (f.key !== "contract" || f.items.length === 0) continue;
 m.set(colId(f.host), contractStepCounts(f.items.map((it) => boardFold.badgeByItemId.get(it.id))));
 }
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
 const authUser = useAuthStore((st) => st.user);
 const isDlOrHor =
 hasRole(authUser, "admin") ||
 hasRole(authUser, "delivery_lead") ||
 hasRole(authUser, "head_of_recruitment");
 // Poza klientem z kolejką Cpro CV wysyła osoba z uprawnieniem „Rekrutacje:
 // zakładanie, zamykanie, wysyłka CV do klienta” (lustro
 // `pipeline_move_rules.assert_client_send_allowed`) — ona dostaje pełny
 // przegląd przed wysyłką zamiast okna „Przesuń dalej”.
 const canReviewAsDl = hasPermission(authUser, "recruitment_manage");
 // Delivery Lead przesuwa bez bramek pól (22.10.2026) tylko wtedy, gdy serwer
 // też go przepuszcza: flaga z `/api/auth/me` liczy uprawnienie i wyłącznik
 // `DL_SKIPS_FILL_GATES` (audyt 22.10.2026, F109). Przy wyłączonym DL ma
 // szarą strzałkę, okno minimum i okno stawki jak rekruter.
 const skipsFillGates = authUser?.skips_fill_gates === true;
 // Terminy od klienta dodaje DL (lustro bramki `interview_slots`: admin, HoR,
 // DL z członkostwem — serwer i tak sprawdza członkostwo).
 const canAddClientSlots = !readOnly && isDlOrHor;
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
 // D1 (16.10.2026): etap „Akceptacja” szablonu — cel „Klient zaakceptował”;
 // gospodarz „Rozmowy u klienta” — cel „Cofnij akceptację klienta”.
 const acceptanceStageCol = useMemo(
 () =>
 boardFold.columns
 .find((f) => f.key === "contract")
 ?.members.find((c) => placeStage(c).badge === "acceptance") ?? null,
 [boardFold]
 );
 const clientInterviewHost = useMemo(
 () => boardFold.columns.find((f) => f.key === "client_interview")?.host ?? null,
 [boardFold]
 );
 // Okno „Klient zaakceptował”: osoba i notatka wpisana już w werdykcie
 // („Akceptuje” z zakładki „Rozmowy”).
 const [acceptFor, setAcceptFor] = useState<{ item: KanbanItem; note: string | null } | null>(null);
 const openClientAccept = useCallback(
 (item: KanbanItem, note?: string | null) => setAcceptFor({ item, note: note ?? null }),
 []
 );
 const onClientAccept = acceptanceStageCol && !readOnly ? openClientAccept : null;
 // Każdy ruch z „Rozmowy u klienta” na „Akceptację i umowę” (strzałka,
 // przeciągnięcie, „Następny etap”, „Inny etap…”) idzie przez to samo okno —
 // jedna droga akceptacji zamiast dwóch przycisków obok siebie.
 const acceptInsteadOfMove = useCallback(
 (item: KanbanItem, dst: KanbanColumn): boolean => {
 if (!onClientAccept || columnByItemId.get(item.id) !== "client_interview") return false;
 const fold = boardFold.columns.find((f) => f.host === dst || f.members.includes(dst));
 if (fold?.key !== "contract") return false;
 onClientAccept(item);
 return true;
 },
 [onClientAccept, columnByItemId, boardFold]
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
 // `eventId = null` — rozmowy nie ma w kalendarzu NEXUSA; okno pyta, kiedy
 // była, i zapisuje pytania pary (20.10.2026).
 const [debriefFor, setDebriefFor] = useState<{
 eventId: number | null;
 candidateId: number;
 name: string;
 } | null>(null);
 const openMoveNext = useCallback(
 (item: KanbanItem, srcColId: string, target: KanbanColumn) => {
 if (acceptInsteadOfMove(item, target)) return;
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
 [boardFold, columnByItemId, acceptInsteadOfMove]
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
 // Strzałka „→” na karcie (D7, 14.10.2026) — ciało niżej, po `usePipelineMove`.
 const arrowAdvanceRef = useRef<(item: KanbanItem) => void>(() => undefined);
 const onArrowAdvance = useCallback((item: KanbanItem) => arrowAdvanceRef.current(item), []);
 const onOpenQc = useCallback((item: KanbanItem) => setQcStageId(item.id), []);
 // Przegląd przed wysłaniem do klienta (`openDlReviewIfSending`) powstaje
 // niżej — potrzebuje kolumn zamkniętych; karta i przeciągnięcie wołają go
 // przez ref.
 const openDlReviewRef = useRef<(item: KanbanItem, dst: KanbanColumn) => boolean>(() => false);
 // Gospodarz kolumny „CV wysłane” — cel wysyłki z przeglądu.
 const cvSentHost = useMemo(
 () => boardFold.columns.find((f) => f.key === "cv_sent")?.host ?? null,
 [boardFold]
 );
 // U Nordei przegląd kończy akceptacja do kolejki Cpro (13.10.2026): celem
 // jest etap „Wysłać do Cpro” szablonu (w tej samej kolumnie „QC CV”).
 const cproStageCol = useMemo(
 () => (cproEnabled ? (stageCols.find((c) => isCproStageName(c.name)) ?? null) : null),
 [cproEnabled, stageCols]
 );
 const dlSendTarget = cproEnabled ? (cproStageCol ?? cvSentHost) : cvSentHost;
 // „Przejrzyj i wyślij” na karcie: od razu przegląd. Gdy przegląd się nie
 // należy (np. QC zdążyło spaść) — okno „Przesuń dalej”, jak strzałka.
 const onReviewSend = useCallback(
 (item: KanbanItem) => {
 if (dlSendTarget && openDlReviewRef.current(item, dlSendTarget)) return;
 onAdvance(item);
 },
 [dlSendTarget, onAdvance]
 );
 // „Przejrzyj po kolei” (13.10.2026): gotowe karty „QC CV”, najdłużej
 // czekające pierwsze. Kolejka trzyma osoby po `candidate_id` — id wiersza
 // etapu zmienia się przy każdym ruchu.
 const dlReadyItems = useMemo(
 () =>
 dlSendQueue(
 boardFold.columns.find((f) => f.key === "cv_qc")?.items ?? [],
 (item) => boardFold.badgeByItemId.get(item.id) === "cpro",
 new Date()
 ),
 [boardFold]
 );
 const {
 active: sequenceActive,
 current: sequenceCurrent,
 position: sequencePosition,
 total: sequenceTotal,
 start: startSequence,
 advance: advanceSequence,
 skip: skipSequence,
 skipped: sequenceSkipped,
 finish: finishSequence,
 } = useReviewSequence(dlReadyItems, candidateIdOf);
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
 // `openDock` powstaje niżej (zależy od kolumn i warsztatu) — kontekst karty
 // woła go przez ref, żeby „Screening razem” z okienka karty otwierał panel.
 const openDockRef = useRef<((item: KanbanItem) => void) | null>(null);
 const openPersonViaRef = useCallback((item: KanbanItem) => openDockRef.current?.(item), []);
 const boardV4 = useMemo<BoardV4Ctx>(
 () => ({
 columnByItemId,
 cproEnabled,
 viewerId: authUser?.id ?? null,
 readOnly,
 takingIds,
 onTake: takeCandidate,
 nextColumnLabel,
 onAdvance: onArrowAdvance,
 onOpenQc,
 canReviewAsDl,
 skipsFillGates,
 viewerOwnsDlReview,
 onReviewSend,
 onOpenPerson: openPersonViaRef,
 onClientAccept,
 }),
 [columnByItemId, cproEnabled, authUser?.id, readOnly, takingIds, takeCandidate, nextColumnLabel, onArrowAdvance, onOpenQc, canReviewAsDl, skipsFillGates, viewerOwnsDlReview, onReviewSend, openPersonViaRef, onClientAccept]
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
 const closeDock = useCallback(() => setDockCandidateId(null), []);
 // Kolumna kolejki strzałek „‹ N z M ›” (D1, 14.10.2026) i osoba, dla której
 // ją ostatnio wyznaczono — liczona niżej, przy `dockOrder`. `forCandidate:
 // null` = „wyznacz od nowa przy następnym renderze”.
 const [queue, setQueue] = useState<{ colId: string | null; forCandidate: number | null }>({
 colId: null,
 forCandidate: null,
 });
 // Pełne narzędzia osoby (dawny warsztat „Tabeli") — od 04.10.2026 to
 // rozwinięty panel osoby („Rozwiń”), nie osobne okno. `open: false` =
 // zwinięty, ale zakładki zostają zamontowane (wpisany tekst przeżywa).
 const [workbench, setWorkbench] = useState<{
 candidateId: number;
 section: PersonPanelSection;
 open: boolean;
 } | null>(null);
 // Rozwinięcie dotyczy jednej osoby — inna osoba w panelu zaczyna zwinięta.
 useEffect(() => {
 setWorkbench((w) => (w && w.candidateId !== dockCandidateId ? null : w));
 }, [dockCandidateId]);
 const openWorkbench = useCallback((candidateId: number, section: PersonPanelSection) => {
 setDockCandidateId(candidateId);
 setWorkbench({ candidateId, section, open: true });
 }, []);
 // „Zapisz i przekaż dalej” w formularzu screeningu przeszło (14.10.2026):
 // panel tej osoby przechodzi na „CV”, a karta CV pokazuje postęp (CV → QC).
 // Inna osoba w panelu — znacznik znika.
 const [forwardedCandidateId, setForwardedCandidateId] = useState<number | null>(null);
 useEffect(() => {
 setForwardedCandidateId((id) => (id != null && id !== dockCandidateId ? null : id));
 }, [dockCandidateId]);
 const onWorkbenchForwarded = useCallback((candidateId: number) => {
 setForwardedCandidateId(candidateId);
 setWorkbench((prev) => (prev && prev.candidateId === candidateId ? { ...prev, section: "cv" } : prev));
 }, []);
 // D3: pole notatki w doku wypełnia otwarty formularz screeningu tej osoby —
 // jeden kanał na Tablicę (dok i formularz są w różnych gałęziach panelu).
 const noteFill = useMemo(() => createNoteFillChannel(), []);
 // 0424 (D3 „od razu z boku”): osoba z „Nowych” i „Screeningu” otwiera się
 // od razu w panelu dzielonym — formularz screeningu (albo profil przed
 // telefonem) i CV obok. „Zwiń” wraca do doku 380 px. Bez kontekstu
 // warsztatów (harness, testy tablicy) zostaje sam dok.
 const canSplit = Boolean(workbenchContext && kanbanQueryState);
 const openDock = useCallback(
 (item: KanbanItem) => {
 // Klik w kartę wyznacza kolejkę od nowa: ta sama osoba, która w tym czasie
 // przeszła do innej kolumny, ma dostać kolejkę tej kolumny (14.10.2026).
 setQueue((q) => (q.forCandidate == null ? q : { ...q, forCandidate: null }));
 const key = columnByItemId.get(item.id);
 if (canSplit && (key === "new" || key === "screening")) {
 openWorkbench(item.candidate_id, "screening");
 return;
 }
 setDockCandidateId(item.candidate_id);
 },
 [canSplit, columnByItemId, openWorkbench]
 );
 openDockRef.current = openDock;
 useEffect(() => {
 onDockCandidateChange?.(dockCandidateId);
 }, [dockCandidateId, onDockCandidateChange]);

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
 // zwinięcie nagłówka (prop), zmiana status-baru lub liczby kolumn.
 useEffect(() => {
 measureColumnHeight();
 }, [
 measureColumnHeight,
 headerCollapsed,
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
 // Minimum dla Delivery Leada (21.10.2026): małe okno z brakującymi polami.
 // `move` = ruch czeka na zapis (strzałka, przeciągnięcie), `retry` = serwer
 // odmówił ruchu na „Zweryfikowany”, `resume` = wracamy do „Przesuń dalej”.
 const [minimumPrompt, setMinimumPrompt] = useState<{
 item: KanbanItem;
 mode: "move" | "retry" | "resume";
 srcColId?: string;
 dst?: KanbanColumn;
 } | null>(null);
 // Formularz screeningu w oknie — tylko bez panelu osoby (harness, testy).
 const [screeningPrompt, setScreeningPrompt] = useState<{
 candidateId: number;
 candidateName: string;
 } | null>(null);
 // 0424: „Screening” na karcie, „Otwórz arkusz” / „Uzupełnij w screeningu”
 // z listy braków i odmowa „Zweryfikowany” bez arkusza otwierają JEDEN
 // formularz screeningu — w panelu osoby, na sekcji „Screening”.
 const openScreeningFor = useCallback(
 (item: KanbanItem) => {
 if (canSplit) {
 openWorkbench(item.candidate_id, "screening");
 return;
 }
 setScreeningPrompt({
 candidateId: item.candidate_id,
 candidateName: itemFullName(item),
 });
 },
 [canSplit, openWorkbench]
 );
 // „Usuń z rekrutacji" — korekta (dodano nie tego kandydata / nie na tę
 // ofertę). Modal potwierdzenia trzyma board, karta tylko sygnalizuje intencję.
 const [pendingRemoval, setPendingRemoval] = useState<KanbanItem | null>(null);
 const [removeBusy, setRemoveBusy] = useState(false);

 // Odłożone ruchy strzałką „→” — `usePipelineMove` niżej; ref, bo synchronizacja
 // ze stanem serwera stoi wyżej niż hak.
 const pendingMovesRef = useRef<() => ReadonlyArray<{ candidateId: number; toColumn: KanbanColumn }>>(() => []);
 useEffect(() => {
 setCols(withPendingMoves(composeColumns(columns, offTemplate), pendingMovesRef.current()));
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
 let index = -1;
 setCols((prev) =>
 prev.map((c) => {
 if (colId(c) === srcId) {
 index = c.items.findIndex((i) => i.id === item.id);
 const items = c.items.filter((i) => i.id !== item.id);
 return { ...c, items, count: items.length };
 }
 if (colId(c) === colId(dst)) {
 const entered = { ...item, stage: c.stage, days_in_stage: 0, moved_at: new Date().toISOString() };
 const items = [entered, ...c.items];
 return { ...c, items, count: items.length };
 }
 return c;
 })
 );
 // „Cofnij” po strzałce „→” (14.10.2026): karta wraca na swoje miejsce
 // w kolumnie źródłowej, bez żądania (także po odświeżeniu w międzyczasie).
 return () =>
 setCols((prev) =>
 prev.map((c) => {
 const items = c.items.filter((i) => i.candidate_id !== item.candidate_id);
 if (colId(c) !== srcId) {
 return items.length === c.items.length ? c : { ...c, items, count: items.length };
 }
 const at = index >= 0 ? Math.min(index, items.length) : items.length;
 const restored = [...items.slice(0, at), item, ...items.slice(at)];
 return { ...c, items: restored, count: restored.length };
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
 withPendingMoves(
 composeColumns(
 fresh.data.columns as KanbanColumn[],
 fresh.data.off_template as OffTemplateColumn | null
 ),
 pendingMovesRef.current()
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
 const items = [{ ...item, moved_at: new Date().toISOString(), ...patch }, ...c.items];
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
 // D1 (04.10.2026): „Zweryfikowany” bez arkusza albo stawki → formularz
 // screeningu tej pary (0424: arkusz i stawka są w jednym miejscu).
 onVerifiedRequirementsMissing: (info, item) => {
 if (info.missing.length === 0) {
 // Brakuje tylko pól minimum dla DL — małe okno, potem ruch jeszcze raz.
 if (info.cardFields.length > 0) setMinimumPrompt({ item, mode: "retry" });
 return;
 }
 openScreeningFor(item);
 },
 });
 const { requestMove, requestReject, canMoveWithoutDialog, deferMove, commitPendingMove } = move;
 // D1/D6 (16.10.2026): akceptacja = ruch na etap „Akceptacja” wspólną ścieżką
 // (data i start w tym samym żądaniu, dzwonki wysyła serwer), a po ruchu
 // werdykt klienta „Akceptuje” z tym, co powiedział klient.
 const confirmClientAccept = useCallback(
 (values: ClientAcceptanceValues, recipients: ClientAcceptanceRecipient[]) => {
 const item = acceptFor?.item;
 setAcceptFor(null);
 if (!item || !acceptanceStageCol) return;
 const src = cols.find((c) => c.items.some((i) => i.candidate_id === item.candidate_id));
 if (!src) return;
 const name = `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
 requestMove(item, colId(src), acceptanceStageCol, {
 clientAcceptance: { acceptedOn: values.acceptedOn, plannedStartOn: values.plannedStartOn },
 onMoved: () => {
 showSuccess(acceptedToast(name, recipients));
 if (values.requestPreContract) {
 // 0506: prośba o przedwstępną „przed umową B2B” z okna akceptacji.
 preContractsApi
 .create({ candidate_id: item.candidate_id, job_id: jobId, needed_before: "b2b_contract" })
 .then(() => invalidatePreContract(queryClient, jobId))
 .catch((e) =>
 showError(`Akceptacja zapisana, ale prośba o przedwstępną nie: ${apiErrorMessage(e, "poproś w panelu osoby.")}`)
 );
 }
 hiringManagerFeedbackApi
 .record(jobId, {
 candidate_id: item.candidate_id,
 decision: "advance",
 rejection_reason_id: null,
 note: values.clientNote,
 })
 .then(() => queryClient.invalidateQueries({ queryKey: ["hiring-manager-feedback", jobId] }))
 .catch((e) =>
 showError(
 `Akceptacja zapisana, ale werdykt klienta nie: ${apiErrorMessage(e, "zapisz go w zakładce „Rozmowy”.")}`
 )
 );
 },
 });
 },
 [acceptFor, acceptanceStageCol, cols, requestMove, showSuccess, showError, jobId, queryClient]
 );
 // „Cofnij akceptację klienta” (menu „⋯” w panelu osoby): karta wraca na
 // „Rozmowę u klienta”, serwer gasi nieprzeczytane dzwonki akceptacji.
 const { askConfirm: askUndoAcceptance, confirmDialog: undoAcceptanceDialog } = useConfirmV2();
 const undoClientAccept = useCallback(
 async (item: KanbanItem) => {
 if (!clientInterviewHost) return;
 const src = cols.find((c) => c.items.some((i) => i.candidate_id === item.candidate_id));
 if (!src) return;
 const ok = await askUndoAcceptance({
 title: "Cofnąć akceptację klienta?",
 description:
 "Karta wróci do „Rozmowy u klienta”. Powiadomienia „Klient zaakceptował”, których nikt jeszcze nie otworzył, zgasną.",
 confirmLabel: "Cofnij akceptację",
 });
 // Rozmowa się odbyła — bez „Kiedy rozmowa u klienta?” (audyt 21.10.2026).
 if (ok) requestMove(item, colId(src), clientInterviewHost, { skipInterviewDate: true });
 },
 [askUndoAcceptance, clientInterviewHost, cols, requestMove]
 );
 pendingMovesRef.current = move.pendingMoves;
 // Osoba z odłożonym ruchem strzałką otwarta w panelu: ruch idzie od razu —
 // formularz screeningu i wymagania czytają stan z serwera, który jeszcze go
 // nie zna (inaczej „Zapisz i przekaż dalej” trafiał na konflikt wersji).
 useEffect(() => {
 if (dockCandidateId == null) return;
 void commitPendingMove(dockCandidateId).then((sent) => {
 if (sent) {
 void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, dockCandidateId) });
 }
 });
 }, [dockCandidateId, commitPendingMove, queryClient, jobId]);

 // Rekrutacja v5: ruch NAPRZÓD przez Tablicę. Na sąsiednią kolumnę bez
 // znanych braków — od razu (`usePipelineMove`, jak dotąd). Dalej niż
 // o jedną kolumnę, przy znanym braku albo na „CV wysłane" (bramka QC,
 // wysyłka przez DL / kolejka Cpro) — najpierw okno „Przesuń dalej".
 // Ruchy wstecz i na etapy-znaczniki w tej samej kolumnie idą od razu.
 // Przegląd przed wysłaniem do klienta woła przez `openDlReviewRef` (wyżej).
 const forwardNeedsMoveNext = useCallback(
 (item: KanbanItem, fromIndex: number, toIndex: number): boolean => {
 const fromKey = boardFold.columns[fromIndex]?.key ?? null;
 const toKey = boardFold.columns[toIndex]?.key ?? null;
 const stageBadge = boardFold.badgeByItemId.get(item.id) ?? null;
 const directToClient =
 toKey === "cv_sent" &&
 !(cproEnabled ? stageBadge === "cpro" : canReviewAsDl && item.qc?.status !== "failed");
 return (
 toIndex - fromIndex > 1 ||
 knownForwardGap(item, fromKey, { skipsFillGates }) != null ||
 directToClient
 );
 },
 [boardFold, cproEnabled, canReviewAsDl, skipsFillGates]
 );
 // Minimum dla DL (21.10.2026): ze „Screeningu” na „Zweryfikowany” brakuje
 // tylko pól karty — zamiast „Przesuń dalej” małe okno z tymi polami.
 // Delivery Lead przesuwa bez bramek pól (22.10.2026) — okna nie dostaje.
 const minimumGapBeforeVerified = useCallback(
 (item: KanbanItem, fromIndex: number, toIndex: number): boolean =>
 !skipsFillGates &&
 boardFold.columns[fromIndex]?.key === "screening" &&
 boardFold.columns[toIndex]?.key === "verified" &&
 minimumOnlyGap(item),
 [boardFold, skipsFillGates]
 );
 const routeMove = useCallback(
 (item: KanbanItem, srcColId: string, dst: KanbanColumn) => {
 if (acceptInsteadOfMove(item, dst)) return;
 const fromIndex = foldIndexByColId.get(srcColId);
 const toIndex = foldIndexByColId.get(colId(dst));
 if (fromIndex == null || toIndex == null || toIndex <= fromIndex) {
 requestMove(item, srcColId, dst);
 return;
 }
 if (openDlReviewRef.current(item, dst)) return;
 if (minimumGapBeforeVerified(item, fromIndex, toIndex)) {
 setMinimumPrompt({ item, mode: "move", srcColId, dst });
 return;
 }
 if (forwardNeedsMoveNext(item, fromIndex, toIndex)) {
 openMoveNext(item, srcColId, dst);
 return;
 }
 requestMove(item, srcColId, dst);
 },
 [foldIndexByColId, forwardNeedsMoveNext, minimumGapBeforeVerified, openMoveNext, requestMove, acceptInsteadOfMove]
 );
 // Strzałka „→” na karcie (D7, decyzja Artura 14.10.2026): ta sama reguła co
 // przeciągnięcie na sąsiednią kolumnę, ale ruch, który nie potrzebuje
 // żadnego okna (stawka, wysyłka, zatrudnienie) ani nie ma znanego braku,
 // idzie bez okna „Przesuń dalej” — karta przechodzi od razu, a komunikat
 // ma 10 s na „Cofnij” (`deferMove`). Reszta — okno „Przesuń dalej” jak dotąd.
 // Przeciąganie zostaje natychmiastowe; dok i okno QC wołają `onAdvance`.
 arrowAdvanceRef.current = (item: KanbanItem) => {
 const next = nextFoldByItemId.get(item.id);
 const src = cols.find((c) => c.items.some((i) => i.id === item.id));
 if (!next || !src) return;
 if (acceptInsteadOfMove(item, next.host)) return;
 const fromIndex = foldIndexByColId.get(colId(src));
 const toIndex = foldIndexByColId.get(colId(next.host));
 if (fromIndex != null && toIndex != null && minimumGapBeforeVerified(item, fromIndex, toIndex)) {
 setMinimumPrompt({ item, mode: "move", srcColId: colId(src), dst: next.host });
 return;
 }
 if (
 fromIndex != null &&
 toIndex != null &&
 !forwardNeedsMoveNext(item, fromIndex, toIndex) &&
 canMoveWithoutDialog(item, next.host)
 ) {
 deferMove(item, colId(src), next.host, {
 targetLabel: next.label,
 // Delivery Lead przesuwa mimo braków (22.10.2026) — komunikat je wymienia.
 detail: skipsFillGates
 ? fillGapsText(
 item,
 boardFold.columns[fromIndex]?.key ?? null,
 boardFold.columns[toIndex]?.key ?? null
 )
 : null,
 });
 return;
 }
 openMoveNext(item, colId(src), next.host);
 };

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
 // Po numerze karty, nie po `res.source.index`: filtr „Kto dodał” chowa
 // część kart, a indeks liczy się po liście, którą widać (14.10.2026).
 const item = srcDisplay.items.find((i) => String(i.id) === res.draggableId);
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

 // Karta i dok podają wiersz etapu — osobę szukamy na Tablicy (ref, żeby
 // kolumny nie dostawały nowej funkcji przy każdym odświeżeniu tablicy).
 const colsRef = useRef(cols);
 colsRef.current = cols;
 const handleOpenScreening = useCallback(
 (stageId: number) => {
 const item = colsRef.current.flatMap((c) => c.items).find((i) => i.id === stageId);
 if (item) openScreeningFor(item);
 },
 [openScreeningFor]
 );

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

 // Przeciąganie karty: znacznik na korzeniu tablicy zamiast stanu Reacta —
 // pokazuje ramki „upuść tutaj” w pustych kolumnach bez przerenderowania
 // kolumn w trakcie ruchu (04.10.2026).
 const boardRootRef = useRef<HTMLDivElement>(null);
 const handleDragStart = useCallback(() => {
 boardRootRef.current?.setAttribute("data-dragging", "true");
 }, []);
 const handleDragEnd = useCallback(
 (res: DropResult) => {
 boardRootRef.current?.removeAttribute("data-dragging");
 onDragEnd(res);
 },
 [onDragEnd]
 );

 // ── Krok 04 Pipeline (flow C2, PR 3/7): dok „Karta w procesie" ─────────
 //
 // `dockItem` szuka po `candidate_id`, nie po `id` (patrz komentarz przy
 // `dockCandidateId`). Jedno przejście po `cols` starcza na trójkę: samą
 // kartę, id kolumny w której dziś stoi (do wykluczenia z pigułek ruchu i
 // do `requestMove`) i etykietę tej kolumny (do nagłówka „Etap ·" w doku).
 // Ta sama reguła służy zapowiedzi następnej osoby w oknie odrzucenia.
 const locateCandidate = useCallback(
 (candidateId: number): { item: KanbanItem; colId: string; label: string } | null => {
 for (const c of cols) {
 const found = c.items.find((i) => i.candidate_id === candidateId);
 if (found) {
 const host = hostByColId.get(colId(c));
 return {
 item: found,
 colId: colId(c),
 label: (host ? boardLabelByColId.get(colId(host)) : undefined) ?? columnLabel(c),
 };
 }
 }
 return null;
 },
 [cols, hostByColId, boardLabelByColId]
 );
 const { dockItem, dockItemColId, dockItemColLabel } = useMemo((): {
 dockItem: KanbanItem | null;
 dockItemColId: string | null;
 dockItemColLabel: string | null;
 } => {
 const place = dockCandidateId != null ? locateCandidate(dockCandidateId) : null;
 return place
 ? { dockItem: place.item, dockItemColId: place.colId, dockItemColLabel: place.label }
 : { dockItem: null, dockItemColId: null, dockItemColLabel: null };
 }, [dockCandidateId, locateCandidate]);

 // Panel osoby zabiera tablicy 380 px z prawej (`lg:pr-[380px]`) — po jego
 // otwarciu i przy „‹ ›” w panelu tablica przewija się tak, żeby karta
 // wybranej osoby została na widoku. Na laptopie 1280 px osoba z „CV
 // wysłane” chowała się pod własnym panelem (04.10.2026). Tylko przy zmianie
 // osoby — odświeżenie tablicy nie przewija jej pod rekruterem.
 const dockOpen = dockItem != null && dockItemColLabel !== null;
 useEffect(() => {
 if (!dockOpen || dockCandidateId == null) return;
 const frame = window.requestAnimationFrame(() => {
 document
 .querySelector<HTMLElement>(`[data-candidate-id="${dockCandidateId}"]`)
 ?.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: "smooth" });
 });
 return () => window.cancelAnimationFrame(frame);
 }, [dockCandidateId, dockOpen]);


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
 if (onBoard) openWorkbench(initialWorkbench.candidateId, initialWorkbench.section);
 onInitialWorkbenchHandled?.();
 }, [initialWorkbench, workbenchContext, cols, onInitialWorkbenchHandled, openWorkbench]);

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
 // `review=1`: przegląd otwiera osobny efekt niżej — `openDlReviewIfSending`
 // powstaje później w tym komponencie.
 const [pendingReviewCandidateId, setPendingReviewCandidateId] = useState<number | null>(null);
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
 if (initialDockOpensReview) setPendingReviewCandidateId(initialDockCandidateId);
 }
 onInitialDockHandled?.();
 }, [initialDockCandidateId, initialDockOpensReview, cols, onInitialDockHandled]);

 // Kolumna terminala „Odrzucony" tego szablonu — potrzebna zarówno „Odrzuć
 // z powodem" w doku, jak i sprawdzeniu, czy dana karta w ogóle DA się
 // jeszcze odrzucić (kandydat już `hired`/`rejected`/`withdrawn` — nie ma
 // po co proponować ponowne odrzucenie).
 const rejectedTemplateCol = useMemo(
 () => stageCols.find((c) => terminalOf(c) === "rejected"),
 [stageCols]
 );
 // Zamknięta rekrutacja (28.10.2026): osoby patrzącego od „CV wysłane”, którym
 // trzeba dać znać — ta sama osoba karty co dzwonek z serwera.
 const myWaiting = useMemo(
 () => (closedJob ? myWaitingItems(stageCols, authUser?.id) : []),
 [closedJob, stageCols, authUser?.id]
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
 // Przełącznik w doku mówi pełnym krokiem („Umowa wysłana”), karta — skrótem.
 label: SETTABLE_BADGE_TOGGLE_LABEL[badge] ?? STAGE_BADGE_LABEL[badge],
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
 // CV, screening, stawka do klienta), a nie samo okno stawki. Od 08.10.2026
 // (D9) przegląd pokazuje budżet i marżę na żywo — decyzja „bez marży” z 23.09
 // jest odwrócona.
 const [dlReviewTask, setDlReviewTask] = useState<BoardTaskRow | null>(null);
 // Jeden panel osoby (04.10.2026): przegląd DL otwiera się W panelu osoby
 // jako szeroki tryb; dok tej samej (albo innej) osoby zostaje pod nim
 // zamontowany i ukryty, a po zamknięciu przeglądu wraca z niewysłaną
 // notatką.
 const reviewOpen = dlReviewTask !== null;
 // Przegląd nie jest oknem z pułapką fokusu — po zamknięciu fokus wraca
 // tam, skąd przegląd otwarto (karta, menu doku, okno „Przesuń dalej”).
 const reviewReturnFocusRef = useRef<HTMLElement | null>(null);
 const closeDlReview = useCallback(() => {
 // Każde zamknięcie przeglądu (X, Esc, klik w tło, konflikt wersji) kończy
 // też kolejkę „po kolei” — inaczej następna osoba otworzyłaby się sama.
 finishSequence();
 setDlReviewTask(null);
 const back = reviewReturnFocusRef.current;
 reviewReturnFocusRef.current = null;
 window.setTimeout(() => {
 // Element, który otworzył przegląd (pozycja menu, okno „Przesuń dalej”),
 // bywa już odmontowany — wtedy fokus idzie do panelu osoby.
 const target =
 back && back.isConnected
 ? back
 : document.querySelector<HTMLElement>('[data-testid="person-panel-dock"]');
 target?.focus();
 }, 0);
 }, [finishSequence]);
 // Prawo wysyłki z wiersza serwera; do jego przyjścia — ta sama reguła
 // w przeglądarce (`recruitment_manage`).
 const [dlReviewCanSend, setDlReviewCanSend] = useState<boolean | undefined>(undefined);
 // Jedna droga dla doku, strzałki na karcie i przeciągnięcia: wysyłka z „QC
 // CV" przez osobę z prawem wysyłki otwiera przegląd (karta, uwagi dla
 // rekrutera, „Wróć do poprawy"). Test na produkcji 03.10.2026: strzałka
 // otwierała samo okno stawki i omijała przegląd.
 // U Nordei (13.10.2026) ta sama droga kończy się akceptacją do kolejki
 // Cpro: wysyłką jest ruch na „Wysłane do Cpro” albo na etap Cpro, a celem
 // przeglądu — etap Cpro. Karta już w kolejce czeka na osobę od Cpro.
 const openDlReviewIfSending = useCallback(
 (item: KanbanItem, dst: KanbanColumn): boolean => {
 const from = columnByItemId.get(item.id);
 // Kolumna „Do Cpro” (etap kolejki), nie „Wysłane do Cpro” — obie mają
 // „Cpro” w nazwie.
 const toCpro = cproStageCol != null && colId(dst) === colId(cproStageCol);
 // Nordea: DL tej rekrutacji odkłada kartę na „QC CV” — przegląd czekałby
 // na niego samego (dzwonek do siebie resolver odsiewa), a osoba od Cpro nic
 // by nie dostała (26.10.2026). Akceptacja od razu.
 const qcHost = boardFold.columns.find((f) => f.key === "cv_qc" && !f.cproQueue)?.host;
 const ownQcDrop =
 cproEnabled && viewerOwnsDlReview && qcHost != null && colId(dst) === colId(qcHost);
 const sendTarget = cproEnabled
 ? dst.stage === "cv_sent" || toCpro || ownQcDrop
 : dst.stage === "cv_sent";
 const fromOk =
 from === "cv_qc" ||
 (cproEnabled && (toCpro || ownQcDrop) && (from === "new" || from === "screening" || from === "verified"));
 if (
 !sendTarget ||
 !canReviewAsDl ||
 !fromOk ||
 boardFold.badgeByItemId.get(item.id) === "cpro" ||
 item.qc?.status === "failed"
 ) {
 return false;
 }
 if (document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
 reviewReturnFocusRef.current = document.activeElement;
 }
 // Przegląd zajmuje szeroki panel — rozwinięte narzędzia zwijają się
 // (zostają zamontowane pod spodem).
 setWorkbench((w) => (w ? { ...w, open: false } : w));
 setDlReviewTask({
 kind: "dl_review",
 stage_id: item.id,
 candidate_id: item.candidate_id,
 candidate_name: itemFullName(item),
 job_id: jobId,
 job_title: jobTitle ?? "",
 client_id: clientId ?? null,
 client_name: null,
 since: item.moved_at ?? new Date().toISOString(),
 process_state_version: item.process_state_version ?? 0,
 target_stage_def_id: cproEnabled
 ? (cproStageCol?.stage_def_id ?? null)
 : (dst.stage_def_id ?? null),
 cpro: cproEnabled,
 rejected_stage_def_id: rejectedTemplateCol?.stage_def_id ?? null,
 // „Wróć do poprawy": gospodarz kolumny „Zweryfikowany".
 return_stage_def_id:
   boardFold.columns.find((f) => f.key === "verified")?.host.stage_def_id ?? null,
 assignee_id: null,
 assignee_name: null,
 verified_at: item.moved_at ?? null,
 expected_rate_value:
 item.expected_rate_value != null ? Number(item.expected_rate_value) : null,
 expected_rate_unit: item.expected_rate_unit ?? null,
 expected_rate_currency: item.expected_rate_currency ?? null,
 // Serwer czyta arkusz pary (także z „Nowych"), gdy etap nie ma własnego.
 screening_stage_id: item.id,
 });
 setDlReviewCanSend(undefined);
 // Wiersz z serwera (ta sama reguła co pulpit): etap CV po QC, kto
 // zweryfikował, klient, stan karty. Do jego przyjścia przegląd stoi na
 // wierszu z tablicy; błąd zostawia ten wiersz (04.10.2026).
 const candidateId = item.candidate_id;
 void fetchDlReviewRow(candidateId, jobId)
 .then((res) => {
 setDlReviewTask((cur) =>
 cur && cur.candidate_id === candidateId ? { ...cur, ...res.row } : cur
 );
 setDlReviewCanSend(res.can_send_to_client);
 })
 .catch(() => undefined);
 return true;
 },
 [cproEnabled, cproStageCol, canReviewAsDl, columnByItemId, jobId, jobTitle, clientId, rejectedTemplateCol, boardFold, viewerOwnsDlReview]
 );
 useEffect(() => {
 openDlReviewRef.current = openDlReviewIfSending;
 }, [openDlReviewIfSending]);
 // „Przejrzyj po kolei”: przegląd bieżącej osoby kolejki otwiera się sam —
 // na starcie i po każdej decyzji albo „Pomiń”. Efekt biegnie też przy
 // odświeżeniu tablicy; przegląd osoby, która już jest otwarta, zostaje
 // nietknięty (wpisana stawka i uwagi).
 const reviewCandidateId = dlReviewTask?.candidate_id ?? null;
 useEffect(() => {
 if (!sequenceActive) return;
 if (sequenceCurrent === null) {
 closeDlReview();
 // Pominięte osoby dalej czekają — komunikat nie może mówić, że nikogo nie ma.
 showInfo(
 sequenceSkipped > 0
 ? `Koniec kolejki — pominięte osoby dalej czekają: ${sequenceSkipped}.`
 : "Kolejka przejrzana — nikt więcej nie czeka w tej rekrutacji."
 );
 return;
 }
 if (reviewCandidateId === sequenceCurrent.candidate_id) return;
 // Fokus po całej kolejce wraca tam, skąd ją uruchomiono, nie do przycisku
 // z przeglądu poprzedniej osoby.
 const back = reviewReturnFocusRef.current;
 const opened = dlSendTarget !== null && openDlReviewIfSending(sequenceCurrent, dlSendTarget);
 if (back) reviewReturnFocusRef.current = back;
 if (!opened) closeDlReview();
 }, [sequenceActive, sequenceCurrent, sequenceSkipped, reviewCandidateId, dlSendTarget, openDlReviewIfSending, closeDlReview, showInfo]);
 const startReviewSequence = useCallback(
 () => startSequence(dlReadyItems),
 [startSequence, dlReadyItems]
 );
 // D10 (08.10.2026): porównanie osób w „QC CV” tej rekrutacji — klik w osobę
 // otwiera jej przegląd z wiersza kolejki (ten sam co na pulpicie).
 const [compareOpen, setCompareOpen] = useState(false);
 const openDlReviewForTask = useCallback((task: BoardTaskRow) => {
 if (document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
 reviewReturnFocusRef.current = document.activeElement;
 }
 setWorkbench((w) => (w ? { ...w, open: false } : w));
 setDlReviewTask(task);
 setDlReviewCanSend(undefined);
 }, []);
 // `?candidate=&review=1` — dzwonek „CV do przeglądu” prowadzi prosto do
 // przeglądu, nie do samego doku (04.10.2026).
 useEffect(() => {
 if (pendingReviewCandidateId == null) return;
 setPendingReviewCandidateId(null);
 const item = cols
 .flatMap((c) => c.items)
 .find((i) => i.candidate_id === pendingReviewCandidateId);
 const reviewTarget = cproEnabled ? (cproStageCol ?? cvSentColumn) : cvSentColumn;
 if (!item || !reviewTarget || !openDlReviewIfSending(item, reviewTarget)) {
 showInfo(
 cproEnabled
 ? "Ta osoba nie czeka teraz na akceptację do kolejki Cpro."
 : "Ta osoba nie czeka teraz na przegląd przed wysłaniem do klienta."
 );
 }
 }, [pendingReviewCandidateId, cols, cproEnabled, cproStageCol, cvSentColumn, openDlReviewIfSending, showInfo]);
 const handleDockMove = useCallback(
 (dst: KanbanColumn) => {
 if (!dockItem || !dockItemColId) return;
 if (acceptInsteadOfMove(dockItem, dst)) return;
 if (openDlReviewIfSending(dockItem, dst)) return;
 // Wybór etapu z doku jest jawny — ruch od razu (serwer i tak pilnuje
 // bramki QC; 409 CV_QC_FAILED otwiera okno QC CV).
 requestMove(dockItem, dockItemColId, dst);
 },
 [dockItem, dockItemColId, requestMove, openDlReviewIfSending, acceptInsteadOfMove]
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
 // Akceptacja do kolejki Cpro (Delivery Lead) idzie przez przegląd —
 // ze stawką do Cpro, nie gołym ruchem.
 if (openDlReviewIfSending(dockItem, dst)) return;
 requestMove(dockItem, dockItemColId, dst);
 },
 [dockItem, dockItemColId, stageCols, requestMove, showError, openDlReviewIfSending]
 );

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
 // Rozwinięte narzędzia tej osoby (tylko dla osoby otwartej w panelu).
 const activeWorkbench =
 workbench && dockItem && workbench.candidateId === dockItem.candidate_id ? workbench : null;
 const workbenchOpen = activeWorkbench?.open === true;
 const dockRow = usePersonRow(stageCols, dockItem?.candidate_id ?? null, jobBudgetHourlyValue ?? null);
 // „Zwiń” / Esc / klik w tło: narzędzia zostają zamontowane.
 const collapseWorkbench = useCallback(() => {
 setWorkbench((w) => (w ? { ...w, open: false } : w));
 }, []);
 // Okno „Przesuń dalej”, z którego rozwinięto panel (akcja „Wygeneruj CV”,
 // rozmowy), wraca przy KAŻDYM wyjściu z szerokiego panelu: „Zwiń”, Esc,
 // zamknięcie karty, inna osoba, a po przeglądzie DL — po jego zamknięciu.
 // Dawny warsztat w oknie miał jedno wyjście; panel ma kilka (przegląd kodu
 // 04.10.2026). `resumeMoveNext` bez zawieszenia tylko odświeża wymagania.
 const wideBefore = useRef(false);
 const panelWide = workbenchOpen || reviewOpen;
 // Szerokość panelu osoby: przegląd DL i rozwinięte narzędzia zajmują całą
 // szerokość okna. Od 09.10.2026 każda zakładka ma podgląd po lewej (także
 // umowa, dopasowanie i notatki) — do tej daty te trzy miały panel 760 px
 // i pasek zakładek przesuwał się w bok przy przejściu między zakładkami.
 const screeningSplit = workbenchOpen && activeWorkbench?.section === "screening";
 const panelSize: PersonPanelSize = reviewOpen ? "review" : workbenchOpen ? "split" : "dock";
 useEffect(() => {
 if (wideBefore.current && !panelWide) resumeMoveNext();
 wideBefore.current = panelWide;
 }, [panelWide, resumeMoveNext]);
 const toggleWorkbench = useCallback(() => {
 if (!dockItem) return;
 if (workbenchOpen) {
 collapseWorkbench();
 return;
 }
 setWorkbench((w) =>
 w && w.candidateId === dockItem.candidate_id
 ? { ...w, open: true }
 : {
 candidateId: dockItem.candidate_id,
 section: dockRow ? workbenchDefaultSection(dockRow) : "notes",
 open: true,
 },
 );
 }, [dockItem, dockRow, workbenchOpen, collapseWorkbench]);
 // Panel osoby jest nakładką z prawej — Escape zamyka jego najwyższą warstwę
 // (przegląd DL, potem rozwinięte narzędzia, potem dok), chyba że otwarty jest dialog (modal powodu
 // odrzucenia, stawki itp.): wtedy Escape należy do niego.
 useEffect(() => {
 if (!dockItem && !dlReviewTask) return;
 const onKey = (e: KeyboardEvent) => {
 if (e.key !== "Escape" || e.defaultPrevented) return;
 if (document.querySelector('[role="dialog"],[role="alertdialog"]')) return;
 // Duże okno notatki w doku jest warstwą nad panelem — zmniejsza je sam
 // dok (`DockNoteComposer`), a panel zostaje otwarty. Okno w doku ukrytym
 // pod przeglądem DL warstwą nie jest.
 const noteWindow = document.querySelector("[data-note-enlarged]");
 if (noteWindow && !noteWindow.closest("[hidden]")) return;
 if (dlReviewTask) closeDlReview();
 else if (workbenchOpen) collapseWorkbench();
 else closeDock();
 };
 window.addEventListener("keydown", onKey);
 return () => window.removeEventListener("keydown", onKey);
 }, [dockItem, dlReviewTask, workbenchOpen, closeDlReview, collapseWorkbench, closeDock]);

 // „Przesuń dalej" z okna QC: okno otwarte z listy braków wraca do swojego
 // „Przesuń dalej", otwarte z karty — otwiera je dla następnej kolumny. Ruch
 // etapu ma jedną drogę (`MoveNextDialog` → `usePipelineMove`).
 const handleQcMoveNext = useCallback(
 (candidateId: number) => {
 const suspended = moveNextSuspended.current;
 setQcStageId(null);
 resumeMoveNext();
 if (suspended) return;
 const item = cols.flatMap((c) => c.items).find((i) => i.candidate_id === candidateId);
 if (item) onAdvance(item);
 },
 [cols, onAdvance, resumeMoveNext]
 );
 const handleMoveNextAction = useCallback(
 (action: MoveRequirementAction, item: KanbanItem) => {
 const name = itemFullName(item);
 const stageId = action.stage_id ?? item.id;
 switch (action.kind) {
 case "open_screening":
 suspendMoveNext();
 openScreeningFor(item);
 return;
 case "open_qc":
 suspendMoveNext();
 setQcStageId(stageId);
 return;
 case "open_card":
 // 0424: pola karty rekomendacji są w formularzu screeningu. Brak samego
 // minimum dla DL (21.10.2026) — małe okno z tymi polami.
 suspendMoveNext();
 if (item.minimum_missing?.length) {
 setMinimumPrompt({ item, mode: "resume" });
 return;
 }
 openScreeningFor(item);
 return;
 case "reject":
 // Odpowiedź narusza „Odpada, gdy…" — okno odrzucenia z notatką od
 // serwera (które pytanie i co padło). Ruch „Przesuń mimo to" zostaje.
 moveNextSuspended.current = false;
 setMoveNextOpen(false);
 setMoveNext(null);
 requestReject(item, rejectedTemplateCol, { notes: action.note ?? null });
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
 if (action.kind === "set_client_rate") {
 // Stawkę do klienta (u Nordei — do Cpro) wpisuje się w przeglądzie —
 // razem z kartą i uwagami dla rekrutera.
 if (dlSendTarget && openDlReviewIfSending(item, dlSendTarget)) {
 setMoveNextOpen(false);
 return;
 }
 }
 if (workbenchContext) {
 suspendMoveNext();
 openWorkbench(item.candidate_id, "cv");
 } else {
 // Osobnego ekranu generatora nie ma od 13.10.2026 — panel osoby
 // ma kartę „CV do klienta” z „Generuj CV”.
 window.open(
 `/jobs/${jobId}?candidate=${item.candidate_id}`,
 "_blank",
 "noopener"
 );
 }
 return;
 case "open_client_form":
 // 0521: formularz CV klienta do uzupełnienia — sekcja CV panelu osoby.
 if (workbenchContext) {
 suspendMoveNext();
 openWorkbench(item.candidate_id, "cv");
 } else {
 window.open(`/jobs/${jobId}?candidate=${item.candidate_id}`, "_blank", "noopener");
 }
 return;
 case "open_pre_contract":
 // 0506: umowa przedwstępna niepodpisana — sekcja w zakładce „Umowa”.
 // Ruch „Przesuń mimo braku” zostaje (ostrzeżenie, nie bramka).
 if (workbenchContext) {
 suspendMoveNext();
 openWorkbench(item.candidate_id, "contract");
 } else {
 window.open(`/jobs/${jobId}?candidate=${item.candidate_id}`, "_blank", "noopener");
 }
 return;
 case "open_debrief":
 suspendMoveNext();
 // Bez terminu w NEXUSIE okno pytań pyta, kiedy była rozmowa (20.10.2026).
 setDebriefFor({
 eventId: action.event_id ?? null,
 candidateId: item.candidate_id,
 name,
 });
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
 showInfo(SLOTS_BY_OTHERS_MESSAGE);
 }
 return;
 default:
 return;
 }
 },
 [suspendMoveNext, boardFold, cols, requestMove, requestReject, rejectedTemplateCol, workbenchContext, jobId, jobTitle, clientId, canAddClientSlots, dlSendTarget, openDlReviewIfSending, showInfo, openWorkbench, openScreeningFor]
 );
 const handleMoveNextMove = useCallback(
 (target: KanbanColumn) => {
 if (!moveNext) return;
 // Okno pamięta kartę z chwili otwarcia; QC mogło się w międzyczasie
 // zaliczyć (poprawka albo „Przepuść mimo QC” z listy braków).
 const item =
 cols.flatMap((c) => c.items).find((i) => i.id === moveNext.item.id) ?? moveNext.item;
 if (openDlReviewIfSending(item, target)) {
 setMoveNextOpen(false);
 return;
 }
 requestMove(moveNext.item, moveNext.srcColId, target);
 },
 [moveNext, cols, requestMove, openDlReviewIfSending]
 );
 const handleHandToCpro = useCallback(
 (stageDefId: number) => {
 if (!moveNext) return;
 const cpro = stageCols.find((c) => c.stage_def_id === stageDefId);
 if (!cpro) {
 showError("Nie znaleziono tego etapu w szablonie tej rekrutacji.");
 return;
 }
 // Delivery Lead akceptuje do kolejki Cpro w przeglądzie (stawka do Cpro).
 // Okno pamięta kartę z chwili otwarcia — QC mogło się w międzyczasie
 // zaliczyć albo zostać przepuszczone (jak w `handleMoveNextMove`).
 const item =
 cols.flatMap((c) => c.items).find((i) => i.id === moveNext.item.id) ?? moveNext.item;
 if (openDlReviewIfSending(item, cpro)) return;
 requestMove(moveNext.item, moveNext.srcColId, cpro);
 },
 [moveNext, cols, stageCols, requestMove, showError, openDlReviewIfSending]
 );

 // Kolumny do renderu: 8 kolumn Tablicy (+ rozwinięci zamknięci + kubełek
 // „Poza szablonem"). Puste kolumny są zawsze widoczne, bez przełącznika
 // (decyzja Artura 25.10.2026) — do tego dnia domyślnie je chowano, a Tablica
 // nie mówiła, że coś ukryła.
 const allOffTemplateCols = useMemo(() => cols.filter((c) => isOffTemplate(c)), [cols]);
 const offTemplateCols = useMemo(
 () => allOffTemplateCols.map((c) => withAddedByFilter(c, addedBy)),
 [allOffTemplateCols, addedBy]
 );
 // Liczba osób w kolumnie bez filtra „Kto dodał” — licznik „N z M” i napis
 // w kolumnie pustej przez filtr (mówi, że filtr schował wszystkich).
 const totalCountByColId = useMemo(() => {
 const m = new Map<string, number>();
 for (const c of [...allDisplayCols, ...allOffTemplateCols]) m.set(colId(c), c.count);
 return m;
 }, [allDisplayCols, allOffTemplateCols]);
 const visibleCols = useMemo(
 () => [...displayCols, ...(showClosed ? boardFold.closed : []), ...offTemplateCols],
 [displayCols, boardFold, showClosed, offTemplateCols]
 );
 // Filtr schował część osób — zaznaczenie ich nie trzyma, żeby pasek
 // zaznaczonych nie działał na kimś, kogo nie widać.
 useEffect(() => {
 if (addedBy.kind === "all") return;
 setSelected((prev) => {
 if (prev.size === 0) return prev;
 const hidden = new Set<number>();
 for (const c of [...allDisplayCols, ...allOffTemplateCols]) {
 for (const item of c.items) if (!matchesAddedBy(item, addedBy)) hidden.add(item.candidate_id);
 }
 const next = new Set(Array.from(prev).filter((id) => !hidden.has(id)));
 return next.size === prev.size ? prev : next;
 });
 }, [addedBy, allDisplayCols, allOffTemplateCols]);
 // Menu „Kto dodał” w panelu osoby — te same liczby co przycisk w nagłówku
 // (osoby w toku, `lib/board-added-by.ts`), z żywego stanu Tablicy.
 const addedByMenuOptions = useMemo(
 () =>
 addedByOptions(peopleInProgress(cols), {
 id: authUser?.id ?? null,
 name: authUser?.name ?? null,
 }),
 [cols, authUser?.id, authUser?.name]
 );

 // ── Kolejka panelu „‹ N z M ›” (D1, 14.10.2026) ────────────────────────
 // Strzałki chodzą po JEDNEJ kolumnie Tablicy — kolumnie otwartej osoby,
 // z filtrem „Kto dodał” — nie po całej Tablicy (rekruter widział „1 z 66”,
 // gdy w „Nowych” było 43). Kolejka zostaje, gdy panel idzie dalej w tej
 // kolumnie (strzałki, przejście po odrzuceniu) albo osoba z niej wypada
 // (ruch, zamknięcie, „Pokaż”); zmienia się, gdy otworzysz osobę z innej
 // kolumny. Zamknięci nie są kolejką. Klucz to `candidate_id` (stabilny przez
 // ruchy), dokładnie jak `dockCandidateId`.
 // Zasady: docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md („Kolejka w kolumnie…”).
 const columnOfCandidate = useMemo(() => {
 const m = new Map<number, string>();
 for (const c of [...allDisplayCols, ...allOffTemplateCols]) {
 for (const item of c.items) if (!m.has(item.candidate_id)) m.set(item.candidate_id, colId(c));
 }
 return m;
 }, [allDisplayCols, allOffTemplateCols]);
 const queueCol = useMemo(
 () => [...displayCols, ...offTemplateCols].find((c) => colId(c) === queue.colId) ?? null,
 [displayCols, offTemplateCols, queue.colId]
 );
 // Kotwica liczona w renderze (stan pochodny, bez efektu — panel nie miga
 // licznikiem poprzedniej kolumny). Po ustawieniu warunek jest fałszywy,
 // więc render się nie zapętla. Zamknięty panel zostawia kolumnę, ale
 // ponowne otwarcie (także tej samej osoby) wyznacza kolejkę od nowa.
 if (dockCandidateId == null) {
 if (queue.forCandidate != null) setQueue({ colId: queue.colId, forCandidate: null });
 } else {
 const ownColumn = columnOfCandidate.get(dockCandidateId) ?? null;
 if (queue.forCandidate !== dockCandidateId || (queueCol == null && ownColumn != null)) {
 const nextColId = queueColumnAfterOpen(
 queueCol ? queue.colId : null,
 dockCandidateId,
 queueCol ? dockNavigationOrder([queueCol]) : [],
 ownColumn
 );
 if (nextColId !== queue.colId || queue.forCandidate !== dockCandidateId) {
 setQueue({ colId: nextColId, forCandidate: dockCandidateId });
 }
 }
 }
 const dockOrder = useMemo(() => (queueCol ? dockNavigationOrder([queueCol]) : []), [queueCol]);
 const dockIndex = dockItem ? dockOrder.indexOf(dockItem.candidate_id) : -1;
 // Cała widoczna Tablica (z filtrem) — „Następna w Screeningu” w karcie CV.
 const boardOrder = useMemo(() => dockNavigationOrder(visibleCols), [visibleCols]);
 const queueColumnName = queueCol
 ? boardLabelByColId.get(colId(queueCol)) ?? columnLabel(queueCol)
 : null;
 const queueSuffix = addedByQueueSuffix(addedBy, addedByMenuOptions);
 const queueLabel = queueColumnName
 ? queueSuffix
 ? `${queueColumnName} · ${queueSuffix}`
 : queueColumnName
 : null;
 // Kto stał za osobą z panelu, zanim wypadła z kolejki — „Wróć do kolejki”.
 const formerlyAfterRef = useRef<number[]>([]);
 useEffect(() => {
 if (dockIndex >= 0) formerlyAfterRef.current = dockOrder.slice(dockIndex + 1);
 }, [dockIndex, dockOrder]);
 // 0424: w panelu dzielonym „‹ ›” po „Nowych” i „Screeningu” zostaje przy
 // formularzu — rekruter przechodzi kolejkę bez zwijania panelu. Ta sama
 // reguła po odrzuceniu z panelu (niżej).
 const showInDock = useCallback(
 (nextId: number) => {
 if (screeningSplit) {
 const nextItem = cols.flatMap((c) => c.items).find((i) => i.candidate_id === nextId);
 const key = nextItem ? columnByItemId.get(nextItem.id) : null;
 if (key === "new" || key === "screening") {
 openWorkbench(nextId, "screening");
 return;
 }
 }
 setDockCandidateId(nextId);
 },
 [screeningSplit, cols, columnByItemId, openWorkbench]
 );
 // „Następna w Screeningu” w karcie CV panelu (14.10.2026): kolejność „›”
 // zawężona do jednej kolumny Tablicy — pierwsza osoba za wskazaną, a gdy za
 // nią nikogo nie ma, pierwsza od góry tej kolumny.
 const nextInColumn = useCallback(
 (candidateId: number, column: BoardColumnKey): NextInColumn | null => {
 const byCandidate = new Map<number, KanbanItem>();
 for (const c of cols) for (const i of c.items) byCandidate.set(i.candidate_id, i);
 const inColumn = boardOrder.filter((id) => {
 const found = byCandidate.get(id);
 return id !== candidateId && found != null && columnByItemId.get(found.id) === column;
 });
 if (inColumn.length === 0) return null;
 const at = boardOrder.indexOf(candidateId);
 const nextId = (at >= 0 ? inColumn.find((id) => boardOrder.indexOf(id) > at) : undefined) ?? inColumn[0];
 const next = byCandidate.get(nextId) as KanbanItem;
 const days = next.days_in_stage;
 return {
 candidateId: nextId,
 name: itemFullName(next),
 detail:
 days == null ? null : days <= 0 ? "czeka od dziś" : days === 1 ? "czeka 1 dzień" : `czeka ${days} dni`,
 };
 },
 [cols, boardOrder, columnByItemId]
 );
 // „Otwórz” przy następnej osobie w karcie CV: osoba z „Nowych”/„Screeningu”
 // dostaje formularz w panelu dzielonym (jak klik w kartę) — rekruter zwykle
 // przechodzi wtedy do kolejnego screeningu, a panel stoi na „CV”, więc samo
 // „›” dałoby wąski dok. Inna kolumna — jak „›”.
 const openPersonInPanel = useCallback(
 (candidateId: number) => {
 const found = cols.flatMap((c) => c.items).find((i) => i.candidate_id === candidateId);
 const key = found ? columnByItemId.get(found.id) : null;
 if (canSplit && (key === "new" || key === "screening")) {
 openWorkbench(candidateId, "screening");
 return;
 }
 showInDock(candidateId);
 },
 [cols, columnByItemId, canSplit, openWorkbench, showInDock]
 );
 const selectAdjacentDockCard = useCallback(
 (delta: -1 | 1) => {
 if (dockOrder.length === 0) return;
 const current = dockIndex;
 if (current < 0) return;
 const next = current + delta;
 if (next < 0 || next >= dockOrder.length) return;
 showInDock(dockOrder[next]);
 },
 [dockOrder, dockIndex, showInDock]
 );

 // ── Po odrzuceniu albo rezygnacji z panelu: następna osoba (13.10.2026) ──
 // Prośba rekrutera, decyzje Artura D1–D4: panel pokazuje osobę, która stała
 // za zamkniętą w kolejności „›”. Dopiero po ruchu potwierdzonym przez serwer
 // — wcześniej może wyskoczyć „Przenieś mimo to” albo debrief dla tej samej
 // osoby. Po ostatniej osobie panel się zamyka z komunikatem.
 // Zasady: docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md.
 type ClosedVerb = "Odrzucono" | "Rezygnacja";
 const [afterClose, setAfterClose] = useState<{
 closedId: number;
 name: string;
 verb: ClosedVerb;
 reason: string | null;
 nextId: number;
 /** Wiersz etapu następnej osoby — po jej ruchu pasek znika. */
 nextStageId: number;
 } | null>(null);
 const advanceAfterClose = useCallback(
 (
 closed: KanbanItem,
 verb: ClosedVerb,
 after: readonly number[],
 reason: string | null,
 queueName: string | null
 ) => {
 // Rekruter zdążył otworzyć kogoś innego albo zamknąć panel — nie skaczemy.
 if (dockCandidateId !== closed.candidate_id) return;
 const live = new Set(dockOrder);
 const nextId = after.find((id) => id !== closed.candidate_id && live.has(id));
 const next = nextId != null ? locateCandidate(nextId) : null;
 const name = itemFullName(closed);
 if (nextId == null || !next) {
 closeDock();
 showActionToast(
 queueName
 ? `${verb}: ${name}. To była ostatnia osoba w kolejce „${queueName}”.`
 : `${verb}: ${name}. To była ostatnia osoba w kolejce.`,
 {
 actionLabel: "Pokaż",
 onAction: () => setDockCandidateId(closed.candidate_id),
 }
 );
 return;
 }
 setAfterClose({ closedId: closed.candidate_id, name, verb, reason, nextId, nextStageId: next.item.id });
 showInDock(nextId);
 },
 [dockCandidateId, dockOrder, locateCandidate, closeDock, showActionToast, showInDock]
 );
 // `onMoved` przychodzi po odpowiedzi serwera — czyta stan z tej chwili.
 const advanceAfterCloseRef = useRef(advanceAfterClose);
 useEffect(() => {
 advanceAfterCloseRef.current = advanceAfterClose;
 }, [advanceAfterClose]);
 useEffect(() => {
 if (afterClose && dockCandidateId !== afterClose.closedId && dockCandidateId !== afterClose.nextId) {
 setAfterClose(null);
 }
 }, [afterClose, dockCandidateId]);
 // Migawka kolejki w chwili otwarcia okna: kto stoi za zamykaną osobą
 // (od 14.10.2026 w tej samej kolumnie i z tym samym filtrem — D1).
 const dockFollowUp = useCallback(
 (closed: KanbanItem, verb: ClosedVerb): RejectFollowUp | undefined => {
 if (dockIndex < 0) return undefined;
 const after = dockOrder.slice(dockIndex + 1);
 const preview = after.length > 0 ? locateCandidate(after[0]) : null;
 return {
 stageLabel: dockItemColLabel,
 next: preview ? { name: itemFullName(preview.item), stageLabel: preview.label } : null,
 onMoved: ({ reasonLabel }) =>
 advanceAfterCloseRef.current(closed, verb, after, reasonLabel, queueLabel),
 };
 },
 [dockIndex, dockOrder, locateCandidate, dockItemColLabel, queueLabel]
 );
 const handleDockReject = useCallback(
 (options?: { notes?: string | null }) => {
 if (!dockItem || !dockItemColId || !rejectedTemplateCol) return;
 requestReject(dockItem, rejectedTemplateCol, {
 notes: options?.notes ?? null,
 followUp: dockFollowUp(dockItem, "Odrzucono"),
 });
 },
 [dockItem, dockItemColId, rejectedTemplateCol, requestReject, dockFollowUp]
 );
 const handleDockWithdraw = useCallback(() => {
 if (!dockItem) return;
 move.requestWithdraw(dockItem, { followUp: dockFollowUp(dockItem, "Rezygnacja") });
 }, [dockItem, move, dockFollowUp]);
 // „Odrzuć” w formularzu screeningu (panel „Rozwiń”) ma własny ruch —
 // ta sama migawka, ten sam skok po udanym ruchu.
 const workbenchRejectFollowUp = useCallback(
 (candidateId: number) =>
 dockItem && dockItem.candidate_id === candidateId ? dockFollowUp(dockItem, "Odrzucono") : undefined,
 [dockItem, dockFollowUp]
 );
 const dockClosedNotice =
 afterClose &&
 dockItem?.candidate_id === afterClose.nextId &&
 dockItem.id === afterClose.nextStageId
 ? {
 verb: afterClose.verb,
 name: afterClose.name,
 reason: afterClose.reason,
 onShow: () => setDockCandidateId(afterClose.closedId),
 }
 : null;
 // Osoba z panelu jest poza kolejką (zamknięta z panelu, przesunięta dalej,
 // schowana filtrem): „Wróć do kolejki” — po odrzuceniu do osoby, która
 // przejęła panel, inaczej do tej, która stała za nią w kolejce.
 const returnToQueueId =
 dockItem && dockIndex < 0
 ? afterClose && dockItem.candidate_id === afterClose.closedId
 ? afterClose.nextId
 : returnToQueueTarget(dockOrder, formerlyAfterRef.current)
 : null;
 const returnToQueueItem =
 returnToQueueId != null ? locateCandidate(returnToQueueId)?.item ?? null : null;
 // Koniec kolejki (D4): „›” jest nieaktywna, pasek mówi, że to ostatnia
 // osoba, i daje „Od pierwszej”, „Wszyscy (N)” (gdy filtr coś schował)
 // oraz „Dalej: <kolumna>” — do pierwszej kolumny na prawo, w której ktoś jest.
 const queueEnd = useMemo(() => {
 if (!queueCol || dockIndex < 0 || dockIndex !== dockOrder.length - 1) return null;
 const queueColId = colId(queueCol);
 const total = totalCountByColId.get(queueColId) ?? queueCol.count;
 const at = displayCols.findIndex((c) => colId(c) === queueColId);
 const next = at >= 0 ? nextColumnWithPeople(displayCols, at) : null;
 return {
 count: dockOrder.length,
 onFirst: dockOrder.length > 1 ? () => showInDock(dockOrder[0]) : undefined,
 showAll:
 onAddedByChange && addedBy.kind !== "all" && total > dockOrder.length
 ? { label: `Wszyscy (${total})`, onClick: () => onAddedByChange(ADDED_BY_ALL) }
 : undefined,
 next: next
 ? {
 label: `Dalej: ${boardLabelByColId.get(colId(next)) ?? columnLabel(next)} (${next.items.length})`,
 onClick: () => showInDock(next.items[0].candidate_id),
 }
 : undefined,
 };
 }, [queueCol, dockIndex, dockOrder, totalCountByColId, displayCols, showInDock, onAddedByChange, addedBy, boardLabelByColId]);

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

 // Zamknięci jako wąska kolumna obok tablicy (02.10.2026; do tego dnia chipy
 // w pasku filtrów). Każda strefa jest celem upuszczenia — odrzucenie z powodem
 // jak dotąd — a klik rozwija pełne kolumny zamkniętych na końcu tablicy.
 // Stoi POZA przewijaną tablicą: przy ośmiu kolumnach byłaby poza ekranem.
 const closedColumn =
 boardFold.closed.length > 0 ? (
 <section
 aria-label="Zamknięci"
 data-testid="board-closed-column"
 data-help="jobs.board.closed"
 className="flex shrink-0 flex-row flex-wrap items-center gap-1.5 rounded-lg border border-border bg-muted/40 p-2 text-[11px] max-lg:order-first lg:w-32 lg:flex-col lg:flex-nowrap lg:items-stretch"
 >
 <h3 className="text-sm font-medium text-foreground">Zamknięci</h3>
 <p className="text-muted-foreground max-lg:hidden">Odrzuceni i rezygnacje</p>
 {showClosed ? (
 <button
 type="button"
 onClick={() => setShowClosed(false)}
 className="rounded-md border border-border px-2 py-1 text-muted-foreground hover:bg-accent pointer-coarse:min-h-9"
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
 "flex rounded-md border border-dashed border-border transition-colors",
 snapshot.isDraggingOver && "border-destructive bg-destructive/10"
 )}
 >
 <button
 type="button"
 onClick={() => setShowClosed(true)}
 aria-label={`${label}: ${count} — pokaż kolumny zamkniętych`}
 title={`${label} — upuść tu kartę albo kliknij, żeby zobaczyć osoby`}
 className="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-muted-foreground hover:text-foreground pointer-coarse:min-h-9"
 >
 {short}
 <span className="font-semibold tabular-nums text-foreground">{count}</span>
 </button>
 <span className="hidden">{provided.placeholder}</span>
 </span>
 )}
 </Droppable>
 ))
 )}
 </section>
 ) : null;

 const viewControls = viewToggleVisible ? (
 <BoardViewControls viewMode={viewMode} onSetViewMode={setViewPreference} />
 ) : null;

 return (
 <BoardV4Context.Provider value={boardV4}>
 <div ref={boardRootRef} className="group/board relative space-y-3">
 {/* DragDropContext obejmuje też kolumnę „Zamknięci" obok tablicy — jej
 strefy są celami upuszczenia. */}
 <DragDropContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
 {/* Dok „Karta kandydata" NIE zajmuje kolumny siatki — wysuwa się z prawej
 dopiero po kliknięciu karty (przegląd UX 17.09.2026: stała trzecia kolumna
 zjadała tablicy 360 px nawet wtedy, gdy nic nie było wybrane). */}
 <div className="space-y-3">
 {renderAbove ? (
 renderAbove(viewControls)
 ) : viewControls ? (
 <div className="flex justify-end">{viewControls}</div>
 ) : null}

 <div className={cn("min-w-0 space-y-3", dockItem && dockItemColLabel !== null &&"lg:pr-[380px]")}>
 {closedJob ? (
 <ClosedJobWaitingBanner
 closedOn={closedJob.closedOn}
 reasonLabel={closedJob.reasonLabel}
 people={myWaiting.map((item) => [item.name, item.lastname].filter(Boolean).join(" ") || `Kandydat #${item.candidate_id}`)}
 onRejectFirst={
 !readOnly && rejectedTemplateCol && myWaiting.length > 0
 ? () => requestReject(myWaiting[0], rejectedTemplateCol)
 : undefined
 }
 />
 ) : null}
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

 {/* Board + „Zamknięci" obok */}
 <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
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
 // `lg:flex-1`, nie `flex-1`: poniżej `lg` opakowanie jest kolumną bez
 // określonej wysokości — tam `flex: 1 1 0%` zastąpiłoby wysokość z `style`
 // i tablica urosłaby do najdłuższej kolumny (bez własnego przewijania).
 "min-w-0 overflow-auto pb-4 min-h-[280px] lg:flex-1",
 // Na dotyku kolumna dociąga do krawędzi (17 rem przy 343 px ekranu =
 // jedna kolumna + skrawek). `proximity`, nie `mandatory`: mandatory
 // walczy z auto-scrollem @hello-pangea/dnd przy przeciąganiu karty.
 "pointer-coarse:snap-x pointer-coarse:snap-proximity",
 columnHeight == null && "h-[calc(100dvh-4rem)] md:h-[calc(100dvh-240px)]"
 )}
 style={columnHeight != null ? { height: columnHeight } : undefined}
 >
 {/* Pas kolumn (17.10.2026, zgłoszenie z filmikiem): rząd flex BEZ
 własnej wysokości (`min-h-full` = co najmniej okno tablicy), więc ma
 wysokość najdłuższej kolumny, a każda kolumna rozciąga się do niej.
 Wcześniej rzędem był sam board o stałej wysokości: kolumny kończyły się
 na dole okna, 29 kart „Screeningu” wystawało poza obrys, a po
 przewinięciu w dół pod kartą nie było pola upuszczenia „Zweryfikowanego”
 (trzeba było przewijać do góry). Pas nie przewija się sam — scroll
 zostaje na boardzie, jedynym scroll-kontenerze dla @hello-pangea/dnd. */}
 <div
 data-testid="pipeline-board-track"
 className={cn("flex min-h-full gap-3", fullPipelineDesktop && "xl:pointer-fine:gap-1")}
 >
 {boardEntries.length === 0 ? (
 <div className="flex-1 py-12 text-center text-sm text-muted-foreground">
 <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-40" />
 Brak kolumn w tej kategorii.
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
 scoreMap={scoreMap}
 criticalGapMap={criticalGapMap}
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
 group={groupByColId.get(entry.key)}
 slaDays={slaDays}
 badgeByItemId={boardFold.badgeByItemId}
 step={cproQueueColIds.has(entry.key) ? null : boardColumnStep(boardKeyByColId.get(entry.key))}
 totalCount={addedBy.kind === "all" ? undefined : totalCountByColId.get(entry.key)}
 filterEmpty={
 onAddedByChange && addedBy.kind !== "all" && (totalCountByColId.get(entry.key) ?? 0) > 0
 ? {
 text: addedByEmptyColumnText(addedBy, addedByMenuOptions),
 onShowAll: () => onAddedByChange(ADDED_BY_ALL),
 }
 : null
 }
headerAction={
 boardKeyByColId.get(entry.key) === "cv_qc" && !cproQueueColIds.has(entry.key) && canReviewAsDl && (totalCountByColId.get(entry.key) ?? entry.col.count) >= 2 && !readOnly ? (
 <Button
 type="button"
 size="sm"
 variant="outline"
 className="h-6 shrink-0 px-2 text-[11px]"
 onClick={() => setCompareOpen(true)}
 data-testid="dl-review-compare"
 data-help="jobs.board.dl-compare"
 >
 Porównaj ({totalCountByColId.get(entry.key) ?? entry.col.count})
 </Button>
 ) : boardKeyByColId.get(entry.key) === "hired" ? (
 <HiredColumnHelp />
 ) : null
 }
 // „Przejrzyj po kolei (N)” w miejscu tekstu „co tu robisz” — tylko
 // u Delivery Leada tej rekrutacji i od dwóch gotowych osób (jedną
 // otwiera przycisk na karcie). Nic nie dochodzi nad tablicą.
 purposeAction={
 boardKeyByColId.get(entry.key) === "cv_qc" && !cproQueueColIds.has(entry.key) && viewerOwnsDlReview && canReviewAsDl && !readOnly && dlReadyItems.length >= 2 ? (
 <button
 type="button"
 onClick={startReviewSequence}
 data-testid="dl-review-sequence-start"
 className="min-w-0 truncate text-left font-semibold leading-snug text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
 >
 Przejrzyj po kolei ({dlReadyItems.length})
 </button>
 ) : null
 }
 headerExtra={contractCountsByColId.has(entry.key) ? (
 <ContractStepChips counts={contractCountsByColId.get(entry.key)!} />
 ) : null}
 purpose={cproQueueColIds.has(entry.key) ? "Wrzuca osoba od Cpro" : boardColumnPurpose(boardKeyByColId.get(entry.key), {
 cproEnabled,
 hired: totalCountByColId.get(entry.key) ?? entry.col.count,
 headcount: workbenchContext?.headcount ?? null,
 })}
 {...(boardLabelByColId.has(entry.key)
 ? { titleOverride: boardLabelByColId.get(entry.key) }
 : {})}
 />
 ))}
 </>
 )}
 </div>
 </div>
 {closedColumn}
 </div>
 </div>

 </div>
 </DragDropContext>

 {((dockItem && dockItemColLabel !== null) || dlReviewTask) && (
 <PersonPanelShell
 size={panelSize}
 chromeTop={chromeTop}
 // Klik w tło zamyka najwyższą warstwę: przegląd, rozwinięcie, kartę.
 onBackdropClick={reviewOpen ? closeDlReview : workbenchOpen ? collapseWorkbench : closeDock}
 >
 {dockItem && dockItemColLabel !== null && (
 // Pod przeglądem dok jest UKRYTY, nie odmontowany: niewysłana
 // notatka, otwarte sekcje i miejsce powrotu fokusu muszą przeżyć.
 <div
 className="flex min-h-0 flex-1 flex-col focus:outline-none"
 data-testid="person-panel-dock"
 tabIndex={-1}
 hidden={reviewOpen}
 inert={reviewOpen || undefined}
 >
 <PersonPanelErrorBoundary key={dockItem.candidate_id} onClose={closeDock}>
 <PipelineCandidateDock
 key={dockItem.candidate_id}
 item={dockItem}
 noteFill={noteFill}
 jobId={jobId}
 onOpenQc={() => setQcStageId(dockItem.id)}
 onTake={readOnly ? undefined : () => void takeCandidate(dockItem)}
 clientId={clientId ?? null}
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
 closedNotice={dockClosedNotice}
 onReturnToQueue={returnToQueueItem ? () => openDock(returnToQueueItem) : undefined}
 queueLabel={queueLabel}
 addedByMenu={
 onAddedByChange
 ? { options: addedByMenuOptions, value: addedBy, onChange: onAddedByChange }
 : undefined
 }
 queueEnd={queueEnd}
 nextAction={dockNextAction}
 primaryTarget={dockPrimaryMove?.target ?? null}
 primaryBlocked={dockPrimaryMove?.blocked ?? null}
 onAdvance={readOnly ? undefined : () => onAdvance(dockItem)}
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
 onClientAccept={
 onClientAccept && dockHostKey === "client_interview" ? () => onClientAccept(dockItem) : undefined
 }
 clientAcceptance={dockHostKey === "contract" ? (dockItem.client_acceptance ?? null) : null}
 onUndoClientAcceptance={
 !readOnly && clientInterviewHost && boardFold.badgeByItemId.get(dockItem.id) === "acceptance"
 ? () => void undoClientAccept(dockItem)
 : undefined
 }
 onOpenWorkbench={
 workbenchContext
 ? (section) => openWorkbench(dockItem.candidate_id, section)
 : undefined
 }
 expanded={workbenchOpen}
 split={screeningSplit}
 onToggleExpanded={workbenchContext && kanbanQueryState ? toggleWorkbench : undefined}
 hidePrimaryMove={
 workbenchOpen &&
 dockRow != null &&
 workbenchSectionOwnsMove({
 row: dockRow,
 section: activeWorkbench.section,
 columns: stageCols,
 readOnly,
 budgetHourly: jobBudgetHourlyValue ?? null,
 })
 }
 workbench={
 activeWorkbench && dockRow && workbenchContext && kanbanQueryState ? (
 <PersonWorkbenchTabs
 row={dockRow}
 jobId={jobId}
 columns={stageCols}
 readOnly={readOnly}
 canWriteClientRate={canWriteClientRate}
 section={activeWorkbench.section}
 onSectionChange={(section) =>
 setWorkbench((prev) => (prev ? { ...prev, section } : prev))
 }
 workbenchContext={{
 ...workbenchContext,
 jobTitle: jobTitle ?? undefined,
 cproEnabled,
 budgetHourly: jobBudgetHourlyValue ?? null,
 kanbanQueryState,
 onTake: readOnly ? undefined : (item) => void takeCandidate(item),
 rejectFollowUp: workbenchRejectFollowUp,
 onForwarded: onWorkbenchForwarded,
 forwardedCandidateId,
 nextInColumn,
 openPerson: openPersonInPanel,
 noteFill,
 onClientAccept: onClientAccept
 ? (candidateId, note) => {
 const it = cols.flatMap((c) => c.items).find((i) => i.candidate_id === candidateId);
 if (it) openClientAccept(it, note);
 }
 : undefined,
 }}
 />
 ) : null
 }
 />
 </PersonPanelErrorBoundary>
 </div>
 )}
 {dlReviewTask ? (
 <DlReviewBody
 task={dlReviewTask}
 canSendToClient={dlReviewCanSend}
 onClose={closeDlReview}
 layout="panel"
 // Kolejka „po kolei”: po decyzji następna osoba zamiast zamknięcia;
 // poza kolejką przegląd zamyka się jak dotąd.
 {...(sequenceActive
 ? {
 onDecided: advanceSequence,
 sequence: {
 position: sequencePosition,
 total: sequenceTotal,
 onSkip: skipSequence,
 onFinish: closeDlReview,
 },
 }
 : {})}
 />
 ) : null}
 </PersonPanelShell>
 )}

 <DlReviewQueueDialog
 jobId={compareOpen ? jobId : null}
 jobTitle={jobTitle ?? null}
 open={compareOpen}
 onOpenChange={setCompareOpen}
 onReview={openDlReviewForTask}
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
 <ClientAcceptedDialog
 open={acceptFor !== null}
 onOpenChange={(open) => {
 if (!open) setAcceptFor(null);
 }}
 jobId={jobId}
 candidateId={acceptFor?.item.candidate_id ?? 0}
 candidateName={`${acceptFor?.item.name ?? ""} ${acceptFor?.item.lastname ?? ""}`.trim() || "Kandydat"}
 initialNote={acceptFor?.note ?? null}
 context={jobTitle ?? null}
 acceptanceStageDefId={acceptanceStageCol?.stage_def_id ?? null}
 onConfirm={confirmClientAccept}
 />
 {undoAcceptanceDialog}
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
 onMoveNext={readOnly ? undefined : (result) => handleQcMoveNext(result.candidate_id)}
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
 candidateId={debriefFor.candidateId}
 candidateName={debriefFor.name}
 jobId={jobId}
 onSaved={() => {
 setDebriefFor(null);
 resumeMoveNext();
 }}
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

 {minimumPrompt && (
 <MinimumFieldsDialog
 open={true}
 candidateId={minimumPrompt.item.candidate_id}
 jobId={jobId}
 candidateName={itemFullName(minimumPrompt.item)}
 actionLabel={minimumPrompt.mode === "resume" ? "Zapisz" : "Zapisz i przesuń"}
 onDone={() => {
 const prompt = minimumPrompt;
 setMinimumPrompt(null);
 if (prompt.mode === "resume") {
 resumeMoveNext();
 return;
 }
 const dst = prompt.dst ?? boardFold.columns.find((f) => f.key === "verified")?.host;
 const src = cols.find((c) => c.items.some((i) => i.id === prompt.item.id));
 const srcColId = prompt.srcColId ?? (src ? colId(src) : null);
 if (dst && srcColId) requestMove(prompt.item, srcColId, dst);
 }}
 onOpenFull={() => {
 const item = minimumPrompt.item;
 setMinimumPrompt(null);
 openScreeningFor(item);
 }}
 onClose={() => {
 const resume = minimumPrompt.mode === "resume";
 setMinimumPrompt(null);
 if (resume) resumeMoveNext();
 }}
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
 candidateId={screeningPrompt.candidateId}
 jobId={jobId}
 candidateName={screeningPrompt.candidateName}
 jobBudgetHourly={jobBudgetHourlyValue ?? null}
 readOnly={readOnly}
 // Zapis zamyka okno (`onOpenChange`), a ono wraca do „Przesuń dalej”.
 onMoved={() => void refreshBoardFromServer()}
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
