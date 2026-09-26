"use client";

/**
 * Przegląd Delivery Leada przed wysłaniem CV do klienta (Pipeline v4,
 * Rekrutacja v5 — decyzje Artura 23.09.2026).
 *
 * U klientów innych niż Nordea osoba w kolumnie „QC CV” czeka, aż DL obejrzy:
 * wynik QC CV (okno `CvQcDialog`), stawkę kandydata, dostępność, CV
 * i odpowiedzi ze screeningu Championa. Dwie decyzje, obie to ZWYKŁY ruch
 * w pipeline (`POST /api/pipeline/move` z wersją procesu):
 *  - „Wyślij do klienta” → „CV wysłane” ze stawką do klienta w tym samym
 *    żądaniu (serwer odmawia bez stawki i poza rolami admin/DL, a CV, które
 *    nie przeszło QC, odbija 409 `CV_QC_FAILED` — wtedy otwiera się QC),
 *  - „Odrzuć (DL)” → etap „Odrzucony” z powodem i `ended_by: "delivery_lead"`.
 *
 * Panel dostaje wiersz kolejki (`BoardTaskRow` z `GET /api/board-tasks`), więc
 * da się go otworzyć także z panelu osoby na Tablicy — wystarczy złożyć wiersz.
 */

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Loader2, Send, ShieldCheck, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useToast } from "@/components/Toast";
import { CvQcDialog } from "@/components/v2/recruitment/CvQcDialog";
import { QcStatusBadge } from "@/components/v2/recruitment/QcStatusBadge";
import { SavedScreeningView } from "@/components/v2/recruitment/PanelSavedViews";
import { ConsentAttachButton } from "@/components/v2/cv-generator/ConsentAttachButton";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_TASKS_QUERY_KEY, waitingFor, type BoardTaskRow } from "@/lib/api/boardTasks";
import { downloadBlob } from "@/lib/authenticated-files";
import { fetchStageCvFile } from "@/lib/stage-cv-file";
import { alignB2bLetterheadPreview } from "@/lib/cv-docx-preview";
import { renderDocxSafely } from "@/lib/docx-preview-safe";
import { qcFailedStageId } from "@/lib/cv-qc";
import {
  eligibilityWarningReason,
  isEligibilityWarning,
} from "@/lib/pipeline-eligibility-warning";
import {
  PIPELINE_VERSION_CONFLICT_MESSAGE,
  invalidateAfterPipelineVersionConflict,
  isPipelineVersionConflict,
} from "@/lib/pipeline-version-conflict";
import { loadJobRejectionReasons } from "@/lib/rejection-reasons";
import { formatDate } from "@/lib/utils";
import { getUserRoles, useAuthStore } from "@/store/auth";

export type ClientRateUnit = "hourly" | "daily" | "monthly";

export const RATE_UNIT_LABEL: Record<ClientRateUnit, string> = {
  hourly: "zł/h",
  daily: "zł/MD",
  monthly: "zł/mies.",
};

// Lustra `CLIENT_SEND_ROLES` i `DL_REJECT_ROLES` z
// `backend/app/services/pipeline_move_rules.py` — przycisk, którego serwer
// i tak by odmówił, nie renderuje się jako aktywny.
const CLIENT_SEND_ROLES = new Set(["admin", "delivery_lead"]);
const DL_REJECT_ROLES = new Set(["admin", "delivery_lead", "head_of_recruitment"]);

function parseAmount(raw: string): number | null {
  const value = Number.parseFloat(raw.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : null;
}

function formatAmount(value: number): string {
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
}

function rateText(
  value: number | string | null | undefined,
  unit: string | null | undefined,
  currency: string | null | undefined,
): string | null {
  if (value == null || value === "") return null;
  const numeric = typeof value === "number" ? value : Number.parseFloat(String(value));
  if (!Number.isFinite(numeric)) return null;
  const cur = (currency ?? "PLN").toUpperCase();
  const unitLabel = unit && unit in RATE_UNIT_LABEL ? RATE_UNIT_LABEL[unit as ClientRateUnit] : null;
  if (cur === "PLN") return `${formatAmount(numeric)} ${unitLabel ?? "zł"}`;
  const suffix = unitLabel ? unitLabel.replace("zł", cur) : cur;
  return `${formatAmount(numeric)} ${suffix}`;
}

// ── Fakty z podglądu kandydata ───────────────────────────────────────────────

interface QuickViewSubset {
  candidate: {
    city?: string | null;
    location?: string | null;
    expected_rate_hourly?: number | string | null;
    expected_rate_currency?: string | null;
  };
  current_position?: { title: string | null } | null;
  availability?: {
    status: string | null;
    available_from: string | null;
    notice_period: number | null;
    notice_period_unit: "days" | "weeks" | "months" | null;
  } | null;
}

const AVAILABILITY_STATUS: Record<string, string> = {
  actively_looking: "Szuka aktywnie",
  open_to_offers: "Otwarty na oferty",
  not_looking: "Nie szuka",
  available: "Dostępny",
};

function availabilityText(a: QuickViewSubset["availability"]): string | null {
  if (!a) return null;
  if (a.available_from) return `od ${formatDate(a.available_from)}`;
  const status = a.status ? (AVAILABILITY_STATUS[a.status] ?? null) : null;
  if (a.notice_period != null && a.notice_period_unit) {
    const units = { days: "dni", weeks: "tyg.", months: "mies." } as const;
    const notice = `wypowiedzenie ${a.notice_period} ${units[a.notice_period_unit]}`;
    return status ? `${status} · ${notice}` : notice;
  }
  return status;
}

function Fact({ label, value, hint }: { label: string; value: string | null; hint?: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-muted/20 px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate text-sm font-medium text-foreground">{value ?? "—"}</dd>
      {hint ? <dd className="text-[11px] text-muted-foreground">{hint}</dd> : null}
    </div>
  );
}

// ── CV wygenerowane automatycznie ────────────────────────────────────────────

interface GeneratedCvRow {
  id: number;
  status: "processing" | "ready" | "failed" | string;
  filename: string;
  origin?: string;
  needs_review?: boolean;
  error_message?: string | null;
  created_at?: string | null;
  /** Reguła klienta wymaga zrzutu zgody RODO, a dokument go nie ma — pobranie odpowie 409. */
  consent_missing?: boolean;
}

function pickCv(rows: GeneratedCvRow[] | undefined): GeneratedCvRow | null {
  if (!rows?.length) return null;
  // Lista stawia auto-CV do przeglądu pierwsze; bierzemy pierwsze gotowe.
  return rows.find((r) => r.status === "ready") ?? rows[0];
}

function CvPreview({
  candidateId,
  jobId,
  cvStageId,
}: {
  candidateId: number;
  jobId: number;
  /** Etap z CV firmowym pary — gdy jest, podgląd i DOCX idą z CV etapu (po QC). */
  cvStageId?: number | null;
}) {
  const { showError } = useToast();
  const query = useQuery({
    queryKey: ["cv-generated", "dl-review", candidateId, jobId],
    queryFn: () =>
      api
        .get<GeneratedCvRow[]>("/api/cv-generator/generated", {
          params: { candidate_id: candidateId, job_id: jobId, limit: 10 },
        })
        .then((r) => r.data),
    // Auto-CV generuje się w tle po weryfikacji — odpytujemy, dopóki trwa.
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => r.status === "processing") ? 5000 : false,
  });
  const cv = pickCv(query.data);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [render, setRender] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [renderError, setRenderError] = useState<string | null>(null);
  // Runda 7 (R7-X4-2): CV firmowe etapu (po poprawkach QC) ma pierwszeństwo
  // przed surowym plikiem z generatora — DL wysyła klientowi to, co ogląda.
  const fromStage = cvStageId != null && cvStageId > 0;
  // Bez zgody RODO serwer odmawia pobrania pliku (409) — nie próbujemy go
  // renderować, tylko prosimy o zrzut.
  const consentMissing = !fromStage && cv?.status === "ready" && cv.consent_missing === true;
  const readyId = cv?.status === "ready" && !consentMissing ? cv.id : null;
  const sourceKey = fromStage ? `stage:${cvStageId}` : readyId != null ? `generated:${readyId}` : null;

  useEffect(() => {
    if (sourceKey == null) return;
    let cancelled = false;
    setRender("loading");
    setRenderError(null);
    (async () => {
      try {
        const blob = fromStage
          ? (await fetchStageCvFile(cvStageId as number)).blob
          : ((
              await api.get(`/api/cv-generator/generated/${readyId}/docx`, {
                responseType: "blob",
              })
            ).data as Blob);
        const host = hostRef.current;
        if (cancelled || !host) return;
        host.innerHTML = "";
        await renderDocxSafely(blob, host, {
          className: "docx",
          inWrapper: true,
          breakPages: true,
          useBase64URL: true,
        });
        if (cancelled) return;
        alignB2bLetterheadPreview(host);
        setRender("ready");
      } catch (error) {
        if (cancelled) return;
        setRender("error");
        // 409 `consent_required` niesie polski komunikat serwera.
        setRenderError(fromStage ? apiErrorMessage(error, "") || null : null);
      }
    })();
    return () => {
      cancelled = true;
    };
    // `fromStage`/`cvStageId`/`readyId` są zawarte w `sourceKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey]);

  const download = async () => {
    try {
      if (fromStage) {
        const file = await fetchStageCvFile(cvStageId as number);
        downloadBlob(file.blob, file.filename || "CV.docx");
        return;
      }
      if (!cv) return;
      const res = await api.get(`/api/cv-generator/generated/${cv.id}/docx`, { responseType: "blob" });
      downloadBlob(res.data as Blob, cv.filename);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać CV."));
    }
  };

  const previewBox = (
    <div className="relative max-h-[28rem] min-h-40 overflow-auto rounded-lg border border-border bg-muted/30 p-2">
      {render !== "ready" ? (
        <p className="absolute inset-0 flex items-center justify-center px-3 text-center text-xs">
          {render === "error" ? (
            <span role="alert" className="text-destructive">
              {renderError ?? "Nie udało się wyświetlić podglądu — pobierz plik DOCX."}
            </span>
          ) : (
            <span className="flex items-center text-muted-foreground">
              <Loader2 className="mr-1.5 size-3 animate-spin" aria-hidden /> Renderowanie podglądu…
            </span>
          )}
        </p>
      ) : null}
      <div ref={hostRef} data-testid="dl-review-cv-host" className="docx-preview-host mx-auto" />
    </div>
  );

  return (
    <section aria-label="CV kandydata" className="space-y-2">
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">CV</h3>
        {cv?.origin === "auto" ? (
          <Badge size="sm" variant="soft">
            Wygenerowane automatycznie
          </Badge>
        ) : null}
        {cv?.needs_review ? (
          <Badge size="sm" variant="warning">
            Do przeglądu
          </Badge>
        ) : null}
        {fromStage || (cv?.status === "ready" && !consentMissing) ? (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => void download()}>
            <Download className="h-3.5 w-3.5" />
            Pobierz DOCX
          </Button>
        ) : null}
      </header>
      {fromStage ? (
        previewBox
      ) : query.isLoading ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie CV…
        </p>
      ) : query.isError ? (
        <p role="alert" className="text-xs text-destructive">
          Nie udało się wczytać listy CV.{" "}
          <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
            Ponów
          </button>
        </p>
      ) : !cv ? (
        <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
          Dla tej rekrutacji nie ma jeszcze wygenerowanego CV — wygeneruj je z panelu osoby na Tablicy.
        </p>
      ) : cv.status === "processing" ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> CV jeszcze się generuje…
        </p>
      ) : cv.status !== "ready" ? (
        <p role="alert" className="text-xs text-destructive">
          Generowanie CV nie powiodło się{cv.error_message ? `: ${cv.error_message}` : "."}
        </p>
      ) : consentMissing ? (
        <div
          role="note"
          data-testid="dl-review-consent-missing"
          className="space-y-2 rounded-lg border border-destructive/25 bg-destructive-muted px-3 py-3 text-xs text-destructive-muted-foreground"
        >
          <p className="font-medium">Brak zgody RODO (PKO BP)</p>
          <p>
            Reguła klienta wymaga zrzutu maila ze zgodą kandydata na końcu CV. Bez niego CV
            nie da się pobrać ani obejrzeć — dołącz zrzut, a dokument przerysuje się bez
            ponownej generacji.
          </p>
          <ConsentAttachButton
            compact
            generatedId={cv.id}
            hasConsent={false}
            onAttached={() => void query.refetch()}
          />
        </div>
      ) : (
        previewBox
      )}
    </section>
  );
}

// ── Panel ────────────────────────────────────────────────────────────────────

export interface DlReviewPanelProps {
  task: BoardTaskRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Nadpisanie bramki wysyłki (domyślnie: rola admin albo Delivery Lead). */
  canSendToClient?: boolean;
}

type PendingAction = "send" | "reject";

export function DlReviewPanel({ task, open, onOpenChange, canSendToClient }: DlReviewPanelProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const me = useAuthStore((s) => s.user);
  const roles = getUserRoles(me as never);
  const canSend = canSendToClient ?? roles.some((r) => CLIENT_SEND_ROLES.has(r));
  const canReject = roles.some((r) => DL_REJECT_ROLES.has(r));

  const [rateRaw, setRateRaw] = useState("");
  const [rateUnit, setRateUnit] = useState<ClientRateUnit>("hourly");
  const [rejecting, setRejecting] = useState(false);
  const [reasonId, setReasonId] = useState("");
  const [freeReason, setFreeReason] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<PendingAction | null>(null);
  const [warning, setWarning] = useState<{ action: PendingAction; reason: string } | null>(null);
  const [qcStageId, setQcStageId] = useState<number | null>(null);

  const stageId = task?.stage_id;
  useEffect(() => {
    setQcStageId(null);
    setRateRaw("");
    setRateUnit("hourly");
    setRejecting(false);
    setReasonId("");
    setFreeReason("");
    setNote("");
    setWarning(null);
  }, [stageId]);

  const candidateId = task?.candidate_id ?? 0;
  const jobId = task?.job_id ?? 0;
  const quickView = useQuery<QuickViewSubset>({
    queryKey: candidateQueryKeys.quickView(candidateId),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${candidateId}/quick-view`, { signal }).then((r) => r.data),
    enabled: open && candidateId > 0,
  });
  const reasons = useQuery({
    queryKey: ["job-rejection-reasons", jobId],
    queryFn: () => loadJobRejectionReasons(jobId),
    enabled: open && rejecting && jobId > 0,
    staleTime: 5 * 60_000,
  });
  const rejectedReasons = useMemo(
    () => (reasons.data ?? []).filter((r) => r.applies_to.includes("rejected")),
    [reasons.data],
  );

  if (!task) return null;

  // Stawka z wiersza weryfikacji; bez niej — stawka z profilu (PLN/h).
  const profile = quickView.data?.candidate;
  const snapshotRate = rateText(task.expected_rate_value, task.expected_rate_unit, task.expected_rate_currency);
  const profileRate =
    profile?.expected_rate_hourly != null
      ? rateText(profile.expected_rate_hourly, "hourly", profile.expected_rate_currency)
      : null;
  // Bez marży (decyzja 23.09.2026): DL widzi stawkę kandydata i sam wpisuje
  // stawkę do klienta.
  const clientRate = parseAmount(rateRaw);
  const location = profile?.city || profile?.location || null;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(task.job_id)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", task.job_id] });
  };

  const move = async (action: PendingAction, acknowledge = false) => {
    const payload: Record<string, unknown> = {
      candidate_id: task.candidate_id,
      job_id: task.job_id,
      expected_state_version: task.process_state_version,
    };
    if (action === "send") {
      if (task.target_stage_def_id == null || clientRate == null) return;
      Object.assign(payload, {
        stage_def_id: task.target_stage_def_id,
        client_rate_value: clientRate,
        client_rate_unit: rateUnit,
        client_rate_currency: "PLN",
      });
    } else {
      if (task.rejected_stage_def_id == null) return;
      Object.assign(payload, {
        stage_def_id: task.rejected_stage_def_id,
        ended_by: "delivery_lead",
        rejection_reason_id: reasonId ? Number(reasonId) : undefined,
        rejection_reason: !reasonId && freeReason.trim() ? freeReason.trim() : undefined,
        notes: note.trim() || undefined,
      });
    }
    if (acknowledge) payload.acknowledge_eligibility = true;
    setBusy(action);
    setWarning(null);
    try {
      await api.post("/api/pipeline/move", payload);
      showSuccess(
        action === "send"
          ? `${task.candidate_name} — CV wysłane do klienta.`
          : `${task.candidate_name} — odrzucony przez DL.`,
      );
      refresh();
      onOpenChange(false);
    } catch (error) {
      const qcStage = qcFailedStageId(error);
      if (qcStage !== undefined) {
        // CV nie przeszło QC — pokaż, co poprawić, zamiast samego komunikatu.
        showError(apiErrorMessage(error, "CV nie przeszło QC — popraw je przed wysłaniem."));
        setQcStageId(qcStage ?? task.stage_id);
      } else if (isEligibilityWarning(error)) {
        setWarning({
          action,
          reason: eligibilityWarningReason(error) ?? "Serwer ostrzega przed tym ruchem.",
        });
      } else if (isPipelineVersionConflict(error)) {
        showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
        invalidateAfterPipelineVersionConflict(queryClient, task.job_id, task.candidate_id);
        refresh();
        onOpenChange(false);
      } else {
        showError(
          apiErrorMessage(
            error,
            action === "send"
              ? "Nie udało się wysłać do klienta. Spróbuj ponownie."
              : "Nie udało się odrzucić. Spróbuj ponownie.",
          ),
        );
      }
    } finally {
      setBusy(null);
    }
  };

  const rejectReady =
    task.rejected_stage_def_id != null &&
    (reasonId !== "" || (rejectedReasons.length === 0 && freeReason.trim() !== ""));
  const sendReady = canSend && clientRate != null && task.target_stage_def_id != null;
  // Wiersz sztuczny „kandydata na etapie” dla widoku screeningu: czyta tylko
  // `id` (wiersz etapu z zapisanym arkuszem).
  const screeningItem = { id: task.screening_stage_id ?? task.stage_id } as KanbanItem;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="xl" className="flex flex-col gap-0 p-0">
        <SheetHeader className="pr-12">
          <SheetTitle>{task.candidate_name}</SheetTitle>
          <SheetDescription>
            {task.job_title}
            {task.client_name ? ` · ${task.client_name}` : ""}
          </SheetDescription>
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
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <QcStatusBadge row={task} />
            <Button size="sm" variant="outline" onClick={() => setQcStageId(task.stage_id)}>
              <ShieldCheck className="size-3.5" aria-hidden />
              Otwórz QC
            </Button>
          </div>
        </SheetHeader>

        <SheetBody className="space-y-5">
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Fact
              label="Stawka kandydata"
              value={snapshotRate ?? profileRate}
              hint={snapshotRate ? "przy weryfikacji" : profileRate ? "z profilu" : undefined}
            />
            <Fact label="Dostępność" value={availabilityText(quickView.data?.availability)} />
            <Fact label="Lokalizacja" value={location} />
            <Fact label="Stanowisko" value={quickView.data?.current_position?.title ?? null} />
          </dl>
          {quickView.isError ? (
            <p role="alert" className="text-xs text-destructive">
              Nie udało się wczytać danych kandydata.{" "}
              <button type="button" className="font-medium underline" onClick={() => void quickView.refetch()}>
                Ponów
              </button>
            </p>
          ) : null}

          <CvPreview candidateId={task.candidate_id} jobId={task.job_id} cvStageId={task.cv_stage_id} />

          <section aria-label="Odpowiedzi ze screeningu" className="space-y-2">
            <h3 className="text-sm font-semibold">Screening Championa</h3>
            <SavedScreeningView item={screeningItem} stageLabel="Zweryfikowany" />
          </section>
        </SheetBody>

        {/* Stopka niesie ostrzeżenie, formularz odrzucenia i stawkę — na
            telefonie w poziomie wychodziła poza ekran razem z „Wyślij". */}
        <SheetFooter className="block max-h-[50dvh] space-y-3 overflow-y-auto sm:block">
          {warning ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
              <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden />
              <span className="min-w-0 flex-1">{warning.reason}</span>
              <Button size="sm" variant="outline" onClick={() => void move(warning.action, true)} disabled={busy !== null}>
                {warning.action === "send" ? "Wyślij mimo to" : "Odrzuć mimo to"}
              </Button>
            </div>
          ) : null}

          {rejecting ? (
            <div className="space-y-2 rounded-lg border border-border p-3" aria-label="Odrzucenie przez DL" role="group">
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
              <label className="block text-xs font-medium">
                Notatka (opcjonalnie)
                <textarea
                  className="mt-1 min-h-16 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
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

          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs font-medium">
              Stawka do klienta *
              <div className="mt-1 flex gap-1">
                <input
                  inputMode="decimal"
                  aria-label="Stawka do klienta"
                  className="h-9 w-28 rounded-md border border-input bg-background px-2 text-sm tabular-nums"
                  value={rateRaw}
                  onChange={(e) => setRateRaw(e.target.value)}
                  disabled={!canSend}
                />
                <select
                  aria-label="Jednostka stawki do klienta"
                  className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                  value={rateUnit}
                  onChange={(e) => setRateUnit(e.target.value as ClientRateUnit)}
                  disabled={!canSend}
                >
                  {(Object.keys(RATE_UNIT_LABEL) as ClientRateUnit[]).map((u) => (
                    <option key={u} value={u}>
                      {RATE_UNIT_LABEL[u]}
                    </option>
                  ))}
                </select>
              </div>
            </label>
            <div className="ml-auto flex flex-wrap gap-2">
              {canReject && !rejecting ? (
                <Button variant="outline" onClick={() => setRejecting(true)} disabled={busy !== null}>
                  <XCircle className="size-4" />
                  Odrzuć (DL)…
                </Button>
              ) : null}
              <Button disabled={!sendReady || busy !== null} onClick={() => void move("send")}>
                {busy === "send" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" />}
                Wyślij do klienta → CV wysłane
              </Button>
            </div>
          </div>
          {!canSend ? (
            <p className="text-xs text-muted-foreground">Do klienta wysyła Delivery Lead — możesz przejrzeć kandydata.</p>
          ) : task.target_stage_def_id == null ? (
            <p className="text-xs text-destructive">
              Szablon tej rekrutacji nie ma etapu „CV wysłane” — przenieś osobę na Tablicy.
            </p>
          ) : null}
        </SheetFooter>
        <CvQcDialog
          stageId={qcStageId}
          open={qcStageId !== null}
          onClose={() => setQcStageId(null)}
          onChanged={refresh}
        />
      </SheetContent>
    </Sheet>
  );
}
