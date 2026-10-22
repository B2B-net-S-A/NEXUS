"use client";

/**
 * Przegląd Delivery Leada przed wysłaniem CV do klienta (Pipeline v4,
 * Rekrutacja v5 — decyzje Artura 23.09.2026; przegląd v2 — D6, D9, D10,
 * 08.10.2026: wymagania, CV i decyzja obok siebie, marża na żywo, „Wróć do
 * poprawy…” z listą pól; układ D4, 09.10.2026: CV pierwsze i największe po
 * lewej, decyzja w stałej kolumnie po prawej z zawsze widocznymi przyciskami).
 *
 * U klientów innych niż Nordea osoba w kolumnie „QC CV” czeka, aż DL obejrzy:
 * wynik QC CV (okno `CvQcDialog`), stawkę kandydata, dostępność, CV
 * kartę rekomendacji (z odpowiedziami na pytania Championa) i arkusz
 * screeningu. Trzy decyzje, każda to ZWYKŁY ruch w pipeline
 * (`POST /api/pipeline/move` z wersją procesu):
 *  - „Akceptuj — wysyłam za X” → „CV wysłane” ze stawką do klienta w tym samym
 *    żądaniu (serwer odmawia bez stawki i bez uprawnienia „Rekrutacje:
 *    zakładanie, zamykanie, wysyłka CV do klienta”, a CV, które nie przeszło
 *    QC, odbija 409 `CV_QC_FAILED` — wtedy otwiera się QC),
 *  - „Wróć do poprawy…” → okno z polami do poprawy (`fix_fields`) i uwagą,
 *    z powrotem na „Zweryfikowany”; rekruter dostaje dzwonek z listą pól,
 *    wpis „wróciło” na pulpicie i podświetlone pola w formularzu,
 *  - „Odrzuć…” → etap „Odrzucony” z powodem i `ended_by: "delivery_lead"`;
 *    od 17.10.2026 z opcjonalnym mailem do kandydata (`RejectionEmailField`,
 *    ze skrzynki DL — osoba w „QC CV” jest po rozmowie z nami).
 *
 * „Uwagi dla rekrutera” (03.10.2026) jadą z każdą z trzech decyzji jako
 * `recruiter_remark`: serwer zapisuje je jako notatkę pary i dokleja do
 * dzwonka. Stawka do klienta ma własne pole — rekruter jej nie widzi.
 * Od 22.10.2026 pole to `MentionTextarea`: „@osoba” w uwadze daje oznaczonej
 * osobie dzwonek wzmianki (u Nordei dzwonek akceptacji idzie do osoby od Cpro,
 * więc tylko tak dowiaduje się rekruter).
 *
 * Kontekst decyzji (wymagania z dowodem, ocena rekrutera, ryzyka, budżet,
 * podpowiedź stawki do klienta, mediana marży u klienta) daje
 * `GET /api/dl-review/context` (`lib/api/dlReview.ts`). Gdy rekruter przesunął
 * kartę mimo uwag QC (tryb doradczy, 12.10.2026), nad decyzją stoi baner: kto,
 * kiedy, dlaczego i ile rzeczy zostało do sprawdzenia, z „Otwórz QC”.
 *
 * Uwaga rekrutera z przekazania (14.10.2026, „Zapisz i przekaż do DL”
 * w edytorze CV) stoi na górze kolumny decyzji, nad „Warunkami” — kontekst
 * daje `recruiter_handoff_remark`; bez uwagi nie ma ramki.
 *
 * Układ zależy od zmierzonej szerokości PRZEGLĄDU, nie okna (`dlReviewMode`):
 * na Tablicy przegląd stoi w panelu osoby `review` na całą szerokość, na
 * pulpicie w oknie `min(100vw,2000px)`.
 *  - poniżej 1100 px (`stack`) — jedna kolumna: CV, wymagania, decyzja; całość
 *    przewija się razem,
 *  - 1100–1639 px (`tabs`) — CV po lewej na całą wysokość, decyzja 460 px po
 *    prawej; „Wymagania i ocena” to trzecia pigułka obok CV, a w kolumnie
 *    decyzji stoi ich skrót z „Pokaż”,
 *  - od 1640 px (`columns`) — CV · wymagania 440 px · decyzja 520 px.
 * Siatka ma zawsze te same cztery dzieci w tej samej kolejności (pasek CV, CV,
 * wymagania, decyzja); tryb zmienia tylko klasy, więc zmiana szerokości nie
 * montuje niczego od nowa (podgląd CV pobiera plik przy montowaniu).
 *
 * Panel dostaje wiersz kolejki (`BoardTaskRow` z `GET /api/board-tasks`), więc
 * da się go otworzyć także z panelu osoby na Tablicy — wystarczy złożyć wiersz.
 */

import Link from "next/link";
import { forwardRef, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, X, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useToast } from "@/components/Toast";
import { MentionTextarea } from "@/components/v2/forms/MentionTextarea";
import { CvQcDialog } from "@/components/v2/recruitment/CvQcDialog";
import {
  CvColumn,
  CvToolbar,
  type CvPreviewLoaders,
  type CvView,
} from "@/components/v2/recruitment/dl-review/CvColumn";
import { DecisionPanel, type DecisionAction } from "@/components/v2/recruitment/dl-review/DecisionPanel";
import { RequirementsColumn } from "@/components/v2/recruitment/dl-review/RequirementsColumn";
import { ReturnForFixDialog } from "@/components/v2/recruitment/dl-review/ReturnForFixDialog";
import { ScreeningSummarySection } from "@/components/v2/screening-form/ScreeningSummaryView";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_TASKS_QUERY_KEY, waitingFor, type BoardTaskRow } from "@/lib/api/boardTasks";
import {
  dlReviewQueueQueryKey,
  useDlReviewContext,
  type DlReviewClientRateHint,
} from "@/lib/api/dlReview";
import { useScreeningFormState } from "@/lib/api/screeningForm";
import {
  screeningDealBreakerWarning,
  screeningFormHref,
  screeningSummaryRows,
} from "@/lib/screening-summary";
import { parseRateInput } from "@/lib/dl-review-margin";
import { invalidateAfterPipelineVersionConflict } from "@/lib/pipeline-version-conflict";
import type { PipelineMovePayload } from "@/lib/pipeline-move-core";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { hasPermission, permissionLabel } from "@/lib/permissions";
import {
  HM_ALREADY_INTERVIEWED_REASON,
  loadJobRejectionReasons,
  reasonNeedsDescription,
  WORK_MODE_MISMATCH_REASON,
} from "@/lib/rejection-reasons";
import {
  EMPTY_REJECTION_DETAILS,
  RejectionDetails,
  rejectionDetailsReady,
  rejectionNotes,
  SameManagerNotice,
  type RejectionDetailsValue,
} from "@/components/v2/recruitment/dl-review/RejectionDetails";
import { RejectionWorkModeField } from "@/components/v2/modals/RejectionWorkModeField";
import {
  RejectionEmailField,
  type RejectionEmailFieldState,
} from "@/components/v2/modals/RejectionEmailField";
import { announceRejectionEmail } from "@/lib/rejection-email";
import {
  useRejectionProfileWorkMode,
  useRejectionWorkModeJob,
} from "@/hooks/useRejectionWorkModeContext";
import { useElementWidth } from "@/lib/use-element-width";
import { cn, formatDate } from "@/lib/utils";
import { getUserRoles, useAuthStore } from "@/store/auth";
import { hourlyText, rateFromText } from "@/lib/candidate-rate";
import {
  RATE_UNIT_LABEL,
  availabilityText,
  rateText,
  type ClientRateUnit,
} from "@/lib/person-facts";
import { contractAvailability, contractAvailabilityText } from "@/lib/contract-availability";
import type { EmploymentMarker } from "@/lib/employment-marker";
import { PersonFacts } from "@/components/v2/person/PersonFacts";
import { PreContractRequestDialog } from "@/components/v2/person/pre-contract/PreContractDialogs";
import { invalidatePreContract } from "@/lib/api/preContracts";

export { RATE_UNIT_LABEL, type ClientRateUnit };

// Przycisk, którego serwer i tak by odmówił, nie renderuje się jako aktywny.
// Wysyłka do klienta idzie za uprawnieniem `recruitment_manage`
// (`pipeline_move_rules.assert_client_send_allowed`); odrzucenie „przez DL”
// zostaje przy rolach — lustro `DL_REJECT_ROLES` z tego samego modułu.
const DL_REJECT_ROLES = new Set(["admin", "delivery_lead", "head_of_recruitment"]);

/** Skąd podpowiedź stawki do klienta — zdanie pod polem. */
export function hintSourceLabel(hint: DlReviewClientRateHint): string {
  const when = hint.at ? ` (${formatDate(hint.at)})` : "";
  if (hint.source === "this_pair") return `stawka tej osoby w tej rekrutacji${when}`;
  return `ostatnia wysyłka tej osoby do tego klienta${hint.job_title ? ` — „${hint.job_title}”` : ""}${when}`;
}

// ── Fakty z podglądu kandydata ───────────────────────────────────────────────

interface QuickViewSubset {
  candidate: {
    city?: string | null;
    location?: string | null;
    expected_rate_hourly?: number | string | null;
    expected_rate_currency?: string | null;
    // „Stawka od” (0414): najniższa stawka z 18 miesięcy.
    rate_from_hourly?: number | string | null;
    rate_from_stale?: boolean | null;
    rate_from_at?: string | null;
    /** Żywa umowa (15.10.2026): termin z umowy, nie ze screeningu. */
    employment_marker?: EmploymentMarker | null;
  };
  current_position?: { title: string | null } | null;
  availability?: {
    status: string | null;
    available_from: string | null;
    notice_period: number | null;
    notice_period_unit: "days" | "weeks" | "months" | null;
  } | null;
}

// ── Panel ────────────────────────────────────────────────────────────────────

export interface DlReviewPanelProps {
  task: BoardTaskRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Flaga wysyłki z serwera (`can_send_to_client` kolejki) — wygrywa z regułą
   *  lokalną. Bez niej: uprawnienie „Rekrutacje: zakładanie, zamykanie,
   *  wysyłka CV do klienta”. */
  canSendToClient?: boolean;
  /** Harness: bajty plików CV bez sieci. */
  previewLoaders?: CvPreviewLoaders;
  onDecided?: DlReviewBodyProps["onDecided"];
  sequence?: DlReviewSequence;
}

/** Przegląd „po kolei” (`hooks/useReviewSequence`): licznik i wyjścia w linii
 *  nagłówka — bez dodatkowego wiersza, który na laptopie zabierałby CV. */
export interface DlReviewSequence {
  position: number;
  total: number;
  onSkip: () => void;
  onFinish: () => void;
}

type PendingAction = DecisionAction;

const REMARK_MAX = 2000;

const ACTION_TEXT: Record<PendingAction, { done: string; failed: string; anyway: string }> = {
  send: {
    done: "CV wysłane do klienta.",
    failed: "Nie udało się wysłać do klienta. Spróbuj ponownie.",
    anyway: "Wyślij mimo to",
  },
  reject: {
    done: "odrzucony przez DL.",
    failed: "Nie udało się odrzucić. Spróbuj ponownie.",
    anyway: "Odrzuć mimo to",
  },
  return: {
    done: "wraca do rekrutera do poprawy.",
    failed: "Nie udało się cofnąć do poprawy. Spróbuj ponownie.",
    anyway: "Cofnij mimo to",
  },
};

/** Nordea (13.10.2026): „wysyłka” to akceptacja do kolejki Cpro. */
const CPRO_SEND_TEXT = {
  done: "zaakceptowane, osoba czeka w kolejce Cpro.",
  failed: "Nie udało się zaakceptować do Cpro. Spróbuj ponownie.",
  anyway: "Zaakceptuj mimo to",
};

function actionTextFor(action: PendingAction, cpro: boolean) {
  return cpro && action === "send" ? CPRO_SEND_TEXT : ACTION_TEXT[action];
}

// ── Układ (D4, 09.10.2026) ───────────────────────────────────────────────────

/** Od tej szerokości przeglądu CV i decyzja stoją obok siebie. */
export const DL_REVIEW_TABS_MIN_WIDTH = 1100;
/** Od tej szerokości „Wymagania i ocena” mają własną kolumnę obok CV. */
export const DL_REVIEW_COLUMNS_MIN_WIDTH = 1640;

export type DlReviewMode = "stack" | "tabs" | "columns";

/** Układ z szerokości przeglądu; 0 (przed pomiarem, jsdom) = najwęższy. */
export function dlReviewMode(width: number): DlReviewMode {
  if (width >= DL_REVIEW_COLUMNS_MIN_WIDTH) return "columns";
  if (width >= DL_REVIEW_TABS_MIN_WIDTH) return "tabs";
  return "stack";
}

// Klasy siatki i jej czterech komórek dla każdego układu. Szerokości kolumn
// stoją w klasach dosłownie — Tailwind czyta je z tekstu pliku.
const GRID_CLASS: Record<DlReviewMode, string> = {
  stack: "grid-cols-1 content-start gap-y-2 overflow-y-auto px-6 py-4",
  tabs: "grid-cols-[minmax(0,1fr)_460px] grid-rows-[auto_minmax(0,1fr)] overflow-hidden",
  columns: "grid-cols-[minmax(0,1fr)_440px_520px] grid-rows-[auto_minmax(0,1fr)] overflow-hidden",
};
const TOOLBAR_CLASS: Record<DlReviewMode, string> = {
  stack: "",
  tabs: "col-start-1 row-start-1 px-4 pb-2 pt-3",
  columns: "col-start-1 row-start-1 px-4 pb-2 pt-3",
};
const CV_CLASS: Record<DlReviewMode, string> = {
  stack: "",
  tabs: "col-start-1 row-start-2 px-4 pb-4",
  columns: "col-start-1 row-start-2 px-4 pb-4",
};
const REQUIREMENTS_CLASS: Record<DlReviewMode, string> = {
  stack: "mt-4",
  tabs: "relative col-start-1 row-start-2 min-h-0 overflow-y-auto px-4 pb-4",
  columns:
    "relative col-start-2 row-start-1 row-span-2 min-h-0 space-y-3 overflow-y-auto border-l border-border px-4 py-3",
};
const DECISION_CLASS: Record<DlReviewMode, string> = {
  stack: "mt-4",
  tabs: "col-start-2 row-start-1 row-span-2 border-l border-border",
  columns: "col-start-3 row-start-1 row-span-2 border-l border-border",
};

/** Przewija do elementu, który właśnie się otworzył (jsdom nie zna tej metody). */
function reveal(element: HTMLElement | null) {
  if (element && typeof element.scrollIntoView === "function") {
    element.scrollIntoView({ block: "nearest" });
  }
}

/**
 * Okno przeglądu — pulpit „Czeka na Ciebie” i harness. Na Tablicy przegląd
 * otwiera się w panelu osoby (`DlReviewBody layout="panel"`), nie w oknie.
 */
const EMAIL_STATE_IDLE: RejectionEmailFieldState = { blocked: false, invalid: false, text: null };

export function DlReviewPanel({
  task,
  open,
  onOpenChange,
  canSendToClient,
  previewLoaders,
  onDecided,
  sequence,
}: DlReviewPanelProps) {
  return (
    <Sheet open={open && task !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="2xl" className="flex flex-col gap-0 p-0 sm:max-w-[min(100vw,2000px)]">
        {task ? (
          <DlReviewBody
            task={task}
            canSendToClient={canSendToClient}
            onClose={() => onOpenChange(false)}
            layout="sheet"
            previewLoaders={previewLoaders}
            onDecided={onDecided}
            sequence={sequence}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

export const DlReviewSheet = DlReviewPanel;

export interface DlReviewBodyProps {
  task: BoardTaskRow;
  canSendToClient?: boolean;
  onClose: () => void;
  /** `sheet` — w oknie (pulpit); `panel` — w panelu osoby na Tablicy. */
  layout: "sheet" | "panel";
  /** Harness: bajty plików CV bez sieci. */
  previewLoaders?: CvPreviewLoaders;
  /** Po udanej decyzji (wysłane / odrzucone / do poprawy) ZAMIAST `onClose` —
   *  wołający decyduje, czy zamknąć, czy pokazać następną osobę. Konflikt
   *  wersji i ręczne zamknięcie dalej idą przez `onClose`. */
  onDecided?: (action: DecisionAction, task: BoardTaskRow) => void;
  sequence?: DlReviewSequence;
}

/** Tytuł przeglądu w panelu osoby — dostaje fokus przy otwarciu. */
const PanelTitle = forwardRef<HTMLHeadingElement, { children: ReactNode }>(function PanelTitle(
  { children },
  ref,
) {
  return (
    <h2 ref={ref} tabIndex={-1} className="text-lg font-bold tracking-heading text-foreground focus:outline-none">
      {children}
    </h2>
  );
});

export function DlReviewBody({
  task,
  canSendToClient,
  onClose,
  layout,
  previewLoaders,
  onDecided,
  sequence,
}: DlReviewBodyProps) {
  const queryClient = useQueryClient();
  // Układ z szerokości samego przeglądu (panel na Tablicy i okno na pulpicie
  // mają różne szerokości przy tym samym oknie przeglądarki).
  const [root, setRoot] = useState<HTMLDivElement | null>(null);
  const mode = dlReviewMode(useElementWidth(root));
  const sideBySide = mode !== "stack";
  const moveCore = usePipelineMoveCore({ jobId: task.job_id });
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    // W panelu osoby nie ma pułapki fokusu okna — fokus idzie na tytuł.
    if (layout === "panel") titleRef.current?.focus();
  }, [layout, task.stage_id]);
  const { showSuccess, showError, showActionToast } = useToast();
  const me = useAuthStore((s) => s.user);
  const roles = getUserRoles(me as never);
  const canSend = canSendToClient ?? hasPermission(me, "recruitment_manage");
  // Nordea (13.10.2026): decyzja to akceptacja do kolejki Cpro.
  const cpro = task.cpro === true;
  const remarkLabel = cpro ? "Uwagi dla rekrutera i osoby od Cpro" : "Uwagi dla rekrutera";
  const canReject = roles.some((r) => DL_REJECT_ROLES.has(r));

  const [rateRaw, setRateRaw] = useState("");
  const [rateUnit, setRateUnit] = useState<ClientRateUnit>("hourly");
  const [currency, setCurrency] = useState("PLN");
  const [rateSource, setRateSource] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reasonId, setReasonId] = useState("");
  const [freeReason, setFreeReason] = useState("");
  // 20.10.2026: opis powodu i rozmowa u tego samego managera (wariant A+B+C).
  const [details, setDetails] = useState<RejectionDetailsValue>(EMPTY_REJECTION_DETAILS);
  const [sameManagerSeen, setSameManagerSeen] = useState(false);
  const [preferHmReason, setPreferHmReason] = useState(false);
  // „Nie akceptuje trybu pracy” (14.10.2026): to samo pytanie co w oknie
  // odrzucenia — domyślnie „Tylko zdalnie” z zapisem na profilu.
  const [officeDays, setOfficeDays] = useState(0);
  const [saveWorkMode, setSaveWorkMode] = useState(true);
  // Mail odrzucenia (17.10.2026, D6): osoba w „QC CV” jest po rozmowie
  // z nami — DL też może ją powiadomić. Mail wychodzi z JEGO skrzynki.
  const [sendEmail, setSendEmail] = useState(false);
  const [emailState, setEmailState] = useState<RejectionEmailFieldState>(EMAIL_STATE_IDLE);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<PendingAction | null>(null);
  const [warning, setWarning] = useState<{ action: PendingAction; reason: string } | null>(null);
  const [qcStageId, setQcStageId] = useState<number | null>(null);
  const [returnOpen, setReturnOpen] = useState(false);
  const [returnInput, setReturnInput] = useState<{ fields: string[]; remark: string } | null>(null);
  const [cvView, setCvView] = useState<CvView>("company");
  // Tylko układ `tabs`: wymagania w miejscu CV (trzecia pigułka paska).
  const [showRequirements, setShowRequirements] = useState(false);
  const prefilled = useRef(false);
  const rejectRef = useRef<HTMLDivElement>(null);
  const warningRef = useRef<HTMLDivElement>(null);

  const stageId = task.stage_id;
  useEffect(() => {
    setCvView("company");
    setShowRequirements(false);
    setQcStageId(null);
    setRateRaw("");
    setRateUnit("hourly");
    setCurrency("PLN");
    setRateSource(null);
    setRejecting(false);
    setReasonId("");
    setFreeReason("");
    setDetails(EMPTY_REJECTION_DETAILS);
    setSameManagerSeen(false);
    setPreferHmReason(false);
    setSendEmail(false);
    setEmailState(EMAIL_STATE_IDLE);
    setNote("");
    setWarning(null);
    setReturnOpen(false);
    setReturnInput(null);
    prefilled.current = false;
  }, [stageId]);

  // Formularz odrzucenia i ostrzeżenie otwierają się nad przyciskami, w kolumnie
  // z własnym przewijaniem — bez tego bywały poza widokiem.
  useEffect(() => {
    if (rejecting) reveal(rejectRef.current);
  }, [rejecting]);
  useEffect(() => {
    if (warning) reveal(warningRef.current);
  }, [warning]);

  const candidateId = task.candidate_id;
  const jobId = task.job_id;
  const context = useDlReviewContext(candidateId, jobId);
  // 0506: prośba o przedwstępną z przeglądu (DL decyduje, że CV poczeka na umowę).
  const [preContractOpen, setPreContractOpen] = useState(false);
  // Braki wśród wymagań, które serwer liczy do „X/Y” (krytyczne i „musi mieć”)
  // — same nazwy; liczb X/Y tu nie przeliczamy.
  const missingRequirements = useMemo(
    () =>
      (context.data?.requirements ?? [])
        .filter((r) => r.status === "missing" && (r.level === "critical" || r.level === "must"))
        .map((r) => r.label),
    [context.data],
  );
  // Podpowiedź stawki do klienta z historii (ta para, potem ta osoba u tego
  // klienta) — wpisana raz, gdy pole jest puste; źródło zostaje pod polem.
  const hint = context.data?.client_rate_hint ?? null;
  useEffect(() => {
    if (prefilled.current || !hint || !canSend) return;
    prefilled.current = true;
    setRateRaw((current) => {
      if (current.trim()) return current;
      setRateUnit((hint.unit as ClientRateUnit) in RATE_UNIT_LABEL ? (hint.unit as ClientRateUnit) : "hourly");
      setCurrency(hint.currency || "PLN");
      setRateSource(hintSourceLabel(hint));
      return String(hint.amount);
    });
  }, [hint, canSend]);

  // Uwaga rekrutera z „Zapisz i przekaż do DL” (14.10.2026) — nad „Warunkami”.
  const remarkRaw = context.data?.recruiter_handoff_remark ?? null;
  const handoffRemark = remarkRaw && remarkRaw.text?.trim() ? remarkRaw : null;
  // Karta przesunięta mimo uwag QC — DL widzi to, zanim wyśle CV do klienta.
  const qcOverride =
    context.data?.qc_status === "overridden" ? (context.data.qc_override ?? null) : null;

  const quickView = useQuery<QuickViewSubset>({
    queryKey: candidateQueryKeys.quickView(candidateId),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${candidateId}/quick-view`, { signal }).then((r) => r.data),
    enabled: candidateId > 0,
  });
  // Stan formularza screeningu pary — ten sam, który rysuje blok „Screening”.
  const screeningState = useScreeningFormState(candidateId, jobId, candidateId > 0).data ?? null;
  // „Odpada, gdy…” naruszone — liczone z odpowiedzi, które panel i tak czyta.
  const dealBreaker = useMemo(
    () => (screeningState ? screeningDealBreakerWarning(screeningSummaryRows(screeningState)) : null),
    [screeningState],
  );
  const reasons = useQuery({
    queryKey: ["job-rejection-reasons", jobId],
    queryFn: () => loadJobRejectionReasons(jobId),
    enabled: rejecting && jobId > 0,
    staleTime: 5 * 60_000,
  });
  const rejectedReasons = useMemo(
    () => (reasons.data ?? []).filter((r) => r.applies_to.includes("rejected")),
    [reasons.data],
  );
  const chosenReason = rejectedReasons.find((r) => r.id === reasonId);
  const workModeReason = chosenReason?.name === WORK_MODE_MISMATCH_REASON;
  const hmReason = chosenReason?.name === HM_ALREADY_INTERVIEWED_REASON;
  const descriptionRequired = reasonNeedsDescription(chosenReason);
  const earlierInterviews = useMemo(
    () => context.data?.earlier_interviews ?? [],
    [context.data],
  );
  // „Odrzuć z tym powodem” z ostrzeżenia: powody wczytują się dopiero po
  // otwarciu formularza, więc wybór powodu czeka na listę.
  useEffect(() => {
    if (!preferHmReason || !reasons.isSuccess) return;
    setPreferHmReason(false);
    const hm = rejectedReasons.find((r) => r.name === HM_ALREADY_INTERVIEWED_REASON);
    if (hm) setReasonId(hm.id);
  }, [preferHmReason, reasons.isSuccess, rejectedReasons]);
  const workModeJob = useRejectionWorkModeJob(jobId, rejecting);
  const profileWorkMode = useRejectionProfileWorkMode(task.candidate_id, rejecting);

  // „W tej rekrutacji” (0414): stawka z wiersza weryfikacji, a bez niej —
  // ze screeningu tej pary (PLN/h). Obok „Stawka od” (najniższa z 18 miesięcy),
  // żeby DL widział, ile jest miejsca na negocjacje.
  const profile = quickView.data?.candidate;
  const snapshotRate = rateText(task.expected_rate_value, task.expected_rate_unit, task.expected_rate_currency);
  const cardRateValue = screeningState?.rate_hints?.card?.amount;
  const cardRate = cardRateValue != null ? hourlyText(cardRateValue) : null;
  const thisJobRate = snapshotRate ?? cardRate;
  const rateFrom = profile
    ? profile.rate_from_hourly !== undefined
      ? rateFromText(profile)
      : profile.expected_rate_hourly != null
        ? rateText(profile.expected_rate_hourly, "hourly", profile.expected_rate_currency)
        : null
    : null;
  // D9 (08.10.2026): marża na żywo w panelu decyzji — `DecisionPanel`.
  const clientRate = parseRateInput(rateRaw);
  const location = profile?.city || profile?.location || null;
  // Dostępność z profilu, a gdy profil jej nie zna — z karty rekomendacji
  // (ta sama wartość stoi niżej na karcie; „—” obok niej wyglądało na brak).
  const qvAvailability = quickView.data?.availability;
  const contractAvail = contractAvailability(
    quickView.data?.candidate.employment_marker,
    qvAvailability?.available_from,
  );
  const profileAvailability = contractAvail
    ? `${contractAvailabilityText(contractAvail)} · z kontraktu`
    : availabilityText(
        qvAvailability
          ? {
              date: qvAvailability.available_from,
              status: qvAvailability.status,
              noticePeriod: qvAvailability.notice_period,
              noticeUnit: qvAvailability.notice_period_unit,
            }
          : null,
      );
  const cardAvailability = screeningState?.card?.fields?.availability?.raw?.trim() || null;

  const remark = note.trim();

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(task.job_id)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", task.job_id] });
    void queryClient.invalidateQueries({ queryKey: dlReviewQueueQueryKey(task.job_id) });
  };

  const move = async (
    action: PendingAction,
    acknowledge = false,
    fix: { fields: string[]; remark: string } | null = returnInput,
  ) => {
    const payload: PipelineMovePayload = {
      candidate_id: task.candidate_id,
      job_id: task.job_id,
      expected_state_version: task.process_state_version,
    };
    let sentRemark = remark;
    const emailFlag = action === "reject" && sendEmail && !emailState.blocked;
    if (action === "send") {
      if (task.target_stage_def_id == null || clientRate == null) return;
      Object.assign(payload, {
        stage_def_id: task.target_stage_def_id,
        client_rate_value: clientRate,
        client_rate_unit: rateUnit,
        client_rate_currency: currency,
      });
    } else if (action === "return") {
      if (task.return_stage_def_id == null) return;
      Object.assign(payload, { stage_def_id: task.return_stage_def_id });
      if (fix) {
        sentRemark = fix.remark;
        if (fix.fields.length > 0) payload.fix_fields = fix.fields;
      }
    } else {
      if (task.rejected_stage_def_id == null) return;
      Object.assign(payload, {
        stage_def_id: task.rejected_stage_def_id,
        ended_by: "delivery_lead",
        rejection_reason_id: reasonId ? Number(reasonId) : undefined,
        rejection_reason: !reasonId && freeReason.trim() ? freeReason.trim() : undefined,
        notes:
          (reasonId
            ? rejectionNotes(details, { hmReason, interviews: earlierInterviews })
            : "") || undefined,
        send_rejection_email: emailFlag,
        rejection_email_subject: emailFlag ? emailState.text?.subject : undefined,
        rejection_email_body: emailFlag ? emailState.text?.body : undefined,
        rejection_email_other_processes: emailFlag
          ? emailState.text?.otherProcesses
          : undefined,
        rejection_email_merge: emailFlag ? emailState.text?.merge : undefined,
        ...(workModeReason
          ? {
              work_mode_max_onsite_days: officeDays,
              work_mode_save_to_profile: saveWorkMode,
            }
          : {}),
      });
    }
    if (sentRemark) payload.recruiter_remark = sentRemark;
    if (acknowledge) payload.acknowledge_eligibility = true;
    setBusy(action);
    setWarning(null);
    try {
      // Ten sam klient i to samo rozpoznanie odmowy co Tablica; ostrzeżenie
      // zostaje w linii panelu („Wyślij mimo to”), dlatego tryb cichy.
      const outcome = await moveCore.send(payload, {
        candidateName: task.candidate_name,
        silent: true,
        fallbackMessage: actionTextFor(action, cpro).failed,
      });
      if (outcome.ok) {
        showSuccess(`${task.candidate_name} — ${actionTextFor(action, cpro).done}`);
        if (action === "reject") {
          announceRejectionEmail(outcome.data, {
            requested: emailFlag,
            toast: { showActionToast, showSuccess, showError },
            cancel: (id) => api.post(`/api/rejection-emails/${id}/cancel`),
          });
        }
        setReturnOpen(false);
        refresh();
        if (onDecided) onDecided(action, task);
        else onClose();
        return;
      }
      const { refusal } = outcome;
      if (refusal.kind === "cv_qc_failed") {
        // CV nie przeszło QC — pokaż, co poprawić, zamiast samego komunikatu.
        showError(refusal.message);
        setQcStageId(refusal.failure.stageId ?? task.stage_id);
      } else if (refusal.kind === "eligibility") {
        setReturnOpen(false);
        setWarning({ action, reason: refusal.message });
      } else if (refusal.kind === "version_conflict") {
        showError(refusal.message);
        invalidateAfterPipelineVersionConflict(queryClient, task.job_id, task.candidate_id);
        refresh();
        onClose();
      } else {
        showError(refusal.message);
      }
    } catch (error) {
      showError(apiErrorMessage(error, actionTextFor(action, cpro).failed));
    } finally {
      setBusy(null);
    }
  };

  const rejectReady =
    task.rejected_stage_def_id != null &&
    (reasonId !== "" || (rejectedReasons.length === 0 && freeReason.trim() !== "")) &&
    (reasonId === "" ||
      rejectionDetailsReady(details, {
        required: descriptionRequired,
        hmReason,
        interviews: earlierInterviews,
      })) &&
    !(sendEmail && emailState.invalid);
  const sendReady = canSend && clientRate != null && task.target_stage_def_id != null;
  const canReturn = (canSend || canReject) && task.return_stage_def_id != null;

  return (
    <div
      ref={setRoot}
      className={cn(
        "flex min-h-0 flex-col",
        // Tło jawnie albo po oknie: przyklejona stopka decyzji je dziedziczy.
        layout === "panel" ? "relative h-full bg-background" : "flex-1 bg-inherit",
      )}
      data-testid={layout === "panel" ? "dl-review-in-panel" : "dl-review-body"}
    >
      {/* Jedna linia: na laptopie 1280×720 każdy wiersz nagłówka zabierał CV. */}
      <header
        className={cn(
          "relative flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-border py-2.5 pr-12",
          sideBySide ? "pl-4" : "pl-6",
        )}
      >
        {layout === "sheet" ? (
          <SheetTitle>{task.candidate_name}</SheetTitle>
        ) : (
          <PanelTitle ref={titleRef}>{task.candidate_name}</PanelTitle>
        )}
        {layout === "sheet" ? (
          <SheetDescription>
            {task.job_title}
            {task.client_name ? ` · ${task.client_name}` : ""}
          </SheetDescription>
        ) : (
          <p className="text-sm text-muted-foreground">
            {task.job_title}
            {task.client_name ? ` · ${task.client_name}` : ""}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {task.verified_by_name ? `Zweryfikował(a) ${task.verified_by_name}` : "Zweryfikowany"}
          {task.verified_at ? ` · ${formatDate(task.verified_at)}` : ""} · czeka{" "}
          {waitingFor(task.ready_since ?? task.since)}
          {" · "}
          <Link
            href={`/jobs/${task.job_id}?candidate=${task.candidate_id}`}
            className="font-medium text-primary hover:underline"
          >
            Otwórz na Tablicy
          </Link>
        </p>
        {sequence ? (
          <p className="flex items-baseline gap-2 text-xs" data-testid="dl-review-sequence">
            <span className="font-semibold tabular-nums text-foreground">
              {sequence.position} z {sequence.total}
            </span>
            {sequence.position < sequence.total ? (
              <button
                type="button"
                onClick={sequence.onSkip}
                className="font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Pomiń
              </button>
            ) : null}
            <button
              type="button"
              onClick={sequence.onFinish}
              className="font-medium text-muted-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Zakończ kolejkę
            </button>
          </p>
        ) : null}
        {layout === "panel" ? (
          <button
            type="button"
            onClick={onClose}
            aria-label="Zamknij przegląd"
            className="absolute right-3 top-2 rounded-md p-1 text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        ) : null}
      </header>

      {/* Zawsze te same cztery dzieci w tej kolejności — tryb zmienia klasy. */}
      <div className={cn("relative grid min-h-0 flex-1 bg-inherit", GRID_CLASS[mode])} data-layout={mode}>
        <CvToolbar
          className={TOOLBAR_CLASS[mode]}
          task={task}
          view={cvView}
          onViewChange={(view) => {
            setCvView(view);
            setShowRequirements(false);
          }}
          requirements={
            mode === "tabs"
              ? {
                  active: showRequirements,
                  missing: missingRequirements.length,
                  onSelect: () => setShowRequirements(true),
                }
              : null
          }
          onOpenQc={() => setQcStageId(task.stage_id)}
        />

        <CvColumn
          className={CV_CLASS[mode]}
          task={task}
          view={cvView}
          fill={sideBySide}
          hidden={mode === "tabs" && showRequirements}
          previewLoaders={previewLoaders}
        />

        <div
          className={cn("min-w-0", REQUIREMENTS_CLASS[mode])}
          hidden={mode === "tabs" && !showRequirements}
          data-testid="dl-review-requirements-cell"
        >
          {mode === "columns" ? (
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Wymagania i ocena
            </h3>
          ) : null}
          <RequirementsColumn
            context={context.data}
            loading={context.isLoading}
            error={context.isError}
            onRetry={() => void context.refetch()}
            screening={
              // 09.10.2026: jeden blok zamiast „Oceny rekrutera”, karty
              // rekomendacji i zwiniętego arkusza. Trafienie „Odpada, gdy…”
              // zaznacza rekruter w formularzu — tu tylko do odczytu.
              <section aria-label="Screening" className="space-y-2">
                <h3 className="text-sm font-semibold">Screening</h3>
                <ScreeningSummarySection
                  candidateId={task.candidate_id}
                  jobId={task.job_id}
                  enabled={task.candidate_id > 0}
                  editHref={screeningFormHref(task.job_id, task.candidate_id)}
                />
              </section>
            }
          />
        </div>

        <DecisionPanel
          className={DECISION_CLASS[mode]}
          stickyActions={sideBySide}
          requirementsSummary={
            mode === "tabs"
              ? { missing: missingRequirements, onShow: () => setShowRequirements(true) }
              : null
          }
          task={task}
          context={context.data}
          contextLoading={context.isLoading}
          facts={
            <>
              {handoffRemark ? (
                <p
                  role="note"
                  data-testid="dl-review-recruiter-remark"
                  className="rounded-lg border border-info/30 bg-info-muted px-3 py-2 text-xs text-info-muted-foreground [overflow-wrap:anywhere]"
                >
                  <span className="font-semibold">
                    Od rekrutera{handoffRemark.author_name ? ` (${handoffRemark.author_name})` : ""}:
                  </span>{" "}
                  {handoffRemark.text}
                </p>
              ) : null}
              <PersonFacts
                testId="dl-review-person-facts"
                rows={[
                  {
                    label: "W tej rekrutacji",
                    value: thisJobRate,
                    hint: snapshotRate ? "przy weryfikacji" : cardRate ? "ze screeningu" : "nie pytano o tę rolę",
                  },
                  {
                    label: "Stawka od",
                    value: rateFrom,
                    hint: rateFrom ? "najniższa z 18 mies." : null,
                  },
                  {
                    label: "Dostępność",
                    value: profileAvailability ?? cardAvailability,
                    hint: !profileAvailability && cardAvailability ? "ze screeningu" : null,
                  },
                  { label: "Lokalizacja", value: location },
                  { label: "Stanowisko", value: quickView.data?.current_position?.title ?? null },
                ]}
              />
              {quickView.isError ? (
                <p role="alert" className="text-xs text-destructive">
                  Nie udało się wczytać danych kandydata.{" "}
                  <button type="button" className="font-medium underline" onClick={() => void quickView.refetch()}>
                    Ponów
                  </button>
                </p>
              ) : null}
            </>
          }
          rateRaw={rateRaw}
          onRateRawChange={(value) => {
            setRateRaw(value);
            setRateSource(null);
          }}
          rateUnit={rateUnit}
          onRateUnitChange={setRateUnit}
          currency={currency}
          onCurrencyChange={setCurrency}
          rateSourceLabel={rateSource}
          canSend={canSend}
          sendReady={sendReady}
          canReturn={canReturn}
          canReject={canReject && !rejecting}
          busy={busy}
          onAccept={() => void move("send")}
          onReturn={() => setReturnOpen(true)}
          onReject={() => setRejecting(true)}
          footerNote={
            !canSend ? (
              <p className="text-xs text-muted-foreground">
                {cpro ? "Do kolejki Cpro akceptuje" : "Do klienta wysyła"} osoba z uprawnieniem „
                {permissionLabel("recruitment_manage")}” — możesz przejrzeć kandydata.
              </p>
            ) : task.target_stage_def_id == null ? (
              <p className="text-xs text-destructive">
                Szablon tej rekrutacji nie ma etapu „{cpro ? "Wysłać do Cpro" : "CV wysłane"}” — przenieś
                osobę na Tablicy.
              </p>
            ) : cpro ? (
              <p className="text-xs text-muted-foreground">
                Po akceptacji osoba trafi do kolejki Cpro, a osoba od Cpro dostanie powiadomienie i mail.
              </p>
            ) : null
          }
        >
          {qcOverride ? (
            <div
              role="note"
              data-testid="dl-review-qc-override"
              className="flex flex-wrap items-start gap-2 rounded-lg bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                Przesunięte mimo uwag QC — {qcOverride.by_name ?? "rekruter"}, {formatDate(qcOverride.at)}:{" "}
                {qcOverride.reason.replace(/[.\s]+$/, "")}. Do sprawdzenia: {context.data?.qc_blocking_failed ?? 0}.
              </span>
              <Button size="sm" variant="outline" onClick={() => setQcStageId(task.stage_id)}>
                Otwórz QC
              </Button>
            </div>
          ) : null}
          {dealBreaker ? (
            <p
              role="note"
              data-testid="dl-review-deal-breaker"
              className="flex items-start gap-2 rounded-lg bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1">
                {dealBreaker} Wysyłka nie jest zablokowana — rozważ odrzucenie.
              </span>
            </p>
          ) : null}
          {!sameManagerSeen && !rejecting ? (
            <SameManagerNotice
              interviews={earlierInterviews}
              managerName={context.data?.hiring_manager_name}
              canReject={canReject && task.rejected_stage_def_id != null}
              onReject={() => {
                const first = earlierInterviews.find((i) => i.same_hiring_manager);
                setDetails({ description: "", interviewJobId: first ? String(first.job_id) : "" });
                setPreferHmReason(true);
                setRejecting(true);
              }}
              onDismiss={() => setSameManagerSeen(true)}
            />
          ) : null}
          {/* `scroll-mb-44`: po przewinięciu element staje nad przyklejoną
              stopką z przyciskami, nie pod nią. */}
          {warning ? (
            <div
              ref={warningRef}
              role="alert"
              className="flex scroll-mb-44 flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs"
            >
              <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden />
              <span className="min-w-0 flex-1">{warning.reason}</span>
              <Button size="sm" variant="outline" onClick={() => void move(warning.action, true)} disabled={busy !== null}>
                {actionTextFor(warning.action, cpro).anyway}
              </Button>
            </div>
          ) : null}

          {rejecting ? (
            <div
              ref={rejectRef}
              className="scroll-mb-44 space-y-2 rounded-lg border border-border p-3"
              aria-label="Odrzucenie przez DL"
              role="group"
            >
              {task.rejected_stage_def_id == null ? (
                <p role="alert" className="text-xs text-destructive">
                  Szablon tej rekrutacji nie ma etapu „Odrzucony” — odrzuć osobę na Tablicy.
                </p>
              ) : reasons.isLoading ? (
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie powodów…
                </p>
              ) : reasons.isError ? (
                <p role="alert" className="text-xs text-destructive">
                  Nie udało się wczytać powodów odrzucenia.{" "}
                  <button type="button" className="font-medium underline" onClick={() => void reasons.refetch()}>
                    Ponów
                  </button>
                </p>
              ) : rejectedReasons.length > 0 ? (
                <label className="block text-xs font-medium">
                  Powód odrzucenia *
                  <select
                    className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                    value={reasonId}
                    onChange={(e) => setReasonId(e.target.value)}
                  >
                    <option value="">Wybierz powód</option>
                    {rejectedReasons.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label className="block text-xs font-medium">
                  Powód odrzucenia *
                  <input
                    className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                    value={freeReason}
                    onChange={(e) => setFreeReason(e.target.value)}
                  />
                </label>
              )}
              {reasonId ? (
                <RejectionDetails
                  required={descriptionRequired}
                  hmReason={hmReason}
                  interviews={earlierInterviews}
                  value={details}
                  onChange={setDetails}
                />
              ) : null}
              {workModeReason ? (
                <RejectionWorkModeField
                  job={workModeJob}
                  profile={profileWorkMode}
                  several={false}
                  days={officeDays}
                  onDaysChange={setOfficeDays}
                  saveToProfile={saveWorkMode}
                  onSaveToProfileChange={setSaveWorkMode}
                  inset={false}
                />
              ) : null}
              {task.rejected_stage_def_id != null ? (
                <RejectionEmailField
                  preview={{
                    jobId: task.job_id,
                    people: [{ candidateId: task.candidate_id, name: task.candidate_name }],
                  }}
                  checked={sendEmail}
                  onCheckedChange={setSendEmail}
                  onStateChange={setEmailState}
                />
              ) : null}
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setRejecting(false)} disabled={busy !== null}>
                  Anuluj
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={!rejectReady || busy !== null}
                  onClick={() => void move("reject")}
                >
                  {busy === "reject" ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <XCircle className="size-3.5" />}
                  Potwierdź odrzucenie
                </Button>
              </div>
            </div>
          ) : null}

          {canSend || canReject ? (
            <div className="text-xs font-medium">
              <span aria-hidden>{remarkLabel}</span>
              <MentionTextarea
                ariaLabel={remarkLabel}
                ariaDescribedBy="dl-review-remark-hint"
                wrapperClassName="mt-1"
                className="min-h-9 rounded-md border-input bg-background px-2 py-1.5 font-normal"
                rows={2}
                scope={{ kind: "job", jobId: task.job_id }}
                value={note}
                onChange={(value) => setNote(value.slice(0, REMARK_MAX))}
              />
              <span id="dl-review-remark-hint" className="mt-1 block text-[11px] font-normal text-muted-foreground">
                {cpro
                  ? "Przy akceptacji uwagę dostanie osoba od Cpro, przy zwrocie i odrzuceniu — rekruter (w powiadomieniu i w notatkach kandydata). „@” oznacza osobę — dostanie powiadomienie przy każdej decyzji. Stawkę do Cpro wpisz tylko w jej polu: rekruter jej nie widzi."
                  : "Uwagę rekruter dostanie w powiadomieniu i w notatkach kandydata; „@” oznacza kolejną osobę. Stawkę do klienta wpisz tylko w jej polu: rekruter jej nie widzi."}
              </span>
            </div>
          ) : null}

          {canSend ? (
            <button
              type="button"
              className="text-left text-xs font-medium text-primary underline-offset-2 hover:underline"
              onClick={() => setPreContractOpen(true)}
              data-testid="dl-review-pre-contract"
            >
              Poproś o umowę przedwstępną przed wysłaniem CV
            </button>
          ) : null}
        </DecisionPanel>
      </div>
      {preContractOpen ? (
        <PreContractRequestDialog
          open
          onOpenChange={setPreContractOpen}
          candidateId={candidateId}
          jobId={jobId}
          personLabel={task.candidate_name}
          defaultNeededBefore="cv_sent"
          onDone={() => invalidatePreContract(queryClient, jobId)}
        />
      ) : null}

      <ReturnForFixDialog
        open={returnOpen}
        onOpenChange={setReturnOpen}
        candidateName={task.candidate_name}
        options={context.data?.fix_options ?? []}
        optionsLoading={context.isLoading}
        busy={busy === "return"}
        initialRemark={note}
        onConfirm={(input) => {
          setReturnInput(input);
          void move("return", false, input);
        }}
      />
      <CvQcDialog
        stageId={qcStageId}
        open={qcStageId !== null}
        onClose={() => setQcStageId(null)}
        onChanged={refresh}
      />
    </div>
  );
}
