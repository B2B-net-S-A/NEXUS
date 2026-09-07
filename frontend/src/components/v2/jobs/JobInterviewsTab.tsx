"use client";

/**
 * Krok 07 „Rozmowy i decyzja" — program „flow w języku C2" (PR 7/7).
 *
 * Zbiera w jednym miejscu to, co dziś jest rozrzucone: kto jest u klienta
 * (kanban), prep-kit (własna strona), Screening Championa dla klienta (modal
 * + link 30-dniowy), weto hiring managera (chip na karcie + 409 przy ruchu)
 * i decyzję (modale odrzucenia). Żadna z tych rzeczy nie znika ze swojego
 * miejsca — ta zakładka je CYTUJE i linkuje.
 *
 * Dane pipeline'u przychodzą PROPSEM z tego samego zapytania `["kanban", id]`,
 * którym strona karmi tablicę. Zero zapytań per wiersz.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  ExternalLink,
  FileText,
  Link2,
  Loader2,
  Save,
  Sparkles,
  UserX,
} from "lucide-react";

import api, {
  extractErrorMsg,
  hiringManagerFeedbackApi,
  screeningApi,
  type HiringManagerDecision,
  type HiringManagerFeedback,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, QueryStateNotice } from "@/components/ds";
import { cn, formatDate } from "@/lib/utils";
import { countPl } from "@/lib/plural-pl";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { terminalOf } from "@/lib/kanban-terminal";
import { isInterviewStage } from "@/lib/job-flow-stages";
import {
  loadJobRejectionReasons,
  type RejectionReasonOption,
} from "@/lib/rejection-reasons";
import {
  colId,
  columnLabel,
  type KanbanColumn,
  type KanbanItem,
} from "@/components/v2/pages/kanban-shared";
import { ScreeningSheet } from "@/components/v2/modals/ScreeningSheet";
import {
  RejectionV2,
  type CandidateOfferResponse,
} from "@/components/v2/modals/RejectionV2";
import {
  InterviewDecisionDock,
  InterviewDecisionDockEmpty,
  buildDecisionMoveTargets,
} from "@/components/v2/jobs/InterviewDecisionDock";

const DECISION_OPTIONS: { value: HiringManagerDecision; label: string }[] = [
  { value: "advance", label: "Dalej" },
  { value: "on_hold", label: "Druga rozmowa" },
  { value: "reject", label: "Odrzuca" },
];

export interface JobInterviewsTabProps {
  jobId: number;
  jobTitle?: string;
  columns: KanbanColumn[];
  readOnly: boolean;
  /** Zapytanie kanbana jeszcze trwa — nie pokazuj pustego stanu jako prawdy. */
  columnsLoading?: boolean;
  /**
   * Błąd zapytania kanbana. Pipeline przychodzi PROPSEM, więc bez tego 403
   * albo 500 renderowałby się tu jako „nikt nie jest u klienta" — awaria nie
   * do odróżnienia od zera.
   */
  columnsError?: unknown;
  /** `isSuccess` zapytania kanbana — pusty stan wolno pokazać tylko po nim. */
  columnsSuccess?: boolean;
  onColumnsRetry?: () => void;
}

interface SelectedEntry {
  item: KanbanItem;
  col: KanbanColumn;
}

export function JobInterviewsTab({
  jobId,
  jobTitle,
  columns,
  readOnly,
  columnsLoading = false,
  columnsError,
  columnsSuccess = true,
  onColumnsRetry,
}: JobInterviewsTabProps) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(
    null,
  );
  const [screeningFor, setScreeningFor] = useState<{
    stageId: number;
    name: string;
  } | null>(null);
  const [pendingTerminal, setPendingTerminal] = useState<{
    col: KanbanColumn;
    terminal: "rejected" | "withdrawn";
    entry: SelectedEntry;
  } | null>(null);

  // ── Kto jest u klienta ──────────────────────────────────────────────
  const interviewColumns = useMemo(
    () => columns.filter(isInterviewStage),
    [columns],
  );
  const entries = useMemo<SelectedEntry[]>(
    () =>
      interviewColumns.flatMap((col) =>
        col.items.map((item) => ({ item, col })),
      ),
    [interviewColumns],
  );
  // „Wcześniej u tego klienta" — kandydaci z wetem HM, którzy NIE stoją dziś
  // na etapie zewnętrznym. To jest sens tej listy: zobaczyć weto ZANIM ktoś
  // zaproponuje kandydata ponownie, a nie dostać 409 przy ruchu. Kandydat już
  // widoczny wyżej ma tam chip „weto" — powtórzenie go tutaj kazałoby czytać
  // jedną osobę jako dwie.
  const vetoedEntries = useMemo<SelectedEntry[]>(() => {
    const alreadyListed = new Set(entries.map((e) => e.item.candidate_id));
    return columns.flatMap((col) =>
      col.items
        .filter(
          (item) => Boolean(item.hm_veto) && !alreadyListed.has(item.candidate_id),
        )
        .map((item) => ({ item, col })),
    );
  }, [columns, entries]);

  const selected = useMemo<SelectedEntry | null>(() => {
    if (selectedCandidateId == null) return null;
    return (
      [...entries, ...vetoedEntries].find(
        (e) => e.item.candidate_id === selectedCandidateId,
      ) ?? null
    );
  }, [entries, vetoedEntries, selectedCandidateId]);

  // Pierwszy kandydat wybiera się sam — pusty środek przy niepustej liście
  // czyta się jak awaria, a nie jak „nic nie kliknąłeś".
  useEffect(() => {
    if (selectedCandidateId != null) return;
    if (entries.length > 0) setSelectedCandidateId(entries[0].item.candidate_id);
  }, [entries, selectedCandidateId]);

  // Kubełka „Poza szablonem" tu nie ma: backend zwraca go OSOBNYM polem
  // (`KanbanView.off_template`), a strona przekazuje wyłącznie `columns` —
  // czyli same kolumny szablonu, które wolno wskazać jako cel ruchu.
  const rejectedColumn = useMemo(
    () => columns.find((c) => terminalOf(c) === "rejected") ?? null,
    [columns],
  );
  const withdrawnColumn = useMemo(
    () => columns.find((c) => terminalOf(c) === "withdrawn") ?? null,
    [columns],
  );

  const stageLabel = useMemo(() => {
    const byDefId = new Map<number, string>();
    const byStage = new Map<string, string>();
    for (const col of columns) {
      if (col.stage_def_id != null) byDefId.set(col.stage_def_id, columnLabel(col));
      if (col.stage) byStage.set(col.stage, columnLabel(col));
    }
    return (row: { stage: string; stage_def_id?: number | null }) =>
      (row.stage_def_id != null ? byDefId.get(row.stage_def_id) : undefined) ??
      byStage.get(row.stage) ??
      row.stage;
  }, [columns]);

  // ── Werdykty hiring managera dla całej rekrutacji (jedno zapytanie) ──
  const feedbackQuery = useQuery<HiringManagerFeedback[]>({
    queryKey: ["hiring-manager-feedback", jobId],
    queryFn: () => hiringManagerFeedbackApi.list(jobId),
    staleTime: 30_000,
  });
  const feedbackByCandidate = useMemo(() => {
    const map = new Map<number, HiringManagerFeedback>();
    for (const row of feedbackQuery.data ?? []) {
      if (!map.has(row.candidate_id)) map.set(row.candidate_id, row);
    }
    return map;
  }, [feedbackQuery.data]);

  const reasonsQuery = useQuery<RejectionReasonOption[]>({
    queryKey: ["job-rejection-reasons", jobId],
    queryFn: () => loadJobRejectionReasons(jobId),
    staleTime: 5 * 60_000,
  });
  const rejectionReasons = reasonsQuery.data ?? [];

  // ── Ruch bez dialogu — ta sama trasa co drag&drop na tablicy ─────────
  const moveMutation = useMutation({
    mutationFn: (vars: { item: KanbanItem; col: KanbanColumn }) =>
      api.post("/api/pipeline/move", {
        candidate_id: vars.item.candidate_id,
        job_id: jobId,
        stage: vars.col.stage,
        stage_def_id: vars.col.stage_def_id ?? undefined,
      }),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      showSuccess(`Przeniesiono na etap „${columnLabel(vars.col)}”.`);
    },
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się przenieść"),
  });

  const terminalMutation = useMutation({
    mutationFn: (vars: {
      item: KanbanItem;
      col: KanbanColumn;
      reasonId: string;
      notes: string;
      sendRejectionEmail: boolean | null;
      offerResponse: CandidateOfferResponse | null;
      freeReason?: string;
    }) =>
      api.post("/api/pipeline/move", {
        candidate_id: vars.item.candidate_id,
        job_id: jobId,
        stage: vars.col.stage,
        stage_def_id: vars.col.stage_def_id ?? undefined,
        rejection_reason_id: vars.reasonId || undefined,
        rejection_reason: vars.freeReason || undefined,
        notes: vars.notes,
        send_rejection_email: vars.sendRejectionEmail ?? undefined,
        candidate_offer_response: vars.offerResponse ?? undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      setPendingTerminal(null);
      showSuccess("Zapisano decyzję.");
    },
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się zapisać"),
  });

  const listViewState = resolveViewState({
    isLoading: columnsLoading,
    isError: Boolean(columnsError),
    error: columnsError,
    isEmpty: entries.length === 0,
    isSuccess: columnsSuccess,
  });
  const listBlocked = isBlockingViewState(listViewState);

  const moveTargets = selected
    ? buildDecisionMoveTargets({
        item: selected.item,
        currentColId: colId(selected.col),
        columns,
        readOnly,
        colIdOf: colId,
      })
    : [];

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
      {/* ── Lewa kolumna: u klienta + weta ─────────────────────────── */}
      <aside className="space-y-4">
        <section className="rounded-xl border border-border bg-card p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold text-foreground">U klienta</h3>
            <Badge variant="outline" size="sm" className="tabular-nums">
              {entries.length}
            </Badge>
          </div>
          <p className="mb-2 text-[11px] text-muted-foreground">
            Etapy zewnętrzne tego szablonu.
          </p>
          {listViewState === "loading" ? (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
            </div>
          ) : listBlocked ? (
            <QueryStateNotice
              state={listViewState as "forbidden" | "not_found" | "error"}
              description={
                listViewState === "error"
                  ? "Nie udało się wczytać pipeline'u tej rekrutacji. Kandydaci nie zniknęli — to nieudane pobranie."
                  : undefined
              }
              onRetry={listViewState === "error" ? onColumnsRetry : undefined}
            />
          ) : listViewState === "empty" ? (
            <p className="text-xs text-muted-foreground">
              Nikt nie jest jeszcze u klienta.
            </p>
          ) : (
            <ul className="space-y-1">
              {entries.map(({ item, col }) => {
                const active = item.candidate_id === selectedCandidateId;
                const feedback = feedbackByCandidate.get(item.candidate_id);
                return (
                  <li key={item.candidate_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedCandidateId(item.candidate_id)}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "w-full rounded-lg border px-2 py-1.5 text-left text-xs transition-colors",
                        active
                          ? "border-primary bg-primary/5 text-foreground"
                          : "border-border bg-background text-muted-foreground hover:bg-muted",
                      )}
                    >
                      <span className="block truncate font-medium text-foreground">
                        {`${item.name ?? ""} ${item.lastname ?? ""}`.trim() ||
                          "Kandydat"}
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-1">
                        <span className="truncate">{columnLabel(col)}</span>
                        {feedback ? (
                          <Badge size="sm" variant="soft">
                            feedback
                          </Badge>
                        ) : null}
                        {item.hm_veto ? (
                          <Badge size="sm" variant="danger">
                            weto
                          </Badge>
                        ) : null}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-border bg-card p-3">
          <h3 className="mb-1 text-xs font-semibold text-foreground">
            Wcześniej u tego klienta
          </h3>
          {vetoedEntries.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">
              Nikt z tej rekrutacji nie ma weta hiring managera.
            </p>
          ) : (
            <ul className="space-y-1">
              {vetoedEntries.map(({ item }) => (
                <li key={`veto-${item.candidate_id}`}>
                  <button
                    type="button"
                    onClick={() => setSelectedCandidateId(item.candidate_id)}
                    className="w-full rounded-lg border border-destructive/40 bg-destructive-muted/40 px-2 py-1.5 text-left text-xs"
                    title={item.hm_veto?.rejection_reason_name ?? undefined}
                  >
                    <span className="block truncate font-medium text-foreground">
                      {`${item.name ?? ""} ${item.lastname ?? ""}`.trim() ||
                        "Kandydat"}
                    </span>
                    <span className="inline-flex items-center gap-1 text-destructive-muted-foreground">
                      <UserX className="h-3 w-3" /> weto HM
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] text-muted-foreground">
            Weto blokuje ponowne „CV Wysłane” i „Interview Klient” u tego
            managera — 409 z powodem, nie do nadpisania.
          </p>
        </section>
      </aside>

      {/* ── Środek: karta rozmowy ──────────────────────────────────── */}
      <section className="min-w-0 space-y-4">
        {listBlocked ? null : listViewState === "empty" ? (
          <EmptyState
            icon={CalendarClock}
            title="Nikt nie jest jeszcze u klienta"
            description="Ten krok zbiera kandydatów na etapach zewnętrznych — Interview Klient, Akceptacja, Negocjacje. Przenieś kogoś na tablicy pipeline'u, żeby zobaczyć tu kartę rozmowy."
          />
        ) : selected ? (
          <InterviewCard
            // Werdykt dociąga się osobnym zapytaniem PO zamontowaniu karty.
            // Bez `feedback?.id` w kluczu formularz zostałby z domyślnymi
            // wartościami i pokazywał „do uzupełnienia" nad zapisanym już
            // werdyktem — pola formularza czyta `useState` raz, przy montażu.
            key={`${selected.item.candidate_id}:${feedbackByCandidate.get(selected.item.candidate_id)?.id ?? "none"}`}
            jobId={jobId}
            jobTitle={jobTitle}
            entry={selected}
            readOnly={readOnly}
            reasons={rejectionReasons}
            reasonsLoading={reasonsQuery.isLoading}
            feedback={feedbackByCandidate.get(selected.item.candidate_id) ?? null}
            feedbackQueryState={resolveViewState({
              isLoading: feedbackQuery.isLoading,
              isError: feedbackQuery.isError,
              error: feedbackQuery.error,
              isSuccess: feedbackQuery.isSuccess,
            })}
            onFeedbackRetry={() => void feedbackQuery.refetch()}
            onOpenScreening={(stageId, name) =>
              setScreeningFor({ stageId, name })
            }
          />
        ) : null}
      </section>

      {/* ── Dok „Decyzja" ──────────────────────────────────────────── */}
      <aside className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-4 xl:self-start">
        {listBlocked ? null : selected ? (
          <InterviewDecisionDock
            key={selected.item.candidate_id}
            item={selected.item}
            jobId={jobId}
            jobTitle={jobTitle}
            currentStageLabel={columnLabel(selected.col)}
            moveTargets={moveTargets}
            readOnly={readOnly}
            onClose={() => setSelectedCandidateId(null)}
            onMoveTo={(col) =>
              moveMutation.mutate({ item: selected.item, col })
            }
            onTerminal={(col, terminal) =>
              setPendingTerminal({ col, terminal, entry: selected })
            }
            rejectedColumn={rejectedColumn}
            withdrawnColumn={withdrawnColumn}
            stageLabel={stageLabel}
          />
        ) : (
          <InterviewDecisionDockEmpty />
        )}
      </aside>

      {screeningFor && (
        <ScreeningSheet
          open
          onOpenChange={(o) => !o && setScreeningFor(null)}
          stageId={screeningFor.stageId}
          candidateName={screeningFor.name}
        />
      )}

      {pendingTerminal && (
        <RejectionV2
          open
          onOpenChange={(o) => !o && setPendingTerminal(null)}
          terminalType={pendingTerminal.terminal}
          reasons={rejectionReasons}
          previousStageCategory={
            pendingTerminal.entry.col.category === "external"
              ? "external"
              : pendingTerminal.entry.col.category === "internal"
                ? "internal"
                : null
          }
          previousStage={pendingTerminal.entry.col.stage}
          onConfirm={(
            reasonId,
            notes,
            sendRejectionEmail,
            offerResponse,
            freeReason,
          ) =>
            terminalMutation.mutate({
              item: pendingTerminal.entry.item,
              col: pendingTerminal.col,
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

// ── Karta rozmowy ───────────────────────────────────────────────────────────

interface InterviewCardProps {
  jobId: number;
  jobTitle?: string;
  entry: SelectedEntry;
  readOnly: boolean;
  reasons: RejectionReasonOption[];
  reasonsLoading: boolean;
  feedback: HiringManagerFeedback | null;
  feedbackQueryState: ReturnType<typeof resolveViewState>;
  onFeedbackRetry: () => void;
  onOpenScreening: (stageId: number, name: string) => void;
}

function InterviewCard({
  jobId,
  jobTitle,
  entry,
  readOnly,
  reasons,
  reasonsLoading,
  feedback,
  feedbackQueryState,
  onFeedbackRetry,
  onOpenScreening,
}: InterviewCardProps) {
  const { item, col } = entry;
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const fullName =
    `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";

  const [decision, setDecision] = useState<HiringManagerDecision>(
    feedback?.decision === "advance" ||
      feedback?.decision === "reject" ||
      feedback?.decision === "on_hold"
      ? feedback.decision
      : "advance",
  );
  const [reasonId, setReasonId] = useState<string>(
    feedback?.rejection_reason_id ? String(feedback.rejection_reason_id) : "",
  );
  const [note, setNote] = useState<string>(feedback?.note ?? "");

  const rejectedReasons = reasons.filter((r) =>
    r.applies_to.includes("rejected"),
  );
  const chosenReason = rejectedReasons.find((r) => r.id === reasonId) ?? null;

  const saveMutation = useMutation({
    mutationFn: () =>
      hiringManagerFeedbackApi.record(jobId, {
        candidate_id: item.candidate_id,
        decision,
        rejection_reason_id: reasonId ? Number(reasonId) : null,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["hiring-manager-feedback", jobId],
      });
      showSuccess("Zapisano feedback klienta.");
    },
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się zapisać"),
  });

  // Screening Championa — skrót wyniku i link dla klienta.
  const screeningQuery = useQuery({
    queryKey: ["pipeline-stage-screening", item.id],
    queryFn: () => screeningApi.getForStage(item.id).then((r) => r.data),
    staleTime: 30_000,
  });
  const answers = screeningQuery.data?.screening_answers ?? null;

  const shareMutation = useMutation({
    mutationFn: () => screeningApi.createShareToken(item.id, 30),
    onSuccess: (res) => {
      const url = `${window.location.origin}${res.data.share_url_suffix}`;
      void navigator.clipboard?.writeText(url).catch(() => undefined);
      showSuccess("Link do karty Championa skopiowany (ważny 30 dni).");
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się utworzyć linku"),
  });

  return (
    <div className="space-y-4">
      {/* Nagłówek karty */}
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold tracking-wide text-primary uppercase">
              Rozmowa u klienta
            </div>
            <h2 className="truncate text-base font-semibold text-foreground">
              {fullName}
            </h2>
            <p className="text-xs text-muted-foreground">
              {columnLabel(col)}
              {item.days_in_stage != null
                ? ` · ${item.days_in_stage} ${item.days_in_stage === 1 ? "dzień" : "dni"} na etapie`
                : ""}
              {jobTitle ? ` · ${jobTitle}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {item.hm_veto ? (
              <Badge variant="danger" size="sm">
                <UserX className="h-2.5 w-2.5" /> Weto HM
              </Badge>
            ) : (
              <Badge variant="soft" size="sm">
                Weto HM: brak
              </Badge>
            )}
            {item.verification_status === "pending" && (
              <Badge variant="warning" size="sm">
                Pending
              </Badge>
            )}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          <Link
            href={`/jobs/${jobId}/prep/${item.candidate_id}`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
          >
            <Sparkles className="h-3.5 w-3.5" /> Prep-kit (AI)
          </Link>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onOpenScreening(item.id, fullName)}
          >
            <FileText className="h-3.5 w-3.5" /> Screening Championa
          </Button>
          {!readOnly && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => shareMutation.mutate()}
              loading={shareMutation.isPending}
              title="Link do karty Championa dla klienta — ważny 30 dni"
            >
              <Link2 className="h-3.5 w-3.5" /> Link dla klienta
            </Button>
          )}
        </div>

        <div className="mt-3 rounded-lg border border-border bg-muted/20 p-3 text-xs">
          {screeningQuery.isLoading ? (
            <span className="inline-flex items-center gap-1.5 text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie
              screeningu…
            </span>
          ) : answers ? (
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                size="sm"
                variant={
                  answers.overall_fit === "fit"
                    ? "success"
                    : answers.overall_fit === "miss"
                      ? "danger"
                      : "warning"
                }
              >
                {answers.overall_fit === "fit"
                  ? "Pasuje"
                  : answers.overall_fit === "miss"
                    ? "Nie pasuje"
                    : "Niepewne"}
              </Badge>
              <span className="text-muted-foreground">
                Odpowiedziano na{" "}
                {countPl(
                  answers.answers.length,
                  "pytanie",
                  "pytania",
                  "pytań",
                )}
                {answers.answered_at
                  ? ` · ${formatDate(answers.answered_at)}`
                  : ""}
              </span>
              {answers.answers.some((a) => a.deal_breaker_hit) && (
                <span className="inline-flex items-center gap-1 text-destructive">
                  <AlertTriangle className="h-3 w-3" /> deal-breaker trafiony
                </span>
              )}
            </div>
          ) : (
            <span className="text-muted-foreground">
              Arkusz screeningu Championa nie jest jeszcze wypełniony dla tego
              etapu.
            </span>
          )}
        </div>
      </div>

      {/* Feedback klienta */}
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Feedback klienta po rozmowie
          </h3>
          {feedback ? (
            <Badge size="sm" variant="soft">
              zapisany
            </Badge>
          ) : (
            <Badge size="sm" variant="warning">
              do uzupełnienia
            </Badge>
          )}
        </div>

        {feedbackQueryState === "forbidden" ||
        feedbackQueryState === "not_found" ||
        feedbackQueryState === "error" ? (
          <QueryStateNotice
            state={feedbackQueryState}
            description={
              feedbackQueryState === "error"
                ? "Nie udało się wczytać zapisanych werdyktów. Zapisane wcześniej dane nie zniknęły — to nieudane pobranie."
                : undefined
            }
            onRetry={
              feedbackQueryState === "error" ? onFeedbackRetry : undefined
            }
          />
        ) : (
          <div className="space-y-3">
            <fieldset disabled={readOnly} className="space-y-3">
              <div className="space-y-1">
                <span className="text-xs font-semibold text-foreground">
                  Werdykt hiring managera
                </span>
                <div className="flex flex-wrap gap-1">
                  {DECISION_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setDecision(opt.value)}
                      aria-pressed={decision === opt.value}
                      className={cn(
                        "rounded-full border px-3 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                        decision === opt.value
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-background text-muted-foreground hover:bg-muted",
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1">
                <label
                  htmlFor="hm-reason"
                  className="text-xs font-semibold text-foreground"
                >
                  Powód (gdy odrzuca)
                </label>
                <select
                  id="hm-reason"
                  value={reasonId}
                  onChange={(e) => setReasonId(e.target.value)}
                  className="w-full rounded-md border border-border bg-card px-3 py-2 text-xs focus:ring-2 focus:ring-primary focus:outline-hidden"
                >
                  <option value="">
                    {reasonsLoading
                      ? "Wczytywanie słownika…"
                      : "— ze słownika szablonu —"}
                  </option>
                  {rejectedReasons.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label
                  htmlFor="hm-note"
                  className="text-xs font-semibold text-foreground"
                >
                  Notatka z feedbacku
                </label>
                <textarea
                  id="hm-note"
                  rows={3}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Co dokładnie powiedział klient…"
                  className="w-full rounded-md border border-border bg-card px-3 py-2 text-xs focus:ring-2 focus:ring-primary focus:outline-hidden"
                />
              </div>
            </fieldset>

            {/* Prawda o wecie — trzy różne zdania, nie jeden przełącznik. */}
            <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs">
              <div className="font-semibold text-foreground">
                Blokuje ponowne propozycje?
              </div>
              <p className="mt-1 text-muted-foreground">
                {chosenReason
                  ? chosenReason.disqualifies_person
                    ? "Ten powód jest werdyktem o osobie — weto powstanie, gdy kandydat zostanie odrzucony z tym powodem."
                    : "Ten powód opisuje sytuację, nie osobę — nie zablokuje kolejnych propozycji."
                  : "Wybierz powód, żeby zobaczyć, czy zablokuje kolejne propozycje temu managerowi."}
              </p>
              {feedback && feedback.veto_blockers.length > 0 && (
                <ul className="mt-2 list-inside list-disc space-y-0.5 text-muted-foreground">
                  {feedback.veto_blockers.map((blocker) => (
                    <li key={blocker}>{blocker}</li>
                  ))}
                </ul>
              )}
              {feedback?.veto_recorded && (
                <Badge size="sm" variant="danger" className="mt-2">
                  <UserX className="h-2.5 w-2.5" /> Weto stoi
                </Badge>
              )}
            </div>

            {!readOnly && (
              <div className="flex justify-end">
                <Button
                  size="sm"
                  onClick={() => saveMutation.mutate()}
                  loading={saveMutation.isPending}
                >
                  <Save className="h-3.5 w-3.5" /> Zapisz feedback
                </Button>
              </div>
            )}
            {readOnly && (
              <p className="text-[11px] text-muted-foreground">
                Tylko do odczytu — brak prawa zapisu w tym pipeline.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <Link
          href={`/candidates/${item.candidate_id}`}
          className="inline-flex items-center gap-1 hover:text-foreground"
        >
          <ExternalLink className="h-3 w-3" /> Pełny profil kandydata
        </Link>
      </div>
    </div>
  );
}
