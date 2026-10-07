"use client";

/**
 * Krok 07 „Rozmowy i decyzja" — program „flow w języku C2" (PR 7/7).
 *
 * Zbiera w jednym miejscu to, co dziś jest rozrzucone: kto jest u klienta
 * (kanban), prep-kit (własna strona), formularz screeningu (okno), weto
 * hiring managera (chip na karcie + 409 przy ruchu) i decyzję (modale
 * odrzucenia). Żadna z tych rzeczy nie znika ze swojego miejsca — ta
 * zakładka je CYTUJE i linkuje.
 *
 * 0424 (D2, 07.10.2026): z NEXUSA nic nie idzie do klienta — przycisk
 * „Karta Championa dla klienta” i link 30-dniowy zniknęły (serwer odpowiada
 * na tworzenie linku 410).
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
  Loader2,
  Save,
  Sparkles,
  UserX,
  Users,
} from "lucide-react";

import type { WorkbenchPanelProps } from "@/components/v2/recruitment/types";
import {
  extractErrorMsg,
  hiringManagerFeedbackApi,
  screeningApi,
  type HiringManagerDecision,
  type HiringManagerFeedback,
  type HiringManagerFeedbackList,
} from "@/lib/api";
import { expectedStateVersionOf } from "@/lib/pipeline-version-conflict";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { itemFullName } from "@/lib/pipeline-flow";
import { useToast } from "@/components/Toast";
import { useCapability } from "@/hooks/useCapability";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, QueryStateNotice } from "@/components/ds";
import { cn, formatDate } from "@/lib/utils";
import { countPl } from "@/lib/plural-pl";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { terminalOf } from "@/lib/kanban-terminal";
import { rejectionEmailAvailableFrom } from "@/lib/rejection-email";
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
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { PrepInviteModal } from "@/components/v2/modals/PrepInviteModal";
import {
  RejectionV2,
  type CandidateOfferResponse,
} from "@/components/v2/modals/RejectionV2";
import {
  InterviewDecisionDock,
  InterviewDecisionDockEmpty,
  buildDecisionMoveTargets,
} from "@/components/v2/jobs/InterviewDecisionDock";
import {
  RailRow,
  RailSection,
  ToolPill,
  WorkbenchCard,
  WorkbenchHeader,
  WorkbenchRail,
} from "@/components/v2/jobs/workbench-chrome";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";

const DECISION_OPTIONS: { value: HiringManagerDecision; label: string }[] = [
  { value: "advance", label: "Dalej" },
  { value: "on_hold", label: "Druga rozmowa" },
  { value: "reject", label: "Odrzuca" },
];

/**
 * `layout="panel"` (rekrutacja v3): bez listy „Rozmowy u klienta" — karta
 * rozmowy i dok decyzji JEDNEJ osoby (`focusCandidateId`) w jednej kolumnie.
 */
export interface JobInterviewsTabProps extends WorkbenchPanelProps {
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
  /** Budżet PLN/h rekrutacji — ta sama kwota co nagłówek (`jobBudgetHourly`). */
  budgetHourly?: number | null;
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
  budgetHourly = null,
  layout = "full",
  focusCandidateId = null,
}: JobInterviewsTabProps) {
  const isPanel = layout === "panel";
  const { showSuccess, showError } = useToast();
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(
    null,
  );
  const [screeningFor, setScreeningFor] = useState<{
    candidateId: number;
    name: string;
  } | null>(null);
  const [showOriginalCv, setShowOriginalCv] = useState(false);
  const [prepInviteOpen, setPrepInviteOpen] = useState(false);
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

  // W panelu wybór jest STEROWANY z zewnątrz (`focusCandidateId`) — ten sam
  // zbiór osób, które pełny układ pozwala kliknąć (etapy klienta + weta HM).
  const activeCandidateId = isPanel ? focusCandidateId : selectedCandidateId;
  const selected = useMemo<SelectedEntry | null>(() => {
    if (activeCandidateId == null) return null;
    return (
      [...entries, ...vetoedEntries].find(
        (e) => e.item.candidate_id === activeCandidateId,
      ) ?? null
    );
  }, [entries, vetoedEntries, activeCandidateId]);

  // Pierwszy kandydat wybiera się sam — pusty środek przy niepustej liście
  // czyta się jak awaria, a nie jak „nic nie kliknąłeś".
  // …i wybór NIE może wskazywać osoby, której już nie ma w kolejce: po
  // decyzji (ruch poza etapy zewnętrzne, odrzucenie) invalidacja kanbana
  // usuwa ją z `entries`, a stary id zostawiałby pusty środek i pusty dok.
  useEffect(() => {
    const stillListed =
      selectedCandidateId != null &&
      [...entries, ...vetoedEntries].some(
        (e) => e.item.candidate_id === selectedCandidateId,
      );
    if (stillListed) return;
    setSelectedCandidateId(entries[0]?.item.candidate_id ?? null);
  }, [entries, vetoedEntries, selectedCandidateId]);

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
  const feedbackQuery = useQuery<HiringManagerFeedbackList>({
    queryKey: ["hiring-manager-feedback", jobId],
    queryFn: () => hiringManagerFeedbackApi.list(jobId),
    staleTime: 30_000,
  });
  const feedbackByCandidate = useMemo(() => {
    const map = new Map<number, HiringManagerFeedback>();
    for (const row of feedbackQuery.data?.items ?? []) {
      if (!map.has(row.candidate_id)) map.set(row.candidate_id, row);
    }
    return map;
  }, [feedbackQuery.data]);
  // Czy zapis werdyktu przejdzie na serwerze — `null`, dopóki nie wiadomo.
  const canRecordOnServer = feedbackQuery.data
    ? feedbackQuery.data.can_record
    : null;

  const reasonsQuery = useQuery<RejectionReasonOption[]>({
    queryKey: ["job-rejection-reasons", jobId],
    queryFn: () => loadJobRejectionReasons(jobId),
    staleTime: 5 * 60_000,
  });
  const rejectionReasons = reasonsQuery.data ?? [];

  // ── Ruch bez dialogu — ta sama droga co drag&drop na tablicy ─────────
  // Rdzeń ruchu (`usePipelineMoveCore`) obsługuje ostrzeżenie „Przenieś mimo
  // to”, wymóg debriefu po rozmowie u klienta i konflikt wersji.
  const moveCore = usePipelineMoveCore({ jobId });
  const moveMutation = useMutation({
    mutationFn: (vars: { item: KanbanItem; col: KanbanColumn }) =>
      moveCore.send(
        {
          candidate_id: vars.item.candidate_id,
          job_id: jobId,
          stage: vars.col.stage,
          stage_def_id: vars.col.stage_def_id ?? undefined,
          expected_state_version: expectedStateVersionOf(vars.item),
        },
        {
          candidateName: itemFullName(vars.item),
          fallbackMessage: "Nie udało się przenieść",
        },
      ),
    onSuccess: (outcome, vars) => {
      if (outcome.ok) showSuccess(`Przeniesiono na etap „${columnLabel(vars.col)}”.`);
    },
    onError: (e) => {
      showError(extractErrorMsg(e) || "Nie udało się przenieść");
    },
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
      moveCore.send(
        {
          candidate_id: vars.item.candidate_id,
          job_id: jobId,
          stage: vars.col.stage,
          stage_def_id: vars.col.stage_def_id ?? undefined,
          rejection_reason_id: vars.reasonId || undefined,
          rejection_reason: vars.freeReason || undefined,
          notes: vars.notes,
          send_rejection_email: vars.sendRejectionEmail ?? undefined,
          candidate_offer_response: vars.offerResponse ?? undefined,
          expected_state_version: expectedStateVersionOf(vars.item),
        },
        {
          candidateName: itemFullName(vars.item),
          fallbackMessage: "Nie udało się zapisać",
        },
      ),
    onSuccess: (outcome) => {
      if (!outcome.ok) {
        if (outcome.refusal.kind === "version_conflict") setPendingTerminal(null);
        return;
      }
      setPendingTerminal(null);
      // Mail odrzucenia („Cofnij wysyłkę”) ogłasza rdzeń ruchu.
      showSuccess("Zapisano decyzję.");
    },
    onError: (e) => {
      showError(extractErrorMsg(e) || "Nie udało się zapisać");
    },
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

  const interviewCard = !selected ? null : (
          <InterviewCard
            // Werdykt dociąga się osobnym zapytaniem PO zamontowaniu karty.
            // Bez `feedback?.id` w kluczu formularz zostałby z domyślnymi
            // wartościami i pokazywał „do uzupełnienia" nad zapisanym już
            // werdyktem — pola formularza czyta `useState` raz, przy montażu.
            key={`${selected.item.candidate_id}:${feedbackByCandidate.get(selected.item.candidate_id)?.id ?? "none"}`}
            jobId={jobId}
            layout={layout}
            jobTitle={jobTitle}
            entry={selected}
            readOnly={readOnly}
            reasons={rejectionReasons}
            reasonsLoading={reasonsQuery.isLoading}
            feedback={feedbackByCandidate.get(selected.item.candidate_id) ?? null}
            budgetHourly={budgetHourly}
            canRecord={canRecordOnServer}
            feedbackQueryState={resolveViewState({
              isLoading: feedbackQuery.isLoading,
              isError: feedbackQuery.isError,
              error: feedbackQuery.error,
              isSuccess: feedbackQuery.isSuccess,
            })}
            onFeedbackRetry={() => void feedbackQuery.refetch()}
            onOpenScreening={(candidateId, name) =>
              setScreeningFor({ candidateId, name })
            }
          />
  );
  const decisionDock = !selected ? null : (
          <InterviewDecisionDock
            key={selected.item.candidate_id}
            item={selected.item}
            jobId={jobId}
            layout={layout}
            jobTitle={jobTitle}
            budgetHourly={budgetHourly}
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
  );
  const modals = (
    <>
      {screeningFor && (
        <ScreeningSheet
          open
          onOpenChange={(o) => !o && setScreeningFor(null)}
          candidateId={screeningFor.candidateId}
          jobId={jobId}
          candidateName={screeningFor.name}
          jobBudgetHourly={budgetHourly}
          readOnly={readOnly}
        />
      )}

      {selected && showOriginalCv && (
        <CVOriginalPreviewModal
          open
          onOpenChange={setShowOriginalCv}
          stageId={selected.item.id}
          jobTitle={jobTitle?.trim() || `Rekrutacja #${jobId}`}
          candidateName={
            `${selected.item.name ?? ""} ${selected.item.lastname ?? ""}`.trim() ||
            "Kandydat"
          }
        />
      )}

      {selected && prepInviteOpen && (
        <PrepInviteModal
          open
          onOpenChange={setPrepInviteOpen}
          candidateName={
            `${selected.item.name ?? ""} ${selected.item.lastname ?? ""}`.trim() ||
            "Kandydat"
          }
          onToast={(message, type) =>
            type === "error" ? showError(message) : showSuccess(message)
          }
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
          // Runda 10 (R10-V2-1): ta sama reguła dostępności maila co na
          // Tablicy (kod etapu albo kolumna), nie sama kategoria kolumny.
          emailAvailable={rejectionEmailAvailableFrom(pendingTerminal.entry.col)}
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
    </>
  );

  if (isPanel) {
    if (listViewState === "loading") {
      return (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
        </div>
      );
    }
    if (listBlocked) {
      return (
        <QueryStateNotice
          state={listViewState as "forbidden" | "not_found" | "error"}
          description={
            listViewState === "error"
              ? "Nie udało się wczytać pipeline'u tej rekrutacji. Kandydaci nie zniknęli — to nieudane pobranie."
              : undefined
          }
          onRetry={listViewState === "error" ? onColumnsRetry : undefined}
        />
      );
    }
    if (!selected) {
      return (
        <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
          Rozmowy i decyzja klienta są dostępne na etapach u klienta (Interview
          Klient, Akceptacja, Negocjacje). Ta osoba jest dziś na innym etapie
          tej rekrutacji.
        </p>
      );
    }
    return (
      <div className="flex min-w-0 flex-col gap-3">
        {moveCore.dialogs}
        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant="outline"
            title="Podgląd CV oryginalnego z momentu zgłoszenia (snapshot etapu)"
            onClick={() => setShowOriginalCv(true)}
          >
            <FileText className="h-3.5 w-3.5" /> Pokaż CV obok
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPrepInviteOpen(true)}
          >
            <CalendarClock className="h-3.5 w-3.5" /> Zaproszenie prep (.ics +
            CV)
          </Button>
        </div>
        {interviewCard}
        {decisionDock}
        {modals}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
      {moveCore.dialogs}
      {/* ── Szyna: u klienta, weta i przygotowanie ─────────────────── */}
      <WorkbenchRail
        icon={<Users className="h-4 w-4 text-primary" />}
        // „Rozmowy u klienta" (M03-B12): liczy etapy kroku 07, bez „CV wysłane"
        // i bez etapów umowy — to NIE jest grupa „U klienta (CV → interview)"
        // z szyny Pipeline'u. Etykieta = KPI jobbara i licznik listwy kroków.
        title="Rozmowy u klienta"
        count={entries.length}
        meta="etapy zewnętrzne"
        footer={
          <Button
            size="sm"
            variant="outline"
            className="justify-center"
            disabled={!selected}
            title={
              selected
                ? "Podgląd CV oryginalnego z momentu zgłoszenia (snapshot etapu)"
                : "Wybierz kandydata z listy"
            }
            onClick={() => setShowOriginalCv(true)}
          >
            <FileText className="h-3.5 w-3.5" /> Pokaż CV obok
          </Button>
        }
      >
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
          <div className="space-y-0.5" role="list" aria-label="Rozmowy u klienta">
            {entries.map(({ item, col }) => {
              const feedback = feedbackByCandidate.get(item.candidate_id);
              return (
                <div key={item.candidate_id} role="listitem">
                  <RailRow
                    tone={
                      item.hm_veto
                        ? "bad"
                        : feedback
                          ? "ok"
                          : "neutral"
                    }
                    label={
                      `${item.name ?? ""} ${item.lastname ?? ""}`.trim() ||
                      "Kandydat"
                    }
                    meta={columnLabel(col)}
                    active={item.candidate_id === selectedCandidateId}
                    onSelect={() => setSelectedCandidateId(item.candidate_id)}
                    title={
                      feedback ? "Feedback hiring managera zapisany" : undefined
                    }
                  />
                </div>
              );
            })}
          </div>
        )}

        <RailSection
          label="Wcześniej u tego klienta"
          note="Weto blokuje ponowne „CV wysłane” i „Interview Klient” u tego managera — 409 z powodem, nie do nadpisania."
        >
          {vetoedEntries.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">
              Nikt z tej rekrutacji nie ma weta hiring managera.
            </p>
          ) : (
            <div className="space-y-0.5">
              {vetoedEntries.map(({ item }) => (
                <RailRow
                  key={`veto-${item.candidate_id}`}
                  tone="bad"
                  label={
                    `${item.name ?? ""} ${item.lastname ?? ""}`.trim() ||
                    "Kandydat"
                  }
                  meta="weto HM"
                  metaTone="bad"
                  active={item.candidate_id === selectedCandidateId}
                  onSelect={() => setSelectedCandidateId(item.candidate_id)}
                  title={item.hm_veto?.rejection_reason_name ?? undefined}
                />
              ))}
            </div>
          )}
        </RailSection>

        {selected && (
          <RailSection label="Przygotowanie">
            <div className="space-y-0.5">
              <Link
                href={`/jobs/${jobId}/prep/${selected.item.candidate_id}`}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-accent"
              >
                <Sparkles className="h-3 w-3 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 truncate">Prep-kit (AI)</span>
                <span className="shrink-0 text-[10.5px] text-muted-foreground">
                  otwórz
                </span>
              </Link>
              <RailRow
                label="Formularz screeningu"
                meta="otwórz"
                onSelect={() =>
                  setScreeningFor({
                    candidateId: selected.item.candidate_id,
                    name:
                      `${selected.item.name ?? ""} ${selected.item.lastname ?? ""}`.trim() ||
                      "Kandydat",
                  })
                }
              />
              <RailRow
                label="Zaproszenie prep (.ics + CV)"
                meta="szablon"
                onSelect={() => setPrepInviteOpen(true)}
              />
            </div>
          </RailSection>
        )}
      </WorkbenchRail>

      {/* ── Środek: karta rozmowy ──────────────────────────────────── */}
      <section className="min-w-0 space-y-4">
        {listBlocked ? null : listViewState === "empty" ? (
          <EmptyState
            icon={CalendarClock}
            title="Nikt nie jest jeszcze u klienta"
            description="Ten krok zbiera kandydatów na etapach zewnętrznych — Interview Klient, Akceptacja, Negocjacje. Przenieś kogoś na tablicy pipeline'u, żeby zobaczyć tu kartę rozmowy."
          />
        ) : selected ? (
          interviewCard
        ) : null}
      </section>

      {/* ── Dok „Decyzja" ──────────────────────────────────────────── */}
      <aside className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-4 xl:self-start">
        {listBlocked ? null : selected ? (
          decisionDock
        ) : (
          <InterviewDecisionDockEmpty />
        )}
      </aside>

      {modals}
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
  /**
   * `can_record` z odczytu werdyktów: czy `POST` przejdzie na serwerze.
   * `null` — odpowiedź jeszcze nie przyszła (formularz zostaje zablokowany).
   */
  canRecord: boolean | null;
  feedbackQueryState: ReturnType<typeof resolveViewState>;
  onFeedbackRetry: () => void;
  /** Formularz screeningu pary (okno). */
  onOpenScreening: (candidateId: number, name: string) => void;
  /** Aktualny budżet PLN/h rekrutacji — pigułka „Stawka ponad budżet". */
  budgetHourly: number | null;
  /** `"panel"` — bez nagłówka kroku; pigułki i akcja w zwartym pasku. */
  layout?: "full" | "panel";
}

function InterviewCard({
  jobId,
  jobTitle,
  entry,
  readOnly,
  reasons,
  reasonsLoading,
  feedback,
  canRecord,
  feedbackQueryState,
  onFeedbackRetry,
  onOpenScreening,
  budgetHourly,
  layout = "full",
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

  // Zapis werdyktu decyduje SERWER: `can_record` z odczytu liczy te same
  // bramki co `POST` (rola, sekcja, członkostwo w zespole z obejściem dla DL).
  // Sama capability roli nie wystarczała — Finance na cudzej rekrutacji
  // widziało aktywne „Zapisz feedback" kończące się 403. CUDZY werdykt
  // nadpisuje wyłącznie autor, DL albo admin — to mówi `can_edit` wiersza.
  // Capability zostaje wyłącznie do WYJAŚNIENIA, dlaczego jest tylko podgląd.
  const canRecordVerdict = useCapability("hm_feedback.record");
  const verdictLockedByAuthor = Boolean(feedback) && feedback?.can_edit === false;
  const canWriteVerdict = !readOnly && canRecord === true && !verdictLockedByAuthor;

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

  // Formularz screeningu — skrót wyniku (wszystko w nim jest dla zespołu).
  const screeningQuery = useQuery({
    queryKey: ["pipeline-stage-screening", item.id],
    queryFn: () => screeningApi.getForStage(item.id).then((r) => r.data),
    staleTime: 30_000,
  });
  const answers = screeningQuery.data?.screening_answers ?? null;

  const headerTools = (
          <>
            {item.hm_veto ? (
              <ToolPill tone="bad">
                <UserX className="h-3 w-3" /> Weto HM: jest
              </ToolPill>
            ) : (
              <ToolPill tone="ok">Weto HM: brak</ToolPill>
            )}
            {isOverHourlyBudget(item, budgetHourly) && (
              <ToolPill tone="warn">Stawka ponad budżet</ToolPill>
            )}
            {item.days_in_stage != null && (
              <ToolPill>
                {item.days_in_stage}{" "}
                {item.days_in_stage === 1 ? "dzień" : "dni"} na etapie
              </ToolPill>
            )}
          </>
  );

  return (
    <div className={layout === "panel" ? "space-y-3" : "space-y-4"}>
      {layout === "panel" ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {headerTools}
        </div>
      ) : (
      <WorkbenchHeader
        title={`Rozmowa u klienta · ${fullName}`}
        subtitle={[
          columnLabel(col),
          item.days_in_stage != null
            ? `${item.days_in_stage} ${item.days_in_stage === 1 ? "dzień" : "dni"} na etapie`
            : null,
          jobTitle ?? null,
        ]
          .filter(Boolean)
          .join(" · ")}
        tools={
          headerTools
        }
      />
      )}

      <WorkbenchCard
        title="Formularz screeningu"
        status={
          <button
            type="button"
            className="text-primary hover:underline"
            onClick={() => onOpenScreening(item.candidate_id, fullName)}
          >
            Otwórz formularz
          </button>
        }
      >
        <div className="text-xs">
          {screeningQuery.isLoading ? (
            <span className="inline-flex items-center gap-1.5 text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie
              screeningu…
            </span>
          ) : screeningQuery.isError ? (
            // Backend zwraca 200 + `screening_answers: null` dla niewypełnionego
            // arkusza, więc błąd to ZAWSZE awaria/403 — nigdy „pusto".
            <span className="inline-flex items-center gap-1.5 text-destructive">
              <AlertTriangle className="h-3 w-3" /> Nie udało się pobrać
              screeningu.
              <button
                type="button"
                className="font-medium text-primary hover:underline"
                onClick={() => void screeningQuery.refetch()}
              >
                Ponów
              </button>
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
      </WorkbenchCard>

      {/* Feedback klienta */}
      <WorkbenchCard
        title="Feedback klienta po rozmowie"
        status={feedbackStatusLabel(feedback)}
        statusTone={feedback ? "ok" : "warn"}
      >
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
            <fieldset disabled={!canWriteVerdict} className="space-y-3">
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

            {canWriteVerdict && (
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
            {readOnly ? (
              <p className="text-[11px] text-muted-foreground">
                Tylko do odczytu — brak prawa zapisu w tym pipeline.
              </p>
            ) : canRecord === false && !canRecordVerdict ? (
              <p className="text-[11px] text-muted-foreground">
                Werdykt zapisuje zespół rekrutacji (rekruter, Delivery Lead,
                admin) — Twoja rola ma tu podgląd.
              </p>
            ) : canRecord === false ? (
              <p className="text-[11px] text-muted-foreground">
                Werdykt zapisuje zespół tej rekrutacji (właściciel, TAC,
                współpracownicy, Delivery Lead) — nie należysz do niego, więc
                masz tu podgląd.
              </p>
            ) : verdictLockedByAuthor ? (
              <p className="text-[11px] text-muted-foreground">
                Werdykt zapisał(a) {feedback?.author_name ?? "inna osoba"} —
                zmienić go może autor, Delivery Lead, Head of Recruitment albo admin.
              </p>
            ) : null}
          </div>
        )}
      </WorkbenchCard>

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

/**
 * Status karty feedbacku klienta. Werdykt zapisany z okna wydarzenia
 * w kalendarzu jest nazwany wprost — do 09.2026 karta go nie widziała
 * i mówiła „do uzupełnienia", więc Delivery Lead wpisywał werdykt drugi raz.
 */
export function feedbackStatusLabel(
  feedback: Pick<HiringManagerFeedback, "calendar_event_id" | "event_start_time"> | null | undefined,
): string {
  if (!feedback) return "do uzupełnienia";
  if (feedback.calendar_event_id != null && feedback.event_start_time) {
    const d = new Date(feedback.event_start_time);
    if (!Number.isNaN(d.getTime())) {
      const day = String(d.getDate()).padStart(2, "0");
      const month = String(d.getMonth() + 1).padStart(2, "0");
      return `zapisany · z rozmowy ${day}.${month}`;
    }
  }
  return "zapisany";
}
