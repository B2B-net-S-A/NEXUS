"use client";

/**
 * ScreeningWorkbench — stanowisko screeningu (krok 05 programu „flow w języku
 * C2", docs/c2-flow-program.md; układ z makiety — fala 3).
 *
 * Dziś screening jest rozrzucony: arkusz wyskakuje jako modal po przeciągnięciu
 * karty, pytania przypięte do rekrutacji mieszkają w zakładce „Baza pytań",
 * prep-kit pod nielinkowanym adresem `/jobs/{id}/prep/{candidateId}`, a stawka
 * w osobnym modalu przy ruchu na „Zweryfikowany". Ten ekran zbiera to w jedno
 * miejsce: kolejka po lewej, arkusz Championa w środku, dok „Weryfikacja"
 * po prawej. **Żadne z tych miejsc nie znika** — modal, „Baza pytań" i ruch
 * z tablicy działają dokładnie jak dotąd.
 *
 * Zero nowych endpointów: kolumny przychodzą z `GET /api/pipeline/kanban/{id}`,
 * które strona rekrutacji pobiera już dla listwy kroków; arkusz woła
 * `…/stages/{id}/screening`, ruch — `POST /api/pipeline/move` z
 * `expected_rate_*`, a odrzucenie z powodem idzie TYM SAMYM modalem
 * (`RejectionV2`) i tą samą trasą co decyzja z tablicy i z kroku 07.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  ExternalLink,
  FileText,
  HelpCircle,
  Loader2,
  Save,
  Sparkles,
  UserX,
} from "lucide-react";

import api, {
  extractErrorMsg,
  interviewQuestionsApi,
  pipelineApi,
  screeningApi,
  type RateUnit,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { hasRole, useAuthStore } from "@/store/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import { Form } from "@/components/v2/forms";
import {
  FIT_OPTIONS,
  ScreeningFormFields,
  ScreeningNoQuestions,
  ScreeningSubmitError,
  useScreeningForm,
} from "@/components/v2/screening/ScreeningForm";
import { VerifiedRateFields } from "@/components/v2/screening/VerifiedRateFields";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import {
  RejectionV2,
  type CandidateOfferResponse,
} from "@/components/v2/modals/RejectionV2";
import { evaluateRateGate } from "@/lib/verified-rate-gate";
import { useClientPlaybook } from "@/lib/client-playbooks";
import {
  loadJobRejectionReasons,
  type RejectionReasonOption,
} from "@/lib/rejection-reasons";
import { terminalOf } from "@/lib/kanban-terminal";
import {
  VERIFIED_STAGE,
  findStageColumn,
  formatExpectedRate,
  itemFullName,
  moveBlockedReason,
  selectPendingVerifications,
  selectScreeningQueue,
  stageAgeTone,
  type FlowQueueEntry,
} from "@/lib/pipeline-flow";
import { countPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";
import { cn, formatDate } from "@/lib/utils";
import { encodeJobBackRef } from "@/lib/url-filters";
import {
  ChromeBanner,
  DockActions,
  DockNotesPanel,
  DockSection,
  RailRow,
  RailSection,
  ReqRow,
  ToolPill,
  WorkbenchDock,
  WorkbenchHeader,
  WorkbenchRail,
  type DockTabItem,
} from "@/components/v2/jobs/workbench-chrome";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";

export interface ScreeningWorkbenchProps {
  jobId: number;
  /** Budżet miesięczny rekrutacji (`Job.salary_max`) — bramka stawki. */
  jobBudgetMax: number | null;
  columns: KanbanColumn[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  onRetry: () => void;
  /** Odśwież kanban po udanym ruchu (strona trzyma klucz zapytania). */
  onMoved: () => void;
  readOnly: boolean;
  onTabChange: (tab: JobDetailTab) => void;
  /** Klient rekrutacji — SLA z karty klienta w nagłówku kolejki. */
  clientId?: number | null;
  /** Nazwa klienta do etykiety „SLA <klient>". */
  clientName?: string | null;
}

type DockTab = "decision" | "notes";

function daysLabel(n: number): string {
  return `${n} ${Math.abs(n) === 1 ? "dzień" : "dni"}`;
}

export function ScreeningWorkbench({
  jobId,
  jobBudgetMax,
  columns,
  isLoading,
  isError,
  error,
  isSuccess,
  onRetry,
  onMoved,
  readOnly,
  onTabChange,
  clientId = null,
  clientName = null,
}: ScreeningWorkbenchProps) {
  const { showSuccess, showError, showActionToast } = useToast();
  const queryClient = useQueryClient();
  // `/pending-verifications` jest bramkowane rolą approvera (admin / DL / HoR)
  // — link dla rekrutera prowadziłby wprost w 403.
  const authUser = useAuthStore((s) => s.user);
  const canApprove = hasRole(
    authUser,
    "admin",
    "delivery_lead",
    "head_of_recruitment",
  );

  const queue = useMemo(() => selectScreeningQueue(columns), [columns]);
  const pendingQueue = useMemo(
    () => selectPendingVerifications(columns),
    [columns],
  );
  const verifiedCol = useMemo(
    () => findStageColumn(columns, VERIFIED_STAGE),
    [columns],
  );
  const rejectedCol = useMemo(
    () => columns.find((c) => terminalOf(c) === "rejected") ?? null,
    [columns],
  );

  const [selectedStageId, setSelectedStageId] = useState<number | null>(null);
  const [dockTab, setDockTab] = useState<DockTab>("decision");
  const [showOriginalCv, setShowOriginalCv] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  // Pierwsze wejście (i zniknięcie wybranej karty po ruchu) wybiera pierwszą
  // pozycję kolejki. Bez tego stanowisko startuje puste, mimo że ktoś czeka.
  // Wybierać można z OBU list (kolejka screeningu i „czeka na akceptację") —
  // klik w pending-a otwiera JEGO arkusz, zamiast gasić całe stanowisko
  // (karty pending stoją w kolumnie „Zweryfikowany", nie w kolejce screeningu).
  const allEntries = useMemo(
    () => [...queue, ...pendingQueue],
    [queue, pendingQueue],
  );
  useEffect(() => {
    setSelectedStageId((prev) =>
      prev != null && allEntries.some((e) => e.item.id === prev)
        ? prev
        : (queue[0]?.item.id ?? null),
    );
  }, [queue, allEntries]);

  const selected: FlowQueueEntry | null =
    allEntries.find((e) => e.item.id === selectedStageId) ?? null;

  // ── SLA klienta (karta klienta) — kontekst wieku na etapie ──────────────
  const playbookQuery = useClientPlaybook(clientId);
  const slaDays = playbookQuery.data?.sla_business_days ?? null;

  // ── Stawka (dok) — resetowana przy zmianie kandydata ────────────────────
  const [rate, setRate] = useState("");
  const [unit, setUnit] = useState<RateUnit>("hourly");
  useEffect(() => {
    setRate("");
    setUnit("hourly");
    setDockTab("decision");
  }, [selectedStageId]);
  const gate = evaluateRateGate({
    rawRate: rate,
    unit,
    currency: "PLN",
    jobBudgetMax,
  });

  // ── Arkusz Championa dla wybranego etapu ────────────────────────────────
  const screening = useScreeningForm({
    // `-1` nie jest wołane: `enabled` jest wtedy false. Hook musi jednak dostać
    // liczbę, a montowanie go warunkowo złamałoby regułę hooków.
    stageId: selected?.item.id ?? -1,
    enabled: selected != null,
  });
  const screeningSaved = screening.data?.screening_answers ?? null;
  const screeningDirty = screening.methods.formState.isDirty;
  const answers = screening.questions.map((q) => ({
    id: q.id,
    question: q.question,
    response: (
      screening.methods.watch(`answers.${q.id}.response`) ?? ""
    ).trim(),
    dealBreakerHit: Boolean(
      screening.methods.watch(`answers.${q.id}.deal_breaker_hit`),
    ),
  }));
  const answeredCount = answers.filter((a) => a.response).length;
  const dealBreakerHit = answers.some((a) => a.dealBreakerHit);
  const overallFit = screening.methods.watch("overall_fit");

  // ── Pytania przypięte do rekrutacji (zakładka „Baza pytań") ─────────────
  const pinnedQuery = useQuery({
    queryKey: ["job-questions", jobId],
    queryFn: () => interviewQuestionsApi.listForJob(jobId).then((r) => r.data),
    staleTime: 60_000,
  });

  // ── Słownik powodów odrzucenia — ten sam, co na tablicy i w kroku 07 ────
  const reasonsQuery = useQuery<RejectionReasonOption[]>({
    queryKey: ["job-rejection-reasons", jobId],
    queryFn: () => loadJobRejectionReasons(jobId),
    staleTime: 5 * 60_000,
  });

  // ── Ruch na „Zweryfikowany" — TEN SAM endpoint co drag&drop ─────────────
  const moveMut = useMutation({
    mutationFn: async () => {
      if (!selected || !verifiedCol) throw new Error("Brak etapu docelowego.");
      const res = await pipelineApi.move({
        candidate_id: selected.item.candidate_id,
        job_id: jobId,
        stage: VERIFIED_STAGE,
        stage_def_id: verifiedCol.stage_def_id ?? undefined,
        expected_rate_value: gate.numericRate,
        expected_rate_unit: unit,
        expected_rate_currency: "PLN",
      });
      const moved = res.data as {
        id?: number;
        verification_status?: "active" | "pending";
      };
      // Ruch tworzy NOWY `CandidateStage`, a `transition_process` nie kopiuje
      // `screening_answers` — arkusz zapisany na etapie „Screening" zostałby na
      // historycznym rekordzie, a portal klienta i generator CV czytają etap
      // NAJNOWSZY. Przepisujemy zapisane odpowiedzi na nowy etap (tablica
      // unika tego, otwierając arkusz dopiero PO ruchu).
      let screeningCopyFailed = false;
      if (screeningSaved && moved.id != null && moved.id !== selected.item.id) {
        try {
          await screeningApi.submit(moved.id, screeningSaved);
        } catch {
          screeningCopyFailed = true;
        }
      }
      return { ...moved, screeningCopyFailed };
    },
    onSuccess: (data) => {
      if (data.screeningCopyFailed) {
        showError(
          "Przeniesiono na „Zweryfikowany”, ale nie udało się przepisać arkusza screeningu na nowy etap — otwórz arkusz z tablicy Pipeline i zapisz go ponownie.",
        );
      } else if (data?.verification_status === "pending") {
        showSuccess(
          "Wysłano do akceptacji stawki. Karta będzie aktywna po zatwierdzeniu.",
        );
      } else {
        showSuccess("Kandydat przeniesiony na „Zweryfikowany”.");
      }
      onMoved();
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się przenieść kandydata."),
  });

  /**
   * Odrzucenie z powodem — ta sama trasa, co decyzja z tablicy i z kroku 07:
   * `RejectionV2` → `POST /api/pipeline/move` z powodem, notatką i regułą
   * maila (15 min + „Cofnij wysyłkę"). Zero drugiej implementacji reguł.
   */
  const rejectMut = useMutation({
    mutationFn: async (vars: {
      reasonId: string;
      notes: string;
      sendRejectionEmail: boolean | null;
      offerResponse: CandidateOfferResponse | null;
      freeReason?: string;
    }) => {
      if (!selected || !rejectedCol) throw new Error("Brak etapu docelowego.");
      return api.post("/api/pipeline/move", {
        candidate_id: selected.item.candidate_id,
        job_id: jobId,
        stage: rejectedCol.stage,
        stage_def_id: rejectedCol.stage_def_id ?? undefined,
        rejection_reason_id: vars.reasonId || undefined,
        rejection_reason: vars.freeReason || undefined,
        notes: vars.notes,
        send_rejection_email: vars.sendRejectionEmail ?? undefined,
        candidate_offer_response: vars.offerResponse ?? undefined,
      });
    },
    onSuccess: (res) => {
      setRejectOpen(false);
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      showSuccess("Zapisano decyzję.");
      // 0045_rejection_emails — ta sama afordancja co na tablicy: backend
      // zaplanował mail odrzucenia za 15 min, rekruter ma 10 s na „Cofnij".
      const scheduledId = (
        res as { data?: { scheduled_rejection_email_id?: number | null } } | null
      )?.data?.scheduled_rejection_email_id;
      if (scheduledId && showActionToast) {
        showActionToast("Email odrzucenia zostanie wysłany za 15 minut.", {
          actionLabel: "Cofnij wysyłkę",
          onAction: async () => {
            try {
              await api.post(`/api/rejection-emails/${scheduledId}/cancel`);
              showSuccess("Anulowano wysyłkę emaila.");
            } catch {
              showError("Nie udało się anulować wysyłki.");
            }
          },
          durationMs: 10_000,
        });
      }
      onMoved();
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się zapisać decyzji."),
  });

  // Bramka ruchu — widoczna z powodem, nigdy 409 po kliknięciu.
  const moveBlocked = selected
    ? (moveBlockedReason({ item: selected.item, readOnly }) ??
      (!verifiedCol
        ? "Szablon tej rekrutacji nie ma kolumny „Zweryfikowany”."
        : !gate.isValid
          ? "Podaj stawkę oczekiwaną — backend jej wymaga przy tym ruchu."
          : screeningDirty
            ? "Arkusz screeningu ma niezapisane odpowiedzi — zapisz go najpierw (przeniesienie tworzy NOWY etap, ten formularz dotyczy obecnego)."
            : null))
    : "Wybierz kandydata z kolejki.";

  // ── Stany widoku ────────────────────────────────────────────────────────
  const viewState = resolveViewState({
    isLoading,
    isError,
    error,
    isSuccess,
  });

  if (viewState === "loading") {
    return (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (
    viewState === "forbidden" ||
    viewState === "not_found" ||
    viewState === "error"
  ) {
    return (
      <QueryStateNotice
        state={viewState}
        className="rounded-xl"
        description={
          viewState === "forbidden"
            ? "Twoja rola nie ma dostępu do pipeline'u tej rekrutacji — to nie znaczy, że kolejka screeningu jest pusta."
            : undefined
        }
        onRetry={onRetry}
      />
    );
  }

  const selectedName = selected ? itemFullName(selected.item) : null;
  const dockTabs: DockTabItem[] = [
    { value: "decision", label: "Stawka i decyzja" },
    { value: "notes", label: "Notatki" },
  ];
  const slaMeta =
    slaDays != null
      ? `SLA ${clientName?.trim() || "klienta"}: ${slaDays} d`
      : null;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
      {/* ── Szyna: kolejki i źródła pytań ──────────────────────────────── */}
      <WorkbenchRail
        icon={<ClipboardCheck className="h-4 w-4 text-primary" />}
        title="Kolejka screeningu"
        count={queue.length}
        meta={slaMeta}
        footer={
          <Button
            size="sm"
            variant="outline"
            className="justify-center"
            disabled={!selected}
            title={
              selected
                ? "Podgląd CV oryginalnego z momentu zgłoszenia (snapshot etapu)"
                : "Wybierz kandydata z kolejki"
            }
            onClick={() => setShowOriginalCv(true)}
          >
            <FileText className="h-3.5 w-3.5" /> Pokaż CV obok
          </Button>
        }
      >
        {queue.length > 0 ? (
          <div className="space-y-0.5" role="list" aria-label="Kolejka screeningu">
            {queue.map((entry) => (
              <div key={entry.item.id} role="listitem">
                <RailRow
                  tone={
                    entry.item.hm_veto
                      ? "bad"
                      : entry.item.verification_status === "pending"
                        ? "warn"
                        : stageAgeTone(entry.item.days_in_stage, slaDays)
                  }
                  label={itemFullName(entry.item)}
                  meta={
                    entry.item.days_in_stage != null
                      ? `${entry.item.days_in_stage} d`
                      : undefined
                  }
                  metaTone={stageAgeTone(entry.item.days_in_stage, slaDays)}
                  active={entry.item.id === selectedStageId}
                  onSelect={() => setSelectedStageId(entry.item.id)}
                />
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Nikt nie stoi dziś na etapie „Screening”. Przenieś kandydata z
            Pipeline’u, żeby zacząć rozmowę.
          </p>
        )}

        <RailSection
          label="Czeka na akceptację stawki"
          note={
            <>
              Approverzy: admin · Delivery Lead · HoR.{" "}
              {canApprove ? (
                <Link
                  href="/pending-verifications"
                  className="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  <ExternalLink className="h-3 w-3" /> Kolejka globalna
                </Link>
              ) : (
                "Kolejka globalna jest dla nich."
              )}
            </>
          }
        >
          {pendingQueue.length > 0 ? (
            <div className="space-y-0.5">
              {pendingQueue.map((entry) => (
                <RailRow
                  key={entry.item.id}
                  tone="warn"
                  label={itemFullName(entry.item)}
                  secondary={formatExpectedRate(entry.item) ?? undefined}
                  meta="pending"
                  metaTone="warn"
                  active={entry.item.id === selectedStageId}
                  onSelect={() => setSelectedStageId(entry.item.id)}
                />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Nikt nie czeka na akceptację stawki.
            </p>
          )}
        </RailSection>

        <RailSection label="Pytania do rozmowy">
          <div className="space-y-0.5">
            <RailRow
              tone="info"
              label="Z Championa (sekcja 5)"
              meta={selected ? String(screening.questions.length) : "—"}
            />
            <RailRow
              label="Przypięte do rekrutacji"
              meta={
                pinnedQuery.isLoading
                  ? "…"
                  : pinnedQuery.isError
                    ? "—"
                    : String(pinnedQuery.data?.length ?? 0)
              }
              onSelect={() => onTabChange("questions")}
            />
            {selected && (
              <Link
                href={`/jobs/${jobId}/prep/${selected.item.candidate_id}`}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-accent"
              >
                <Sparkles className="h-3 w-3 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 truncate">
                  Prep-kit (AI, z podobnych)
                </span>
                <span className="shrink-0 text-[10.5px] text-muted-foreground">
                  otwórz
                </span>
              </Link>
            )}
          </div>
          <button
            type="button"
            onClick={() => onTabChange("questions")}
            className="flex h-7 w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-border text-[11px] text-muted-foreground hover:bg-accent"
          >
            <BookOpen className="h-3 w-3" /> Szukaj w bazie pytań · + Dodaj
          </button>
        </RailSection>
      </WorkbenchRail>

      {/* ── Środek: nagłówek i arkusz screeningu ────────────────────────── */}
      <div className="min-w-0 space-y-4">
        {!selected ? (
          <div className="rounded-xl border border-dashed border-border bg-muted/20 p-8 text-center text-sm text-muted-foreground">
            <ClipboardCheck className="mx-auto mb-2 h-6 w-6 opacity-40" />
            {queue.length === 0
              ? "Kolejka screeningu jest pusta — nikt nie czeka dziś na rozmowę."
              : "Wybierz kandydata z kolejki po lewej."}
          </div>
        ) : (
          <>
            <WorkbenchHeader
              title={`Screening · ${selectedName}`}
              subtitle={[
                selected.col.name ?? "Screening",
                selected.item.days_in_stage != null
                  ? slaDays != null
                    ? `dzień ${selected.item.days_in_stage} z ${slaDays} SLA`
                    : `${daysLabel(selected.item.days_in_stage)} na etapie`
                  : null,
                formatExpectedRate(selected.item),
              ]
                .filter(Boolean)
                .join(" · ")}
              badges={
                <>
                  {selected.item.verification_status === "pending" && (
                    <Badge variant="warning" size="sm">
                      <HelpCircle className="h-2.5 w-2.5" /> Pending
                    </Badge>
                  )}
                  {selected.item.hm_veto && (
                    <Badge
                      variant="danger"
                      size="sm"
                      title={`Powód: ${selected.item.hm_veto.rejection_reason_name}`}
                    >
                      <UserX className="h-2.5 w-2.5" /> Weto HM
                    </Badge>
                  )}
                </>
              }
              actions={
                <Link
                  href={`/candidates/${selected.item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
                >
                  <ExternalLink className="h-3.5 w-3.5" /> Pełny profil
                </Link>
              }
              tools={
                <>
                  <ToolPill tone={overallFit === "fit" ? "ok" : "info"}>
                    Ogólna ocena dopasowania:{" "}
                    {screeningSaved || screeningDirty
                      ? (FIT_OPTIONS.find((o) => o.value === overallFit)
                          ?.label ?? "—")
                      : "—"}
                  </ToolPill>
                  <ToolPill>
                    {screening.questions.length > 0
                      ? `${answeredCount} z ${countPl(screening.questions.length, "pytania", "pytań", "pytań")} odpowiedzianych`
                      : "Brak pytań Championa"}
                  </ToolPill>
                  {dealBreakerHit && (
                    <ToolPill tone="bad">
                      <AlertTriangle className="h-3 w-3" /> deal-breaker
                      zaznaczony
                    </ToolPill>
                  )}
                </>
              }
              toolsRight={
                screeningDirty ? (
                  <span className="inline-flex items-center gap-1 text-[11px] text-warning-muted-foreground">
                    <Clock className="h-3 w-3" /> Niezapisane zmiany
                  </span>
                ) : screeningSaved?.answered_at ? (
                  <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                    <Clock className="h-3 w-3" /> Zapisano{" "}
                    {formatDate(screeningSaved.answered_at)}
                  </span>
                ) : null
              }
            />

            <div className="rounded-xl border border-border bg-card p-4">
              {screening.query.isLoading ? (
                <div className="flex items-center gap-1.5 py-8 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Ładowanie pytań
                  screeningowych…
                </div>
              ) : screening.query.isError ? (
                <QueryStateNotice
                  state={
                    resolveViewState({
                      isLoading: false,
                      isError: true,
                      error: screening.query.error,
                      isSuccess: false,
                    }) as "forbidden" | "not_found" | "error"
                  }
                  onRetry={() => void screening.query.refetch()}
                />
              ) : screening.questions.length === 0 ? (
                <ScreeningNoQuestions
                  onOpenChampion={() => onTabChange("champion")}
                />
              ) : (
                <Form methods={screening.methods} onSubmit={screening.onSubmit}>
                  <ScreeningFormFields
                    questions={screening.questions}
                    methods={screening.methods}
                  />
                  {screening.submitError && (
                    <ScreeningSubmitError message={screening.submitError} />
                  )}
                  {!readOnly && (
                    <div className="flex justify-end border-t border-border pt-3">
                      <Button
                        type="submit"
                        loading={screening.submitMut.isPending}
                      >
                        <Save className="h-4 w-4" /> Zapisz screening
                      </Button>
                    </div>
                  )}
                </Form>
              )}
            </div>

            {screening.questions.length > 0 && (
              <ChromeBanner
                tone="warn"
                icon={<AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
              >
                Deal-breaker zaznaczony przy dowolnym pytaniu zeruje wynik
                screeningu Championa (<code>match_percent = 0</code>) — tak jak
                dziś.
              </ChromeBanner>
            )}
          </>
        )}
      </div>

      {/* ── Dok: weryfikacja stawki i decyzja ───────────────────────────── */}
      <aside className="lg:col-span-2 xl:sticky xl:top-4 xl:col-span-1 xl:self-start">
        <WorkbenchDock
          name="Weryfikacja"
          who={selectedName}
          whoSub={
            selected
              ? [
                  selected.col.name ?? "Screening",
                  selected.item.days_in_stage != null
                    ? `${selected.item.days_in_stage} d`
                    : null,
                  selected.item.added_to_job_by_name,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : undefined
          }
          tabs={selected ? dockTabs : undefined}
          activeTab={dockTab}
          onTabChange={(v) => setDockTab(v as DockTab)}
          footer={
            <>
              <FileText className="h-3 w-3 shrink-0" />
              Snapshot CV oryginalnego robi się przy pierwszym ruchu — tak jak
              dziś.
            </>
          }
        >
          {!selected ? (
            <p className="text-xs text-muted-foreground">
              Wybierz kandydata z kolejki, żeby wpisać stawkę i zamknąć
              weryfikację.
            </p>
          ) : dockTab === "notes" ? (
            <DockNotesPanel
              candidateId={selected.item.candidate_id}
              jobId={jobId}
              readOnly={readOnly}
              enabled={dockTab === "notes"}
            />
          ) : (
            <>
              <DockSection title="Stawka oczekiwana" right='gate „Zweryfikowany"'>
                <VerifiedRateFields
                  rate={rate}
                  onRateChange={setRate}
                  unit={unit}
                  onUnitChange={setUnit}
                  gate={gate}
                  disabled={readOnly}
                  idPrefix="screening-dock-rate"
                />
                <p className="text-[10.5px] text-muted-foreground">
                  Powyżej budżetu albo nieznana jednostka → karta „Pending”
                  i powiadomienie approverów (admin / DL / HoR). Normalizacja:
                  h×168, dzień×21.
                </p>
              </DockSection>

              <DockSection title="Wynik screeningu">
                {answers.length > 0 ? (
                  <div>
                    {answers.map((a) => (
                      <ReqRow
                        key={a.id}
                        tone={
                          a.dealBreakerHit ? "n" : a.response ? "y" : "w"
                        }
                        label={a.question}
                        tag={
                          a.dealBreakerHit
                            ? "narusza"
                            : a.response
                              ? "ok"
                              : "brak"
                        }
                      />
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Ta rekrutacja nie ma pytań Championa — wynik screeningu
                    będzie sam z siebie pusty.
                  </p>
                )}
                <div className="flex flex-wrap gap-1 pt-1">
                  {FIT_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      disabled={readOnly || screening.questions.length === 0}
                      aria-pressed={overallFit === opt.value}
                      title={opt.description}
                      onClick={() =>
                        screening.methods.setValue("overall_fit", opt.value, {
                          shouldDirty: true,
                        })
                      }
                      className={cn(
                        "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                        overallFit === opt.value
                          ? "border-primary bg-primary/10 font-medium text-primary"
                          : "border-border bg-background text-muted-foreground hover:bg-muted",
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                <p className="text-[10.5px] text-muted-foreground">
                  Te same pigułki co „Ogólna ocena dopasowania” w arkuszu —
                  jeden stan, dwa miejsca. Zapisuje je „Zapisz screening”.
                </p>
                {screeningDirty && (
                  <p className="inline-flex items-start gap-1 text-[11px] text-warning-muted-foreground">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                    Masz niezapisane odpowiedzi w arkuszu.
                  </p>
                )}
              </DockSection>

              {!readOnly && (
                <DockActions>
                  <Button
                    className="col-span-2 w-full justify-start"
                    size="sm"
                    disabled={Boolean(moveBlocked) || moveMut.isPending}
                    loading={moveMut.isPending}
                    title={moveBlocked ?? undefined}
                    onClick={() => moveMut.mutate()}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Zweryfikowany — zapisz stawkę i przenieś
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start"
                    title="Zostaw kandydata w kolejce i wróć do niego później"
                    onClick={() => setSelectedStageId(null)}
                  >
                    <Clock className="h-3.5 w-3.5" /> Wróć później
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start text-destructive hover:bg-destructive/10 hover:text-destructive"
                    disabled={!rejectedCol}
                    title={
                      rejectedCol
                        ? "Ten sam modal powodu i ta sama reguła maila co na tablicy"
                        : "Szablon tej rekrutacji nie ma kolumny „Odrzucony”."
                    }
                    onClick={() => setRejectOpen(true)}
                  >
                    <Ban className="h-3.5 w-3.5" /> Odrzuć z powodem
                  </Button>
                </DockActions>
              )}
              {moveBlocked && !readOnly && (
                <p className="text-[11px] text-muted-foreground">
                  {moveBlocked}
                </p>
              )}
            </>
          )}
        </WorkbenchDock>
      </aside>

      {selected && showOriginalCv && (
        <CVOriginalPreviewModal
          open
          onOpenChange={setShowOriginalCv}
          stageId={selected.item.id}
          jobTitle={`Rekrutacja #${jobId}`}
          candidateName={selectedName ?? "Kandydat"}
        />
      )}

      {selected && rejectedCol && rejectOpen && (
        <RejectionV2
          open
          onOpenChange={setRejectOpen}
          terminalType="rejected"
          reasons={reasonsQuery.data ?? []}
          previousStageCategory={
            selected.col.category === "external" ? "external" : "internal"
          }
          previousStage={selected.col.stage}
          onConfirm={(
            reasonId,
            notes,
            sendRejectionEmail,
            offerResponse,
            freeReason,
          ) =>
            rejectMut.mutate({
              reasonId,
              notes,
              sendRejectionEmail,
              offerResponse: offerResponse ?? null,
              freeReason,
            })
          }
        />
      )}
    </div>
  );
}
