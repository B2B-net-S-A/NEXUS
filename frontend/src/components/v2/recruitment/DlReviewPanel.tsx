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
 *  - „Odrzuć…” → etap „Odrzucony” z powodem i `ended_by: "delivery_lead"`.
 *
 * „Uwagi dla rekrutera” (03.10.2026) jadą z każdą z trzech decyzji jako
 * `recruiter_remark`: serwer zapisuje je jako notatkę pary i dokleja do
 * dzwonka. Stawka do klienta ma własne pole — rekruter jej nie widzi.
 *
 * Kontekst decyzji (wymagania z dowodem, ocena rekrutera, ryzyka, budżet,
 * podpowiedź stawki do klienta, mediana marży u klienta) daje
 * `GET /api/dl-review/context` (`lib/api/dlReview.ts`).
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
import { CvQcDialog } from "@/components/v2/recruitment/CvQcDialog";
import { SavedScreeningView } from "@/components/v2/recruitment/PanelSavedViews";
import {
  CvColumn,
  CvToolbar,
  type CvPreviewLoaders,
  type CvView,
} from "@/components/v2/recruitment/dl-review/CvColumn";
import { DecisionPanel, type DecisionAction } from "@/components/v2/recruitment/dl-review/DecisionPanel";
import { RequirementsColumn } from "@/components/v2/recruitment/dl-review/RequirementsColumn";
import { ReturnForFixDialog } from "@/components/v2/recruitment/dl-review/ReturnForFixDialog";
import { RecommendationCardSection } from "@/components/v2/screening/RecommendationCardSection";
import {
  RecommendationCardQuestions,
  RecommendationCardStatus,
} from "@/components/v2/screening/RecommendationCardView";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_TASKS_QUERY_KEY, waitingFor, type BoardTaskRow } from "@/lib/api/boardTasks";
import {
  dlReviewQueueQueryKey,
  useDlReviewContext,
  type DlReviewClientRateHint,
} from "@/lib/api/dlReview";
import { useRecommendationCard } from "@/lib/api/recommendationCards";
import { parseRateInput } from "@/lib/dl-review-margin";
import { invalidateAfterPipelineVersionConflict } from "@/lib/pipeline-version-conflict";
import type { PipelineMovePayload } from "@/lib/pipeline-move-core";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { hasPermission, permissionLabel } from "@/lib/permissions";
import { loadJobRejectionReasons } from "@/lib/rejection-reasons";
import { dealBreakerWarning } from "@/lib/recommendation-card";
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
import { PersonFacts } from "@/components/v2/person/PersonFacts";

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
export function DlReviewPanel({ task, open, onOpenChange, canSendToClient, previewLoaders }: DlReviewPanelProps) {
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

export function DlReviewBody({ task, canSendToClient, onClose, layout, previewLoaders }: DlReviewBodyProps) {
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
  const { showSuccess, showError } = useToast();
  const me = useAuthStore((s) => s.user);
  const roles = getUserRoles(me as never);
  const canSend = canSendToClient ?? hasPermission(me, "recruitment_manage");
  const canReject = roles.some((r) => DL_REJECT_ROLES.has(r));

  const [rateRaw, setRateRaw] = useState("");
  const [rateUnit, setRateUnit] = useState<ClientRateUnit>("hourly");
  const [currency, setCurrency] = useState("PLN");
  const [rateSource, setRateSource] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reasonId, setReasonId] = useState("");
  const [freeReason, setFreeReason] = useState("");
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

  const quickView = useQuery<QuickViewSubset>({
    queryKey: candidateQueryKeys.quickView(candidateId),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${candidateId}/quick-view`, { signal }).then((r) => r.data),
    enabled: candidateId > 0,
  });
  const card = useRecommendationCard(candidateId, jobId, candidateId > 0);
  // „Odpada, gdy…” naruszone — liczone z karty, którą panel i tak czyta.
  const dealBreaker = card.data ? dealBreakerWarning(card.data) : null;
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

  // „W tej rekrutacji” (0414): stawka z wiersza weryfikacji, a bez niej —
  // z karty rekomendacji tej pary. Obok „Stawka od” (najniższa z 18 miesięcy),
  // żeby DL widział, ile jest miejsca na negocjacje.
  const profile = quickView.data?.candidate;
  const snapshotRate = rateText(task.expected_rate_value, task.expected_rate_unit, task.expected_rate_currency);
  const cardRateValue = card.data?.fields.rate?.value;
  const cardRate =
    card.data?.fields.rate?.period === "h" && cardRateValue != null
      ? hourlyText(cardRateValue)
      : null;
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
  const profileAvailability = availabilityText(
    qvAvailability
      ? {
          date: qvAvailability.available_from,
          status: qvAvailability.status,
          noticePeriod: qvAvailability.notice_period,
          noticeUnit: qvAvailability.notice_period_unit,
        }
      : null,
  );
  const cardAvailability = card.data?.fields.availability?.raw?.trim() || null;

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
        fallbackMessage: ACTION_TEXT[action].failed,
      });
      if (outcome.ok) {
        showSuccess(`${task.candidate_name} — ${ACTION_TEXT[action].done}`);
        setReturnOpen(false);
        refresh();
        onClose();
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
      showError(apiErrorMessage(error, ACTION_TEXT[action].failed));
    } finally {
      setBusy(null);
    }
  };

  const rejectReady =
    task.rejected_stage_def_id != null &&
    (reasonId !== "" || (rejectedReasons.length === 0 && freeReason.trim() !== ""));
  const sendReady = canSend && clientRate != null && task.target_stage_def_id != null;
  const canReturn = (canSend || canReject) && task.return_stage_def_id != null;
  // Wiersz sztuczny „kandydata na etapie” dla widoku screeningu: czyta tylko
  // `id` (wiersz etapu z zapisanym arkuszem).
  const screeningItem = { id: task.screening_stage_id ?? task.stage_id } as KanbanItem;

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
          {task.verified_at ? ` · ${formatDate(task.verified_at)}` : ""} · czeka {waitingFor(task.since)}
          {" · "}
          <Link
            href={`/jobs/${task.job_id}?candidate=${task.candidate_id}`}
            className="font-medium text-primary hover:underline"
          >
            Otwórz na Tablicy
          </Link>
        </p>
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
          >
            <section aria-label="Karta rekomendacji" className="space-y-3">
              <header className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold">Karta rekomendacji</h3>
                {card.data ? <RecommendationCardStatus card={card.data} /> : null}
              </header>
              <RecommendationCardSection
                candidateId={task.candidate_id}
                jobId={task.job_id}
                candidateName={task.candidate_name}
              />
              {/* 0424: trafienie „Odpada, gdy…” zaznacza rekruter w formularzu
                  screeningu — przegląd pokazuje je tylko do odczytu. */}
              {card.data ? <RecommendationCardQuestions card={card.data} editable={false} /> : null}
            </section>
            <details className="group rounded-lg border border-border">
              <summary className="cursor-pointer px-3 py-2 text-sm font-semibold">
                Arkusz screeningu Championa
              </summary>
              <div className="border-t border-border p-3">
                <SavedScreeningView item={screeningItem} stageLabel="QC CV" />
              </div>
            </details>
          </RequirementsColumn>
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
              <PersonFacts
                testId="dl-review-person-facts"
                rows={[
                  {
                    label: "W tej rekrutacji",
                    value: thisJobRate,
                    hint: snapshotRate ? "przy weryfikacji" : cardRate ? "z karty" : "nie pytano o tę rolę",
                  },
                  {
                    label: "Stawka od",
                    value: rateFrom,
                    hint: rateFrom ? "najniższa z 18 mies." : null,
                  },
                  {
                    label: "Dostępność",
                    value: profileAvailability ?? cardAvailability,
                    hint: !profileAvailability && cardAvailability ? "z karty" : null,
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
                Do klienta wysyła osoba z uprawnieniem „{permissionLabel("recruitment_manage")}” — możesz
                przejrzeć kandydata.
              </p>
            ) : task.target_stage_def_id == null ? (
              <p className="text-xs text-destructive">
                Szablon tej rekrutacji nie ma etapu „CV wysłane” — przenieś osobę na Tablicy.
              </p>
            ) : null
          }
        >
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
                {ACTION_TEXT[warning.action].anyway}
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
            <label className="block text-xs font-medium">
              Uwagi dla rekrutera
              <textarea
                aria-describedby="dl-review-remark-hint"
                className="mt-1 block min-h-9 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm font-normal"
                rows={2}
                maxLength={REMARK_MAX}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <span id="dl-review-remark-hint" className="mt-1 block text-[11px] font-normal text-muted-foreground">
                Uwagę rekruter dostanie w powiadomieniu i w notatkach kandydata. Stawkę do klienta wpisz tylko
                w jej polu: rekruter jej nie widzi.
              </span>
            </label>
          ) : null}
        </DecisionPanel>
      </div>

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
