"use client";

/**
 * PipelineCandidateDock — dok „Karta w procesie" (krok 04 Pipeline, program
 * „flow w języku C2", PR 3/7).
 *
 * Ten sam język co `JobMatchDock` w `/jobs/[id]/page.tsx` (warsztat C2):
 * dok obok tablicy, akcje na dole, zakładki montowane leniwie (dopiero po
 * kliknięciu). Ruch na etap NIE ma własnej logiki — woła `onMoveTo`, które
 * `KanbanBoardV2` podłącza do `requestMove` (ta sama gałąź co drag&drop:
 * modal stawki dla „Zweryfikowany", stawki do klienta dla „CV Wysłane",
 * potwierdzenie dla „Zatrudniony", powód dla etapów terminalnych).
 *
 * Fala 3 („parytet z makietami") dokłada oś czasu etapu, nawigator kart
 * i główną akcję „Przenieś na etap: <następny>". Wiersz „następna akcja"
 * przychodzi GOTOWY z tablicy (`lib/pipeline-next-action.ts`) — dok nie liczy
 * go po swojemu, bo dwie kopie tej reguły rozjechałyby się przy pierwszej
 * zmianie progu. Backend nadal nie ma pola „next action": to zdanie o ETAPIE
 * („na tym etapie następnym krokiem jest X"), nie zmyślony fakt o kandydacie.
 */

import {
  ChampionInsightsDigest,
  ExperienceChips,
} from "@/components/champion/ChampionBriefForRecruiters";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarPlus,
  Ban,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  ClipboardCheck,
  Clock,
  Download,
  ExternalLink,
  FileDown,
  FileSignature,
  FileText,
  HelpCircle,
  Loader2,
  Mail,
  Maximize,
  Maximize2,
  Minimize,
  Minimize2,
  MoreHorizontal,
  Pencil,
  PhoneOff,
  Plus,
  Undo2,
  Send,
  Sparkles,
  Trophy,
  UserPlus,
  UserX,
  X,
} from "lucide-react";

import { PreContractRequestDialog } from "@/components/v2/person/pre-contract/PreContractDialogs";
import { invalidatePreContract, preContractReadOnly } from "@/lib/api/preContracts";
import api, {
  candidatesApi,
  candidateStageCvApi,
  extractErrorMsg,
  type CandidateBlacklistInfo,
  type ChampionProfile,
  type CVOriginalSnapshot,
  type RateUnit,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import { fetchStageCvFile, fetchStageCvPdf } from "@/lib/stage-cv-file";
import { useStageBrandedCv } from "@/hooks/useStageBrandedCv";
import { useToast } from "@/components/Toast";
import { MentionTextarea } from "@/components/v2/forms/MentionTextarea";
import { Badge } from "@/components/ui/badge";
import { PairOwnerLine } from "@/components/v2/jobs/PairOwnerLine";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AddedByMenuContent, type AddedByMenuProps } from "@/components/v2/jobs/AddedByFilter";
import { readNoteDraft, writeNoteDraft } from "@/lib/note-drafts";
import { cn, formatDate } from "@/lib/utils";
import { EmploymentPopoverPill } from "@/components/v2/employment/EmploymentNotice";
import {
  BlacklistDialog,
  BlacklistPopoverPill,
} from "@/components/v2/candidate-profile/BlacklistDialogs";
import { useAuthStore } from "@/store/auth";
import { hasPermission } from "@/lib/permissions";
import { DlMatchDialog } from "@/components/v2/recruitment/dl-review/DlMatchDialog";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import type { ClientRateUnit } from "@/lib/person-facts";
import { encodeJobBackRef } from "@/lib/url-filters";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { candidateNoteItems, useCandidateNotes } from "@/components/v2/pages/candidate-notes-query";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import { type KanbanColumn, type KanbanItem } from "@/components/v2/pages/kanban-shared";
import { DockClosedReason } from "@/components/v2/jobs/DockClosedReason";
import { DockAutofillReason } from "@/components/v2/jobs/DockAutofillReason";
import { closedReason } from "@/lib/closed-reason";
import { useNoteFillAvailable, type NoteFillChannel } from "@/lib/note-fill-channel";
import type { NextAction } from "@/lib/pipeline-next-action";
import { DockCallCheatsheet } from "@/components/v2/jobs/DockCallCheatsheet";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { CVShareLinkModal } from "@/components/v2/modals/CVShareLinkModal";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { CV_CLIENT_LINKS_UI_ENABLED } from "@/lib/cv-generator";
import { stageCvStatus } from "@/lib/cv-to-client";
import { CvGeneratorDialog } from "@/components/v2/cv-generator/CvGeneratorDialog";
import { CvQcDialog } from "@/components/v2/recruitment/CvQcDialog";
import { DebriefRequiredDialog } from "@/components/v2/recruitment/DebriefRequiredDialog";
import { DockNextStage } from "@/components/v2/jobs/DockNextStage";
import { DockStageFold, NextStageSummary } from "@/components/v2/jobs/DockStageFold";
import { ScreeningLegacyText, ScreeningSummaryView } from "@/components/v2/screening-form/ScreeningSummaryView";
import {
  MOVE_REQUIREMENTS_PREFIX,
  useMoveRequirements,
  type MoveRequirementAction,
} from "@/lib/api/moveRequirements";
import { recommendationCardQueryKey } from "@/lib/api/recommendationCards";
import { screeningFormQueryKey, useScreeningFormState } from "@/lib/api/screeningForm";
import { screeningSectionSummary } from "@/lib/screening-summary";
import {
  companyCvSentence,
  dockOriginalCv,
  pairCompanyCv,
  originalCvSentence,
  withoutQuarantinedCv,
  type DockProfileCvDoc,
} from "@/lib/dock-cv-summary";
import { useCvQc, type QcResult } from "@/lib/api/cvQc";
import { formatClientRate } from "@/lib/board-card-badges";
import { CONTRACT_PANEL_STAGES, DockContractSteps } from "@/components/v2/jobs/DockContractSteps";
import { countForm, qcWarningsText } from "@/lib/cv-qc";
import {
  acceptanceLine,
  acceptanceTitle,
  longDay,
  type ClientAcceptanceBadge,
} from "@/lib/client-acceptance";
import type { CandidateDocument } from "@/components/v2/files/FilePreviewModal";
import { DockFollowupBlock } from "@/components/v2/followups/DockFollowupBlock";
import { DockInterviewCycle } from "@/components/v2/jobs/DockInterviewCycle";
import { DockLoadError } from "@/components/v2/jobs/workbench-chrome";
import { PinnedCandidateNotes } from "@/components/v2/recruitment/PinnedCandidateNotes";
import { hourlyText } from "@/lib/candidate-rate";
import {
  clientRateNoteCaption,
  expectedRateHintCaption,
  expectedRateHintText,
  fetchRecruitmentRateHints,
  recruitmentRateHintsQueryKey,
} from "@/lib/api/recruitmentRateHints";
import { sentLine, useClientRateHistory } from "@/lib/api/clientRateHistory";
import { downloadCoverSheet, useCoverSheet } from "@/lib/api/coverSheet";
import { canViewClientRate } from "@/lib/client-rate-access";
import { availabilityText, onsiteText } from "@/lib/person-facts";
import { contractAvailability, contractAvailabilityText } from "@/lib/contract-availability";
import { dockNotesSummary, splitPersonNotes } from "@/components/v2/person/notes-by-recruitment";
import { PersonContactLine } from "@/components/v2/person/PersonContactLine";
import { PersonFacts, RateWithBudget } from "@/components/v2/person/PersonFacts";
import { NewInBasePill, type CandidateInBase } from "@/components/v2/person/PersonInBase";
import { PersonNotesHistory } from "@/components/v2/person/PersonNotesHistory";
import { WorkbenchBelowTabsContext } from "@/components/v2/person/WorkbenchBelowTabs";
import { RateChangeBanner } from "@/components/v2/rate-change/RateChangeBanner";
import { ClientRateChangeDialog } from "@/components/v2/rate-change/ClientRateChangeDialog";
import { RateChangeDialog } from "@/components/v2/rate-change/RateChangeDialog";
import { rateChangeStatusLabel } from "@/lib/rate-change";
import { useNoAnswerNote } from "@/hooks/useNoAnswerNote";
import { useCapability } from "@/hooks/useCapability";
import { CvFileDropTarget, StageCvUploadTile, useStageCvUpload } from "@/components/v2/person/StageCvUpload";
import { DockCvFreshness, profileReadPending } from "@/components/v2/jobs/DockCvFreshness";
import { CompanyCvStaleNotice } from "@/components/v2/recruitment/CompanyCvStaleNotice";
import { ClientFormCard } from "@/components/v2/recruitment/client-form/ClientFormCard";
import {
  ClientQuestionsNoteHint,
  DockClientInterviewQuestions,
} from "@/components/v2/jobs/DockClientInterviewQuestions";
import { extractClientQuestions, looksLikeClientQuestions } from "@/lib/client-question-notes";

// Edytor brandowanego CV jest ciężki (rich text) — leniwy import jak w
// CandidateDetailV2, żeby nie puchła zakładka Pipeline dla osób, które go
// nigdy nie otworzą.
// Radix zamyka menu i oddaje fokus PO `onSelect` — akcja otwierająca modal
// (stawka, powód odrzucenia) musi poczekać jeden tick, inaczej zwrot fokusu
// zamyka świeżo otwarty dialog. Kopia z `JobDetailCompactHeader`.
const deferMenuAction = (action: () => void) => {
  window.setTimeout(action, 0);
};

// Podgląd CV z profilu (PDF/DOCX) — ten sam modal co karta CV na profilu
// kandydata; leniwie, bo niesie podgląd DOCX i pdf.js.
const FilePreviewModal = dynamic(
  () => import("@/components/v2/files/FilePreviewModal").then((m) => m.FilePreviewModal),
  { ssr: false }
);

const CVBrandedEditModal = dynamic(
  () =>
    import("@/components/v2/modals/CVBrandedEditModal").then(
      (m) => m.CVBrandedEditModal
    ),
  { ssr: false }
);

export interface PipelineMoveTarget {
  col: KanbanColumn;
  blockedReason: string | null;
}

type DockTab = "process" | "screening" | "cv" | "match" | "notes";

/**
 * Panel osoby (makieta 22.09.2026): zamiast pięciu zakładek — sekcje zwijane
 * z jednozdaniowym podsumowaniem. Otwarta jest sekcja właściwa dla etapu
 * („Teraz"), reszta czeka zwinięta; każdą da się rozwinąć obok innych.
 */
const DOCK_SECTION_LABEL: Record<DockTab, string> = {
  process: "W procesie",
  screening: "Screening",
  cv: "CV",
  match: "Dopasowanie",
  notes: "Notatki",
};

/**
 * Sekcja „Teraz" wg etapu karty (legacy-enum `stage`). Pipeline v4
 * (23.09.2026): screening robi się w kolumnie „Nowi", więc wszystkie jej etapy
 * (posting / new / prep_call / screening) otwierają arkusz screeningu.
 */
export function nowSectionForStage(stage: string | null | undefined): DockTab {
  switch (stage) {
    case "posting":
    case "new":
    case "screening":
    case "prep_call":
      return "screening";
    case "verified":
      return "cv";
    default:
      return "process";
  }
}

function DockSection({
  id,
  label,
  summary,
  isNow,
  open,
  onToggle,
  children,
}: {
  id: DockTab;
  label: string;
  summary: ReactNode;
  isNow: boolean;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-lg border",
        isNow ? "border-primary/40 bg-primary/5" : "border-border",
      )}
      aria-labelledby={`dock-section-${id}`}
    >
      <button
        type="button"
        id={`dock-section-${id}`}
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span className="text-xs font-semibold text-foreground">{label}</span>
        {isNow ? (
          <span className="rounded bg-primary px-1.5 text-[10px] font-semibold uppercase tracking-wide text-primary-foreground">
            Teraz
          </span>
        ) : null}
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
          {open ? null : summary}
        </span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>
      {open ? <div className="px-3 pb-3">{children}</div> : null}
    </section>
  );
}

/** Wycinek `CandidateResponse`, którego dok naprawdę używa. `candidatesApi.get`
 *  nie jest typowane, więc typujemy tu wprost — zamiast `any`. */
interface CandidateDetail extends CandidateInBase {
  email?: string | null;
  phone?: string | null;
  city?: string | null;
  location?: string | null;
  status?: string | null;
  /** Wpis czarnej listy „u nas” — tylko przy `status === "blacklisted"`. */
  blacklist?: CandidateBlacklistInfo | null;
  availability_status?: string | null;
  availability_date?: string | null;
  notice_period?: number | null;
  notice_period_unit?: "days" | "weeks" | "months" | null;
  max_onsite_days_per_week?: number | null;
  linkedin_current_title?: string | null;
  linkedin_current_company?: string | null;
  cv_filename?: string | null;
  /** Odczyt AI głównego CV — linia „AI czyta nowe CV” po wgraniu z rekrutacji. */
  cv_parsed_at?: string | null;
  /** Tu tylko znacznik kwarantanny tożsamości (`_identity_quarantine_source`). */
  cv_extracted_data?: unknown;
}

/** Stawka kandydata pary — do podglądu marży w oknie stawki do klienta. */
function dockCandidateRate(item: KanbanItem): { value: number; unit: RateUnit } | null {
  const value = Number(item.expected_rate_value);
  if (item.expected_rate_value == null || item.expected_rate_value === "" || !Number.isFinite(value)) {
    return null;
  }
  return { value, unit: item.expected_rate_unit ?? "hourly" };
}

function daysLabel(n: number): string {
  return `${n} ${Math.abs(n) === 1 ? "dzień" : "dni"}`;
}

/** Wiersz osi czasu etapu — kropka + tytuł + data + kto/skąd. */
function TimelineEntry({
  tone = "done",
  title,
  when,
  who,
}: {
  tone?: "done" | "now";
  title: string;
  when?: string | null;
  who?: string | null;
}) {
  return (
    <li className="grid grid-cols-[10px_minmax(0,1fr)] gap-x-2">
      <span
        className={cn(
          "mt-1.5 h-2 w-2 rounded-full",
          tone === "now" ? "bg-primary ring-2 ring-primary/20" : "bg-border"
        )}
        aria-hidden="true"
      />
      <span className="min-w-0 pb-2">
        <span className="block font-medium text-foreground">{title}</span>
        {when && <span className="block text-muted-foreground">{when}</span>}
        {who && <span className="block text-muted-foreground">{who}</span>}
      </span>
    </li>
  );
}

export interface PipelineCandidateDockProps {
  item: KanbanItem;
  /** D3: „Zapisz notatkę i wypełnij formularz” — kanał do formularza screeningu (14.10.2026). */
  noteFill?: NoteFillChannel;
  jobId: number;
  currentStageLabel: string;
  /** Tytuł rekrutacji — nagłówki modali CV i zakładka „Dopasowanie". Bez
   *  niego fallback „Rekrutacja #id"; nigdy nazwa etapu (to inna rzecz). */
  jobTitle?: string;
  matchScore?: number | null;
  scoresLoading?: boolean;
  moveTargets: PipelineMoveTarget[];
  readOnly: boolean;
  contactFeatureEnabled: boolean;
  canReject: boolean;
  /**
   * Powód, dla którego „Odrzuć z powodem" jest dziś zablokowane (np. tablica
   * tylko do odczytu). Przycisk
   * zostaje widoczny i wyszarzony z powodem, zamiast odbić się o 409.
   */
  rejectBlockedReason?: string | null;
  /**
   * Aktualny budżet PLN/h rekrutacji (`effective_budget_hourly`) — odznaka
   * „Ponad budżet" (informacja). `null` = brak budżetu.
   */
  budgetHourly?: number | null;
  /** Pozycja osoby w kolejce strzałek (1-based) i długość kolejki. Od
   *  14.10.2026 kolejka to JEDNA kolumna Tablicy z filtrem „Kto dodał”
   *  (`docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md („Kolejka w kolumnie…”)`).
   *  Bez nich nawigator „‹ N z M ›" się nie renderuje — nie zgadujemy pozycji. */
  position?: number | null;
  total?: number;
  /** Po czym chodzą strzałki: „Nowi”, „Nowi · dodani przez Ciebie”. */
  queueLabel?: string | null;
  /** Etykieta kolejki otwiera menu „Kto dodał” (w „Rozwiń” Tablica jest
   *  zasłonięta). Bez niego etykieta jest zwykłym tekstem. */
  addedByMenu?: AddedByMenuProps;
  /** Ostatnia osoba w kolejce (D4): pasek z „Od pierwszej”, „Wszyscy (N)”
   *  (filtr coś schował) i „Dalej: <kolumna> (N)”. */
  queueEnd?: {
    count: number;
    onFirst?: () => void;
    showAll?: { label: string; onClick: () => void };
    next?: { label: string; onClick: () => void };
  } | null;
  onSelectPrevious?: () => void;
  onSelectNext?: () => void;
  /** Pasek po odrzuceniu albo rezygnacji poprzedniej osoby z panelu — panel
   *  przeszedł do tej osoby sam (13.10.2026). „Pokaż” wraca do poprzedniej. */
  closedNotice?: {
    verb: "Odrzucono" | "Rezygnacja";
    name: string;
    reason: string | null;
    onShow: () => void;
  } | null;
  /** Osoba właśnie zamknięta z panelu (poza kolejnością Tablicy): zamiast
   *  napisu „Panel osoby” — „Wróć do kolejki” do osoby, która była następna. */
  onReturnToQueue?: () => void;
  /** Wiersz „co dalej" policzony przez tablicę (`nextActionFor`). */
  nextAction?: NextAction | null;
  /** Pierwszy DOZWOLONY etap po bieżącym — główna akcja doku. */
  primaryTarget?: KanbanColumn | null;
  /**
   * Etap blokujący drogę naprzód (weto HM) i powód — gdy jest, dok zamiast
   * akcji „naprzód" pokazuje wyszarzony krok z powodem, a nie objazd weta.
   * Wynik `primaryForwardMove` z `lib/pipeline-flow.ts`.
   */
  primaryBlocked?: { col: KanbanColumn; reason: string } | null;
  /**
   * Otwiera „Przesuń dalej” Tablicy dla tej osoby — przycisk w stopce okna
   * QC CV. Bez niego okno QC nie ma przycisku ruchu.
   */
  onAdvance?: () => void;
  onClose: () => void;
  onMoveTo: (col: KanbanColumn) => void;
  /**
   * Ruch na etap szablonu wskazany przez serwer w ramce „Następny etap”
   * (przekazanie DL na „QC CV”, kolejka Cpro u Nordei).
   */
  onMoveToStageDef?: (stageDefId: number) => void;
  onOpenScreening: (stageId: number, name: string) => void;
  /** „Odrzuć z powodem". `notes` — notatka startowa okna (np. naruszone
   *  „Odpada, gdy…" z ramki „Następny etap"). */
  onReject: (options?: { notes?: string | null }) => void;
  /** Pipeline v4: „Zrezygnował" — rezygnacja kandydata z powodem. */
  onWithdraw?: () => void;
  /** Pipeline v4: DL wpisuje terminy od klienta prosto z osoby w „CV wysłane"
   *  (terminy same przenoszą kartę na „Rozmowę u klienta"). */
  onAddClientSlots?: () => void;
  /**
   * PR 4 (04.10.2026): okno QC CV dla tej osoby — dok pokazuje wynik QC już na
   * „Zweryfikowanym”, zanim rekruter przekaże kartę dalej.
   */
  onOpenQc?: () => void;
  /** PR 5: „Biorę” z panelu — ta sama blokada 12 h co przycisk na karcie. */
  onTake?: () => void;
  /** PR 6: klient rekrutacji — link do jego zamówień w kroku „Umowa”. */
  clientId?: number | null;
  /**
   * Pełny warsztat osoby (dawna „Tabela": CV do klienta ze stawką i linkiem,
   * rozmowy z werdyktem HM, umowa) — szeroki panel nad Tablicą. Brak = bez
   * przycisków warsztatu (np. harness).
   */
  onOpenWorkbench?: (section: WorkbenchSection) => void;
  /**
   * Odznaki etapu (Tablica 22.09.2026): „DZ ✓", „Gotowy do Cpro" (Nordea),
   * „podpisana". Włączenie = ruch na etap-odznakę, wyłączenie = powrót na
   * etap kolumny — liczy to tablica, dok tylko pokazuje przełączniki.
   */
  /**
   * Jeden panel osoby (04.10.2026): „Rozwiń” poszerza panel na całe okno
   * (podgląd po lewej) i pod tą samą głową pokazuje pełne narzędzia osoby
   * (`workbench`) zamiast sekcji.
   * Sekcje i narzędzia zostają zamontowane — wpisany tekst przeżywa zmianę.
   */
  expanded?: boolean;
  onToggleExpanded?: () => void;
  /** Zakładki pełnych narzędzi (`PersonWorkbenchTabs`) — gdy były otwarte. */
  workbench?: ReactNode;
  /**
   * Otwarta zakładka ma własny przycisk ruchu — ramka „Następny etap” znika.
   * W pozostałych zakładkach rozwiniętego panelu ramka stoi pod paskiem
   * zakładek, w zwiniętej linii „Warunki i następny etap” (09.10.2026).
   */
  hidePrimaryMove?: boolean;
  /**
   * Panel dzielony (0424): formularz screeningu albo profil przed telefonem
   * z podglądem obok. „Biorę” i „Nie odebrał” stoją wtedy w profilu przed
   * telefonem (bez dubla w głowie panelu), a przypięte notatki są zwinięte —
   * przy 1280×720 każda linia wysokości się liczy.
   */
  split?: boolean;
  badgeToggles?: ReadonlyArray<{
    key: string;
    label: string;
    active: boolean;
    disabledReason: string | null;
    onToggle: () => void;
  }>;
  /**
   * D1 (16.10.2026): „Klient zaakceptował” — okno akceptacji dla osoby
   * w „Rozmowie u klienta”. Brak = przycisku nie ma (inna kolumna, szablon
   * bez etapu „Akceptacja”, tylko odczyt).
   */
  onClientAccept?: () => void;
  /** Akceptacja klienta tej osoby — tylko w kolumnie „Akceptacja i umowa”. */
  clientAcceptance?: ClientAcceptanceBadge | null;
  /** „Cofnij akceptację klienta” w menu „⋯” — osoba stoi na etapie akceptacji. */
  onUndoClientAcceptance?: () => void;
}

type WorkbenchSection = "cv" | "screening" | "interviews" | "contract" | "notes";

/** Etapy, na których pierwszą pracą jest telefon (kolumny „Nowi” i „Screening”). */
const ENTRY_STAGES: ReadonlySet<string> = new Set(["posting", "new", "screening", "prep_call"]);

/**
 * Zdanie QC CV w doku na „Zweryfikowanym” (PR 4, 04.10.2026). Od 18.10.2026
 * dopisuje nieblokujące uwagi tą samą regułą co plakietka karty
 * (`qcCountsText`), żeby karta i panel mówiły te same liczby.
 */
export function earlyQcSentence(
  loading: boolean,
  result: Pick<QcResult, "passed" | "blocking_failed" | "override"> & { warnings_count?: number } | null,
): string {
  if (loading) return "QC CV: sprawdzam…";
  if (!result) return "QC CV: nie udało się sprawdzić";
  const warnings = result.warnings_count ?? 0;
  const tail = warnings > 0 ? ` · ${qcWarningsText(warnings)} (nie blokuje)` : "";
  if (result.passed) {
    return result.override
      ? "QC CV: przepuszczone przez Delivery Leada"
      : `QC CV: bez blokad — można przekazać dalej${tail}`;
  }
  const n = result.blocking_failed;
  return `QC CV: ${countForm(n, ["rzecz", "rzeczy", "rzeczy"])} do poprawy przed wysłaniem${tail}`;
}

function WorkbenchLink({
  onClick,
  children,
}: {
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
    >
      {children} <span aria-hidden="true">→</span>
    </button>
  );
}

/** Rzadsze akcje osoby — CV, wiadomość, pełny profil — w menu „⋯". */
function PersonMoreMenu({
  onOpenCv,
  onSendEmail,
  profileHref,
  onUndoClientAcceptance,
  onBlacklist,
  onPreContract,
  onSendAlso,
  onAddAlso,
}: {
  onOpenCv: () => void;
  onSendEmail: () => void;
  profileHref: string;
  onUndoClientAcceptance?: () => void;
  /** „Czarna lista…” (17.10.2026) — to samo okno co w menu profilu. */
  onBlacklist?: () => void;
  /** 0506: umowa przedwstępna — zakładka „Umowa” albo okno prośby. */
  onPreContract?: () => void;
  /** Match (22.10.2026): DL wysyła osobę także do innych swoich rekrutacji. */
  onSendAlso?: () => void;
  /**
   * „Dodaj też do rekrutacji…” (decyzja Artura 29.10.2026, wariant B): osoba
   * na dowolnym etapie trafia do „Nowych” innej rekrutacji — to samo okno co
   * „Przypisz do rekrutacji” na profilu.
   */
  onAddAlso?: () => void;
}) {
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="outline" aria-label="Więcej akcji osoby">
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuItem onSelect={() => deferMenuAction(onOpenCv)}>
          <FileText className="h-3.5 w-3.5" /> Otwórz CV
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => deferMenuAction(onSendEmail)}>
          <Mail className="h-3.5 w-3.5" /> Wyślij wiadomość
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={profileHref}>
            <ExternalLink className="h-3.5 w-3.5" /> Pełny profil
          </Link>
        </DropdownMenuItem>
        {onAddAlso && (
          <DropdownMenuItem onSelect={() => deferMenuAction(onAddAlso)} data-testid="dock-add-also">
            <Plus className="h-3.5 w-3.5" /> Dodaj też do rekrutacji…
          </DropdownMenuItem>
        )}
        {onSendAlso && (
          <DropdownMenuItem onSelect={() => deferMenuAction(onSendAlso)} data-testid="dock-send-also">
            <Send className="h-3.5 w-3.5" /> Wyślij też do…
          </DropdownMenuItem>
        )}
        {onPreContract && (
          <DropdownMenuItem onSelect={() => deferMenuAction(onPreContract)} data-testid="dock-pre-contract">
            <FileSignature className="h-3.5 w-3.5" /> Umowa przedwstępna…
          </DropdownMenuItem>
        )}
        {onUndoClientAcceptance && (
          <DropdownMenuItem
            onSelect={() => deferMenuAction(onUndoClientAcceptance)}
            className="text-warning focus:text-warning"
          >
            <Undo2 className="h-3.5 w-3.5" /> Cofnij akceptację klienta
          </DropdownMenuItem>
        )}
        {onBlacklist && (
          <DropdownMenuItem
            onSelect={() => deferMenuAction(onBlacklist)}
            className="text-destructive focus:text-destructive"
          >
            <Ban className="h-3.5 w-3.5" /> Czarna lista…
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const NOTE_KEYS_HINT = "Enter dodaje notatkę · Shift+Enter nowa linia";
/** Etapy po akceptacji DL-a, z których DL może wysłać osobę też gdzie indziej. */
const SEND_ALSO_STAGES = new Set(["cv_sent", "client_interview", "acceptance", "negotiation"]);

/** Jednostka stawki do klienta z karty — „Wyślij też do…” wysyła ją bez zmian. */
export function sendAlsoUnit(unit: string | null | undefined): ClientRateUnit {
  return unit === "daily" || unit === "monthly" ? unit : "hourly";
}
/** Akcje paska „Koniec kolejki” (14.10.2026). */
const QUEUE_END_ACTION =
  "shrink-0 rounded-md px-1.5 py-0.5 font-semibold text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:p-2";
const NOTE_KEYS_HINT_BIG = "Enter nowa linia · Ctrl+Enter dodaje";

/**
 * Pole notatki na dole panelu osoby (12.10.2026, zgłoszenie rekruterów: jedna
 * linia 230 px bez możliwości powiększenia). Trzy stany:
 * - zwarty — puste pole bez fokusu: jedna linia i ikona wysyłki, jak dotąd,
 * - otwarty — fokus w kompozytorze albo wpisany tekst: pole na całą szerokość
 *   rośnie z tekstem (z fokusem 3–10 linii, bez fokusu najwyżej 3, żeby długi
 *   szkic nie zabierał sekcjom doku miejsca na laptopie 1280 × 650),
 * - duży — „Powiększ”: pole wypełnia panel pod paskiem osoby, a Enter robi
 *   nową linię, bo długa notatka z rozmowy nie może wysłać się w połowie.
 * Margines 92 px „na maskotkę Jarvisa” zniknął: od 04.10.2026 maskotka chowa
 * się, gdy panel osoby jest otwarty (`globals.css`).
 */
function DockNoteComposer({
  value,
  onChange,
  onSubmit,
  onSubmitAndFill,
  pending,
  jobId,
  big,
  onBigChange,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** D3 (14.10.2026): formularz screeningu tej osoby czeka na notatkę. */
  onSubmitAndFill?: () => void;
  pending: boolean;
  jobId: number;
  big: boolean;
  onBigChange: (big: boolean) => void;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const fieldRef = useRef<HTMLTextAreaElement | null>(null);
  const [focused, setFocused] = useState(false);
  const open = big || focused || value.trim().length > 0;
  const cannotSend = !value.trim() || pending;

  // Esc zamyka najwyższą warstwę panelu, a duże okno jest najwyższą — także
  // gdy fokus jest poza polem (podgląd CV, tło). Zamknięcie listy „@”
  // przychodzi tu jako `defaultPrevented`. Tablica ma własny nasłuch `window`
  // i kolejność obu nie jest stała (tamten rejestruje się na nowo po „Rozwiń”
  // i po odświeżeniu karty), a React przerysowuje między nimi. Dlatego dwa
  // zabezpieczenia: `preventDefault()` tutaj (Tablica druga — widzi obsłużone
  // zdarzenie) i `data-note-enlarged` (Tablica pierwsza — widzi otwarte okno).
  // Dok ukryty pod przeglądem Delivery Leada nie jest warstwą: Esc należy
  // wtedy do przeglądu.
  useEffect(() => {
    if (!big) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector('[role="dialog"],[role="alertdialog"]')) return;
      if (rootRef.current?.closest("[hidden]")) return;
      e.preventDefault();
      onBigChange(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [big, onBigChange]);

  const setBig = (next: boolean) => {
    onBigChange(next);
    fieldRef.current?.focus();
  };

  // D3: zwykły zapis notatki, potem formularz screeningu obok czyta ją sam.
  const fillButton = onSubmitAndFill ? (
    <Button size="sm" variant="outline" onClick={onSubmitAndFill} disabled={cannotSend}>
      <ClipboardCheck className="h-3.5 w-3.5" aria-hidden="true" /> Zapisz notatkę i wypełnij formularz
    </Button>
  ) : null;

  return (
    <div
      ref={rootRef}
      className={cn(
        "border-t border-border bg-muted/10 p-3",
        big ? "flex min-h-0 flex-1 flex-col gap-2" : open ? "space-y-1.5" : "flex items-end gap-1.5",
      )}
      data-help="jobs.person.note"
      data-note-enlarged={big ? "" : undefined}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        // Fokus wewnątrz kompozytora (Tab na „Powiększ”) to dalej pisanie.
        if (!e.currentTarget.contains(e.relatedTarget)) setFocused(false);
      }}
    >
      {big ? (
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1 truncate text-xs font-medium text-muted-foreground">
            Nowa notatka
          </p>
          <Button size="sm" variant="outline" onClick={() => setBig(false)}>
            <Minimize className="h-3.5 w-3.5" aria-hidden="true" /> Zmniejsz
          </Button>
        </div>
      ) : null}
      <MentionTextarea
        value={value}
        onChange={onChange}
        scope={{ kind: "job", jobId }}
        textareaRef={fieldRef}
        onKeyDown={(e) => {
          if (e.key !== "Enter") return;
          // Duże okno: Enter to nowa linia, wysyła Ctrl/⌘+Enter (działa też w małym).
          if (big ? !(e.ctrlKey || e.metaKey) : e.shiftKey) return;
          e.preventDefault();
          onSubmit();
        }}
        ariaLabel="Dodaj notatkę"
        placeholder="Dodaj notatkę… (@ oznacza osobę)"
        rows={focused && !big ? 3 : 1}
        maxRows={focused ? 10 : 3}
        autoGrow={!big}
        wrapperClassName={big ? "flex min-h-0 flex-1 flex-col" : open ? undefined : "w-0 flex-1"}
        className={cn(
          "block rounded-md focus:ring-primary",
          big
            ? "min-h-0 flex-1 px-3 py-2 text-sm"
            : open
              ? "px-3 py-2 text-sm"
              : "min-h-8 px-3 py-1.5 text-xs",
        )}
      />
      {open ? (
        // Klik w rząd (także w wyłączony przycisk wysyłki) nie zabiera fokusu
        // z pola — inaczej puste pole zwijałoby się pod kursorem.
        <div className="flex items-center gap-1.5" onMouseDown={(e) => e.preventDefault()}>
          <p className="min-w-0 flex-1 text-[11px] leading-tight text-muted-foreground">
            {big ? NOTE_KEYS_HINT_BIG : NOTE_KEYS_HINT}
          </p>
          {big ? (
            <>
              {fillButton}
              <Button size="sm" onClick={onSubmit} disabled={cannotSend} loading={pending}>
                <Send className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj notatkę
              </Button>
            </>
          ) : (
            <>
              <Button
                size="icon-sm"
                variant="outline"
                onClick={() => setBig(true)}
                aria-label="Powiększ pole notatki"
                title="Powiększ pole notatki"
              >
                <Maximize className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
              <Button
                size="sm"
                onClick={onSubmit}
                disabled={cannotSend}
                loading={pending}
                aria-label="Dodaj notatkę — wyślij"
              >
                <Send className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
        </div>
      ) : (
        <Button
          size="sm"
          onClick={onSubmit}
          disabled={cannotSend}
          loading={pending}
          aria-label="Dodaj notatkę — wyślij"
        >
          <Send className="h-3.5 w-3.5" />
        </Button>
      )}
      {open && !big && fillButton ? (
        <div className="flex justify-end" onMouseDown={(e) => e.preventDefault()}>
          {fillButton}
        </div>
      ) : null}
    </div>
  );
}

export function PipelineCandidateDock({
  item,
  noteFill,
  jobId,
  currentStageLabel,
  jobTitle,
  matchScore,
  moveTargets,
  readOnly,
  contactFeatureEnabled,
  canReject,
  rejectBlockedReason = null,
  budgetHourly = null,
  position,
  total,
  onSelectPrevious,
  onSelectNext,
  closedNotice = null,
  onReturnToQueue,
  queueLabel = null,
  addedByMenu,
  queueEnd = null,
  nextAction,
  primaryTarget,
  primaryBlocked = null,
  onAdvance,
  onClose,
  onMoveTo,
  onMoveToStageDef,
  onOpenScreening,
  onReject,
  onWithdraw,
  onAddClientSlots,
  onOpenQc,
  onTake,
  clientId = null,
  onOpenWorkbench,
  badgeToggles = [],
  expanded = false,
  onToggleExpanded,
  workbench = null,
  hidePrimaryMove = false,
  split = false,
  onClientAccept,
  clientAcceptance = null,
  onUndoClientAcceptance,
}: PipelineCandidateDockProps) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const nowSection = nowSectionForStage(item.stage);
  const [openSections, setOpenSections] = useState<Set<DockTab>>(
    () => new Set([nowSection]),
  );
  const isOpen = (id: DockTab) => openSections.has(id);
  const toggleSection = (id: DockTab) =>
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const [openOriginal, setOpenOriginal] = useState(false);
  const [openBranded, setOpenBranded] = useState(false);
  const [openGenerator, setOpenGenerator] = useState(false);
  // 0521: okno braków formularza CV klienta („Uzupełnij formularz” z wymagań).
  const [clientFormOpen, setClientFormOpen] = useState(false);
  const [openShare, setOpenShare] = useState(false);
  const [openEmail, setOpenEmail] = useState(false);
  const [openBlacklist, setOpenBlacklist] = useState(false);
  const [openPreContract, setOpenPreContract] = useState(false);
  const [openSendAlso, setOpenSendAlso] = useState(false);
  const [openAddAlso, setOpenAddAlso] = useState(false);
  // Szkic notatki per osoba + rekrutacja (12.10.2026): dok montuje się na
  // nowo dla każdej osoby (`key` w `KanbanBoardV2`), więc niewysłany tekst
  // wraca z pamięci karty przeglądarki, a nie ze stanu.
  const userId = useAuthStore((s) => s.user?.id);
  const [noteText, setNoteTextState] = useState(() =>
    readNoteDraft(userId, jobId, item.candidate_id),
  );
  const setNoteText = (text: string) => {
    setNoteTextState(text);
    writeNoteDraft(userId, jobId, item.candidate_id, text);
  };
  const [noteBigRequested, setNoteBig] = useState(false);
  // Dok tylko do odczytu nie ma pola notatki — nie może zostać z ukrytą treścią.
  const noteBig = noteBigRequested && !readOnly;
  // Okna akcji z ramki „Następny etap” (te same, które otwiera „Przesuń dalej”).
  const [qcStageId, setQcStageId] = useState<number | null>(null);
  // Okno pytań klienta: `eventId = null` — rozmowy nie ma w kalendarzu
  // NEXUSA, okno pyta, kiedy była (20.10.2026). `initialQuestions` — z notatki.
  const [debriefFor, setDebriefFor] = useState<{
    eventId: number | null;
    initialQuestions?: string[];
  } | null>(null);
  // Podpowiedź pod notatką „To wygląda na pytania klienta” — szkic listy
  // pytań wyjęty z właśnie zapisanej notatki (20.10.2026).
  const [questionsHint, setQuestionsHint] = useState<string[] | null>(null);
  useEffect(() => setQuestionsHint(null), [item.candidate_id]);
  const interviewBadge = item.interview_badge ?? null;
  const interviewStepState = interviewBadge?.steps?.find((s) => s.key === "interview")?.state;
  const openSlotRequest =
    interviewBadge?.slot_request?.status === "awaiting_recruiter" ||
    interviewBadge?.slot_request?.status === "awaiting_dl";
  // Para w „Rozmowie u klienta” bez rozmowy w kalendarzu — „Pytania z rozmowy”
  // zapisuje je z datą rozmowy (serwer zakłada odbytą rozmowę).
  const pairQuestionsWithoutEvent =
    item.stage === "client_interview" &&
    interviewBadge?.interview_event_id == null &&
    !openSlotRequest;
  // Podpowiedź z notatki ma sens po rozmowie: w etapie rozmowy albo przy
  // rozmowie w kalendarzu, która już się zaczęła.
  const questionsHintApplies =
    interviewStepState !== "scheduled" &&
    !openSlotRequest &&
    (item.stage === "client_interview" || interviewBadge?.interview_event_id != null);
  const [rateChangeOpen, setRateChangeOpen] = useState(false);
  const [clientRateChangeOpen, setClientRateChangeOpen] = useState(false);
  // Linia „Warunki i następny etap” pod paskiem zakładek — domyślnie zwinięta.
  const [stageFoldOpen, setStageFoldOpen] = useState(false);
  const [profileCvPreviewId, setProfileCvPreviewId] = useState<number | null>(null);

  // Zmiana kandydata (nowy klik na tablicy) — wróć na pierwszą zakładkę;
  // inaczej dok pokazywałby zakładkę „Notatki" poprzedniego kandydata.
  // Niewysłana notatka jest szkicem tej osoby (wyżej), nie stanem do czyszczenia.
  useEffect(() => {
    setOpenSections(new Set([nowSectionForStage(item.stage)]));
    setStageFoldOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tylko zmiana osoby
  }, [item.candidate_id]);

  const fullName = `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;
  // „Wgraj nowe CV” (13.10.2026): zapis w rekrutacji i teczce kandydata —
  // ta sama capability co wgrywanie w zakładce „CV i dokumenty”.
  const canManageDocuments = useCapability("candidate.document.manage");
  const canUploadCv = !readOnly && canManageDocuments;
  // „Czarna lista…” — ta sama bramka co zapis profilu (serwer: candidate write).
  const canWriteCandidate = useCapability("candidate.write");
  const canBlacklist = !readOnly && canWriteCandidate;
  // „Umowa przedwstępna…” — bramka API przedwstępnych (`pre_contract.work`);
  // Automatyzacje prowadzą ją mimo podglądu Tablicy (decyzja 22.10.2026).
  const canWorkPreContracts = useCapability("pre_contract.work");
  const dockUser = useAuthStore((st) => st.user);
  const canRequestPreContract = canWorkPreContracts && !preContractReadOnly(dockUser, readOnly);
  // Match (22.10.2026): osoba po akceptacji DL-a — wysyłka do innych rekrutacji
  // z portfela; prawo to samo co wysyłka CV do klienta.
  const canSendAlso =
    !readOnly && hasPermission(dockUser, "recruitment_manage") && SEND_ALSO_STAGES.has(item.stage ?? "");
  const cvUpload = useStageCvUpload({ candidateId: item.candidate_id, stageId: item.id, jobId });
  // Nazwa kolejki strzałek za „‹ N z M ›”. Z menu „Kto dodał”, bo w widoku
  // „Rozwiń” Tablica (i przycisk w nagłówku) jest zasłonięta (14.10.2026).
  const queueTag = queueLabel ? (
    addedByMenu ? (
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            data-testid="dock-queue-label"
            title={queueLabel}
            aria-label={`Kolejka: ${queueLabel}. Zmień filtr „Kto dodał”`}
            className="inline-flex min-w-0 items-center gap-0.5 rounded-md bg-primary/10 px-1.5 py-0.5 font-semibold text-primary hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:p-2"
          >
            <span className="truncate">{queueLabel}</span>
            <ChevronDown className="h-3 w-3 shrink-0" aria-hidden="true" />
          </button>
        </DropdownMenuTrigger>
        <AddedByMenuContent {...addedByMenu} align="start" />
      </DropdownMenu>
    ) : (
      <span data-testid="dock-queue-label" title={queueLabel} className="min-w-0 truncate font-semibold text-foreground/80">
        {queueLabel}
      </span>
    )
  ) : null;
  const initials = fullName
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  // Bramka „Oczekuje" usunięta 17.09.2026 — stawka ponad AKTUALNY budżet PLN/h
  // rekrutacji to odznaka, nie blokada, więc nie odbiera karcie zielonej
  // pigułki „bez blokad".
  const overBudget = isOverHourlyBudget(item, budgetHourly);
  const normalizedScore =
    typeof matchScore === "number" && Number.isFinite(matchScore)
      ? Math.max(0, Math.min(100, Math.round(matchScore)))
      : null;

  // Osoba z kolumny zamkniętych: powód, kto i kiedy (19.10.2026).
  const closed = closedReason(item);
  const addedAttribution = item.added_to_job_by_name?.trim()
    ? `Dodano do rekrutacji przez: ${item.added_to_job_by_name.trim()}${
        item.added_to_job_at ? ` · ${formatDate(item.added_to_job_at)}` : ""
      }`
    : `Brak danych o osobie dodającej${
        item.added_to_job_at ? ` · dodano ${formatDate(item.added_to_job_at)}` : ""
      }`;

  // ── Screening — jeden widok pary: warunki, odpowiedzi i ocena ───────────
  // 09.10.2026: dok czyta stan formularza (ten sam klucz co zakładka
  // „Screening” po „Rozwiń”), nie osobno arkusz etapu i kartę rekomendacji.
  const screeningQuery = useScreeningFormState(item.candidate_id, jobId, isOpen("screening"));
  const screeningState = screeningQuery.data ?? null;
  // Po ruchu karty stan pary jest o wiersz etapu do tyłu (stawka z okna
  // „Zweryfikowany”, kolumna) — odświeżamy go raz na nowy wiersz.
  const refreshedForStage = useRef<number | null>(null);
  const screeningStageId = screeningState?.stage_id ?? null;
  useEffect(() => {
    if (screeningStageId == null || screeningStageId === item.id) return;
    if (refreshedForStage.current === item.id) return;
    refreshedForStage.current = item.id;
    void queryClient.invalidateQueries({ queryKey: screeningFormQueryKey(jobId, item.candidate_id) });
  }, [item.id, item.candidate_id, jobId, queryClient, screeningStageId]);

  // ── CV — status oryginalnego/brandowanego (tylko na zakładce CV) ───────
  const cvOriginalQuery = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", item.id],
    queryFn: () => candidateStageCvApi.original.get(item.id).then((r) => r.data),
    enabled: isOpen("cv"),
  });
  // CV firmowe PARY: wiersz bieżącego etapu, a gdy jest pusty — wiersz
  // wskazany przez serwer (`pair_source_stage_id`; ruch na kolejną kolumnę
  // zakłada nowy wiersz bez CV, runda 10, F23). Ten sam hook i klucze co karta
  // „CV do klienta”: edycja, pobranie i ramka idą na `cvStageId`.
  const stageBranded = useStageBrandedCv(item.id, {
    enabled: isOpen("cv") || openBranded || openShare,
  });
  const cvBrandedQuery = stageBranded.ownQuery;
  const companyBrandedQuery = stageBranded.query;
  const companyBranded = companyBrandedQuery.data;
  const brandedStatus = cvBrandedQuery.data?.status ?? "none";
  const stageCv = stageCvStatus(companyBranded);
  // Oryginał z profilu — pytamy tylko, gdy etap nie ma kopii ze zgłoszenia.
  // Klucz wspólny z kartą CV na profilu kandydata.
  const snapshotMissing = cvOriginalQuery.isSuccess && !cvOriginalQuery.data?.has_snapshot;
  const profileCvQuery = useQuery<CandidateDocument[]>({
    queryKey: candidateQueryKeys.cvDocuments(item.candidate_id),
    queryFn: () =>
      api
        .get<CandidateDocument[]>(`/api/candidates/${item.candidate_id}/documents?kind=cv`)
        .then((r) => (Array.isArray(r.data) ? r.data : [])),
    // Osoba, która może wgrać CV, widzi też „W profilu jest nowsze CV” —
    // do tego lista plików jest potrzebna także obok kopii ze zgłoszenia.
    enabled: isOpen("cv") && (snapshotMissing || cvOriginalQuery.isError || canUploadCv),
    staleTime: 30_000,
  });

  // ── Notatki — wszystkie notatki osoby, podzielone na tę rekrutację
  // i „wcześniej u nas” (12.10.2026). Zapytanie stoi od otwarcia karty, bo
  // podpis zwiniętej sekcji ma od razu mówić, że osoba ma u nas historię.
  const notesQuery = useCandidateNotes(item.candidate_id);
  const notesSplit = useMemo(
    () => splitPersonNotes(candidateNoteItems(notesQuery.data), jobId),
    [notesQuery.data, jobId],
  );
  // D3 (14.10.2026): formularz screeningu tej osoby (zakładka po „Rozwiń”)
  // przyjmie notatkę — wtedy obok „Dodaj notatkę” stoi „…i wypełnij formularz”.
  const noteFillAvailable = useNoteFillAvailable(noteFill, item.candidate_id);
  const addNoteMutation = useMutation({
    mutationFn: ({ content }: { content: string; fill: boolean }) =>
      api.post<{ id?: number }>("/api/notes", {
        candidate_id: item.candidate_id,
        job_id: jobId,
        content,
        note_type: "general",
      }),
    // Szkic znika z pamięci przy wysłaniu, nie po odpowiedzi serwera:
    // `onSuccess` działa też po odmontowaniu doku, więc „wyślij, wyjdź, wróć”
    // oddawałoby wysłany tekst jako szkic — gotowy duplikat.
    onMutate: () => writeNoteDraft(userId, jobId, item.candidate_id, ""),
    onSuccess: (res, vars) => {
      setNoteText("");
      setNoteBig(false);
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.notes(item.candidate_id),
      });
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.timelineRoot(item.candidate_id),
      });
      // 0413: notatka z ustaleniami z rozmowy wypełnia pola screeningu od razu.
      queryClient.invalidateQueries({
        queryKey: recommendationCardQueryKey(item.candidate_id, jobId),
      });
      queryClient.invalidateQueries({
        queryKey: screeningFormQueryKey(jobId, item.candidate_id),
      });
      // Plakietka karty na tablicy i ramka „Następny etap” czytają ten sam stan.
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      queryClient.invalidateQueries({ queryKey: MOVE_REQUIREMENTS_PREFIX });
      if (vars.fill) void fillScreeningForm(res.data?.id, vars.content);
      else showSuccess("Notatka dodana.");
      if (questionsHintApplies && looksLikeClientQuestions(vars.content)) {
        setQuestionsHint(extractClientQuestions(vars.content));
      }
    },
    onError: (e, { content }) => {
      // Nieudany zapis oddaje szkic, o ile w międzyczasie nie powstał nowy.
      if (!readNoteDraft(userId, jobId, item.candidate_id)) {
        writeNoteDraft(userId, jobId, item.candidate_id, content);
      }
      showError(extractErrorMsg(e) || "Nie udało się dodać notatki");
    },
  });

  // Formularz czyta notatkę trasą „Wklej tekst” i przy zapisie odsyła jej
  // numer — serwer nie zakłada drugiej. Notatka jest zapisana niezależnie od
  // tego, czy odczyt się udał (powód porażki pokazuje formularz).
  const fillScreeningForm = async (noteId: number | undefined, text: string) => {
    if (!noteFill || noteId == null) {
      showSuccess("Notatka dodana.");
      return;
    }
    try {
      const taken = await noteFill.send(item.candidate_id, { noteId, text });
      if (taken) {
        showSuccess("Notatka dodana i przekazana do formularza screeningu — sprawdź pola i zapisz formularz.");
      } else {
        showError("Notatka dodana, ale formularz screeningu nie jest już otwarty — nie wypełniłem go.");
      }
    } catch {
      showError("Notatka dodana i zostaje w historii, ale formularza z niej nie wypełniłem.");
    }
  };

  const submitNote = (fill = false) => {
    const content = noteText.trim();
    if (!content || addNoteMutation.isPending) return;
    addNoteMutation.mutate({ content, fill });
  };

  // ── Profil kandydata — podtytuł nagłówka (stanowisko · firma · miasto),
  //    chip statusu, warunki wobec oferty ORAZ adres do modala e-mail.
  //
  //    Jedno zapytanie na OTWARTĄ kartę (nie na kartę tablicy) — klucz jest
  //    ten sam, co profilu kandydata, więc przy przejściu na profil odpowiedź
  //    jest już w cache'u. Tablica z 26+ kartami nie strzela tu ani razu.
  const candidateDetailQuery = useQuery<CandidateDetail>({
    queryKey: candidateQueryKeys.detail(item.candidate_id),
    queryFn: () =>
      candidatesApi.get(item.candidate_id).then((r) => r.data as CandidateDetail),
    staleTime: 60_000,
    // Po wgraniu CV z rekrutacji: dopytuj, aż AI odczyta plik (albo minie okno).
    refetchInterval: (query) =>
      profileReadPending(cvUpload.uploadedAt, query.state.data ?? null) ? 15_000 : false,
  });
  const candidate = candidateDetailQuery.data ?? null;
  // Bez cudzego CV z kwarantanny tożsamości (audyt 13.10.2026, pkt 8).
  const ownProfileCvDocs = withoutQuarantinedCv(
    profileCvQuery.data as DockProfileCvDoc[] | undefined,
    candidate?.cv_extracted_data,
  );

  const originalCv = dockOriginalCv({
    snapshot: cvOriginalQuery.data,
    snapshotLoading: cvOriginalQuery.isLoading,
    profileDocs: ownProfileCvDocs,
    profileDocsFailed: profileCvQuery.isError,
    cvFilename: candidate?.cv_filename ?? null,
  });
  // Czy PARA ma CV firmowe poza CV etapu (gotowe CV z generatora, plik
  // „…B2B…”), mówi lista wymagań ramki „Następny etap” — czytana z cache
  // (`enabled: false`), bez drugiego żądania.
  // Obserwator MUSI mieć ten sam `queryFn` co ramka (`useMoveRequirements`):
  // react-query bierze opcje zapytania z ostatniego `setOptions`, a efekty
  // rodzica biegną po efektach dziecka — atrapa `queryFn: () => null`
  // (#1789) zerowała ramkę przy każdym `invalidateQueries` (audyt 24.09.2026).
  // 404 z `…/cv/branded` pada od 12.10.2026 tylko dla nieistniejącego etapu —
  // brak wiersza CV to stan „none” z `pair_source_stage_id`, więc błąd odczytu
  // to zawsze awaria, nigdy „brak CV”.
  const brandedFailed = cvBrandedQuery.isError || companyBrandedQuery.isError;
  const editStageId = stageBranded.cvStageId;
  const nextStageRequirements = useMoveRequirements(
    {
      candidateId: item.candidate_id,
      jobId,
      toStageDefId: primaryTarget?.stage_def_id ?? null,
    },
    false,
  );
  const companyCv = companyCvSentence(companyBranded, {
    pairHasCompanyCv: pairCompanyCv(nextStageRequirements.data?.items),
  });
  // D1 (14.10.2026): „Pobierz Word / PDF” przy CV firmowym — ten sam plik co
  // w karcie „CV do klienta” (szkic z bieżącej treści albo zatwierdzona
  // wersja), z wiersza, na którym CV leży. Zgoda RODO: serwer odmawia 409
  // `consent_required`, dok mówi to od razu (`consent_missing`).
  const canDownloadCompanyCv = companyBrandedQuery.isSuccess && stageCv === "ready";
  const companyConsentMissing = canDownloadCompanyCv && companyBranded?.consent_missing === true;
  const [downloadingCv, setDownloadingCv] = useState<"docx" | "pdf" | null>(null);
  const downloadCompanyCv = async (format: "docx" | "pdf") => {
    setDownloadingCv(format);
    try {
      const file =
        format === "docx"
          ? await fetchStageCvFile(editStageId, { download: "dock" })
          : await fetchStageCvPdf(editStageId, { download: "dock" });
      downloadBlob(file.blob, file.filename || (format === "docx" ? "CV.docx" : "CV.pdf"));
    } catch (error) {
      showError(
        apiErrorMessage(
          error,
          format === "pdf"
            ? "Nie udało się pobrać PDF. Spróbuj za chwilę albo pobierz plik Word."
            : "Nie udało się pobrać CV.",
        ),
      );
    } finally {
      setDownloadingCv(null);
    }
  };
  // QC CV wcześniej (PR 4): na „Zweryfikowanym” z CV firmowym pary dok liczy
  // QC tak jak bramka „CV wysłane” — rekruter poprawia przed przekazaniem.
  const earlyQc =
    item.stage === "verified" && (companyCv.tone === "success" || companyCv.tone === "info");
  const qcQuery = useCvQc(item.id, isOpen("cv") && earlyQc);
  const profileHref = `/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`;

  // ── Ramka „Następny etap”: przyciski usuwające braki. Każda akcja otwiera
  //    istniejące okno; przycisku, którego dok nie umie obsłużyć, nie ma.
  const verifiedTarget =
    primaryTarget?.stage === "verified"
      ? primaryTarget
      : (moveTargets.find((t) => t.col.stage === "verified" && !t.blockedReason)?.col ?? null);
  // „Przesuń na Zatrudniony…” w sekcji umowy — umowa spoza Generatora
  // (20.10.2026). Ten sam `onMoveTo` co menu „Inny etap…”.
  const hiredTarget =
    moveTargets.find((t) => t.col.stage === "hired" && !t.blockedReason)?.col ?? null;
  const refreshMoveRequirements = () => {
    void queryClient.invalidateQueries({ queryKey: MOVE_REQUIREMENTS_PREFIX });
  };
  const canActOnRequirement = (action: MoveRequirementAction): boolean => {
    switch (action.kind) {
      case "open_screening":
      case "open_qc":
      case "generate_cv":
      case "open_card":
      case "open_client_form":
        return true;
      case "set_candidate_rate":
        return verifiedTarget != null;
      case "set_client_rate":
        return Boolean(onOpenWorkbench);
      case "open_debrief":
        return true;
      case "request_slots":
        return Boolean(onAddClientSlots);
      case "reject":
        return canReject && !rejectBlockedReason;
      case "open_pre_contract":
        return Boolean(onOpenWorkbench);
      default:
        return false;
    }
  };
  const handleRequirementAction = (action: MoveRequirementAction) => {
    const stageId = action.stage_id ?? item.id;
    switch (action.kind) {
      case "open_screening":
        onOpenScreening(stageId, fullName);
        return;
      case "open_qc":
        setQcStageId(stageId);
        return;
      case "generate_cv":
        setOpenGenerator(true);
        return;
      case "open_client_form":
        setOpenSections((prev) => new Set(prev).add("cv"));
        setClientFormOpen(true);
        return;
      case "set_candidate_rate":
        // Stawkę kandydata zapisuje ruch na „Zweryfikowany” (okno stawki).
        if (verifiedTarget) onMoveTo(verifiedTarget);
        return;
      case "set_client_rate":
        onOpenWorkbench?.("cv");
        return;
      case "open_debrief":
        setDebriefFor({ eventId: action.event_id ?? null });
        return;
      case "request_slots":
        onAddClientSlots?.();
        return;
      case "open_card":
        // 0424: pola uzupełnia się w formularzu screeningu (panel osoby na
        // „Screeningu”); bez panelu — sekcja „Screening” tylko do odczytu.
        if (onOpenWorkbench) {
          onOpenWorkbench("screening");
          return;
        }
        setOpenSections((prev) => new Set(prev).add("screening"));
        return;
      case "reject":
        onReject({ notes: action.note ?? null });
        return;
      case "open_pre_contract":
        // 0506: umowa przedwstępna — sekcja w zakładce „Umowa” panelu osoby.
        onOpenWorkbench?.("contract");
        return;
      default:
        return;
    }
  };

  const clientRateText = formatClientRate(item);
  // 12.10.2026: para z czasów Traffita nie ma stawek na etapie — oczekiwanie
  // kandydata leży w karcie rekomendacji, cena wysłania w notatce Delivery
  // Leada z dnia wysyłki. Jedno zapytanie na OTWARTĄ kartę i tylko wtedy,
  // gdy czegoś brakuje; notatkę z wysyłki serwer oddaje wyłącznie rolom,
  // które widzą stawkę do klienta.
  const authUser = useAuthStore((st) => st.user);
  const missingExpectedRate =
    item.expected_rate_value == null || item.expected_rate_value === "";
  const rateHintsQuery = useQuery({
    queryKey: recruitmentRateHintsQueryKey(item.candidate_id, jobId),
    queryFn: () => fetchRecruitmentRateHints(item.candidate_id, jobId),
    enabled:
      !split &&
      (missingExpectedRate || (clientRateText == null && canViewClientRate(authUser))),
    staleTime: 60_000,
  });
  const expectedRateHint = missingExpectedRate
    ? (rateHintsQuery.data?.expected_rate_hint ?? null)
    : null;
  const expectedRateHintValue = expectedRateHintText(expectedRateHint);
  const clientRateNote =
    clientRateText == null ? (rateHintsQuery.data?.client_rate_note ?? null) : null;
  // 20.10.2026: za ile CV poszło do klienta, zmiany po wysyłce i blokada po
  // zamówieniu — tylko gdy para ma stawkę do klienta, a rola ją widzi.
  const clientRateHistory = useClientRateHistory(
    item.candidate_id,
    jobId,
    !split && clientRateText != null && canViewClientRate(authUser),
  ).data;
  const clientRateLock = clientRateHistory?.order_lock ?? null;
  // „Karta przed CV” (29.10.2026): po wysyłce DL pobiera kartę także stąd —
  // tylko u klienta z wzorem karty i tylko rola, która widzi stawkę.
  const coverSheetEnabled =
    useCoverSheet(
      item.candidate_id,
      jobId,
      !split && clientRateText != null && canViewClientRate(authUser),
    ).data?.enabled === true;
  const [coverSheetBusy, setCoverSheetBusy] = useState(false);
  const downloadSheet = async () => {
    setCoverSheetBusy(true);
    try {
      await downloadCoverSheet(item.candidate_id, jobId);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać karty przed CV."));
    } finally {
      setCoverSheetBusy(false);
    }
  };
  const clientRateHint = clientRateHistory
    ? [
        sentLine(clientRateHistory),
        clientRateLock ? `stawkę zmienia się w zamówieniu „${clientRateLock.title}”` : null,
      ]
        .filter(Boolean)
        .join(" · ") || null
    : null;
  // „Nie odebrał” jednym kliknięciem — ta sama notatka-próba co w profilu
  // (rodzaj `contact_attempt`); ten sam hook stoi w profilu przed telefonem.
  const noAnswerMut = useNoAnswerNote({ candidateId: item.candidate_id, jobId });
  // Żywa umowa (15.10.2026): termin z umowy, nie ze screeningu sprzed
  // zatrudnienia — znacznik niesie karta Tablicy.
  const contractAvail = contractAvailability(
    item.employment_marker,
    candidate?.availability_date ?? item.availability_date,
  );
  const availabilityLabel = contractAvail
    ? `${contractAvailabilityText(contractAvail)} · z kontraktu`
    : availabilityText(
        candidate
          ? {
              date: candidate.availability_date,
              status: candidate.availability_status,
              noticePeriod: candidate.notice_period,
              // Profil bez jednostki okresu wypowiedzenia — dni (jak dotąd w doku).
              noticeUnit: candidate.notice_period_unit ?? "days",
            }
          : null,
      );

  // Modal montuje się dopiero z DANYMI (patrz render niżej) — w oknie między
  // kliknięciem a odpowiedzią pole „Do" byłoby puste. Gdy zapytanie padnie,
  // intencja wysyłki jest zamykana z toastem, a nie wisi na spinnerze.
  const emailLookupFailed = openEmail && candidateDetailQuery.isError;
  useEffect(() => {
    if (!emailLookupFailed) return;
    showError("Nie udało się pobrać adresu e-mail kandydata.");
    setOpenEmail(false);
  }, [emailLookupFailed, showError]);

  // ── Pasek zakładek stoi w miejscu (09.10.2026) ────────────────────────
  // Po „Rozwiń” głowa panelu ma tę samą wysokość w każdej zakładce: fakty,
  // „Nie odebrał” i ramka „Następny etap” przechodzą pod pasek zakładek jako
  // jedna zwinięta linia (`DockStageFold`). Do tej daty wracały do głowy po
  // wyjściu ze „Screeningu” i przy oknie 1536 × 780 na treść zakładki
  // zostawało ok. 70 px. Wąski dok renderuje je w głowie jak dotąd.
  const tabsOpen = expanded && workbench != null;

  // Fakty o osobie RAZ, pod nazwiskiem (PR 5, 04.10.2026) — do tej
  // pory stały zwinięte w „W procesie”. Wyłącznie z danych, które dok
  // już ma (karta kanbanu + profil kandydata). Brak danych to „—”, nie
  // znikający wiersz: pusty rząd czyta się jak „bez zastrzeżeń”.
  // W trybie `split` (Nowi/Screening, 0424) te same fakty stoją w
  // profilu przed telefonem i w „Warunkach” formularza — tu ich nie
  // powtarzamy, żeby formularz zaczynał się wyżej na laptopie.
  const factsBlock = !split ? (
    <PersonFacts
      testId="dock-facts"
      pairs
      rows={[
        {
          label: "W tej rekrutacji",
          wide: true,
          hint:
            expectedRateHint && expectedRateHintValue
              ? expectedRateHintCaption(expectedRateHint)
              : null,
          value: (
            <>
              {expectedRateHint && expectedRateHintValue ? (
                <span className="font-medium tabular-nums" data-testid="dock-rate-hint">
                  {expectedRateHintValue}
                </span>
              ) : (
                <RateWithBudget
                  value={item.expected_rate_value}
                  unit={item.expected_rate_unit}
                  currency={item.expected_rate_currency}
                  budgetMonthly={item.budget_max_at_move}
                />
              )}
              {item.rate_change ? (
                <span className="ml-1.5 rounded bg-warning/15 px-1.5 py-0.5 text-[11px] font-semibold text-warning">
                  {rateChangeStatusLabel(item.rate_change.status)}
                  {item.rate_change.previous_hourly != null
                    ? ` · było ${hourlyText(item.rate_change.previous_hourly)}`
                    : ""}
                </span>
            ) : null}
            {!readOnly ? (
              // 0418: zmiana stawki w procesie — z powodem, śladem
              // i powiadomieniem DL / Head of Recruitment.
              <button
                type="button"
                onClick={() => setRateChangeOpen(true)}
                className="ml-1.5 text-xs font-medium text-primary hover:underline"
              >
                Zmień
              </button>
            ) : null}
          </>
        ),
      },
      // „Stawka od” (0414): najniższa stawka z 18 miesięcy — obok stawki
      // z tej rekrutacji, żeby było widać pole negocjacji.
      { label: "Stawka od", value: hourlyText(item.candidate_rate_from_hourly) },
      { label: "Dostępność", value: availabilityLabel },
      { label: "Tryb", value: onsiteText(candidate?.max_onsite_days_per_week) },
      // Stawka do klienta tylko, gdy serwer ją przysłał (rekruter jej nie
      // dostaje — `can_view_client_rate`).
      ...(clientRateText
        ? [
            {
              label: "Do klienta",
              wide: clientRateHint != null,
              hint: clientRateHint,
              value: (
                <>
                  <span className="font-medium tabular-nums">{clientRateText}</span>
                  {!readOnly && clientRateHistory?.can_write ? (
                    // 20.10.2026: zmiana po wysyłce — z powodem i śladem.
                    <button
                      type="button"
                      data-testid="dock-client-rate-change"
                      onClick={() => setClientRateChangeOpen(true)}
                      className="ml-1.5 text-xs font-medium text-primary hover:underline"
                    >
                      Zmień
                    </button>
                  ) : null}
                  {coverSheetEnabled ? (
                    <button
                      type="button"
                      data-testid="dock-cover-sheet-download"
                      disabled={coverSheetBusy}
                      onClick={() => void downloadSheet()}
                      className="ml-1.5 text-xs font-medium text-primary hover:underline disabled:opacity-60"
                    >
                      Karta (Word)
                    </button>
                  ) : null}
                </>
              ),
            },
          ]
        : clientRateNote
          ? [
              {
                label: "Do klienta",
                wide: true,
                value: <span className="text-muted-foreground">brak stawki</span>,
                hint: `${clientRateNoteCaption(clientRateNote)}: „${clientRateNote.text}”`,
              },
            ]
          : []),
    ]}
  />
  ) : null;

  // PR 5 (04.10.2026): w „Nowych” i „Screeningu” pierwsza praca to
  // telefon — „Biorę” i „Nie odebrał” bez wychodzenia z panelu.
  const contactRow =
    !readOnly && ENTRY_STAGES.has(item.stage ?? "") && !split ? (
      <div className="flex flex-wrap gap-1.5" data-testid="dock-contact-row">
        {onTake && item.can_take && item.claim_user_id == null && (
          <Button size="sm" variant="outline" onClick={onTake}>
            <UserPlus className="h-3.5 w-3.5" />{" "}
            {item.entry_source === "system" && !item.entry_autofill?.decided
              ? "Dzwonię — biorę na 12 h"
              : "Biorę — 12 h"}
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          disabled={noAnswerMut.isPending}
          onClick={() => noAnswerMut.mutate()}
        >
          <PhoneOff className="h-3.5 w-3.5" /> Nie odebrał
        </Button>
      </div>
    ) : null;

  const nextStageBlock = readOnly || hidePrimaryMove ? null : primaryTarget ? (
    <DockNextStage
      candidateId={item.candidate_id}
      jobId={jobId}
      target={primaryTarget}
      readOnly={readOnly}
      onMove={onMoveTo}
      onMoveToStageDef={onMoveToStageDef}
      onAction={handleRequirementAction}
      canAct={canActOnRequirement}
      refreshToken={item}
      item={item}
    />
  ) : primaryBlocked ? (
    <div className="space-y-1">
      <Button
        size="sm"
        disabled
        title={primaryBlocked.reason}
        className="w-full justify-center"
      >
        <ChevronRight className="h-3.5 w-3.5" />
        Przenieś na etap:{" "}
        {primaryBlocked.col.name ?? primaryBlocked.col.stage}
      </Button>
      <p role="note" className="text-[10.5px] leading-snug text-destructive">
        {primaryBlocked.reason}
      </p>
    </div>
  ) : null;

  const stageFold =
    tabsOpen && (factsBlock || nextStageBlock) ? (
      <DockStageFold
        title={
          factsBlock && nextStageBlock
            ? "Warunki i następny etap"
            : factsBlock
              ? "Warunki wobec rekrutacji"
              : "Następny etap"
        }
        summary={
          nextStageBlock && primaryTarget ? (
            <NextStageSummary
              candidateId={item.candidate_id}
              jobId={jobId}
              target={primaryTarget}
              refreshToken={item}
            />
          ) : nextStageBlock && primaryBlocked ? (
            (primaryBlocked.col.name ?? primaryBlocked.col.stage)
          ) : null
        }
        open={stageFoldOpen}
        onToggle={() => setStageFoldOpen((value) => !value)}
      >
        {factsBlock}
        {contactRow}
        {nextStageBlock}
      </DockStageFold>
    ) : null;

  return (
    <CvFileDropTarget
      enabled={canUploadCv}
      upload={cvUpload}
      title={`${fullName} · ${jobLabel}`}
      className="flex h-full flex-col rounded-xl border border-border bg-card"
    >
      {/* ── Pasek osoby (zawsze w miejscu) ────────────────────────────── */}
      {/* 09.10.2026: w wąskim doku w miejscu stoi tylko ten pasek i pole
          notatki; „Warunki”, „Następny etap” i przyciski etapów przewijają
          się razem z sekcjami. Do tej daty cała głowa stała w miejscu i przy
          oknie 1280 × 650 na sekcje zostawało 92 px, a z otwartą sprawą
          zmiany stawki przyciski wypadały poza ekran. Po „Rozwiń” układ jest
          jak dotąd: akcje stoją nad paskiem zakładek, przewija się treść
          zakładki. Zmieniają się wyłącznie klasy — elementy zostają w tym
          samym miejscu drzewa, więc „Rozwiń” niczego nie odmontowuje. */}
      <div
        className={cn(
          "space-y-2.5 px-4 pt-4",
          tabsOpen ? "pb-2.5" : "border-b border-border pb-3",
        )}
        data-testid="dock-person-bar"
      >
        {/* Nawigator „‹ N z M ›" — kolejka jednej kolumny Tablicy z filtrem
            „Kto dodał” (14.10.2026), za nim jej nazwa. Renderuje się tylko
            z podaną pozycją: bez niej nie zgadujemy. */}
        <div className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
          {position != null && total ? (
            <>
              <button
                type="button"
                onClick={onSelectPrevious}
                disabled={position <= 1}
                className="shrink-0 rounded-md p-0.5 hover:bg-accent disabled:opacity-40 pointer-coarse:p-2.5"
                aria-label="Poprzednia karta"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span className="shrink-0 whitespace-nowrap tabular-nums">
                {position} z {total}
              </span>
              <button
                type="button"
                onClick={onSelectNext}
                disabled={position >= total}
                className="shrink-0 rounded-md p-0.5 hover:bg-accent disabled:opacity-40 pointer-coarse:p-2.5"
                aria-label="Następna karta"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
              {queueTag}
            </>
          ) : onReturnToQueue ? (
            <>
              <button
                type="button"
                onClick={onReturnToQueue}
                className="inline-flex shrink-0 items-center gap-0.5 rounded-md px-1 py-0.5 font-semibold text-primary hover:bg-accent pointer-coarse:p-2"
              >
                Wróć do kolejki
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              {queueTag}
            </>
          ) : (
            <span className="text-[10px] font-semibold uppercase tracking-wide text-primary">
              Panel osoby
            </span>
          )}
          {onToggleExpanded ? (
            <button
              type="button"
              onClick={onToggleExpanded}
              aria-pressed={expanded}
              data-help="jobs.person.expand"
              className="ml-auto inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {expanded ? (
                <Minimize2 className="h-3.5 w-3.5" aria-hidden="true" />
              ) : (
                <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {expanded ? "Zwiń" : "Rozwiń"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            className={cn(
              "shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent pointer-coarse:p-2.5",
              !onToggleExpanded && "ml-auto",
            )}
            aria-label="Zamknij dok"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {closedNotice ? (
          <div
            role="status"
            aria-label="Poprzednia osoba"
            className="flex items-center gap-2 rounded-lg bg-success-muted px-2.5 py-1.5 text-[11.5px] leading-snug text-success-muted-foreground"
          >
            <CircleCheck className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="min-w-0 flex-1">
              {closedNotice.verb}:{" "}
              <span className="font-semibold text-foreground">{closedNotice.name}</span>
              {closedNotice.reason ? ` · ${closedNotice.reason}` : ""}
            </span>
            <button
              type="button"
              onClick={closedNotice.onShow}
              className="shrink-0 rounded-md px-1.5 py-0.5 font-semibold underline underline-offset-2 hover:bg-background/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:p-2"
            >
              Pokaż
            </button>
          </div>
        ) : null}

        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-sm font-semibold text-foreground">
                {fullName}
              </span>
              {/* Champion (D3, 15.10.2026): sam znak — oznacza Delivery Lead
                  w nagłówku rekrutacji, panel nie ma przycisków oznaczania. */}
              {item.is_champion ? (
                <span
                  className="inline-flex shrink-0 items-center gap-0.5 rounded px-1 text-[10px] font-semibold bg-medal-gold text-medal-gold-foreground"
                  title="Champion tej rekrutacji — oznaczył Delivery Lead."
                  data-testid="dock-champion-badge"
                >
                  <Trophy className="h-2.5 w-2.5" aria-hidden="true" />
                  Champion
                </span>
              ) : null}
              <Link
                href={profileHref}
                target="_blank"
                rel="noopener"
                aria-label={`Profil kandydata ${fullName} — otwiera się w nowej karcie`}
                className="inline-flex shrink-0 items-center gap-0.5 rounded-md px-1 text-[11px] font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Profil <span aria-hidden="true">↗</span>
              </Link>
            </div>
            {/* Podtytuł: stanowisko · firma · miasto · wynik. Człony, których
                nie znamy, po prostu nie wchodzą — myślnik w środku listy
                czytałby się jak wartość. */}
            <div className="truncate text-[11px] text-muted-foreground">
              {[
                candidate?.linkedin_current_title?.trim() || null,
                candidate?.linkedin_current_company?.trim() || null,
                candidate?.city?.trim() || candidate?.location?.trim() || null,
                normalizedScore != null ? `${normalizedScore} / 100` : null,
              ]
                .filter(Boolean)
                .join(" · ") ||
                (candidateDetailQuery.isLoading
                  ? "Wczytywanie profilu…"
                  : candidateDetailQuery.isError
                    ? "Nie udało się wczytać profilu"
                    : "Brak danych profilowych")}
            </div>
            {/* 09.10.2026: telefon i e-mail bez wchodzenia w profil. */}
            <PersonContactLine phone={candidate?.phone} email={candidate?.email} personName={fullName} />
            {/* „Prowadzi” (25.10.2026): czyja to osoba w tej rekrutacji. */}
            <PairOwnerLine item={item} jobId={jobId} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {/* Krótka pigułka zamiast stałej ramki: głowa panelu nie przewija
              się, a treść pod nią ma tylko ~390 px przy 1280 × 650. Klient,
              koniec zamówienia i Delivery Lead są w dymku po kliknięciu. */}
          {item.employment_marker && <EmploymentPopoverPill marker={item.employment_marker} />}
          {/* 17.10.2026: „Pracuje u nas” liczy się wyłącznie z umowy — karta na
              „Zatrudniony” bez umowy u klienta mówi, czego brakuje. */}
          {item.missing_contract && (
            <Badge
              variant="warning"
              size="sm"
              title="Karta jest na „Zatrudniony”, ale w Kontraktach nie ma umowy tej osoby u klienta. „Pracuje u nas” pojawi się po wpisaniu umowy."
              data-testid="dock-missing-contract"
            >
              Brak umowy w Kontraktach
            </Badge>
          )}
          {/* „W bazie od” (13.10.2026): świeża osoba widoczna na każdej zakładce. */}
          <NewInBasePill candidate={candidate} />
          {/* Czarna lista „u nas”: kto, kiedy i dlaczego w dymku po kliknięciu. */}
          {candidate?.status === "blacklisted" && (
            <BlacklistPopoverPill blacklist={candidate.blacklist} />
          )}
          {overBudget && (
            <Badge
              variant="warning"
              size="sm"
              title="Stawka kandydata przekracza budżet PLN/h rekrutacji — informacja, nic nie blokuje."
            >
              <HelpCircle className="h-2.5 w-2.5" /> Ponad budżet
            </Badge>
          )}
          {contactFeatureEnabled && (
            <ContactStatusBadge contactCase={item.contact_case} size="sm" />
          )}
          {item.hm_veto && (
            <Badge
              variant="danger"
              size="sm"
              title={[
                `${item.hm_veto.hiring_manager_name ?? "Hiring manager tej rekrutacji"} odrzucił(a) tego kandydata po rozmowie ${formatDate(item.hm_veto.rejected_at)}`,
                `Powód: ${item.hm_veto.rejection_reason_name}`,
                item.hm_veto.source_job_title
                  ? `Rekrutacja: ${item.hm_veto.source_job_title}`
                  : null,
              ]
                .filter(Boolean)
                .join("\n")}
            >
              <UserX className="h-2.5 w-2.5" /> Weto HM
            </Badge>
          )}
        </div>
      </div>

      <div
        className={cn("min-h-0 flex-1", tabsOpen ? "flex flex-col" : "overflow-y-auto")}
        data-person-scroll={tabsOpen ? undefined : ""}
        data-testid="dock-body"
        // Duże okno notatki zajmuje to miejsce: środek doku jest wtedy UKRYTY,
        // nie odmontowany (otwarte sekcje, zakładka i podgląd CV zostają).
        hidden={noteBig}
        inert={noteBig || undefined}
      >
      <div
        className={cn(
          "space-y-2.5 px-4",
          tabsOpen ? "shrink-0 border-b border-border pb-4" : "pt-3",
        )}
        data-testid="dock-actions"
      >
        {/* Koniec kolejki (D4) stoi tu, nie w pasku osoby: w wąskim doku pasek
            osoby nie przewija się, a te dwie linie zjadały sekcjom 61 px
            (1280 × 650, e2e „wąski dok osoby przewija się w całości”). */}
        {queueEnd && (queueEnd.onFirst || queueEnd.showAll || queueEnd.next) ? (
          <div
            role="status"
            aria-label="Koniec kolejki"
            data-testid="dock-queue-end"
            className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-muted px-2.5 py-1.5 text-[11.5px] leading-snug text-muted-foreground"
          >
            <span className="w-full">
              {queueEnd.count === 1
                ? "To jedyna osoba w kolejce."
                : `To ostatnia z ${queueEnd.count} osób w kolejce.`}
            </span>
            {queueEnd.onFirst ? (
              <button type="button" onClick={queueEnd.onFirst} className={QUEUE_END_ACTION}>
                Od pierwszej
              </button>
            ) : null}
            {queueEnd.showAll ? (
              <button type="button" onClick={queueEnd.showAll.onClick} className={QUEUE_END_ACTION}>
                {queueEnd.showAll.label}
              </button>
            ) : null}
            {queueEnd.next ? (
              <button
                type="button"
                onClick={queueEnd.next.onClick}
                className={cn(QUEUE_END_ACTION, "inline-flex items-center gap-0.5")}
              >
                {queueEnd.next.label}
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            ) : null}
          </div>
        ) : null}

        {/* 19.10.2026: powód odrzucenia / rezygnacji od razu po otwarciu osoby
            z kolumny zamkniętych — także w widoku „Rozwiń”. */}
        <DockClosedReason item={item} />
        <DockAutofillReason item={item} />
        {tabsOpen ? null : factsBlock}
        {item.rate_change && !readOnly ? (
          // 0418: otwarta sprawa zmiany stawki — negocjacja (DL, HoR),
          // wynik rozmowy, decyzja DL o stawce do klienta.
          <RateChangeBanner
            candidateId={item.candidate_id}
            jobId={jobId}
            onWithdraw={
              canReject && !rejectBlockedReason
                ? () => onReject({ notes: "Rezygnacja po zmianie stawki kandydata." })
                : undefined
            }
          />
        ) : null}

        {/* Główna akcja zaraz pod nazwiskiem (makieta „Panel osoby"). Ta sama
            ścieżka co drag&drop (`requestMove`) — okna stawki, potwierdzeń
            i powodu odrzucenia działają bez zmian. */}
        {!readOnly && (
          <div className="space-y-1.5" data-help="jobs.person.actions">
            {tabsOpen ? null : contactRow}
            {tabsOpen ? null : nextStageBlock}
            {onClientAccept && (
              <Button
                size="sm"
                variant="outline"
                data-testid="dock-client-accept"
                onClick={onClientAccept}
                className="w-full border-success/40 bg-success-muted text-success-muted-foreground hover:bg-success/15 hover:text-success-muted-foreground"
              >
                <CircleCheck className="h-3.5 w-3.5" aria-hidden="true" /> Klient zaakceptował
              </Button>
            )}
            <div className="flex flex-wrap items-center gap-1.5">
              {moveTargets.length > 0 && (
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button size="sm" variant="outline" className="flex-1 justify-between">
                      Inny etap…
                      <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    className="max-h-[60dvh] w-72 overflow-y-auto"
                  >
                    {moveTargets.map(({ col, blockedReason }) => {
                      const label = col.name ?? col.stage;
                      return (
                        <DropdownMenuItem
                          key={col.stage_def_id ?? col.stage}
                          aria-label={label}
                          disabled={Boolean(blockedReason)}
                          title={blockedReason ?? undefined}
                          onSelect={() => deferMenuAction(() => onMoveTo(col))}
                          className="block"
                        >
                          <span className="block">{label}</span>
                          {blockedReason && (
                            <span className="block text-xs text-muted-foreground">
                              {blockedReason}
                            </span>
                          )}
                        </DropdownMenuItem>
                      );
                    })}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
              {canReject && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onReject()}
                  disabled={Boolean(rejectBlockedReason)}
                  title={rejectBlockedReason ?? undefined}
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                >
                  <Ban className="h-3.5 w-3.5" /> Odrzuć z powodem
                </Button>
              )}
              {canReject && onWithdraw && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={onWithdraw}
                  disabled={Boolean(rejectBlockedReason)}
                  title={rejectBlockedReason ?? undefined}
                >
                  Zrezygnował
                </Button>
              )}
              {onAddClientSlots && (
                <Button size="sm" variant="outline" onClick={onAddClientSlots}>
                  <CalendarPlus className="h-3.5 w-3.5" aria-hidden="true" /> Terminy od klienta
                </Button>
              )}
              <PersonMoreMenu
                onOpenCv={() => setOpenOriginal(true)}
                onSendEmail={() => setOpenEmail(true)}
                profileHref={profileHref}
                onUndoClientAcceptance={onUndoClientAcceptance}
                onBlacklist={canBlacklist ? () => setOpenBlacklist(true) : undefined}
                onSendAlso={canSendAlso ? () => setOpenSendAlso(true) : undefined}
                onAddAlso={canWriteCandidate && !readOnly ? () => setOpenAddAlso(true) : undefined}
                onPreContract={
                  canRequestPreContract
                    ? () => (onOpenWorkbench ? onOpenWorkbench("contract") : setOpenPreContract(true))
                    : undefined
                }
              />
            </div>
          </div>
        )}
        {clientAcceptance && (
          <div
            data-testid="dock-client-acceptance"
            className="mt-2 rounded-lg bg-success-muted px-3 py-2 text-success-muted-foreground"
            title={acceptanceTitle(clientAcceptance) ?? undefined}
          >
            <p className="text-[13px] font-semibold">{acceptanceLine(clientAcceptance)}</p>
            {longDay(clientAcceptance.planned_start_on) && (
              <p className="text-xs">Planowany start: {longDay(clientAcceptance.planned_start_on)}</p>
            )}
          </div>
        )}
        {badgeToggles.length > 0 && (
          <div
            role="group"
            aria-label="Odznaki etapu"
            className="mt-2 flex flex-wrap items-center gap-1.5"
          >
            {badgeToggles.map((badge) => (
              <button
                key={badge.key}
                type="button"
                aria-pressed={badge.active}
                disabled={Boolean(badge.disabledReason)}
                title={badge.disabledReason ?? undefined}
                onClick={badge.onToggle}
                className={cn(
                  "inline-flex h-7 items-center gap-1 rounded-full border px-2.5 text-[11px] font-semibold transition-colors disabled:opacity-50",
                  badge.active
                    ? "border-success/40 bg-success/10 text-success"
                    : "border-border bg-background text-muted-foreground hover:bg-accent",
                )}
              >
                {badge.active ? "✓ " : "+ "}
                {badge.label.replace(/\s*✓$/, "")}
              </button>
            ))}
          </div>
        )}
        {readOnly && (
          <PersonMoreMenu
            onOpenCv={() => setOpenOriginal(true)}
            onSendEmail={() => setOpenEmail(true)}
            profileHref={profileHref}
          />
        )}
      </div>

      {/* ── Sekcje doku / treść zakładki ─────────────────────────────── */}
      {/* `data-person-scroll` stoi na elemencie, który się przewija: w wąskim
          doku na całym środku (akcje + sekcje), po „Rozwiń” na treści zakładki
          (mierzy go test „pasek zakładek stoi w miejscu”). */}
      <div
        className={cn("space-y-3 p-4", tabsOpen && "min-h-0 flex-1 overflow-y-auto")}
        data-person-scroll={tabsOpen ? "" : undefined}
      >
        {/* 0399: przypięte notatki kandydata — z każdej rekrutacji. */}
        {/* Zwinięte także po „Rozwiń”: stoją NAD paskiem zakładek, więc muszą
            mieć tę samą wysokość w każdej zakładce. */}
        <PinnedCandidateNotes candidateId={item.candidate_id} collapsed={split || tabsOpen} />
        {workbench ? (
          <div hidden={!expanded}>
            <WorkbenchBelowTabsContext.Provider value={stageFold}>{workbench}</WorkbenchBelowTabsContext.Provider>
          </div>
        ) : null}
        <div className="space-y-3" hidden={expanded} data-testid="dock-sections">
        <DockSection
          id="process"
          label={DOCK_SECTION_LABEL.process}
          summary={`${currentStageLabel}${item.days_in_stage != null ? ` · ${daysLabel(item.days_in_stage)}` : ""}${nextAction && nextAction.kind !== "none" ? ` · ${nextAction.label}` : ""}`}
          isNow={nowSection === "process"}
          open={isOpen("process")}
          onToggle={() => toggleSection("process")}
        >
          <div className="space-y-3">
            {/* 0372: follow-up z kandydatem, gdy klient milczy — jeden telefon
                na osobę, także gdy jest w kilku procesach. */}
            {item.followup && (
              <DockFollowupBlock candidateId={item.candidate_id} badge={item.followup} />
            )}
            {item.interview_badge && (
              <DockInterviewCycle
                badge={item.interview_badge}
                pair={{
                  candidate_id: item.candidate_id,
                  candidate_name: fullName,
                  candidate_email: candidate?.email ?? null,
                  job_id: jobId,
                  job_title: jobTitle ?? null,
                  client_id: clientId,
                  client_name: null,
                }}
                readOnly={readOnly}
                onDebrief={(eventId) => setDebriefFor({ eventId })}
                onAddClientSlots={onAddClientSlots}
              />
            )}
            {pairQuestionsWithoutEvent && (
              <DockClientInterviewQuestions
                readOnly={readOnly}
                onOpen={() => setDebriefFor({ eventId: null })}
              />
            )}
            {/* 04.10.2026: sekcja stoi też poza „Umową” i „Zatrudnionym”, gdy para
                ma już umowę w Generatorze (wygenerowaną po rozmowie u klienta). */}
            {(CONTRACT_PANEL_STAGES.has(item.stage ?? "") || item.agreement) && (
              <DockContractSteps
                candidateId={item.candidate_id}
                jobId={jobId}
                clientId={clientId}
                orderStatus={item.order_status ?? null}
                readOnly={readOnly}
                agreement={item.agreement ?? null}
                onGenerate={onOpenWorkbench ? () => onOpenWorkbench("contract") : undefined}
                onMarkHired={hiredTarget ? () => onMoveTo(hiredTarget) : undefined}
              />
            )}
            <div className="space-y-2 rounded-lg border border-border bg-muted/20 p-3 text-xs">
              <div className="flex items-center justify-between gap-2 font-medium text-foreground">
                <span className="truncate">Etap · {currentStageLabel}</span>
                {item.days_in_stage != null && (
                  <span className="inline-flex shrink-0 items-center gap-1 text-muted-foreground">
                    <Clock className="h-3 w-3" /> {daysLabel(item.days_in_stage)}
                  </span>
                )}
              </div>

              {/* Oś czasu etapu — wyłącznie z faktów, które karta niesie.
                  Wpisów, których backend nie ma (pobranie CV, kontakt), tu
                  nie ma: zmyślony wiersz w historii jest gorszy niż jej brak. */}
              <ul className="space-y-0">
                <TimelineEntry
                  title={
                    item.added_to_job_by_name?.trim()
                      ? "Dodany do rekrutacji"
                      : "Dodany do rekrutacji (brak danych o osobie)"
                  }
                  when={
                    item.added_to_job_at ? formatDate(item.added_to_job_at) : null
                  }
                  who={item.added_to_job_by_name?.trim() || null}
                />
                {closed ? (
                  <TimelineEntry
                    title={`${closed.verb} · ${closed.reasonText}`}
                    when={closed.at ? formatDate(closed.at) : null}
                    who={closed.by}
                  />
                ) : item.days_in_stage != null ? (
                  <TimelineEntry
                    title={`W etapie od ${daysLabel(item.days_in_stage)}`}
                    who={currentStageLabel}
                  />
                ) : null}
                {nextAction && nextAction.kind !== "none" && (
                  <TimelineEntry
                    tone="now"
                    title={`Następna akcja: ${nextAction.label}`}
                    who={
                      nextAction.tone === "gate"
                        ? "Ruch zablokowany bramką — patrz „Inny etap…”."
                        : nextAction.tone === "due"
                          ? "Po terminie — ta karta czeka dłużej, niż powinna."
                          : null
                    }
                  />
                )}
              </ul>
              <div className="flex items-start gap-1.5 border-t border-border pt-2 text-muted-foreground">
                <UserPlus className="mt-0.5 h-3 w-3 shrink-0" />
                <span>{addedAttribution}</span>
              </div>
            </div>

            {onOpenWorkbench ? (
              <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-2">
                <WorkbenchLink onClick={() => onOpenWorkbench("interviews")}>
                  Rozmowy i werdykt klienta
                </WorkbenchLink>
                <WorkbenchLink onClick={() => onOpenWorkbench("contract")}>
                  Umowa
                </WorkbenchLink>
              </div>
            ) : null}
          </div>
        </DockSection>

        <DockSection
          id="screening"
          label={DOCK_SECTION_LABEL.screening}
          summary={screeningSectionSummary(item.card, screeningState?.sheet?.overall_fit ?? null)}
          isNow={nowSection === "screening"}
          open={isOpen("screening")}
          onToggle={() => toggleSection("screening")}
        >
          <div className="space-y-3">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onOpenScreening(item.id, fullName)}
              className="w-full justify-start"
            >
              <Sparkles className="h-3.5 w-3.5" /> Otwórz rozmowę z kandydatem
            </Button>
            {/* „Ściąga do rozmowy” (29.09.2026): tekst na start, odpowiedzi na
                pytania kandydata i trzy pytania z profilu — z wyjaśnienia
                „Po ludzku”. Pusta ściąga się nie renderuje. */}
            <DockCallCheatsheet jobId={jobId} />
            {screeningQuery.isSuccess ? (
              // Sekcje 4 i 8 Championa — co sprawdzić i na co uważać, zanim
              // rekruter zadzwoni. Zwinięte: dok ma być krótki.
              <details
                className="rounded-lg border border-border p-2 text-xs"
                data-testid="dock-champion-brief"
              >
                <summary className="cursor-pointer font-medium text-foreground">
                  Na co uważać u tego klienta
                </summary>
                <div className="mt-2 space-y-2">
                  <ExperienceChips
                    experience={
                      (screeningState?.champion_profile as Partial<ChampionProfile>)
                        ?.experience
                    }
                  />
                  <ChampionInsightsDigest
                    profile={screeningState?.champion_profile as Partial<ChampionProfile>}
                    limit={3}
                  />
                </div>
              </details>
            ) : null}
            {screeningQuery.isLoading ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
              </div>
            ) : screeningQuery.isError ? (
              <DockLoadError what="screening" onRetry={() => void screeningQuery.refetch()} />
            ) : screeningState ? (
              // Warunki, odpowiedzi i ocena w kolejności formularza. Edycja:
              // „Otwórz rozmowę z kandydatem” wyżej (formularz screeningu).
              <ScreeningSummaryView
                state={screeningState}
                className="rounded-lg border border-border bg-muted/20 p-3"
                legacy={<ScreeningLegacyText candidateId={item.candidate_id} jobId={jobId} />}
              />
            ) : null}
          </div>
        </DockSection>

        <DockSection
          id="cv"
          label={DOCK_SECTION_LABEL.cv}
          summary={companyBrandedQuery.isSuccess ? companyCv.text : "Oryginał i CV firmowe"}
          isNow={nowSection === "cv"}
          open={isOpen("cv")}
          onToggle={() => toggleSection("cv")}
        >
          <div className="space-y-3">
            {/* 0521: klient bierze swój formularz CV zamiast CV firmowego —
                formularz pierwszy, CV firmowe tylko na żądanie (decyzja D2). */}
            {item.client_form ? (
              <ClientFormCard
                stageId={item.id}
                candidateName={fullName}
                readOnly={readOnly}
                openDialog={clientFormOpen}
                onOpenDialogChange={setClientFormOpen}
                onGenerateCompanyCv={() => setOpenGenerator(true)}
              />
            ) : null}
            {/* 0525: tabela punktowa klienta (Excel) — tylko gdy jest jej wzór. */}
            {item.client_form ? (
              <ClientFormCard
                kind="score"
                stageId={item.id}
                candidateName={fullName}
                readOnly={readOnly}
              />
            ) : null}
            {/* Dwa dokumenty, dwa zdania, a pod każdym jego akcje (D1, 14.10.2026):
                CV firmowe pary i oryginał — ze zgłoszenia albo z profilu. Brak
                kopii w zgłoszeniu to nie „brak CV”, jeśli profil je ma. */}
            <ul className="space-y-2.5 text-xs" data-testid="dock-cv-state">
              <li className="space-y-1.5" data-testid="dock-company-cv">
                <div className="flex items-start gap-1.5">
                  {companyBrandedQuery.isLoading ? (
                    <Loader2 className="mt-0.5 h-3 w-3 animate-spin text-muted-foreground" aria-hidden="true" />
                  ) : (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "mt-1 h-2 w-2 shrink-0 rounded-full",
                        brandedFailed
                          ? "bg-muted-foreground"
                          : companyCv.tone === "success"
                            ? "bg-success"
                            : companyCv.tone === "info"
                              ? "bg-info"
                              : companyCv.tone === "warning"
                                ? "bg-warning"
                                : "bg-muted-foreground",
                      )}
                    />
                  )}
                  <span className="min-w-0 flex-1 text-foreground">
                    {brandedFailed ? (
                      <>
                        CV firmowe: nie udało się sprawdzić ·{" "}
                        <button
                          type="button"
                          onClick={() => {
                            void cvBrandedQuery.refetch();
                            if (stageBranded.pairStageId != null) void companyBrandedQuery.refetch();
                          }}
                          className="font-medium text-primary hover:underline"
                        >
                          Ponów
                        </button>
                      </>
                    ) : (
                      companyCv.text
                    )}
                  </span>
                </div>
                {/* Awaria odczytu nie udaje braku CV: bez pobierania i bez „Generuj CV”. */}
                {!brandedFailed && (canDownloadCompanyCv || !readOnly) ? (
                  <div className="flex flex-wrap gap-1.5 pl-3.5">
                    {canDownloadCompanyCv ? (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void downloadCompanyCv("docx")}
                          disabled={downloadingCv != null || companyConsentMissing}
                          loading={downloadingCv === "docx"}
                        >
                          <Download className="h-3.5 w-3.5" aria-hidden /> Pobierz Word
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          aria-label="Pobierz PDF"
                          onClick={() => void downloadCompanyCv("pdf")}
                          disabled={downloadingCv != null || companyConsentMissing}
                          loading={downloadingCv === "pdf"}
                        >
                          <FileDown className="h-3.5 w-3.5" aria-hidden /> PDF
                        </Button>
                      </>
                    ) : null}
                    {!readOnly ? (
                      stageCv === "ready" ? (
                        <Button size="sm" variant="outline" onClick={() => setOpenBranded(true)}>
                          <Pencil className="h-3.5 w-3.5" aria-hidden /> Edytuj CV
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setOpenGenerator(true)}
                          disabled={companyBrandedQuery.isLoading}
                        >
                          <Sparkles className="h-3.5 w-3.5" aria-hidden /> Generuj CV
                        </Button>
                      )
                    ) : null}
                  </div>
                ) : null}
                {companyConsentMissing ? (
                  <p className="pl-3.5 text-muted-foreground" data-testid="dock-company-cv-consent">
                    Bez zrzutu zgody RODO nie pobierzesz CV.{" "}
                    {onOpenWorkbench ? (
                      <WorkbenchLink onClick={() => onOpenWorkbench("cv")}>
                        Dołącz go w karcie „CV do klienta”
                      </WorkbenchLink>
                    ) : (
                      "Dołącz go w karcie „CV do klienta”."
                    )}
                  </p>
                ) : null}
              </li>
              <li className="space-y-1.5">
                <div className="flex items-start gap-1.5">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "mt-1 h-2 w-2 shrink-0 rounded-full",
                      originalCv.kind === "none" ? "bg-warning" : originalCv.kind === "loading" ? "bg-border" : "bg-success",
                    )}
                  />
                  <span className="min-w-0 flex-1 text-foreground">{originalCvSentence(originalCv)}</span>
                </div>
                {originalCv.kind === "snapshot" || originalCv.kind === "unknown" ? (
                  <div className="pl-3.5">
                    <Button size="sm" variant="outline" onClick={() => setOpenOriginal(true)}>
                      <FileText className="h-3.5 w-3.5" aria-hidden /> Pokaż CV oryginalne
                    </Button>
                  </div>
                ) : originalCv.kind === "profile" ? (
                  <div className="pl-3.5">
                    <Button size="sm" variant="outline" onClick={() => setProfileCvPreviewId(originalCv.doc.id)}>
                      <FileText className="h-3.5 w-3.5" aria-hidden /> Pokaż CV z profilu
                    </Button>
                  </div>
                ) : originalCv.kind === "none" && !canUploadCv ? (
                  <div className="pl-3.5">
                    <Link
                      href={`${profileHref}&tab=documents`}
                      target="_blank"
                      rel="noopener"
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Dodaj CV w profilu kandydata ↗
                    </Link>
                  </div>
                ) : null}
              </li>
              {earlyQc && (
                <li className="flex items-start gap-1.5" data-testid="dock-early-qc">
                  {qcQuery.isLoading ? (
                    <Loader2 className="mt-0.5 h-3 w-3 animate-spin text-muted-foreground" aria-hidden="true" />
                  ) : (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "mt-1 h-2 w-2 shrink-0 rounded-full",
                        qcQuery.isSuccess && qcQuery.data.passed
                          ? "bg-success"
                          : qcQuery.isSuccess
                            ? "bg-warning"
                            : "bg-muted-foreground",
                      )}
                    />
                  )}
                  <span className="min-w-0 flex-1 text-foreground">
                    {earlyQcSentence(qcQuery.isLoading, qcQuery.isSuccess ? qcQuery.data : null)}
                  </span>
                  {onOpenQc && qcQuery.isSuccess && (
                    <button
                      type="button"
                      onClick={onOpenQc}
                      className="shrink-0 font-medium text-primary hover:underline"
                    >
                      Otwórz QC
                    </button>
                  )}
                </li>
              )}
            </ul>
            {canUploadCv ? (
              <>
                <DockCvFreshness
                  stageId={item.id}
                  original={originalCv}
                  profileDocs={ownProfileCvDocs}
                  candidate={candidate}
                  uploadedAt={cvUpload.uploadedAt}
                  onShowProfileCv={setProfileCvPreviewId}
                />
                {/* Szkic CV firmowego bywa na poprzednim wierszu etapu pary
                    (ruch karty) — ramka czyta go tam (audyt 13.10.2026). */}
                {stageCvStatus(cvBrandedQuery.data) === "ready" ||
                (stageBranded.pairStageId != null && companyBranded?.status === "draft") ? (
                  <CompanyCvStaleNotice
                    stageId={item.id}
                    cvStageId={editStageId}
                    candidateId={item.candidate_id}
                    candidateName={fullName}
                    jobId={jobId}
                    branded={cvBrandedQuery.data}
                    original={originalCv}
                  />
                ) : null}
                <StageCvUploadTile
                  upload={cvUpload}
                  label={originalCv.kind === "none" ? "Wgraj CV" : "Wgraj nowe CV"}
                />
              </>
            ) : null}
            {CV_CLIENT_LINKS_UI_ENABLED && !readOnly && (
              <Button
                size="sm"
                variant="outline"
                disabled={brandedStatus !== "finalized"}
                onClick={() => setOpenShare(true)}
                title={
                  brandedStatus !== "finalized"
                    ? "Najpierw zapisz CV do klienta w edytorze"
                    : undefined
                }
                className="justify-start"
              >
                <Send className="h-3.5 w-3.5" /> Wyślij klientowi
              </Button>
            )}
            {onOpenWorkbench ? (
              <WorkbenchLink onClick={() => onOpenWorkbench("cv")}>
                {/* Stawka i „Oznacz CV wysłane” są w karcie tylko na „Zweryfikowanym” (D3). */}
                {item.stage === "verified"
                  ? "Wysyłka CV do klienta (stawka, wersje)"
                  : "CV do klienta: strony i wersje"}
              </WorkbenchLink>
            ) : null}
          </div>
        </DockSection>

        <DockSection
          id="match"
          label={DOCK_SECTION_LABEL.match}
          summary={normalizedScore != null ? `${normalizedScore} / 100` : "Uzasadnienie dopasowania"}
          isNow={nowSection === "match"}
          open={isOpen("match")}
          onToggle={() => toggleSection("match")}
        >
          <DopasowanieTab
            candidateId={item.candidate_id}
            recruitments={[{ job_id: jobId, job_title: jobLabel }]}
            defaultJobId={jobId}
            readOnly={readOnly}
          />
        </DockSection>

        <DockSection
          id="notes"
          label={DOCK_SECTION_LABEL.notes}
          summary={notesQuery.isSuccess ? dockNotesSummary(notesSplit) : "Notatki w tej rekrutacji"}
          isNow={nowSection === "notes"}
          open={isOpen("notes")}
          onToggle={() => toggleSection("notes")}
        >
          <PersonNotesHistory
            variant="dock"
            candidateId={item.candidate_id}
            jobId={jobId}
            readOnly={readOnly}
            onOpenHistory={onOpenWorkbench ? () => onOpenWorkbench("notes") : undefined}
          />
        </DockSection>
        </div>
      </div>
      </div>

      {questionsHint && !readOnly ? (
        <ClientQuestionsNoteHint
          count={questionsHint.length}
          onSave={() => {
            setDebriefFor({
              eventId: interviewBadge?.interview_event_id ?? null,
              initialQuestions: questionsHint,
            });
            setQuestionsHint(null);
          }}
          onDismiss={() => setQuestionsHint(null)}
        />
      ) : null}
      {/* Notatka zawsze pod ręką — bez przechodzenia do sekcji „Notatki". */}
      {!readOnly && (
        <DockNoteComposer
          value={noteText}
          onChange={setNoteText}
          onSubmit={() => submitNote()}
          onSubmitAndFill={noteFillAvailable ? () => submitNote(true) : undefined}
          pending={addNoteMutation.isPending}
          jobId={jobId}
          big={noteBig}
          onBigChange={setNoteBig}
        />
      )}

      {profileCvPreviewId != null && profileCvQuery.data && (
        <FilePreviewModal
          documents={profileCvQuery.data}
          initialDocumentId={profileCvPreviewId}
          candidateId={item.candidate_id}
          onClose={() => setProfileCvPreviewId(null)}
          onDownload={(doc) =>
            import("@/components/v2/files/FilePreviewModal")
              .then((m) => m.downloadDocumentBlob(item.candidate_id, doc))
              .catch(() => showError("Nie udało się pobrać pliku."))
          }
        />
      )}
      {qcStageId != null && (
        <CvQcDialog
          stageId={qcStageId}
          open
          onClose={() => {
            setQcStageId(null);
            refreshMoveRequirements();
          }}
          onChanged={() => {
            void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
            void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
            refreshMoveRequirements();
          }}
          onMoveNext={
            onAdvance
              ? () => {
                  setQcStageId(null);
                  refreshMoveRequirements();
                  onAdvance();
                }
              : undefined
          }
        />
      )}
      {rateChangeOpen ? (
        <RateChangeDialog
          open
          onOpenChange={(o) => !o && setRateChangeOpen(false)}
          candidateId={item.candidate_id}
          jobId={jobId}
          description={`${fullName} · ${jobLabel}`}
        />
      ) : null}
      {clientRateChangeOpen ? (
        <ClientRateChangeDialog
          open
          onOpenChange={(o) => !o && setClientRateChangeOpen(false)}
          candidateId={item.candidate_id}
          jobId={jobId}
          description={`${fullName} · ${jobLabel}`}
          candidateRate={dockCandidateRate(item)}
        />
      ) : null}
      {debriefFor != null && (
        <DebriefRequiredDialog
          open
          onOpenChange={(open) => {
            if (open) return;
            setDebriefFor(null);
            refreshMoveRequirements();
          }}
          eventId={debriefFor.eventId}
          candidateId={item.candidate_id}
          candidateName={fullName}
          jobId={jobId}
          initialQuestions={debriefFor.initialQuestions}
          submitLabel="Zapisz pytania"
          onSaved={() => {
            setDebriefFor(null);
            refreshMoveRequirements();
          }}
        />
      )}
      {openOriginal && (
        <CVOriginalPreviewModal
          open
          onOpenChange={setOpenOriginal}
          stageId={item.id}
          jobTitle={jobLabel}
          candidateName={fullName}
        />
      )}
      {!readOnly && openBranded && (
        <CVBrandedEditModal
          open
          onOpenChange={(open) => {
            setOpenBranded(open);
            if (!open) {
              void queryClient.invalidateQueries({
                queryKey: ["cv-share-tokens-recruitment", item.candidate_id, jobId],
              });
            }
          }}
          onRegenerate={() => setOpenGenerator(true)}
          stageId={editStageId}
          jobTitle={jobLabel}
          candidateName={fullName}
        />
      )}
      {!readOnly && openGenerator && (
        <CvGeneratorDialog
          open
          onOpenChange={setOpenGenerator}
          candidateId={item.candidate_id}
          candidateName={fullName}
          jobId={jobId}
          onEnqueued={() => {
            setOpenGenerator(false);
            showSuccess("CV generuje się w tle. Gdy będzie gotowe, podepnie się do tego etapu.");
            void queryClient.invalidateQueries({ queryKey: ["cv-branded", item.id] });
            refreshMoveRequirements();
          }}
        />
      )}
      {!readOnly && openShare && (
        <CVShareLinkModal
          open
          onOpenChange={setOpenShare}
          stageId={item.id}
          candidateName={fullName}
        />
      )}
      {/* Dopiero z danymi — modal nigdy nie otwiera się z pustym adresem
          (adres nie jest na karcie kanbanu, dociągamy go leniwie wyżej). */}
      {openEmail && candidateDetailQuery.data && (
        <SendEmailV2
          open
          onOpenChange={setOpenEmail}
          candidateId={item.candidate_id}
          candidateName={fullName}
          candidateEmail={candidateDetailQuery.data.email ?? ""}
          requestId={jobId}
        />
      )}
      {canBlacklist && openBlacklist && (
        <BlacklistDialog
          open
          onOpenChange={setOpenBlacklist}
          candidateId={item.candidate_id}
          candidateName={fullName}
          alreadyBlacklisted={candidate?.status === "blacklisted"}
        />
      )}
      {openAddAlso && (
        <QuickAssignV2
          open
          onOpenChange={setOpenAddAlso}
          candidateId={item.candidate_id}
          candidateName={fullName}
        />
      )}
      {openSendAlso && (
        <DlMatchDialog
          open
          onOpenChange={setOpenSendAlso}
          candidateId={item.candidate_id}
          candidateName={fullName}
          jobId={jobId}
          jobLabel={jobLabel}
          defaultRate={item.client_rate_value != null ? String(item.client_rate_value) : ""}
          rateUnit={sendAlsoUnit(item.client_rate_unit)}
          currency={item.client_rate_currency || "PLN"}
        />
      )}
      {openPreContract && (
        <PreContractRequestDialog
          open
          onOpenChange={setOpenPreContract}
          candidateId={item.candidate_id}
          jobId={jobId}
          personLabel={fullName}
          onDone={() => invalidatePreContract(queryClient, jobId)}
        />
      )}
      {/* „Zastąpić CV do klienta?” po wgraniu pliku „B2B_…” (15.10.2026). */}
      {cvUpload.confirmDialog}
    </CvFileDropTarget>
  );
}
