"use client";

/**
 * Orkiestracja ruchu kandydata w pipeline — wyniesiona z `KanbanBoardV2`
 * (czysta ekstrakcja, zero zmiany zachowania), żeby widok tabeli i panel osoby
 * mogły wywołać DOKŁADNIE te same przepływy co tablica.
 *
 * Reguły, których ten hook pilnuje (patrz CLAUDE.md „Kanban bez bramek" oraz
 * „Pipeline rekrutacji — bramka ruchu…"):
 * - jedyna bramka frontu to `moveBlockedReason`;
 * - po ruchu unieważniamy OBA klucze `["kanban", String(id)]` i `["kanban", id]`,
 *   a w pętli zbiorczej — raz, po pętli;
 * - 409 `ELIGIBILITY_WARNING` → okno „Przenieś mimo to" i TEN SAM ruch
 *   z `acknowledge_eligibility: true`;
 * - 409 `PIPELINE_VERSION_CONFLICT` → toast + odświeżenie, BEZ ponowienia;
 *   wersję wysyła wyłącznie ruch pojedynczy z karty, która niesie liczbę;
 * - mail odrzucenia jest opt-in, a zaplanowany mail ma toast „Cofnij wysyłkę";
 * - „Zatrudniony" wymaga potwierdzenia; „Zweryfikowany" pyta o stawkę
 *   (podpowiedź z profilu, „Pomiń stawkę"); „CV Wysłane" pyta o stawkę do
 *   klienta tylko przy `canWriteClientRate`;
 * - ruch zbiorczy = pętla pojedynczych ruchów i kolejki okien, nigdy `/bulk-move`.
 */

import { useCallback, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import api, { pipelineApi, type RateUnit } from "@/lib/api";
import { getUserRoles, useAuthStore } from "@/store/auth";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { VerifiedRateModal } from "@/components/v2/modals/VerifiedRateModal";
import { ClientRateModal } from "@/components/v2/modals/ClientRateModal";
import { RejectionV2, type EndedBy } from "@/components/v2/modals/RejectionV2";
import { DebriefRequiredDialog } from "@/components/v2/recruitment/DebriefRequiredDialog";
import {
  colId,
  type KanbanColumn,
  type KanbanItem,
} from "@/components/v2/pages/kanban-shared";
import { celebrate } from "@/lib/celebrate";
import { terminalOf } from "@/lib/kanban-terminal";
import { moveDialogFor } from "@/lib/pipeline-move-dialog";
import { assignErrorMessage } from "@/lib/assign-error";
import {
  bulkMoveFailureMessage,
  bulkMoveSkipReason,
  itemFullName,
  moveBlockedReason,
} from "@/lib/pipeline-flow";
import {
  PIPELINE_VERSION_CONFLICT_MESSAGE,
  expectedStateVersionOf,
  invalidateAfterPipelineVersionConflict,
  isPipelineVersionConflict,
} from "@/lib/pipeline-version-conflict";
import {
  eligibilityWarningReason,
  isEligibilityWarning,
} from "@/lib/pipeline-eligibility-warning";

// Lustro `RECRUITMENT_RATE_EDIT_ROLES` (backend/app/api/recruitment_access.py):
// ruch na „Zweryfikowany" może zapisać stawkę kandydata i poza tymi rolami
// serwer odpowiada 403. Okno stawki dla innej roli kończyłoby się odmową PO
// wpisaniu kwoty, więc ekran mówi o tym przed. (Head of Recruitment ma
// parytet z rekruterem od 17.09.2026.)
const RATE_EDIT_ROLES = new Set([
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
  "recruiter",
  "finance",
]);
export const RATE_EDIT_DENIED_MESSAGE =
  "Ruch na „Zweryfikowany” może zapisać stawkę kandydata — mogą go wykonać: rekruter, TAC, Delivery Lead, Head of Recruitment, Finanse lub administrator.";

export interface PipelineRejectionReasonOption {
  id: string;
  label: string;
  applies_to: ("rejected" | "withdrawn")[];
}

/** Dane rekrutacji, których potrzebują okna ruchu. Wołający pobiera je sam
 *  (tablica robi to jednym `GET /api/jobs/{id}` razem z szablonem). */
export interface PipelineMoveJob {
  /** Budżet PLN/h — okno „Zweryfikowany" porównuje z nim stawkę. */
  budgetHourly: number | null;
  /** Słownik powodów `RejectionV2` (z szablonu albo szablonu domyślnego). */
  rejectionReasons: PipelineRejectionReasonOption[];
}

/** Pola karty, które serwer potwierdził po ruchu (nowy `CandidateStage`). */
export type PipelineMoveConfirmedPatch = Partial<KanbanItem>;

/**
 * Adapter stanu optymistycznego. Tablica trzyma własne `cols` i podaje adapter;
 * bez adaptera hook wyłącznie unieważnia zapytania `["kanban", …]`.
 */
export interface PipelineMoveOptimisticAdapter {
  /** Przenieś kartę lokalnie PRZED odpowiedzią serwera. Może zwrócić funkcję
   *  cofającą — użyta po błędzie tylko wtedy, gdy nie ma `sync`. */
  apply: (
    item: KanbanItem,
    fromColId: string,
    toColumn: KanbanColumn
  ) => void | (() => void);
  /** Serwer potwierdził ruch: karta ma stać w `toColumn` z polami `patch`
   *  (nowe id etapu, wersja procesu, status…). Dla „Zweryfikowany" karta NIE
   *  była przeniesiona optymistycznie — adapter ma ją zdjąć z `fromColId`
   *  i dołożyć do `toColumn`. */
  confirm?: (args: {
    item: KanbanItem;
    fromColId: string | null;
    toColumn: KanbanColumn;
    patch: PipelineMoveConfirmedPatch;
  }) => void;
  /** Wróć do prawdy serwera (błąd ruchu, konflikt wersji, „Anuluj" w oknie
   *  ostrzeżenia, częściowy sukces pętli). */
  sync?: () => Promise<void> | void;
}

export interface UsePipelineMoveOptions {
  jobId: number;
  job: PipelineMoveJob;
  /** Kolumny, po których hook szuka kolumny źródłowej karty (ruch zbiorczy,
   *  odrzucenie) i kategorii poprzedniego etapu dla `RejectionV2`. */
  columns: KanbanColumn[];
  readOnly: boolean;
  canWriteClientRate: boolean;
  optimistic?: PipelineMoveOptimisticAdapter;
  /** Rekrutacja Nordei: „CV wysłane" = „Wysłane do Cpro", bez przeglądu DL. */
  cproEnabled?: boolean;
}

interface MoveEntry {
  item: KanbanItem;
  srcColId: string;
}

interface MoveReason {
  id: string;
  notes: string;
  sendRejectionEmail?: boolean | null;
  candidateOfferResponse?: "pending" | "accepted" | "declined" | null;
  // Wolny tekst powodu — tylko gdy szablon nie miał zdefiniowanych powodów.
  freeReason?: string;
  // Kto zakończył proces (0352).
  endedBy?: EndedBy;
}

interface SendMoveOptions {
  silent?: boolean;
  // Pętle zbiorcze (i ruch + PATCH stawki) unieważniają zapytanie strony
  // RAZ, po całej operacji — odświeżenie w środku pętli nadpisywało
  // optymistyczne ruchy kolejnych kart stanem sprzed nich.
  deferCacheSync?: boolean;
  // F05: pojedynczy ruch z karty odsyła wersję procesu
  // (`expected_state_version`). Ruchy zbiorcze przekazują `false` — bez
  // sprawdzenia, jak dotąd.
  checkVersion?: boolean;
  // 17.09.2026: powtórka po 409 ELIGIBILITY_WARNING („Przenieś mimo to").
  acknowledgeEligibility?: boolean;
  // REC-06: przy `silent` powód odmowy trafia do wołającego (ruch zbiorczy
  // składa z nich jeden komunikat z nazwiskami).
  onFailure?: (reason: string) => void;
  // 0348: osoba, która wyśle kandydata do Cpro — tylko przy „Gotowy do Cpro".
  taskAssigneeId?: number;
  // Pipeline v4: stawka do klienta w TYM SAMYM żądaniu co ruch na „CV wysłane".
  clientRate?: RatePayload;
}

type RatePayload = { rate: number; unit: RateUnit; currency: string };

/** 409 `DEBRIEF_REQUIRED` (Pipeline v4) → id rozmowy u klienta albo `null`. */
function debriefRequiredEventId(error: unknown): number | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response;
  const detail = response?.data?.detail as { code?: unknown; event_id?: unknown } | undefined;
  if (response?.status !== 409 || !detail || detail.code !== "DEBRIEF_REQUIRED") return null;
  return typeof detail.event_id === "number" ? detail.event_id : null;
}

// Pipeline v4 (23.09.2026): poza Nordeą do klienta wysyła Delivery Lead
// (lustro `pipeline_move_rules.CLIENT_SEND_ROLES`).
const CLIENT_SEND_ROLES = new Set(["admin", "delivery_lead"]);
const DL_REJECT_ROLES = new Set(["admin", "delivery_lead", "head_of_recruitment"]);
export const CLIENT_SEND_DENIED_MESSAGE =
  "Do klienta wysyła Delivery Lead — osoba czeka w „Zweryfikowanym” na jego przegląd.";

export interface PipelineMoveControls {
  /** Ta sama decyzja co przeciągnięcie karty na tablicy. */
  requestMove: (
    item: KanbanItem,
    fromColumn: KanbanColumn | string,
    toColumn: KanbanColumn,
    options?: { taskAssigneeId?: number }
  ) => void;
  /** Ruch zbiorczy: pętla pojedynczych ruchów / kolejki okien. `onHandled`
   *  woła się w chwili, gdy wołający powinien wyczyścić zaznaczenie. */
  requestBulkMove: (
    items: KanbanItem[],
    toColumn: KanbanColumn,
    options?: { onHandled?: () => void }
  ) => Promise<void>;
  /** „Odrzuć z powodem" — otwiera `RejectionV2` na kolumnie terminalnej
   *  „Odrzucony" (domyślnie pierwszej takiej w `columns`). `endedBy` wstępnie
   *  wybiera „kto kończy". */
  requestReject: (
    items: KanbanItem | KanbanItem[],
    toColumn?: KanbanColumn,
    options?: { endedBy?: Exclude<EndedBy, "candidate"> }
  ) => void;
  /** „Zrezygnował" — `RejectionV2` na kolumnie „Wycofany". */
  requestWithdraw: (items: KanbanItem | KanbanItem[]) => void;
  /** Trwa pętla ruchu zbiorczego. */
  isMoving: boolean;
  /** Wszystkie okna przepływu — wyrenderuj raz w drzewie wołającego. */
  dialogs: ReactNode;
}

export function usePipelineMove({
  jobId,
  job,
  columns,
  readOnly,
  canWriteClientRate,
  optimistic,
  cproEnabled = false,
}: UsePipelineMoveOptions): PipelineMoveControls {
  const queryClient = useQueryClient();
  const { showActionToast, showSuccess, showError } = useToast();
  // Pełny zbiór ról (primary + secondary), nie tylko primary — hybryda ról
  // widzi to, na co pozwala jej którakolwiek z nich (parity z backendem).
  const authUser = useAuthStore((s) => s.user);
  const canEditRates = getUserRoles(authUser).some((r) => RATE_EDIT_ROLES.has(r));
  const canSendToClient = getUserRoles(authUser).some((r) => CLIENT_SEND_ROLES.has(r));
  const canEndAsDeliveryLead = getUserRoles(authUser).some((r) => DL_REJECT_ROLES.has(r));

  // Ref, nie zależność: adapter jest zwykle świeżym obiektem przy każdym
  // renderze wołającego, a callbacki ruchu mają zostać stabilne.
  const optimisticRef = useRef(optimistic);
  optimisticRef.current = optimistic;

  const [bulkBusy, setBulkBusy] = useState(false);
  // M4 PR-03 (audyt P1.6): potwierdzenie przed hired — ruch tworzy draft
  // kontraktu + zamówienia, nie powinien być skutkiem samego puszczenia myszy.
  const [hiredConfirm, setHiredConfirm] = useState<{
    item: KanbanItem;
    destCol: KanbanColumn;
    srcColId: string;
  } | null>(null);
  // Terminal-move modal — pojedynczy ruch LUB bulk (wspólny powód odrzucenia
  // dla wszystkich zaznaczonych kandydatów).
  const [pendingRejection, setPendingRejection] = useState<{
    entries: MoveEntry[];
    destCol: KanbanColumn;
    terminalType: "rejected" | "withdrawn";
    endedBy?: Exclude<EndedBy, "candidate"> | null;
  } | null>(null);
  const [verifiedRatePrompt, setVerifiedRatePrompt] = useState<{
    item: KanbanItem;
    destCol: KanbanColumn;
    srcColId: string;
  } | null>(null);
  // Bulk → "Zweryfikowany": stawka jest per kandydat, więc kolejka modali
  // (jeden po drugim) zamiast jednego wspólnego formularza.
  const [verifiedQueue, setVerifiedQueue] = useState<MoveEntry[]>([]);
  const [verifiedBulkTotal, setVerifiedBulkTotal] = useState(0);
  // „CV Wysłane" → zapytaj o stawkę do klienta (sell rate). Analogiczne do
  // verified, ale stawka jest opcjonalna i zapisywana osobnym PATCH-em po ruchu
  // (kolumny client_rate_* na najnowszym CandidateStage). Bulk = kolejka modali.
  const [clientRatePrompt, setClientRatePrompt] = useState<{
    item: KanbanItem;
    destCol: KanbanColumn;
    srcColId: string;
  } | null>(null);
  const [clientRateQueue, setClientRateQueue] = useState<MoveEntry[]>([]);
  // Pipeline v4: 409 DEBRIEF_REQUIRED — najpierw telefon po rozmowie u klienta
  // i pytania klienta, potem TEN SAM ruch.
  const [debriefRequired, setDebriefRequired] = useState<{
    eventId: number;
    item: KanbanItem;
    retry: () => Promise<void>;
  } | null>(null);
  const [clientRateBulkTotal, setClientRateBulkTotal] = useState(0);
  // 409 ELIGIBILITY_WARNING (17.09.2026) — jedno okno. `retry` powtarza ruch,
  // który je wywołał, z `acknowledge_eligibility: true`; `onDismiss` pozwala
  // kolejce zbiorczej pójść dalej po „Anuluj".
  const [eligibilityWarning, setEligibilityWarning] = useState<{
    reason: string;
    retry: () => Promise<void>;
    onDismiss?: () => void;
  } | null>(null);

  const applyOptimistic = useCallback(
    (item: KanbanItem, srcId: string, dst: KanbanColumn) =>
      optimisticRef.current?.apply(item, srcId, dst),
    []
  );

  // Strona trzyma pipeline pod `["kanban", id]` (`id` to string z `useParams`)
  // i karmi nim listwę kroków, klaster KPI w jobbarze oraz kolejki kroków
  // 05–08. Oba klucze — część konsumentów trzyma liczbę.
  const syncKanbanCache = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  }, [queryClient, jobId]);

  // M4 PR-03: po błędzie ruchu NIE zostawiamy karty w niepotwierdzonej
  // kolumnie — dociągamy prawdę z serwera (a nie lokalny snapshot, bo 409
  // oznacza, że stan pary i tak się zmienił pod nami).
  const refreshAfterMove = useCallback(
    async (rollback?: void | (() => void)) => {
      const adapter = optimisticRef.current;
      if (adapter?.sync) await adapter.sync();
      else if (typeof rollback === "function") rollback();
      // Częściowy sukces (bulk) i 409 „stan zmienił się pod nami" dotyczą też
      // reszty strony — ta sama prawda ma trafić do KPI i kolejek kroków.
      syncKanbanCache();
    },
    [syncKanbanCache]
  );

  // „Anuluj" w oknie ostrzeżenia: optymistyczna karta wraca na miejsce
  // (prawda serwera), a kolejka zbiorcza — jeśli to ona pytała — idzie dalej.
  const dismissEligibilityWarning = useCallback(async () => {
    const onDismiss = eligibilityWarning?.onDismiss;
    setEligibilityWarning(null);
    onDismiss?.();
    await refreshAfterMove();
  }, [eligibilityWarning, refreshAfterMove]);

  const sendMove = useCallback(
    async (
      item: KanbanItem,
      dst: KanbanColumn,
      reason?: MoveReason,
      opts?: SendMoveOptions
    ): Promise<boolean> => {
      try {
        const response = await api.post<{
          id?: number;
          verification_status?: "active" | "pending" | "rejected";
          scheduled_rejection_email_id?: number | null;
          process_state_version?: number | null;
        }>("/api/pipeline/move", {
          candidate_id: item.candidate_id,
          job_id: jobId,
          stage: dst.stage,
          stage_def_id: dst.stage_def_id ?? undefined,
          rejection_reason_id: reason?.id || undefined,
          rejection_reason: reason?.freeReason || undefined,
          notes: reason?.notes,
          send_rejection_email: reason?.sendRejectionEmail ?? undefined,
          candidate_offer_response: reason?.candidateOfferResponse ?? undefined,
          expected_state_version:
            opts?.checkVersion === false ? undefined : expectedStateVersionOf(item),
          acknowledge_eligibility: opts?.acknowledgeEligibility ? true : undefined,
          task_assignee_id: opts?.taskAssigneeId ?? undefined,
          ended_by: reason?.endedBy ?? undefined,
          client_rate_value: opts?.clientRate?.rate ?? undefined,
          client_rate_unit: opts?.clientRate?.unit ?? undefined,
          client_rate_currency: opts?.clientRate?.currency ?? undefined,
        });

        // M4 PR-03 (audyt P1.3): backend tworzy NOWY CandidateStage — karta
        // dostaje jego id + status z serwera. Bez tego kolejne akcje
        // (screening, scorecard) celowały w historyczny rekord.
        const newStageId = response?.data?.id;
        const serverVerifStatus = response?.data?.verification_status;
        // F05: nowa wersja procesu — kolejny ruch z tej karty przed odświeżeniem
        // nie może wysłać wersji sprzed własnego ruchu.
        const serverVersion = response?.data?.process_state_version;
        if (typeof newStageId === "number" && newStageId !== item.id) {
          // Od 17.09.2026 po ruchu NIE otwieramy arkuszy screeningu ani
          // scorecardu — nowy wiersz etapu ma je puste, więc karta pokazuje
          // odznaki „do uzupełnienia" (screening_done/scorecard_done).
          const patch: PipelineMoveConfirmedPatch = {
            id: newStageId,
            screening_done: false,
            scorecard_done: false,
          };
          if (serverVerifStatus) patch.verification_status = serverVerifStatus;
          if (typeof serverVersion === "number") {
            patch.process_state_version = serverVersion;
          }
          optimisticRef.current?.confirm?.({
            item,
            fromColId: null,
            toColumn: dst,
            patch,
          });
        }

        // Kids mode: confetti + mascot pop on a win. No-op outside game mode.
        if (dst.stage === "hired") {
          celebrate({ variant: "hired", message: "Zatrudniony! 🎉" });
        } else if (reason?.candidateOfferResponse === "accepted") {
          celebrate({ variant: "offer", message: "Oferta przyjęta! 💖" });
        }

        // 0045_rejection_emails — if the backend scheduled an auto-email,
        // offer a 10-second "Cofnij wysyłkę" toast so the recruiter can
        // abort before the 15-minute countdown elapses.
        const scheduledId = response?.data?.scheduled_rejection_email_id;
        if (scheduledId) {
          showActionToast("Email odrzucenia zostanie wysłany za 15 minut.", {
            actionLabel: "Cofnij wysyłkę",
            onAction: async () => {
              try {
                await api.post(`/api/rejection-emails/${scheduledId}/cancel`);
                showSuccess("Anulowano wysyłkę emaila.");
              } catch (err) {
                console.error("rejection email cancel failed", err);
                showError("Nie udało się anulować wysyłki.");
              }
            },
            durationMs: 10_000,
          });
        }

        if (!opts?.deferCacheSync) syncKanbanCache();
        return true;
      } catch (e) {
        console.error("Move failed", e);
        if (opts?.silent) {
          opts.onFailure?.(
            isEligibilityWarning(e)
              ? (eligibilityWarningReason(e) ?? "serwer ostrzega przed tym ruchem")
              : isPipelineVersionConflict(e)
                ? PIPELINE_VERSION_CONFLICT_MESSAGE
                : assignErrorMessage(e),
          );
        }
        if (
          !opts?.silent &&
          !opts?.acknowledgeEligibility &&
          isEligibilityWarning(e)
        ) {
          // Czarna lista / NDA / konkurent / weto HM: jedno pytanie, potem TEN
          // SAM ruch z potwierdzeniem. Optymistyczna karta czeka na decyzję;
          // „Anuluj" cofa ją prawdą serwera.
          setEligibilityWarning({
            reason: eligibilityWarningReason(e) ?? "Serwer ostrzega przed tym ruchem.",
            retry: async () => {
              setEligibilityWarning(null);
              await sendMoveRef.current?.(item, dst, reason, {
                ...opts,
                acknowledgeEligibility: true,
              });
            },
          });
          return false;
        }
        const debriefEventId = debriefRequiredEventId(e);
        if (!opts?.silent && debriefEventId != null) {
          setDebriefRequired({
            eventId: debriefEventId,
            item,
            retry: async () => {
              setDebriefRequired(null);
              await sendMoveRef.current?.(item, dst, reason, opts);
            },
          });
          return false;
        }
        if (!opts?.silent && isPipelineVersionConflict(e)) {
          // Ktoś przesunął tę parę po odczycie tablicy: bez ponowienia —
          // pokazujemy prawdę serwera i dajemy zdecydować jeszcze raz.
          showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
          invalidateAfterPipelineVersionConflict(queryClient, jobId, item.candidate_id);
          await refreshAfterMove();
          return false;
        }
        if (!opts?.silent) {
          // Wspólny parser zachowuje dotychczasowe szczegóły błędu i dodatkowo
          // rozpoznaje strukturalny PRIORITY_WORK_LOCKED.
          showError(assignErrorMessage(e));
          // M4 PR-03 (audyt P1.4): rollback optimistic — widok wraca do
          // prawdy serwera zamiast kłamać kolumną, której DB nie potwierdziła.
          await refreshAfterMove();
        }
        return false;
      }
    },
    [
      jobId,
      queryClient,
      refreshAfterMove,
      syncKanbanCache,
      showActionToast,
      showSuccess,
      showError,
    ]
  );
  // Ref, nie zależność: `retry` w oknie ostrzeżenia woła NAJNOWSZĄ wersję
  // `sendMove`, a sam `sendMove` nie może zależeć od siebie.
  const sendMoveRef = useRef<typeof sendMove | null>(null);
  sendMoveRef.current = sendMove;

  const requestMove = useCallback(
    (
      item: KanbanItem,
      fromColumn: KanbanColumn | string,
      dst: KanbanColumn,
      options?: { taskAssigneeId?: number }
    ) => {
      const srcColId = typeof fromColumn === "string" ? fromColumn : colId(fromColumn);
      if (readOnly) return;
      if (srcColId === colId(dst)) return;

      // Ta sama bramka co pigułki doku i warsztaty 05–07.
      const dstTerminal = terminalOf(dst);
      const blocked = moveBlockedReason({
        item,
        readOnly,
        terminal: dstTerminal === "rejected" || dstTerminal === "withdrawn",
        targetStage: dst.stage,
      });
      if (blocked) {
        showError(blocked);
        return;
      }

      // Która gałąź — decyduje `lib/pipeline-move-dialog`, wspólne z dokiem
      // „Decyzja" kroku 07.
      const dialog = moveDialogFor(dst);

      // „Zweryfikowany" — najpierw zapytaj o stawkę, dopiero potem ruch.
      // NIE applyOptimistic tu, bo rekruter może anulować w modalu.
      if (dialog === "verified_rate") {
        if (!canEditRates) {
          showError(RATE_EDIT_DENIED_MESSAGE);
          return;
        }
        setVerifiedQueue([]);
        setVerifiedBulkTotal(1);
        setVerifiedRatePrompt({ item, destCol: dst, srcColId });
        return;
      }

      // „CV Wysłane" poza Nordeą (Pipeline v4): wysyła DL, stawka wymagana.
      if (dialog === "client_rate" && !cproEnabled) {
        if (!canSendToClient) {
          showError(CLIENT_SEND_DENIED_MESSAGE);
          return;
        }
        setClientRateQueue([]);
        setClientRateBulkTotal(1);
        setClientRatePrompt({ item, destCol: dst, srcColId });
        return;
      }

      // „CV Wysłane" — zapytaj o stawkę do klienta przed ruchem (rekruter może
      // pominąć lub anulować w modalu, dlatego NIE applyOptimistic tutaj).
      if (dialog === "client_rate" && canWriteClientRate) {
        setClientRateQueue([]);
        setClientRateBulkTotal(1);
        setClientRatePrompt({ item, destCol: dst, srcColId });
        return;
      }

      // M4 PR-03 (audyt P1.6): hired = artefakty (draft kontraktu i zamówienia)
      // — wymaga jawnego potwierdzenia zamiast samego drop-u.
      if (dialog === "hired_confirm") {
        setHiredConfirm({ item, destCol: dst, srcColId });
        return;
      }

      // Terminal — najpierw modal powodu; optimistic dopiero po potwierdzeniu,
      // żeby anulowanie nie zostawiało karty w złej kolumnie.
      if (dialog === "rejection") {
        const dropTerminal = terminalOf(dst);
        setPendingRejection({
          entries: [{ item, srcColId }],
          destCol: dst,
          terminalType: dropTerminal === "withdrawn" ? "withdrawn" : "rejected",
        });
        return;
      }

      applyOptimistic(item, srcColId, dst);
      sendMove(
        item,
        dst,
        undefined,
        options?.taskAssigneeId != null ? { taskAssigneeId: options.taskAssigneeId } : undefined
      );
    },
    [
      readOnly,
      applyOptimistic,
      sendMove,
      showError,
      canEditRates,
      canWriteClientRate,
      canSendToClient,
      cproEnabled,
    ]
  );

  // Submit z okna „Zweryfikowany". `payload === null` = „Pomiń stawkę" (stawka
  // opcjonalna od 17.09.2026). `acknowledge` = powtórka po 409
  // ELIGIBILITY_WARNING; kolejka zbiorcza przesuwa się DOPIERO po decyzji.
  const submitVerifiedMove = useCallback(
    async (payload: RatePayload | null, acknowledge = false) => {
      if (!verifiedRatePrompt) return;
      const { item, destCol, srcColId } = verifiedRatePrompt;
      const isSingleMove = verifiedBulkTotal <= 1;
      const advanceQueue = () => {
        const [next, ...rest] = verifiedQueue;
        setVerifiedQueue(rest);
        setVerifiedRatePrompt(
          next ? { item: next.item, destCol, srcColId: next.srcColId } : null
        );
      };
      try {
        const res = await pipelineApi.move({
          candidate_id: item.candidate_id,
          job_id: jobId,
          stage: "verified",
          stage_def_id: destCol.stage_def_id ?? undefined,
          ...(payload
            ? {
                expected_rate_value: payload.rate,
                expected_rate_unit: payload.unit,
                expected_rate_currency: payload.currency,
              }
            : {}),
          // F05: tylko ruch pojedynczy — kolejka zbiorcza bez sprawdzenia.
          expected_state_version: isSingleMove
            ? expectedStateVersionOf(item)
            : undefined,
          acknowledge_eligibility: acknowledge ? true : undefined,
        });
        // Backend tworzy NOWY CandidateStage — bierzemy jego id (nie stare
        // item.id), żeby screening zapisał się na świeżym etapie „verified".
        const newStageId = (res?.data as { id?: number } | undefined)?.id ?? null;
        optimisticRef.current?.confirm?.({
          item,
          fromColId: srcColId,
          toColumn: destCol,
          patch: {
            id: newStageId ?? item.id,
            stage: destCol.stage,
            days_in_stage: 0,
            verification_status: "active",
            expected_rate_value: payload?.rate ?? item.expected_rate_value ?? null,
            expected_rate_unit: payload?.unit ?? item.expected_rate_unit ?? null,
            expected_rate_currency:
              payload?.currency ?? item.expected_rate_currency ?? null,
            // Nowy wiersz etapu — arkusze trzeba uzupełnić od nowa (odznaki).
            screening_done: false,
            scorecard_done: false,
            process_state_version:
              typeof res?.data?.process_state_version === "number"
                ? res.data.process_state_version
                : item.process_state_version,
          },
        });
        syncKanbanCache();
        advanceQueue();
      } catch (e) {
        console.error("Move to verified failed", e);
        if (!acknowledge && isEligibilityWarning(e)) {
          setEligibilityWarning({
            reason: eligibilityWarningReason(e) ?? "Serwer ostrzega przed tym ruchem.",
            retry: async () => {
              setEligibilityWarning(null);
              await submitVerifiedMoveRef.current?.(payload, true);
            },
            onDismiss: advanceQueue,
          });
          return;
        }
        if (isPipelineVersionConflict(e)) {
          showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
          invalidateAfterPipelineVersionConflict(queryClient, jobId, item.candidate_id);
          await refreshAfterMove();
        } else {
          showError(assignErrorMessage(e));
        }
        advanceQueue();
      }
    },
    [
      verifiedRatePrompt,
      verifiedQueue,
      verifiedBulkTotal,
      jobId,
      queryClient,
      refreshAfterMove,
      syncKanbanCache,
      showError,
    ]
  );
  const submitVerifiedMoveRef = useRef<typeof submitVerifiedMove | null>(null);
  submitVerifiedMoveRef.current = submitVerifiedMove;

  // Submit z modala „CV Wysłane — stawka do klienta". `payload === null` =
  // rekruter pominął stawkę (ruch i tak następuje). Najpierw ruch (tworzy
  // nowy CandidateStage), potem PATCH stawki na ten najnowszy etap. Obsługuje
  // też kolejkę bulk (jeden modal na kandydata).
  const submitClientRateMove = useCallback(
    async (payload: RatePayload | null) => {
      if (!clientRatePrompt) return;
      const { item, destCol, srcColId } = clientRatePrompt;
      const isBulk = clientRateBulkTotal > 1;

      applyOptimistic(item, srcColId, destCol);
      // Zapytanie strony odświeżamy PO zapisie stawki — inaczej kolejki kroków
      // dostałyby „CV Wysłane" bez stawki, którą zaraz zapiszemy.
      let failureReason: string | null = null;
      // Pipeline v4: stawka jedzie w tym samym żądaniu co ruch — serwer
      // odmawia ruchu bez niej (poza Nordeą), więc nie ma już stanu
      // „przeniesiono, ale stawki brak".
      const ok = await sendMove(item, destCol, undefined, {
        silent: isBulk,
        deferCacheSync: true,
        checkVersion: !isBulk,
        clientRate: payload ?? undefined,
        onFailure: (r) => {
          failureReason = r;
        },
      });
      if (ok && payload && !isBulk) {
        showSuccess("Przeniesiono na „CV Wysłane” ze stawką do klienta.");
      } else if (!ok && isBulk) {
        // `sendMove` w trybie zbiorczym jest cichy — bez tego toastu karta
        // wracała na miejsce bez słowa wyjaśnienia.
        const failedName =
          `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
        showError(
          `${failedName}: nie udało się przenieść na „CV Wysłane”` +
            (failureReason ? ` — ${failureReason}.` : "."),
        );
        await refreshAfterMove();
      }
      if (ok) syncKanbanCache();

      // Bulk: pokaż modal stawki dla kolejnego kandydata z kolejki (lub zamknij).
      const [next, ...rest] = clientRateQueue;
      setClientRateQueue(rest);
      setClientRatePrompt(
        next ? { item: next.item, destCol, srcColId: next.srcColId } : null
      );
    },
    [
      clientRatePrompt,
      clientRateQueue,
      clientRateBulkTotal,
      applyOptimistic,
      sendMove,
      refreshAfterMove,
      syncKanbanCache,
      showSuccess,
      showError,
    ]
  );

  const requestBulkMove = useCallback(
    async (
      items: KanbanItem[],
      dst: KanbanColumn,
      options?: { onHandled?: () => void }
    ) => {
      const onHandled = options?.onHandled;
      // Karty wraz z kolumną źródłową; karty już w celu pomijamy.
      const entries: MoveEntry[] = [];
      const skippedEntries: { name: string; reason: string }[] = [];
      const dstTerminal = terminalOf(dst);
      for (const candidate of items) {
        const cid = candidate.candidate_id;
        const src = columns.find((c) => c.items.some((i) => i.candidate_id === cid));
        if (!src || colId(src) === colId(dst)) continue;
        const item = src.items.find((i) => i.candidate_id === cid)!;
        // Ruch zbiorczy nie ma okna „Przenieś mimo to", więc karty z
        // ostrzeżeniem widocznym na karcie (weto HM na etapie klienta)
        // POMIJAMY z wyjaśnieniem — nie liczymy ich jako nieudanych. Taką
        // kartę przenosi się pojedynczo, z potwierdzeniem.
        const reason = bulkMoveSkipReason({
          item,
          readOnly,
          terminal: dstTerminal === "rejected" || dstTerminal === "withdrawn",
          targetStage: dst.stage,
        });
        if (reason) {
          skippedEntries.push({ name: itemFullName(item), reason });
          continue;
        }
        entries.push({ item, srcColId: colId(src) });
      }
      if (skippedEntries.length > 0) {
        showError(
          `Pominięto ${skippedEntries.length}: ` +
            skippedEntries.map((b) => `${b.name} — ${b.reason}`).join("; ")
        );
      }
      if (entries.length === 0) {
        onHandled?.();
        return;
      }

      // „Zweryfikowany" pyta o stawkę per kandydat (opcjonalnie — „Pomiń
      // stawkę") → kolejka okien, jedno po drugim.
      if (dst.stage === "verified") {
        if (!canEditRates) {
          showError(RATE_EDIT_DENIED_MESSAGE);
          return;
        }
        setVerifiedBulkTotal(entries.length);
        setVerifiedQueue(entries.slice(1));
        setVerifiedRatePrompt({
          item: entries[0].item,
          destCol: dst,
          srcColId: entries[0].srcColId,
        });
        onHandled?.();
        return;
      }

      // „CV Wysłane" — stawka do klienta per kandydat → kolejka modali.
      // Poza Nordeą (Pipeline v4) tylko DL/admin i bez pomijania stawki.
      if (dst.stage === "cv_sent" && !cproEnabled && !canSendToClient) {
        showError(CLIENT_SEND_DENIED_MESSAGE);
        return;
      }
      if (dst.stage === "cv_sent" && (canWriteClientRate || !cproEnabled)) {
        setClientRateBulkTotal(entries.length);
        setClientRateQueue(entries.slice(1));
        setClientRatePrompt({
          item: entries[0].item,
          destCol: dst,
          srcColId: entries[0].srcColId,
        });
        onHandled?.();
        return;
      }

      // M4 PR-03 (audyt P1.6): zbiorcze zatrudnianie bez wizardu = N draftów
      // kontraktów jednym kliknięciem — wykonuj pojedynczo (z potwierdzeniem).
      if (terminalOf(dst) === "hired") {
        showError("Zatrudnienie oznaczaj pojedynczo — przeciągnij kartę kandydata.");
        return;
      }

      // Etapy terminalne wymagają powodu — jeden modal, wspólny powód dla
      // całego zaznaczenia.
      const bulkTerminal = terminalOf(dst);
      if (bulkTerminal === "rejected" || bulkTerminal === "withdrawn") {
        setPendingRejection({ entries, destCol: dst, terminalType: bulkTerminal });
        onHandled?.();
        return;
      }

      setBulkBusy(true);
      try {
        const failed: { name: string; reason: string }[] = [];
        for (const { item, srcColId } of entries) {
          applyOptimistic(item, srcColId, dst);
          let reason = "nieznany błąd";
          const ok = await sendMove(item, dst, undefined, {
            silent: true,
            deferCacheSync: true,
            checkVersion: false,
            onFailure: (r) => {
              reason = r;
            },
          });
          if (!ok) failed.push({ name: itemFullName(item), reason });
        }
        if (failed.length > 0) {
          showError(bulkMoveFailureMessage(failed, entries.length));
          // `refreshAfterMove` odświeża też zapytanie strony.
          await refreshAfterMove();
        } else {
          syncKanbanCache();
          if (entries.length > 1) {
            showSuccess(`Przeniesiono ${entries.length} kandydatów.`);
          }
        }
        onHandled?.();
      } finally {
        setBulkBusy(false);
      }
    },
    [
      columns,
      readOnly,
      canEditRates,
      canWriteClientRate,
      canSendToClient,
      cproEnabled,
      applyOptimistic,
      sendMove,
      refreshAfterMove,
      syncKanbanCache,
      showError,
      showSuccess,
    ]
  );

  const requestReject = useCallback(
    (
      items: KanbanItem | KanbanItem[],
      toColumn?: KanbanColumn,
      options?: { endedBy?: Exclude<EndedBy, "candidate"> }
    ) => {
      const dst = toColumn ?? columns.find((c) => terminalOf(c) === "rejected");
      if (!dst) return;
      const entries: MoveEntry[] = [];
      for (const candidate of Array.isArray(items) ? items : [items]) {
        const src = columns.find((c) =>
          c.items.some((i) => i.candidate_id === candidate.candidate_id)
        );
        if (!src) continue;
        entries.push({ item: candidate, srcColId: colId(src) });
      }
      if (entries.length === 0) return;
      setPendingRejection({
        entries,
        destCol: dst,
        terminalType: "rejected",
        endedBy: options?.endedBy ?? null,
      });
    },
    [columns]
  );

  const requestWithdraw = useCallback(
    (items: KanbanItem | KanbanItem[]) => {
      const dst = columns.find((c) => terminalOf(c) === "withdrawn");
      if (!dst) {
        showError("Ten szablon nie ma etapu „Wycofany” — użyj „Odrzuć”.");
        return;
      }
      const entries: MoveEntry[] = [];
      for (const candidate of Array.isArray(items) ? items : [items]) {
        const src = columns.find((c) =>
          c.items.some((i) => i.candidate_id === candidate.candidate_id)
        );
        if (!src) continue;
        entries.push({ item: candidate, srcColId: colId(src) });
      }
      if (entries.length === 0) return;
      setPendingRejection({ entries, destCol: dst, terminalType: "withdrawn" });
    },
    [columns, showError]
  );

  const confirmRejection = (
    reasonId: string,
    notes: string,
    sendRejectionEmail: boolean | null | undefined,
    candidateOfferResponse: "pending" | "accepted" | "declined" | null | undefined,
    freeReason?: string,
    endedBy?: EndedBy
  ) => {
    if (!pendingRejection) return;
    const { entries, destCol } = pendingRejection;
    setPendingRejection(null);
    void (async () => {
      const failed: { name: string; reason: string }[] = [];
      for (const { item, srcColId } of entries) {
        applyOptimistic(item, srcColId, destCol);
        let failureReason = "nieznany błąd";
        const ok = await sendMove(
          item,
          destCol,
          {
            id: reasonId,
            notes,
            sendRejectionEmail,
            candidateOfferResponse: candidateOfferResponse ?? null,
            freeReason,
            endedBy,
          },
          {
            silent: entries.length > 1,
            deferCacheSync: entries.length > 1,
            checkVersion: entries.length === 1,
            onFailure: (r) => {
              failureReason = r;
            },
          }
        );
        if (!ok) failed.push({ name: itemFullName(item), reason: failureReason });
      }
      if (failed.length > 0) {
        if (entries.length > 1) {
          showError(bulkMoveFailureMessage(failed, entries.length));
        }
        await refreshAfterMove();
      } else if (entries.length > 1) {
        syncKanbanCache();
        showSuccess(`Przeniesiono ${entries.length} kandydatów.`);
      }
    })();
  };

  const dialogs: ReactNode = (
    <>
      <RejectionV2
        open={pendingRejection !== null}
        onOpenChange={(v) => !v && setPendingRejection(null)}
        terminalType={pendingRejection?.terminalType ?? "rejected"}
        reasons={job.rejectionReasons}
        previousStageCategory={(() => {
          const firstSrc = pendingRejection?.entries[0]?.srcColId;
          if (!firstSrc) return null;
          const cat = columns.find((c) => colId(c) === firstSrc)?.category;
          return cat === "external" ? "external" : cat === "internal" ? "internal" : null;
        })()}
        previousStage={
          pendingRejection
            ? columns.find(
                (c) => colId(c) === pendingRejection.entries[0]?.srcColId
              )?.stage ?? null
            : null
        }
        onConfirm={confirmRejection}
        initialEndedBy={pendingRejection?.endedBy ?? null}
        canEndAsDeliveryLead={canEndAsDeliveryLead}
      />

      {debriefRequired && (
        <DebriefRequiredDialog
          open
          onOpenChange={(open) => {
            if (!open) {
              setDebriefRequired(null);
              void refreshAfterMove();
            }
          }}
          eventId={debriefRequired.eventId}
          candidateName={itemFullName(debriefRequired.item)}
          jobId={jobId}
          onSaved={() => void debriefRequired.retry()}
        />
      )}

      {/* „Zweryfikowany" — stawka opcjonalna, podpowiedź z profilu kandydata */}
      {verifiedRatePrompt && (
        <VerifiedRateModal
          key={verifiedRatePrompt.item.id}
          open={true}
          onOpenChange={(v) => {
            if (!v) {
              // Anulowanie przerywa też resztę bulk-kolejki.
              setVerifiedRatePrompt(null);
              setVerifiedQueue([]);
              setVerifiedBulkTotal(0);
            }
          }}
          candidateName={
            (`${verifiedRatePrompt.item.name ?? ""} ${verifiedRatePrompt.item.lastname ?? ""}`.trim() ||
              "Kandydat") +
            (verifiedBulkTotal > 1
              ? ` (${verifiedBulkTotal - verifiedQueue.length}/${verifiedBulkTotal})`
              : "")
          }
          jobBudgetHourly={job.budgetHourly}
          initialRateHourly={verifiedRatePrompt.item.candidate_expected_rate_hourly ?? null}
          onConfirm={(payload) => void submitVerifiedMove(payload)}
          onSkip={() => void submitVerifiedMove(null)}
        />
      )}

      {/* „CV Wysłane" — rekruter podaje stawkę do klienta (lub pomija) */}
      {clientRatePrompt && (
        <ClientRateModal
          key={clientRatePrompt.item.id}
          open={true}
          onOpenChange={(v) => {
            if (!v) {
              // Anulowanie (X/Escape) przerywa też resztę bulk-kolejki.
              setClientRatePrompt(null);
              setClientRateQueue([]);
              setClientRateBulkTotal(0);
            }
          }}
          candidateName={
            (`${clientRatePrompt.item.name ?? ""} ${clientRatePrompt.item.lastname ?? ""}`.trim() ||
              "Kandydat") +
            (clientRateBulkTotal > 1
              ? ` (${clientRateBulkTotal - clientRateQueue.length}/${clientRateBulkTotal})`
              : "")
          }
          onConfirm={(payload) => submitClientRateMove(payload)}
          onSkip={() => submitClientRateMove(null)}
          required={!cproEnabled}
        />
      )}

      {/* M4 PR-03 (audyt P1.6): potwierdzenie przed hired — powstają artefakty */}
      {hiredConfirm && (
        <Dialog open onOpenChange={(o) => !o && setHiredConfirm(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Potwierdź zatrudnienie</DialogTitle>
              <DialogDescription>
                {`${hiredConfirm.item.name ?? ""} ${hiredConfirm.item.lastname ?? ""}`.trim() ||
                  "Kandydat"}{" "}
                trafi na etap „Zatrudniony”. System spróbuje założyć szkic kontraktu
                i zamówienia; jeśli się nie uda, zatrudnienie i tak zostanie zapisane,
                a Delivery dostanie powiadomienie z powodem.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setHiredConfirm(null)}>
                Anuluj
              </Button>
              <Button
                onClick={() => {
                  const { item, destCol, srcColId } = hiredConfirm;
                  setHiredConfirm(null);
                  applyOptimistic(item, srcColId, destCol);
                  void sendMove(item, destCol);
                }}
              >
                Potwierdź zatrudnienie
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {/* 409 ELIGIBILITY_WARNING (17.09.2026) — jedno pytanie, potem ten sam ruch
          z potwierdzeniem. Czarna lista / NDA / konkurent / weto HM nie blokują. */}
      {eligibilityWarning && (
        <Dialog
          open={true}
          onOpenChange={(v: boolean) => {
            if (!v) void dismissEligibilityWarning();
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Ostrzeżenie przed przeniesieniem</DialogTitle>
              <DialogDescription>{eligibilityWarning.reason}</DialogDescription>
            </DialogHeader>
            <DialogBody>
              <p className="text-sm text-muted-foreground">
                Ruch jest możliwy — zapiszemy w historii, kto go potwierdził.
              </p>
            </DialogBody>
            <DialogFooter>
              <Button variant="ghost" onClick={() => void dismissEligibilityWarning()}>
                Anuluj
              </Button>
              <Button onClick={() => void eligibilityWarning.retry()}>
                Przenieś mimo to
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );

  return {
    requestMove,
    requestBulkMove,
    requestReject,
    requestWithdraw,
    isMoving: bulkBusy,
    dialogs,
  };
}
