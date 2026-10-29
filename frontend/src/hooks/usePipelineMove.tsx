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
 * - „Zatrudniony" wymaga potwierdzenia; „Zweryfikowany" pyta o stawkę tylko
 *   wtedy, gdy para jej jeszcze nie ma (D2, 14.10.2026 — stawka etapu jest na
 *   karcie, serwer przenosi ją z poprzedniego wiersza); „CV wysłane" pyta
 *   o stawkę do klienta tylko przy `canWriteClientRate`;
 * - ruch zbiorczy = pętla pojedynczych ruchów i kolejki okien, nigdy `/bulk-move`;
 * - strzałka „→” na karcie (`deferMove`, 14.10.2026): karta przechodzi od razu,
 *   żądanie idzie po 10 s albo przy zamknięciu Tablicy, „Cofnij” w komunikacie
 *   wraca bez żądania;
 * - „Rozmowa u klienta” pyta „Kiedy rozmowa?” (20.10.2026), chyba że para ma
 *   zaplanowaną rozmowę albo otwarte terminy od klienta; termin zakłada
 *   rozmowę PO udanym ruchu (`POST /api/interview-cycle/client-interviews`).
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import api, {
  b2bGeneratorApi,
  pipelineApi,
  type B2BGeneratedContractRow,
  type RateUnit,
} from "@/lib/api";
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
import { useClientRateHistory } from "@/lib/api/clientRateHistory";
import { canViewClientRate } from "@/lib/client-rate-access";
import { RejectionV2, type EndedBy } from "@/components/v2/modals/RejectionV2";
import type { RejectionWorkModeChoice } from "@/components/v2/modals/RejectionWorkModeField";
import {
  rejectionRateMoveFields,
  type RejectionRateChoice,
} from "@/components/v2/modals/RejectionRateField";
import {
  autofillMoveFields,
  needsAutofillReason,
  type AutofillFeedbackChoice,
} from "@/lib/autofill-feedback";
import { placeStage } from "@/lib/board-stages";
import {
  useRejectionProfileWorkMode,
  useRejectionProfileRate,
  useRejectionWorkModeJob,
} from "@/hooks/useRejectionWorkModeContext";
import type { RejectFollowUp } from "@/lib/reject-follow-up";
import {
  announceRejectionEmail,
  rejectionEmailAvailableFrom,
  rejectionEmailBulkSkipMessage,
  type RejectionEmailText,
} from "@/lib/rejection-email";
import { TwinSkipDialog } from "@/components/v2/jobs/twins/TwinSkipDialog";
import { DebriefRequiredDialog } from "@/components/v2/recruitment/DebriefRequiredDialog";
import {
  ClientInterviewDateDialog,
  type ClientInterviewDate,
} from "@/components/v2/recruitment/ClientInterviewDateDialog";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import {
  colId,
  type KanbanColumn,
  type KanbanItem,
} from "@/components/v2/pages/kanban-shared";
import { celebrate } from "@/lib/celebrate";
import { generatorPrefillHref } from "@/lib/b2b-generator-register";
import { pendingAgreement } from "@/lib/b2b-agreement";
import type { ClientAcceptancePayload } from "@/lib/client-acceptance";
import { apiErrorMessage } from "@/lib/api-error";
import { championRemovalOutcome, type JobChampionsFields } from "@/lib/job-champions";
import { EmploymentNotice } from "@/components/v2/employment/EmploymentNotice";
import dynamic from "next/dynamic";
import {
  HIRED_SIGNED_VIA_OPTIONS,
  hiredReasonComplete,
  verifiedRequirementsOf,
  HIRED_CURRENT_ENGAGEMENT_OPTIONS,
  type HiredCurrentEngagement,
  type HiredSignedVia,
  type VerifiedRequirementsMissing,
} from "@/lib/verified-gate";
import { terminalOf } from "@/lib/kanban-terminal";
import { moveDialogFor, movesBackTo, needsInterviewDate } from "@/lib/pipeline-move-dialog";
import { hasPermission, permissionLabel } from "@/lib/permissions";
import { assignErrorMessage } from "@/lib/assign-error";
import {
  cvQcFailureOf,
  debriefRequiredOf,
  twinRequiredOf,
  type CvQcFailure,
  type PipelineMoveResult,
  type TwinScreeningRequired,
} from "@/lib/pipeline-move-core";
import {
  formatExpectedRate,
  knownClientRate,
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
import { invalidateAfterPipelineMove } from "@/lib/pipeline-move-invalidation";
import {
  eligibilityWarningReason,
  isEligibilityWarning,
} from "@/lib/pipeline-eligibility-warning";

// Lustro `RECRUITMENT_RATE_EDIT_ROLES` (backend/app/api/recruitment_access.py):
// ruch na „Zweryfikowany" może zapisać stawkę kandydata i poza tymi rolami
// serwer odpowiada 403. Okno stawki dla innej roli kończyłoby się odmową PO
// wpisaniu kwoty, więc ekran mówi o tym przed. Od 02.10.2026 to każda rola
// wewnętrzna (także Talent Community Manager) — bez roli podglądu.
const RATE_EDIT_ROLES = new Set([
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "recruiter",
  "finance",
]);

// Okno „Oznacz jako podpisaną” żyje w module Generatora (6 tys. linii) —
// Tablica ładuje je dopiero, gdy ktoś potwierdza podpis z okna zatrudnienia.
const ConfirmFullySignedDialog = dynamic(
  () =>
    import("@/components/v2/pages/B2BContractGeneratorV2").then(
      (m) => m.ConfirmFullySignedDialog,
    ),
  { ssr: false },
);

export const RATE_EDIT_DENIED_MESSAGE =
  "Ruch na „Zweryfikowany” może zapisać stawkę kandydata — mogą go wykonać: rekruter, Delivery Lead, Talent Community Manager, Head of Recruitment, Finanse lub administrator.";

export type { RejectFollowUp };

export interface PipelineRejectionReasonOption {
  id: string;
  label: string;
  /** Klucz danych powodu — po nim okno rozpoznaje „Nie akceptuje trybu pracy”. */
  name?: string;
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
  /**
   * 409 `CV_QC_FAILED` (Rekrutacja v5): bramka QC odmówiła wysłania CV.
   * Wołający otwiera okno QC CV dla `stageId`; bez tej opcji hook pokazuje
   * sam komunikat serwera.
   */
  onCvQcFailed?: (failure: CvQcFailure, item: KanbanItem) => void;
  /**
   * 409 `VERIFIED_REQUIREMENTS_MISSING` (D1, 04.10.2026): wejście na
   * „Zweryfikowany” bez arkusza screeningu albo stawki. Wołający otwiera
   * arkusz (`screeningStageId`); bez tej opcji hook pokazuje komunikat.
   */
  onVerifiedRequirementsMissing?: (info: VerifiedRequirementsMissing, item: KanbanItem) => void;
}

interface MoveEntry {
  item: KanbanItem;
  srcColId: string;
}

/** Ile karta po strzałce „→” czeka na ekranie, zanim ruch pójdzie do serwera. */
export const DEFERRED_MOVE_MS = 10_000;

/** Odłożony ruch strzałką „→” — jeszcze nie wysłany. */
interface DeferredMove {
  item: KanbanItem;
  srcColId: string;
  dst: KanbanColumn;
  timer: ReturnType<typeof setTimeout>;
  /** Cofnięcie stanu optymistycznego, jeśli adapter je dał. */
  rollback: void | (() => void);
}

/**
 * D2 (14.10.2026): para ma już stawkę etapu — z karty albo przeniesioną przez
 * serwer z poprzedniego wiersza (`carried_expected_rate`). Ruch na
 * „Zweryfikowany” idzie wtedy bez okna stawki.
 */
function hasStageRate(item: KanbanItem): boolean {
  return item.expected_rate_value != null && item.expected_rate_value !== "";
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
  // Temat i treść maila poprawione w oknie odrzucenia (tylko jedna osoba).
  emailText?: RejectionEmailText | null;
  // „Nie akceptuje trybu pracy” (14.10.2026): dni w biurze i zapis na profilu
  // — ten sam wybór dla każdej odrzucanej osoby.
  workMode?: RejectionWorkModeChoice | null;
  // Osoba od systemu (23.10.2026): powód dla systemu — tylko przy osobie,
  // która go wymaga (`needsAutofillReason`).
  autofill?: AutofillFeedbackChoice | null;
  // „Za wysokie oczekiwania finansowe” (26.10.2026): nowa stawka — tylko
  // przy jednej osobie (okno nie pyta przy kilku).
  rate?: RejectionRateChoice | null;
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
  // D2 (04.10.2026): jak podpisano umowę przy ręcznym ruchu na „Zatrudniony”.
  hiredSignedVia?: { via: HiredSignedVia; note: string };
  // 12.10.2026: „Co z obecną współpracą?” — osoba ma umowę u innego klienta.
  hiredCurrentEngagement?: HiredCurrentEngagement;
  // Runda 10 (R10-V2-1): ruch zbiorczy zbiera statusy maila odrzucenia
  // i mówi o niezaplanowanych RAZ, po pętli.
  onRejectionEmailStatus?: (status: string | null) => void;
  // 13.10.2026: ruch potwierdzony przez serwer — także ponowiony po
  // „Przenieś mimo to” i po debriefie (oba niosą te same `opts`).
  onMoved?: () => void;
  // 0451 (16.10.2026): okno „Klient zaakceptował” — data akceptacji i start.
  clientAcceptance?: ClientAcceptancePayload;
  // 0614: pominięcie bliźniaka z powodem (`TwinSkipDialog`).
  twinSkips?: Record<string, string>;
}

type RatePayload = {
  rate: number;
  unit: RateUnit;
  currency: string;
  /** „To jego nowe minimum” (0414). */
  isMinimum?: boolean;
};

// Pipeline v4 (23.09.2026): poza klientem z kolejką Cpro CV wysyła osoba
// z uprawnieniem „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta” (lustro
// `pipeline_move_rules.assert_client_send_allowed`) — domyślnie Delivery Lead
// i administrator, ale o tym, kto je ma, decyduje panel „Osoby i role”.
// Odrzucenie „przez DL” (`DL_REJECT_ROLES`) zostaje przy rolach, jak w backendzie.
const DL_REJECT_ROLES = new Set(["admin", "delivery_lead", "head_of_recruitment"]);
export const CLIENT_SEND_DENIED_MESSAGE = `Do klienta wysyła osoba z uprawnieniem „${permissionLabel("recruitment_manage")}” — kandydat czeka w „QC CV” na jej przegląd.`;

// Rozpoznanie odmów serwera żyje w `lib/pipeline-move-core.ts` — jedno dla
// Tablicy i ekranów z własnym ruchem. Eksport zostaje dla dotychczasowych importów.
export { cvQcFailureOf, type CvQcFailure } from "@/lib/pipeline-move-core";

/** Dodatki pojedynczego ruchu (karta, dok, okno „Klient zaakceptował”). */
export interface RequestMoveOptions {
  taskAssigneeId?: number;
  /** 0451: data akceptacji i planowany start — ruch na etap akceptacji. */
  clientAcceptance?: ClientAcceptancePayload;
  /** Serwer przyjął ruch (także po „Przenieś mimo to” i debriefie). */
  onMoved?: () => void;
  /**
   * Bez okna „Kiedy rozmowa u klienta?” — karta wraca po odbytej rozmowie
   * („Cofnij akceptację klienta”, audyt 21.10.2026). Powrót z kolumny za
   * „Rozmową” hook rozpoznaje sam (`movesBackTo`).
   */
  skipInterviewDate?: boolean;
}

export interface PipelineMoveControls {
  /** Ta sama decyzja co przeciągnięcie karty na tablicy. */
  requestMove: (
    item: KanbanItem,
    fromColumn: KanbanColumn | string,
    toColumn: KanbanColumn,
    options?: RequestMoveOptions
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
   *  wybiera „kto kończy", `notes` wstawia notatkę startową (np. naruszone
   *  „Odpada, gdy…” z wymagań ruchu). */
  requestReject: (
    items: KanbanItem | KanbanItem[],
    toColumn?: KanbanColumn,
    options?: {
      endedBy?: Exclude<EndedBy, "candidate">;
      notes?: string | null;
      followUp?: RejectFollowUp;
    }
  ) => void;
  /** „Zrezygnował" — `RejectionV2` na kolumnie „Wycofany". */
  requestWithdraw: (
    items: KanbanItem | KanbanItem[],
    options?: { followUp?: RejectFollowUp }
  ) => void;
  /**
   * Ruch przejdzie bez żadnego okna (stawka, wysyłka, zatrudnienie, powód)
   * i bez ostrzeżenia, które karta już zna — strzałka „→” może go odłożyć.
   */
  canMoveWithoutDialog: (item: KanbanItem, toColumn: KanbanColumn) => boolean;
  /**
   * Strzałka „→” (14.10.2026): karta przechodzi na ekranie od razu, ruch idzie
   * do serwera po `delayMs` (domyślnie 10 s) albo przy zamknięciu Tablicy.
   * Komunikat „<osoba> → <kolumna>” ma „Cofnij” — karta wraca bez żądania.
   * Wołający sprawdza wcześniej `canMoveWithoutDialog`.
   */
  deferMove: (
    item: KanbanItem,
    fromColumn: KanbanColumn | string,
    toColumn: KanbanColumn,
    options: { targetLabel: string; delayMs?: number; detail?: string | null }
  ) => void;
  /** Ruchy czekające na wysłanie — Tablica nakłada je na stan z serwera. */
  pendingMoves: () => ReadonlyArray<{ candidateId: number; toColumn: KanbanColumn }>;
  /**
   * Wyślij od razu odłożony ruch tej osoby (panel osoby czyta stan z serwera).
   * `null` = nic nie czekało, `true`/`false` = serwer przyjął / odmówił.
   */
  commitPendingMove: (candidateId: number) => Promise<boolean | null>;
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
  onCvQcFailed,
  onVerifiedRequirementsMissing,
}: UsePipelineMoveOptions): PipelineMoveControls {
  const queryClient = useQueryClient();
  const { showActionToast, showSuccess, showError } = useToast();
  // Pełny zbiór ról (primary + secondary), nie tylko primary — hybryda ról
  // widzi to, na co pozwala jej którakolwiek z nich (parity z backendem).
  const authUser = useAuthStore((s) => s.user);
  const canEditRates = getUserRoles(authUser).some((r) => RATE_EDIT_ROLES.has(r));
  const canSendToClient = hasPermission(authUser, "recruitment_manage");
  // Bez okna stawki przesuwa tylko konto, które serwer przepuszcza bez bramek
  // pól (`/api/auth/me` → `skips_fill_gates`) — przy wyłączonym
  // `DL_SKIPS_FILL_GATES` DL znowu dostaje okno (audyt 22.10.2026, F109).
  const skipsFillGates = authUser?.skips_fill_gates === true;
  const canEndAsDeliveryLead = getUserRoles(authUser).some((r) => DL_REJECT_ROLES.has(r));

  // Ref, nie zależność: adapter jest zwykle świeżym obiektem przy każdym
  // renderze wołającego, a callbacki ruchu mają zostać stabilne.
  const optimisticRef = useRef(optimistic);
  optimisticRef.current = optimistic;
  const onCvQcFailedRef = useRef(onCvQcFailed);
  onCvQcFailedRef.current = onCvQcFailed;
  const onVerifiedMissingRef = useRef(onVerifiedRequirementsMissing);
  onVerifiedMissingRef.current = onVerifiedRequirementsMissing;
  // Okno „Potwierdź zatrudnienie”: jak podpisano umowę (D2).
  const [hiredVia, setHiredVia] = useState<HiredSignedVia | null>(null);
  const [hiredNote, setHiredNote] = useState("");
  // Osoba ma już trwającą umowę u innego klienta: co z obecną współpracą.
  const [hiredEngagement, setHiredEngagement] = useState<HiredCurrentEngagement | null>(null);
  // 04.10.2026: para ma umowę „W trakcie” w Generatorze — pierwsza opcja to
  // potwierdzenie jej podpisu (ta sama automatyka co w rejestrze), a przy
  // „B2B poza Generatorem” umowa z rejestru zostaje anulowana.
  const [hiredFromGenerator, setHiredFromGenerator] = useState(false);
  const [cancelGeneratorAgreement, setCancelGeneratorAgreement] = useState(true);
  const [hiredBusy, setHiredBusy] = useState(false);
  const [signRow, setSignRow] = useState<B2BGeneratedContractRow | null>(null);

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
    /** Notatka startowa okna odrzucenia. */
    notes?: string | null;
    /** Tylko z panelu osoby i tylko przy jednej osobie. */
    followUp?: RejectFollowUp;
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
  const [verifiedSubmitting, setVerifiedSubmitting] = useState(false);
  const verifiedSubmittingRef = useRef(false);
  // „CV wysłane" → zapytaj o stawkę do klienta (sell rate). Analogiczne do
  // verified, ale stawka jest opcjonalna i zapisywana osobnym PATCH-em po ruchu
  // (kolumny client_rate_* na najnowszym CandidateStage). Bulk = kolejka modali.
  const [clientRatePrompt, setClientRatePrompt] = useState<{
    item: KanbanItem;
    destCol: KanbanColumn;
    srcColId: string;
  } | null>(null);
  const [clientRateQueue, setClientRateQueue] = useState<MoveEntry[]>([]);
  // Para z zamówieniem: stawkę zmienia się w zamówieniu (`order_lock`), więc
  // okno nie przyjmuje kwoty — serwer i tak oddałby 409 (21.10.2026).
  const clientRateHistory = useClientRateHistory(
    clientRatePrompt?.item.candidate_id ?? null,
    jobId,
    clientRatePrompt != null && canViewClientRate(authUser),
  );
  // Pipeline v4: 409 DEBRIEF_REQUIRED — najpierw telefon po rozmowie u klienta
  // i pytania klienta, potem TEN SAM ruch.
  const [twinRequired, setTwinRequired] = useState<{
    refusal: TwinScreeningRequired;
    resend: (skips: Record<string, string>) => Promise<void>;
  } | null>(null);
  const [debriefRequired, setDebriefRequired] = useState<{
    /** `null` — rozmowy nie ma w kalendarzu; okno pyta, kiedy była. */
    eventId: number | null;
    item: KanbanItem;
    retry: () => Promise<void>;
  } | null>(null);
  // Okno debriefu zamknięte ZAPISEM (ruch idzie ponownie), nie „Anuluj”.
  const debriefSavedRef = useRef(false);
  // „Rozmowa u klienta” — „Kiedy rozmowa?” przed ruchem (20.10.2026).
  const [interviewDatePrompt, setInterviewDatePrompt] = useState<{
    item: KanbanItem;
    destCol: KanbanColumn;
    srcColId: string;
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

  // Ostatnie pola, które serwer potwierdził po ruchu (nowe id etapu, wersja
  // procesu), po `candidate_id`. Okno albo pętla trzymające kartę sprzed tego
  // ruchu wysyłają następny ruch już z nimi — strzałka „→” odkłada ruch
  // o 10 s, więc karta sprzed ruchu żyje dłużej niż dawniej.
  const confirmedRef = useRef(
    new Map<number, { fromId: number; patch: PipelineMoveConfirmedPatch }>()
  );
  const latest = useCallback((item: KanbanItem): KanbanItem => {
    const confirmed = confirmedRef.current.get(item.candidate_id);
    return confirmed && confirmed.fromId === item.id ? { ...item, ...confirmed.patch } : item;
  }, []);

  const applyOptimistic = useCallback(
    (item: KanbanItem, srcId: string, dst: KanbanColumn) =>
      optimisticRef.current?.apply(latest(item), srcId, dst),
    [latest]
  );

  // Strona trzyma pipeline pod `["kanban", id]` (`id` to string z `useParams`)
  // i karmi nim listwę kroków, klaster KPI w jobbarze oraz kolejki kroków
  // 05–08. Oba klucze — część konsumentów trzyma liczbę.
  // Wspólna lista z ekranami spoza Tablicy (`lib/pipeline-move-invalidation`):
  // tablica (oba klucze), follow-up osoby, „Czeka na Ciebie”, wymagania ruchu.
  const syncKanbanCache = useCallback(
    (candidateId?: number) => invalidateAfterPipelineMove(queryClient, jobId, candidateId),
    [queryClient, jobId]
  );

  const hiredAgreement = pendingAgreement(hiredConfirm?.item.agreement ?? null);
  // Znacznik „Pracuje u nas” z karty: pytanie o obecną współpracę pojawia się
  // tylko, gdy osoba ma zatrudnienie u klienta innego niż klient rekrutacji.
  const hiredMarker = hiredConfirm?.item.employment_marker ?? null;
  const hiredElsewhere = hiredMarker?.elsewhere === true ? hiredMarker : null;

  const invalidateAgreementViews = useCallback(() => {
    syncKanbanCache();
    void queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    void queryClient.invalidateQueries({ queryKey: ["board-tasks"] });
  }, [queryClient, syncKanbanCache]);

  const closeHiredConfirm = useCallback(() => {
    setHiredConfirm(null);
    setHiredVia(null);
    setHiredNote("");
    setHiredEngagement(null);
    setHiredFromGenerator(false);
    setCancelGeneratorAgreement(true);
  }, []);

  // „Umowa z Generatora jest podpisana”: z uprawnieniem „Podpis B2B” to samo
  // okno co w rejestrze (ono przesuwa kartę na „Zatrudniony” i zakłada
  // kontrakt); bez niego prośba do Delivery Leada (D1). Ruch karty nie idzie.
  const confirmFromGenerator = useCallback(
    async (agreementId: number) => {
      if (!hiredConfirm) return;
      setHiredBusy(true);
      try {
        const rows = await b2bGeneratorApi.generated(20, {
          jobId,
          candidateId: hiredConfirm.item.candidate_id,
        });
        const row = rows.find((r) => r.id === agreementId);
        if (row?.can_confirm_signed) {
          closeHiredConfirm();
          setSignRow(row);
          return;
        }
        const result = await b2bGeneratorApi.requestSignature(agreementId);
        closeHiredConfirm();
        invalidateAgreementViews();
        if (!result.sent) {
          showSuccess("Prośba o potwierdzenie podpisu była już wysłana w ciągu ostatniej doby.");
        } else if (result.recipient_names.length > 0) {
          showSuccess(
            `Wysłano prośbę o potwierdzenie podpisu: ${result.recipient_names.join(", ")}. Karta przejdzie na „Zatrudniony” po potwierdzeniu.`,
          );
        } else {
          showSuccess("Wysłano prośbę o potwierdzenie podpisu.");
        }
      } catch (e) {
        showError(apiErrorMessage(e, "Nie udało się sprawdzić umowy w Generatorze."));
      } finally {
        setHiredBusy(false);
      }
    },
    [hiredConfirm, jobId, closeHiredConfirm, invalidateAgreementViews, showSuccess, showError],
  );

  // Zatrudnienie inną drogą przy umowie „W trakcie” w rejestrze: umowa nie
  // doszła do skutku, więc „Anulowana” (numer zostaje zużyty).
  const cancelAgreement = useCallback(
    async (agreementId: number) => {
      try {
        await b2bGeneratorApi.updateGenerated(agreementId, { contract_status: "cancelled" });
        invalidateAgreementViews();
      } catch (e) {
        showError(
          apiErrorMessage(
            e,
            "Kandydat jest zatrudniony, ale nie udało się anulować umowy w rejestrze — zrób to w Generatorze.",
          ),
        );
      }
    },
    [invalidateAgreementViews, showError],
  );

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
      movedItem: KanbanItem,
      dst: KanbanColumn,
      reason?: MoveReason,
      opts?: SendMoveOptions
    ): Promise<boolean> => {
      const item = latest(movedItem);
      try {
        const response = await api.post<PipelineMoveResult>("/api/pipeline/move", {
          candidate_id: item.candidate_id,
          job_id: jobId,
          stage: dst.stage,
          stage_def_id: dst.stage_def_id ?? undefined,
          rejection_reason_id: reason?.id || undefined,
          rejection_reason: reason?.freeReason || undefined,
          notes: reason?.notes,
          send_rejection_email: reason?.sendRejectionEmail ?? undefined,
          rejection_email_subject: reason?.emailText?.subject,
          rejection_email_body: reason?.emailText?.body,
          rejection_email_other_processes: reason?.emailText?.otherProcesses,
          rejection_email_merge: reason?.emailText?.merge,
          work_mode_max_onsite_days: reason?.workMode?.maxOnsiteDays ?? undefined,
          work_mode_save_to_profile: reason?.workMode
            ? reason.workMode.saveToProfile
            : undefined,
          ...autofillMoveFields(reason?.autofill),
          ...rejectionRateMoveFields(reason?.rate),
          candidate_offer_response: reason?.candidateOfferResponse ?? undefined,
          expected_state_version:
            opts?.checkVersion === false ? undefined : expectedStateVersionOf(item),
          acknowledge_eligibility: opts?.acknowledgeEligibility ? true : undefined,
          task_assignee_id: opts?.taskAssigneeId ?? undefined,
          ended_by: reason?.endedBy ?? undefined,
          client_rate_value: opts?.clientRate?.rate ?? undefined,
          client_rate_unit: opts?.clientRate?.unit ?? undefined,
          client_rate_currency: opts?.clientRate?.currency ?? undefined,
          hired_signed_via: opts?.hiredSignedVia?.via ?? undefined,
          hired_signed_note: opts?.hiredSignedVia?.note.trim() || undefined,
          hired_current_engagement: opts?.hiredCurrentEngagement ?? undefined,
          client_accepted_on: opts?.clientAcceptance?.acceptedOn ?? undefined,
          planned_start_on: opts?.clientAcceptance?.plannedStartOn ?? undefined,
          twin_skips: opts?.twinSkips,
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
          confirmedRef.current.set(item.candidate_id, { fromId: item.id, patch });
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
        // Runda 9 (R9-N11-2) / 10 (R10-V2-1): zaznaczony mail, którego
        // serwer nie zaplanował — mówimy dlaczego, zamiast ciszy.
        announceRejectionEmail(response?.data, {
          requested: reason?.sendRejectionEmail,
          reportSkip: !opts?.silent,
          toast: { showActionToast, showSuccess, showError },
          cancel: (id) => api.post(`/api/rejection-emails/${id}/cancel`),
        });
        if (
          reason?.sendRejectionEmail &&
          !response?.data?.scheduled_rejection_email_id
        ) {
          opts?.onRejectionEmailStatus?.(
            response?.data?.rejection_email_status ?? null
          );
        }

        if (!opts?.deferCacheSync) syncKanbanCache(item.candidate_id);
        opts?.onMoved?.();
        return true;
      } catch (e) {
        console.error("Move failed", e);
        if (opts?.silent) {
          opts.onFailure?.(
            isEligibilityWarning(e)
              ? (eligibilityWarningReason(e) ?? "serwer ostrzega przed tym ruchem")
              : cvQcFailureOf(e)
                ? (cvQcFailureOf(e) as CvQcFailure).message
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
        const debriefRefusal = debriefRequiredOf(e);
        if (!opts?.silent && debriefRefusal) {
          setDebriefRequired({
            eventId: debriefRefusal.eventId,
            item,
            retry: async () => {
              setDebriefRequired(null);
              const moved = await sendMoveRef.current?.(item, dst, reason, opts);
              // Tablica po debriefie (05.10.2026): odczyt tablicy, który
              // ruszył PRZED zapisem ruchu, nadpisywał kartę stanem sprzed
              // niego. Ten odczyt startuje dopiero po potwierdzeniu ruchu.
              if (moved) await refreshAfterMove();
            },
          });
          return false;
        }
        const twinRefusal = twinRequiredOf(e);
        if (!opts?.silent && twinRefusal) {
          // 0614: karta wraca na miejsce; okno — screening razem w panelu osoby
          // albo pominięcie bliźniaka z powodem i ten sam ruch.
          await refreshAfterMove();
          setTwinRequired({
            refusal: twinRefusal,
            resend: async (skips) => {
              setTwinRequired(null);
              const moved = await sendMoveRef.current?.(item, dst, reason, {
                ...opts,
                twinSkips: { ...opts?.twinSkips, ...skips },
              });
              if (moved) await refreshAfterMove();
            },
          });
          return false;
        }
        const verifiedMissing = verifiedRequirementsOf(e);
        if (!opts?.silent && verifiedMissing) {
          // D1: karta wraca na miejsce, a wołający otwiera arkusz screeningu
          // (brak stawki dopisuje okno „Zweryfikowany”).
          showError(verifiedMissing.message);
          await refreshAfterMove();
          onVerifiedMissingRef.current?.(verifiedMissing, item);
          return false;
        }
        const qcFailure = cvQcFailureOf(e);
        if (!opts?.silent && qcFailure) {
          // Bramka QC CV: karta wraca na miejsce (prawda serwera), a wołający
          // otwiera okno QC — tam są poprawki i obejście DL/admina.
          showError(qcFailure.message);
          await refreshAfterMove();
          onCvQcFailedRef.current?.(qcFailure, item);
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
      latest,
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

  // ── Strzałka „→”: ruch odłożony o 10 s z „Cofnij” (14.10.2026) ──────────
  const deferredRef = useRef(new Map<number, DeferredMove>());
  const [deferredCount, setDeferredCount] = useState(0);
  const dropDeferred = useCallback((candidateId: number): DeferredMove | null => {
    const pending = deferredRef.current.get(candidateId) ?? null;
    if (!pending) return null;
    clearTimeout(pending.timer);
    deferredRef.current.delete(candidateId);
    setDeferredCount(deferredRef.current.size);
    return pending;
  }, []);
  // Wysyła odłożony ruch tej osoby od razu. `true` = nic nie czekało albo
  // serwer przyjął ruch (błąd pokazuje i cofa sam `sendMove`).
  const commitDeferred = useCallback(
    async (candidateId: number): Promise<boolean> => {
      const pending = dropDeferred(candidateId);
      if (!pending) return true;
      return (await sendMoveRef.current?.(pending.item, pending.dst)) ?? false;
    },
    [dropDeferred]
  );
  // „Cofnij”: karta wraca na miejsce, do serwera nic nie idzie.
  const cancelDeferred = useCallback(
    (candidateId: number) => {
      const pending = dropDeferred(candidateId);
      if (!pending) {
        showError("Ruch jest już zapisany — przesuń osobę z powrotem ręcznie.");
        return;
      }
      if (typeof pending.rollback === "function") pending.rollback();
      else void optimisticRef.current?.sync?.();
    },
    [dropDeferred, showError]
  );
  // Tablica znika (inna strona, zamknięty panel rekrutacji) — odłożone ruchy
  // idą od razu, nie przepadają.
  useEffect(() => {
    const pending = deferredRef.current;
    return () => {
      for (const candidateId of Array.from(pending.keys())) {
        void commitDeferred(candidateId);
      }
    };
  }, [commitDeferred]);
  // Zamknięcie karty przeglądarki przed wysłaniem — przeglądarka pyta.
  useEffect(() => {
    if (deferredCount === 0) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [deferredCount]);

  const requestMove = useCallback(
    (
      rawItem: KanbanItem,
      fromColumn: KanbanColumn | string,
      dst: KanbanColumn,
      options?: RequestMoveOptions
    ) => {
      const srcColId = typeof fromColumn === "string" ? fromColumn : colId(fromColumn);
      if (readOnly) return;
      if (srcColId === colId(dst)) return;
      // Odłożony ruch tej osoby czeka jeszcze na wysłanie: najpierw on, potem
      // ten — już z wersją procesu po pierwszym (`latest`).
      if (deferredRef.current.has(rawItem.candidate_id)) {
        void commitDeferred(rawItem.candidate_id).then((ok) => {
          if (ok) requestMoveRef.current?.(rawItem, srcColId, dst, options);
        });
        return;
      }
      const item = latest(rawItem);

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
      // D2 (14.10.2026): para ma już stawkę etapu — ruch bez okna, jak każdy
      // inny (serwer przenosi stawkę; brak arkusza = 409 i formularz).
      // 22.10.2026: Delivery Lead przesuwa bez bramek pól — także bez okna
      // stawki (brak zostaje odznaką na karcie, `requirements_skipped`).
      if (dialog === "verified_rate" && (hasStageRate(item) || skipsFillGates)) {
        applyOptimistic(item, srcColId, dst);
        void sendMove(item, dst);
        return;
      }
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

      // „CV wysłane" bez kolejki Cpro (Pipeline v4): wysyła osoba z uprawnieniem
      // do prowadzenia rekrutacji, stawka wymagana.
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

      // „CV wysłane" — zapytaj o stawkę do klienta przed ruchem (rekruter może
      // pominąć lub anulować w modalu, dlatego NIE applyOptimistic tutaj).
      if (dialog === "client_rate" && canWriteClientRate) {
        setClientRateQueue([]);
        setClientRateBulkTotal(1);
        setClientRatePrompt({ item, destCol: dst, srcColId });
        return;
      }

      // „Rozmowa u klienta” bez terminu w NEXUSIE — najpierw „Kiedy rozmowa?”.
      // NIE applyOptimistic tu: „Anuluj” zostawia kartę na miejscu.
      if (
        dialog === "interview_date" &&
        !options?.skipInterviewDate &&
        !movesBackTo(columns, srcColId, dst, colId) &&
        needsInterviewDate(item)
      ) {
        setInterviewDatePrompt({ item, destCol: dst, srcColId });
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
      sendMove(item, dst, undefined, {
        taskAssigneeId: options?.taskAssigneeId,
        clientAcceptance: options?.clientAcceptance,
        onMoved: options?.onMoved,
      });
    },
    [
      readOnly,
      latest,
      commitDeferred,
      applyOptimistic,
      sendMove,
      showError,
      canEditRates,
      canWriteClientRate,
      canSendToClient,
      skipsFillGates,
      cproEnabled,
      columns,
    ]
  );
  const requestMoveRef = useRef(requestMove);
  requestMoveRef.current = requestMove;

  const canMoveWithoutDialog = useCallback(
    (item: KanbanItem, dst: KanbanColumn): boolean => {
      if (readOnly) return false;
      const dstTerminal = terminalOf(dst);
      const terminal = dstTerminal === "rejected" || dstTerminal === "withdrawn";
      // Weto HM i globalna czarna lista: serwer zapyta „Przenieś mimo to” —
      // takie pytanie nie może przyjść 10 s po kliknięciu.
      if (
        bulkMoveSkipReason({ item, readOnly, terminal, targetStage: dst.stage, targetColumn: dst }) ||
        (item.warnings ?? []).includes("blacklisted")
      ) {
        return false;
      }
      switch (moveDialogFor(dst)) {
        case "none":
          return true;
        case "verified_rate":
          return hasStageRate(latest(item)) || skipsFillGates;
        case "client_rate":
          return cproEnabled && !canWriteClientRate;
        case "interview_date":
          return !needsInterviewDate(latest(item));
        default:
          return false;
      }
    },
    [readOnly, latest, cproEnabled, canWriteClientRate, skipsFillGates]
  );

  const deferMove = useCallback(
    (
      item: KanbanItem,
      fromColumn: KanbanColumn | string,
      dst: KanbanColumn,
      options: { targetLabel: string; delayMs?: number; detail?: string | null }
    ) => {
      if (readOnly) return;
      const srcColId = typeof fromColumn === "string" ? fromColumn : colId(fromColumn);
      if (srcColId === colId(dst)) return;
      // Druga strzałka przed wysłaniem pierwszej: pierwszy ruch idzie od razu,
      // ten czeka już z wersją procesu po nim.
      if (deferredRef.current.has(item.candidate_id)) {
        void commitDeferred(item.candidate_id).then((ok) => {
          if (ok) deferMoveRef.current?.(item, srcColId, dst, options);
        });
        return;
      }
      const current = latest(item);
      const delayMs = options.delayMs ?? DEFERRED_MOVE_MS;
      const rollback = applyOptimistic(current, srcColId, dst);
      const timer = setTimeout(() => void commitDeferred(current.candidate_id), delayMs);
      deferredRef.current.set(current.candidate_id, { item: current, srcColId, dst, timer, rollback });
      setDeferredCount(deferredRef.current.size);
      const detail = options.detail ? ` · ${options.detail}` : "";
      showActionToast(`${itemFullName(current)} → ${options.targetLabel}${detail}`, {
        actionLabel: "Cofnij",
        onAction: () => cancelDeferred(current.candidate_id),
        durationMs: delayMs,
      });
    },
    [readOnly, latest, applyOptimistic, commitDeferred, cancelDeferred, showActionToast]
  );
  const deferMoveRef = useRef(deferMove);
  deferMoveRef.current = deferMove;

  const pendingMoves = useCallback(
    () =>
      Array.from(deferredRef.current.values()).map((pending) => ({
        candidateId: pending.item.candidate_id,
        toColumn: pending.dst,
      })),
    []
  );
  const commitPendingMove = useCallback(
    async (candidateId: number): Promise<boolean | null> =>
      deferredRef.current.has(candidateId) ? commitDeferred(candidateId) : null,
    [commitDeferred]
  );

  // Submit z okna „Kiedy rozmowa?”. Ruch idzie jak zwykle; termin zakłada
  // rozmowę dopiero po potwierdzonym ruchu — odmowa ruchu nie zostawia
  // w kalendarzu rozmowy osoby, która nie przeszła dalej.
  const submitInterviewDateMove = useCallback(
    (value: ClientInterviewDate | null) => {
      const prompt = interviewDatePrompt;
      if (!prompt) return;
      setInterviewDatePrompt(null);
      const { item, destCol, srcColId } = prompt;
      applyOptimistic(item, srcColId, destCol);
      void sendMove(item, destCol, undefined, {
        onMoved: value
          ? () => {
              void interviewCycleApi
                .createClientInterview({
                  candidate_id: item.candidate_id,
                  job_id: jobId,
                  start: value.start,
                  duration_minutes: value.durationMinutes,
                })
                .then(() => {
                  queryClient.invalidateQueries({ queryKey: ["interview-cycle"] });
                  queryClient.invalidateQueries({ queryKey: ["kanban"] });
                })
                .catch((err) =>
                  showError(
                    apiErrorMessage(
                      err,
                      "Kandydat jest na „Rozmowa u klienta”, ale terminu rozmowy nie udało się zapisać.",
                    ),
                  ),
                );
            }
          : undefined,
      });
    },
    [interviewDatePrompt, applyOptimistic, sendMove, jobId, queryClient, showError]
  );

  // Submit z okna „Zweryfikowany". `payload === null` = „Pomiń stawkę" (stawka
  // opcjonalna od 17.09.2026). `acknowledge` = powtórka po 409
  // ELIGIBILITY_WARNING; kolejka zbiorcza przesuwa się DOPIERO po decyzji.
  const submitVerifiedMove = useCallback(
    async (payload: RatePayload | null, acknowledge = false) => {
      if (!verifiedRatePrompt) return;
      // Runda 10 (R10-N15-7): jeden ruch naraz — ref, bo dwa kliknięcia
      // w tej samej klatce widzą jeszcze stary stan.
      if (verifiedSubmittingRef.current) return;
      verifiedSubmittingRef.current = true;
      setVerifiedSubmitting(true);
      const { destCol, srcColId } = verifiedRatePrompt;
      const item = latest(verifiedRatePrompt.item);
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
                ...(payload.isMinimum ? { expected_rate_is_minimum: true } : {}),
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
        if (newStageId != null && newStageId !== item.id) {
          confirmedRef.current.set(item.candidate_id, {
            fromId: item.id,
            patch: {
              id: newStageId,
              ...(typeof res?.data?.process_state_version === "number"
                ? { process_state_version: res.data.process_state_version }
                : {}),
            },
          });
        }
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
        const verifiedMissing = verifiedRequirementsOf(e);
        if (verifiedMissing) {
          showError(verifiedMissing.message);
          await refreshAfterMove();
          onVerifiedMissingRef.current?.(verifiedMissing, item);
        } else if (isPipelineVersionConflict(e)) {
          showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
          invalidateAfterPipelineVersionConflict(queryClient, jobId, item.candidate_id);
          await refreshAfterMove();
        } else {
          showError(assignErrorMessage(e));
        }
        advanceQueue();
      } finally {
        verifiedSubmittingRef.current = false;
        setVerifiedSubmitting(false);
      }
    },
    [
      verifiedRatePrompt,
      verifiedQueue,
      verifiedBulkTotal,
      latest,
      jobId,
      queryClient,
      refreshAfterMove,
      syncKanbanCache,
      showError,
    ]
  );
  const submitVerifiedMoveRef = useRef<typeof submitVerifiedMove | null>(null);
  submitVerifiedMoveRef.current = submitVerifiedMove;

  // Submit z modala „CV wysłane — stawka do klienta". `payload === null` =
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
      // dostałyby „CV wysłane" bez stawki, którą zaraz zapiszemy.
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
        showSuccess("Przeniesiono na „CV wysłane” ze stawką do klienta.");
      } else if (!ok && isBulk) {
        // `sendMove` w trybie zbiorczym jest cichy — bez tego toastu karta
        // wracała na miejsce bez słowa wyjaśnienia.
        const failedName =
          `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
        showError(
          `${failedName}: nie udało się przenieść na „CV wysłane”` +
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
      // Odłożone ruchy strzałką tych osób idą najpierw — pętla wyśle swoje
      // już z wersją procesu po nich (`latest`).
      await Promise.all(
        items
          .filter((i) => deferredRef.current.has(i.candidate_id))
          .map((i) => commitDeferred(i.candidate_id))
      );
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
          // Runda 10 (R10-X2-4): weto po kolumnie Tablicy, jak serwer.
          targetColumn: dst,
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

      // „Zweryfikowany" pyta o stawkę per kandydat → kolejka okien, jedno po
      // drugim. D2 (14.10.2026): osoby ze stawką etapu idą bez okna, w pętli
      // niżej; okna dostają tylko osoby bez stawki.
      let quietEntries = entries;
      if (dst.stage === "verified") {
        const withoutRate = entries.filter((e) => !hasStageRate(latest(e.item)));
        quietEntries = entries.filter((e) => hasStageRate(latest(e.item)));
        if (withoutRate.length > 0) {
          if (!canEditRates) {
            showError(RATE_EDIT_DENIED_MESSAGE);
            if (quietEntries.length === 0) return;
          } else {
            setVerifiedBulkTotal(withoutRate.length);
            setVerifiedQueue(withoutRate.slice(1));
            setVerifiedRatePrompt({
              item: withoutRate[0].item,
              destCol: dst,
              srcColId: withoutRate[0].srcColId,
            });
          }
        }
        if (quietEntries.length === 0) {
          onHandled?.();
          return;
        }
      }

      // „CV wysłane" — stawka do klienta per kandydat → kolejka modali.
      // Bez kolejki Cpro (Pipeline v4) tylko z uprawnieniem do prowadzenia
      // rekrutacji i bez pomijania stawki.
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
        for (const { item, srcColId } of quietEntries) {
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
          showError(bulkMoveFailureMessage(failed, quietEntries.length));
          // `refreshAfterMove` odświeża też zapytanie strony.
          await refreshAfterMove();
        } else {
          syncKanbanCache();
          if (quietEntries.length > 1) {
            showSuccess(`Przeniesiono ${quietEntries.length} kandydatów.`);
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
      latest,
      commitDeferred,
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
      options?: {
        endedBy?: Exclude<EndedBy, "candidate">;
        notes?: string | null;
        followUp?: RejectFollowUp;
      }
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
      // Odłożony ruch strzałką idzie od razu — odrzucenie po potwierdzeniu
      // wyśle już wersję procesu po nim (`latest`).
      for (const entry of entries) void commitDeferred(entry.item.candidate_id);
      setPendingRejection({
        entries,
        destCol: dst,
        terminalType: "rejected",
        endedBy: options?.endedBy ?? null,
        notes: options?.notes ?? null,
        followUp: entries.length === 1 ? options?.followUp : undefined,
      });
    },
    [columns, commitDeferred]
  );

  const requestWithdraw = useCallback(
    (items: KanbanItem | KanbanItem[], options?: { followUp?: RejectFollowUp }) => {
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
      for (const entry of entries) void commitDeferred(entry.item.candidate_id);
      setPendingRejection({
        entries,
        destCol: dst,
        terminalType: "withdrawn",
        followUp: entries.length === 1 ? options?.followUp : undefined,
      });
    },
    [columns, showError, commitDeferred]
  );

  const confirmRejection = (
    reasonId: string,
    notes: string,
    sendRejectionEmail: boolean | null | undefined,
    candidateOfferResponse: "pending" | "accepted" | "declined" | null | undefined,
    freeReason?: string,
    endedBy?: EndedBy,
    cancelAgreementId?: number | null,
    emailText?: RejectionEmailText | null,
    workMode?: RejectionWorkModeChoice | null,
    autofill?: AutofillFeedbackChoice | null,
    rate?: RejectionRateChoice | null
  ) => {
    if (!pendingRejection) return;
    const { entries, destCol, followUp } = pendingRejection;
    setPendingRejection(null);
    const reasonLabel =
      job.rejectionReasons.find((r) => r.id === reasonId)?.label ?? (freeReason?.trim() || null);
    void (async () => {
      const failed: { name: string; reason: string }[] = [];
      const emailStatuses: (string | null)[] = [];
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
            emailText: entries.length === 1 ? emailText ?? null : null,
            workMode: workMode ?? null,
            autofill: autofill && rejectionNeedsAutofill(item, srcColId) ? autofill : null,
            rate: entries.length === 1 ? rate ?? null : null,
          },
          {
            silent: entries.length > 1,
            deferCacheSync: entries.length > 1,
            checkVersion: entries.length === 1,
            onFailure: (r) => {
              failureReason = r;
            },
            onRejectionEmailStatus: (status) => {
              emailStatuses.push(status);
            },
            onMoved: followUp ? () => followUp.onMoved({ reasonLabel }) : undefined,
          }
        );
        if (!ok) failed.push({ name: itemFullName(item), reason: failureReason });
        else if (cancelAgreementId && entries.length === 1) {
          await cancelAgreement(cancelAgreementId);
        }
      }
      if (entries.length > 1) {
        const emailSkip = rejectionEmailBulkSkipMessage(emailStatuses);
        if (emailSkip) showError(emailSkip);
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

  // Pytanie o dni w biurze przy „Nie akceptuje trybu pracy”: tryb pracy
  // rekrutacji i — przy jednej osobie — profilu (te same zapytania co strona
  // rekrutacji i dok osoby, zwykle z cache'u).
  const rejectionOpen = pendingRejection !== null;
  const rejectionWorkModeJob = useRejectionWorkModeJob(jobId, rejectionOpen);
  const rejectionProfileWorkMode = useRejectionProfileWorkMode(
    pendingRejection?.entries.length === 1
      ? pendingRejection.entries[0].item.candidate_id
      : null,
    rejectionOpen
  );
  const rejectionProfileRate = useRejectionProfileRate(
    pendingRejection?.entries.length === 1
      ? pendingRejection.entries[0].item.candidate_id
      : null,
    rejectionOpen
  );
  // Odrzucenie championa (D7): co stanie się z rekrutacją — z detalu
  // w cache'u (to samo zapytanie trzyma `useRejectionWorkModeJob`). Tylko
  // przy jednej osobie; bez detalu okno nic nie zapowiada.
  const championEntry =
    pendingRejection?.entries.length === 1 && pendingRejection.entries[0].item.is_champion
      ? pendingRejection.entries[0].item
      : null;
  const rejectionChampionNotice = championEntry
    ? championRemovalOutcome(
        queryClient.getQueryData<JobChampionsFields>(["job", String(jobId)]),
        championEntry.candidate_id,
        itemFullName(championEntry)
      )
    : null;

  // Osoba od systemu z „Nowych”/„Screeningu” (23.10.2026): okno pyta
  // o powód dla systemu; ten sam wybór idzie do każdej takiej osoby.
  function rejectionNeedsAutofill(item: KanbanItem, srcColId: string): boolean {
    const src = columns.find((c) => colId(c) === srcColId);
    return needsAutofillReason(item, src ? placeStage(src).column : null);
  }
  const autofillEntries = (pendingRejection?.entries ?? []).filter((entry) =>
    rejectionNeedsAutofill(entry.item, entry.srcColId)
  );
  const rejectionAutofill =
    pendingRejection?.terminalType === "rejected" && autofillEntries.length > 0
      ? {
          rateKnown:
            autofillEntries.length === 1 &&
            Boolean(autofillEntries[0].item.entry_autofill?.rate_known),
          several: (pendingRejection?.entries.length ?? 0) > 1,
        }
      : null;

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
        // Runda 10 (R10-V2-1): przy kilku osobach checkbox jest, gdy KTÓRAKOLWIEK
        // była u klienta — o pozostałych mówi zbiorcze zdanie po odrzuceniu.
        emailAvailable={(pendingRejection?.entries ?? []).some((entry) =>
          rejectionEmailAvailableFrom(
            columns.find((c) => colId(c) === entry.srcColId)
          )
        )}
        onConfirm={confirmRejection}
        initialEndedBy={pendingRejection?.endedBy ?? null}
        initialNotes={pendingRejection?.notes ?? null}
        canEndAsDeliveryLead={canEndAsDeliveryLead}
        agreement={
          pendingRejection && pendingRejection.entries.length === 1
            ? pendingRejection.entries[0].item.agreement ?? null
            : null
        }
        subject={
          pendingRejection && pendingRejection.entries.length === 1
            ? {
                name: itemFullName(pendingRejection.entries[0].item),
                stageLabel: pendingRejection.followUp?.stageLabel ?? null,
              }
            : null
        }
        nextPerson={pendingRejection?.followUp ? pendingRejection.followUp.next : undefined}
        championNotice={rejectionChampionNotice}
        workModeJob={rejectionWorkModeJob}
        profileWorkMode={rejectionProfileWorkMode}
        profileRate={rejectionProfileRate}
        autofill={rejectionAutofill}
        emailPreview={
          pendingRejection
            ? {
                jobId,
                people: pendingRejection.entries.map((entry) => ({
                  candidateId: entry.item.candidate_id,
                  name: itemFullName(entry.item),
                })),
              }
            : null
        }
      />

      {twinRequired ? (
        <TwinSkipDialog
          refusal={twinRequired.refusal}
          onSkip={(skips) => void twinRequired.resend(skips)}
          onClose={() => setTwinRequired(null)}
        />
      ) : null}
      {debriefRequired && (
        <DebriefRequiredDialog
          open
          onOpenChange={(open) => {
            if (open) return;
            setDebriefRequired(null);
            // Zapis debriefu ponawia ruch (`onSaved` przychodzi przed
            // zamknięciem) — odświeżenie tutaj ruszyłoby równolegle z ruchem
            // i mogło wrócić później niż on, ze starą kolumną.
            if (debriefSavedRef.current) {
              debriefSavedRef.current = false;
              return;
            }
            void refreshAfterMove();
          }}
          eventId={debriefRequired.eventId}
          candidateId={debriefRequired.item.candidate_id}
          candidateName={itemFullName(debriefRequired.item)}
          jobId={jobId}
          onSaved={() => {
            debriefSavedRef.current = true;
            void debriefRequired.retry();
          }}
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
          // Stawka z karty TEJ rekrutacji (rekruter wpisał ją w notatce i nie
          // powinien wpisywać drugi raz), potem „Stawka od” (0414), potem profil.
          initialRateHourly={
            verifiedRatePrompt.item.card?.rate_hourly ??
            verifiedRatePrompt.item.candidate_rate_from_hourly ??
            verifiedRatePrompt.item.candidate_expected_rate_hourly ??
            null
          }
          rateFromHourly={verifiedRatePrompt.item.candidate_rate_from_hourly ?? null}
          onConfirm={(payload) => void submitVerifiedMove(payload)}
          // D1 (04.10.2026): stawka jest wymagana. „Pomiń” zostaje tylko,
          // gdy stawka już jest (profil albo wcześniejszy etap tej pary).
          onSkip={
            verifiedRatePrompt.item.candidate_expected_rate_hourly != null ||
            verifiedRatePrompt.item.expected_rate_value != null
              ? () => void submitVerifiedMove(null)
              : undefined
          }
          submitting={verifiedSubmitting}
        />
      )}

      {/* „CV wysłane" — rekruter podaje stawkę do klienta (lub pomija) */}
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
          candidateRateLabel={formatExpectedRate(clientRatePrompt.item)}
          initialRate={knownClientRate(clientRatePrompt.item)}
          orderLock={clientRateHistory.data?.order_lock ?? null}
        />
      )}

      {interviewDatePrompt && (
        <ClientInterviewDateDialog
          open
          candidateName={itemFullName(interviewDatePrompt.item)}
          onCancel={() => setInterviewDatePrompt(null)}
          onConfirm={(value) => submitInterviewDateMove(value)}
        />
      )}

      {/* M4 PR-03 (audyt P1.6): potwierdzenie przed hired — powstają artefakty.
          D2 (04.10.2026): ręczny ruch mówi, jak podpisano umowę. */}
      {hiredConfirm && (
        <Dialog
          open
          onOpenChange={(o) => {
            if (!o) {
              closeHiredConfirm();
            }
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Potwierdź zatrudnienie</DialogTitle>
              <DialogDescription>
                {`${hiredConfirm.item.name ?? ""} ${hiredConfirm.item.lastname ?? ""}`.trim() ||
                  "Kandydat"}{" "}
                trafi na etap „Zatrudniony”.
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="space-y-3 text-sm">
              {/* 20.10.2026: zespół pytał, czy zatrudnia tylko Delivery Lead
                  i czy bez zamówienia się da — okno odpowiada na to pierwsze. */}
              <p
                data-testid="hired-can-save"
                className="rounded-md border border-success/30 bg-success-muted px-3 py-2 text-success-muted-foreground"
              >
                Możesz to zapisać sam. Zamówienie od klienta nie jest potrzebne —
                przyjdzie później.
              </p>
              {hiredElsewhere ? (
                <div className="space-y-2 rounded-lg border border-warning/25 bg-warning-muted/50 p-3">
                  <EmploymentNotice
                    marker={hiredElsewhere}
                    hint={null}
                    tone="neutral"
                    className="border-0 bg-transparent p-0"
                  />
                  {hiredFromGenerator ? (
                    <p className="text-xs text-muted-foreground">
                      Delivery Lead klienta, u którego osoba pracuje, dostanie
                      powiadomienie po potwierdzeniu podpisu.
                    </p>
                  ) : (
                    <>
                      <fieldset className="space-y-1.5">
                        <legend className="mb-1 font-medium">Co z obecną współpracą?</legend>
                        {HIRED_CURRENT_ENGAGEMENT_OPTIONS.map((option) => (
                          <label key={option.value} className="flex items-start gap-2">
                            <input
                              type="radio"
                              name="hired-current-engagement"
                              className="mt-1"
                              value={option.value}
                              checked={hiredEngagement === option.value}
                              onChange={() => setHiredEngagement(option.value)}
                            />
                            {option.label}
                          </label>
                        ))}
                      </fieldset>
                      <p className="text-xs text-muted-foreground">
                        Delivery Lead dostanie powiadomienie z Twoją odpowiedzią.
                        Obecna umowa i zamówienie nie zmienią się same.
                      </p>
                    </>
                  )}
                </div>
              ) : null}
              <fieldset className="space-y-1.5">
                <legend className="mb-1 font-medium">Jak podpisano umowę?</legend>
                {hiredAgreement ? (
                  <label className="flex items-start gap-2 rounded-md border border-primary/40 bg-primary/5 px-2 py-1.5">
                    <input
                      type="radio"
                      name="hired-signed-via"
                      className="mt-1"
                      checked={hiredFromGenerator}
                      onChange={() => {
                        setHiredFromGenerator(true);
                        setHiredVia(null);
                      }}
                    />
                    <span>
                      <span className="font-medium">
                        Umowa {hiredAgreement.number} z Generatora jest podpisana
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        Potwierdzenie podpisu zakłada kontrakt i zamówienie
                        i przesuwa kartę na „Zatrudniony”. Bez uprawnienia
                        „Podpis B2B” wyślemy prośbę do Delivery Leada.
                      </span>
                    </span>
                  </label>
                ) : null}
                {HIRED_SIGNED_VIA_OPTIONS.map((option) => (
                  <label key={option.value} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="hired-signed-via"
                      value={option.value}
                      checked={!hiredFromGenerator && hiredVia === option.value}
                      onChange={() => {
                        setHiredFromGenerator(false);
                        setHiredVia(option.value);
                      }}
                    />
                    {option.label}
                  </label>
                ))}
              </fieldset>
              {hiredAgreement ? null : (
                <p className="text-xs text-muted-foreground">
                  Umowa B2B z Generatora? Potwierdź ją przyciskiem „Oznacz jako
                  podpisaną” —{" "}
                  <a
                    className="font-medium text-primary underline-offset-2 hover:underline"
                    href={generatorPrefillHref(hiredConfirm.item.candidate_id, jobId)}
                  >
                    otwórz Generator
                  </a>
                  . Bez uprawnienia „Podpis B2B” poprosisz o to Delivery Leada klienta.
                </p>
              )}
              {hiredFromGenerator ? null : (
                <div
                  data-testid="hired-what-happens"
                  className="space-y-1 rounded-md border border-border px-3 py-2 text-xs"
                >
                  <p className="font-medium text-foreground">Co stanie się samo po zapisie</p>
                  <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                    <li>Powstanie szkic kontraktu i zamówienia (jeśli się nie uda, zatrudnienie i tak zostanie zapisane).</li>
                    <li>Delivery Lead i Finanse dostaną sprawę „uzupełnij zamówienie” — to ich krok.</li>
                    {/* 17.10.2026: „Pracuje u nas” daje wyłącznie umowa w Kontraktach —
                        sam etap „Zatrudniony” już go nie zapala. */}
                    <li data-testid="hired-contract-marker-note">
                      „Pracuje u nas” pojawi się, gdy umowa trafi do Kontraktów. Delivery Lead
                      klienta dostanie przypomnienie, żeby ją wpisać.
                    </li>
                  </ul>
                </div>
              )}
              {hiredAgreement && !hiredFromGenerator && hiredVia !== null ? (
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={cancelGeneratorAgreement}
                    onChange={(e) => setCancelGeneratorAgreement(e.target.checked)}
                  />
                  Anuluj umowę {hiredAgreement.number} w rejestrze (nie doszła do skutku)
                </label>
              ) : null}
              <label className="block space-y-1">
                <span className="font-medium">
                  Opis{hiredVia === "other" ? " (wymagany)" : " (opcjonalnie)"}
                </span>
                <textarea
                  className="w-full rounded-md border border-input bg-background px-3 py-2"
                  rows={2}
                  maxLength={500}
                  value={hiredNote}
                  onChange={(e) => setHiredNote(e.target.value)}
                />
              </label>
            </DialogBody>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  closeHiredConfirm();
                }}
              >
                Anuluj
              </Button>
              <Button
                disabled={
                  hiredBusy ||
                  (!hiredFromGenerator &&
                    (!hiredReasonComplete(hiredVia, hiredNote) ||
                      (hiredElsewhere !== null && hiredEngagement === null)))
                }
                onClick={() => {
                  const { item, destCol, srcColId } = hiredConfirm;
                  const agreement = hiredAgreement;
                  if (hiredFromGenerator && agreement) {
                    void confirmFromGenerator(agreement.id);
                    return;
                  }
                  if (hiredVia === null) return;
                  const signed = { via: hiredVia, note: hiredNote };
                  const engagement = hiredElsewhere ? (hiredEngagement ?? undefined) : undefined;
                  const cancelId =
                    agreement && cancelGeneratorAgreement ? agreement.id : null;
                  closeHiredConfirm();
                  applyOptimistic(item, srcColId, destCol);
                  void sendMove(item, destCol, undefined, {
                    hiredSignedVia: signed,
                    hiredCurrentEngagement: engagement,
                  }).then(
                    (ok) => {
                      if (ok && cancelId !== null) void cancelAgreement(cancelId);
                    },
                  );
                }}
              >
                {hiredFromGenerator ? "Dalej: potwierdź podpis" : "Potwierdź zatrudnienie"}
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

      {signRow && (
        <ConfirmFullySignedDialog
          row={signRow}
          open={true}
          onOpenChange={(v: boolean) => {
            if (!v) setSignRow(null);
          }}
          onConfirmed={(result) => {
            setSignRow(null);
            invalidateAgreementViews();
            showSuccess(result.message);
          }}
        />
      )}
    </>
  );

  return {
    requestMove,
    requestBulkMove,
    requestReject,
    requestWithdraw,
    canMoveWithoutDialog,
    deferMove,
    pendingMoves,
    commitPendingMove,
    isMoving: bulkBusy,
    dialogs,
  };
}
