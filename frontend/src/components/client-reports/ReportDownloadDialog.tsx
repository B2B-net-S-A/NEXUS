"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileCheck2, TriangleAlert } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CALENDAR_RHYTHMS,
  downloadReport,
  downloadRunFile,
  getPeriods,
  getPreview,
  getRuns,
  markSent,
  shortDate,
  type ReportDefinition,
  type ReportRun,
} from "@/lib/api/client-reports";
import { ReportStateDot } from "./ReportStateDot";

const FIELD = "h-9 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground";

interface ReportDownloadDialogProps {
  definition: ReportDefinition | null;
  /** Okres z kalendarza; bez niego — najbliższy niezałatwiony. */
  initialPeriod?: string | null;
  canEdit: boolean;
  onClose: () => void;
}

function todayIso(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

/** Jedno okno dla każdego raportu: okres, podgląd, plik, wysyłka, historia. */
export function ReportDownloadDialog({ definition, initialPeriod, canEdit, onClose }: ReportDownloadDialogProps) {
  if (!definition) return null;
  return <DialogInner key={definition.id} definition={definition} initialPeriod={initialPeriod} canEdit={canEdit} onClose={onClose} />;
}

function DialogInner({
  definition,
  initialPeriod,
  canEdit,
  onClose,
}: {
  definition: ReportDefinition;
  initialPeriod?: string | null;
  canEdit: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const periodic = CALENDAR_RHYTHMS.includes(definition.rhythm);
  const hasGenerator = Boolean(definition.generator_key);
  const periods = useQuery({
    queryKey: ["client-report-periods", definition.id],
    queryFn: () => getPeriods(definition.id),
    enabled: periodic,
  });
  // Termin „do ustalenia” wskazuje okres bieżący (niezamknięty) — wtedy
  // domyślnie ostatni zamknięty okres z listy.
  const [period, setPeriod] = useState<string>(
    initialPeriod ?? (definition.next.state && definition.next.state !== "no_date" ? definition.next.period_key ?? "" : ""),
  );
  useEffect(() => {
    if (!period && periods.data?.length) {
      setPeriod((periods.data.find((p) => p.closed) ?? periods.data[0]).key);
    }
  }, [period, periods.data]);
  const preview = useQuery({
    queryKey: ["client-report-preview", definition.id, period],
    queryFn: () => getPreview(definition.id, period),
    enabled: hasGenerator && Boolean(period),
    retry: false,
  });
  const runs = useQuery({ queryKey: ["client-report-runs", definition.id], queryFn: () => getRuns(definition.id) });

  const [downloading, setDownloading] = useState(false);
  const [sending, setSending] = useState(false);
  const [sentOn, setSentOn] = useState(todayIso());
  const [sentTo, setSentTo] = useState(definition.recipient ?? "");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["client-report-runs", definition.id] });
    void queryClient.invalidateQueries({ queryKey: ["client-report-periods", definition.id] });
    void queryClient.invalidateQueries({ queryKey: ["client-reports", definition.client_id] });
    void queryClient.invalidateQueries({ queryKey: ["client-reports-calendar"] });
  };

  const download = async () => {
    setDownloading(true);
    try {
      await downloadReport(definition.id, period, `${definition.name} ${period}.xlsx`);
      refresh();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać raportu."));
    } finally {
      setDownloading(false);
    }
  };

  const lastGenerated: ReportRun | undefined = runs.data?.find((r) => r.status === "generated" && r.period_key === period);
  const send = useMutation({
    mutationFn: () =>
      markSent(definition.id, {
        period_key: periodic ? period : sentOn,
        sent_on: sentOn,
        sent_to: sentTo.trim() || undefined,
        note: note.trim() || undefined,
        run_id: !file && lastGenerated ? lastGenerated.id : undefined,
        file,
      }),
    onSuccess: () => {
      showSuccess("Zapisano wysyłkę w historii.");
      setSending(false);
      setFile(null);
      setNote("");
      refresh();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać wysyłki.")),
  });

  const selected = periods.data?.find((p) => p.key === period);
  const sourceLine = [definition.source_ref, definition.recipient ? `dla: ${definition.recipient}` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{definition.name}</DialogTitle>
          <DialogDescription>{sourceLine || definition.due_label}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {periodic ? (
            <div className="grid grid-cols-[1fr_auto] items-end gap-3 text-sm">
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">Okres</span>
                <select id="report-period" className={FIELD} value={period} onChange={(e) => setPeriod(e.target.value)}>
                  {(periods.data ?? []).map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.label}
                      {p.due ? ` — termin ${shortDate(p.due, p.key)}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              {selected ? <ReportStateDot state={selected.state} /> : null}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Raport {definition.rhythm === "event" ? "zdarzeniowy" : "na żądanie"} — zapisz wysyłkę z datą.</p>
          )}

          {hasGenerator ? (
            <section className="space-y-2" aria-live="polite">
              <h3 className="text-xs font-semibold text-muted-foreground">
                Podgląd{preview.data ? `: ${preview.data.period_label}` : ""}
              </h3>
              {preview.isPending && period ? <p className="text-sm text-muted-foreground">Liczę z danych NEXUSA…</p> : null}
              {preview.isError ? (
                <p className="rounded-md bg-destructive/10 px-2 py-1.5 text-sm text-destructive">
                  {apiErrorMessage(preview.error, "Nie udało się policzyć podglądu.")}
                </p>
              ) : null}
              {preview.isSuccess ? (
                <>
                  <table className="w-full text-sm">
                    <tbody className="divide-y divide-border tabular-nums">
                      {preview.data.lines.map((line) => (
                        <tr key={line.label} className="h-8">
                          <td className="py-0.5">{line.label}</td>
                          <td className={`py-0.5 text-right ${line.strong ? "font-semibold text-foreground" : ""}`}>{line.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {preview.data.checks.map((check) => (
                    <p key={check} className="flex items-start gap-1.5 rounded-md bg-warning/10 px-2 py-1.5 text-xs text-foreground">
                      <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
                      {check}
                    </p>
                  ))}
                </>
              ) : null}
            </section>
          ) : (
            <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              Ten raport przygotowuje się poza NEXUSEM. Po wysłaniu wgraj plik, żeby został w historii.
            </p>
          )}

          {sending ? (
            <section className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-2">
              <h3 className="text-xs font-semibold text-muted-foreground sm:col-span-2">Wysłałeś raport ze swojej poczty — zapisz ślad</h3>
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">Data wysłania</span>
                <Input id="report-sent-on" type="date" max={todayIso()} value={sentOn} onChange={(e) => setSentOn(e.target.value)} />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">Do kogo</span>
                <Input id="report-sent-to" value={sentTo} maxLength={255} onChange={(e) => setSentTo(e.target.value)} />
              </label>
              <label className="space-y-1 sm:col-span-2">
                <span className="text-xs text-muted-foreground">
                  Plik, który poszedł {lastGenerated && !file ? `(bez wyboru: ${lastGenerated.file_name})` : "(opcjonalnie)"}
                </span>
                <Input id="report-sent-file" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
              <label className="space-y-1 sm:col-span-2">
                <span className="text-xs text-muted-foreground">Uwaga</span>
                <Input id="report-sent-note" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
              </label>
              <div className="flex justify-end gap-2 sm:col-span-2">
                <Button variant="ghost" size="sm" onClick={() => setSending(false)}>
                  Anuluj
                </Button>
                <Button size="sm" onClick={() => send.mutate()} loading={send.isPending} disabled={!sentOn || (periodic && !period)}>
                  Zapisz wysyłkę
                </Button>
              </div>
            </section>
          ) : null}

          <section className="rounded-lg border border-border">
            <h3 className="border-b border-border px-3 py-2 text-xs font-semibold text-muted-foreground">Historia</h3>
            {runs.isError ? (
              <p className="px-3 py-2 text-sm text-destructive">{apiErrorMessage(runs.error, "Nie udało się wczytać historii.")}</p>
            ) : null}
            {runs.isSuccess && runs.data.length === 0 ? (
              <p className="px-3 py-2 text-sm text-muted-foreground">Brak wysyłek w NEXUSIE — pierwsza zapisana wysyłka założy historię.</p>
            ) : null}
            {runs.isSuccess && runs.data.length > 0 ? (
              <ul className="max-h-40 divide-y divide-border overflow-y-auto text-sm">
                {runs.data.map((run) => (
                  <li key={run.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
                    <span className="min-w-0">
                      <span className="text-foreground">{run.period_key}</span>{" "}
                      <span className="text-muted-foreground">
                        {run.status === "sent"
                          ? `wysłany ${shortDate(run.sent_at?.slice(0, 10) ?? null, "x")}${run.sent_to ? ` do: ${run.sent_to}` : ""}${run.sent_by ? ` · ${run.sent_by}` : ""}`
                          : `wygenerowany${run.generated_by ? ` · ${run.generated_by}` : ""}`}
                      </span>
                    </span>
                    {run.has_file ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => downloadRunFile(run).catch((error) => showError(apiErrorMessage(error, "Nie udało się pobrać pliku.")))}
                      >
                        Plik
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        </DialogBody>
        <DialogFooter className="gap-2">
          {canEdit && definition.status === "active" && !sending ? (
            <Button variant="outline" onClick={() => setSending(true)}>
              <FileCheck2 className="h-4 w-4" aria-hidden="true" /> Oznacz jako wysłany…
            </Button>
          ) : null}
          {hasGenerator ? (
            <Button onClick={download} loading={downloading} disabled={!period || preview.isError}>
              <Download className="h-4 w-4" aria-hidden="true" /> Pobierz XLSX
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
