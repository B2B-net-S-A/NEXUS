"use client";

/**
 * Kolejka Cpro (Rekrutacja v5, decyzja Artura 23.09.2026) — Nordea.
 *
 * Do Cpro wrzuca JEDNA osoba na całą firmę (nie per rekrutacja); zmienić ją
 * albo ustawić zastępstwo może każdy z zespołu. Okno prowadzi pracę
 * rekrutacja po rekrutacji: po lewej procesy z licznikami, po prawej osoby
 * po kolei z danymi do przepisania do Cpro. „✓ Wrzucone” i „Zwróć do
 * rekrutera” to ZWYKŁY ruch w pipeline (`POST /api/pipeline/move` z wersją
 * procesu) — okno nie ma własnej ścieżki zapisu etapu.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, Download, Loader2, Undo2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useToast } from "@/components/Toast";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  BOARD_TASKS_QUERY_KEY,
  CPRO_QUEUE_QUERY_KEY,
  CPRO_SENDER_QUERY_KEY,
  assigneeLabel,
  setCproSender,
  useCproAssigneeOptions,
  useCproQueue,
  useCproSender,
  waitingFor,
  type CproQueueItem,
  type CproQueueJob,
  type CproSender,
} from "@/lib/api/boardTasks";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
import { copyTextToClipboard } from "@/lib/clipboard";
import { countPl } from "@/lib/plural-pl";
import { QC_STATUS_LABEL } from "@/lib/cv-qc";
import { eligibilityWarningReason, isEligibilityWarning } from "@/lib/pipeline-eligibility-warning";
import {
  PIPELINE_VERSION_CONFLICT_MESSAGE,
  isPipelineVersionConflict,
} from "@/lib/pipeline-version-conflict";
import { resolveViewState } from "@/lib/view-state";
import { cn, formatDate } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

// ── Dane do przepisania ──────────────────────────────────────────────────────

const RATE_UNIT: Record<string, string> = { hourly: "/h", daily: "/MD", monthly: "/mies." };

export function cproRateText(item: Pick<CproQueueItem, "client_rate_value" | "client_rate_unit" | "client_rate_currency">): string {
  if (item.client_rate_value == null) return "brak stawki";
  const amount = item.client_rate_value.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
  const currency = (item.client_rate_currency ?? "PLN").toUpperCase();
  const unit = item.client_rate_unit ? (RATE_UNIT[item.client_rate_unit] ?? "") : "";
  return `${amount} ${currency === "PLN" ? "zł" : currency}${unit}`;
}

/** `2026-11-01` → `01.11.2026` — tak, jak wpisuje się datę w Cpro. */
export function cproDate(value: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : formatDate(value);
}

export function cproAvailabilityText(value: string | null): string {
  return value ? cproDate(value) : "od zaraz";
}

/** Tekst do schowka — to samo, co widać w wierszu, bez żadnych ukrytych pól. */
export function cproCopyText(
  item: CproQueueItem,
  job: Pick<CproQueueJob, "job_title" | "client_reference">,
): string {
  // Nazwa i numer od klienta (0380) — tak, jak klient zna swoje zapytanie.
  const reference = job.client_reference?.trim();
  return [
    item.candidate_name,
    `Rekrutacja: ${job.job_title}`,
    ...(reference ? [`Numer u klienta: ${reference}`] : []),
    `Stawka do Cpro: ${cproRateText(item)}`,
    `Dostępność: ${cproAvailabilityText(item.availability)}`,
  ].join("\n");
}

function invalidateCpro(queryClient: ReturnType<typeof useQueryClient>, jobId?: number) {
  void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
  if (jobId != null) {
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  }
}

// ── Kto wrzuca (cała firma) ──────────────────────────────────────────────────

interface SenderControlProps {
  sender: CproSender | undefined;
  loading?: boolean;
  /** Wariant jednoliniowy do panelu „Czeka na Ciebie”. */
  compact?: boolean;
}

export function CproSenderControl({ sender, loading = false, compact = false }: SenderControlProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const me = useAuthStore((s) => s.user);
  const [open, setOpen] = useState(false);
  const [userId, setUserId] = useState<string>("");
  const [until, setUntil] = useState("");
  const [saving, setSaving] = useState(false);
  const options = useCproAssigneeOptions(open);

  useEffect(() => {
    if (!open) return;
    setUserId(sender?.user_id != null ? String(sender.user_id) : "");
    setUntil(sender?.until ?? "");
  }, [open, sender?.user_id, sender?.until]);

  const name = loading ? "…" : sender?.user_name ?? "nikt nie ustawiony";
  const save = async () => {
    if (!userId) return;
    setSaving(true);
    try {
      const res = await setCproSender({ user_id: Number(userId), until: until || null });
      queryClient.setQueryData(CPRO_SENDER_QUERY_KEY, res);
      invalidateCpro(queryClient);
      showSuccess(
        `Do Cpro wrzuca: ${res.user_name ?? "wybrana osoba"}${res.until ? ` (do ${cproDate(res.until)})` : ""}.`,
      );
      setOpen(false);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zmienić osoby. Spróbuj ponownie."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className={cn(
        "flex items-center gap-2",
        !compact && "rounded-lg border border-border bg-muted/30 px-3 py-2",
      )}
    >
      <p className={cn("min-w-0", compact ? "text-xs text-muted-foreground" : "text-sm")}>
        <span className={cn(!compact && "block text-xs text-muted-foreground")}>
          Do Cpro wrzuca{compact ? ": " : " (cała firma)"}
        </span>
        <span className={cn("font-semibold text-foreground", compact && "font-medium")}>{name}</span>
        {sender?.until ? (
          <span className="text-xs text-muted-foreground">
            {" "}
            · zastępstwo do {cproDate(sender.until)}
            {sender.fallback_user_name ? `, potem ${sender.fallback_user_name}` : ""}
          </span>
        ) : null}
      </p>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button size="sm" variant={compact ? "ghost" : "outline"} className={cn(compact && "h-7 px-2")}>
            Zmień
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 space-y-3" aria-label="Kto wrzuca do Cpro">
          <p className="text-sm font-semibold">Kto wrzuca do Cpro</p>
          <label className="block text-xs font-medium text-muted-foreground">
            Osoba
            <select
              className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground"
              value={userId}
              disabled={options.isLoading}
              onChange={(e) => setUserId(e.target.value)}
            >
              <option value="">{options.isLoading ? "Wczytywanie…" : "Wybierz osobę"}</option>
              {sender?.user_id != null && !(options.data ?? []).some((o) => o.id === sender.user_id) ? (
                <option value={sender.user_id}>{sender.user_name ?? "Obecna osoba"}</option>
              ) : null}
              {(options.data ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {assigneeLabel(o)}
                  {o.id === me?.id ? " (ja)" : ""}
                </option>
              ))}
            </select>
          </label>
          {options.isError ? (
            <p role="alert" className="text-xs text-destructive">
              Nie udało się wczytać zespołu.{" "}
              <button type="button" className="font-medium underline" onClick={() => void options.refetch()}>
                Ponów
              </button>
            </p>
          ) : null}
          <label className="block text-xs font-medium text-muted-foreground">
            Do kiedy (opcjonalnie — potem wraca poprzednia osoba)
            <input
              type="date"
              className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </label>
          <p className="text-xs text-muted-foreground">
            Zmienić może każdy z zespołu. Nowa osoba dostaje powiadomienie.
          </p>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              Anuluj
            </Button>
            <Button size="sm" disabled={!userId || saving} onClick={() => void save()}>
              {saving ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
              Zapisz
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

// ── Okno kolejki ─────────────────────────────────────────────────────────────

interface DoneRow {
  stage_id: number;
  candidate_name: string;
  outcome: "sent" | "returned";
}

export interface CproQueueDialogProps {
  open: boolean;
  onClose: () => void;
  /** Rekrutacja otwarta na starcie (klik w linię panelu). */
  initialJobId?: number | null;
}

export function CproQueueDialog({ open, onClose, initialJobId = null }: CproQueueDialogProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const queue = useCproQueue(open);
  const senderQuery = useCproSender(open);
  const [jobId, setJobId] = useState<number | null>(initialJobId);
  const [done, setDone] = useState<Record<number, DoneRow[]>>({});
  const doneRef = useRef(done);
  doneRef.current = done;
  // Rekrutacje znane w tej sesji okna: serwer zdejmuje wrzuconą osobę (a z nią
  // czasem całą rekrutację) po odświeżeniu — pasek postępu i lista „✓ w Cpro”
  // mają zostać, dopóki okno jest otwarte.
  const [known, setKnown] = useState<CproQueueJob[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [returning, setReturning] = useState<number | null>(null);
  const [returnReason, setReturnReason] = useState("");

  useEffect(() => {
    if (open) setJobId(initialJobId);
    else {
      setDone({});
      setKnown([]);
      setReturning(null);
      setReturnReason("");
    }
  }, [open, initialJobId]);

  useEffect(() => {
    const serverJobs = queue.data?.jobs;
    if (!serverJobs) return;
    setKnown((prev) => {
      const server = new Map(serverJobs.map((j) => [j.job_id, j]));
      const out: CproQueueJob[] = [];
      for (const j of prev) {
        const fresh = server.get(j.job_id);
        if (fresh) {
          out.push(fresh);
          server.delete(j.job_id);
        } else if ((doneRef.current[j.job_id]?.length ?? 0) > 0) {
          out.push({ ...j, items: [] });
        }
      }
      return [...out, ...server.values()];
    });
  }, [queue.data]);

  const leftIn = (j: CproQueueJob) =>
    j.items.filter((i) => !(done[j.job_id] ?? []).some((d) => d.stage_id === i.stage_id)).length;
  const jobs = known.length > 0 || !queue.data ? known : queue.data.jobs;
  const job = jobs.find((j) => j.job_id === jobId) ?? jobs.find((j) => leftIn(j) > 0) ?? jobs[0];
  // Rekrutacja wybrana automatycznie zostaje wybrana — po wrzuceniu ostatniej
  // osoby okno ma pokazać postęp, a nie przeskoczyć samo do następnej.
  const pickedJobId = job?.job_id ?? null;
  useEffect(() => {
    if (jobId == null && pickedJobId != null) setJobId(pickedJobId);
  }, [jobId, pickedJobId]);
  const doneRows = job ? (done[job.job_id] ?? []) : [];
  const doneIds = new Set(doneRows.map((d) => d.stage_id));
  const remaining = job ? job.items.filter((i) => !doneIds.has(i.stage_id)) : [];
  const total = doneRows.length + remaining.length;
  const current = remaining[0];
  const jobIndex = job ? jobs.indexOf(job) : -1;
  const nextJob =
    jobs.slice(jobIndex + 1).find((j) => leftIn(j) > 0) ??
    jobs.slice(0, Math.max(jobIndex, 0)).find((j) => leftIn(j) > 0) ??
    null;
  const sender = queue.data?.sender ?? senderQuery.data;
  const state = resolveViewState({ isLoading: queue.isLoading, error: queue.error });

  const markDone = (forJob: number, row: DoneRow) =>
    setDone((prev) => ({ ...prev, [forJob]: [...(prev[forJob] ?? []), row] }));

  const move = async (item: CproQueueItem, kind: "sent" | "returned") => {
    if (!job) return;
    const stageDefId = kind === "sent" ? item.target_stage_def_id : item.return_stage_def_id;
    if (stageDefId == null) return;
    setBusy(item.stage_id);
    try {
      await api.post("/api/pipeline/move", {
        candidate_id: item.candidate_id,
        job_id: job.job_id,
        stage_def_id: stageDefId,
        expected_state_version: item.process_state_version,
        ...(kind === "returned" ? { notes: returnReason.trim() } : {}),
      });
      markDone(job.job_id, { stage_id: item.stage_id, candidate_name: item.candidate_name, outcome: kind });
      showSuccess(
        kind === "sent"
          ? `${item.candidate_name} — wrzucone do Cpro.`
          : `${item.candidate_name} — zwrócone do rekrutera.`,
      );
      if (kind === "returned") {
        setReturning(null);
        setReturnReason("");
      }
    } catch (error) {
      if (isEligibilityWarning(error)) {
        showError(
          `${eligibilityWarningReason(error) ?? "Serwer ostrzega przed tym ruchem."} Otwórz osobę na Tablicy, żeby zdecydować.`,
        );
      } else if (isPipelineVersionConflict(error)) {
        showError(PIPELINE_VERSION_CONFLICT_MESSAGE);
      } else {
        showError(apiErrorMessage(error, kind === "sent" ? "Nie udało się przesunąć. Spróbuj ponownie." : "Nie udało się zwrócić. Spróbuj ponownie."));
      }
    } finally {
      setBusy(null);
      void queryClient.invalidateQueries({ queryKey: CPRO_QUEUE_QUERY_KEY });
      invalidateCpro(queryClient, job.job_id);
    }
  };

  const copy = async (item: CproQueueItem) => {
    if (!job) return;
    const ok = await copyTextToClipboard(cproCopyText(item, job));
    if (ok) showSuccess("Dane skopiowane — wklej je w Cpro.");
    else showError("Przeglądarka nie pozwoliła skopiować — przepisz dane z wiersza.");
  };

  const downloadCv = async (item: CproQueueItem) => {
    const cv = item.cv;
    const path = cv?.generated_document_id
      ? `/api/cv-generator/generated/${cv.generated_document_id}/docx`
      : cv?.document_id
        ? `/api/candidates/${item.candidate_id}/documents/${cv.document_id}/content`
        : null;
    if (!path) return;
    try {
      const { blob, filename } = await fetchAuthenticatedDownload(path);
      downloadBlob(blob, filename ?? `CV ${item.candidate_name}`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać CV."));
    }
  };

  const totalWaiting = jobs.reduce((n, j) => n + leftIn(j), 0);

  return (
    <Dialog open={open} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <DialogContent size="2xl" className="flex max-h-[92dvh] flex-col p-0" aria-describedby="cpro-queue-desc">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3 pr-16">
          <div className="min-w-0 space-y-0.5">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Pulpit · Czeka na Ciebie</p>
            <DialogTitle className="text-base font-semibold">
              Do wrzucenia do Cpro
              {queue.data
                ? ` · ${countPl(totalWaiting, "osoba", "osoby", "osób")} w ${jobs.length} ${jobs.length === 1 ? "rekrutacji" : "rekrutacjach"}`
                : ""}
            </DialogTitle>
            <DialogDescription id="cpro-queue-desc" className="text-xs text-muted-foreground">
              Tylko Nordea. Osoby trafiają tu po QC CV.
            </DialogDescription>
          </div>
          <CproSenderControl sender={sender} loading={!sender && (queue.isLoading || senderQuery.isLoading)} />
        </div>

        {queue.isLoading ? (
          <p className="flex items-center gap-2 px-5 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Wczytywanie kolejki…
          </p>
        ) : !queue.data ? (
          <div role="alert" className="space-y-2 px-5 py-6 text-sm text-muted-foreground">
            <p>
              {state === "forbidden"
                ? "Nie masz dostępu do kolejki Cpro."
                : "Nie udało się wczytać kolejki Cpro. Spróbuj ponownie."}
            </p>
            {state !== "forbidden" ? (
              <Button size="sm" variant="outline" onClick={() => void queue.refetch()}>
                Ponów
              </Button>
            ) : null}
          </div>
        ) : jobs.length === 0 ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">
            Nic nie czeka na Cpro.{queue.data.sent_today > 0 ? ` Wrzucone dziś: ${queue.data.sent_today}.` : ""}
          </p>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto md:grid-cols-[280px_minmax(0,1fr)] md:overflow-hidden">
            <nav aria-label="Rekrutacje" className="min-h-0 border-b border-border md:overflow-y-auto md:border-b-0 md:border-r">
              <ul>
                {jobs.map((j) => {
                  const active = j.job_id === job?.job_id;
                  const left = leftIn(j);
                  return (
                    <li key={j.job_id}>
                      <button
                        type="button"
                        aria-current={active ? "true" : undefined}
                        onClick={() => setJobId(j.job_id)}
                        className={cn(
                          "flex w-full items-center justify-between gap-2 border-b border-border px-4 py-2.5 text-left hover:bg-muted/50",
                          active && "bg-primary/10",
                        )}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">{j.job_title}</span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {j.client_name ? `${j.client_name} · ` : ""}najstarsza czeka {waitingFor(j.oldest_since)}
                          </span>
                        </span>
                        <span
                          className={cn(
                            "shrink-0 rounded-md border px-1.5 text-xs font-semibold tabular-nums",
                            active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-muted",
                          )}
                        >
                          {left}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <p className="px-4 py-2.5 text-xs text-muted-foreground">Wrzucone dziś · {queue.data.sent_today}</p>
            </nav>

            {job ? (
              <section aria-label={`Kolejka: ${job.job_title}`} className="min-h-0 space-y-3 p-4 md:overflow-y-auto">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold">
                      {job.job_title}
                      {job.client_name ? ` · ${job.client_name}` : ""}
                    </h3>
                    <Link href={`/jobs/${job.job_id}`} className="text-xs font-medium text-primary hover:underline">
                      Otwórz Tablicę rekrutacji
                    </Link>
                  </div>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {doneRows.length} z {total} wrzucone
                  </span>
                </div>
                <div
                  role="progressbar"
                  aria-label="Postęp rekrutacji"
                  aria-valuemin={0}
                  aria-valuemax={total}
                  aria-valuenow={doneRows.length}
                  className="h-1.5 overflow-hidden rounded-full border border-border bg-muted"
                >
                  <div className="h-full bg-success" style={{ width: `${total ? (doneRows.length / total) * 100 : 0}%` }} />
                </div>

                <ol className="space-y-2">
                  {doneRows.map((row, i) => (
                    <li
                      key={`done-${row.stage_id}`}
                      className="grid grid-cols-[24px_1fr_auto] items-center gap-3 rounded-lg border border-border px-3 py-2 opacity-60"
                    >
                      <span className="text-center font-mono text-xs text-muted-foreground">{i + 1}</span>
                      <span className="text-sm font-medium">{row.candidate_name}</span>
                      <Badge variant={row.outcome === "sent" ? "success" : "outline"} size="sm">
                        {row.outcome === "sent" ? "✓ w Cpro" : "zwrócone"}
                      </Badge>
                    </li>
                  ))}
                  {remaining.map((item, i) => {
                    const isCurrent = item === current;
                    const hasCv = !!(item.cv?.generated_document_id || item.cv?.document_id);
                    return (
                      <li
                        key={item.stage_id}
                        aria-current={isCurrent ? "step" : undefined}
                        className={cn(
                          "grid grid-cols-[24px_1fr] gap-3 rounded-lg border border-border px-3 py-2.5 sm:grid-cols-[24px_1fr_auto] sm:items-center",
                          isCurrent && "border-primary ring-2 ring-primary/15",
                        )}
                      >
                        <span className="text-center font-mono text-xs text-muted-foreground">{doneRows.length + i + 1}</span>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold">{item.candidate_name}</p>
                          <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                            <span>
                              stawka do Cpro: <span className="font-mono text-foreground">{cproRateText(item)}</span>
                            </span>
                            <span>
                              dostępność: <span className="font-mono text-foreground">{cproAvailabilityText(item.availability)}</span>
                            </span>
                            <span className={cn(item.qc_status === "failed" && "text-destructive")}>
                              {item.qc_status ? QC_STATUS_LABEL[item.qc_status] : QC_STATUS_LABEL.unchecked}
                            </span>
                            <span>czeka {waitingFor(item.since)}</span>
                          </p>
                        </div>
                        <div className="col-span-2 flex flex-wrap gap-1.5 sm:col-span-1 sm:justify-end">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!hasCv}
                            title={hasCv ? undefined : "Brak CV firmowego"}
                            onClick={() => void downloadCv(item)}
                            aria-label={`Pobierz CV: ${item.candidate_name}`}
                          >
                            <Download className="size-3.5" aria-hidden />
                            CV
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void copy(item)}
                            aria-label={`Kopiuj dane: ${item.candidate_name}`}
                          >
                            <Copy className="size-3.5" aria-hidden />
                            Kopiuj dane
                          </Button>
                          <Button
                            size="sm"
                            variant={isCurrent ? "primary" : "outline"}
                            disabled={busy !== null || item.target_stage_def_id == null}
                            onClick={() => void move(item, "sent")}
                            aria-label={`Wrzucone do Cpro: ${item.candidate_name}`}
                          >
                            {busy === item.stage_id ? (
                              <Loader2 className="size-3.5 animate-spin" aria-hidden />
                            ) : (
                              <CheckCircle2 className="size-3.5" aria-hidden />
                            )}
                            Wrzucone
                          </Button>
                        </div>
                        {returning === item.stage_id ? (
                          <div className="col-span-full space-y-2 rounded-md border border-border bg-muted/30 p-2.5" role="group" aria-label="Zwrot do rekrutera">
                            <label className="block text-xs font-medium">
                              Dlaczego nie da się wrzucić? *
                              <textarea
                                className="mt-1 min-h-14 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                                value={returnReason}
                                onChange={(e) => setReturnReason(e.target.value)}
                                placeholder="Np. brak zgody RODO w CV, stawka powyżej limitu call-offu"
                              />
                            </label>
                            <div className="flex justify-end gap-2">
                              <Button size="sm" variant="ghost" onClick={() => setReturning(null)}>
                                Anuluj
                              </Button>
                              <Button
                                size="sm"
                                variant="destructive"
                                disabled={!returnReason.trim() || busy !== null || item.return_stage_def_id == null}
                                onClick={() => void move(item, "returned")}
                              >
                                Zwróć do rekrutera
                              </Button>
                            </div>
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>

                {remaining.length === 0 ? (
                  <p className="text-sm text-muted-foreground">W tej rekrutacji nic więcej nie czeka.</p>
                ) : null}

                <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                  {current ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setReturning(current.stage_id);
                        setReturnReason("");
                      }}
                    >
                      <Undo2 className="size-3.5" aria-hidden />
                      Nie da się wrzucić — zwróć do rekrutera
                    </Button>
                  ) : (
                    <span />
                  )}
                  <Button
                    size="sm"
                    variant={remaining.length === 0 ? "primary" : "outline"}
                    disabled={!nextJob}
                    onClick={() => nextJob && setJobId(nextJob.job_id)}
                  >
                    {nextJob ? `Następna rekrutacja: ${nextJob.job_title} →` : "Następna rekrutacja →"}
                  </Button>
                </div>
              </section>
            ) : null}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
