"use client";

// Finanse → Rozliczenia → „E-faktury (Peppol)” (plan Nordei N2): stan e-faktury
// przy każdej fakturze z KSeF do odbiorcy w sieci Peppol, „Wyślij” pojedynczo
// i dla zaznaczonych, plik UBL do pobrania. Tryb testowy wysyła na adres
// testowy odbiorcy; automatyczna wysyłka tylko po włączeniu przez Finanse.
import { Download, RefreshCw, Send, Settings2 } from "lucide-react";
import { useMemo, useState } from "react";

import { QueryStateNotice, StatusDot, type StatusDotTone } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import {
  fetchEinvoiceUbl,
  useEinvoices,
  useRefreshEinvoices,
  useSendEinvoices,
  type EinvoiceRow,
  type EinvoiceStatus,
} from "@/lib/api/client-einvoices";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { EinvoiceSettingsPanel } from "./EinvoiceSettingsPanel";
import { money, monthLabel } from "./format";

export const EINVOICE_STATUS: Record<EinvoiceStatus, { label: string; tone: StatusDotTone }> = {
  waiting_xml: { label: "Czeka na XML z KSeF", tone: "neutral" },
  waiting_receiver: { label: "Brak adresu Peppol", tone: "warning" },
  invalid: { label: "Błąd walidacji", tone: "danger" },
  ready: { label: "Do wysłania", tone: "info" },
  sent: { label: "Wysłana", tone: "info" },
  delivered: { label: "Doręczona", tone: "success" },
  rejected: { label: "Odrzucona", tone: "danger" },
  skipped: { label: "Bez e-faktury", tone: "neutral" },
};
const SENDABLE: readonly EinvoiceStatus[] = ["ready", "rejected"];
/** Kolejność liczników i wierszy: najpierw to, co wymaga działania. */
const ORDER: readonly EinvoiceStatus[] = ["invalid", "rejected", "ready", "waiting_receiver", "waiting_xml", "sent", "delivered", "skipped"];

function when(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Warsaw" });
}

function StatusCell({ row }: { row: EinvoiceRow }) {
  const meta = EINVOICE_STATUS[row.status];
  const blocking = row.problems.filter((p) => p.flag !== "warning");
  return (
    <div className="min-w-0">
      <StatusDot tone={meta.tone}>{meta.label}</StatusDot>
      {row.status === "invalid" || row.status === "skipped"
        ? (blocking.length ? blocking : row.problems).slice(0, 3).map((p) => (
            <span key={`${p.rule}-${p.location}`} className={cn(CALM_SUBLINE, row.status === "invalid" && "text-destructive")}>
              {p.rule && !p.rule.includes("_") ? `${p.rule}: ` : ""}
              {p.text}
            </span>
          ))
        : null}
      {row.status === "rejected" && row.delivery_detail ? (
        <span className={cn(CALM_SUBLINE, "text-destructive")}>{row.delivery_detail}</span>
      ) : null}
      {row.status === "ready" && row.tested_at ? (
        <span className={CALM_SUBLINE}>Test doręczony {when(row.tested_at)}</span>
      ) : null}
    </div>
  );
}

export function EinvoicesView({ clientId, month, canWrite }: { clientId: number; month: string; canWrite: boolean }) {
  const query = useEinvoices(clientId, month);
  const send = useSendEinvoices();
  const refresh = useRefreshEinvoices();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [filter, setFilter] = useState<EinvoiceStatus | null>(null);

  const rows = useMemo(
    () =>
      [...(query.data?.rows ?? [])]
        .filter((r) => filter == null || r.status === filter)
        .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || b.issue_date.localeCompare(a.issue_date)),
    [query.data, filter],
  );
  const sendable = rows.filter((r) => SENDABLE.includes(r.status));
  const picked = sendable.filter((r) => selected.has(r.id));

  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać e-faktur.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const data = query.data;
  const test = data.mode === "test";

  async function onSend(targets: EinvoiceRow[]) {
    if (!targets.length) return;
    const ok = await askConfirm({
      title: targets.length === 1 ? `Wysłać e-fakturę ${targets[0].invoice_number}?` : `Wysłać ${targets.length} e-faktur?`,
      description: test
        ? "Tryb testowy: plik pójdzie na adres testowy odbiorcy w sieci Peppol, nie do księgowości klienta."
        : "Tryb produkcyjny: e-faktura trafi do systemu klienta i nie da się jej wycofać. Zmiana kwoty wymaga korekty w KSeF.",
      confirmLabel: "Wyślij",
      variant: test ? "default" : "destructive",
    });
    if (!ok) return;
    try {
      let sent = 0;
      const failed: string[] = [];
      for (let i = 0; i < targets.length; i += 25) {
        const res = await send.mutateAsync(targets.slice(i, i + 25).map((r) => r.id));
        sent += res.sent;
        failed.push(...res.failed.map((f) => `${f.invoice_number}: ${f.reason}`));
      }
      setSelected(new Set());
      if (failed.length) showError(`Wysłano ${sent}, nie wyszło ${failed.length}. ${failed.slice(0, 2).join(" · ")}`);
      else showSuccess(`Wysłano ${sent} ${sent === 1 ? "e-fakturę" : "e-faktur"}${test ? " na adres testowy" : ""}.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wysłać e-faktur."));
    }
  }

  async function onRefresh() {
    try {
      const res = await refresh.mutateAsync();
      showSuccess(`Sprawdzono ${res.checked} faktur, nowe stany doręczenia: ${res.refreshed}.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się odświeżyć stanów."));
    }
  }

  async function onDownload(row: EinvoiceRow) {
    try {
      downloadBlob(await fetchEinvoiceUbl(row.id), `${row.invoice_number.replace(/[^\w.-]+/g, "_")}.xml`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się przygotować pliku UBL."));
    }
  }

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const allPicked = sendable.length > 0 && picked.length === sendable.length;

  return (
    <div className="space-y-3">
      {confirmDialog}
      <section className="rounded-xl border border-primary/25 bg-primary/[0.04] p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold">
              E-faktury Peppol za {monthLabel(month)}
              <StatusDot tone={test ? "warning" : "success"}>{test ? "Tryb testowy" : "Produkcja"}</StatusDot>
              <StatusDot tone={data.auto_send ? "info" : "neutral"}>
                {data.auto_send ? "Wysyłka automatyczna" : "Wysyłka ręczna"}
              </StatusDot>
            </h2>
            <p className="max-w-[78ch] text-xs text-muted-foreground">
              Faktura wystawiona w EBI24 wraca z KSeF, a NEXUS robi z niej e-fakturę Peppol BIS 3 i sprawdza ją regułami
              EN16931 i Peppol. {test ? "W trybie testowym wysyłka idzie na adres testowy odbiorcy." : "Wysyłka idzie do systemu klienta."}
            </p>
            {!data.provider_ready ? (
              <p className="mt-1 text-xs text-warning-muted-foreground">{data.provider_detail}</p>
            ) : null}
            <div className="mt-1.5 flex flex-wrap gap-1" role="group" aria-label="Filtr stanu e-faktury">
              {ORDER.filter((s) => data.counts[s] || s === filter).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={filter === s}
                  onClick={() => setFilter(filter === s ? null : s)}
                  className={cn(
                    "rounded-md border px-2 py-0.5 text-xs pointer-coarse:min-h-9",
                    filter === s ? "border-primary bg-primary/10 text-foreground" : "border-transparent text-muted-foreground hover:border-border",
                  )}
                >
                  {EINVOICE_STATUS[s].label}: <span className="font-semibold tabular-nums text-foreground">{data.counts[s] ?? 0}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="outline" disabled={refresh.isPending} onClick={onRefresh}>
              <RefreshCw aria-hidden className={cn("size-3.5", refresh.isPending && "animate-spin")} /> Odśwież stany
            </Button>
            {canWrite ? (
              <Button
                size="sm"
                disabled={!data.provider_ready || picked.length === 0 || send.isPending}
                onClick={() => onSend(picked)}
              >
                <Send aria-hidden className="size-3.5" /> Wyślij zaznaczone ({picked.length})
              </Button>
            ) : null}
            {canWrite ? (
              <Button size="sm" variant="ghost" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((v) => !v)}>
                <Settings2 aria-hidden className="size-3.5" /> Ustawienia
              </Button>
            ) : null}
          </div>
        </div>
      </section>
      {settingsOpen ? <EinvoiceSettingsPanel onClose={() => setSettingsOpen(false)} /> : null}
      {rows.length === 0 ? (
        <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
          {filter ? `Żadna faktura nie ma stanu „${EINVOICE_STATUS[filter].label}”.` : "W tym miesiącu nie ma faktur do odbiorców w sieci Peppol."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full min-w-[920px] table-fixed text-[13px]">
            <colgroup>
              <col className="w-9" />
              <col className="w-[19%]" />
              <col className="w-[17%]" />
              <col className="w-[12%]" />
              <col />
              <col className="w-[17%]" />
              <col className="w-[132px]" />
            </colgroup>
            <thead className="border-b bg-muted/40 text-left">
              <tr>
                <th className="px-3 py-1.5">
                  {canWrite ? (
                    <input
                      type="checkbox"
                      aria-label="Zaznacz wszystkie do wysłania"
                      checked={allPicked}
                      disabled={sendable.length === 0}
                      onChange={() => setSelected(allPicked ? new Set() : new Set(sendable.map((r) => r.id)))}
                      className="size-3.5 accent-primary"
                    />
                  ) : null}
                </th>
                <th className={cn(CALM_HEAD, "px-2 py-1.5")}>Faktura</th>
                <th className={cn(CALM_HEAD, "px-2 py-1.5")}>Odbiorca</th>
                <th className={cn(CALM_HEAD, "px-2 py-1.5 text-right")}>Brutto</th>
                <th className={cn(CALM_HEAD, "px-2 py-1.5")}>E-faktura</th>
                <th className={cn(CALM_HEAD, "px-2 py-1.5")}>Wysyłka</th>
                <th className="px-3 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const canSend = SENDABLE.includes(r.status);
                return (
                  <tr key={r.id} className={cn(CALM_ROW, "align-top")}>
                    <td className="px-3 py-2">
                      {canWrite && canSend ? (
                        <input
                          type="checkbox"
                          aria-label={`Zaznacz ${r.invoice_number}`}
                          checked={selected.has(r.id)}
                          onChange={() => toggle(r.id)}
                          className="size-3.5 accent-primary"
                        />
                      ) : null}
                    </td>
                    <td className="px-2 py-2">
                      <span className="block truncate font-medium">{r.invoice_number}</span>
                      <span className={CALM_SUBLINE}>
                        {[
                          r.kind === "correction" ? (r.document_type === "credit_note" ? "Korekta (nota)" : "Korekta") : null,
                          r.issue_date,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </td>
                    <td className="px-2 py-2">
                      <span className="block truncate">{r.receiver_name}</span>
                      {r.buyer_name && r.buyer_name !== r.receiver_name ? (
                        <span className={cn(CALM_SUBLINE, "truncate")}>{r.buyer_name}</span>
                      ) : null}
                    </td>
                    <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{money(r.gross_amount, r.currency)}</td>
                    <td className="px-2 py-2">
                      <StatusCell row={r} />
                    </td>
                    <td className="px-2 py-2 text-xs">
                      {r.sent_at ? (
                        <>
                          <span className="block">
                            {r.target === "test" ? "Test" : "Produkcja"} · {when(r.sent_at)}
                          </span>
                          <span className={cn(CALM_SUBLINE, "truncate font-mono text-[11px]")}>{r.recipient}</span>
                        </>
                      ) : (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        {canWrite && canSend ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={!data.provider_ready || send.isPending}
                            onClick={() => onSend([r])}
                          >
                            Wyślij
                          </Button>
                        ) : null}
                        {r.status !== "waiting_xml" && r.status !== "skipped" && r.status !== "waiting_receiver" ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs"
                            aria-label={`Pobierz UBL ${r.invoice_number}`}
                            onClick={() => onDownload(r)}
                          >
                            <Download aria-hidden className="size-3.5" /> UBL
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
