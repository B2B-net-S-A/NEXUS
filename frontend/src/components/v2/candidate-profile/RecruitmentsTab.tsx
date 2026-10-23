"use client";

/**
 * Zakładka „Rekrutacje” (13.10.2026, E3 + D5):
 *
 * 1. „W toku · N” — zwarta tabela: rekrutacja z klientem, etap, kto ma ruch,
 *    dni bez ruchu, stawki; na górze proces najdłużej bez ruchu. Klik w nazwę
 *    rekrutacji otwiera jej Tablicę z panelem tej osoby (17.10.2026 — wcześniej
 *    nazwa tylko rozwijała wiersz i rekruterzy szukali rekrutacji po numerze
 *    w wyszukiwarce). Strzałka i reszta wiersza rozwijają kartę procesu
 *    (stawki, CV dla klienta, ścieżka etapów), zwiniętą „Ocenę dopasowania”
 *    tej rekrutacji i feedback po jej rozmowach. „⋯” wiersza: Tablica
 *    i „Usuń z rekrutacji”; akcje CV zostają w karcie, więc zwinięty wiersz nie
 *    pyta serwera o CV.
 * 2. „Zakończone · N” — otwarte, 5 ostatnich + „Pokaż wszystkie”; nazwa
 *    prowadzi na Tablicę, strzałka i wiersz rozwijają ścieżkę etapów,
 *    CV oryginalne, ocenę dopasowania i feedback.
 * 3. Feedback po rozmowach bez rekrutacji (albo z rekrutacji spoza listy).
 * 4. „Pasujące rekrutacje” — zwinięte; rekomendacje pobierają się dopiero
 *    po „Pokaż”, a nie przy każdym wejściu w zakładkę.
 *
 * Osobnej sekcji „Dopasowanie do rekrutacji” już nie ma (D5) — ocena siedzi
 * w wierszu. Stary adres `?recruitments=matching` rozwija wiersz rekrutacji,
 * z której otwarto profil (albo pierwszy w toku), z otwartą oceną.
 *
 * Pule, historia stawek, konflikty i weta przeszły do karty osoby („⋯” i fakt
 * „Stawka od”) — tu zostało to, co dotyczy procesów.
 */

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  ChevronDown,
  ChevronUp,
  Kanban,
  MoreHorizontal,
  RefreshCcw,
  Sparkles,
  Trash2,
} from "lucide-react";

import {
  candidatesApi,
  candidateStageCvApi,
  type CVOriginalSnapshot,
  type RateUnit,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { canViewClientRate, canWriteClientRate } from "@/lib/client-rate-access";
import { useClientRateHistory } from "@/lib/api/clientRateHistory";
import { ClientRateChangeDialog } from "@/components/v2/rate-change/ClientRateChangeDialog";
import { daysSince, nextActionOwnerLabel } from "@/lib/candidate-overview";
import { hasRole, useAuthStore } from "@/store/auth";
import { CV_CLIENT_LINKS_UI_ENABLED } from "@/lib/cv-generator";
import { stageCvBadge, stageCvStatus } from "@/lib/cv-to-client";
import { normalizeCvAlign } from "@/lib/cv-editor-align";
import { fetchStageCvFile, fetchStageCvPdf } from "@/lib/stage-cv-file";
import { useStageBrandedCv } from "@/hooks/useStageBrandedCv";
import { CvGeneratorDialog } from "@/components/v2/cv-generator/CvGeneratorDialog";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { CVShareLinkModal } from "@/components/v2/modals/CVShareLinkModal";
import { CandidateInterviewFeedbackPanel } from "@/components/feedback/CandidateInterviewFeedbackPanel";
import { RateChangeLatest } from "@/components/v2/rate-change/RateChangeLatest";
import {
  clientRateNoteCaption,
  expectedRateHintCaption,
  type ClientRateNote,
  type ExpectedRateHint,
} from "@/lib/api/recruitmentRateHints";
import { SuggestedJobsWidget } from "@/components/SuggestedJobsWidget";
import { candidatePipelinesQueryKey } from "@/components/CandidatePipelinesWidget";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { candidateStageLabel } from "@/components/v2/pages/candidate-timeline-labels";
import {
  entrySourceLabel,
  furthestBoardColumnLabel,
  recruitmentOutcome,
  recruitmentStageLabel,
  recruitmentStagePath,
  reachedClient,
} from "@/lib/recruitment-stage-label";
import { autoMatchBadgeLabel, autoMatchBadgeTitle } from "@/lib/candidate-notes-view";
import {
  focusCandidateRecruitmentCard,
  resolveVisibleRecruitmentFocus,
  type CandidateRecruitmentView,
} from "@/components/v2/pages/candidate-profile-navigation";
import { cn, formatDate } from "@/lib/utils";
import { JobNameLabel } from "@/components/v2/jobs/JobNameLabel";
import { candidateJobNames, jobNameText } from "@/lib/job-name-text";
import { candidateBoardHref, splitRecruitments } from "./profile-helpers";
import { SectionError, SectionLoading, formatRate } from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- odpowiedź /history jest luźno typowana */

// Modal edycji brandowanego CV ciągnie TipTap — renderuje się wyłącznie po
// kliknięciu w konkretnej rekrutacji, więc nie może siedzieć w chunku trasy.
const CVBrandedEditModal = dynamic(
  () =>
    import("@/components/v2/modals/CVBrandedEditModal").then(
      (m) => m.CVBrandedEditModal,
    ),
  { ssr: false },
);
// Podgląd pliku CV (pdf.js) — też dopiero po kliknięciu.
const CvFilePreviewDialog = dynamic(
  () => import("@/components/v2/cv/CvFilePreviewDialog").then((m) => m.CvFilePreviewDialog),
  { ssr: false },
);

export interface RecruitmentsTabProps {
  candidateId: number;
  candidateName: string;
  history: any[];
  isPending: boolean;
  error: unknown;
  refetch: () => void;
  refreshing: boolean;
  focusedJobId: number | null;
  /** Rekrutacja, z której otwarto profil — jej wiersz jest rozwinięty od wejścia. */
  defaultJobId: number | null;
  view: CandidateRecruitmentView;
  readOnly: boolean;
  /**
   * Flagi stawki do klienta z odpowiedzi `/history` (`can_view_client_rate`,
   * `can_write_client_rate`). Runda 10 (R10-X2-3): serwer liczy je z roli
   * I sekcji — rola z przeglądarki jest tylko zapasem, gdy ich brak.
   */
  clientRateAccess?: ClientRateAccess;
}

export interface ClientRateAccess {
  canView?: boolean | null;
  canWrite?: boolean | null;
}

/** Zakończone: tyle ostatnich widać od razu, reszta za „Pokaż wszystkie”. */
const CLOSED_PREVIEW_COUNT = 5;

const rowJobId = (job: any): number | null => {
  const id = job?.job_id ?? job?.id;
  return typeof id === "number" ? id : null;
};

/** Najdłużej bez ruchu na górze; wiersz bez daty ruchu na końcu. */
function byIdleDays(rows: any[]): any[] {
  const now = new Date();
  return [...rows].sort(
    (a, b) => (daysSince(b.last_seen, now) ?? -1) - (daysSince(a.last_seen, now) ?? -1),
  );
}

function timeOf(iso: unknown): number {
  const at = typeof iso === "string" ? Date.parse(iso) : Number.NaN;
  return Number.isNaN(at) ? 0 : at;
}

/** Ostatnio zakończone na górze (5 pierwszych widać bez „Pokaż wszystkie”). */
function byMostRecent(rows: any[]): any[] {
  return [...rows].sort((a, b) => timeOf(b.last_seen) - timeOf(a.last_seen));
}

export function RecruitmentsTab({
  candidateId,
  candidateName,
  history,
  isPending,
  error,
  refetch,
  refreshing,
  focusedJobId: requestedFocusJobId,
  defaultJobId,
  view,
  readOnly,
  clientRateAccess,
}: RecruitmentsTabProps) {
  const authUser = useAuthStore((state) => state.user);
  const { active, ended } = useMemo(() => splitRecruitments(history), [history]);
  const activeRows = useMemo(() => byIdleDays(active), [active]);
  const endedRows = useMemo(() => byMostRecent(ended), [ended]);
  const focusedJobId = useMemo(
    () => resolveVisibleRecruitmentFocus(requestedFocusJobId, history),
    [history, requestedFocusJobId],
  );
  const entryJobId = useMemo(
    () => resolveVisibleRecruitmentFocus(defaultJobId, history),
    [defaultJobId, history],
  );
  // `?recruitments=matching` (dawna zakładka „Dopasowanie”): rekrutacja,
  // z której otwarto profil, inaczej pierwsza w toku, inaczej ostatnia
  // zakończona — z otwartą oceną dopasowania.
  const matchingJobId =
    view === "matching"
      ? (entryJobId ?? rowJobId(activeRows[0]) ?? rowJobId(endedRows[0]))
      : null;
  const inEnded = (jobId: number | null) =>
    jobId != null && endedRows.some((job) => rowJobId(job) === jobId);
  const focusInEnded = inEnded(focusedJobId);
  const matchingInEnded = inEnded(matchingJobId);

  const [endedOpen, setEndedOpen] = useState(true);
  useEffect(() => {
    if (focusInEnded || matchingInEnded) setEndedOpen(true);
  }, [focusInEnded, matchingInEnded]);

  // Fokus na karcie wskazanej w adresie — raz na (kandydat, rekrutacja).
  const handledFocusRef = useRef<string | null>(null);
  useEffect(() => {
    if (focusedJobId == null || history.length === 0) return;
    if (focusInEnded && !endedOpen) return;
    const key = `${candidateId}:${focusedJobId}`;
    if (handledFocusRef.current === key) return;
    if (!focusCandidateRecruitmentCard(focusedJobId)) return;
    handledFocusRef.current = key;
  }, [candidateId, endedOpen, focusInEnded, focusedJobId, history.length]);

  const [suggestedOpen, setSuggestedOpen] = useState(false);
  // Bez żadnej rekrutacji „Dopasowanie” nie ma czego ocenić — stary link
  // otwiera wtedy pasujące rekrutacje.
  const matchingWithoutRecruitments =
    view === "matching" && !isPending && !error && history.length === 0;
  const handledMatchingRef = useRef<string | null>(null);
  useEffect(() => {
    if (view !== "matching") return;
    const targetId =
      matchingJobId != null
        ? `candidate-recruitment-${matchingJobId}-match`
        : matchingWithoutRecruitments
          ? "candidate-suggested-jobs"
          : null;
    if (targetId == null) return;
    if (matchingJobId == null) setSuggestedOpen(true);
    const key = `${candidateId}:${targetId}`;
    if (handledMatchingRef.current === key) return;
    // Po klatce: zamiana starego adresu na kanoniczny (router.replace) i render
    // wierszy przesuwają układ — przewinięcie od razu trafiało w złe miejsce.
    const timer = window.setTimeout(() => {
      document.getElementById(targetId)?.scrollIntoView?.({ block: "start" });
      handledMatchingRef.current = key;
    }, 120);
    return () => window.clearTimeout(timer);
  }, [candidateId, matchingJobId, matchingWithoutRecruitments, view]);

  const jobTitles = useMemo(
    () =>
      new Map<number, string>(
        history
          .filter((job: any) => typeof job?.job_id === "number")
          .map((job: any) => [job.job_id as number, jobNameText(candidateJobNames(job))]),
      ),
    [history],
  );
  // Feedback rekrutacji z listy siedzi w jej wierszu; na dole zostaje reszta.
  const jobIdsWithRow = useMemo(
    () => new Set(history.map(rowJobId).filter((id): id is number => id != null)),
    [history],
  );

  const showClientRate = clientRateAccess?.canView ?? canViewClientRate(authUser);
  const hasData = history.length > 0;

  return (
    <div className="min-w-0 space-y-5">
      {isPending && !hasData ? (
        <SectionLoading label="Ładowanie rekrutacji…" />
      ) : error && !hasData ? (
        <SectionError title="Nie udało się pobrać rekrutacji" onRetry={refetch} />
      ) : (
        <section aria-labelledby="candidate-recruitments-active" className="space-y-2">
          <h2
            id="candidate-recruitments-active"
            className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
          >
            W toku{active.length > 0 ? ` · ${active.length}` : ""}
          </h2>
          {refreshing ? (
            <p role="status" className="text-xs text-muted-foreground">
              Odświeżam…
            </p>
          ) : null}
          {active.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {hasData
                ? "Brak trwających procesów."
                : "Kandydat nie jest w żadnej rekrutacji."}
            </p>
          ) : (
            <ActiveRecruitmentsTable
              items={activeRows}
              candidateId={candidateId}
              candidateName={candidateName}
              focusedJobId={focusedJobId}
              entryJobId={entryJobId}
              matchingJobId={matchingJobId}
              readOnly={readOnly}
              clientRateAccess={clientRateAccess}
              showClientRate={showClientRate}
              jobTitles={jobTitles}
            />
          )}
        </section>
      )}

      {ended.length > 0 ? (
        <section aria-labelledby="candidate-recruitments-ended" className="space-y-2">
          <button
            type="button"
            id="candidate-recruitments-ended"
            onClick={() => setEndedOpen((open) => !open)}
            aria-expanded={endedOpen}
            className="flex min-h-9 items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-primary"
          >
            {endedOpen ? (
              <ChevronUp aria-hidden="true" className="h-3 w-3" />
            ) : (
              <ChevronDown aria-hidden="true" className="h-3 w-3" />
            )}
            Zakończone · {ended.length}
          </button>
          {endedOpen ? (
            <ClosedRecruitmentsTable
              items={endedRows}
              candidateId={candidateId}
              candidateName={candidateName}
              focusedJobId={focusedJobId}
              entryJobId={entryJobId}
              matchingJobId={matchingJobId}
              readOnly={readOnly}
              jobTitles={jobTitles}
            />
          ) : null}
        </section>
      ) : null}

      {/* Rozmowy bez rekrutacji (i z rekrutacji spoza listy) — póki lista się
          ładuje, blok czeka, żeby nie mignął feedbackiem z wierszy. */}
      {hasData || !isPending ? (
        <CandidateInterviewFeedbackPanel
          candidateId={candidateId}
          jobTitles={jobTitles}
          excludeJobIds={jobIdsWithRow}
          hideWhenEmpty
        />
      ) : null}

      <section
        id="candidate-suggested-jobs"
        aria-labelledby="candidate-suggested-jobs-heading"
        className="scroll-mt-4 space-y-2"
      >
        <div className="flex min-h-11 items-center justify-between gap-2 rounded-lg border border-border px-3">
          <h2
            id="candidate-suggested-jobs-heading"
            className="flex items-center gap-2 text-sm font-semibold text-foreground"
          >
            <Sparkles aria-hidden="true" className="h-4 w-4 text-primary" />
            Pasujące rekrutacje
          </h2>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setSuggestedOpen((open) => !open)}
            aria-expanded={suggestedOpen}
            aria-controls="candidate-suggested-jobs-body"
          >
            {suggestedOpen ? "Ukryj" : "Pokaż"}
          </Button>
        </div>
        {suggestedOpen ? (
          <div id="candidate-suggested-jobs-body">
            {/* Bez `hideWhenEmpty`: po „Pokaż” pusty wynik ma powiedzieć, że
                nic nie pasuje, a nie zostawić pustego miejsca. */}
            <SuggestedJobsWidget
              candidateId={candidateId}
              canAssign={!readOnly}
              stacked
              maxItems={5}
              title="Otwarte rekrutacje dopasowane do profilu"
            />
          </div>
        ) : null}
      </section>
    </div>
  );
}

/**
 * Stan rozwinięcia wierszy jednej tabeli. Wiersz z adresu (`focusJobId`),
 * z „Dopasowania” albo rekrutacja, z której otwarto profil, jest rozwinięty
 * od pierwszego renderu — fokus karty w rodzicu szuka jej elementu zaraz po
 * zamontowaniu tabeli.
 */
function useRecruitmentRows(
  items: any[],
  {
    focusedJobId,
    matchingJobId,
    entryJobId,
    expandSingle,
  }: {
    focusedJobId: number | null;
    matchingJobId: number | null;
    entryJobId: number | null;
    /** Jedyny wiersz tabeli rozwinięty od razu (jeden proces w toku). */
    expandSingle: boolean;
  },
) {
  const here = (jobId: number | null) =>
    jobId != null && items.some((job) => rowJobId(job) === jobId) ? jobId : null;
  const focusedHere = here(focusedJobId);
  const matchingHere = here(matchingJobId);

  const [openJobId, setOpenJobId] = useState<number | null>(
    () =>
      focusedHere ??
      matchingHere ??
      here(entryJobId) ??
      (expandSingle && items.length === 1 ? rowJobId(items[0]) : null),
  );
  const [matchOpen, setMatchOpen] = useState<ReadonlySet<number>>(
    () => new Set(matchingHere != null ? [matchingHere] : []),
  );

  useEffect(() => {
    if (focusedHere != null) setOpenJobId(focusedHere);
  }, [focusedHere]);
  useEffect(() => {
    if (matchingHere == null) return;
    setOpenJobId(matchingHere);
    setMatchOpen((previous) =>
      previous.has(matchingHere) ? previous : new Set(previous).add(matchingHere),
    );
  }, [matchingHere]);

  return {
    openJobId,
    toggleRow: (jobId: number) =>
      setOpenJobId((current) => (current === jobId ? null : jobId)),
    isMatchOpen: (jobId: number) => matchOpen.has(jobId),
    toggleMatch: (jobId: number) =>
      setMatchOpen((previous) => {
        const next = new Set(previous);
        if (next.has(jobId)) next.delete(jobId);
        else next.add(jobId);
        return next;
      }),
  };
}

/**
 * Strzałka rozwijająca wiersz. Nazwa rekrutacji obok jest linkiem do Tablicy,
 * więc przycisk ma własną nazwę; ujemny margines powiększa pole kliknięcia
 * bez przesuwania układu.
 */
function RowToggle({
  open,
  onToggle,
  controls,
  title,
}: {
  open: boolean;
  onToggle: () => void;
  controls: string;
  title: string;
}) {
  const Icon = open ? ChevronUp : ChevronDown;
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={controls}
      aria-label={`Szczegóły: ${title}`}
      className="-m-1 shrink-0 rounded p-1 text-muted-foreground hover:text-primary"
    >
      <Icon aria-hidden="true" className="mt-0.5 h-3.5 w-3.5" />
    </button>
  );
}

/** Klik w wiersz rozwija go — poza przyciskami, linkami i oknami z portalu. */
function isNestedControlClick(event: MouseEvent<HTMLElement>): boolean {
  const target = event.target;
  if (!(target instanceof Element) || !event.currentTarget.contains(target)) return true;
  return target.closest("a, button, input, select, textarea, [role='menuitem']") !== null;
}

function compactRate(rate: { value: number; unit?: string | null; currency?: string | null }): string {
  const unit = rate.unit === "hourly" ? "/h" : rate.unit === "daily" ? "/d" : "/mies.";
  const currency = !rate.currency || rate.currency === "PLN" ? "zł" : rate.currency;
  return `${rate.value.toLocaleString("pl-PL")} ${currency}${unit}`;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * „W toku” jako zwarta tabela (E3, 13.10.2026): 9 kart z formularzem stawek
 * i przyciskami CV zajmowało kilka ekranów. Wiersz mówi, gdzie jest proces
 * i kto ma ruch; reszta pracy w rozwinięciu (istniejąca karta procesu).
 */
function ActiveRecruitmentsTable({
  items,
  candidateId,
  candidateName,
  focusedJobId,
  entryJobId,
  matchingJobId,
  readOnly,
  clientRateAccess,
  showClientRate,
  jobTitles,
}: {
  items: any[];
  candidateId: number;
  candidateName: string;
  focusedJobId: number | null;
  entryJobId: number | null;
  matchingJobId: number | null;
  readOnly: boolean;
  clientRateAccess?: ClientRateAccess;
  showClientRate: boolean;
  jobTitles: ReadonlyMap<number, string>;
}) {
  const rows = useRecruitmentRows(items, {
    focusedJobId,
    matchingJobId,
    entryJobId,
    expandSingle: true,
  });
  const columns = showClientRate ? 7 : 6;

  return (
    <div className="relative overflow-x-auto rounded-lg border border-border">
      <table
        className={cn("w-full text-sm", showClientRate ? "min-w-[40rem]" : "min-w-[34rem]")}
        aria-label="Rekrutacje w toku"
      >
        <thead className="bg-muted text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="sticky left-0 z-10 bg-muted px-3 py-2 font-medium">
              Rekrutacja
            </th>
            <th scope="col" className="px-3 py-2 font-medium">Etap</th>
            <th scope="col" className="px-3 py-2 font-medium" title="Kto ma następny krok">
              Ruch
            </th>
            <th
              scope="col"
              aria-sort="descending"
              title="Dni od ostatniego ruchu na Tablicy"
              className="px-3 py-2 text-right font-medium"
            >
              Dni
            </th>
            <th scope="col" className="px-3 py-2 font-medium">Stawka</th>
            {showClientRate ? (
              <th scope="col" className="px-3 py-2 font-medium">Do klienta</th>
            ) : null}
            <th scope="col" className="w-10 px-1 py-2">
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((job: any, i: number) => {
            const jobId = rowJobId(job) as number;
            return (
              <ActiveRecruitmentRow
                key={jobId ?? i}
                job={job}
                jobId={jobId}
                open={rows.openJobId === jobId}
                onToggle={() => rows.toggleRow(jobId)}
                matchOpen={rows.isMatchOpen(jobId)}
                onToggleMatch={() => rows.toggleMatch(jobId)}
                columns={columns}
                candidateId={candidateId}
                candidateName={candidateName}
                focusedJobId={focusedJobId}
                readOnly={readOnly}
                clientRateAccess={clientRateAccess}
                showClientRate={showClientRate}
                jobTitles={jobTitles}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ActiveRecruitmentRow({
  job,
  jobId,
  open,
  onToggle,
  matchOpen,
  onToggleMatch,
  columns,
  candidateId,
  candidateName,
  focusedJobId,
  readOnly,
  clientRateAccess,
  showClientRate,
  jobTitles,
}: {
  job: any;
  jobId: number;
  open: boolean;
  onToggle: () => void;
  matchOpen: boolean;
  onToggleMatch: () => void;
  columns: number;
  candidateId: number;
  candidateName: string;
  focusedJobId: number | null;
  readOnly: boolean;
  clientRateAccess?: ClientRateAccess;
  showClientRate: boolean;
  jobTitles: ReadonlyMap<number, string>;
}) {
  const [confirmRemove, setConfirmRemove] = useState(false);
  // Nazwa jak w nagłówku rekrutacji (16.10.2026); `job_title` (od klienta)
  // zostaje dla okien, które mówią do klienta (CV).
  const names = candidateJobNames({ ...job, job_id: jobId });
  const title = jobNameText(names);
  const detailsId = `candidate-active-recruitment-${jobId}-details`;
  const days = daysSince(job.last_seen);
  const owner = nextActionOwnerLabel(job.next_action_owner);
  const expectedHint: ExpectedRateHint | null = job.expected_rate_hint ?? null;

  return (
    <>
      <tr
        className="group cursor-pointer border-t border-border hover:bg-accent"
        onClick={(event) => {
          if (isNestedControlClick(event)) return;
          onToggle();
        }}
      >
        <td className="sticky left-0 z-10 bg-card px-3 py-1.5 group-hover:bg-accent">
          {/* Nazwa prowadzi na Tablicę z otwartą osobą (17.10.2026); strzałka
              i reszta wiersza rozwijają szczegóły. */}
          <div className="flex min-h-9 items-start gap-1.5">
            <RowToggle open={open} onToggle={onToggle} controls={detailsId} title={title} />
            <span className="min-w-0">
              <JobNameLabel
                job={names}
                href={candidateBoardHref(jobId, candidateId)}
                titleId={`candidate-recruitment-${jobId}-title`}
                wrap
                titleClassName="font-medium text-foreground hover:text-primary"
              />
              {job.client_name ? (
                <span className="block text-xs text-muted-foreground">{job.client_name}</span>
              ) : null}
            </span>
          </div>
        </td>
        <td className="px-3 py-1.5">
          <Badge size="sm" variant="neutral">
            {recruitmentStageLabel(job.latest_stage, job.latest_stage_name, candidateStageLabel)}
          </Badge>
        </td>
        <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground">
          {owner ? capitalize(owner) : "—"}
        </td>
        <td
          className="px-3 py-1.5 text-right tabular-nums text-muted-foreground"
          title={job.last_seen ? `Ostatni ruch ${formatDate(job.last_seen)}` : undefined}
        >
          {days ?? "—"}
        </td>
        <td className="whitespace-nowrap px-3 py-1.5 tabular-nums">
          {job.expected_rate ? (
            compactRate(job.expected_rate)
          ) : expectedHint ? (
            <span
              className="text-muted-foreground"
              title={`Z notatek, jeszcze nie wpisana: ${expectedRateHintCaption(expectedHint)}`}
            >
              ~{compactRate({ value: Number(expectedHint.amount_hourly), unit: "hourly" })}
            </span>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </td>
        {showClientRate ? (
          <td className="whitespace-nowrap px-3 py-1.5 tabular-nums">
            {job.client_rate ? (
              compactRate(job.client_rate)
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </td>
        ) : null}
        <td className="px-1 py-1 text-right">
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button
                size="sm"
                variant="ghost"
                className="min-h-9 min-w-9"
                aria-label={`Akcje rekrutacji: ${title}`}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem asChild className="min-h-11">
                <Link href={candidateBoardHref(jobId, candidateId)}>
                  <Kanban className="h-4 w-4" />
                  Tablica
                </Link>
              </DropdownMenuItem>
              {!readOnly ? (
                // Rzadka i nieodwracalna akcja w „⋯” — czerwony przycisk przy
                // każdym procesie zachęcał do pomyłki (przegląd 04.10.2026).
                <DropdownMenuItem
                  className="min-h-11 text-destructive focus:text-destructive"
                  title="Usuń kandydata z tej rekrutacji"
                  onSelect={() => setTimeout(() => setConfirmRemove(true), 0)}
                >
                  <Trash2 className="h-4 w-4" />
                  Usuń z rekrutacji
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
          {!readOnly ? (
            <RemoveFromRecruitmentDialog
              open={confirmRemove}
              onOpenChange={setConfirmRemove}
              candidateId={candidateId}
              jobId={jobId}
              jobTitle={job.job_title ?? null}
            />
          ) : null}
        </td>
      </tr>
      {open ? (
        <tr id={detailsId} className="border-t border-border bg-muted/20">
          <td colSpan={columns} className="p-3">
            <div className="space-y-3">
              <RecruitmentCard
                job={job}
                candidateId={candidateId}
                candidateName={candidateName}
                focusedJobId={focusedJobId}
                readOnly={readOnly}
                clientRateAccess={clientRateAccess}
                showTitle={false}
              />
              <RecruitmentMatchScore
                candidateId={candidateId}
                jobId={jobId}
                jobTitle={job.job_title ?? null}
                open={matchOpen}
                onToggle={onToggleMatch}
                readOnly={readOnly}
              />
              <CandidateInterviewFeedbackPanel
                candidateId={candidateId}
                jobTitles={jobTitles}
                jobId={jobId}
                hideWhenEmpty
              />
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

/**
 * Ocena dopasowania jednej rekrutacji (D5, 13.10.2026) — zwinięta, bo liczy
 * wynik i prosi AI o uzasadnienie; montuje się dopiero po „Pokaż”.
 */
function RecruitmentMatchScore({
  candidateId,
  jobId,
  jobTitle,
  open,
  onToggle,
  readOnly,
}: {
  candidateId: number;
  jobId: number;
  jobTitle: string | null;
  open: boolean;
  onToggle: () => void;
  readOnly: boolean;
}) {
  const regionId = `candidate-recruitment-${jobId}-match`;
  const bodyId = `${regionId}-body`;
  return (
    <section id={regionId} className="scroll-mt-4 rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex min-h-11 w-full items-center justify-between gap-2 px-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Sparkles aria-hidden="true" className="h-4 w-4 text-primary" />
          Ocena dopasowania
        </span>
        <span className="flex items-center gap-1 text-xs font-medium text-primary">
          {open ? "Ukryj" : "Pokaż"}
          {open ? (
            <ChevronUp aria-hidden="true" className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown aria-hidden="true" className="h-3.5 w-3.5" />
          )}
        </span>
      </button>
      {open ? (
        <div id={bodyId} className="border-t border-border p-3">
          <DopasowanieTab
            candidateId={candidateId}
            recruitments={[{ job_id: jobId, job_title: jobTitle }]}
            jobId={jobId}
            readOnly={readOnly}
          />
        </div>
      ) : null}
    </section>
  );
}

/** Potwierdzenie „Usuń z rekrutacji” — wspólne dla wiersza w toku i karty zakończonej. */
function RemoveFromRecruitmentDialog({
  open,
  onOpenChange,
  candidateId,
  jobId,
  jobTitle,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  jobId: number;
  jobTitle: string | null;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const removeMut = useMutation({
    mutationFn: () => candidatesApi.removeFromRecruitment(candidateId, jobId),
    onSuccess: () => {
      showSuccess(
        jobTitle
          ? `Kandydat usunięty z rekrutacji „${jobTitle}”`
          : "Kandydat usunięty z rekrutacji",
      );
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.historyRoot(candidateId),
      });
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.recommendationsRoot(candidateId),
      });
      queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      queryClient.invalidateQueries({
        queryKey: candidatePipelinesQueryKey(candidateId),
      });
      onOpenChange(false);
    },
    onError: (e) =>
      showError(apiErrorMessage(e, "Błąd podczas usuwania z rekrutacji")),
  });

  return (
    <ConfirmV2
      open={open}
      onOpenChange={onOpenChange}
      variant="destructive"
      title="Usunąć kandydata z tej rekrutacji?"
      description={`Kandydat zostanie zdjęty z pipeline'u rekrutacji „${jobTitle ?? `#${jobId}`}”. Usunięta zostanie cała historia jego etapów na tej rekrutacji wraz ze snapshotami CV (oryginalne i firmowe) oraz linkami do udostępnień. Tego nie można cofnąć — kandydata można jednak dodać ponownie. Profil i umowy pozostają bez zmian. To nie to samo co odrzucenie — jeśli kandydat brał udział w procesie, użyj „Odrzuć” na tablicy, żeby zachować historię.`}
      confirmLabel="Usuń z rekrutacji"
      loading={removeMut.isPending}
      onConfirm={() => removeMut.mutate()}
    />
  );
}

/**
 * „Zakończone” jako tabela tylko do odczytu (decyzja 04.10.2026): 24 karty
 * z „Generuj CV”, stawkami do uzupełnienia i czerwonym „Usuń z rekrutacji”
 * zamieniały historię w formularz. Klik w wiersz rozwija szczegóły (ścieżka
 * etapów, powód odrzucenia, CV oryginalne, ocena dopasowania, feedback);
 * usunięcie z zakończonej rekrutacji zostaje wyłącznie dla admina,
 * w szczegółach. Od 13.10.2026 widać 5 ostatnich, resztę po „Pokaż wszystkie”.
 */
function ClosedRecruitmentsTable({
  items,
  candidateId,
  candidateName,
  focusedJobId,
  entryJobId,
  matchingJobId,
  readOnly,
  jobTitles,
}: {
  items: any[];
  candidateId: number;
  candidateName: string;
  focusedJobId: number | null;
  entryJobId: number | null;
  matchingJobId: number | null;
  readOnly: boolean;
  jobTitles: ReadonlyMap<number, string>;
}) {
  const rows = useRecruitmentRows(items, {
    focusedJobId,
    matchingJobId,
    entryJobId,
    expandSingle: false,
  });
  // Wiersz wskazany adresem poza piątką ostatnich — od razu cała lista,
  // inaczej fokus i przewinięcie nie miałyby czego znaleźć.
  const targetIndex = Math.max(
    ...[focusedJobId, matchingJobId, entryJobId].map((jobId) =>
      jobId == null ? -1 : items.findIndex((job) => rowJobId(job) === jobId),
    ),
  );
  const [showAll, setShowAll] = useState(() => targetIndex >= CLOSED_PREVIEW_COUNT);
  useEffect(() => {
    if (targetIndex >= CLOSED_PREVIEW_COUNT) setShowAll(true);
  }, [targetIndex]);
  const shown = showAll ? items : items.slice(0, CLOSED_PREVIEW_COUNT);

  return (
    <div className="space-y-1">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[34rem] text-sm" aria-label="Zakończone rekrutacje">
          <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Rekrutacja</th>
              <th scope="col" className="px-3 py-2 font-medium">Klient</th>
              <th scope="col" className="px-3 py-2 font-medium">Doszedł do</th>
              <th scope="col" className="px-3 py-2 font-medium">Wynik</th>
              <th scope="col" className="px-3 py-2 font-medium">Kiedy</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((job: any, i: number) => {
              const jobId = rowJobId(job) as number;
              return (
                <ClosedRecruitmentRow
                  key={jobId ?? i}
                  job={job}
                  jobId={jobId}
                  open={rows.openJobId === jobId}
                  outcome={recruitmentOutcome(job)}
                  onToggle={() => rows.toggleRow(jobId)}
                  matchOpen={rows.isMatchOpen(jobId)}
                  onToggleMatch={() => rows.toggleMatch(jobId)}
                  candidateId={candidateId}
                  candidateName={candidateName}
                  focusedJobId={focusedJobId}
                  readOnly={readOnly}
                  jobTitles={jobTitles}
                />
              );
            })}
          </tbody>
        </table>
      </div>
      {!showAll && items.length > CLOSED_PREVIEW_COUNT ? (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="inline-flex min-h-9 items-center px-1 text-xs font-medium text-primary hover:underline"
        >
          Pokaż wszystkie ({items.length})
        </button>
      ) : null}
    </div>
  );
}

const OUTCOME_VARIANT: Record<string, "success" | "danger" | "warning" | "neutral"> = {
  success: "success",
  danger: "danger",
  warning: "warning",
  neutral: "neutral",
};

function ClosedRecruitmentRow({
  job,
  jobId,
  open,
  outcome,
  onToggle,
  matchOpen,
  onToggleMatch,
  candidateId,
  candidateName,
  focusedJobId,
  readOnly,
  jobTitles,
}: {
  job: any;
  jobId: number;
  open: boolean;
  outcome: ReturnType<typeof recruitmentOutcome>;
  onToggle: () => void;
  matchOpen: boolean;
  onToggleMatch: () => void;
  candidateId: number;
  candidateName: string;
  focusedJobId: number | null;
  readOnly: boolean;
  jobTitles: ReadonlyMap<number, string>;
}) {
  const detailsId = `candidate-closed-recruitment-${jobId}-details`;
  const names = candidateJobNames({ ...job, job_id: jobId });
  return (
    <>
      <tr
        className="cursor-pointer border-t border-border hover:bg-muted/30"
        onClick={(event) => {
          if (isNestedControlClick(event)) return;
          onToggle();
        }}
      >
        <td className="px-3 py-2">
          <div className="flex min-h-9 items-center gap-1.5">
            <RowToggle
              open={open}
              onToggle={onToggle}
              controls={detailsId}
              title={jobNameText(names)}
            />
            <JobNameLabel
              job={names}
              href={candidateBoardHref(jobId, candidateId)}
              wrap
              titleClassName="font-medium text-foreground hover:text-primary"
            />
          </div>
        </td>
        <td className="px-3 py-2 text-muted-foreground">{job.client_name ?? "—"}</td>
        <td className="px-3 py-2 text-muted-foreground">
          {furthestBoardColumnLabel(job.stages) ?? "—"}
        </td>
        <td className="px-3 py-2">
          <Badge size="sm" variant={OUTCOME_VARIANT[outcome.tone]}>
            {outcome.label}
          </Badge>
        </td>
        <td className="whitespace-nowrap px-3 py-2 tabular-nums text-muted-foreground">
          {job.last_seen ? formatDate(job.last_seen) : "—"}
        </td>
      </tr>
      {open ? (
        <tr id={detailsId} className="border-t border-border bg-muted/20">
          <td colSpan={5} className="p-3">
            <div className="space-y-3">
              <RecruitmentCard
                job={job}
                candidateId={candidateId}
                candidateName={candidateName}
                focusedJobId={focusedJobId}
                readOnly={readOnly}
                ended
              />
              <RecruitmentMatchScore
                candidateId={candidateId}
                jobId={jobId}
                jobTitle={job.job_title ?? null}
                open={matchOpen}
                onToggle={onToggleMatch}
                readOnly={readOnly}
              />
              <CandidateInterviewFeedbackPanel
                candidateId={candidateId}
                jobTitles={jobTitles}
                jobId={jobId}
                hideWhenEmpty
              />
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

type RecruitmentRate = {
  value: number;
  unit: string | null;
  currency: string | null;
} | null;

type RatePayload = {
  rate_value: number | null;
  rate_unit?: RateUnit;
  rate_currency?: string;
};

// Edytowalna komórka stawki (wartość + jednostka). Współdzielona przez
// „Stawkę kandydata” (expected_rate) i „Stawkę do klienta” (client_rate).
function EditableRateCell({
  candidateId,
  label,
  rate,
  suggested = null,
  footnote = null,
  mutationFn,
  successMessage,
  testIdPrefix,
  readOnly = false,
  onEdit,
}: {
  candidateId: number;
  label: string;
  rate: RecruitmentRate;
  /** „Edytuj” istniejącej kwoty otwiera okno zamiast pola (stawka do klienta, 20.10.2026). */
  onEdit?: () => void;
  /**
   * Kwota z notatek, gdy etap jej nie ma (12.10.2026): stoi w miejscu „—”,
   * a „Uzupełnij” otwiera pole już z nią. Stawką staje się po zapisie.
   */
  suggested?: RecruitmentRate;
  /** Skąd jest kwota albo notatka, która ją niesie — mały tekst pod wartością. */
  footnote?: ReactNode;
  mutationFn: (payload: RatePayload) => Promise<unknown>;
  successMessage: string;
  testIdPrefix: string;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [editing, setEditing] = useState(false);
  const shown = rate ?? suggested;
  const [value, setValue] = useState(shown?.value != null ? String(shown.value) : "");
  const [unit, setUnit] = useState<RateUnit>((shown?.unit as RateUnit) ?? "monthly");
  // Pole startuje od tego, co widać TERAZ — stawka albo podpowiedź mogły dojść
  // po zamontowaniu wiersza (odświeżenie `/history`).
  const resetDraft = () => {
    setValue(shown?.value != null ? String(shown.value) : "");
    setUnit((shown?.unit as RateUnit) ?? "monthly");
  };

  const mut = useMutation({
    mutationFn: (payload: RatePayload) => {
      if (readOnly) throw new Error("Brak prawa zapisu w Sourcing");
      return mutationFn(payload);
    },
    onSuccess: () => {
      showSuccess(successMessage);
      invalidateCandidateMutation(queryClient, candidateId, "rate");
      setEditing(false);
    },
    onError: (e) => showError(apiErrorMessage(e, "Nie udało się zapisać stawki")),
  });

  const save = () => {
    const trimmed = value.trim();
    const v = trimmed === "" ? null : Number(trimmed.replace(",", "."));
    if (v !== null && (!Number.isFinite(v) || v < 0)) {
      showError("Podaj poprawną kwotę");
      return;
    }
    mut.mutate({ rate_value: v, rate_unit: unit, rate_currency: "PLN" });
  };

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground">{label}</span>
        {!editing && !readOnly ? (
          <button
            type="button"
            onClick={() => {
              if (rate && onEdit) {
                onEdit();
                return;
              }
              resetDraft();
              setEditing(true);
            }}
            className="text-primary hover:underline"
            data-testid={`${testIdPrefix}-edit`}
          >
            {rate ? "Edytuj" : "Uzupełnij"}
          </button>
        ) : null}
      </div>
      {editing && !readOnly ? (
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <input
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="np. 22000"
            className="h-8 w-24 rounded border border-border bg-card px-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-primary"
            autoFocus
            aria-label={label}
            data-testid={`${testIdPrefix}-input`}
          />
          <select
            value={unit}
            onChange={(e) => setUnit(e.target.value as RateUnit)}
            className="h-8 rounded border border-border bg-card px-1 text-xs"
            aria-label={`${label} — jednostka`}
          >
            <option value="monthly">/mies.</option>
            <option value="daily">/d</option>
            <option value="hourly">/h</option>
          </select>
          <Button size="sm" disabled={mut.isPending} onClick={save} data-testid={`${testIdPrefix}-save`}>
            Zapisz
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setEditing(false);
              resetDraft();
            }}
          >
            Anuluj
          </Button>
        </div>
      ) : (
        <div className="font-medium text-foreground">
          {shown ? formatRate(shown.value, shown.currency, shown.unit) : "—"}
        </div>
      )}
      {!rate && footnote ? (
        <div
          className="mt-1 break-words text-[11px] text-muted-foreground"
          data-testid={`${testIdPrefix}-footnote`}
        >
          {footnote}
        </div>
      ) : null}
    </div>
  );
}

// Stawka kandydata i stawka do klienta per rekrutacja; marża liczona
// z wartości z serwera (tylko przy tej samej jednostce).
export function RecruitmentRateRow({
  candidateId,
  jobId,
  clientRate,
  expectedRate,
  expectedRateHint = null,
  clientRateNote = null,
  readOnly = false,
  clientRateAccess,
}: {
  candidateId: number;
  jobId: number;
  clientRate: RecruitmentRate;
  expectedRate: RecruitmentRate;
  /**
   * Para z czasów Traffita nie ma stawek na etapie (12.10.2026): serwer
   * dokłada oczekiwanie kandydata z karty rekomendacji i notatkę Delivery
   * Leada z dnia wysyłki (`services/recruitment_rate_hints.py`).
   */
  expectedRateHint?: ExpectedRateHint | null;
  clientRateNote?: ClientRateNote | null;
  readOnly?: boolean;
  clientRateAccess?: ClientRateAccess;
}) {
  const authUser = useAuthStore((st) => st.user);
  // Decyzja 23.09.2026: stawki do klienta nie widzą rekruter, sourcer i TAC;
  // wpisuje ją wyłącznie DL albo admin (lustro `candidate_access.py`).
  // Runda 10 (R10-X2-3): rozstrzyga serwer (rola + zapis w sekcji); rola
  // z przeglądarki tylko wtedy, gdy odpowiedź nie niesie flag.
  const showClientRate = clientRateAccess?.canView ?? canViewClientRate(authUser);
  // 20.10.2026: zmiana istniejącej stawki do klienta idzie przez okno z powodem;
  // po zamówieniu na tę parę stawkę zmienia się w zamówieniu.
  const [clientRateDialogOpen, setClientRateDialogOpen] = useState(false);
  const clientRateLock =
    useClientRateHistory(candidateId, jobId, showClientRate && clientRate != null).data
      ?.order_lock ?? null;
  const clientRateWritable =
    showClientRate &&
    clientRateLock == null &&
    (clientRateAccess?.canWrite ?? canWriteClientRate(authUser));
  const sameUnit =
    showClientRate &&
    clientRate != null &&
    expectedRate != null &&
    clientRate.unit === expectedRate.unit;
  const margin =
    sameUnit && clientRate != null && expectedRate != null
      ? clientRate.value - expectedRate.value
      : null;

  return (
    <div className="mt-3 border-t border-border pt-3">
      <div className="grid grid-cols-2 gap-3 text-xs">
        <EditableRateCell
          candidateId={candidateId}
          label="Stawka kandydata"
          rate={expectedRate}
          suggested={
            expectedRateHint
              ? {
                  value: Number(expectedRateHint.amount_hourly),
                  unit: "hourly",
                  currency: "PLN",
                }
              : null
          }
          footnote={expectedRateHint ? expectedRateHintCaption(expectedRateHint) : null}
          testIdPrefix="expected-rate"
          successMessage="Zapisano stawkę kandydata"
          readOnly={readOnly}
          mutationFn={(payload) =>
            candidatesApi.setRecruitmentExpectedRate(candidateId, jobId, payload)
          }
        />
        {showClientRate ? (
          <EditableRateCell
            candidateId={candidateId}
            label="Stawka do klienta"
            rate={clientRate}
            footnote={
              clientRateNote ? (
                <>
                  {clientRateNoteCaption(clientRateNote)}: „{clientRateNote.text}”
                </>
              ) : null
            }
            testIdPrefix="client-rate"
            successMessage="Zapisano stawkę do klienta"
            readOnly={readOnly || !clientRateWritable}
            onEdit={() => setClientRateDialogOpen(true)}
            mutationFn={(payload) =>
              candidatesApi.setRecruitmentClientRate(candidateId, jobId, payload)
            }
          />
        ) : null}
      </div>
      {clientRateLock ? (
        <div className="mt-2 text-xs text-muted-foreground" data-testid="client-rate-order-lock">
          Stawkę do klienta zmienia się w zamówieniu „{clientRateLock.title}”.{" "}
          <a href={`/contracts/${clientRateLock.contract_id}`} className="text-primary hover:underline">
            Otwórz kontrakt
          </a>
        </div>
      ) : null}
      {clientRateDialogOpen ? (
        <ClientRateChangeDialog
          open
          onOpenChange={(o) => !o && setClientRateDialogOpen(false)}
          candidateId={candidateId}
          jobId={jobId}
          candidateRate={
            expectedRate
              ? { value: expectedRate.value, unit: (expectedRate.unit ?? "hourly") as RateUnit }
              : null
          }
        />
      ) : null}
      <RateChangeLatest candidateId={candidateId} jobId={jobId} />
      {margin != null ? (
        <div className="mt-2 text-xs text-muted-foreground">
          Marża:{" "}
          <span
            className={
              margin >= 0 ? "font-medium text-success" : "font-medium text-destructive"
            }
          >
            {formatRate(margin, clientRate?.currency, clientRate?.unit)}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function RecruitmentCard({
  job,
  candidateId,
  candidateName,
  focusedJobId,
  readOnly = false,
  clientRateAccess,
  ended = false,
  showTitle = true,
}: {
  job: any;
  candidateId: number;
  candidateName: string;
  focusedJobId: number | null;
  readOnly?: boolean;
  clientRateAccess?: ClientRateAccess;
  /**
   * Szczegóły zakończonego procesu (rozwinięty wiersz tabeli „Zakończone”):
   * tylko odczyt — ścieżka etapów, powód odrzucenia, CV oryginalne. Usunąć
   * z zakończonej rekrutacji może wyłącznie admin.
   */
  ended?: boolean;
  /**
   * Wiersz „W toku” pokazuje już tytuł, klienta i etap — karta w jego
   * rozwinięciu podaje tylko resztę (skąd przyszedł, kiedy dodany). Tablica
   * i „Usuń z rekrutacji” siedzą w „⋯” wiersza.
   */
  showTitle?: boolean;
}) {
  const isAdmin = useAuthStore((state) => hasRole(state.user, "admin"));
  // Proces w toku usuwa się z „⋯” wiersza tabeli; tu zostaje zakończony (admin).
  const canRemove = ended && !readOnly && isAdmin;
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const stageId: number | null = job.latest_stage_id ?? null;
  const jobId: number = job.job_id ?? job.id;
  const isFocused = focusedJobId === jobId;
  const recruitmentTitleId = `candidate-recruitment-${jobId}-title`;
  const [openOriginal, setOpenOriginal] = useState(false);
  const [openClientCv, setOpenClientCv] = useState(false);
  const [openBranded, setOpenBranded] = useState(false);
  const [openGenerator, setOpenGenerator] = useState(false);
  const [openShare, setOpenShare] = useState(false);
  const [confirmRefresh, setConfirmRefresh] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  const { data: original } = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", stageId],
    queryFn: () =>
      candidateStageCvApi.original.get(stageId as number).then((r) => r.data),
    enabled: stageId != null,
  });

  // Stan CV do klienta decyduje, czy karta daje „Generuj CV”, czy „Edytuj CV”.
  // Od generatora CV v3 GET przy braku CV zwraca pusty stan (bez renderowania
  // starego szablonu), więc pytamy od razu, a nie dopiero po kliknięciu.
  // Runda 12: najnowszy wiersz etapu (po ruchu na kolejną kolumnę) nie ma
  // własnego CV — edycja, plakietka i link idą na wiersz pary z CV.
  const {
    query: { data: branded },
    pairStageId,
    cvStageId,
  } = useStageBrandedCv(stageId);

  const refreshMut = useMutation({
    mutationFn: () => {
      if (readOnly) throw new Error("Brak prawa zapisu w Sourcing");
      return candidateStageCvApi.original.refresh(stageId as number);
    },
    onSuccess: () => {
      showSuccess("Snapshot CV oryginalnego zaktualizowany");
      queryClient.invalidateQueries({ queryKey: ["cv-original", stageId] });
      setConfirmRefresh(false);
    },
    onError: (e) =>
      showError(apiErrorMessage(e, "Błąd podczas odświeżania snapshotu")),
  });

  const stagePath = recruitmentStagePath(job.stages, candidateStageLabel);
  const brandedStatus =
    (branded?.status as "none" | "draft" | "finalized" | undefined) ?? "none";
  const stageCv = stageCvStatus(branded);
  const stageCvBadgeInfo = stageCvBadge(branded);
  // Prośba Igora (23.10.2026): DL chce zobaczyć CV, które poszło do klienta,
  // bez otwierania edytora — także w zakończonym procesie. Szkic czyta się
  // tylko z prawem zapisu (serwer: `CandidateWriteAccess`), zatwierdzoną
  // wersję każdy, kto widzi dokumenty kandydata.
  const sentToClient = reachedClient(job.stages);
  const canPreviewClientCv =
    stageCv === "ready" && (!readOnly || brandedStatus === "finalized");
  const clientCvLabel = sentToClient ? "CV wysłane do klienta" : "Podgląd CV do klienta";
  const sourceLabel =
    entrySourceLabel(job.entry_source) && !autoMatchBadgeLabel(job.entry_auto_match)
      ? entrySourceLabel(job.entry_source)
      : null;
  const addedLabel = job.first_seen ? `dodano ${formatDate(job.first_seen)}` : null;
  const sourceAndAdded = [sourceLabel, addedLabel].filter(Boolean).join(" · ");

  return (
    <div
      id={`candidate-recruitment-${jobId}`}
      role="group"
      aria-labelledby={recruitmentTitleId}
      tabIndex={isFocused ? -1 : undefined}
      aria-current={isFocused ? "true" : undefined}
      data-focused-recruitment={isFocused ? "true" : undefined}
      className={cn(
        "rounded-lg border border-border bg-card p-3 transition-colors hover:border-primary/40",
        isFocused && "border-primary ring-2 ring-ring ring-offset-2",
      )}
    >
      <div className="min-w-0">
        {showTitle ? (
          <>
            <JobNameLabel
              job={candidateJobNames({ ...job, job_id: jobId })}
              href={candidateBoardHref(jobId, candidateId)}
              titleId={recruitmentTitleId}
              wrap
              titleClassName="font-medium text-foreground"
            />
            <div className="text-xs text-muted-foreground">
              {job.client_name ? `${job.client_name} · ` : ""}
              {recruitmentStageLabel(
                job.latest_stage,
                job.latest_stage_name,
                candidateStageLabel,
              )}
              {sourceAndAdded ? ` · ${sourceAndAdded}` : ""}
            </div>
          </>
        ) : sourceAndAdded ? (
          <div className="text-xs text-muted-foreground">{capitalize(sourceAndAdded)}</div>
        ) : null}
        {/* 0399: wynik automatu przy procesie zamiast notatki w historii. */}
        {autoMatchBadgeLabel(job.entry_auto_match) ? (
          <div className="mt-1.5">
            <Badge size="sm" variant="soft" title={autoMatchBadgeTitle(job.entry_auto_match)}>
              {autoMatchBadgeLabel(job.entry_auto_match)}
            </Badge>
          </div>
        ) : null}
        {stagePath.length > 1 ? (
          <ol
            aria-label="Ścieżka etapów"
            className="mt-1.5 flex flex-wrap items-center gap-1 text-xs text-muted-foreground"
          >
            {stagePath.map((label, si) => (
              <li key={`${label}-${si}`} className="flex items-center gap-1">
                {si > 0 ? <span aria-hidden="true">→</span> : null}
                <Badge size="sm" variant="soft">
                  {label}
                </Badge>
              </li>
            ))}
          </ol>
        ) : null}
        {/* Powód odrzucenia — tylko gdy rekrutacja ZAKOŃCZYŁA się odrzuceniem. */}
        {job.latest_stage === "rejected" && job.rejection_reason ? (
          <div className="mt-2 flex items-start gap-1.5 rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
            <Ban className="mt-px h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0">
              <span className="font-medium">Powód odrzucenia:</span>{" "}
              {job.rejection_reason}
            </span>
          </div>
        ) : null}
        {/* Tylko stany z treścią — plakietka „brak CV” na każdej karcie byłaby
            szumem; brak CV to przycisk „Generuj CV” niżej. */}
        {stageCvBadgeInfo ? (
          <div className="mt-2">
            <Badge size="sm" variant={stageCvBadgeInfo.tone}>
              {stageCvBadgeInfo.label}
            </Badge>
          </div>
        ) : null}
      </div>

      {!ended ? (
        <RecruitmentRateRow
          candidateId={candidateId}
          jobId={jobId}
          clientRate={job.client_rate ?? null}
          expectedRate={job.expected_rate ?? null}
          expectedRateHint={job.expected_rate_hint ?? null}
          clientRateNote={job.client_rate_note ?? null}
          readOnly={readOnly}
          clientRateAccess={clientRateAccess}
        />
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
        {stageId != null ? (
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setOpenOriginal(true)}
              disabled={!original?.has_snapshot}
              title={
                original && !original.has_snapshot
                  ? "Brak CV w momencie zgłoszenia"
                  : undefined
              }
            >
              Pokaż CV oryginalne
            </Button>
            {canPreviewClientCv ? (
              <Button size="sm" variant="outline" onClick={() => setOpenClientCv(true)}>
                {clientCvLabel}
              </Button>
            ) : null}
            {!readOnly && !ended ? (
              <>
                {stageCv === "ready" ? (
                  <Button size="sm" variant="outline" onClick={() => setOpenBranded(true)}>
                    Edytuj CV
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => setOpenGenerator(true)}>
                    Generuj CV
                  </Button>
                )}
                {CV_CLIENT_LINKS_UI_ENABLED ? (
                  <Button
                    size="sm"
                    disabled={brandedStatus !== "finalized"}
                    onClick={() => setOpenShare(true)}
                    title={
                      brandedStatus !== "finalized"
                        ? "Najpierw zapisz CV do klienta w edytorze"
                        : undefined
                    }
                  >
                    Wyślij klientowi
                  </Button>
                ) : null}
              </>
            ) : null}
          </>
        ) : null}
        {(!readOnly && !ended && stageId != null) || canRemove ? (
          // Rzadkie i nieodwracalne akcje w „⋯” — czerwony przycisk przy każdym
          // procesie zachęcał do pomyłki (przegląd 04.10.2026).
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto min-h-9 min-w-9"
                aria-label={`Więcej akcji: ${jobNameText(candidateJobNames({ ...job, job_id: jobId }))}`}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              {!readOnly && !ended && stageId != null ? (
                <DropdownMenuItem
                  className="min-h-11"
                  title="Aktualizuj snapshot oryginalnego z bieżącym CV kandydata"
                  onSelect={() => setTimeout(() => setConfirmRefresh(true), 0)}
                >
                  <RefreshCcw className="h-4 w-4" />
                  Odśwież CV oryginalne
                </DropdownMenuItem>
              ) : null}
              {canRemove ? (
                <DropdownMenuItem
                  className="min-h-11 text-destructive focus:text-destructive"
                  title="Usuń kandydata z tej rekrutacji"
                  onSelect={() => setTimeout(() => setConfirmRemove(true), 0)}
                >
                  <Trash2 className="h-4 w-4" />
                  Usuń z rekrutacji
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>

      {openOriginal && stageId != null ? (
        <CVOriginalPreviewModal
          open
          onOpenChange={setOpenOriginal}
          stageId={stageId}
          jobTitle={job.job_title}
          candidateName={candidateName}
        />
      ) : null}
      {openClientCv && cvStageId != null ? (
        <CvFilePreviewDialog
          open
          onOpenChange={setOpenClientCv}
          title={`${clientCvLabel} — ${candidateName}`}
          loadPdf={() => fetchStageCvPdf(cvStageId).then((file) => file.blob)}
          load={() => fetchStageCvFile(cvStageId).then((file) => file.blob)}
          fallbackHtml={branded?.content_html ?? null}
          language={branded?.language === "en" ? "en" : "pl"}
          textAlign={normalizeCvAlign(branded?.text_align)}
        />
      ) : null}
      {!readOnly && openBranded && stageId != null ? (
        <CVBrandedEditModal
          open
          onOpenChange={setOpenBranded}
          onRegenerate={() => setOpenGenerator(true)}
          stageId={cvStageId ?? stageId}
          jobTitle={job.job_title}
          candidateName={candidateName}
        />
      ) : null}
      {!readOnly && openGenerator ? (
        <CvGeneratorDialog
          open
          onOpenChange={setOpenGenerator}
          candidateId={candidateId}
          candidateName={candidateName}
          jobId={jobId}
          onEnqueued={() => {
            setOpenGenerator(false);
            showSuccess("CV generuje się w tle. Gdy będzie gotowe, pojawi się przy tej rekrutacji.");
            void queryClient.invalidateQueries({ queryKey: ["cv-branded", stageId] });
            if (pairStageId != null) {
              void queryClient.invalidateQueries({ queryKey: ["cv-branded", pairStageId] });
            }
          }}
        />
      ) : null}
      {!readOnly && openShare && stageId != null ? (
        <CVShareLinkModal
          open
          onOpenChange={setOpenShare}
          stageId={cvStageId ?? stageId}
          candidateName={candidateName}
        />
      ) : null}

      {!readOnly ? (
        <ConfirmV2
          open={confirmRefresh}
          onOpenChange={setConfirmRefresh}
          title="Aktualizować snapshot oryginalny?"
          description="Zostanie nadpisany aktualną zawartością CV kandydata. Stary snapshot przepadnie. Operacja jest logowana w aktywnościach."
          confirmLabel="Aktualizuj"
          loading={refreshMut.isPending}
          onConfirm={() => refreshMut.mutate()}
        />
      ) : null}
      {canRemove ? (
        <RemoveFromRecruitmentDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          candidateId={candidateId}
          jobId={jobId}
          jobTitle={job.job_title ?? null}
        />
      ) : null}
    </div>
  );
}
