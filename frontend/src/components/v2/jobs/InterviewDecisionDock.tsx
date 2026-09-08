"use client";

/**
 * InterviewDecisionDock — dok „Decyzja" (krok 07 „Rozmowy i decyzja",
 * program „flow w języku C2", PR 7/7).
 *
 * Ten sam język co `PipelineCandidateDock` (krok 04) i `JobMatchDock` (C2):
 * dok obok listy, akcje na dole, zakładki montowane leniwie.
 *
 * Trzy granice, które ten dok trzyma świadomie:
 *
 * 1. **Nie hostuje modali stawek ani potwierdzenia zatrudnienia.** Które
 *    etapy ich wymagają, mówi `lib/pipeline-move-dialog` — ten sam moduł, na
 *    którym stoi `KanbanBoardV2.requestMove`. Pigułka takiego etapu jest
 *    WIDOCZNA i wyszarzona z polskim powodem, a nie ukryta ani kończąca się
 *    409 po kliknięciu (kontrakt bramki dopuszczalności).
 * 2. **Odrzucenie i wycofanie idą przez `RejectionV2`** — ten sam modal, ten
 *    sam `POST /api/pipeline/move`, ten sam 15-minutowy „Cofnij wysyłkę".
 *    Zero drugiej implementacji reguł maila.
 * 3. **Reakcji kandydata na ofertę NIE da się tu ustawić** i tak jest napisane.
 *    `candidate_offer_response` zapisuje wyłącznie ruch na „Wycofany" po
 *    akceptacji; dok pokazuje wartość i prowadzi do tej jedynej ścieżki.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Ban,
  CheckCircle2,
  Clock,
  ExternalLink,
  HandCoins,
  Loader2,
  Sparkles,
  UserX,
  X,
} from "lucide-react";

import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatDate } from "@/lib/utils";
import { encodeJobBackRef } from "@/lib/url-filters";
import { formatExpectedRate } from "@/lib/pipeline-flow";
import {
  colId,
  type KanbanColumn,
  type KanbanItem,
} from "@/components/v2/pages/kanban-shared";
import {
  DockActions,
  DockNotesPanel,
  DockSection,
  KvList,
  WorkbenchDock,
} from "@/components/v2/jobs/workbench-chrome";
import {
  dialogUnavailableReason,
  moveDialogFor,
} from "@/lib/pipeline-move-dialog";
import { terminalOf } from "@/lib/kanban-terminal";

export interface DecisionMoveTarget {
  col: KanbanColumn;
  blockedReason: string | null;
}

type DockTab = "decision" | "offer" | "notes" | "history";

const DOCK_TABS: { value: DockTab; label: string }[] = [
  { value: "decision", label: "Decyzja" },
  { value: "offer", label: "Oferta" },
  { value: "notes", label: "Notatki" },
  { value: "history", label: "Historia" },
];

const OFFER_RESPONSE_LABEL: Record<string, string> = {
  pending: "Oczekuje",
  accepted: "Przyjął",
  declined: "Odrzucił",
};

/** Wiersz `GET /api/pipeline/history/{candidate}/{job}` (`CandidateStageResponse`). */
interface StageHistoryItem {
  id: number;
  stage: string;
  stage_def_id?: number | null;
  moved_at: string;
  notes?: string | null;
}

/**
 * Pigułki „Przenieś na etap" dla kroku 07.
 *
 * Bramka liczona z DANYCH KARTY (backend nie ma endpointu podglądu — egzekwuje
 * ją wewnątrz `POST /pipeline/move`), dokładnie jak w doku kroku 04: weto
 * hiring managera blokuje każdy ruch nie-terminalny, terminalne ZAWSZE
 * przechodzą, `pending` nie jest bramką. Do tego dochodzi powód „ten dialog
 * mieszka na tablicy" z `lib/pipeline-move-dialog`.
 */
export function buildDecisionMoveTargets({
  item,
  currentColId,
  columns,
  readOnly,
  colIdOf,
}: {
  item: KanbanItem;
  currentColId: string | null;
  columns: KanbanColumn[];
  readOnly: boolean;
  colIdOf: (col: KanbanColumn) => string;
}): DecisionMoveTarget[] {
  return columns
    .filter((c) => colIdOf(c) !== currentColId)
    .map((col) => {
      const terminal = terminalOf(col);
      let blockedReason: string | null = null;
      if (readOnly) {
        blockedReason = "Tylko do odczytu — brak prawa zapisu w tym pipeline.";
      } else if (terminal === "rejected" || terminal === "withdrawn") {
        blockedReason = null;
      } else if (item.hm_veto) {
        blockedReason = `Hiring manager tej rekrutacji już odrzucił tego kandydata po rozmowie (${formatDate(item.hm_veto.rejected_at)}) — ${item.hm_veto.rejection_reason_name}.`;
      } else {
        blockedReason = dialogUnavailableReason(moveDialogFor(col));
      }
      return { col, blockedReason };
    });
}

export interface InterviewDecisionDockProps {
  item: KanbanItem;
  jobId: number;
  jobTitle?: string;
  currentStageLabel: string;
  moveTargets: DecisionMoveTarget[];
  readOnly: boolean;
  onClose: () => void;
  /** Ruch bez dialogu — dok wysyła go sam (`POST /api/pipeline/move`). */
  onMoveTo: (col: KanbanColumn) => void;
  /** Terminalne — otwiera `RejectionV2` w trybie `rejected` albo `withdrawn`. */
  onTerminal: (col: KanbanColumn, terminal: "rejected" | "withdrawn") => void;
  /** Skrót „Odrzuć z powodem" — kolumna „Odrzucony" tego szablonu. */
  rejectedColumn: KanbanColumn | null;
  /** Skrót „Wycofany z reakcją na ofertę" — kolumna „Wycofany" tego szablonu. */
  withdrawnColumn: KanbanColumn | null;
  /**
   * Etykieta etapu dla wiersza historii. Historia zwraca LEGACY enum
   * (`client_interview`), a tablica pokazuje nazwę z szablonu („Interview
   * Klient") — bez tłumaczenia dok mówiłby o etapach innym językiem niż
   * kolumna obok.
   */
  stageLabel: (row: { stage: string; stage_def_id?: number | null }) => string;
}

export function InterviewDecisionDock({
  item,
  jobId,
  jobTitle,
  currentStageLabel,
  moveTargets,
  readOnly,
  onClose,
  onMoveTo,
  onTerminal,
  rejectedColumn,
  withdrawnColumn,
  stageLabel,
}: InterviewDecisionDockProps) {
  const [activeTab, setActiveTab] = useState<DockTab>("decision");

  // Zmiana kandydata — wróć na pierwszą zakładkę (draft notatki czyści się
  // sam: `DockNotesPanel` montuje się z kluczem kandydata).
  useEffect(() => {
    setActiveTab("decision");
  }, [item.candidate_id]);

  const fullName =
    `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;

  const historyQuery = useQuery<StageHistoryItem[]>({
    queryKey: ["candidate-stage-history", item.candidate_id, jobId],
    queryFn: () =>
      api
        .get<StageHistoryItem[]>(
          `/api/pipeline/history/${item.candidate_id}/${jobId}`,
        )
        .then((r) => r.data ?? []),
    enabled: activeTab === "history",
  });

  const offerResponse = item.candidate_offer_response ?? null;

  return (
    <WorkbenchDock
      name="Decyzja"
      who={fullName}
      whoSub={
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <span>{currentStageLabel}</span>
          {item.days_in_stage != null && (
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {item.days_in_stage} {item.days_in_stage === 1 ? "dzień" : "dni"}
            </span>
          )}
          {item.hm_veto && (
            <Badge variant="danger" size="sm">
              <UserX className="h-2.5 w-2.5" /> Weto HM
            </Badge>
          )}
        </span>
      }
      headerRight={
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent"
          aria-label="Zamknij dok"
        >
          <X className="h-4 w-4" />
        </button>
      }
      tabs={DOCK_TABS}
      activeTab={activeTab}
      onTabChange={(v) => setActiveTab(v as DockTab)}
      footer={
        <>
          <Sparkles className="h-3 w-3 shrink-0" />„Przyjął” = konfetti jak dziś
          (kids mode) i powiadomienia stage’owe wg reguł klienta.
        </>
      }
    >
      <>
        {activeTab === "decision" && (
          <div className="space-y-3">
            {moveTargets.length > 0 ? (
              <div className="space-y-1.5">
                <div className="text-xs font-semibold text-foreground">
                  Przenieś na etap
                </div>
                <div className="flex flex-wrap gap-1">
                  {moveTargets.map(({ col, blockedReason }) => {
                    const terminal = terminalOf(col);
                    return (
                      <button
                        key={colId(col)}
                        type="button"
                        disabled={Boolean(blockedReason)}
                        title={blockedReason ?? undefined}
                        onClick={() => {
                          if (terminal === "rejected" || terminal === "withdrawn") {
                            onTerminal(col, terminal);
                            return;
                          }
                          onMoveTo(col);
                        }}
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                          blockedReason
                            ? "cursor-not-allowed border-border bg-muted text-muted-foreground/60"
                            : "border-border bg-background text-foreground hover:border-primary hover:bg-primary/5",
                        )}
                      >
                        {col.name ?? col.stage}
                      </button>
                    );
                  })}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Etapy terminalne zawsze przechodzą bramkę — inaczej nie dałoby
                  się zamknąć kandydata. „Zatrudniony” nigdy zbiorczo.
                </p>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Ten szablon procesu nie ma innych etapów niż bieżący.
              </p>
            )}

            {/* Reguły odrzucenia i wycofania — wypisane, żeby nikt nie musiał
                ich pamiętać (makieta kroku 07). */}
            <section className="space-y-2 rounded-lg border border-destructive/30 bg-destructive-muted/20 px-3 py-2.5">
              <h4 className="text-[10px] font-bold uppercase tracking-[0.1em] text-destructive-muted-foreground">
                Odrzucenie / wycofanie
              </h4>
              <KvList
                rows={[
                  {
                    k: "Powód",
                    v: "ze słownika szablonu (fallback: wolny tekst); „Wycofany” ZAWSZE ze słownika",
                  },
                  {
                    k: "Mail",
                    v: "tylko dla „Odrzucony” z etapu zewnętrznego · wysyłka za 15 min · „Cofnij wysyłkę” (10 s)",
                  },
                ]}
              />
            </section>
          </div>
        )}

        {activeTab === "offer" && (
          <div className="space-y-3">
            <DockSection title="Oferta i reakcja kandydata">
              <KvList
                rows={[
                  {
                    k: "Stawka kandydata",
                    v:
                      formatExpectedRate(item) ??
                      (<span className="text-muted-foreground">brak danych</span>),
                  },
                  {
                    k: "Budżet oferty",
                    v:
                      item.budget_max_at_move != null ? (
                        <span className="tabular-nums">
                          do {item.budget_max_at_move}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">brak danych</span>
                      ),
                  },
                  {
                    k: "Reakcja",
                    v: offerResponse ? (
                      <Badge
                        size="sm"
                        variant={
                          offerResponse === "accepted"
                            ? "success"
                            : offerResponse === "declined"
                              ? "danger"
                              : "warning"
                        }
                      >
                        {OFFER_RESPONSE_LABEL[offerResponse] ?? offerResponse}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">nie zapisano</span>
                    ),
                  },
                ]}
              />
            </DockSection>
            <p className="text-[11px] text-muted-foreground">
              Reakcję kandydata zapisuje wyłącznie wycofanie po akceptacji — to
              jedyna ścieżka, którą zna backend. Stąd nie da się jej ustawić
              osobno i dok tego nie udaje.
            </p>
            {withdrawnColumn && !readOnly && (
              <Button
                size="sm"
                variant="outline"
                className="w-full justify-start"
                onClick={() => onTerminal(withdrawnColumn, "withdrawn")}
              >
                <HandCoins className="h-3.5 w-3.5" /> Wycofaj z reakcją na ofertę
              </Button>
            )}
          </div>
        )}

        {activeTab === "notes" && (
          <DockNotesPanel
            candidateId={item.candidate_id}
            jobId={jobId}
            readOnly={readOnly}
            enabled={activeTab === "notes"}
          />
        )}

        {activeTab === "history" && (
          <div className="space-y-2">
            {historyQuery.isLoading ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
              </div>
            ) : (historyQuery.data ?? []).length > 0 ? (
              (historyQuery.data ?? []).map((row) => (
                <div
                  key={row.id}
                  className="rounded-lg border border-border bg-muted/20 p-2.5 text-xs"
                >
                  <div className="flex items-center justify-between text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {stageLabel(row)}
                    </span>
                    <span>{formatDate(row.moved_at)}</span>
                  </div>
                  {row.notes ? (
                    <p className="mt-1 whitespace-pre-line text-muted-foreground">
                      {row.notes}
                    </p>
                  ) : null}
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">
                Brak zapisanych ruchów na tej rekrutacji.
              </p>
            )}
          </div>
        )}

        {/* ── Akcje (zawsze widoczne, na dole treści doku) ─────────────── */}
        <div className="space-y-1.5 border-t border-border pt-3">
          <DockActions>
            <Link
              href={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
              className="inline-flex h-8 items-center justify-start gap-1.5 rounded-lg border border-border px-3 text-xs text-muted-foreground hover:bg-muted"
            >
              <ExternalLink className="h-3.5 w-3.5" /> Pełny profil
            </Link>
            <Link
              href={`/jobs/${jobId}/prep/${item.candidate_id}`}
              className="inline-flex h-8 items-center justify-start gap-1.5 rounded-lg border border-border px-3 text-xs text-muted-foreground hover:bg-muted"
              title={`Prep-kit dla rekrutacji ${jobLabel}`}
            >
              <CheckCircle2 className="h-3.5 w-3.5" /> Prep-kit
            </Link>
            {rejectedColumn && !readOnly && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => onTerminal(rejectedColumn, "rejected")}
                className="col-span-2 w-full justify-start text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                <Ban className="h-3.5 w-3.5" /> Odrzuć z powodem
              </Button>
            )}
          </DockActions>
        </div>
      </>
    </WorkbenchDock>
  );
}

/** Pusty stan doku — nikt nie jest wybrany na liście „U klienta". */
export function InterviewDecisionDockEmpty() {
  return (
    <div className="rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
      <CheckCircle2 className="mx-auto mb-2 h-6 w-6 opacity-40" />
      Wybierz kandydata z listy „U klienta”, aby zobaczyć decyzję, ofertę
      i historię.
    </div>
  );
}
