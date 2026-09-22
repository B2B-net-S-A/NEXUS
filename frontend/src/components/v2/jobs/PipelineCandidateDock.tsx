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
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  FileText,
  HelpCircle,
  Loader2,
  Mail,
  MoreHorizontal,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn, formatDate } from "@/lib/utils";
import { countPl } from "@/lib/plural-pl";
import { normalizeRateToMonthly } from "@/lib/verified-rate-gate";
import { encodeJobBackRef } from "@/lib/url-filters";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import { type KanbanColumn, type KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { NextAction } from "@/lib/pipeline-next-action";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { CVShareLinkModal } from "@/components/v2/modals/CVShareLinkModal";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { CV_CLIENT_LINKS_UI_ENABLED } from "@/lib/cv-generator";

// Edytor brandowanego CV jest ciężki (rich text) — leniwy import jak w
// CandidateDetailV2, żeby nie puchła zakładka Pipeline dla osób, które go
// nigdy nie otworzą.
// Radix zamyka menu i oddaje fokus PO `onSelect` — akcja otwierająca modal
// (stawka, powód odrzucenia) musi poczekać jeden tick, inaczej zwrot fokusu
// zamyka świeżo otwarty dialog. Kopia z `JobDetailCompactHeader`.
const deferMenuAction = (action: () => void) => {
  window.setTimeout(action, 0);
};

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

/** Sekcja „Teraz" wg etapu karty (legacy-enum `stage`). */
export function nowSectionForStage(stage: string | null | undefined): DockTab {
  switch (stage) {
    case "posting":
    case "new":
    case "verified":
      return "cv";
    case "screening":
    case "prep_call":
      return "screening";
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
  /**
   * Etap blokujący drogę naprzód (weto HM) i powód — gdy jest, dok zamiast
   * akcji „naprzód" pokazuje wyszarzony krok z powodem, a nie objazd weta.
   * Wynik `primaryForwardMove` z `lib/pipeline-flow.ts`.
   */
  primaryBlocked?: { col: KanbanColumn; reason: string } | null;
  onClose: () => void;
  onMoveTo: (col: KanbanColumn) => void;
  onOpenScreening: (stageId: number, name: string) => void;
  onReject: () => void;
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
  badgeToggles?: ReadonlyArray<{
    key: string;
    label: string;
    active: boolean;
    disabledReason: string | null;
    onToggle: () => void;
  }>;
}

type WorkbenchSection = "cv" | "screening" | "interviews" | "contract";

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
}: {
  onOpenCv: () => void;
  onSendEmail: () => void;
  profileHref: string;
}) {
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="outline" aria-label="Więcej akcji osoby">
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
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
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function PipelineCandidateDock({
  item,
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
  nextAction,
  primaryTarget,
  primaryBlocked = null,
  onClose,
  onMoveTo,
  onOpenScreening,
  onReject,
  onOpenWorkbench,
  badgeToggles = [],
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
  const [openShare, setOpenShare] = useState(false);
  const [openEmail, setOpenEmail] = useState(false);
  const [noteText, setNoteText] = useState("");

  // Zmiana kandydata (nowy klik na tablicy) — wróć na pierwszą zakładkę i
  // wyczyść niedokończony draft notatki; inaczej dok pokazywałby zakładkę
  // „Notatki" poprzedniego kandydata z jego niewysłanym tekstem.
  useEffect(() => {
    setOpenSections(new Set([nowSectionForStage(item.stage)]));
    setNoteText("");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tylko zmiana osoby
  }, [item.candidate_id]);

  const fullName = `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;
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

  // `budget_max_at_move` to MIESIĘCZNY budżet w PLN zapisany PRZY RUCHU na
  // „Zweryfikowany", a stawka kandydata bywa godzinowa albo dzienna. Surowe
  // porównanie liczb mówiło „w budżecie" przy 150 zł/h wobec 20 000 zł/mc
  // (150 < 20 000), choć to 25 200 zł/mc. Normalizujemy polityką
  // `rate_normalization.py` (168h-21d-v1; od 17.09.2026 porównanie jest
  // wyłącznie informacyjne — bramka zdjęta); nieznana jednostka
  // albo waluta ≠ PLN to „nie do porównania", nigdy „w budżecie".
  const budgetCheck = useMemo(() => {
    const raw = item.expected_rate_value;
    if (raw == null || raw === "" || item.budget_max_at_move == null) {
      return { verdict: "none" as const, monthly: null };
    }
    const numeric = Number.parseFloat(String(raw).replace(",", "."));
    const monthly = Number.isFinite(numeric)
      ? normalizeRateToMonthly(numeric, item.expected_rate_unit, item.expected_rate_currency)
      : null;
    if (monthly == null) return { verdict: "incomparable" as const, monthly: null };
    return {
      verdict: monthly > item.budget_max_at_move ? ("over" as const) : ("within" as const),
      monthly,
    };
  }, [
    item.expected_rate_value,
    item.expected_rate_unit,
    item.expected_rate_currency,
    item.budget_max_at_move,
  ]);

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
    enabled: isOpen("screening"),
    staleTime: 30_000,
  });
  const screeningAnswers = screeningQuery.data?.screening_answers ?? null;

  // ── CV — status oryginalnego/brandowanego (tylko na zakładce CV) ───────
  const cvOriginalQuery = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", item.id],
    queryFn: () => candidateStageCvApi.original.get(item.id).then((r) => r.data),
    enabled: isOpen("cv"),
  });
  const cvBrandedQuery = useQuery<CVBrandedState>({
    queryKey: ["cv-branded", item.id],
    queryFn: () => candidateStageCvApi.branded.get(item.id).then((r) => r.data),
    enabled: isOpen("cv") || openBranded || openShare,
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
    enabled: isOpen("notes"),
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
    <div className="flex h-full flex-col rounded-xl border border-border bg-card">
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
          {candidate?.status === "blacklisted" && (
            <Badge
              variant={candidate.status === "blacklisted" ? "danger" : "neutral"}
              size="sm"
            >
              {CANDIDATE_STATUS_LABEL[candidate.status] ?? candidate.status}
            </Badge>
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

        {/* Główna akcja zaraz pod nazwiskiem (makieta „Panel osoby"). Ta sama
            ścieżka co drag&drop (`requestMove`) — okna stawki, potwierdzeń
            i powodu odrzucenia działają bez zmian. */}
        {!readOnly && (
          <div className="space-y-1.5">
            {primaryTarget ? (
              <Button
                size="sm"
                onClick={() => onMoveTo(primaryTarget)}
                className="w-full justify-center"
              >
                <ChevronRight className="h-3.5 w-3.5" />
                Przenieś na etap: {primaryTarget.name ?? primaryTarget.stage}
              </Button>
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
            ) : null}
            <div className="flex items-center gap-1.5">
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
                    className="max-h-[60vh] w-72 overflow-y-auto"
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
                  onClick={onReject}
                  disabled={Boolean(rejectBlockedReason)}
                  title={rejectBlockedReason ?? undefined}
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                >
                  <Ban className="h-3.5 w-3.5" /> Odrzuć z powodem
                </Button>
              )}
              <PersonMoreMenu
                onOpenCv={() => setOpenOriginal(true)}
                onSendEmail={() => setOpenEmail(true)}
                profileHref={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
              />
            </div>
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
                {badge.label}
              </button>
            ))}
          </div>
        )}
        {readOnly && (
          <PersonMoreMenu
            onOpenCv={() => setOpenOriginal(true)}
            onSendEmail={() => setOpenEmail(true)}
            profileHref={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
          />
        )}
      </div>

      {/* ── Treść zakładki (przewijana) ──────────────────────────────── */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        <DockSection
          id="process"
          label={DOCK_SECTION_LABEL.process}
          summary={`${currentStageLabel}${item.days_in_stage != null ? ` · ${daysLabel(item.days_in_stage)}` : ""}${nextAction && nextAction.kind !== "none" ? ` · ${nextAction.label}` : ""}`}
          isNow={nowSection === "process"}
          open={isOpen("process")}
          onToggle={() => toggleSection("process")}
        >
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

            {/* Warunki wobec oferty — wyłącznie z danych, które dok już ma
                (karta kanbanu + profil kandydata). Brak danych to „—", nie
                znikający wiersz: pusty rząd czyta się jak „bez zastrzeżeń". */}
            <div className="space-y-1">
              <div className="text-xs font-semibold text-foreground">
                Warunki wobec rekrutacji
              </div>
              <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
                <ConditionRow label="Stawka">
                  {item.expected_rate_value != null ? (
                    <>
                      <span
                        className={cn(
                          "font-medium tabular-nums",
                          budgetCheck.verdict === "over"
                            ? "text-warning"
                            : budgetCheck.verdict === "within"
                              ? "text-success"
                              : "text-foreground"
                        )}
                        title={
                          budgetCheck.monthly != null
                            ? `≈ ${budgetCheck.monthly.toLocaleString("pl-PL")} PLN/mc (21 dni × 8 h)`
                            : undefined
                        }
                      >
                        {item.expected_rate_value} {item.expected_rate_currency ?? "PLN"}
                        {item.expected_rate_unit ? `/${item.expected_rate_unit}` : ""}
                      </span>
                      {item.budget_max_at_move != null && (
                        <span className="ml-1 text-muted-foreground">
                          {budgetCheck.verdict === "over"
                            ? "ponad budżet"
                            : budgetCheck.verdict === "within"
                              ? `w budżecie do ${item.budget_max_at_move.toLocaleString("pl-PL")} PLN/mc`
                              : "nie do porównania z budżetem (jednostka lub waluta)"}
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
          summary={screeningAnswers ? (screeningAnswers.overall_fit === "fit" ? "Pasuje" : screeningAnswers.overall_fit === "miss" ? "Nie pasuje" : "Niepewne") : "Arkusz Championa"}
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
        </DockSection>

        <DockSection
          id="cv"
          label={DOCK_SECTION_LABEL.cv}
          summary={brandedStatus === "finalized" ? "CV firmowe gotowe" : brandedStatus === "draft" ? "CV firmowe w szkicu" : "Oryginał i CV firmowe"}
          isNow={nowSection === "cv"}
          open={isOpen("cv")}
          onToggle={() => toggleSection("cv")}
        >
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
                  {CV_CLIENT_LINKS_UI_ENABLED && (
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
                  )}
                </>
              )}
            </div>
            {onOpenWorkbench ? (
              <WorkbenchLink onClick={() => onOpenWorkbench("cv")}>
                Wysyłka CV do klienta (stawka, wersje)
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
          summary={notesQuery.data?.items ? `${notesQuery.data.items.length} w tej rekrutacji` : "Notatki w tej rekrutacji"}
          isNow={nowSection === "notes"}
          open={isOpen("notes")}
          onToggle={() => toggleSection("notes")}
        >
          <div className="space-y-3">
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
        </DockSection>
      </div>

      {/* Notatka zawsze pod ręką — bez przechodzenia do sekcji „Notatki".
          Prawy margines zostawia róg maskotce Jarvisa (fixed, 64 px + 20 px
          odstępu) — bez niego zasłaniała przycisk wysyłania notatki. */}
      {!readOnly && (
        <div className="flex items-end gap-1.5 border-t border-border bg-muted/10 p-3 pr-[5.75rem]">
          <textarea
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submitNote();
              }
            }}
            aria-label="Dodaj notatkę"
            placeholder="Dodaj notatkę… (Enter wysyła)"
            rows={1}
            className="min-h-8 flex-1 resize-none rounded-md border border-border bg-card px-3 py-1.5 text-xs focus:outline-hidden focus:ring-2 focus:ring-primary"
          />
          <Button
            size="sm"
            onClick={submitNote}
            disabled={!noteText.trim() || addNoteMutation.isPending}
            loading={addNoteMutation.isPending}
            aria-label="Dodaj notatkę — wyślij"
          >
            <Send className="h-3.5 w-3.5" />
          </Button>
        </div>
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
          onOpenChange={setOpenBranded}
          onRegenerate={() => window.location.assign(`/cv-generator?candidate_id=${item.candidate_id}&job_id=${jobId}`)}
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
