"use client";

/**
 * Zakładka „Rekrutacje”: karty procesów (aktywne na górze, zakończone
 * zwinięte), feedback po rozmowach, zwijane „Dopasowanie do rekrutacji”
 * (dawna zakładka „Dopasowanie”) i boczna kolumna: pasujące otwarte
 * rekrutacje, sugerowane pule oraz dane handlowe (historia stawek, konflikty,
 * weta hiring managerów) — nagłówek tylko wtedy, gdy któryś widżet ma treść.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, ChevronDown, ChevronUp, RefreshCcw, Sparkles, Trash2 } from "lucide-react";

import {
  candidatesApi,
  candidateStageCvApi,
  type CVBrandedState,
  type CVOriginalSnapshot,
  type RateUnit,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { canViewClientRate, canWriteClientRate } from "@/lib/client-rate-access";
import { useAuthStore } from "@/store/auth";
import { CV_CLIENT_LINKS_UI_ENABLED } from "@/lib/cv-generator";
import { stageCvBadge, stageCvStatus } from "@/lib/cv-to-client";
import { CvGeneratorDialog } from "@/components/v2/cv-generator/CvGeneratorDialog";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { CVShareLinkModal } from "@/components/v2/modals/CVShareLinkModal";
import { CandidateInterviewFeedbackPanel } from "@/components/feedback/CandidateInterviewFeedbackPanel";
import { SuggestedJobsWidget } from "@/components/SuggestedJobsWidget";
import { SuggestedPoolsWidget } from "@/components/candidates/SuggestedPoolsWidget";
import { RateHistoryWidget } from "@/components/RateHistoryWidget";
import { ConflictsWidget } from "@/components/ConflictsWidget";
import { HiringManagerVetoesWidget } from "@/components/HiringManagerVetoesWidget";
import { ScreeningSummaryCard } from "@/components/v2/candidate-profile/ScreeningSummaryCard";
import { candidatePipelinesQueryKey } from "@/components/CandidatePipelinesWidget";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { candidateStageLabel } from "@/components/v2/pages/candidate-timeline-labels";
import {
  focusCandidateRecruitmentCard,
  resolveVisibleRecruitmentFocus,
  type CandidateRecruitmentView,
} from "@/components/v2/pages/candidate-profile-navigation";
import { cn, formatDate } from "@/lib/utils";
import { splitRecruitments } from "./profile-helpers";
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

export interface RecruitmentsTabProps {
  candidateId: number;
  candidateName: string;
  history: any[];
  isPending: boolean;
  error: unknown;
  refetch: () => void;
  refreshing: boolean;
  focusedJobId: number | null;
  /** Rekrutacja, z której otwarto profil — domyślna w „Dopasowaniu”. */
  defaultJobId: number | null;
  view: CandidateRecruitmentView;
  readOnly: boolean;
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
}: RecruitmentsTabProps) {
  const { active, ended } = useMemo(() => splitRecruitments(history), [history]);
  const focusedJobId = useMemo(
    () => resolveVisibleRecruitmentFocus(requestedFocusJobId, history),
    [history, requestedFocusJobId],
  );
  const focusInEnded =
    focusedJobId != null &&
    ended.some((job: any) => (job.job_id ?? job.id) === focusedJobId);
  const [endedOpen, setEndedOpen] = useState(false);
  useEffect(() => {
    if (focusInEnded) setEndedOpen(true);
  }, [focusInEnded]);

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

  // `?recruitments=matching` (dawna zakładka „Dopasowanie”) rozwija sekcję.
  const matchingRef = useRef<HTMLElement | null>(null);
  const [matchingOpen, setMatchingOpen] = useState(view === "matching");
  useEffect(() => {
    if (view !== "matching") return;
    setMatchingOpen(true);
    // Po klatce: zamiana starego adresu na kanoniczny (router.replace) i render
    // kart przesuwają układ — przewinięcie od razu trafiało w złe miejsce.
    const timer = window.setTimeout(
      () => matchingRef.current?.scrollIntoView?.({ block: "start" }),
      120,
    );
    return () => window.clearTimeout(timer);
  }, [view]);

  const jobTitles = useMemo(
    () =>
      new Map<number, string>(
        history
          .filter((job: any) => typeof job?.job_id === "number")
          .map((job: any) => [
            job.job_id as number,
            String(job.job_title ?? `Rekrutacja #${job.job_id}`),
          ]),
      ),
    [history],
  );

  const hasData = history.length > 0;

  return (
    <div className="grid grid-cols-1 items-start gap-5 @4xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-4">
        {isPending && !hasData ? (
          <SectionLoading label="Ładowanie rekrutacji…" />
        ) : error && !hasData ? (
          <SectionError title="Nie udało się pobrać rekrutacji" onRetry={refetch} />
        ) : !hasData ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Kandydat nie jest w żadnej rekrutacji.
          </p>
        ) : (
          <div className="space-y-2">
            {refreshing ? (
              <p role="status" className="text-xs text-muted-foreground">
                Odświeżam…
              </p>
            ) : null}
            {active.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Brak trwających procesów.
              </p>
            ) : (
              active.map((job: any, i: number) => (
                <RecruitmentCard
                  key={job.job_id ?? job.id ?? i}
                  job={job}
                  candidateId={candidateId}
                  candidateName={candidateName}
                  focusedJobId={focusedJobId}
                  readOnly={readOnly}
                />
              ))
            )}
            {ended.length > 0 ? (
              <div className="pt-2">
                <button
                  type="button"
                  onClick={() => setEndedOpen((open) => !open)}
                  aria-expanded={endedOpen}
                  className="flex min-h-9 items-center gap-1 text-xs font-medium text-muted-foreground hover:text-primary"
                >
                  {endedOpen ? (
                    <ChevronUp className="h-3 w-3" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )}
                  Zakończone ({ended.length})
                </button>
                {endedOpen ? (
                  <div className="mt-2 space-y-2">
                    {ended.map((job: any, i: number) => (
                      <RecruitmentCard
                        key={job.job_id ?? job.id ?? i}
                        job={job}
                        candidateId={candidateId}
                        candidateName={candidateName}
                        focusedJobId={focusedJobId}
                        readOnly={readOnly}
                      />
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        )}

        <CandidateInterviewFeedbackPanel candidateId={candidateId} jobTitles={jobTitles} />

        <section
          ref={matchingRef}
          id="candidate-matching-section"
          aria-labelledby="candidate-matching-heading"
          className="scroll-mt-4 rounded-lg border border-border"
        >
          <button
            type="button"
            onClick={() => setMatchingOpen((open) => !open)}
            aria-expanded={matchingOpen}
            className="flex min-h-11 w-full items-center justify-between gap-2 px-3 text-left"
          >
            <span
              id="candidate-matching-heading"
              className="flex items-center gap-2 text-sm font-semibold text-foreground"
            >
              <Sparkles className="h-4 w-4 text-primary" />
              Dopasowanie do rekrutacji
            </span>
            {matchingOpen ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
          {matchingOpen ? (
            <div className="border-t border-border p-3">
              {isPending && !hasData ? (
                <SectionLoading label="Ładowanie danych dopasowania…" />
              ) : error && !hasData ? (
                <SectionError
                  title="Nie udało się pobrać danych do dopasowania"
                  onRetry={refetch}
                />
              ) : (
                <DopasowanieTab
                  candidateId={candidateId}
                  recruitments={history}
                  defaultJobId={defaultJobId}
                  readOnly={readOnly}
                />
              )}
            </div>
          ) : null}
        </section>
      </div>

      <aside className="space-y-4 @4xl:sticky @4xl:top-4" aria-label="Sugestie i dane handlowe">
        <ScreeningSummaryCard candidateId={candidateId} />
        <SuggestedJobsWidget
          candidateId={candidateId}
          canAssign={!readOnly}
          hideWhenEmpty
          stacked
          maxItems={5}
          title="Pasujące otwarte rekrutacje"
        />
        <SuggestedPoolsWidget candidateId={candidateId} canAdd={!readOnly} />
        {/* Nagłówek tylko wtedy, gdy któryś widżet coś wyrenderował —
            wszystkie trzy chowają się przy braku danych (`hideWhenEmpty`). */}
        <section
          aria-labelledby="candidate-commercial-data"
          className="hidden space-y-3 has-[[data-commercial-slot]>*]:block"
        >
          <h2
            id="candidate-commercial-data"
            className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
          >
            Dane handlowe
          </h2>
          <div data-commercial-slot>
            <RateHistoryWidget candidateId={candidateId} hideWhenEmpty />
          </div>
          <div data-commercial-slot>
            <ConflictsWidget candidateId={candidateId} hideWhenEmpty />
          </div>
          <div data-commercial-slot>
            <HiringManagerVetoesWidget candidateId={candidateId} hideWhenEmpty />
          </div>
        </section>
      </aside>
    </div>
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
  mutationFn,
  successMessage,
  testIdPrefix,
  readOnly = false,
}: {
  candidateId: number;
  label: string;
  rate: RecruitmentRate;
  mutationFn: (payload: RatePayload) => Promise<unknown>;
  successMessage: string;
  testIdPrefix: string;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(rate?.value != null ? String(rate.value) : "");
  const [unit, setUnit] = useState<RateUnit>((rate?.unit as RateUnit) ?? "monthly");

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
            onClick={() => setEditing(true)}
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
              setValue(rate?.value != null ? String(rate.value) : "");
              setUnit((rate?.unit as RateUnit) ?? "monthly");
            }}
          >
            Anuluj
          </Button>
        </div>
      ) : (
        <div className="font-medium text-foreground">
          {rate ? formatRate(rate.value, rate.currency, rate.unit) : "—"}
        </div>
      )}
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
  readOnly = false,
}: {
  candidateId: number;
  jobId: number;
  clientRate: RecruitmentRate;
  expectedRate: RecruitmentRate;
  readOnly?: boolean;
}) {
  const authUser = useAuthStore((st) => st.user);
  // Decyzja 23.09.2026: stawki do klienta nie widzą rekruter, sourcer i TAC;
  // wpisuje ją wyłącznie DL albo admin (lustro `candidate_access.py`).
  const showClientRate = canViewClientRate(authUser);
  const clientRateWritable = canWriteClientRate(authUser);
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
            testIdPrefix="client-rate"
            successMessage="Zapisano stawkę do klienta"
            readOnly={readOnly || !clientRateWritable}
            mutationFn={(payload) =>
              candidatesApi.setRecruitmentClientRate(candidateId, jobId, payload)
            }
          />
        ) : null}
      </div>
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
}: {
  job: any;
  candidateId: number;
  candidateName: string;
  focusedJobId: number | null;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const stageId: number | null = job.latest_stage_id ?? null;
  const jobId: number = job.job_id ?? job.id;
  const isFocused = focusedJobId === jobId;
  const recruitmentTitleId = `candidate-recruitment-${jobId}-title`;
  const [openOriginal, setOpenOriginal] = useState(false);
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
  const { data: branded } = useQuery<CVBrandedState>({
    queryKey: ["cv-branded", stageId],
    queryFn: () =>
      candidateStageCvApi.branded.get(stageId as number).then((r) => r.data),
    enabled: stageId != null,
  });

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

  const removeMut = useMutation({
    mutationFn: () => {
      if (readOnly) throw new Error("Brak prawa zapisu w Sourcing");
      return candidatesApi.removeFromRecruitment(candidateId, jobId);
    },
    onSuccess: () => {
      showSuccess(
        job.job_title
          ? `Kandydat usunięty z rekrutacji „${job.job_title}”`
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
      setConfirmRemove(false);
    },
    onError: (e) =>
      showError(apiErrorMessage(e, "Błąd podczas usuwania z rekrutacji")),
  });

  const brandedStatus =
    (branded?.status as "none" | "draft" | "finalized" | undefined) ?? "none";
  const stageCv = stageCvStatus(branded);
  const stageCvBadgeInfo = stageCvBadge(branded);

  return (
    <div
      id={`candidate-recruitment-${jobId}`}
      role="group"
      aria-labelledby={recruitmentTitleId}
      tabIndex={isFocused ? -1 : undefined}
      aria-current={isFocused ? "true" : undefined}
      data-focused-recruitment={isFocused ? "true" : undefined}
      className={cn(
        "rounded-lg border border-border p-3 transition-colors hover:border-primary/40",
        isFocused && "border-primary ring-2 ring-ring ring-offset-2",
      )}
    >
      <div className="min-w-0">
        <Link
          id={recruitmentTitleId}
          href={`/jobs/${jobId}`}
          className="font-medium text-foreground hover:underline"
        >
          {job.job_title ?? `Rekrutacja #${jobId}`}
        </Link>
        <div className="text-xs text-muted-foreground">
          {job.client_name ? `${job.client_name} · ` : ""}
          {candidateStageLabel(job.latest_stage)}
          {job.first_seen ? ` · dodano ${formatDate(job.first_seen)}` : ""}
        </div>
        {Array.isArray(job.stages) && job.stages.length > 1 ? (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {job.stages.slice(0, 6).map((s: any, si: number) => (
              <Badge key={si} size="sm" variant="soft">
                {candidateStageLabel(s.stage)}
              </Badge>
            ))}
          </div>
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

      <RecruitmentRateRow
        candidateId={candidateId}
        jobId={jobId}
        clientRate={job.client_rate ?? null}
        expectedRate={job.expected_rate ?? null}
        readOnly={readOnly}
      />

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
            {!readOnly ? (
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
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirmRefresh(true)}
                  title="Aktualizuj snapshot oryginalnego z bieżącym CV kandydata"
                  aria-label="Aktualizuj snapshot CV oryginalnego"
                >
                  <RefreshCcw className="h-3.5 w-3.5" />
                </Button>
              </>
            ) : null}
          </>
        ) : null}
        {!readOnly ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setConfirmRemove(true)}
            className="ml-auto text-destructive hover:bg-destructive/10 hover:text-destructive"
            title="Usuń kandydata z tej rekrutacji"
          >
            <Trash2 className="mr-1 h-3.5 w-3.5" />
            Usuń z rekrutacji
          </Button>
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
      {!readOnly && openBranded && stageId != null ? (
        <CVBrandedEditModal
          open
          onOpenChange={setOpenBranded}
          onRegenerate={() => setOpenGenerator(true)}
          stageId={stageId}
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
          }}
        />
      ) : null}
      {!readOnly && openShare && stageId != null ? (
        <CVShareLinkModal
          open
          onOpenChange={setOpenShare}
          stageId={stageId}
          candidateName={candidateName}
        />
      ) : null}

      {!readOnly ? (
        <>
          <ConfirmV2
            open={confirmRefresh}
            onOpenChange={setConfirmRefresh}
            title="Aktualizować snapshot oryginalny?"
            description="Zostanie nadpisany aktualną zawartością CV kandydata. Stary snapshot przepadnie. Operacja jest logowana w aktywnościach."
            confirmLabel="Aktualizuj"
            loading={refreshMut.isPending}
            onConfirm={() => refreshMut.mutate()}
          />
          <ConfirmV2
            open={confirmRemove}
            onOpenChange={setConfirmRemove}
            variant="destructive"
            title="Usunąć kandydata z tej rekrutacji?"
            description={`Kandydat zostanie zdjęty z pipeline'u rekrutacji „${job.job_title ?? `#${jobId}`}”. Usunięta zostanie cała historia jego etapów na tej rekrutacji wraz ze snapshotami CV (oryginalne i firmowe) oraz linkami do udostępnień. Tego nie można cofnąć — kandydata można jednak dodać ponownie. Profil i umowy pozostają bez zmian. To nie to samo co odrzucenie — jeśli kandydat brał udział w procesie, użyj „Odrzuć” na tablicy, żeby zachować historię.`}
            confirmLabel="Usuń z rekrutacji"
            loading={removeMut.isPending}
            onConfirm={() => removeMut.mutate()}
          />
        </>
      ) : null}
    </div>
  );
}
