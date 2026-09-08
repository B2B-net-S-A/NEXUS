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

import { useEffect, useMemo, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  FileText,
  HelpCircle,
  Loader2,
  Mail,
  Send,
  Sparkles,
  UserPlus,
  UserX,
  X,
} from "lucide-react";

import api, {
  candidatesApi,
  candidateStageCvApi,
  extractErrorMsg,
  screeningApi,
  type CVBrandedState,
  type CVOriginalSnapshot,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TabbedNav } from "@/components/ds";
import { cn, formatDate } from "@/lib/utils";
import { countPl } from "@/lib/plural-pl";
import { encodeJobBackRef } from "@/lib/url-filters";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import { ScoreRing, type KanbanColumn, type KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { NextAction } from "@/lib/pipeline-next-action";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { CVShareLinkModal } from "@/components/v2/modals/CVShareLinkModal";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";

// Edytor brandowanego CV jest ciężki (rich text) — leniwy import jak w
// CandidateDetailV2, żeby nie puchła zakładka Pipeline dla osób, które go
// nigdy nie otworzą.
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

const DOCK_TABS: { value: DockTab; label: string }[] = [
  { value: "process", label: "W procesie" },
  { value: "screening", label: "Screening" },
  { value: "cv", label: "CV" },
  { value: "match", label: "Dopasowanie" },
  { value: "notes", label: "Notatki" },
];

interface NoteListItem {
  id: number;
  content: string;
  content_rendered?: string | null;
  author_name?: string | null;
  created_at: string;
}

/** Wycinek `CandidateResponse`, którego dok naprawdę używa. `candidatesApi.get`
 *  nie jest typowane, więc typujemy tu wprost — zamiast `any`. */
interface CandidateDetail {
  email?: string | null;
  city?: string | null;
  location?: string | null;
  status?: string | null;
  availability_status?: string | null;
  availability_date?: string | null;
  notice_period?: number | null;
  notice_period_unit?: "days" | "weeks" | "months" | null;
  max_onsite_days_per_week?: number | null;
  linkedin_current_title?: string | null;
  linkedin_current_company?: string | null;
}

/** Etykiety statusu kandydata — lustro `CandidateStatus` z backendu. */
const CANDIDATE_STATUS_LABEL: Record<string, string> = {
  active: "Aktywny",
  open_to_offers: "Otwarty na oferty",
  employed: "Zatrudniony",
  inactive: "Nieaktywny",
  blacklisted: "Czarna lista",
  archived: "Zarchiwizowany",
};

const NOTICE_UNIT_LABEL: Record<string, string> = {
  days: "dni",
  weeks: "tyg.",
  months: "mies.",
};

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

/** Wiersz „Warunki wobec oferty" — brak danych mówi „—", nie znika. */
function ConditionRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 text-foreground">{children}</span>
    </>
  );
}

export interface PipelineCandidateDockProps {
  item: KanbanItem;
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
  /** Pozycja karty w kolejności TABLICY (1-based) i liczba kart. Bez nich
   *  nawigator „‹ N z M ›" się nie renderuje — nie zgadujemy pozycji. */
  position?: number | null;
  total?: number;
  onSelectPrevious?: () => void;
  onSelectNext?: () => void;
  /** Wiersz „co dalej" policzony przez tablicę (`nextActionFor`). */
  nextAction?: NextAction | null;
  /** Pierwszy DOZWOLONY etap po bieżącym — główna akcja doku. */
  primaryTarget?: KanbanColumn | null;
  onClose: () => void;
  onMoveTo: (col: KanbanColumn) => void;
  onOpenScreening: (stageId: number, name: string) => void;
  onReject: () => void;
}

export function PipelineCandidateDock({
  item,
  jobId,
  currentStageLabel,
  jobTitle,
  matchScore,
  scoresLoading,
  moveTargets,
  readOnly,
  contactFeatureEnabled,
  canReject,
  position,
  total,
  onSelectPrevious,
  onSelectNext,
  nextAction,
  primaryTarget,
  onClose,
  onMoveTo,
  onOpenScreening,
  onReject,
}: PipelineCandidateDockProps) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<DockTab>("process");
  const [openOriginal, setOpenOriginal] = useState(false);
  const [openBranded, setOpenBranded] = useState(false);
  const [openShare, setOpenShare] = useState(false);
  const [openEmail, setOpenEmail] = useState(false);
  const [noteText, setNoteText] = useState("");

  // Zmiana kandydata (nowy klik na tablicy) — wróć na pierwszą zakładkę i
  // wyczyść niedokończony draft notatki; inaczej dok pokazywałby zakładkę
  // „Notatki" poprzedniego kandydata z jego niewysłanym tekstem.
  useEffect(() => {
    setActiveTab("process");
    setNoteText("");
  }, [item.candidate_id]);

  const fullName = `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;
  const initials = fullName
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const isPending = item.verification_status === "pending";
  const noKnownBlockers =
    !item.hm_veto &&
    !isPending &&
    moveTargets.length > 0 &&
    moveTargets.every((t) => !t.blockedReason);
  const normalizedScore =
    typeof matchScore === "number" && Number.isFinite(matchScore)
      ? Math.max(0, Math.min(100, Math.round(matchScore)))
      : null;

  // `budget_max_at_move` to budżet zapisany PRZY RUCHU na „Zweryfikowany" —
  // porównanie ma sens tylko wtedy, gdy karta niesie obie liczby.
  const overBudget =
    item.expected_rate_value != null &&
    item.budget_max_at_move != null &&
    Number(item.expected_rate_value) > item.budget_max_at_move;

  const addedAttribution = item.added_to_job_by_name?.trim()
    ? `Dodano do rekrutacji przez: ${item.added_to_job_by_name.trim()}${
        item.added_to_job_at ? ` · ${formatDate(item.added_to_job_at)}` : ""
      }`
    : `Brak danych o osobie dodającej${
        item.added_to_job_at ? ` · dodano ${formatDate(item.added_to_job_at)}` : ""
      }`;

  // ── Screening — skrót wyniku, jeśli backend go ma ──────────────────────
  const screeningQuery = useQuery({
    queryKey: ["pipeline-stage-screening", item.id],
    queryFn: () => screeningApi.getForStage(item.id).then((r) => r.data),
    enabled: activeTab === "screening",
    staleTime: 30_000,
  });
  const screeningAnswers = screeningQuery.data?.screening_answers ?? null;

  // ── CV — status oryginalnego/brandowanego (tylko na zakładce CV) ───────
  const cvOriginalQuery = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", item.id],
    queryFn: () => candidateStageCvApi.original.get(item.id).then((r) => r.data),
    enabled: activeTab === "cv",
  });
  const cvBrandedQuery = useQuery<CVBrandedState>({
    queryKey: ["cv-branded", item.id],
    queryFn: () => candidateStageCvApi.branded.get(item.id).then((r) => r.data),
    enabled: activeTab === "cv" || openBranded || openShare,
  });
  const brandedStatus = cvBrandedQuery.data?.status ?? "none";

  // ── Notatki — przypięte do TEJ rekrutacji (candidate_id + job_id) ──────
  const notesQueryKey = useMemo(
    () => [...candidateQueryKeys.notes(item.candidate_id), jobId] as const,
    [item.candidate_id, jobId]
  );
  const notesQuery = useQuery<{ items?: NoteListItem[] }>({
    queryKey: notesQueryKey,
    queryFn: () =>
      api
        .get(`/api/notes?candidate_id=${item.candidate_id}&job_id=${jobId}`)
        .then((r) => r.data),
    enabled: activeTab === "notes",
  });
  const addNoteMutation = useMutation({
    mutationFn: (content: string) =>
      api.post("/api/notes", {
        candidate_id: item.candidate_id,
        job_id: jobId,
        content,
        note_type: "general",
      }),
    onSuccess: () => {
      setNoteText("");
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.notes(item.candidate_id),
      });
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.timelineRoot(item.candidate_id),
      });
      showSuccess("Notatka dodana.");
    },
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się dodać notatki"),
  });

  const submitNote = () => {
    const content = noteText.trim();
    if (!content || addNoteMutation.isPending) return;
    addNoteMutation.mutate(content);
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
  });
  const candidate = candidateDetailQuery.data ?? null;

  const availabilityLabel = candidate?.availability_date
    ? `od ${formatDate(candidate.availability_date)}`
    : candidate?.notice_period != null
      ? `wypowiedzenie ${candidate.notice_period} ${
          NOTICE_UNIT_LABEL[candidate.notice_period_unit ?? "days"] ?? ""
        }`.trim()
      : null;

  // 0 dni w biurze = wyłącznie zdalnie (kontrakt kolumny `max_onsite_days_per_week`).
  const onsiteLabel =
    candidate?.max_onsite_days_per_week == null
      ? null
      : candidate.max_onsite_days_per_week === 0
        ? "Zdalnie"
        : `Do ${candidate.max_onsite_days_per_week} dni w biurze`;
  // Modal montuje się dopiero z DANYMI (patrz render niżej) — w oknie między
  // kliknięciem a odpowiedzią pole „Do" byłoby puste. Gdy zapytanie padnie,
  // intencja wysyłki jest zamykana z toastem, a nie wisi na spinnerze.
  const emailLookupFailed = openEmail && candidateDetailQuery.isError;
  useEffect(() => {
    if (!emailLookupFailed) return;
    showError("Nie udało się pobrać adresu e-mail kandydata.");
    setOpenEmail(false);
  }, [emailLookupFailed, showError]);

  return (
    <div className="flex max-h-[calc(100vh-2rem)] flex-col rounded-xl border border-border bg-card">
      {/* ── Nagłówek ──────────────────────────────────────────────────── */}
      <div className="space-y-2.5 border-b border-border p-4">
        {/* Nawigator „‹ N z M ›" — kolejność tablicy, kolumna po kolumnie.
            Renderuje się tylko z podaną pozycją: bez niej nie zgadujemy. */}
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          {position != null && total ? (
            <>
              <button
                type="button"
                onClick={onSelectPrevious}
                disabled={position <= 1}
                className="rounded-md p-0.5 hover:bg-accent disabled:opacity-40"
                aria-label="Poprzednia karta"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span className="tabular-nums">
                {position} z {total}
              </span>
              <button
                type="button"
                onClick={onSelectNext}
                disabled={position >= total}
                className="rounded-md p-0.5 hover:bg-accent disabled:opacity-40"
                aria-label="Następna karta"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </>
          ) : (
            <span className="text-[10px] font-semibold uppercase tracking-wide text-primary">
              Karta w procesie
            </span>
          )}
          <button
            type="button"
            onClick={onClose}
            className="ml-auto shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent"
            aria-label="Zamknij dok"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-foreground">
              {fullName}
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
                  : "Brak danych profilowych")}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {(normalizedScore != null || scoresLoading) && (
            <ScoreRing score={normalizedScore} density="compact" />
          )}
          {candidate?.status && (
            <Badge
              variant={candidate.status === "blacklisted" ? "danger" : "neutral"}
              size="sm"
            >
              {CANDIDATE_STATUS_LABEL[candidate.status] ?? candidate.status}
            </Badge>
          )}
          {isPending && (
            <Badge variant="warning" size="sm">
              <HelpCircle className="h-2.5 w-2.5" /> Pending
            </Badge>
          )}
          {contactFeatureEnabled && (
            <ContactStatusBadge contactCase={item.contact_case} size="sm" />
          )}
          {/* Zielona pigułka mówi o tym, co karta WIE — nie o całej bramce.
              Pozostałych siedmiu powodów (czarna lista, NDA, konkurent,
              zatrudnienie u klienta…) backend pilnuje dopiero wewnątrz
              `POST /pipeline/move`, więc tooltip nazywa granicę tej obietnicy;
              bez niego pigułka obiecywałaby przejście, którego nie sprawdziła. */}
          {noKnownBlockers && (
            <Badge
              variant="success"
              size="sm"
              title="Karta nie niesie weta hiring managera ani oczekującej weryfikacji, a żaden etap nie jest wyszarzony. Pozostałe powody blokady bramka sprawdza dopiero przy samym ruchu."
            >
              <CheckCircle2 className="h-2.5 w-2.5" /> Brak znanych blokad
            </Badge>
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

        <TabbedNav
          ariaLabel="Zakładki karty kandydata"
          value={activeTab}
          onValueChange={(v) => setActiveTab(v as DockTab)}
          tabs={DOCK_TABS}
          overflow="scroll"
        />
      </div>

      {/* ── Treść zakładki (przewijana) ──────────────────────────────── */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {activeTab === "process" && (
          <div className="space-y-3">
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
                {item.days_in_stage != null && (
                  <TimelineEntry
                    title={`W etapie od ${daysLabel(item.days_in_stage)}`}
                    who={currentStageLabel}
                  />
                )}
                {nextAction && nextAction.kind !== "none" && (
                  <TimelineEntry
                    tone="now"
                    title={`Następna akcja: ${nextAction.label}`}
                    who={
                      nextAction.tone === "gate"
                        ? "Ruch zablokowany bramką — patrz „Przenieś na etap”."
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

            {/* Warunki wobec oferty — wyłącznie z danych, które dok już ma
                (karta kanbanu + profil kandydata). Brak danych to „—", nie
                znikający wiersz: pusty rząd czyta się jak „bez zastrzeżeń". */}
            <div className="space-y-1">
              <div className="text-xs font-semibold text-foreground">
                Warunki wobec oferty
              </div>
              <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
                <ConditionRow label="Stawka">
                  {item.expected_rate_value != null ? (
                    <>
                      <span
                        className={cn(
                          "font-medium tabular-nums",
                          overBudget ? "text-warning" : "text-success"
                        )}
                      >
                        {item.expected_rate_value} {item.expected_rate_currency ?? "PLN"}
                        {item.expected_rate_unit ? `/${item.expected_rate_unit}` : ""}
                      </span>
                      {item.budget_max_at_move != null && (
                        <span className="ml-1 text-muted-foreground">
                          {overBudget
                            ? "ponad budżet"
                            : `w budżecie do ${item.budget_max_at_move}`}
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-muted-foreground">brak stawki</span>
                  )}
                </ConditionRow>
                <ConditionRow label="Dostępność">
                  {availabilityLabel ?? <span className="text-muted-foreground">—</span>}
                </ConditionRow>
                <ConditionRow label="Tryb">
                  {onsiteLabel ?? <span className="text-muted-foreground">—</span>}
                </ConditionRow>
                <ConditionRow label="Pokrycie must">
                  <span className="text-muted-foreground">
                    — <span className="text-[10px]">(zakładka „Dopasowanie”)</span>
                  </span>
                </ConditionRow>
              </div>
            </div>
          </div>
        )}

        {activeTab === "screening" && (
          <div className="space-y-3">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onOpenScreening(item.id, fullName)}
              className="w-full justify-start"
            >
              <Sparkles className="h-3.5 w-3.5" /> Otwórz Screening Championa
            </Button>
            {screeningQuery.isLoading ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
              </div>
            ) : screeningAnswers ? (
              <div className="space-y-1.5 rounded-lg border border-border bg-muted/20 p-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-foreground">Wynik</span>
                  <Badge
                    size="sm"
                    variant={
                      screeningAnswers.overall_fit === "fit"
                        ? "success"
                        : screeningAnswers.overall_fit === "miss"
                          ? "danger"
                          : "warning"
                    }
                  >
                    {screeningAnswers.overall_fit === "fit"
                      ? "Pasuje"
                      : screeningAnswers.overall_fit === "miss"
                        ? "Nie pasuje"
                        : "Niepewne"}
                  </Badge>
                </div>
                <div className="text-muted-foreground">
                  Odpowiedziano na{" "}
                  {countPl(screeningAnswers.answers.length, "pytanie", "pytania", "pytań")}
                  {screeningAnswers.answers.some((a) => a.deal_breaker_hit) && (
                    <span className="ml-1 inline-flex items-center gap-0.5 text-destructive">
                      <AlertTriangle className="h-3 w-3" /> deal-breaker trafiony
                    </span>
                  )}
                </div>
                {screeningAnswers.answered_at && (
                  <div className="text-muted-foreground">
                    Wypełniono {formatDate(screeningAnswers.answered_at)}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Brak jeszcze wypełnionego screeningu dla tego etapu.
              </p>
            )}
          </div>
        )}

        {activeTab === "cv" && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {cvOriginalQuery.isLoading ? (
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              ) : cvOriginalQuery.data ? (
                cvOriginalQuery.data.has_snapshot ? (
                  <Badge size="sm" variant="success">
                    CV oryginalne
                  </Badge>
                ) : (
                  <Badge size="sm" variant="warning">
                    Brak CV w momencie zgłoszenia
                  </Badge>
                )
              ) : null}
              {brandedStatus === "finalized" ? (
                <Badge size="sm" variant="success">
                  Brandowane: gotowe
                </Badge>
              ) : brandedStatus === "draft" ? (
                <Badge size="sm" variant="info">
                  Brandowane: draft
                </Badge>
              ) : (
                <Badge size="sm" variant="neutral">
                  Brandowane: brak
                </Badge>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setOpenOriginal(true)}
                className="justify-start"
              >
                <FileText className="h-3.5 w-3.5" /> Pokaż CV oryginalne
              </Button>
              {!readOnly && (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setOpenBranded(true)}
                    className="justify-start"
                  >
                    <FileText className="h-3.5 w-3.5" />{" "}
                    {brandedStatus === "none" ? "Stwórz brandowane" : "Edytuj brandowane"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={brandedStatus !== "finalized"}
                    onClick={() => setOpenShare(true)}
                    title={
                      brandedStatus !== "finalized"
                        ? "Najpierw sfinalizuj brandowane CV"
                        : undefined
                    }
                    className="justify-start"
                  >
                    <Send className="h-3.5 w-3.5" /> Wyślij klientowi
                  </Button>
                </>
              )}
            </div>
          </div>
        )}

        {activeTab === "match" && (
          <DopasowanieTab
            candidateId={item.candidate_id}
            recruitments={[{ job_id: jobId, job_title: jobLabel }]}
            defaultJobId={jobId}
            readOnly={readOnly}
          />
        )}

        {activeTab === "notes" && (
          <div className="space-y-3">
            {!readOnly && (
              <div className="space-y-1.5">
                <textarea
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      submitNote();
                    }
                  }}
                  placeholder="Dodaj notatkę… (Enter wysyła, Shift+Enter nowa linia)"
                  rows={2}
                  className="w-full rounded-md border border-border bg-card px-3 py-2 text-xs focus:outline-hidden focus:ring-2 focus:ring-primary"
                />
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={submitNote}
                    disabled={!noteText.trim() || addNoteMutation.isPending}
                    loading={addNoteMutation.isPending}
                  >
                    <Send className="h-3.5 w-3.5" />
                    Dodaj notatkę
                  </Button>
                </div>
              </div>
            )}
            {notesQuery.isLoading ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
              </div>
            ) : (notesQuery.data?.items ?? []).length > 0 ? (
              <div className="space-y-2">
                {(notesQuery.data?.items ?? []).map((n) => (
                  <div
                    key={n.id}
                    className="rounded-lg border border-border bg-muted/20 p-2.5 text-xs"
                  >
                    <div className="mb-1 flex items-center justify-between text-muted-foreground">
                      <span className="font-medium text-foreground">
                        {n.author_name ?? "Nieznany autor"}
                      </span>
                      <span>{formatDate(n.created_at)}</span>
                    </div>
                    <p className="whitespace-pre-line text-foreground">
                      {n.content_rendered ?? n.content}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Brak notatek dla tej rekrutacji.
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── Przenieś na etap + akcje (zawsze widoczne, niezależnie od zakładki) ── */}
      <div className="space-y-3 border-t border-border bg-muted/10 p-4">
        {moveTargets.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-semibold text-foreground">Przenieś na etap</div>
            <div className="flex flex-wrap gap-1">
              {moveTargets.map(({ col, blockedReason }) => (
                <button
                  key={col.stage_def_id ?? col.stage}
                  type="button"
                  disabled={Boolean(blockedReason)}
                  title={blockedReason ?? undefined}
                  onClick={() => onMoveTo(col)}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                    blockedReason
                      ? "cursor-not-allowed border-border bg-muted text-muted-foreground/60"
                      : "border-border bg-background text-foreground hover:border-primary hover:bg-primary/5"
                  )}
                >
                  {col.name ?? col.stage}
                </button>
              ))}
            </div>
            <p className="text-[10.5px] leading-snug text-muted-foreground">
              Ta sama bramka co w C2 — zablokowany etap jest wyszarzony
              z powodem, zamiast odbić się o 409 po kliknięciu.
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-1.5">
          {/* Główna akcja: pierwszy DOZWOLONY etap po bieżącym. Ta sama ścieżka
              co drag&drop (`requestMove`), więc modale stawki, potwierdzenia
              i powodu odrzucenia działają bez zmian. */}
          {primaryTarget && !readOnly && (
            <Button
              size="sm"
              onClick={() => onMoveTo(primaryTarget)}
              className="col-span-2 justify-start"
            >
              <ChevronRight className="h-3.5 w-3.5" />
              Przenieś na etap: {primaryTarget.name ?? primaryTarget.stage}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => setOpenOriginal(true)}
            className="justify-start"
          >
            <FileText className="h-3.5 w-3.5" /> Otwórz CV
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setOpenEmail(true)}
            loading={openEmail && !candidateDetailQuery.data && candidateDetailQuery.isFetching}
            className="justify-start"
          >
            <Mail className="h-3.5 w-3.5" /> Wyślij wiadomość
          </Button>
          <Link
            href={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
            className="inline-flex h-8 items-center justify-start gap-1.5 rounded-lg border border-border px-3 text-xs text-muted-foreground hover:bg-muted"
          >
            <ExternalLink className="h-3.5 w-3.5" /> Pełny profil
          </Link>
          {canReject && !readOnly && (
            <Button
              size="sm"
              variant="outline"
              onClick={onReject}
              className="justify-start text-destructive hover:bg-destructive/10 hover:text-destructive"
            >
              <Ban className="h-3.5 w-3.5" /> Odrzuć z powodem
            </Button>
          )}
        </div>
      </div>

      {/* Stopka — te same dwa ruchy co strzałki w nagłówku, w zasięgu kciuka
          po przewinięciu doku do końca. */}
      {position != null && total ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
          <Button
            size="sm"
            variant="ghost"
            onClick={onSelectPrevious}
            disabled={position <= 1}
            className="h-7 px-2"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Poprzedni
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onSelectNext}
            disabled={position >= total}
            className="h-7 px-2"
          >
            Następny <ChevronRight className="h-3.5 w-3.5" />
          </Button>
          <span className="ml-auto">Wynik = ten sam, co pierścień na tablicy.</span>
        </div>
      ) : null}

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
          onOpenChange={setOpenBranded}
          stageId={item.id}
          jobTitle={jobLabel}
          candidateName={fullName}
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
        />
      )}
    </div>
  );
}

/** Pusty stan doku — nic nie jest kliknięte na tablicy. Ten sam ton co
 *  `JobMatchDock` w warsztacie C2, żeby dwa doki tej samej rekrutacji
 *  mówiły tym samym językiem. */
export function PipelineCandidateDockEmpty() {
  return (
    <div className="rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
      <CheckCircle2 className="mx-auto mb-2 h-6 w-6 opacity-40" />
      Kliknij kartę na tablicy, aby zobaczyć jej etap, screening, CV i historię.
    </div>
  );
}
