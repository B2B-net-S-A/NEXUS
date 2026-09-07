"use client";

/**
 * ScreeningWorkbench — stanowisko screeningu (krok 05 programu „flow w języku
 * C2", docs/c2-flow-program.md, PR 6/7).
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
 * `…/stages/{id}/screening`, a ruch — `POST /api/pipeline/move` z
 * `expected_rate_*`, ten sam, którym przenosi karty `KanbanBoardV2`.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  ExternalLink,
  HelpCircle,
  Loader2,
  Save,
  Sparkles,
  UserX,
} from "lucide-react";

import {
  extractErrorMsg,
  interviewQuestionsApi,
  pipelineApi,
  type RateUnit,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import { Form } from "@/components/v2/forms";
import {
  ScreeningFormFields,
  ScreeningNoQuestions,
  ScreeningSubmitError,
  useScreeningForm,
} from "@/components/v2/screening/ScreeningForm";
import { VerifiedRateFields } from "@/components/v2/screening/VerifiedRateFields";
import { evaluateRateGate } from "@/lib/verified-rate-gate";
import {
  VERIFIED_STAGE,
  findStageColumn,
  itemFullName,
  moveBlockedReason,
  selectPendingVerifications,
  selectScreeningQueue,
  type FlowQueueEntry,
} from "@/lib/pipeline-flow";
import { countPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";
import { cn, formatDate } from "@/lib/utils";
import { encodeJobBackRef } from "@/lib/url-filters";
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
}

function daysLabel(n: number): string {
  return `${n} ${Math.abs(n) === 1 ? "dzień" : "dni"}`;
}

/** Wiersz kolejki — nazwisko, sygnał bramki, wiek na etapie. */
function QueueRow({
  entry,
  active,
  onSelect,
  trailing,
}: {
  entry: FlowQueueEntry;
  active: boolean;
  onSelect: () => void;
  trailing?: string;
}) {
  const { item } = entry;
  const blocked = Boolean(item.hm_veto);
  const pending = item.verification_status === "pending";
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? "true" : undefined}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
        active
          ? "bg-primary/10 font-medium text-primary"
          : "text-foreground hover:bg-accent",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          blocked ? "bg-destructive" : pending ? "bg-warning" : "bg-primary",
        )}
      />
      <span className="min-w-0 flex-1 truncate">{itemFullName(item)}</span>
      {trailing ? (
        <span className="shrink-0 tabular-nums text-muted-foreground">
          {trailing}
        </span>
      ) : null}
    </button>
  );
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
}: ScreeningWorkbenchProps) {
  const { showSuccess, showError } = useToast();

  const queue = useMemo(() => selectScreeningQueue(columns), [columns]);
  const pendingQueue = useMemo(
    () => selectPendingVerifications(columns),
    [columns],
  );
  const verifiedCol = useMemo(
    () => findStageColumn(columns, VERIFIED_STAGE),
    [columns],
  );

  const [selectedStageId, setSelectedStageId] = useState<number | null>(null);
  // Pierwsze wejście (i zniknięcie wybranej karty po ruchu) wybiera pierwszą
  // pozycję kolejki. Bez tego stanowisko startuje puste, mimo że ktoś czeka.
  useEffect(() => {
    if (queue.length === 0) {
      setSelectedStageId(null);
      return;
    }
    setSelectedStageId((prev) =>
      prev != null && queue.some((e) => e.item.id === prev)
        ? prev
        : queue[0].item.id,
    );
  }, [queue]);

  const selected = queue.find((e) => e.item.id === selectedStageId) ?? null;

  // ── Stawka (dok) — resetowana przy zmianie kandydata ────────────────────
  const [rate, setRate] = useState("");
  const [unit, setUnit] = useState<RateUnit>("hourly");
  useEffect(() => {
    setRate("");
    setUnit("hourly");
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
  const answeredCount = screening.questions.filter((q) =>
    (screening.methods.watch(`answers.${q.id}.response`) ?? "").trim(),
  ).length;
  const dealBreakerHit = screening.questions.some((q) =>
    screening.methods.watch(`answers.${q.id}.deal_breaker_hit`),
  );

  // ── Pytania przypięte do rekrutacji (zakładka „Baza pytań") ─────────────
  const pinnedQuery = useQuery({
    queryKey: ["job-questions", jobId],
    queryFn: () => interviewQuestionsApi.listForJob(jobId).then((r) => r.data),
    staleTime: 60_000,
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
      return res.data as { verification_status?: "active" | "pending" };
    },
    onSuccess: (data) => {
      if (data?.verification_status === "pending") {
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

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
      {/* ── Lewa kolumna: kolejki i źródła pytań ───────────────────────── */}
      <aside className="space-y-4 self-start rounded-xl border border-border bg-card p-4">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <ClipboardCheck className="h-4 w-4 text-primary" />
          Kolejka screeningu
          <Badge variant="outline" size="sm" className="ml-auto tabular-nums">
            {queue.length}
          </Badge>
        </div>

        {queue.length > 0 ? (
          <div className="space-y-0.5" role="list" aria-label="Kolejka screeningu">
            {queue.map((entry) => (
              <div key={entry.item.id} role="listitem">
                <QueueRow
                  entry={entry}
                  active={entry.item.id === selectedStageId}
                  onSelect={() => setSelectedStageId(entry.item.id)}
                  trailing={
                    entry.item.days_in_stage != null
                      ? `${entry.item.days_in_stage} d`
                      : undefined
                  }
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

        <div className="border-t border-border pt-3">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Czeka na akceptację stawki
          </div>
          {pendingQueue.length > 0 ? (
            <div className="space-y-0.5">
              {pendingQueue.map((entry) => (
                <QueueRow
                  key={entry.item.id}
                  entry={entry}
                  active={false}
                  onSelect={() => setSelectedStageId(entry.item.id)}
                  trailing={
                    entry.item.expected_rate_value != null
                      ? `${entry.item.expected_rate_value} ${entry.item.expected_rate_currency ?? "PLN"}`
                      : "pending"
                  }
                />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Nikt nie czeka na akceptację stawki.
            </p>
          )}
          <Link
            href="/pending-verifications"
            className="mt-2 inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" /> Kolejka akceptacji (globalna)
          </Link>
        </div>

        <div className="border-t border-border pt-3">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Pytania do rozmowy
          </div>
          <ul className="space-y-1 text-xs text-muted-foreground">
            <li className="flex items-center justify-between gap-2">
              <span>Z Championa (sekcja 5)</span>
              <span className="tabular-nums text-foreground">
                {selected ? screening.questions.length : "—"}
              </span>
            </li>
            <li className="flex items-center justify-between gap-2">
              <span>Przypięte do rekrutacji</span>
              <span className="tabular-nums text-foreground">
                {pinnedQuery.isLoading
                  ? "…"
                  : pinnedQuery.isError
                    ? "—"
                    : (pinnedQuery.data?.length ?? 0)}
              </span>
            </li>
          </ul>
          <div className="mt-2 flex flex-col gap-1">
            <button
              type="button"
              onClick={() => onTabChange("questions")}
              className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
            >
              <BookOpen className="h-3 w-3" /> Baza pytań tej rekrutacji
            </button>
            {selected && (
              // Prep-kit istniał od dawna pod adresem, do którego NIC nie
              // linkowało — stanowisko screeningu jest jego naturalnym wejściem.
              <Link
                href={`/jobs/${jobId}/prep/${selected.item.candidate_id}`}
                className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
              >
                <Sparkles className="h-3 w-3" /> Prep-kit (AI) dla tej rozmowy
              </Link>
            )}
          </div>
        </div>
      </aside>

      {/* ── Środek: arkusz screeningu ───────────────────────────────────── */}
      <div className="min-w-0">
        {!selected ? (
          <div className="rounded-xl border border-dashed border-border bg-muted/20 p-8 text-center text-sm text-muted-foreground">
            <ClipboardCheck className="mx-auto mb-2 h-6 w-6 opacity-40" />
            {queue.length === 0
              ? "Kolejka screeningu jest pusta — nikt nie czeka dziś na rozmowę."
              : "Wybierz kandydata z kolejki po lewej."}
          </div>
        ) : (
          <div className="rounded-xl border border-border bg-card">
            <div className="space-y-2 border-b border-border p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-foreground">
                  Screening · {itemFullName(selected.item)}
                </h2>
                {selected.item.days_in_stage != null && (
                  <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    {daysLabel(selected.item.days_in_stage)} na etapie
                  </span>
                )}
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
                <Link
                  href={`/candidates/${selected.item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
                  className="ml-auto inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <ExternalLink className="h-3 w-3" /> Pełny profil
                </Link>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>
                  {screening.questions.length > 0
                    ? `${answeredCount} z ${countPl(screening.questions.length, "pytania", "pytań", "pytań")} odpowiedzianych`
                    : "Brak pytań Championa"}
                </span>
                {screeningSaved?.answered_at && (
                  <span>
                    · zapisano {formatDate(screeningSaved.answered_at)}
                  </span>
                )}
                {dealBreakerHit && (
                  <span className="inline-flex items-center gap-1 text-destructive">
                    <AlertTriangle className="h-3 w-3" /> deal-breaker zaznaczony —
                    wynik screeningu spadnie do 0
                  </span>
                )}
              </div>
            </div>

            <div className="p-4">
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
                <ScreeningNoQuestions />
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
          </div>
        )}
      </div>

      {/* ── Dok: weryfikacja stawki i decyzja ───────────────────────────── */}
      <aside className="lg:col-span-2 xl:sticky xl:top-4 xl:col-span-1 xl:self-start">
        <div className="space-y-4 rounded-xl border border-border bg-card p-4">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-primary">
              Weryfikacja
            </div>
            <div className="truncate text-sm font-semibold text-foreground">
              {selected ? itemFullName(selected.item) : "Nikt nie wybrany"}
            </div>
          </div>

          {selected ? (
            <>
              <div className="space-y-2">
                <div className="text-xs font-semibold text-foreground">
                  Stawka oczekiwana
                </div>
                <VerifiedRateFields
                  rate={rate}
                  onRateChange={setRate}
                  unit={unit}
                  onUnitChange={setUnit}
                  gate={gate}
                  disabled={readOnly}
                  idPrefix="screening-dock-rate"
                />
              </div>

              <div className="space-y-1.5 border-t border-border pt-3">
                <div className="text-xs font-semibold text-foreground">
                  Wynik screeningu
                </div>
                {screeningSaved ? (
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-muted-foreground">Ocena ogólna</span>
                    <Badge
                      size="sm"
                      variant={
                        screeningSaved.overall_fit === "fit"
                          ? "success"
                          : screeningSaved.overall_fit === "miss"
                            ? "danger"
                            : "warning"
                      }
                    >
                      {screeningSaved.overall_fit === "fit"
                        ? "Pasuje"
                        : screeningSaved.overall_fit === "miss"
                          ? "Nie pasuje"
                          : "Niepewne"}
                    </Badge>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Arkusz jeszcze niezapisany dla tego etapu.
                  </p>
                )}
                {screeningDirty && (
                  <p className="inline-flex items-start gap-1 text-xs text-warning-muted-foreground">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                    Masz niezapisane odpowiedzi w arkuszu.
                  </p>
                )}
              </div>

              {!readOnly && (
                <div className="space-y-1.5 border-t border-border pt-3">
                  <Button
                    className="w-full justify-center"
                    disabled={Boolean(moveBlocked) || moveMut.isPending}
                    loading={moveMut.isPending}
                    title={moveBlocked ?? undefined}
                    onClick={() => moveMut.mutate()}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Zweryfikowany — zapisz stawkę i przenieś
                  </Button>
                  {moveBlocked && (
                    <p className="text-[11px] text-muted-foreground">
                      {moveBlocked}
                    </p>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              Wybierz kandydata z kolejki, żeby wpisać stawkę i zamknąć
              weryfikację.
            </p>
          )}

          <p className="border-t border-border pt-3 text-[11px] text-muted-foreground">
            Odrzucenie z powodem, etapy terminalne i pozostałe ruchy zostają na
            tablicy Pipeline — ten ekran domyka wyłącznie screening
            i weryfikację stawki.
          </p>
        </div>
      </aside>
    </div>
  );
}
